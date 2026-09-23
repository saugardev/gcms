# Saved-analysis service

The Rust HTTP service reads saved Rust analyses from PostgreSQL. Read requests
never invoke Python or repeat processing.

## Run locally

Copy `.env.example` to `.env`, choose a password and use it in both variables.
Run `docker compose up -d --wait`, or use an existing PostgreSQL 16+ database.
From the repository root:

```sh
set -a
source .env
set +a
cargo build --release --locked --manifest-path services/rust/Cargo.toml \
  --no-default-features --features server --bin gcms-api
services/rust/target/release/gcms-api migrate
services/rust/target/release/gcms-api import artifacts/review-rust.json
services/rust/target/release/gcms-api serve
```

The saved report is local data, not bundled with the repository. The importer
validates the report and atomically stores components, candidates and review
traces. Repeating an import leaves the existing result unchanged. The API binds
to `127.0.0.1:8001` by default and returns `Server-Timing` and `Cache-Control: no-store`.

## Rust read API

| Method | Path | Response |
| --- | --- | --- |
| GET | `/health` | Database connectivity |
| GET | `/v1/analyses` | Latest 100 saved sample summaries |
| GET | `/v1/analyses/{id}` | Metadata, chromatogram and compact peak summaries |
| GET | `/v1/analyses/{id}/components/{component_id}` | Original component, candidates, spectra and optional review annotation |
| GET | `/v1/analyses/{id}/spectra?components=component-0001,component-0002` | Selected component spectra in retention-time order, without candidate/review payloads |


## Checks

```sh
cargo test --locked --manifest-path services/rust/Cargo.toml \
  --no-default-features --features server --bin gcms-api
python3 scripts/check_workspace.py artifacts/review-rust.json
```

The HTTP check requires a running service and the imported report. It verifies
every stored component, candidate, spectrum and review trace against the report.
