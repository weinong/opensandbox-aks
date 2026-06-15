# OpenSandbox on AKS with Kata

This repository contains a reproducible example for running [OpenSandbox](https://github.com/opensandbox-group/OpenSandbox) on Azure Kubernetes Service with AKS Pod Sandboxing backed by Kata Containers.

The example provisions AKS and Azure Container Registry with Bicep, installs the OpenSandbox Kubernetes controller, deploys an OpenSandbox lifecycle server configured for the `kata-vm-isolation` RuntimeClass, and runs a Python SDK smoke test that creates a sandbox and executes commands inside it.

## Layout

- `infra/`: Bicep templates for AKS and ACR.
- `examples/opensandbox-kata/`: Python SDK smoke test, Kubernetes manifests, server config, and server Dockerfile.
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
