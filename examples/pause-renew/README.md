# Pause, Resume, And Renew Example

This example uses the OpenSandbox Python SDK against the lifecycle server deployed by this repository. It demonstrates three lifecycle operations:

- `renew`: extends the sandbox expiration time so it is not automatically deleted while you still need it.
- `pause`: asks the Kubernetes controller to commit the sandbox root filesystem to an OCI snapshot image and release the running workload pod.
- `resume`: starts the same sandbox ID from the snapshot image and reconnects the SDK client to the new execution endpoint.

Pause/resume preserves root filesystem changes, not process memory. The example writes a file under `/tmp`, pauses the sandbox, resumes it, then reads the same file back to prove the filesystem snapshot survived.

## Prerequisites

- The AKS OpenSandbox server is already deployed with `make k8s-deploy` from the repository root.
- The OpenSandbox controller is installed with pause/resume support from `make controller-install`.
- `kubectl` points at the AKS cluster.
- `uv` is available.

## Run

Install dependencies:

```bash
uv venv --allow-existing .venv
uv pip install --python .venv -r examples/pause-renew/requirements.txt
```

Port-forward the OpenSandbox server:

```bash
kubectl -n opensandbox port-forward svc/opensandbox-server 8080:8080
```

In another terminal, load the API key and run the example:

```bash
export OPEN_SANDBOX_API_KEY=$(kubectl -n opensandbox get secret opensandbox-server -o jsonpath='{.data.api-key}' | base64 -d)
OPEN_SANDBOX_DOMAIN=localhost:8080 VERIFY_WITH_KUBECTL=1 uv run --no-project --python .venv/bin/python python examples/pause-renew/app.py
```

Expected output includes:

```text
sandbox id: <sandbox-id>
renewed expiration: <timestamp>
state before pause: state survived pause/resume for <sandbox-id>
sandbox paused
batchsandbox phase: Paused
sandbox resumed
state after resume: state survived pause/resume for <sandbox-id>
command after resume: resumed sandbox is healthy
sandbox killed: <sandbox-id>
```

The example always waits for the lifecycle server to report the sandbox state as `Paused` before calling `resume`. If `VERIFY_WITH_KUBECTL=1` is set, it also checks the backing `BatchSandbox` reports `status.phase=Paused`. Omit that variable if you are running without local `kubectl` access.
