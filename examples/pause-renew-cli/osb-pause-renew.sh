#!/usr/bin/env bash
set -euo pipefail

OSB_BIN="${OSB_BIN:-osb}"
UV="${UV:-uv}"
UV_PYTHON="${UV_PYTHON:-.venv/bin/python}"
OPEN_SANDBOX_DOMAIN="${OPEN_SANDBOX_DOMAIN:-localhost:8080}"
OPEN_SANDBOX_PROTOCOL="${OPEN_SANDBOX_PROTOCOL:-http}"
SANDBOX_IMAGE="${SANDBOX_IMAGE:-python:3.12-slim}"
OPEN_SANDBOX_NAMESPACE="${OPEN_SANDBOX_NAMESPACE:-opensandbox}"
STATE_FILE="/tmp/opensandbox-pause-renew-cli.txt"

if [ -z "${OPEN_SANDBOX_API_KEY:-}" ]; then
  printf 'OPEN_SANDBOX_API_KEY is required\n' >&2
  exit 1
fi

osb_base=(
  "$UV"
  run
  --no-project
  --python
  "$UV_PYTHON"
  "$OSB_BIN"
  --no-color
  --domain "$OPEN_SANDBOX_DOMAIN"
  --protocol "$OPEN_SANDBOX_PROTOCOL"
  --use-server-proxy
)

sandbox_id=""
cleanup() {
  if [ -n "$sandbox_id" ]; then
    if "${osb_base[@]}" sandbox kill "$sandbox_id" -o json >/dev/null 2>&1; then
      printf 'sandbox killed: %s\n' "$sandbox_id"
    fi
  fi
}
trap cleanup EXIT

get_sandbox_state() {
  "${osb_base[@]}" sandbox get "$sandbox_id" -o json \
    | "$UV" run --no-project --python "$UV_PYTHON" python -c 'import json,sys; print(json.load(sys.stdin)["status"]["state"])'
}

wait_for_state() {
  expected="$1"
  deadline=$((SECONDS + 180))
  last_state=""
  while [ "$SECONDS" -lt "$deadline" ]; do
    last_state=$(get_sandbox_state || true)
    if [ "$last_state" = "$expected" ]; then
      printf 'sandbox state: %s\n' "$expected"
      return 0
    fi
    sleep 2
  done
  printf 'Timed out waiting for sandbox %s state %s; last state was %s\n' "$sandbox_id" "$expected" "$last_state" >&2
  return 1
}

wait_for_batchsandbox_phase() {
  expected="$1"
  deadline=$((SECONDS + 180))
  last_phase=""
  while [ "$SECONDS" -lt "$deadline" ]; do
    last_phase=$(kubectl get batchsandbox "$sandbox_id" \
      -n "$OPEN_SANDBOX_NAMESPACE" \
      -o jsonpath='{.status.phase}' 2>/dev/null || true)
    if [ "$last_phase" = "$expected" ]; then
      printf 'batchsandbox phase: %s\n' "$expected"
      return 0
    fi
    sleep 2
  done
  printf 'Timed out waiting for BatchSandbox %s phase %s; last phase was %s\n' "$sandbox_id" "$expected" "$last_phase" >&2
  return 1
}

create_json=$("${osb_base[@]}" sandbox create \
  --image "$SANDBOX_IMAGE" \
  --timeout 10m \
  --metadata example=pause-renew-cli \
  --resource cpu=500m \
  --resource memory=512Mi \
  -o json)

sandbox_id=$(printf '%s' "$create_json" | "$UV" run --no-project --python "$UV_PYTHON" python -c 'import json,sys; print(json.load(sys.stdin)["id"])')
printf 'sandbox id: %s\n' "$sandbox_id"

"${osb_base[@]}" sandbox renew "$sandbox_id" --timeout 30m -o json >/dev/null
printf 'sandbox renewed for 30m\n'

"${osb_base[@]}" file write "$sandbox_id" "$STATE_FILE" \
  -c "state survived pause/resume for $sandbox_id" \
  -o json >/dev/null

before_pause=$("${osb_base[@]}" file cat "$sandbox_id" "$STATE_FILE" -o raw)
printf 'state before pause: %s\n' "$before_pause"

timestamp=$("${osb_base[@]}" command run "$sandbox_id" -o raw -- date -u +%Y-%m-%dT%H:%M:%SZ)
printf 'timestamp before pause: %s\n' "$timestamp"

"${osb_base[@]}" sandbox pause "$sandbox_id" -o json >/dev/null
printf 'sandbox pause requested\n'

wait_for_state "Paused"

if [ "${VERIFY_WITH_KUBECTL:-}" = "1" ]; then
  wait_for_batchsandbox_phase "Paused"
fi

"${osb_base[@]}" sandbox resume "$sandbox_id" --resume-timeout 120s -o json >/dev/null
printf 'sandbox resumed\n'

after_resume=$("${osb_base[@]}" file cat "$sandbox_id" "$STATE_FILE" -o raw)
printf 'state after resume: %s\n' "$after_resume"

if [ "$after_resume" != "$before_pause" ]; then
  printf 'Sandbox state file changed across pause/resume\n' >&2
  exit 1
fi

health=$("${osb_base[@]}" command run "$sandbox_id" -o raw -- echo 'resumed sandbox is healthy')
if [ "$health" != "resumed sandbox is healthy" ]; then
  printf 'unexpected command output after resume: %s\n' "$health" >&2
  exit 1
fi
printf 'command after resume: %s\n' "$health"
