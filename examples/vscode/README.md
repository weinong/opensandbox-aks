# VS Code Web Sandbox Example

This example runs [code-server](https://github.com/coder/code-server), a browser-accessible VS Code build, inside an OpenSandbox workload on the AKS Kata runtime configured by this repository.

It is adapted from the upstream OpenSandbox [`examples/vscode`](https://github.com/opensandbox-group/OpenSandbox/tree/main/examples/vscode) example, but uses the deployed AKS lifecycle server, the configured Azure Container Registry, and the `kata-optimized` RuntimeClass.

## Prerequisites

- The AKS OpenSandbox server is already deployed with `make k8s-deploy` from the repository root.
- Container images are prepared with the repository image targets. Run `make vscode-image-push` for this example image, or `make images-push` to build and push all repository images.
- `kubectl` points at the AKS cluster.
- `docker`, `az`, `uv`, and `curl` are available locally.
- The configured ACR is reachable by the OpenSandbox workload pods. The default managed identity `AcrPull` path from this repo handles that for images pushed to `$(ACR_NAME).azurecr.io`.

## Automated Run

Port-forward the OpenSandbox server and shared ingress gateway, create a sandbox from the already-pushed VS Code image, start `code-server`, and print the browser URL:

```bash
make vscode-example
```

The target uses these defaults:

```text
VSCODE_IMAGE_NAME=opensandbox-vscode
VSCODE_IMAGE_TAG=latest
VSCODE_PORT=8443
ENABLE_INGRESS_GATEWAY=true
INGRESS_GATEWAY_ROUTE_MODE=header
VSCODE_GATEWAY_DOMAIN=127.0.0.1.nip.io
```

The image installs pinned `code-server` release `4.124.2` from the upstream `.deb` package and verifies the package SHA-256 during build.

`make vscode-example` does not rebuild or push the container image. Re-run `make vscode-image-push` after changing `examples/vscode/Dockerfile` or related image contents, and use a unique `VSCODE_IMAGE_TAG` when you need to avoid reusing a stale mutable tag such as `latest`.

The printed VS Code URL uses the shared OpenSandbox ingress gateway because VS Code Web requires browser HTTP and WebSocket traffic. The launcher waits for `code-server` to answer inside the sandbox, then prints a host-routed gateway URL.

The example starts `code-server` with `--auth none` and binds browser access to `127.0.0.1` through local port-forwarding. Treat it as a disposable single-user development example; do not expose the printed URL or raw gateway port on a shared network.

`make k8s-deploy` deploys the shared OpenSandbox ingress gateway by default and configures the lifecycle server for gateway header routing:

```bash
make k8s-deploy
make vscode-image-push
make vscode-example
```

`make vscode-example` port-forwards the single shared `opensandbox-ingress-gateway` service on `INGRESS_GATEWAY_LOCAL_PORT` and prints a browser URL such as `http://<sandbox-id>-8443.127.0.0.1.nip.io:8081/`. The browser sends that host in the normal `Host` header, and the gateway uses it to route directly to the sandbox while preserving the request path as `/`. This keeps `code-server` mounted at `/`, which is required for its root-relative workbench assets, without a local path-rewriting proxy.

Open the printed `VS Code Web endpoint`, not the raw gateway port. The raw gateway port, for example `http://127.0.0.1:8081/`, has no sandbox route in its host and returns `OpenSandbox Ingress: invalid ingress route` for `/`.

If you previously deployed with URI routing, redeploy before running this example:

```bash
INGRESS_GATEWAY_ROUTE_MODE=header make k8s-deploy
```

If you explicitly disable the gateway with `ENABLE_INGRESS_GATEWAY=false`, or deploy it with a route mode other than `header`, `make vscode-example` will fail early. Redeploy with `make k8s-deploy` before running this example.

## How It Works

`kubectl -n opensandbox get pods` should show the sandbox workload pod:

```text
<sandbox-id>-0              1/1     Running
```

The `<sandbox-id>-0` pod is the actual OpenSandbox workload. It is created by the OpenSandbox controller from the `BatchSandbox` resource, runs the VS Code image, and uses the `kata-optimized` RuntimeClass. `code-server` runs in this sandbox on port `8443`.

Traffic flow:

```text
browser -> <sandbox-id>-8443.127.0.0.1.nip.io:<gateway-local-port>/ -> kubectl port-forward -> opensandbox-ingress-gateway -> <sandbox-endpoint-ip>:8443 -> code-server in <sandbox-id>-0
```

Example resources are cleaned up when the script exits normally or when you press `Ctrl+C`. If the process is interrupted abruptly, clean up with:

```bash
kubectl delete batchsandbox -n opensandbox <sandbox-id>
```

The example keeps the sandbox alive for 10 minutes. Override that duration when needed:

```bash
KEEPALIVE_SECONDS=1800 make vscode-example
```

Use a fixed local gateway port when needed:

```bash
INGRESS_GATEWAY_LOCAL_PORT=18443 make vscode-example
```

Press `Ctrl+C` to stop early. The script kills the sandbox on exit.

## Step-By-Step Run

Build and push the image to ACR:

```bash
make vscode-image-push
```

Install the SDK into the repository virtual environment:

```bash
uv venv --allow-existing .venv
uv pip install --python .venv -r examples/vscode/requirements.txt
```

Port-forward the OpenSandbox server and ingress gateway in separate terminals:

```bash
kubectl -n opensandbox port-forward svc/opensandbox-server 8080:8080
```

```bash
kubectl -n opensandbox port-forward svc/opensandbox-ingress-gateway 8081:80
```

In another terminal, load the API key and run the example:

```bash
export OPEN_SANDBOX_API_KEY=$(kubectl -n opensandbox get secret opensandbox-server -o jsonpath='{.data.api-key}' | base64 -d)
OPEN_SANDBOX_DOMAIN=localhost:8080 \
SANDBOX_IMAGE=<acr-name>.azurecr.io/opensandbox-vscode:latest \
INGRESS_GATEWAY_LOCAL_PORT=8081 \
VERIFY_KATA_WITH_KUBECTL=1 \
uv run --no-project --python .venv/bin/python python examples/vscode/main.py
```

Open the printed `http://<sandbox-id>-8443.127.0.0.1.nip.io:8081/` URL in a browser to use VS Code Web inside the sandbox. Keep the script running while using the browser; stopping it terminates both the local port-forward and the sandbox.
