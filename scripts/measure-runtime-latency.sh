#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/measure-runtime-latency.sh [options]

Measure Kubernetes pod create-to-Ready latency for runtime classes, optionally
with an Azure Disk PVC.

Options:
  --runtime-class NAME       RuntimeClass to test (required)
  --namespace NAME           Namespace to create/use (default: runtime-latency)
  --pod-name NAME            Pod name (default: latency-smoke)
  --image IMAGE              Container image (default: python:3.12-slim)
  --pull-policy POLICY       Image pull policy (default: IfNotPresent)
  --runs N                   Number of iterations (default: 5)
  --node-selector KEY=VALUE  Node selector to add. Repeatable.
  --toleration KEY=VALUE:EFFECT
                             Toleration to add. Repeatable. Example: firecracker=true:NoSchedule
  --pvc-mode MODE            none | dynamic | existing (default: none)
  --pvc-name NAME            PVC name (default: latency-disk)
  --storage-class NAME       StorageClass for dynamic PVC (default: managed-csi)
  --storage-size SIZE        Size for dynamic PVC (default: 8Gi)
  --keep                     Keep namespace/resources after measurement
  --help                     Show this help

Examples:
  # gVisor no-volume latency
  scripts/measure-runtime-latency.sh \
    --runtime-class gvisor \
    --node-selector kubernetes.azure.com/agentpool=katapool

  # Firecracker no-volume latency
  scripts/measure-runtime-latency.sh \
    --runtime-class kata-fc \
    --node-selector kubernetes.azure.com/agentpool=fcpool \
    --toleration firecracker=true:NoSchedule \
    --pull-policy Never

  # Dynamic Azure Disk PVC latency
  scripts/measure-runtime-latency.sh \
    --runtime-class gvisor \
    --node-selector kubernetes.azure.com/agentpool=katapool \
    --pvc-mode dynamic \
    --runs 1

  # Existing PVC attach/mount latency
  scripts/measure-runtime-latency.sh \
    --runtime-class gvisor \
    --node-selector kubernetes.azure.com/agentpool=katapool \
    --pvc-mode existing \
    --pvc-name latency-disk
EOF
}

runtime_class=""
namespace="runtime-latency"
pod_name="latency-smoke"
image="python:3.12-slim"
pull_policy="IfNotPresent"
runs="5"
pvc_mode="none"
pvc_name="latency-disk"
storage_class="managed-csi"
storage_size="8Gi"
keep="false"
node_selectors=()
tolerations=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --runtime-class) runtime_class="$2"; shift 2 ;;
    --namespace) namespace="$2"; shift 2 ;;
    --pod-name) pod_name="$2"; shift 2 ;;
    --image) image="$2"; shift 2 ;;
    --pull-policy) pull_policy="$2"; shift 2 ;;
    --runs) runs="$2"; shift 2 ;;
    --node-selector) node_selectors+=("$2"); shift 2 ;;
    --toleration) tolerations+=("$2"); shift 2 ;;
    --pvc-mode) pvc_mode="$2"; shift 2 ;;
    --pvc-name) pvc_name="$2"; shift 2 ;;
    --storage-class) storage_class="$2"; shift 2 ;;
    --storage-size) storage_size="$2"; shift 2 ;;
    --keep) keep="true"; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$runtime_class" ]]; then
  echo "--runtime-class is required" >&2
  usage >&2
  exit 2
fi

if ! [[ "$runs" =~ ^[0-9]+$ ]] || [[ "$runs" -lt 1 ]]; then
  echo "--runs must be a positive integer" >&2
  exit 2
fi

case "$pvc_mode" in
  none|dynamic|existing) ;;
  *) echo "--pvc-mode must be one of: none, dynamic, existing" >&2; exit 2 ;;
esac

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

write_namespace() {
  cat > "$tmpdir/namespace.yaml" <<EOF
apiVersion: v1
kind: Namespace
metadata:
  name: ${namespace}
EOF
}

write_pvc() {
  cat > "$tmpdir/pvc.yaml" <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ${pvc_name}
  namespace: ${namespace}
spec:
  accessModes: ["ReadWriteOnce"]
  storageClassName: ${storage_class}
  resources:
    requests:
      storage: ${storage_size}
EOF
}

write_pod() {
  local out="$1"
  {
    cat <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: ${pod_name}
  namespace: ${namespace}
spec:
  runtimeClassName: ${runtime_class}
  restartPolicy: Never
EOF

    if [[ ${#node_selectors[@]} -gt 0 ]]; then
      echo "  nodeSelector:"
      for selector in "${node_selectors[@]}"; do
        key="${selector%%=*}"
        value="${selector#*=}"
        echo "    ${key}: ${value}"
      done
    fi

    if [[ ${#tolerations[@]} -gt 0 ]]; then
      echo "  tolerations:"
      for tol in "${tolerations[@]}"; do
        left="${tol%:*}"
        effect="${tol##*:}"
        key="${left%%=*}"
        value="${left#*=}"
        cat <<EOF
    - key: ${key}
      operator: Equal
      value: "${value}"
      effect: ${effect}
EOF
      done
    fi

    cat <<EOF
  containers:
    - name: smoke
      image: ${image}
      imagePullPolicy: ${pull_policy}
      command: ["sleep", "3600"]
EOF

    if [[ "$pvc_mode" != "none" ]]; then
      cat <<EOF
      volumeMounts:
        - name: data
          mountPath: /mnt/data
EOF
    fi

    cat <<EOF
      resources:
        requests:
          cpu: 250m
          memory: 256Mi
        limits:
          cpu: 500m
          memory: 512Mi
EOF

    if [[ "$pvc_mode" != "none" ]]; then
      cat <<EOF
  volumes:
    - name: data
      persistentVolumeClaim:
        claimName: ${pvc_name}
EOF
    fi
  } > "$out"
}

write_namespace
write_pod "$tmpdir/pod.yaml"
kubectl apply -f "$tmpdir/namespace.yaml" >/dev/null

if [[ "$pvc_mode" == "dynamic" ]]; then
  write_pvc
  kubectl apply -f "$tmpdir/pvc.yaml" >/dev/null
elif [[ "$pvc_mode" == "existing" ]]; then
  if ! kubectl get pvc -n "$namespace" "$pvc_name" >/dev/null 2>&1; then
    echo "PVC ${namespace}/${pvc_name} does not exist for --pvc-mode existing" >&2
    exit 1
  fi
fi

printf 'runtime_class=%s pvc_mode=%s runs=%s namespace=%s pod=%s\n' \
  "$runtime_class" "$pvc_mode" "$runs" "$namespace" "$pod_name"
printf 'run,apply_to_ready_ms,kubectl_apply_ms,wait_ms,node\n'

for i in $(seq 1 "$runs"); do
  kubectl delete pod -n "$namespace" "$pod_name" --ignore-not-found --wait=true >/dev/null
  start_ms="$(date +%s%3N)"
  kubectl apply -f "$tmpdir/pod.yaml" >/dev/null
  applied_ms="$(date +%s%3N)"
  kubectl wait --for=condition=Ready "pod/${pod_name}" -n "$namespace" --timeout=900s >/dev/null
  ready_ms="$(date +%s%3N)"
  node="$(kubectl get pod "$pod_name" -n "$namespace" -o jsonpath='{.spec.nodeName}')"
  printf '%s,%s,%s,%s,%s\n' \
    "$i" "$((ready_ms - start_ms))" "$((applied_ms - start_ms))" "$((ready_ms - applied_ms))" "$node"
done

if [[ "$keep" != "true" ]]; then
  kubectl delete pod -n "$namespace" "$pod_name" --ignore-not-found --wait=false >/dev/null
  if [[ "$pvc_mode" == "dynamic" ]]; then
    kubectl delete pvc -n "$namespace" "$pvc_name" --ignore-not-found --wait=false >/dev/null
  fi
fi
