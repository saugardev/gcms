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
   It also indexes sparse ion traces by native mass for fast chromatogram reads.
   It does not rerun peak detection, matching or stability checks. Repeated imports
   leave the stored data unchanged. Missing acquisitions leave Scan controls disabled.
   For scans imported before ion extraction was added, run `migrate`, then
   `services/rust/target/release/gcms-api index-ions <analysis-id>` once. This reads
   the stored scans directly from PostgreSQL and needs no acquisition file.
3. In a second terminal:

   ```sh
   pnpm --dir app install --frozen-lockfile
   pnpm --dir app dev
   ```

Open **http://127.0.0.1:3000**. The UI authenticates `/api/*` requests and forwards them to the Rust service at
`http://127.0.0.1:8001/v1/*`. To change that address, copy `app/.env.example` to
`app/.env.local` and set `GCMS_API_URL` before starting or building Next.js.
For a production UI build, run `pnpm --dir app build` then `pnpm --dir app start`.
Both services bind to loopback by default. Register at `/register`, then sign in.
Set `APP_ORIGIN` to the exact browser origin in both service environments (default
`http://127.0.0.1:3000`); production uses HTTPS and Secure cookies. Changing the
browser hostname or port requires updating this setting. Remote hosting still
needs HTTPS termination and database TLS setup.
The existing live Python deployment is a separate application.

## Analyst interactions

- The sidebar's Project selector chooses the saved sample for both Dashboard and
  Accepted components. Sign out is at the bottom of the sidebar. The top bar keeps
  Reload sample and the notifications box available on both pages.
- Accepted components lists shared analyst acceptances in retention-time order,
  with area, reviewer and decision time. Search by candidate, component or reviewer;
  View component opens that specific accepted candidate in the dashboard. The list
  updates when a teammate accepts, rejects or clears a decision.
- Chromatogram and mirrored mass spectrum stay open alongside the component and
  candidate lists on desktop. Lists scroll independently; small screens stack.
- Click a detected peak or table row to inspect it. Ctrl/Cmd-click toggles a
  component; Shift-click selects a range in the current table order. Checkboxes
  also support multiple selection. Selected peaks are highlighted in the table and
  chromatogram. Selecting several components opens stacked spectra with a shared
  m/z axis; larger selections scroll inside the spectrum panel. Spectra are not summed.
  Click a spectrum or its heading to make it active and inspect its library search results.
  The Library match tab returns to the active component's mirrored reference view.
- Arrow keys move through table rows; Shift-arrow extends the selection. Home/End
  move to the first/last shown row, Ctrl/Cmd+A selects shown rows, and Escape clears
  selection. Filters preserve the selection and report an active peak outside them.
  Links preserve the active analysis/peak; multiple selection lasts until reload.
- Use Select mode to drag across a group of peaks. Hold Ctrl/Cmd or Shift to add
  a range. Switch to Zoom mode to magnify a region. Pan, focus the selected peak
  or group, or reset the chromatogram. Focusing a reviewed component uses its saved detailed peak trace;
  the overview uses the saved preview. Raw and corrected traces can be compared.
- Search names, CAS numbers or component IDs; filter identification status and parameter
  sensitivity together, and sort by retention time, area or match score. Click an
  identification/parameter sensitivity badge or “Labels & shortcuts” for explanations. These
  controls inspect and filter saved labels; they do not change analysis results.
- Ambiguous components show “Why ambiguous?” above their candidates, using the
  saved warning flags, close-match count, score gap and ambiguity margin. Conflicting
  reference identities are explained separately. Missing reasons are reported explicitly.
- Select a library candidate to change the lower half of the mirrored spectrum.
  Component and reference spectra show relative abundance (%), with each spectrum's
  base peak (strongest ion) normalized to 100%. The TIC and EIC show abundance in
  instrument counts. Area (%) is the share of reported component-ion areas, not
  concentration. Match score is spectral similarity on a 0–1 scale, not a NIST match factor.
- Drag across a mass spectrum to zoom m/z in all comparison lanes together.
  Zoom/pan buttons work with the keyboard; Reset m/z or double-click restores the range.
- Switch the chromatogram to Scan mode and click any acquisition time to see the
  nearest stored raw scan. The cursor marks its actual time and the chromatogram
  pans to keep a newly requested scan in view. Scan spectrum also offers
  previous/next scan buttons and a retention-time input. Raw spectra preserve native
  mass values (1/20 Da), include background and are separate from reconstructed
  component spectra. The candidates panel identifies the component it belongs to.
- Click an ion in the raw spectrum, or enter its m/z, to overlay its extracted ion
  chromatogram (EIC). The ± tolerance selects an inclusive mass window (default
  0.5 Da; 0 selects the exact native mass). Counts are summed from stored ion traces
  on the same scale as the TIC. Hide Raw TIC to inspect the ion alone; × clears it.
  Selecting an ion does not change the active component or identify a compound.
- The info icon after each card title opens an explanation. Click outside or
  press Escape to close it.
- Reload sample makes fresh HTTP reads. The small time beside it measures the
  analysis response, including transfer and JSON parsing, not processing time.

When imported, the raw chromatogram uses every acquisition scan. The corrected
overview remains the saved report preview; focusing a single reviewed peak uses
its saved detailed corrected trace. Select/Zoom clicks choose the nearest detected
component; Scan clicks choose the nearest raw acquisition scan. Proposals, similarity scores and area
percentages retain the original scientific limitations in [science.md](science.md).

## Accounts and shared analyst decisions

Authentication adapts the browser-session flow from `saugardev/saas-template`:
Argon2id passwords, random opaque sessions with only SHA-256 token hashes stored
in PostgreSQL, a 30-day expiry, and logout revocation. Next.js keeps the token in
an HttpOnly, SameSite=Lax cookie and forwards it to Rust using `Authorization:
Session <token>`. Production cookies are Secure. The token never reaches browser
JavaScript. Login/registration allow 10 attempts per normalized email per 15
minutes, with at most two concurrent password hashes. These limits are in memory.
Email addresses are unverified login identifiers; no recovery emails or social
login are implemented.

Registration is open. **Every registered account can read all analyses and edit
shared decisions.** There are no private workspaces or ownership-based filters.
All saved-data routes require a live session; `/health` remains public.

Each candidate has Accept, Reject, and Clear decision controls. One candidate
**group** per component can be accepted. Accepting another clears the previous
acceptance without rejecting other candidates. A group containing several
identities remains a group; analyst acceptance does not resolve its identities.
Decisions persist independently of the immutable engine results, including
reviewer name, time, a component version, and append-only change history in
`review_events`. Re-importing the same saved report preserves these decisions.
Stale writes return 409 with current review state, allowing a deliberate retry.

WebSockets stream committed decisions at `/ws/analyses/{id}` through Next.js to
Rust. The handshake checks the session cookie and exact Origin; token URLs are
never used. Connected sessions receive updated decisions and a dismissible
notification in the top-right box with the reviewer, candidate, and a View component action. Selection,
zoom, filters, and spectral comparison remain personal. Reconnects fetch a fresh
review snapshot, merged by component version. Revoked/expired sockets close on
the next event or 15-second heartbeat. Database failures fail closed.

Run **one Rust API process**: live fan-out and authentication throttling are
process-local. Add PostgreSQL notifications and shared throttling before running
multiple replicas. Reverse proxies must forward WebSocket upgrades to Next.js;
the pinned Next.js server forwards the dedicated WebSocket rewrite to Rust.

## Rust API

| Method | Path | Response |
| --- | --- | --- |
| GET | `/health` | Database connectivity |
| POST | `/v1/auth/register` | Name/email/password → user, opaque session and expiry (server-to-server only) |
| POST | `/v1/auth/login` | Email/password → user, new session and expiry |
| POST | `/v1/auth/logout` | Revoke current session |
| GET | `/v1/me` | Current authenticated user |
| GET | `/v1/analyses/{id}/reviews` | Lightweight shared review snapshot |
| PUT | `/v1/analyses/{id}/components/{component_id}/candidates/{group_id}/decision` | `{decision: accepted/rejected/unreviewed, expected_version: number}` → review and event |
| GET (upgrade) | `/v1/analyses/{id}/events` | Authenticated, Origin-checked WebSocket |
| GET | `/v1/analyses` | Latest 100 saved sample summaries |
| GET | `/v1/analyses/{id}` | Metadata, chromatogram and compact peak summaries |
| GET | `/v1/analyses/{id}/components/{component_id}` | Original component, candidates, spectra and optional review annotation |
| GET | `/v1/analyses/{id}/spectra?components=component-0001,component-0002` | Selected component spectra in retention-time order, without candidate/review payloads |
| GET | `/v1/analyses/{id}/scans?time_seconds=2820` | Nearest raw scan (earlier scan on ties; endpoints outside the acquisition) |
| GET | `/v1/analyses/{id}/scans?index=0` | Raw scan by zero-based acquisition index |
| GET | `/v1/analyses/{id}/ions?mz=83&tolerance=0.5` | Ion counts for every raw scan within m/z ± tolerance (0–5 Da; default 0.5) |

IDs are SHA-256 hashes of the canonical saved report. The database stores large
component details separately, so opening a sample does not download every
spectrum. Component details are fetched once per selection and cached in the
browser until reload. The API always queries PostgreSQL; it has no file fallback
or processing endpoint. Overview responses also contain `raw_chromatogram` (null
until imported). Comparison spectra use one batch query. Raw time lookup uses
indexed neighbors rather than scanning the acquisition. Ion extraction reads only
the indexed mass channels in the requested window, returning zero for scans with
no matching ions; it returns 409 if ion traces have not been indexed.
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

The final check requires the imported sample, running Rust API, and a valid
`GCMS_SESSION_TOKEN` environment variable (obtain it using the Rust login endpoint;
do not put it in command arguments or source files). It compares
every stored component, candidate spectrum and review trace to the saved report,
checks batch comparison, read-only routes and errors, and measures ten local reads
per endpoint. Optional `--acquisition` verifies every raw timestamp and total ion
count, plus exact spectra and nearest-time lookup across the acquisition. It also
compares four full ion chromatograms, including exact masses, tolerance boundaries
and absent ions, against the acquisition.
No analysis is rerun. Keep the PostgreSQL data volume to retain imported results.

Authentication/collaboration integration check (uses an isolated, disposable
PostgreSQL schema and starts its own Rust API; never edits existing analyses):

```sh
cargo build --locked --manifest-path services/rust/Cargo.toml \
  --no-default-features --features server --bin gcms-api
uv run --with websockets python scripts/check_collaboration.py
```

Requires `DATABASE_URL`, `psql`, and schema-create permissions. Covers authentication,
expiry/revocation, throttling, shared review writes, optimistic concurrency, audit
history, immutable reports, two WebSocket clients, and reconnect snapshots.
