# OpenSandbox AKS Kata CLI Example

This example uses the upstream [`osb` CLI](https://github.com/opensandbox-group/OpenSandbox/tree/main/cli) against the OpenSandbox lifecycle server deployed by this repository.

It creates a sandbox, checks health, runs commands, writes and reads a file, verifies the sandbox workload uses the `kata-optimized` RuntimeClass, and cleans up the sandbox.

## Prerequisites

- The AKS OpenSandbox server is already deployed with `make k8s-deploy` from the repository root.
- `kubectl` points at the AKS cluster.
- `uv` is available.

## Automated Run

Run the full CLI example from the repository root after `make k8s-deploy`:

```bash
make cli-client-example
```

The target installs `opensandbox-cli` into `.venv` with `uv`, port-forwards the OpenSandbox server, runs `osb`, verifies `kata-optimized`, and kills the sandbox when finished.

## Step-By-Step Run

Install the CLI into the repository virtual environment:

```bash
uv venv --allow-existing .venv
uv pip install --python .venv -r examples/cli-client/requirements.txt opensandbox-cli==0.1.1
```

Port-forward the OpenSandbox server:

```bash
kubectl -n opensandbox port-forward svc/opensandbox-server 8080:8080
```

In another terminal, load the API key from the Kubernetes Secret:

```bash
export OPEN_SANDBOX_API_KEY=$(kubectl -n opensandbox get secret opensandbox-server -o jsonpath='{.data.api-key}' | base64 -d)
```

Create a sandbox with the CLI:

```bash
uv run --no-project --python .venv/bin/python osb \
  --no-color \
  --domain localhost:8080 \
  --protocol http \
  --use-server-proxy \
  sandbox create \
  --image python:3.12-slim \
  --timeout 10m \
  --metadata example=aks-kata-osb-cli \
  --resource cpu=500m \
  --resource memory=512Mi \
  -o json
```

Save the returned `id` as `SANDBOX_ID`, then inspect and check health:

```bash
export SANDBOX_ID=<sandbox-id>

uv run --no-project --python .venv/bin/python osb --no-color --domain localhost:8080 --protocol http --use-server-proxy sandbox get "$SANDBOX_ID" -o json
uv run --no-project --python .venv/bin/python osb --no-color --domain localhost:8080 --protocol http --use-server-proxy sandbox health "$SANDBOX_ID" -o json
```

Run commands in the sandbox:

```bash
uv run --no-project --python .venv/bin/python osb --no-color --domain localhost:8080 --protocol http --use-server-proxy command run "$SANDBOX_ID" -o raw -- sh -lc 'echo hello from osb cli on aks kata'
uv run --no-project --python .venv/bin/python osb --no-color --domain localhost:8080 --protocol http --use-server-proxy command run "$SANDBOX_ID" -o raw -- uname -a
```

Write and read a file:

```bash
uv run --no-project --python .venv/bin/python osb --no-color --domain localhost:8080 --protocol http --use-server-proxy file write "$SANDBOX_ID" /tmp/opensandbox-osb-cli.txt -c 'osb cli example' -o json
uv run --no-project --python .venv/bin/python osb --no-color --domain localhost:8080 --protocol http --use-server-proxy file cat "$SANDBOX_ID" /tmp/opensandbox-osb-cli.txt -o raw
```

Verify the workload pod uses Kata:

```bash
kubectl get batchsandbox "$SANDBOX_ID" -n opensandbox -o jsonpath='{.spec.template.spec.runtimeClassName}{"\n"}'
```

The output should be `kata-optimized`.

Clean up the sandbox:

```bash
uv run --no-project --python .venv/bin/python osb --no-color --domain localhost:8080 --protocol http --use-server-proxy sandbox kill "$SANDBOX_ID" -o json
```
