# OpenSandbox Server Deployment

This deployment packages the upstream OpenSandbox lifecycle server for AKS and configures it to create sandboxes with the AKS `kata-vm-isolation` RuntimeClass.

## What It Runs

- OpenSandbox Kubernetes controller, installed from the upstream Helm chart.
- OpenSandbox lifecycle server, built from `Dockerfile`.
- Kubernetes manifests and server configuration for the lifecycle server.

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

The AKS node pool is created with Bicep using `workloadRuntime: 'KataMshvVmIsolation'`, which creates the matching `kata-vm-isolation` RuntimeClass.

Deploy from the repository root with `make k8s-deploy`, or run the full workflow with `make all`.
