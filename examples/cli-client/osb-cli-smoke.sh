#!/usr/bin/env bash
set -euo pipefail

OSB_BIN="${OSB_BIN:-osb}"
OPEN_SANDBOX_DOMAIN="${OPEN_SANDBOX_DOMAIN:-localhost:8080}"
OPEN_SANDBOX_PROTOCOL="${OPEN_SANDBOX_PROTOCOL:-http}"
SANDBOX_IMAGE="${SANDBOX_IMAGE:-python:3.12-slim}"
OPEN_SANDBOX_NAMESPACE="${OPEN_SANDBOX_NAMESPACE:-opensandbox}"

if [ -z "${OPEN_SANDBOX_API_KEY:-}" ]; then
  printf 'OPEN_SANDBOX_API_KEY is required\n' >&2
  exit 1
fi

osb_base=(
  "$OSB_BIN"
  --no-color
  --domain "$OPEN_SANDBOX_DOMAIN"
  --protocol "$OPEN_SANDBOX_PROTOCOL"
  --use-server-proxy
)

sandbox_id=""
cleanup() {
  if [ -n "$sandbox_id" ]; then
    "${osb_base[@]}" sandbox kill "$sandbox_id" -o json >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

create_json=$("${osb_base[@]}" sandbox create \
  --image "$SANDBOX_IMAGE" \
  --timeout 10m \
  --metadata example=aks-kata-osb-cli \
  --resource cpu=500m \
  --resource memory=512Mi \
  -o json)

sandbox_id=$(printf '%s' "$create_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
printf 'sandbox id: %s\n' "$sandbox_id"

"${osb_base[@]}" sandbox get "$sandbox_id" -o json >/dev/null
"${osb_base[@]}" sandbox health "$sandbox_id" -o json >/dev/null

hello=$("${osb_base[@]}" command run "$sandbox_id" -o raw -- sh -lc 'echo hello from osb cli on aks kata')
if [ "$hello" != "hello from osb cli on aks kata" ]; then
  printf 'unexpected command output: %s\n' "$hello" >&2
  exit 1
fi
printf 'command output: %s\n' "$hello"

uname_output=$("${osb_base[@]}" command run "$sandbox_id" -o raw -- uname -a)
printf 'sandbox kernel: %s\n' "$uname_output"

"${osb_base[@]}" file write "$sandbox_id" /tmp/opensandbox-osb-cli.txt \
  -c 'osb cli example' \
  -o json >/dev/null
file_content=$("${osb_base[@]}" file cat "$sandbox_id" /tmp/opensandbox-osb-cli.txt -o raw)
if [ "$file_content" != "osb cli example" ]; then
  printf 'unexpected file content: %s\n' "$file_content" >&2
  exit 1
fi
printf 'file roundtrip: %s\n' "$file_content"

if [ "${VERIFY_KATA_WITH_KUBECTL:-}" = "1" ]; then
  for _ in {1..30}; do
    runtime_class=$(kubectl get batchsandbox "$sandbox_id" \
      -n "$OPEN_SANDBOX_NAMESPACE" \
      -o jsonpath='{.spec.template.spec.runtimeClassName}' 2>/dev/null || true)
    if [ "$runtime_class" = "kata-optimized" ]; then
      printf 'runtime class: kata-optimized\n'
      exit 0
    fi
    sleep 1
  done
  printf 'Sandbox %s did not use runtimeClassName=kata-optimized\n' "$sandbox_id" >&2
  exit 1
fi
