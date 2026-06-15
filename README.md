# OpenSandbox on AKS with Kata

This repository contains a reproducible example for running [OpenSandbox](https://github.com/opensandbox-group/OpenSandbox) on Azure Kubernetes Service with AKS Pod Sandboxing backed by Kata Containers.

The example provisions AKS and Azure Container Registry with Bicep, installs the OpenSandbox Kubernetes controller, deploys an OpenSandbox lifecycle server configured for the `kata-vm-isolation` RuntimeClass, and runs a Python SDK smoke test that creates a sandbox and executes commands inside it.

## Layout

- `infra/`: Bicep templates for AKS and ACR.
- `deploy/opensandbox-server/`: OpenSandbox server Dockerfile, Kubernetes manifests, and server config.
- `examples/python-client/`: Python SDK smoke test and step-by-step client instructions.
- `examples/cli-client/`: `osb` CLI smoke test and step-by-step CLI instructions.
- `Makefile`: Human-reproducible workflow.

## SKU Choice

AKS Pod Sandboxing requires Azure Linux nodes and a VM size that is generation 2 and supports nested virtualization. This example defaults to `Standard_D4s_v3`, matching Microsoft AKS Pod Sandboxing guidance. The current AKS Bicep API uses `KataMshvVmIsolation` for the managed node pool workload runtime and exposes pods through the `kata-vm-isolation` Kubernetes RuntimeClass.

Use `Standard_DC8as_cc_v5` instead when you specifically need AKS Confidential Containers with `KataCcIsolation`; that is a different workload runtime and requires AMD SEV-SNP capable confidential computing quota.

## Prerequisites

- Azure CLI 2.80.0 or newer
- `kubectl`
- `helm`
- `docker`
- `make`
- `python3`
- `curl`

## Quick Start

Generate local environment config:

```bash
make local-config
make print-config
```

The generated `.make.env` file is ignored by git and contains resource names, the current Azure subscription ID, and a local `OPEN_SANDBOX_API_KEY`. Edit it if you want specific names, region, node count, or fallback settings. Deploy and smoke-test targets create/backfill this file automatically when needed without overwriting existing values. If you use a custom `LOCAL_CONFIG` path, add it to `.gitignore` or `.git/info/exclude` before generating secrets.

Run the end-to-end workflow:

```bash
make all
```

Useful individual targets:

```bash
make infra-deploy
make aks-credentials
make acr-login
make image-build
make image-push
make k8s-deploy
make smoke-test
make cli-smoke-test
make clean-k8s
make infra-delete
```

Cleanup targets require explicit confirmation to avoid deleting the wrong environment:

```bash
make clean-k8s CONFIRM_AKS_NAME=<your-aks-name> CONFIRM_RESOURCE_GROUP=<your-resource-group> CONFIRM_SUBSCRIPTION_ID=<your-subscription-id> CONFIRM_OPEN_SANDBOX_NAMESPACE=<your-namespace>
make infra-delete CONFIRM_RESOURCE_GROUP=<your-resource-group> CONFIRM_SUBSCRIPTION_ID=<your-subscription-id>
```

For cleanup and deletion, identity values must come from `.make.env` or explicit make command-line variables such as `make clean-k8s AKS_NAME=... RESOURCE_GROUP=... SUBSCRIPTION_ID=... OPEN_SANDBOX_NAMESPACE=...`. Exported environment variables are intentionally rejected for these destructive targets.

If your account cannot create role assignments, use ACR admin credentials for the sample server-image pull path. This fallback is selected only when both `ASSIGN_ACR_PULL_ROLE=false` and `ACR_ADMIN_USER_ENABLED=true` are set. It is less secure than the default managed-identity `AcrPull` path because ACR admin credentials are registry-wide credentials; use it only for disposable examples, then run `make clean-k8s`, disable ACR admin credentials, and rotate the ACR admin passwords when finished. The Makefile uses a short-lived `az acr login --expose-token` token in a per-push temporary Docker config for local image push and patches only the `opensandbox-server` ServiceAccount with the pull secret.

```bash
make all ASSIGN_ACR_PULL_ROLE=false ACR_ADMIN_USER_ENABLED=true
```

## Validation

The smoke test prints sandbox command output and the kernel/runtime details observed inside the sandbox. To verify the Kubernetes pod is using Kata, run:

```bash
kubectl get pods -n opensandbox -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.runtimeClassName}{"\n"}{end}'
```

OpenSandbox-created workload pods should show `kata-vm-isolation`.

### Why the sandbox kernel can look like the node kernel

`uname -a` inside a sandbox reports the kernel release and build string visible inside that workload. With AKS Pod Sandboxing, a Kata pod runs in a lightweight Pod VM with its own guest kernel, but AKS can use the same Azure Linux kernel release family for both the node and the Kata guest. Because of that, the release string can match the node's release, for example `6.6.137.mshv1-1.azl3`, even though the pod is using the Kata runtime path.

Treat `runtimeClassName`, not the `uname` release alone, as the primary proof that the OpenSandbox workload is using Kata. In this example the Kata path is configured in three places:

- The AKS node pool is created with `workloadRuntime: 'KataMshvVmIsolation'` in `infra/main.bicep`.
- OpenSandbox is configured with `k8s_runtime_class = "kata-vm-isolation"` in `deploy/opensandbox-server/config/sandbox.toml`.
- The BatchSandbox template sets `runtimeClassName: kata-vm-isolation` in `deploy/opensandbox-server/k8s/batchsandbox-template.yaml`.

For a live comparison, create one regular pod and one Kata pod on the cluster, then compare their runtime classes and kernel strings:

```bash
kubectl run proof-normal -n opensandbox --image=python:3.12-slim --restart=Never --command -- sleep 3600

kubectl apply -n opensandbox -f - <<'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: proof-kata
spec:
  runtimeClassName: kata-vm-isolation
  containers:
  - name: proof
    image: python:3.12-slim
    command: ["sleep", "3600"]
    resources:
      requests:
        cpu: "250m"
        memory: "512Mi"
      limits:
        cpu: "500m"
        memory: "512Mi"
  restartPolicy: Never
EOF

kubectl wait --for=condition=Ready pod/proof-normal -n opensandbox --timeout=180s
kubectl wait --for=condition=Ready pod/proof-kata -n opensandbox --timeout=180s

kubectl get pods proof-normal proof-kata -n opensandbox \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.runtimeClassName}{"\t"}{.spec.nodeName}{"\n"}{end}'

kubectl exec -n opensandbox proof-normal -- uname -a
kubectl exec -n opensandbox proof-kata -- uname -a

kubectl delete pod proof-normal proof-kata -n opensandbox --ignore-not-found
```

Example output from this cluster showed both pods on the same node and both using the same kernel release, while only the Kata pod had `runtimeClassName: kata-vm-isolation`:

```text
proof-normal        <empty>               <same-node-name>
proof-kata          kata-vm-isolation     <same-node-name>

Linux proof-normal 6.6.137.mshv1-1.azl3 #1 SMP Tue May 19 17:27:14 UTC 2026 x86_64 GNU/Linux
Linux proof-kata   6.6.137.mshv1-1.azl3 #1 SMP Tue May 19 17:02:13 UTC 2026 x86_64 GNU/Linux
```

The matching release confirms that `uname` alone is not an isolation test. The Kata runtime class, runtime handler, scheduling selector, and Kata pod overhead are the Kubernetes-level evidence that the workload is using AKS Pod Sandboxing.
