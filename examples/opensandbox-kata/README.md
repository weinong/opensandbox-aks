# OpenSandbox AKS Kata Example

This example deploys an OpenSandbox lifecycle server to AKS and configures the server to create sandboxes with the AKS `kata-vm-isolation` RuntimeClass.

## What It Runs

- OpenSandbox Kubernetes controller, installed from the upstream Helm chart.
- OpenSandbox lifecycle server, built from `server.Dockerfile`.
- A Python SDK smoke test in `app.py` that creates a sandbox, writes and reads a file, runs shell commands, prints `uname -a`, and cleans up the sandbox.

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

Run from the repository root with `make all`.
