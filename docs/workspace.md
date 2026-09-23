# Saved-analysis workspace

The Next.js app reads a previously generated Rust report from PostgreSQL through
an independent Rust HTTP service. Opening a sample or selecting a component
never invokes Python, reads the acquisition, or runs the analysis again.

## Layout

```text
app/                         Next.js UI (src/app, src/components, src/lib)
services/rust/               Rust API, PostgreSQL schema, importer, numerical kernels
services/python/gcms/        Existing Python API, CLI, reader and research baseline
```

Root `pyproject.toml` and `uv.lock` continue to manage the Python package and its
existing test/deployment commands. The Rust server builds without Python using
`--no-default-features --features server`.

## Run locally

Requires Node.js 20.9+, pnpm 10, the pinned Rust toolchain, and PostgreSQL 16+.
Run commands from the repository root.

1. Copy `.env.example` to `.env`, choose a password and use it in both variables.
   Start PostgreSQL with `docker compose up -d --wait`. An existing local
   PostgreSQL instance works too: point `DATABASE_URL` at its database.
2. Build the Rust server and prepare the database:

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

   `artifacts/review-rust.json` is the current sample's existing saved Rust review.
   It is local data, not a bundled repository asset. Substitute your own saved
   Rust analysis (`schema_version: "1.0"`) or review (`"review-1.0"`) report when
   working on another checkout. The import validates and saves it in one
   transaction. Repeating the same import returns `imported: false` and leaves
   the existing result unchanged. `migrate` is also safe to repeat.

   To enable individual raw scans, import the original acquisition once using
   the ID returned by the report import:

   ```sh
   services/rust/target/release/gcms-api import-scans <analysis-id> /path/to/sample.D/data.ms
   ```

   This Rust command checks the file's SHA-256 against the saved report, then
   stores native m/z/intensity pairs and the full raw TIC atomically in PostgreSQL.
   It does not rerun peak detection, matching or stability checks. Repeated imports
   leave the stored data unchanged. Missing acquisitions leave Scan controls disabled.
3. In a second terminal:

   ```sh
   pnpm --dir app install --frozen-lockfile
   pnpm --dir app dev
   ```

Open **http://127.0.0.1:3000**. The UI proxies `/api/*` to the Rust service at
`http://127.0.0.1:8001/v1/*`. To change that address, copy `app/.env.example` to
`app/.env.local` and set `GCMS_API_URL` before starting or building Next.js.
For a production UI build, run `pnpm --dir app build` then `pnpm --dir app start`.
Both services bind to loopback by default. This local version has no login;
remote hosting needs the deployment's access controls and database TLS setup.
The existing live Python deployment is a separate application.

## Analyst interactions

- Chromatogram and mirrored mass spectrum stay open alongside the component and
  candidate lists on desktop. Lists scroll independently; small screens stack.
- Click a detected peak or table row to inspect it. Ctrl/Cmd-click toggles a
  component; Shift-click selects a range in the current table order. Checkboxes
  also support multiple selection. Selected peaks are highlighted in the table and
  chromatogram. Selecting several components opens stacked spectra with a shared
  m/z axis; larger selections scroll inside the spectrum panel. Spectra are not summed.
  Click a spectrum or its heading to make it active and inspect its saved library candidates.
  The Library match tab returns to the active component's mirrored reference view.
- Arrow keys move through table rows; Shift-arrow extends the selection. Home/End
  move to the first/last shown row, Ctrl/Cmd+A selects shown rows, and Escape clears
  selection. Filters preserve the selection and report an active peak outside them.
  Links preserve the active analysis/peak; multiple selection lasts until reload.
- Use Select mode to drag across a group of peaks. Hold Ctrl/Cmd or Shift to add
  a range. Switch to Zoom mode to magnify a region. Pan, focus the selected peak
  or group, or reset the chromatogram. Focusing a reviewed component uses its saved detailed peak trace;
  the overview uses the saved preview. Raw and corrected traces can be compared.
- Search names, CAS numbers or component IDs; filter assignment and processing
  stability together, and sort by retention time, area or similarity. Click an
  assignment/stability badge or “Labels & shortcuts” for explanations. These
  controls inspect and filter saved labels; they do not change analysis results.
- Select a library candidate to change the lower half of the mirrored spectrum.
  Component and reference intensities are independently normalized to 100%.
- Drag across a mass spectrum to zoom m/z in all comparison lanes together.
  Zoom/pan buttons work with the keyboard; Reset m/z or double-click restores the range.
- Switch the chromatogram to Scan mode and click any acquisition time to see the
  nearest stored raw scan. The cursor marks its actual time and the chromatogram
  pans to keep a newly requested scan in view. Raw scan also offers
  previous/next scan buttons and a retention-time input. Raw spectra preserve native
  mass values (1/20 Da), include background and are separate from reconstructed
  component spectra. The candidates panel identifies the component it belongs to.
- Reload sample makes fresh HTTP reads. The small time beside it measures the
  analysis response, including transfer and JSON parsing, not processing time.

When imported, the raw chromatogram uses every acquisition scan. The corrected
overview remains the saved report preview; focusing a single reviewed peak uses
its saved detailed corrected trace. Select/Zoom clicks choose the nearest detected
component; Scan clicks choose the nearest raw acquisition scan. Proposals, similarity scores and area
percentages retain the original scientific limitations in [science.md](science.md).

## Rust read API

| Method | Path | Response |
| --- | --- | --- |
| GET | `/health` | Database connectivity |
| GET | `/v1/analyses` | Latest 100 saved sample summaries |
| GET | `/v1/analyses/{id}` | Metadata, chromatogram and compact peak summaries |
| GET | `/v1/analyses/{id}/components/{component_id}` | Original component, candidates, spectra and optional review annotation |
| GET | `/v1/analyses/{id}/spectra?components=component-0001,component-0002` | Selected component spectra in retention-time order, without candidate/review payloads |
| GET | `/v1/analyses/{id}/scans?time_seconds=2820` | Nearest raw scan (earlier scan on ties; endpoints outside the acquisition) |
| GET | `/v1/analyses/{id}/scans?index=0` | Raw scan by zero-based acquisition index |

IDs are SHA-256 hashes of the canonical saved report. The database stores large
component details separately, so opening a sample does not download every
spectrum. Component details are fetched once per selection and cached in the
browser until reload. The API always queries PostgreSQL; it has no file fallback
or processing endpoint. Overview responses also contain `raw_chromatogram` (null
until imported). Comparison spectra use one batch query. Raw time lookup uses
indexed neighbors rather than scanning the acquisition.
Responses include `Server-Timing: db_api;dur=…` in
milliseconds and `Cache-Control: no-store`. Invalid IDs return 400, missing records
404, and database failures 503. Migrations/import are CLI commands only.

## Checks

```sh
cargo test --locked --manifest-path services/rust/Cargo.toml \
  --no-default-features --features server --bin gcms-api
pnpm --dir app test
pnpm --dir app check
pnpm --dir app build
python3 scripts/check_workspace.py artifacts/review-rust.json --acquisition /path/to/sample.D/data.ms
```

The final check requires the imported sample and running Rust API. It compares
every stored component, candidate spectrum and review trace to the saved report,
checks batch comparison, read-only routes and errors, and measures ten local reads
per endpoint. Optional `--acquisition` verifies every raw timestamp and total ion
count, plus exact spectra and nearest-time lookup across the acquisition.
No analysis is rerun. Keep the PostgreSQL data volume to retain imported results.
