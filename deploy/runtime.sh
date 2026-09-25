#!/usr/bin/env bash
# Runs inside the dedicated VM, streamed by deploy/jio.sh.
set -Eeuo pipefail
revision="${1:?Commit SHA required}"
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || exit 1
root=/var/lib/gcms
sudo -n install -d -m 755 -o "$(id -un)" -g "$(id -gn)" "$root"
exec 9>"$root/deploy.lock"
flock -n 9 || { echo 'Another deployment is running' >&2; exit 1; }
sudo -n test -f "$root/data/library.msp"
sudo -n test -f "$root/data/sample.D/data.ms"

if ! command -v cc >/dev/null || ! command -v git >/dev/null; then
  sudo -n apt-get update -qq
  sudo -n env DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=180 install -y --no-install-recommends build-essential git ca-certificates curl
fi
export UV_INSTALL_DIR="$root/bin" UV_PYTHON_INSTALL_DIR="$root/python" UV_CACHE_DIR="$root/uv-cache"
export CARGO_HOME="$root/cargo" RUSTUP_HOME="$root/rustup" CARGO_TARGET_DIR="$root/target"
export PATH="$UV_INSTALL_DIR:$CARGO_HOME/bin:$PATH"
if [[ ! -x "$UV_INSTALL_DIR/uv" ]] || [[ "$(uv --version)" != 'uv 0.11.6'* ]]; then
  curl -fsSL https://astral.sh/uv/0.11.6/install.sh -o "$root/install-uv.sh"
  UV_NO_MODIFY_PATH=1 sh "$root/install-uv.sh"
fi
if [[ ! -x "$CARGO_HOME/bin/rustup" ]]; then
  curl --proto '=https' --tlsv1.2 -fsSL https://sh.rustup.rs -o "$root/install-rust.sh"
  sh "$root/install-rust.sh" -y --no-modify-path --profile minimal --default-toolchain 1.94.0
fi
rustup toolchain install 1.94.0 --profile minimal
export RUSTUP_TOOLCHAIN=1.94.0

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
uv sync --locked
export PYO3_PYTHON="$release/.venv/bin/python"
# Force our crate to rebuild when its source directory changes; cache dependencies.
cargo clean --release -p gcms-rust --manifest-path services/rust/Cargo.toml
cargo build --release --locked --manifest-path services/rust/Cargo.toml
mkdir -p services/rust/target/release
install -m 755 "$CARGO_TARGET_DIR/release/lib_gcms_rust.so" services/rust/target/release/
export GCMS_LIBRARY="$root/data/library.msp" GCMS_SAMPLE="$root/data/sample.D"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
.venv/bin/python -c 'from gcms.rust_backend import native; native()'
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check services/python tests scripts

sudo -n tee /etc/systemd/system/gcms.service >/dev/null <<EOF
[Unit]
After=network-online.target
Wants=network-online.target
[Service]
User=gcms
Group=gcms
WorkingDirectory=$root/current
Environment=GCMS_LIBRARY=$GCMS_LIBRARY GCMS_SAMPLE=$GCMS_SAMPLE
Environment=OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
ExecStart=$root/current/.venv/bin/uvicorn gcms.api:app --host 127.0.0.1 --port 8000 --workers 1
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
UMask=0077
[Install]
WantedBy=multi-user.target
EOF
sudo -n systemctl daemon-reload
sudo -n systemctl enable gcms
previous="$(readlink "$root/current" || true)"
activate() {
  ln -sfn "$1" "$root/next" && mv -Tf "$root/next" "$root/current" && sudo -n systemctl restart gcms
}
healthy() {
  for path in /health / '/v1/sample?review=true&engine=python' '/v1/sample?review=true&engine=rust'; do
    curl --fail --silent --show-error --retry 10 --retry-connrefused --retry-all-errors --retry-delay 1 --max-time 120 "http://127.0.0.1:8000$path" --output /dev/null || return 1
  done
}
if ! activate "$release" || ! healthy; then
  sudo -n journalctl -u gcms --no-pager -n 50 >&2
  if [[ -n "$previous" ]]; then activate "$previous"; else sudo -n systemctl stop gcms; fi
  echo 'New release failed health checks' >&2
  exit 1
fi
printf '%s\n' "$revision" > "$root/deployed-revision"
# ponytail: retain releases for rollback; prune them when disk use warrants it.
echo "GCMS is healthy at $revision"
