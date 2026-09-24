// Session/password flow adapted from saugardev/saas-template (MIT).
// See THIRD_PARTY_NOTICES.md. Only browser sessions are needed here.
use crate::{ApiError, ApiResult};
use argon2::{Argon2, PasswordHash, PasswordHasher, PasswordVerifier};
use axum::{
    Extension, Json,
    extract::{FromRef, Request, State},
    http::{HeaderMap, StatusCode, header},
    middleware::Next,
    response::{IntoResponse, Response},
};
use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
use deadpool_postgres::Pool;
use rand::RngCore;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};
use tokio::sync::{Semaphore, broadcast};
use tokio_postgres::GenericClient;

#[derive(Clone)]
pub struct AppState {
    pub pool: Pool,
    pub origin: String,
    // ponytail: one API process; use PostgreSQL notifications when adding replicas.
    pub events: broadcast::Sender<Value>,
    hashing: Arc<Semaphore>,
    attempts: Arc<Mutex<HashMap<String, (Instant, u32)>>>,
}
impl FromRef<AppState> for Pool {
    fn from_ref(state: &AppState) -> Self {
        state.pool.clone()
    }
}
impl AppState {
    pub fn new(pool: Pool, origin: String) -> Result<Self, &'static str> {
        let uri: axum::http::Uri = origin.parse().map_err(|_| "Invalid APP_ORIGIN")?;
        if !matches!(uri.scheme_str(), Some("http" | "https"))
            || uri.authority().is_none_or(|a| a.as_str().contains('@'))
            || !matches!(uri.path_and_query().map(|p| p.as_str()), None | Some("/"))
        {
            return Err("APP_ORIGIN must be an http(s) origin without a path");
        }
        Ok(Self {
            pool,
            origin: origin.trim_end_matches('/').to_owned(),
            events: broadcast::channel(256).0,
            hashing: Arc::new(Semaphore::new(2)),
            attempts: Arc::new(Mutex::new(HashMap::new())),
        })
    }
    fn throttle(&self, email: &str) -> Result<(), ApiError> {
        let mut attempts = self.attempts.lock().map_err(|_| unavailable())?;
        attempts.retain(|_, (time, _)| time.elapsed() < Duration::from_secs(900));
        if attempts.len() >= 10_000 {
            return Err(limited());
        }
        let attempt = attempts
            .entry(email.to_owned())
            .or_insert((Instant::now(), 0));
        if attempt.1 >= 10 {
            return Err(limited());
        }
        attempt.1 += 1;
        Ok(())
    }
    async fn password(&self, password: String, hash: Option<String>) -> Result<String, ApiError> {
        let permit = self
            .hashing
            .clone()
            .try_acquire_owned()
            .map_err(|_| limited())?;
        tokio::task::spawn_blocking(move || {
            let _permit = permit;
            if let Some(hash) = hash {
                let parsed = PasswordHash::new(&hash).map_err(|_| unavailable())?;
                if Argon2::default()
                    .verify_password(password.as_bytes(), &parsed)
                    .is_err()
                {
                    return Err(unauthorized());
                }
                Ok(hash)
            } else {
                Argon2::default()
                    .hash_password(password.as_bytes())
                    .map(|h| h.to_string())
                    .map_err(|_| unavailable())
            }
        })
        .await
        .map_err(|_| unavailable())?
    }
}
fn limited() -> ApiError {
    ApiError(
        StatusCode::TOO_MANY_REQUESTS,
        "Too many sign-in attempts. Try again later.",
    )
}
fn unavailable() -> ApiError {
    ApiError(
        StatusCode::SERVICE_UNAVAILABLE,
        "Authentication is temporarily unavailable.",
    )
}
pub fn unauthorized() -> ApiError {
    ApiError(StatusCode::UNAUTHORIZED, "Sign in again to continue.")
}
pub fn token() -> String {
    let mut bytes = [0_u8; 32];
    rand::rng().fill_bytes(&mut bytes);
    URL_SAFE_NO_PAD.encode(bytes)
}
pub fn hash_token(token: &str) -> Vec<u8> {
    Sha256::digest(token.as_bytes()).to_vec()
}
pub fn session_token(headers: &HeaderMap) -> Option<&str> {
    let (scheme, token) = headers
        .get(header::AUTHORIZATION)?
        .to_str()
        .ok()?
        .split_once(' ')?;
    (scheme.eq_ignore_ascii_case("session") && valid_token(token)).then_some(token)
}
fn valid_token(token: &str) -> bool {
    token.len() == 43
        && token
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
}
pub fn cookie_token(headers: &HeaderMap) -> Option<&str> {
    headers
        .get(header::COOKIE)?
        .to_str()
        .ok()?
        .split(';')
        .find_map(|part| {
            let (key, value) = part.trim().split_once('=')?;
            (key == "mafer_session" && valid_token(value)).then_some(value)
        })
}
#[derive(Clone, Debug, Serialize)]
pub struct User {
    pub id: String,
    pub name: String,
    pub email: String,
}
pub async fn user(pool: &Pool, token: &str) -> Result<User, ApiError> {
    if !valid_token(token) {
        return Err(unauthorized());
    }
    let row = pool.get().await?.query_opt(
        "SELECT u.id,u.name,u.email FROM app_sessions s JOIN app_users u ON u.id=s.user_id WHERE s.token_hash=$1 AND s.revoked_at IS NULL AND s.expires_at>now()",
        &[&hash_token(token)]).await?.ok_or_else(unauthorized)?;
    Ok(User {
        id: row.get(0),
        name: row.get(1),
        email: row.get(2),
    })
}
pub async fn require_session(
    State(state): State<AppState>,
    mut request: Request,
    next: Next,
) -> Response {
    let result = match session_token(request.headers()) {
        Some(token) => user(&state.pool, token).await,
        None => Err(unauthorized()),
    };
    match result {
        Ok(user) => {
            request.extensions_mut().insert(user);
            next.run(request).await
        }
        Err(error) => error.into_response(),
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Credentials {
    email: String,
    password: String,
    name: Option<String>,
}
fn email(value: &str) -> Result<String, ApiError> {
    let email = value.trim().to_ascii_lowercase();
    let parts: Vec<_> = email.split('@').collect();
    if email.len() > 254
        || parts.len() != 2
        || parts.iter().any(|s| s.is_empty())
        || email.chars().any(char::is_whitespace)
    {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            "Enter a valid email address.",
        ));
    }
    Ok(email)
}
fn password_length(value: &str) -> Result<(), ApiError> {
    if !(8..=1024).contains(&value.len()) {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            "Use a password between 8 and 1024 bytes.",
        ));
    }
    Ok(())
}
async fn issue_session<C: GenericClient + Sync>(client: &C, user: &User) -> ApiResult {
    let token = token();
    let row = client.query_one("INSERT INTO app_sessions(token_hash,user_id,expires_at) VALUES ($1,$2,now()+interval '30 days') RETURNING extract(epoch from expires_at)::double precision", &[&hash_token(&token), &user.id]).await?;
    Ok(Json(
        json!({"session_token":token,"expires_at":row.get::<_,f64>(0),"user":user}),
    ))
}
pub async fn register(
    State(state): State<AppState>,
    Json(request): Json<Credentials>,
) -> Result<(StatusCode, Json<Value>), ApiError> {
    let email = email(&request.email)?;
    password_length(&request.password)?;
    let name = request.name.as_deref().unwrap_or("").trim();
    if !(2..=100).contains(&name.chars().count()) {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            "Name must contain 2–100 characters.",
        ));
    }
    state.throttle(&email)?;
    let hash = state.password(request.password, None).await?;
    let user = User {
        id: token(),
        name: name.to_owned(),
        email,
    };
    let mut client = state.pool.get().await?;
    let tx = client.transaction().await?;
    if tx.execute("INSERT INTO app_users(id,email,name,password_hash) VALUES ($1,$2,$3,$4) ON CONFLICT(email) DO NOTHING", &[&user.id,&user.email,&user.name,&hash]).await? == 0 {
        return Err(ApiError(StatusCode::CONFLICT, "An account already exists for this email."));
    }
    let response = issue_session(&*tx, &user).await?;
    tx.commit().await?;
    Ok((StatusCode::CREATED, response))
}
pub async fn login(State(state): State<AppState>, Json(request): Json<Credentials>) -> ApiResult {
    let email = email(&request.email)?;
    password_length(&request.password)?;
    state.throttle(&email)?;
    let client = state.pool.get().await?;
    let row = client
        .query_opt(
            "SELECT id,name,password_hash FROM app_users WHERE email=$1",
            &[&email],
        )
        .await?;
    // Unknown accounts still perform Argon2 work, just like a wrong password.
    state
        .password(request.password, row.as_ref().map(|r| r.get(2)))
        .await
        .map_err(|error| {
            if error.0 == StatusCode::UNAUTHORIZED {
                ApiError(StatusCode::UNAUTHORIZED, "Email or password is incorrect.")
            } else {
                error
            }
        })?;
    let row = row.ok_or(ApiError(
        StatusCode::UNAUTHORIZED,
        "Email or password is incorrect.",
    ))?;
    issue_session(
        &**client,
        &User {
            id: row.get(0),
            name: row.get(1),
            email,
        },
    )
    .await
}
pub async fn me(Extension(user): Extension<User>) -> Json<Value> {
    Json(json!({"user":user}))
}
pub async fn logout(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Result<StatusCode, ApiError> {
    let token = session_token(&headers).ok_or_else(unauthorized)?;
    state
        .pool
        .get()
        .await?
        .execute(
            "UPDATE app_sessions SET revoked_at=now() WHERE token_hash=$1",
            &[&hash_token(token)],
        )
        .await?;
    let _ = state.events.send(json!({"type":"session_changed"}));
    Ok(StatusCode::NO_CONTENT)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn identifiers_and_tokens() {
        assert_eq!(email(" Test@Example.com ").unwrap(), "test@example.com");
        for bad in ["a@@b", "@b", "a@", "a b@c"] {
            assert!(email(bad).is_err());
        }
        let a = token();
        let b = token();
        assert_ne!(a, b);
        assert!(valid_token(&a));
        assert_eq!(hash_token(&a).len(), 32);
        assert!(!valid_token("bad"));
        assert!(password_length(&"x".repeat(1025)).is_err());
    }
}
