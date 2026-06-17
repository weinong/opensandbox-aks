# VS Code Web Sandbox Example

This example runs [code-server](https://github.com/coder/code-server), a browser-accessible VS Code build, inside an OpenSandbox workload on the AKS Kata runtime configured by this repository.

It is adapted from the upstream OpenSandbox [`examples/vscode`](https://github.com/opensandbox-group/OpenSandbox/tree/main/examples/vscode) example, but uses the deployed AKS lifecycle server, the configured Azure Container Registry, and the `kata-optimized` RuntimeClass.

## Prerequisites

- The AKS OpenSandbox server is already deployed with `make k8s-deploy` from the repository root.
- `kubectl` points at the AKS cluster.
- `docker`, `az`, `python3`, and `curl` are available locally.
- The configured ACR is reachable by the OpenSandbox workload pods. The default managed identity `AcrPull` path from this repo handles that for images pushed to `$(ACR_NAME).azurecr.io`.

## Automated Run

Build and push the VS Code sandbox image, port-forward the OpenSandbox server, create a sandbox, start `code-server`, create a helper proxy pod, and print the browser URL:

```bash
make vscode-example
```

The target uses these defaults:

```text
VSCODE_IMAGE_NAME=opensandbox-vscode
VSCODE_IMAGE_TAG=latest
VSCODE_PORT=8443
ENABLE_INGRESS_GATEWAY=false
```

The image installs pinned `code-server` release `4.124.2` from the upstream `.deb` package and verifies the package SHA-256 during build.

The printed VS Code URL uses a local `kubectl port-forward` to a short-lived helper proxy pod that forwards traffic to the sandbox endpoint IP. This bypasses the OpenSandbox lifecycle server endpoint proxy for browser traffic because VS Code Web requires WebSocket upgrade support. The launcher waits for `code-server` to answer inside the sandbox before opening the local port-forward.

The example starts `code-server` with `--auth none` and binds browser access to `127.0.0.1` through local port-forwarding/proxying. Treat it as a disposable single-user development example; do not expose the printed URL or raw gateway port on a shared network.

To avoid the per-sandbox helper proxy pod, deploy the shared OpenSandbox ingress gateway and run the example through gateway URI routing:

```bash
make k8s-deploy ENABLE_INGRESS_GATEWAY=true
make vscode-example ENABLE_INGRESS_GATEWAY=true
```

With gateway mode enabled, `make vscode-example` port-forwards the single shared `opensandbox-ingress-gateway` service on `INGRESS_GATEWAY_LOCAL_PORT` and prints a local browser URL such as `http://127.0.0.1:<local-port>/`. The example keeps a lightweight local route proxy process that prefixes browser HTTP and WebSocket requests with the gateway route before sending them to the shared gateway. This avoids a per-sandbox Kubernetes helper pod and keeps `code-server` mounted at `/`, which is required for its root-relative workbench assets.

Open the printed `VS Code Web endpoint`, not the raw gateway port. The raw gateway port, for example `http://127.0.0.1:8081/`, expects paths in the form `/<sandbox-id>/<port>/...` and returns `OpenSandbox Ingress: invalid ingress route` for `/`.

If you previously opened a VS Code endpoint before updating this example, stop the old `make vscode-example` process and start a fresh one. The local route proxy is created per run, so already-running proxy processes do not pick up code changes.

If the cluster is already deployed with `[ingress] mode = "gateway"`, `make vscode-example` detects that server config and uses gateway access automatically. This avoids accidentally running SDK readiness checks through lifecycle server proxy mode against a gateway-configured server.

## How It Works

In the default helper-proxy mode, `kubectl -n opensandbox get pods` should show two example-related pods:

```text
<sandbox-id>-0              1/1     Running
vscode-proxy-<sandbox-id>   1/1     Running
```

The `<sandbox-id>-0` pod is the actual OpenSandbox workload. It is created by the OpenSandbox controller from the `BatchSandbox` resource, runs the VS Code image, and uses the `kata-optimized` RuntimeClass. `code-server` runs in this sandbox on port `8443`.

The `vscode-proxy-<sandbox-id>` pod is not another sandbox. It is a temporary helper pod created by `examples/vscode/main.py` so local browser traffic can reach VS Code reliably. Kubernetes `kubectl port-forward pod/<kata-pod>` connects to `127.0.0.1:<port>` inside the pod network namespace, but the OpenSandbox/Kata endpoint for browser traffic is exposed through the sandbox endpoint IP annotation. The helper pod listens on `8443`, forwards raw TCP to that sandbox endpoint IP, and then the script runs local `kubectl port-forward` to the helper pod.

Traffic flow:

```text
browser -> 127.0.0.1:<local-port> -> kubectl port-forward -> vscode-proxy-<sandbox-id>:8443 -> <sandbox-endpoint-ip>:8443 -> code-server in <sandbox-id>-0
```

In gateway mode, the shared gateway replaces the per-sandbox proxy pod:

```text
browser -> 127.0.0.1:<local-port>/ -> local route proxy -> 127.0.0.1:<gateway-local-port>/<sandbox-id>/8443/ -> kubectl port-forward -> opensandbox-ingress-gateway -> <sandbox-endpoint-ip>:8443 -> code-server in <sandbox-id>-0
```

Example resources are cleaned up when the script exits normally or when you press `Ctrl+C`. If the process is interrupted abruptly, clean up with:

```bash
kubectl delete pod -n opensandbox -l app.kubernetes.io/name=opensandbox-vscode-proxy
kubectl delete batchsandbox -n opensandbox <sandbox-id>
```

The example keeps the sandbox alive for 10 minutes. Override that duration when needed:

```bash
KEEPALIVE_SECONDS=1800 make vscode-example
```

Use a fixed local browser port when needed:

```bash
VSCODE_LOCAL_PORT=18443 make vscode-example
```

Press `Ctrl+C` to stop early. The script kills the sandbox on exit.

## Step-By-Step Run

Build and push the image to ACR:

```bash
make vscode-image-push
```

Install the SDK into the repository virtual environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r examples/vscode/requirements.txt
```

Port-forward the OpenSandbox server:

```bash
kubectl -n opensandbox port-forward svc/opensandbox-server 8080:8080
```

In another terminal, load the API key and run the example:

```bash
export OPEN_SANDBOX_API_KEY=$(kubectl -n opensandbox get secret opensandbox-server -o jsonpath='{.data.api-key}' | base64 -d)
OPEN_SANDBOX_DOMAIN=localhost:8080 \
SANDBOX_IMAGE=<acr-name>.azurecr.io/opensandbox-vscode:latest \
VERIFY_KATA_WITH_KUBECTL=1 \
python examples/vscode/main.py
```

Open the printed `http://127.0.0.1:<port>/` URL in a browser to use VS Code Web inside the sandbox. Keep the script running while using the browser; stopping it terminates both the local port-forward and the sandbox.

For gateway mode in the step-by-step flow, also port-forward the gateway service and set `VSCODE_ACCESS_MODE=gateway`:

```bash
kubectl -n opensandbox port-forward svc/opensandbox-ingress-gateway 8081:80
```

```bash
OPEN_SANDBOX_DOMAIN=localhost:8080 \
SANDBOX_IMAGE=<acr-name>.azurecr.io/opensandbox-vscode:latest \
VSCODE_ACCESS_MODE=gateway \
VERIFY_KATA_WITH_KUBECTL=1 \
python examples/vscode/main.py
```
