# GitHub Copilot CLI Sandbox Example

This example runs the GitHub Copilot CLI inside an OpenSandbox workload on the AKS Kata runtime configured by this repository, with Credential Vault keeping the real GitHub token out of the sandbox pod environment.

## Prerequisites

- The AKS OpenSandbox server is already deployed with `make k8s-deploy` from the repository root.
- The shared OpenSandbox ingress gateway is enabled in header mode, which is the repository default.
- `kubectl` points at the AKS cluster.
- `uv` is available.
- `COPILOT_GITHUB_TOKEN` is set locally to a fine-grained GitHub token with the `Copilot Requests` permission for an account with GitHub Copilot access.
- `make github-copilot-cli-image-push` has built and pushed the Copilot CLI sandbox image.

## Automated Run

Build and push the Copilot CLI sandbox image once after `make k8s-deploy`:

```bash
make github-copilot-cli-image-push
```

Run the GitHub Copilot CLI example from the repository root:

```bash
COPILOT_GITHUB_TOKEN=<github-token> make github-copilot-cli-example
```

Successful output looks like:

```text
make github-copilot-cli-example
Using .make.env
Using CPython 3.13.3
Creating virtual environment at: .venv
Activate with: source .venv/bin/activate
sandbox id: 2716952a-bb0b-4aee-82af-11822bf86291
credential hosts: api.github.com,github.com,api.enterprise.githubcopilot.com
egress hosts: api.github.com,github.com,copilot-proxy.githubusercontent.com,api.githubcopilot.com,api.enterprise.githubcopilot.com,copilot-telemetry.githubusercontent.com,telemetry.enterprise.githubcopilot.com
credential vault configured: 1 credential(s), 1 binding(s)
[copilot-version stdout] GitHub Copilot CLI 1.0.63.
[copilot-version stdout] Run 'copilot update' to check for updates.
[copilot-version stderr] Package extraction took 7973ms
[copilot-prompt stdout] This command retrieves information about **Kubernetes pods** in a specific namespace:
[copilot-prompt stdout] - **`kubectl`** - the Kubernetes CLI tool
[copilot-prompt stdout] - **`get pods`** - lists pod resources (running containers/workloads)
[copilot-prompt stdout] - **`-n opensandbox`** - scopes the query to the `opensandbox` namespace only (without `-n`, it defaults to the `default` namespace)
[copilot-prompt stdout] **Output** typically shows each pod's name, ready state, status (Running/Pending/Error), restart count, and age.
runtime class: kata-optimized
sandbox killed: 2716952a-bb0b-4aee-82af-11822bf86291
```

The target verifies the Copilot CLI image is present in ACR, installs SDK dependencies into `.venv` with `uv`, port-forwards the OpenSandbox server and ingress gateway, creates a sandbox with Credential Vault enabled, waits for command execution to work, runs a programmatic prompt, verifies `kata-optimized`, and kills the sandbox when finished.

Changing the Python launcher, `COPILOT_CREDENTIAL_HOSTS`, `COPILOT_EGRESS_HOSTS`, or `COPILOT_PROMPT` does not require rebuilding the Copilot sandbox image or redeploying OpenSandbox. Rebuild and push the image only when `examples/github-copilot-cli/Dockerfile` changes. Redeploy OpenSandbox only when server config under `deploy/opensandbox-server/` changes.

The real GitHub token is written to OpenSandbox Credential Vault, not to the sandbox pod environment. The sandbox only receives fake `COPILOT_GITHUB_TOKEN` and `GH_TOKEN` values. Credential Vault injects the real token as an outbound `Authorization: Bearer ...` header for matching HTTPS requests to the configured GitHub authentication hosts.

The launcher uses `use_server_proxy=False` and talks to sandbox ports through the local ingress-gateway port-forward. The repository configures the gateway address as the local development address `127.0.0.1:8081`, so local examples use client-side gateway access instead of server-proxy mode.

This repository pins Credential Vault-capable OpenSandbox components for this flow: `opensandbox-server==0.2.0`, `opensandbox==0.1.11`, and `opensandbox/egress:v1.1.1`. The sandbox image pins GitHub Copilot CLI `1.0.63` and verifies the release tarball checksum during image build.

By default, the Copilot CLI runs this prompt in non-interactive mode with shell and file-write tools denied:

```text
Explain this shell command without running it: kubectl get pods -n opensandbox
```

The launcher runs Copilot with `--no-auto-update` and `--disable-builtin-mcps` to keep the example deterministic and focused on the CLI prompt flow.

Override it when needed:

```bash
COPILOT_GITHUB_TOKEN=<github-token> \
COPILOT_PROMPT='Explain how az aks get-credentials works without running it' \
make github-copilot-cli-example
```

The example separates Credential Vault injection hosts from network egress hosts. By default, the GitHub token is injected for `api.github.com,github.com,api.enterprise.githubcopilot.com`, while egress is allowed to `api.github.com,github.com,copilot-proxy.githubusercontent.com,api.githubcopilot.com,api.enterprise.githubcopilot.com,copilot-telemetry.githubusercontent.com,telemetry.enterprise.githubcopilot.com`.

If Copilot CLI uses a subset of the supported GitHub auth hosts in your environment, override the comma-separated credential host list:

```bash
COPILOT_GITHUB_TOKEN=<github-token> \
COPILOT_CREDENTIAL_HOSTS='api.github.com,github.com,api.enterprise.githubcopilot.com' \
make github-copilot-cli-example
```

If Copilot CLI uses additional model or telemetry hosts, override the egress host list. The credential host list is intentionally restricted to the known GitHub/Copilot auth hosts so arbitrary egress hosts do not receive the GitHub token:

```bash
COPILOT_GITHUB_TOKEN=<github-token> \
COPILOT_EGRESS_HOSTS='api.github.com,github.com,copilot-proxy.githubusercontent.com,api.githubcopilot.com,api.enterprise.githubcopilot.com,copilot-telemetry.githubusercontent.com,telemetry.enterprise.githubcopilot.com' \
make github-copilot-cli-example
```

## Step-By-Step Run

Build and push the sandbox image:

```bash
make github-copilot-cli-image-push
```

Install the SDK into the repository virtual environment:

```bash
uv venv --allow-existing .venv
uv pip install --python .venv -r examples/github-copilot-cli/requirements.txt
```

Port-forward the OpenSandbox server:

```bash
kubectl -n opensandbox port-forward svc/opensandbox-server 8080:8080
```

Port-forward the OpenSandbox ingress gateway in a second terminal:

```bash
kubectl -n opensandbox port-forward svc/opensandbox-ingress-gateway 8081:80
```

In another terminal, load the API key from the Kubernetes Secret and run the client:

```bash
export OPEN_SANDBOX_API_KEY=$(kubectl -n opensandbox get secret opensandbox-server -o jsonpath='{.data.api-key}' | base64 -d)
export COPILOT_GITHUB_TOKEN=<github-token>
export SANDBOX_IMAGE=<acr-login-server>/opensandbox-copilot-cli:latest

OPEN_SANDBOX_DOMAIN=localhost:8080 \
VERIFY_KATA_WITH_KUBECTL=1 \
uv run --no-project --python .venv/bin/python python examples/github-copilot-cli/main.py
```

The script passes fake token values into the sandbox, stores the real token in Credential Vault, uses the preinstalled GitHub Copilot CLI, then runs:

```bash
copilot -p 'Explain this shell command without running it: kubectl get pods -n opensandbox' -s --no-ask-user --allow-all --deny-tool=shell --deny-tool=write
```

Credential Vault can only inject credentials into outbound network requests. If a future Copilot CLI release locally validates the token before making network requests, or refuses the fake token before the sidecar can inject the real header, this example will fail early. In that case, use the direct environment-token delivery path only for disposable trusted tests, or update the host/binding strategy to match the CLI's current authentication flow.
