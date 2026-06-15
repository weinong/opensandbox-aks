# Pause, Resume, And Renew CLI Example

This example uses the upstream `osb` CLI against the lifecycle server deployed by this repository. It demonstrates the same lifecycle flow as `examples/pause-renew/`, but through CLI commands instead of the Python SDK.

- `osb sandbox renew`: extends the sandbox expiration time.
- `osb sandbox pause`: asks the controller to snapshot the sandbox root filesystem and release the workload pod.
- `osb sandbox resume`: recreates the same sandbox ID from the snapshot image.

Pause/resume preserves root filesystem changes, not process memory. The script writes a file under `/tmp`, pauses the sandbox, resumes it, then reads the same file back.

## Prerequisites

- The AKS OpenSandbox server is already deployed with `make k8s-deploy` from the repository root.
- The OpenSandbox controller is installed with pause/resume support from `make controller-install`.
- `kubectl` points at the AKS cluster.
- `python3` is available.

## Run

From the repository root, run the automated target:

```bash
make pause-renew-cli-example
```

For a manual run, install the CLI and dependencies:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r examples/pause-renew-cli/requirements.txt opensandbox-cli==0.1.1
```

Port-forward the OpenSandbox server:

```bash
kubectl -n opensandbox port-forward svc/opensandbox-server 8080:8080
```

In another terminal, load the API key and run the script:

```bash
export OPEN_SANDBOX_API_KEY=$(kubectl -n opensandbox get secret opensandbox-server -o jsonpath='{.data.api-key}' | base64 -d)
OPEN_SANDBOX_DOMAIN=localhost:8080 VERIFY_WITH_KUBECTL=1 bash examples/pause-renew-cli/osb-pause-renew.sh
```

Expected output includes:

```text
sandbox id: <sandbox-id>
sandbox renewed for 30m
state before pause: state survived pause/resume for <sandbox-id>
sandbox pause requested
sandbox state: Paused
batchsandbox phase: Paused
sandbox resumed
state after resume: state survived pause/resume for <sandbox-id>
command after resume: resumed sandbox is healthy
sandbox killed: <sandbox-id>
```

The script always waits for the lifecycle server to report state `Paused` before resuming. If `VERIFY_WITH_KUBECTL=1` is set, it also checks the backing `BatchSandbox.status.phase` for `Paused`.
