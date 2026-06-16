# OpenSandbox Python Client Example

This example uses the upstream OpenSandbox Python SDK against the OpenSandbox lifecycle server deployed by this repository.

It creates a sandbox, runs commands, writes and reads a file, prints `uname -a`, verifies the sandbox workload uses the `kata-optimized` RuntimeClass, and cleans up the sandbox.

## Prerequisites

- The AKS OpenSandbox server is already deployed with `make k8s-deploy` from the repository root.
- `kubectl` points at the AKS cluster.
- `python3` is available.

## Automated Run

Run the Python SDK smoke test from the repository root after `make k8s-deploy`:

```bash
make smoke-test
```

The target installs SDK dependencies into `.venv`, port-forwards the OpenSandbox server, runs `app.py`, verifies `kata-optimized`, and kills the sandbox when finished.

## Step-By-Step Run

Install the SDK into the repository virtual environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r examples/python-client/requirements.txt
```

Port-forward the OpenSandbox server:

```bash
kubectl -n opensandbox port-forward svc/opensandbox-server 8080:8080
```

In another terminal, load the API key from the Kubernetes Secret and run the client:

```bash
export OPEN_SANDBOX_API_KEY=$(kubectl -n opensandbox get secret opensandbox-server -o jsonpath='{.data.api-key}' | base64 -d)
OPEN_SANDBOX_DOMAIN=localhost:8080 VERIFY_KATA_WITH_KUBECTL=1 python examples/python-client/app.py
```
