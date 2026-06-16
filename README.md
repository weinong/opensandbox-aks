# OpenSandbox on AKS with Kata

This repository contains a reproducible example for running [OpenSandbox](https://github.com/opensandbox-group/OpenSandbox) on Azure Kubernetes Service with AKS Pod Sandboxing backed by Kata Containers.

The example provisions AKS and Azure Container Registry with Bicep, installs the OpenSandbox Kubernetes controller, deploys an OpenSandbox lifecycle server configured for the `kata-vm-isolation` RuntimeClass, and runs a Python SDK smoke test that creates a sandbox and executes commands inside it.

## Layout

- `infra/`: Bicep templates for AKS and ACR.
- `deploy/opensandbox-server/`: OpenSandbox server Dockerfile, Kubernetes manifests, and server config.
- `deploy/gvisor-runtime/`: optional unsupported gVisor runtime installer and smoke test manifests for AKS nodes.
- `deploy/firecracker-runtime/`: optional unsupported Firecracker runtime installer and smoke test manifests for a dedicated AKS user node pool.
- `examples/python-client/`: Python SDK smoke test and step-by-step client instructions.
- `examples/cli-client/`: `osb` CLI smoke test and step-by-step CLI instructions.
- `examples/gvisor-runtime/`: optional unsupported gVisor runtime usage notes.
- `examples/pause-renew/`: Python SDK example for renewing expiration, pausing, resuming, and verifying persisted filesystem state.
- `examples/pause-renew-cli/`: `osb` CLI example for the same renew, pause, and resume lifecycle.
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

The generated `.make.env` file is ignored by git and contains environment-specific values: resource names, region, node count, namespace, the current Azure subscription ID, and a local `OPEN_SANDBOX_API_KEY`. Stable workflow defaults such as image tag, controller version, CLI version, snapshot defaults, and example image live in the `Makefile` and can still be overridden on the make command line when needed. Deploy and smoke-test targets create/backfill this file automatically without overwriting existing environment values. During migration, known generated stable defaults are pruned from existing `.make.env` files so future Makefile defaults apply. If you use a custom `LOCAL_CONFIG` path, add it to `.gitignore` or `.git/info/exclude` before generating secrets.

By default this sample uses managed identity `AcrPull` for the server image path and does not create registry credentials. OpenSandbox pause/resume needs push and pull credentials for root filesystem snapshot images; for disposable examples, opt in with `ENABLE_SNAPSHOT_REGISTRY_SECRET=true ACR_ADMIN_USER_ENABLED=true`, or create your own `kubernetes.io/dockerconfigjson` secret named by `OPEN_SANDBOX_SNAPSHOT_SECRET` before pausing sandboxes.

Run the end-to-end workflow:

```bash
make all
```

`make all` deploys the infrastructure, installs the controller and server, then runs the Python SDK smoke test. Run the pause/resume snapshot examples separately with `make pause-renew-example` or `make pause-renew-cli-example` after the deployment is healthy.

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
make gvisor-install
make gvisor-smoke-test
make firecracker-nodepool-add
make firecracker-install
make firecracker-smoke-test
make pause-renew-example
make pause-renew-cli-example
make clean-k8s
make clean-opensandbox-crds
make infra-delete
```

The gVisor targets mutate AKS node host files and restart `containerd`; they are
for disposable experiments or isolated test node pools only. See
`examples/gvisor-runtime/README.md` before running them.

The Firecracker targets create/use a dedicated tainted user node pool and mutate
node host files to install Kata's Firecracker shim plus devmapper snapshotter
configuration. See `deploy/firecracker-runtime/README.md` before running them.

Cleanup targets require explicit confirmation to avoid deleting the wrong environment:

```bash
make clean-k8s CONFIRM_AKS_NAME=<your-aks-name> CONFIRM_RESOURCE_GROUP=<your-resource-group> CONFIRM_SUBSCRIPTION_ID=<your-subscription-id> CONFIRM_OPEN_SANDBOX_NAMESPACE=<your-namespace>
make clean-opensandbox-crds CONFIRM_AKS_NAME=<your-aks-name> CONFIRM_RESOURCE_GROUP=<your-resource-group> CONFIRM_SUBSCRIPTION_ID=<your-subscription-id> CONFIRM_DELETE_OPEN_SANDBOX_CRDS=delete-cluster-wide-opensandbox-crds
make infra-delete CONFIRM_RESOURCE_GROUP=<your-resource-group> CONFIRM_SUBSCRIPTION_ID=<your-subscription-id>
```

For cleanup and deletion, identity values must come from `.make.env` or explicit make command-line variables such as `make clean-k8s AKS_NAME=... RESOURCE_GROUP=... SUBSCRIPTION_ID=... OPEN_SANDBOX_NAMESPACE=...`. Exported environment variables are intentionally rejected for these destructive targets.

If your account cannot create role assignments, use the same ACR admin credentials for the sample server-image pull path. This fallback is selected only when both `ASSIGN_ACR_PULL_ROLE=false` and `ACR_ADMIN_USER_ENABLED=true` are set. It is less secure than the default managed-identity `AcrPull` path because ACR admin credentials are registry-wide credentials; use it only for disposable examples, then run `make clean-k8s`, disable ACR admin credentials, and rotate the ACR admin passwords when finished. The Makefile uses a short-lived `az acr login --expose-token` token in a per-push temporary Docker config for local image push and patches only the `opensandbox-server` ServiceAccount with the pull secret.

```bash
make all ASSIGN_ACR_PULL_ROLE=false ACR_ADMIN_USER_ENABLED=true
```

## Pause And Resume

OpenSandbox pause/resume requires controller support in addition to the lifecycle server API. This repo installs OpenSandbox controller `0.2.0` because older `0.1.0` CRDs do not include `BatchSandbox.spec.pause`, `BatchSandbox.status.phase`, or the `SandboxSnapshot` resource required by pause/resume.

The controller commits the sandbox root filesystem to an OCI image and stores it under `OPEN_SANDBOX_SNAPSHOT_REGISTRY`, which defaults to `<acr>.azurecr.io/opensandbox-snapshots`. Pause/resume currently supports single-replica sandboxes, which is what this sample creates.

For a disposable sample environment backed by this repo's ACR, let the Makefile create the snapshot push/pull secret:

```bash
make all ACR_ADMIN_USER_ENABLED=true ENABLE_SNAPSHOT_REGISTRY_SECRET=true
```

ACR admin credentials are registry-wide credentials stored in a Kubernetes docker config secret. Prefer a scoped registry credential for durable environments, and rotate or disable ACR admin credentials after disposable testing.

Useful checks after `make controller-install`:

```bash
kubectl get crd batchsandboxes.sandbox.opensandbox.io \
  -o jsonpath='{.spec.versions[?(@.name=="v1alpha1")].schema.openAPIV3Schema.properties.spec.properties.pause.type}{"\n"}'
kubectl get crd sandboxsnapshots.sandbox.opensandbox.io
kubectl get deploy -n opensandbox-system -l control-plane=controller-manager
```

If an existing cluster was previously installed with controller `0.1.0`, rerun `make controller-install`. If `sandboxsnapshots.sandbox.opensandbox.io` is still missing or the `pause` jsonpath above does not print `boolean`, first use the disposable-environment reset path: `make clean-k8s` followed by `make controller-install` and `make k8s-deploy`. If stale cluster-scoped CRDs still block the upgrade, run `make clean-opensandbox-crds` with its explicit confirmation string. That target deletes OpenSandbox CRDs and all matching custom resources cluster-wide, so do not use it on a shared cluster or on a cluster with OpenSandbox resources you need to keep.

Pause/resume preserves root filesystem changes but does not checkpoint process memory or running processes. After resume, the sandbox starts from the committed image using the same sandbox ID.

The `examples/pause-renew/` example demonstrates the complete flow from the Python SDK:

```bash
make pause-renew-example
```

The `examples/pause-renew-cli/` example demonstrates the same flow with the `osb` CLI:

```bash
make pause-renew-cli-example
```

Both examples create a sandbox, renew the expiration by 30 minutes, write a file under `/tmp`, pause the sandbox, wait until the lifecycle server reports state `Paused`, optionally check the backing `BatchSandbox` reports `status.phase=Paused`, resume the same sandbox ID, read the file back, run a command after resume, and kill the sandbox. The important distinction is that `renew` extends how long the lifecycle service keeps the sandbox before automatic cleanup, while `pause` releases the running Kubernetes workload after snapshotting the root filesystem, and `resume` recreates the workload from that snapshot.

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
