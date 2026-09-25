#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
vm="${JIO_VM_ID:?Set JIO_VM_ID to the dedicated GCMS VM}"
revision="${GIT_REF:-$(git rev-parse HEAD)}"
[[ "$vm" =~ ^[0-9a-f]{32}$ && "$revision" =~ ^[0-9a-f]{40}$ ]] || { echo 'Expected a VM ID and full commit SHA' >&2; exit 1; }
[[ "$(jio usage)" == "Account: gcms ("* ]] || { echo 'Deployment requires the gcms Jio account' >&2; exit 1; }

if readiness="$(jio exec "$vm" true --timeout 15 2>&1)"; then
  :
elif [[ "$readiness" == "jio: session $vm is Stopped" ]]; then
  jio start "$vm"
  jio exec "$vm" true --timeout 15
else
  printf '%s\n' "$readiness" >&2
  exit 1
fi

# Allocate the public origin before building/configuring browser sessions.
published="$(jio ports "$vm")"
url="$(awk '$1 == 8000 && $2 == "published" { print $3; exit }' <<< "$published")"
if [[ -z "$url" ]]; then
  for attempt in 1 2 3; do
    if url="$(jio expose 8000 "$vm")"; then break; fi
    [[ "$attempt" != 3 ]] || exit 1
    sleep 35
  done
fi
[[ "$url" =~ ^https://[a-zA-Z0-9.-]+(:[0-9]+)?$ ]] || { echo 'Invalid HTTPS origin from Jio' >&2; exit 1; }
# Complete heredoc prevents installers from consuming the remaining SSH input.
{
  printf "bash -s -- '%s' '%s' <<'GCMS_DEPLOY_SCRIPT'\n" "$revision" "$url"
  cat deploy/runtime.sh
  printf '\nGCMS_DEPLOY_SCRIPT\n'
} | jio connect "$vm"

bash deploy/check.sh "$url" "$url" "$revision"
printf 'App: %s\nRevision: %s\n' "$url" "$revision"
