#!/usr/bin/env bash
# Verify the Next.js surface, its Rust/PostgreSQL dependency, assets and auth boundary.
set -Eeuo pipefail
url="${1:?App URL required}"
origin="${2:?Browser origin required}"
revision="${3:?Commit SHA required}"
health="$(curl --fail --silent --show-error --retry 15 --retry-all-errors --retry-delay 2 --max-time 15 "$url/health")"
python3 -c 'import json,sys; h=json.load(sys.stdin); assert h == {"status":"ok","storage":"postgresql","app":"mafer-workspace","revision":sys.argv[1]}, h' "$revision" <<< "$health"
for path in /login /register; do
  page="$(curl --fail --silent --show-error --max-time 20 "$url$path")"
  [[ "$page" == *'Mafer · Analyst workspace'* && "$page" == *'/_next/static/'* ]]
done
asset="$(python3 -c 'import re,sys; print(re.search(r"(?:src|href)=\"(/_next/static/[^\"]+)",sys.stdin.read())[1])' <<< "$page")"
curl --fail --silent --show-error --max-time 20 "$url$asset" --output /dev/null
[[ "$(curl --silent --show-error --max-time 15 --output /dev/null --write-out '%{http_code}' "$url/api/analyses")" == 401 ]]
# Invalid input tests both origin configuration and the Rust auth handler without creating an account.
[[ "$(curl --silent --show-error --max-time 15 --output /dev/null --write-out '%{http_code}' -H "Origin: $origin" -H 'Content-Type: application/json' --data '{"email":"invalid","password":""}' "$url/api/auth/login")" == 400 ]]
[[ "$(curl --silent --show-error --max-time 15 --output /dev/null --write-out '%{http_code}' -H 'Origin: https://invalid.example' -H 'Content-Type: application/json' --data '{}' "$url/api/auth/login")" == 403 ]]
printf 'Verified Next.js, assets, Rust/PostgreSQL health, protected data and sign-in origin at %s\n' "$url"
