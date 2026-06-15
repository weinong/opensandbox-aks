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
- `openssl` for the quick-start API key command, or any equivalent random secret generator

## Quick Start

Set the required variables:

```bash
export LOCATION=eastus
export RESOURCE_GROUP=rg-opensandbox-kata
export AKS_NAME=osb-kata-aks
export ACR_NAME=<globally-unique-acr-name>
export OPEN_SANDBOX_API_KEY=$(openssl rand -hex 32)
```

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
