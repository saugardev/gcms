#!/usr/bin/env bash
# Runs inside the dedicated VM, streamed by deploy/jio.sh.
set -Eeuo pipefail
revision="${1:?Commit SHA required}"
app_origin="${2:?Public HTTPS origin required}"
[[ "$revision" =~ ^[0-9a-f]{40}$ && "$app_origin" =~ ^https://[a-zA-Z0-9.-]+(:[0-9]+)?$ ]] || exit 1
root=/var/lib/gcms
sudo -n install -d -m 755 -o "$(id -un)" -g "$(id -gn)" "$root"
exec 9>"$root/deploy.lock"
flock -n 9 || { echo 'Another deployment is running' >&2; exit 1; }
sudo -n test -f "$root/data/review-rust.json"
sudo -n test -f "$root/data/sample.D/data.ms"

if ! command -v cc >/dev/null || ! command -v git >/dev/null || ! command -v psql >/dev/null; then
  sudo -n apt-get update -qq
  sudo -n env DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=180 install -y --no-install-recommends build-essential git ca-certificates curl xz-utils postgresql-16
fi
export CARGO_HOME="$root/cargo" RUSTUP_HOME="$root/rustup" CARGO_TARGET_DIR="$root/target"
export PATH="$root/node/bin:$CARGO_HOME/bin:$PATH"
if [[ ! -x "$CARGO_HOME/bin/rustup" ]]; then
  curl --proto '=https' --tlsv1.2 -fsSL https://sh.rustup.rs -o "$root/install-rust.sh"
  sh "$root/install-rust.sh" -y --no-modify-path --profile minimal --default-toolchain 1.94.0
fi
rustup toolchain install 1.94.0 --profile minimal
export RUSTUP_TOOLCHAIN=1.94.0
if [[ ! -x "$root/node/bin/node" ]] || [[ "$("$root/node/bin/node" --version)" != v24.21.0 ]]; then
  [[ "$(uname -m)" == x86_64 ]] || { echo 'This deployment requires the x86_64 Jio VM' >&2; exit 1; }
  curl -fsSL https://nodejs.org/dist/v24.21.0/node-v24.21.0-linux-x64.tar.xz -o "$root/node.tar.xz"
  (cd "$root" && printf '%s  node.tar.xz\n' fd8e59d5a511510f6a298afb548f18c7d2b1be404d8b4a27d94fbe49f56cb2d6 | sha256sum -c -)
  mkdir -p "$root/node"
  tar -xJf "$root/node.tar.xz" --strip-components=1 -C "$root/node"
fi
if [[ ! -x "$root/node/bin/pnpm" ]] || [[ "$(pnpm --version)" != 10.32.1 ]]; then
  npm install --global --prefix "$root/node" pnpm@10.32.1
fi

sudo -n id gcms >/dev/null 2>&1 || sudo -n useradd --system --home-dir "$root/data" --shell /usr/sbin/nologin gcms
sudo -n chown -R "$(id -un):gcms" "$root/data"
sudo -n chmod -R u=rwX,g=rX,o= "$root/data"
mkdir -p "$root/repo" "$root/releases"
if [[ ! -d "$root/repo/.git" ]]; then
  git -C "$root/repo" init -q
  git -C "$root/repo" remote add origin https://github.com/saugardev/gcms.git
fi
git -C "$root/repo" fetch --depth=1 origin "$revision"
[[ "$(git -C "$root/repo" rev-parse FETCH_HEAD)" == "$revision" ]]
release="$(mktemp -d "$root/releases/$revision.XXXXXX")"
chmod 755 "$release"
git -C "$root/repo" archive "$revision" | tar -x -C "$release"
cd "$release"
cargo test --locked --manifest-path services/rust/Cargo.toml --no-default-features --features server --bin gcms-api
cargo build --release --locked --manifest-path services/rust/Cargo.toml --no-default-features --features server --bin gcms-api
install -m 755 "$CARGO_TARGET_DIR/release/gcms-api" "$release/gcms-api"
export APP_ORIGIN="$app_origin" GCMS_API_URL=http://127.0.0.1:8001 DEPLOYMENT_VERSION="$revision" NEXT_TELEMETRY_DISABLED=1
pnpm --dir app install --frozen-lockfile
pnpm --dir app test
pnpm --dir app build

# Peer authentication: only the local gcms OS account can use the database role.
sudo -n systemctl enable --now postgresql
if [[ "$(sudo -n -u postgres psql -Atqc "SELECT 1 FROM pg_roles WHERE rolname='gcms'")" != 1 ]]; then
  sudo -n -u postgres createuser gcms
fi
if [[ "$(sudo -n -u postgres psql -Atqc "SELECT 1 FROM pg_database WHERE datname='gcms'")" != 1 ]]; then
  sudo -n -u postgres createdb --owner=gcms gcms
fi
mkdir -p "$root/backups"
chmod 700 "$root/backups"
# The deploy user owns the backup; postgres only reads the database.
# shellcheck disable=SC2024
(umask 077; sudo -n -u postgres pg_dump -Fc gcms > "$root/backups/$(date -u +%Y%m%dT%H%M%SZ)-$revision.dump")
database='host=/var/run/postgresql user=gcms dbname=gcms'
api() { sudo -n -u gcms env "DATABASE_URL=$database" "$release/gcms-api" "$@"; }
api migrate
imported="$(api import "$root/data/review-rust.json")"
analysis_id="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<< "$imported")"
api import-scans "$analysis_id" "$root/data/sample.D/data.ms"
[[ "$(sudo -n -u gcms psql -d gcms -Atqc 'SELECT count(*) FROM components')" -gt 0 ]]

# Keep both old units so the first migration from the Python dashboard can roll back too.
previous="$(readlink "$root/current" || true)"
for service in gcms gcms-api; do
  if [[ -f "/etc/systemd/system/$service.service" ]]; then
    cp "/etc/systemd/system/$service.service" "$release/deploy/previous-$service.service"
  fi
done
cat > "$release/deploy/gcms-api.service" <<EOF
[Unit]
After=network-online.target postgresql.service
Wants=network-online.target
Requires=postgresql.service
[Service]
User=gcms
Group=gcms
WorkingDirectory=$root/current
Environment="DATABASE_URL=$database"
Environment=APP_ORIGIN=$app_origin GCMS_BIND=127.0.0.1:8001
ExecStart=$root/current/gcms-api serve
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
UMask=0077
[Install]
WantedBy=multi-user.target
EOF
cat > "$release/deploy/gcms.service" <<EOF
[Unit]
After=network-online.target gcms-api.service
Wants=network-online.target gcms-api.service
[Service]
User=gcms
Group=gcms
WorkingDirectory=$root/current/app
Environment=NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
Environment=APP_ORIGIN=$app_origin GCMS_API_URL=http://127.0.0.1:8001 DEPLOYMENT_VERSION=$revision
ExecStart=$root/node/bin/node $root/current/app/node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
UMask=0077
[Install]
WantedBy=multi-user.target
EOF
mkdir -p "$release/app/.next/cache"
sudo -n chown -R gcms:gcms "$release/app/.next/cache"
rollback() {
  trap - ERR
  sudo -n journalctl -u gcms -u gcms-api --no-pager -n 50 >&2 || true
  sudo -n systemctl stop gcms gcms-api || true
  for service in gcms gcms-api; do
    if [[ -f "$release/deploy/previous-$service.service" ]]; then
      sudo -n cp "$release/deploy/previous-$service.service" "/etc/systemd/system/$service.service"
    else
      sudo -n systemctl disable "$service" || true
      sudo -n rm -f "/etc/systemd/system/$service.service"
    fi
  done
  sudo -n systemctl daemon-reload
  if [[ -n "$previous" ]]; then
    ln -sfn "$previous" "$root/next" && mv -Tf "$root/next" "$root/current"
    [[ ! -f "$release/deploy/previous-gcms-api.service" ]] || sudo -n systemctl start gcms-api
    sudo -n systemctl start gcms
  fi
  echo 'New workspace failed checks; restored the previous service release.' >&2
  exit 1
}
trap rollback ERR
sudo -n cp "$release/deploy/gcms.service" "$release/deploy/gcms-api.service" /etc/systemd/system/
sudo -n systemctl daemon-reload
sudo -n systemctl enable gcms gcms-api
ln -sfn "$release" "$root/next"
mv -Tf "$root/next" "$root/current"
sudo -n systemctl restart gcms-api gcms
bash deploy/check.sh http://127.0.0.1:8000 "$app_origin" "$revision"
trap - ERR
printf '%s\n' "$revision" > "$root/deployed-revision"
# ponytail: retain releases and DB backups; prune them when disk use warrants it.
echo "Mafer workspace is healthy at $revision"
