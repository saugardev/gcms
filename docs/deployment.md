# Jio deployment

[Documentation](README.md) · [Project](../README.md)

Pushing `main` or running **Deploy GCMS** in GitHub Actions deploys the exact
commit to the dedicated Jio VM. The public port **8000** serves the Next.js
workspace from `app/`, including sign-in, Dashboard and Accepted components.
The old Python dashboard is no longer the production entry point.

The VM uses the **gcms** Jio account, Large size (4 vCPU, 8 GiB). GitHub needs
secrets `JIO_API_KEY` and `JIO_SSH_KEY`, plus variable `JIO_VM_ID`. The SSH secret
is the VM's generated `id_ed25519` private key. Optional `JIO_ENDPOINT` selects
a different endpoint. Credentials stay in GitHub secrets and private local state.
When using the local deployment account, unset any ambient `JIO_API_KEY` that
belongs to another account and select its isolated `JIO_STATE_DIR`.

## Runtime and saved data

- `gcms.service`: production Next.js on `127.0.0.1:8000`, published by Jio over HTTPS.
- `gcms-api.service`: Rust saved-analysis API on `127.0.0.1:8001`, including sessions,
  candidate decisions and WebSocket events. Only the UI port is published.
- PostgreSQL 16: persistent Ubuntu service, stored outside application releases.
  Rust connects through `/var/run/postgresql` using peer authentication as the
  `gcms` OS/database user. No database password or public database port is needed.

Node.js 24.21.0 (checksum verified), pnpm 10.32.1 and Rust 1.94.0 are pinned.
The Rust API builds with `--no-default-features --features server`; production
requests do not run Python. The Next.js proxy forwards authenticated reads and
writes; its WebSocket rewrite connects to the same Rust API. Both services get
`APP_ORIGIN` from Jio's actual HTTPS URL before the build.

Provision these private inputs over authenticated SSH before the first deployment:

```text
/var/lib/gcms/data/review-rust.json
/var/lib/gcms/data/sample.D/data.ms
```

Use the existing saved Rust report for the current sample. Deployment migrates
the schema, imports the report and imports/indexes matching raw scans. These
commands are idempotent, preserve analyst decisions and do not rerun the analysis.
The importer verifies the acquisition hash against the report. Inputs are not
committed or included in Actions artifacts. Existing library files are preserved.

Production has its own database: accounts and analyst decisions created on a
local development machine are not automatically copied. Register at `/register`.
All registered users share the saved analyses and analyst decisions.

## Checks and rollback

Each release runs Rust server tests, frontend tests and a Next.js production
build before activation. The database gets a restricted `pg_dump` backup under
`/var/lib/gcms/backups` before migrations. Schema changes must remain backward
compatible: automatic service rollback does **not** restore the database.

The deploy switches `/var/lib/gcms/current`, restarts both application services,
and runs `deploy/check.sh`. Checks require the Next.js `/health` response to
identify `mafer-workspace`, the exact revision, and a healthy Rust/PostgreSQL
connection. They also verify sign-in/registration pages, a built static asset,
protected data and allowed/rejected request origins. The same checks run against
the public HTTPS URL, so a healthy legacy Python dashboard cannot pass deployment.
A local activation/check failure restores the previous symlink and both unit
files, including when migrating from the old Python service.

Releases and backups remain on the VM for rollback. Monitor disk use and copy
backups off the VM for disaster recovery. The installed revision is recorded in
`/var/lib/gcms/deployed-revision`. The Actions summary links to the app and reports
whether deployment checks passed.

```sh
jio ports "$JIO_VM_ID"
jio exec "$JIO_VM_ID" 'sudo -n systemctl status gcms gcms-api postgresql --no-pager'
jio exec "$JIO_VM_ID" 'sudo -n journalctl -u gcms -u gcms-api -n 80 --no-pager'
GIT_REF=$(git rev-parse HEAD) bash deploy/jio.sh
```
