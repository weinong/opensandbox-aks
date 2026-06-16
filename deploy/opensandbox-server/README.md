# OpenSandbox Server Deployment

This deployment packages the upstream OpenSandbox lifecycle server for AKS and configures it to create sandboxes with the AKS `kata-vm-isolation` RuntimeClass.

## What It Runs

- OpenSandbox Kubernetes controller, installed from the upstream Helm chart.
- OpenSandbox lifecycle server, built from `Dockerfile`.
- Kubernetes manifests and server configuration for the lifecycle server.

The Makefile installs controller chart `0.2.0` so BatchSandbox pause/resume is available. Pause/resume depends on the `SandboxSnapshot` CRD and `BatchSandbox.spec.pause`; older controller releases do not provide those fields.

## Runtime Configuration

`config/sandbox.toml` uses:

```toml
[runtime]
type = "kubernetes"
execd_image = "opensandbox/execd:v1.0.18"

[kubernetes]
workload_provider = "batchsandbox"
batchsandbox_template_file = "/app/batchsandbox-template.yaml"

[secure_runtime]
type = "kata"
k8s_runtime_class = "kata-vm-isolation"
```

The Bicep template keeps cluster components on a non-Kata Azure Linux system pool and creates a dedicated tainted Kata user pool with `workloadRuntime: 'KataMshvVmIsolation'`, which creates the matching `kata-vm-isolation` RuntimeClass. `k8s/batchsandbox-template.yaml` sets the runtime class and targets the Kata pool with a node selector and toleration.

## Pause/Resume Snapshot Configuration

`make controller-install` passes snapshot settings to the controller:

```text
controller.snapshot.registry=$(OPEN_SANDBOX_SNAPSHOT_REGISTRY)
controller.snapshot.snapshotPushSecret=$(OPEN_SANDBOX_SNAPSHOT_SECRET)
controller.snapshot.resumePullSecret=$(OPEN_SANDBOX_SNAPSHOT_SECRET)
controller.snapshot.imageCommitterImage=$(OPEN_SANDBOX_IMAGE_COMMITTER_IMAGE)
```

`make k8s-deploy` creates `OPEN_SANDBOX_SNAPSHOT_SECRET` as a docker-registry secret only when both `ENABLE_SNAPSHOT_REGISTRY_SECRET=true` and `ACR_ADMIN_USER_ENABLED=true` are set. Otherwise, create an equivalent `kubernetes.io/dockerconfigjson` secret in the sandbox namespace before calling `sandbox pause`.

Deploy from the repository root with `make k8s-deploy`, or run the full workflow with `make all`.
