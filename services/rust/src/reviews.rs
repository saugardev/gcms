use crate::{
    ApiError, ApiResult,
    auth::{self, AppState, User},
    valid_component, valid_id,
};
use axum::{
    Extension, Json,
    extract::{
        Path, State, WebSocketUpgrade,
        ws::{CloseFrame, Message, WebSocket},
    },
    http::{HeaderMap, StatusCode, header},
    response::{IntoResponse, Response},
};
use serde::Deserialize;
use serde_json::{Value, json};
use std::time::Duration;
use tokio::sync::broadcast;
use tokio_postgres::GenericClient;

const REVIEW_SQL: &str = "SELECT jsonb_build_object('component_id',c.id,'version',c.review_version,'decisions',COALESCE((SELECT jsonb_agg(jsonb_build_object('group_id',d.group_id,'candidate_name',d.candidate_name,'decision',d.decision,'updated_by',jsonb_build_object('id',u.id,'name',u.name),'updated_at',d.updated_at) ORDER BY d.group_id) FROM candidate_decisions d JOIN app_users u ON u.id=d.updated_by WHERE d.analysis_id=c.analysis_id AND d.component_id=c.id),'[]'::jsonb)) FROM components c WHERE c.analysis_id=$1";
async fn current<C: GenericClient + Sync>(
    client: &C,
    analysis: &str,
    component: &str,
) -> Result<Value, ApiError> {
    let row = client
        .query_one(
            &format!("{REVIEW_SQL} AND c.id=$2"),
            &[&analysis, &component],
        )
        .await?;
    Ok(row.get(0))
}
pub async fn snapshot(State(state): State<AppState>, Path(id): Path<String>) -> ApiResult {
    valid_id(&id)?;
    let client = state.pool.get().await?;
    if client
        .query_opt("SELECT id FROM analyses WHERE id=$1", &[&id])
        .await?
        .is_none()
    {
        return Err(ApiError(StatusCode::NOT_FOUND, "Analysis not found."));
    }
    let rows = client
        .query(
            &format!("{REVIEW_SQL} AND c.review_version>0 ORDER BY c.id"),
            &[&id],
        )
        .await?;
    Ok(Json(
        json!({"analysis_id":id,"reviews":rows.into_iter().map(|r|r.get::<_,Value>(0)).collect::<Vec<_>>()}),
    ))
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Decision {
    decision: String,
    expected_version: i64,
}
pub async fn decide(
    State(state): State<AppState>,
    Extension(user): Extension<User>,
    Path((id, component, group)): Path<(String, String, String)>,
    Json(input): Json<Decision>,
) -> Result<Response, ApiError> {
    valid_id(&id)?;
    valid_component(&component)?;
    if !matches!(
        input.decision.as_str(),
        "accepted" | "rejected" | "unreviewed"
    ) || input.expected_version < 0
        || group.is_empty()
        || group.len() > 256
    {
        return Err(ApiError(
            StatusCode::BAD_REQUEST,
            "Invalid candidate decision.",
        ));
    }
    let mut client = state.pool.get().await?;
    let tx = client.transaction().await?;
    let row = tx
        .query_opt(
            "SELECT data,review_version FROM components WHERE analysis_id=$1 AND id=$2 FOR UPDATE",
            &[&id, &component],
        )
        .await?
        .ok_or(ApiError(StatusCode::NOT_FOUND, "Component not found."))?;
    let data: Value = row.get(0);
    let candidates: Vec<_> = data["component"]["candidates"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|c| c["group_id"].as_str() == Some(&group))
        .collect();
    if candidates.len() != 1 {
        return Err(ApiError(
            StatusCode::NOT_FOUND,
            "Candidate not found or not uniquely identified.",
        ));
    }
    let candidate_name = candidates[0]["identities"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|i| i["name"].as_str())
        .collect::<Vec<_>>()
        .join(" / ");
    let before = current(&*tx, &id, &component).await?;
    if row.get::<_, i64>(1) != input.expected_version {
        return Ok((StatusCode::CONFLICT, Json(json!({"error":{"message":"Another reviewer changed this component. Review the latest decisions and try again."},"review":before}))).into_response());
    }
    let old = before["decisions"]
        .as_array()
        .unwrap()
        .iter()
        .find(|d| d["group_id"] == group)
        .and_then(|d| d["decision"].as_str())
        .unwrap_or("unreviewed");
    if old == input.decision {
        return Ok(Json(json!({"review":before,"event":null})).into_response());
    }
    if input.decision == "accepted" {
        tx.execute("UPDATE candidate_decisions SET decision='unreviewed',updated_by=$3,updated_at=now() WHERE analysis_id=$1 AND component_id=$2 AND decision='accepted'", &[&id,&component,&user.id]).await?;
    }
    tx.execute("INSERT INTO candidate_decisions(analysis_id,component_id,group_id,candidate_name,decision,updated_by) VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT(analysis_id,component_id,group_id) DO UPDATE SET decision=EXCLUDED.decision,updated_by=EXCLUDED.updated_by,updated_at=now()", &[&id,&component,&group,&candidate_name,&input.decision,&user.id]).await?;
    tx.execute(
        "UPDATE components SET review_version=review_version+1 WHERE analysis_id=$1 AND id=$2",
        &[&id, &component],
    )
    .await?;
    let review = current(&*tx, &id, &component).await?;
    let mut event = json!({"type":"review_changed","analysis_id":id,"component_id":component,"group_id":group,"candidate_name":candidate_name,"decision":input.decision,"actor":{"id":user.id,"name":user.name},"review":review});
    let row = tx.query_one("INSERT INTO review_events(analysis_id,component_id,actor_id,data) VALUES ($1,$2,$3,$4) RETURNING id,created_at::text", &[&id,&component,&user.id,&json!({"event":event,"before":before})]).await?;
    event["event_id"] = json!(row.get::<_, i64>(0).to_string());
    event["occurred_at"] = json!(row.get::<_, String>(1));
    tx.commit().await?;
    let _ = state.events.send(event.clone());
    Ok(Json(json!({"review":review,"event":event})).into_response())
}

pub async fn events(
    State(state): State<AppState>,
    Path(id): Path<String>,
    headers: HeaderMap,
    ws: WebSocketUpgrade,
) -> Result<Response, ApiError> {
    if headers.get(header::ORIGIN).and_then(|v| v.to_str().ok()) != Some(&state.origin) {
        return Err(ApiError(
            StatusCode::FORBIDDEN,
            "WebSocket origin is not allowed.",
        ));
    }
    let token = auth::cookie_token(&headers)
        .ok_or_else(auth::unauthorized)?
        .to_owned();
    auth::user(&state.pool, &token).await?;
    valid_id(&id)?;
    if state
        .pool
        .get()
        .await?
        .query_opt("SELECT id FROM analyses WHERE id=$1", &[&id])
        .await?
        .is_none()
    {
        return Err(ApiError(StatusCode::NOT_FOUND, "Analysis not found."));
    }
    // Subscribe before telling the client to fetch its snapshot; versions resolve races.
    let receiver = state.events.subscribe();
    Ok(ws
        .max_message_size(1024)
        .max_frame_size(1024)
        .on_upgrade(move |socket| stream(socket, state, id, token, receiver)))
}
async fn send(socket: &mut WebSocket, message: Message) -> bool {
    matches!(
        tokio::time::timeout(Duration::from_secs(5), socket.send(message)).await,
        Ok(Ok(()))
    )
}
async fn stream(
    mut socket: WebSocket,
    state: AppState,
    id: String,
    token: String,
    mut receiver: broadcast::Receiver<Value>,
) {
    if !send(
        &mut socket,
        Message::Text(json!({"type":"ready"}).to_string().into()),
    )
    .await
    {
        return;
    }
    let mut heartbeat = tokio::time::interval(Duration::from_secs(15));
    let mut last_seen = tokio::time::Instant::now();
    loop {
        tokio::select! {
            message = socket.recv() => {
                match message {
                    Some(Ok(Message::Pong(_))) => last_seen=tokio::time::Instant::now(),
                    Some(Ok(Message::Ping(_))) => {},
                    Some(Ok(Message::Close(_))) | None | Some(Err(_)) => break,
                    _ => break, // This socket only delivers events; writes use authenticated HTTP.
                }
            }
            _ = heartbeat.tick() => {
                if auth::user(&state.pool,&token).await.is_err() {
                    let _=send(&mut socket,Message::Close(Some(CloseFrame{code:1008,reason:"Session ended".into()}))).await;
                    break;
                }
                if last_seen.elapsed()>Duration::from_secs(45) || !send(&mut socket,Message::Ping(Vec::new().into())).await { break; }
            }
            event = receiver.recv() => {
                if auth::user(&state.pool,&token).await.is_err() {
                    let _=send(&mut socket,Message::Close(Some(CloseFrame{code:1008,reason:"Session ended".into()}))).await;
                    break;
                }
                let event = match event {
                    Ok(event) if event["analysis_id"]==id => event,
                    Ok(_) => continue,
                    Err(broadcast::error::RecvError::Lagged(_)) => json!({"type":"resync"}),
                    Err(_) => break,
                };
                if !send(&mut socket,Message::Text(event.to_string().into())).await { break; }
            }
        }
    }
}
