mod auth;
mod import;
mod reviews;
mod scans;

use axum::{
    Json, Router,
    extract::{DefaultBodyLimit, Path, Query, State},
    http::{StatusCode, header},
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::{get, post, put},
};
use deadpool_postgres::{Config, Pool, Runtime};
use serde_json::{Value, json};
use std::{
    collections::HashMap,
    env,
    error::Error,
    time::{Duration, Instant},
};
use tokio_postgres::NoTls;

#[derive(Debug)]
struct ApiError(StatusCode, &'static str);
impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        (self.0, Json(json!({"error":{"message":self.1}}))).into_response()
    }
}
impl From<tokio_postgres::Error> for ApiError {
    fn from(error: tokio_postgres::Error) -> Self {
        eprintln!("Database query failed: {error}");
        Self(
            StatusCode::SERVICE_UNAVAILABLE,
            "Saved analyses are temporarily unavailable.",
        )
    }
}
impl From<deadpool_postgres::PoolError> for ApiError {
    fn from(error: deadpool_postgres::PoolError) -> Self {
        eprintln!("Database connection failed: {error}");
        Self(
            StatusCode::SERVICE_UNAVAILABLE,
            "Saved analyses are temporarily unavailable.",
        )
    }
}
type ApiResult = Result<Json<Value>, ApiError>;

async fn timing(request: axum::extract::Request, next: Next) -> Response {
    let start = Instant::now();
    let mut response = next.run(request).await;
    response.headers_mut().insert(
        "server-timing",
        format!("db_api;dur={:.3}", start.elapsed().as_secs_f64() * 1000.0)
            .parse()
            .unwrap(),
    );
    response
        .headers_mut()
        .insert(header::CACHE_CONTROL, "no-store".parse().unwrap());
    response
}

async fn health(State(pool): State<Pool>) -> ApiResult {
    pool.get().await?.simple_query("SELECT 1").await?;
    Ok(Json(json!({"status":"ok","storage":"postgresql"})))
}

async fn analyses(State(pool): State<Pool>) -> ApiResult {
    let client = pool.get().await?;
    let rows = client.query("SELECT id, sample_name, imported_at::text, jsonb_array_length(peaks) FROM analyses ORDER BY imported_at DESC, id LIMIT 100",&[]).await?;
    Ok(Json(
        json!({"analyses":rows.into_iter().map(|r|json!({"id":r.get::<_,String>(0),"sample_name":r.get::<_,String>(1),"imported_at":r.get::<_,String>(2),"component_count":r.get::<_,i32>(3)})).collect::<Vec<_>>()}),
    ))
}

fn valid_id(id: &str) -> Result<(), ApiError> {
    if id.len() == 64 && id.bytes().all(|b| b.is_ascii_hexdigit()) {
        Ok(())
    } else {
        Err(ApiError(StatusCode::BAD_REQUEST, "Invalid analysis ID."))
    }
}

async fn analysis(State(pool): State<Pool>, Path(id): Path<String>) -> ApiResult {
    valid_id(&id)?;
    let client = pool.get().await?;
    let row = client
        .query_opt(
            "SELECT a.metadata, a.chromatogram, a.peaks, a.imported_at::text, r.chromatogram FROM analyses a LEFT JOIN raw_acquisitions r ON r.analysis_id=a.id WHERE a.id = $1",
            &[&id],
        )
        .await?
        .ok_or(ApiError(StatusCode::NOT_FOUND, "Analysis not found."))?;
    Ok(Json(
        json!({"id":id,"metadata":row.get::<_,Value>(0),"chromatogram":row.get::<_,Value>(1),"peaks":row.get::<_,Value>(2),"imported_at":row.get::<_,String>(3),"raw_chromatogram":row.get::<_,Option<Value>>(4)}),
    ))
}

async fn component(
    State(pool): State<Pool>,
    Path((id, component)): Path<(String, String)>,
) -> ApiResult {
    valid_id(&id)?;
    valid_component(&component)?;
    let client = pool.get().await?;
    let row = client
        .query_opt(
            "SELECT data FROM components WHERE analysis_id = $1 AND id = $2",
            &[&id, &component],
        )
        .await?
        .ok_or(ApiError(StatusCode::NOT_FOUND, "Component not found."))?;
    Ok(Json(row.get(0)))
}

fn valid_component(component: &str) -> Result<(), ApiError> {
    if !component
        .strip_prefix("component-")
        .is_some_and(|s| s.len() == 4 && s.bytes().all(|b| b.is_ascii_digit()))
    {
        return Err(ApiError(StatusCode::BAD_REQUEST, "Invalid component ID."));
    }
    Ok(())
}

async fn spectra(
    State(pool): State<Pool>,
    Path(id): Path<String>,
    Query(query): Query<HashMap<String, String>>,
) -> ApiResult {
    valid_id(&id)?;
    let ids: Vec<&str> = query
        .get("components")
        .map(|s| s.split(',').collect())
        .unwrap_or_default();
    if ids.is_empty() || ids.len() > 1000 {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            "Choose 1–1000 components.",
        ));
    }
    for component in &ids {
        valid_component(component)?;
    }
    let mut ids = ids;
    ids.sort_unstable();
    ids.dedup();
    let client = pool.get().await?;
    let rows = client.query("SELECT jsonb_build_object('component_id',id,'apex_seconds',data->'component'->'apex_seconds','spectrum',data->'component'->'spectrum') FROM components WHERE analysis_id=$1 AND id=ANY($2) ORDER BY (data->'component'->>'apex_seconds')::double precision,id", &[&id,&ids]).await?;
    if rows.len() != ids.len() {
        return Err(ApiError(
            StatusCode::NOT_FOUND,
            "A selected component was not found.",
        ));
    }
    Ok(Json(
        json!({"spectra":rows.iter().map(|r|r.get::<_,Value>(0)).collect::<Vec<_>>()}),
    ))
}

async fn scan(
    State(pool): State<Pool>,
    Path(id): Path<String>,
    Query(query): Query<HashMap<String, String>>,
) -> ApiResult {
    valid_id(&id)?;
    let invalid = || {
        ApiError(
            StatusCode::BAD_REQUEST,
            "Specify one nonnegative scan index or finite time_seconds.",
        )
    };
    if query.len() != 1 {
        return Err(invalid());
    }
    let client = pool.get().await?;
    let row = if let Some(value) = query.get("index") {
        let index = value.parse::<i32>().ok().filter(|v|*v>=0).ok_or_else(invalid)?;
        client.query_opt("SELECT scan_index,time_seconds,spectrum FROM raw_scans WHERE analysis_id=$1 AND scan_index=$2", &[&id,&index]).await?
    } else {
        let time = query.get("time_seconds").and_then(|v|v.parse::<f64>().ok()).filter(|v|v.is_finite() && *v>=0.0).ok_or_else(invalid)?;
        // Two indexed neighbors; never sort every scan to find the closest time.
        client.query_opt("SELECT * FROM ((SELECT scan_index,time_seconds,spectrum FROM raw_scans WHERE analysis_id=$1 AND time_seconds <= $2 ORDER BY time_seconds DESC LIMIT 1) UNION ALL (SELECT scan_index,time_seconds,spectrum FROM raw_scans WHERE analysis_id=$1 AND time_seconds > $2 ORDER BY time_seconds LIMIT 1)) neighbors ORDER BY abs(time_seconds-$2),scan_index LIMIT 1", &[&id,&time]).await?
    }.ok_or(ApiError(StatusCode::NOT_FOUND, "Raw scan not found. Import the matching acquisition first."))?;
    Ok(Json(
        json!({"scan_index":row.get::<_,i32>(0),"time_seconds":row.get::<_,f64>(1),"spectrum":row.get::<_,Value>(2)}),
    ))
}

async fn ion_trace(
    State(pool): State<Pool>,
    Path(id): Path<String>,
    Query(query): Query<HashMap<String, String>>,
) -> ApiResult {
    valid_id(&id)?;
    let invalid = || {
        ApiError(
            StatusCode::BAD_REQUEST,
            "Specify m/z from 0 to 3276.75 and tolerance from 0 to 5 Da.",
        )
    };
    let mz = query
        .get("mz")
        .and_then(|v| v.parse::<f64>().ok())
        .ok_or_else(invalid)?;
    let tolerance = query
        .get("tolerance")
        .map(|v| v.parse::<f64>())
        .transpose()
        .map_err(|_| invalid())?
        .unwrap_or(0.5);
    let (low, high) = scans::mass_window(mz, tolerance).ok_or_else(invalid)?;
    let client = pool.get().await?;
    let row = client.query_opt("SELECT jsonb_array_length(chromatogram->'time_seconds'), EXISTS(SELECT 1 FROM raw_ion_traces WHERE analysis_id=$1) FROM raw_acquisitions WHERE analysis_id=$1", &[&id]).await?.ok_or(ApiError(StatusCode::NOT_FOUND,"Raw acquisition not found."))?;
    if !row.get::<_, bool>(1) {
        return Err(ApiError(
            StatusCode::CONFLICT,
            "Index the stored ions before extracting a chromatogram.",
        ));
    }
    let mut intensity = vec![0_u64; row.get::<_, i32>(0) as usize];
    let rows = client
        .query(
            "SELECT points FROM raw_ion_traces WHERE analysis_id=$1 AND mass_key BETWEEN $2 AND $3",
            &[&id, &low, &high],
        )
        .await?;
    let corrupt = || {
        ApiError(
            StatusCode::INTERNAL_SERVER_ERROR,
            "The stored ion trace is invalid.",
        )
    };
    for row in rows {
        let points: Vec<(usize, u64)> =
            serde_json::from_value(row.get::<_, Value>(0)).map_err(|_| corrupt())?;
        for (index, value) in points {
            let target = intensity.get_mut(index).ok_or_else(corrupt)?;
            *target = target.checked_add(value).ok_or_else(corrupt)?;
        }
    }
    Ok(Json(
        json!({"mz":mz,"tolerance":tolerance,"intensity":intensity}),
    ))
}

async fn import_file(pool: &Pool, path: &str) -> Result<(), Box<dyn Error>> {
    if std::fs::metadata(path)?.len() > 64 * 1024 * 1024 {
        return Err("Report exceeds 64 MiB".into());
    }
    let report = import::parse(&std::fs::read(path)?)?;
    let mut client = pool.get().await?;
    let tx = client.transaction().await?;
    let added = tx.execute("INSERT INTO analyses (id,sample_name,metadata,chromatogram,peaks) VALUES ($1,$2,$3,$4,$5) ON CONFLICT (id) DO NOTHING",&[&report.id,&report.name,&report.metadata,&report.chromatogram,&report.peaks]).await?;
    if added == 1 {
        let statement = tx
            .prepare("INSERT INTO components (analysis_id,id,data) VALUES ($1,$2,$3)")
            .await?;
        for (id, data) in &report.components {
            tx.execute(&statement, &[&report.id, id, data]).await?;
        }
    }
    tx.commit().await?;
    println!(
        "{}",
        json!({"id":report.id,"imported":added==1,"components":report.components.len()})
    );
    Ok(())
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<String> = env::args().skip(1).collect();
    if !matches!(
        args.first().map(String::as_str),
        Some("serve" | "migrate" | "import" | "import-scans" | "index-ions")
    ) || args.len()
        != match args.first().map(String::as_str) {
            Some("import" | "index-ions") => 2,
            Some("import-scans") => 3,
            _ => 1,
        }
    {
        return Err("Usage: gcms-api migrate | import <saved-rust-report.json> | import-scans <analysis-id> <data.ms> | index-ions <analysis-id> | serve".into());
    }
    let mut config = Config::new();
    config.url =
        Some(env::var("DATABASE_URL").map_err(|_| "Set DATABASE_URL before starting the service")?);
    let mut pool_config = deadpool_postgres::PoolConfig::new(8);
    pool_config.timeouts.wait = Some(Duration::from_secs(5));
    pool_config.timeouts.create = Some(Duration::from_secs(5));
    pool_config.timeouts.recycle = Some(Duration::from_secs(5));
    config.pool = Some(pool_config);
    let pool = config.create_pool(Some(Runtime::Tokio1), NoTls)?;
    match args[0].as_str() {
        "migrate" => {
            pool.get()
                .await?
                .batch_execute(include_str!("../schema.sql"))
                .await?;
            println!("Database schema ready.");
        }
        "import" => import_file(&pool, &args[1]).await?,
        "import-scans" => {
            scans::import(&pool, &args[1], &args[2]).await?;
            scans::index_ions(&pool, &args[1]).await?;
        }
        "index-ions" => scans::index_ions(&pool, &args[1]).await?,
        _ => {
            // Fail startup if the database is unavailable or migrations have not run.
            pool.get()
                .await?
                .simple_query("SELECT id FROM analyses LIMIT 0")
                .await?;
            pool.get().await?.simple_query("SELECT token_hash FROM app_sessions LIMIT 0; SELECT review_version FROM components LIMIT 0; SELECT id FROM review_events LIMIT 0").await?;
            let state = auth::AppState::new(
                pool,
                env::var("APP_ORIGIN").unwrap_or_else(|_| "http://127.0.0.1:3000".into()),
            )?;
            let router = app_router(state);
            let address = env::var("GCMS_BIND").unwrap_or_else(|_| "127.0.0.1:8001".into());
            let listener = tokio::net::TcpListener::bind(&address).await?;
            println!("GC-MS saved-analysis API listening on http://{address}");
            axum::serve(listener, router)
                .with_graceful_shutdown(async {
                    let _ = tokio::signal::ctrl_c().await;
                })
                .await?;
        }
    }
    Ok(())
}

fn app_router(state: auth::AppState) -> Router {
    let protected = Router::new()
        .route("/v1/me", get(auth::me))
        .route("/v1/auth/logout", post(auth::logout))
        .route("/v1/analyses", get(analyses))
        .route("/v1/analyses/{id}", get(analysis))
        .route("/v1/analyses/{id}/components/{component}", get(component))
        .route("/v1/analyses/{id}/spectra", get(spectra))
        .route("/v1/analyses/{id}/scans", get(scan))
        .route("/v1/analyses/{id}/ions", get(ion_trace))
        .route("/v1/analyses/{id}/reviews", get(reviews::snapshot))
        .route(
            "/v1/analyses/{id}/components/{component}/candidates/{group}/decision",
            put(reviews::decide),
        )
        .route_layer(middleware::from_fn_with_state(
            state.clone(),
            auth::require_session,
        ));
    Router::new()
        .merge(protected)
        .route("/health", get(health))
        .route("/v1/auth/register", post(auth::register))
        .route("/v1/auth/login", post(auth::login))
        .route("/v1/analyses/{id}/events", get(reviews::events))
        .fallback(|| async { ApiError(StatusCode::NOT_FOUND, "Endpoint not found.") })
        .layer(DefaultBodyLimit::max(16 * 1024))
        .layer(middleware::from_fn(timing))
        .with_state(state)
}
