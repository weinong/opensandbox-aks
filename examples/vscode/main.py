import asyncio
import inspect
import os
import shlex
import subprocess
import urllib.error
import urllib.request
from datetime import timedelta
from urllib.parse import urlparse

from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.models.execd import RunCommandOpts


INGRESS_ROUTE_HEADER = "OpenSandbox-Ingress-To"


async def print_logs(label: str, execution) -> None:
    for message in execution.logs.stdout:
        text = message.text.strip()
        if text:
            print(f"[{label} stdout] {text}")
    for message in execution.logs.stderr:
        text = message.text.strip()
        if text:
            print(f"[{label} stderr] {text}")
    if execution.error:
        print(f"[{label} error] {execution.error.name}: {execution.error.value}")


def execution_stdout(execution) -> str:
    return "".join(chunk.text for chunk in execution.logs.stdout).strip()


def execution_stderr(execution) -> str:
    return "".join(chunk.text for chunk in execution.logs.stderr).strip()


async def get_sandbox_endpoint(sandbox: Sandbox, port: int):
    endpoint = sandbox.get_endpoint(port)
    if inspect.isawaitable(endpoint):
        return await endpoint
    return endpoint


def endpoint_value(endpoint) -> str:
    value = getattr(endpoint, "endpoint", endpoint)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"Unexpected sandbox endpoint response: {endpoint!r}")
    return value


def endpoint_header(endpoint, name: str) -> str | None:
    headers = getattr(endpoint, "headers", None) or {}
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None


def host_routed_gateway_url(sandbox_id: str, port: int) -> str:
    domain = os.getenv("VSCODE_GATEWAY_DOMAIN", "127.0.0.1.nip.io").strip().strip(".")
    if not domain or ":" in domain or "/" in domain:
        raise RuntimeError(
            "VSCODE_GATEWAY_DOMAIN must be a bare wildcard DNS suffix, "
            "for example 127.0.0.1.nip.io"
        )
    gateway_port = int(os.getenv("INGRESS_GATEWAY_LOCAL_PORT", "8081"))
    scheme = os.getenv("VSCODE_GATEWAY_SCHEME", "http").strip() or "http"
    host = f"{sandbox_id}-{port}.{domain}"
    port_suffix = (
        "" if (scheme, gateway_port) in {("http", 80), ("https", 443)}
        else f":{gateway_port}"
    )
    return f"{scheme}://{host}{port_suffix}/"


def ensure_header_mode_endpoint(endpoint, sandbox_id: str, port: int) -> None:
    expected_route = f"{sandbox_id}-{port}"
    route = endpoint_header(endpoint, INGRESS_ROUTE_HEADER)
    if route == expected_route:
        return
    if route:
        raise RuntimeError(
            f"Unexpected {INGRESS_ROUTE_HEADER} route {route!r}; expected {expected_route!r}"
        )

    raise RuntimeError(
        "VS Code no-proxy browser access requires OpenSandbox ingress gateway "
        f"header mode, but endpoint {endpoint_value(endpoint)!r} did not include "
        f"{INGRESS_ROUTE_HEADER}. Redeploy with INGRESS_GATEWAY_ROUTE_MODE=header."
    )


def request_once(url: str) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=1):
        pass


async def wait_for_http(url: str, timeout_seconds: int) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    last_error = ""
    while asyncio.get_running_loop().time() < deadline:
        try:
            await asyncio.to_thread(request_once, url)
            return
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}"
        except Exception as exc:
            last_error = str(exc)
        await asyncio.sleep(1)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


async def wait_for_code_server(sandbox: Sandbox, code_port: int) -> None:
    for _ in range(60):
        probe = await sandbox.commands.run(
            f"curl -fsS http://127.0.0.1:{code_port}/ >/dev/null && echo READY"
        )
        if probe.exit_code == 0 and execution_stdout(probe) == "READY":
            return

        status = await sandbox.commands.run(
            "test -s /tmp/code-server.log && tail -n 40 /tmp/code-server.log || true"
        )
        log_text = execution_stdout(status) or execution_stderr(status)
        if any(
            text in log_text.lower()
            for text in (
                "bind:",
                "address already in use",
                "permission denied",
                "code-server: not found",
            )
        ):
            raise RuntimeError(f"code-server failed to start:\n{log_text}")

        await asyncio.sleep(1)

    logs = await sandbox.commands.run(
        "test -s /tmp/code-server.log && tail -n 80 /tmp/code-server.log || true"
    )
    raise RuntimeError(
        f"Timed out waiting for code-server on port {code_port}:\n"
        f"{execution_stdout(logs) or execution_stderr(logs)}"
    )


async def verify_kata_runtime(namespace: str, sandbox_id: str) -> None:
    for _ in range(30):
        result = subprocess.run(
            [
                "kubectl",
                "get",
                "batchsandbox",
                sandbox_id,
                "-n",
                namespace,
                "-o",
                "jsonpath={.spec.template.spec.runtimeClassName}",
            ],
            capture_output=True,
            check=False,
            text=True,
        )
        if result.stdout.strip() == "kata-optimized":
            print("runtime class: kata-optimized")
            return
        await asyncio.sleep(1)
    raise RuntimeError(f"Sandbox {sandbox_id} did not use runtimeClassName=kata-optimized")


async def main() -> None:
    code_port = int(os.getenv("CODE_PORT", "8443"))
    keepalive_seconds = int(os.getenv("KEEPALIVE_SECONDS", "600"))
    namespace = os.getenv("OPEN_SANDBOX_NAMESPACE", "opensandbox")

    sandbox = await Sandbox.create(
        os.getenv("SANDBOX_IMAGE", "opensandbox-vscode:latest"),
        connection_config=ConnectionConfig(
            domain=os.getenv("OPEN_SANDBOX_DOMAIN", "localhost:8080"),
            api_key=os.getenv("OPEN_SANDBOX_API_KEY", "dev-api-key"),
            request_timeout=timedelta(seconds=90),
            use_server_proxy=False,
        ),
        timeout=timedelta(minutes=15),
        resource={"cpu": "1", "memory": "2Gi"},
        metadata={"example": "aks-kata-vscode"},
    )

    async with sandbox:
        try:
            print(f"sandbox id: {sandbox.id}")
            vscode_url = host_routed_gateway_url(sandbox.id, code_port)
            trusted_origin = urlparse(vscode_url).netloc
            start_exec = await sandbox.commands.run(
                "sh -lc "
                + shlex.quote(
                    f"code-server --bind-addr 0.0.0.0:{code_port} "
                    f"--auth none --trusted-origins {trusted_origin} /workspace "
                    ">/tmp/code-server.log 2>&1"
                ),
                opts=RunCommandOpts(background=True),
            )
            await print_logs("code-server", start_exec)
            await wait_for_code_server(sandbox, code_port)
            print(f"code-server ready on sandbox port {code_port}")

            endpoint = await get_sandbox_endpoint(sandbox, code_port)
            ensure_header_mode_endpoint(endpoint, sandbox.id, code_port)
            await wait_for_http(vscode_url, 30)

            print(f"gateway endpoint: {endpoint_value(endpoint)}")
            print(
                f"gateway route header: {INGRESS_ROUTE_HEADER}: "
                f"{endpoint_header(endpoint, INGRESS_ROUTE_HEADER)}"
            )
            print("VS Code Web endpoint:")
            print(f"  {vscode_url}")

            if os.getenv("VERIFY_KATA_WITH_KUBECTL") == "1":
                await verify_kata_runtime(namespace, sandbox.id)

            print(f"Keeping sandbox alive for {keepalive_seconds} seconds.")
            print("Press Ctrl+C to stop and delete the sandbox.")
            await asyncio.sleep(keepalive_seconds)
        except asyncio.CancelledError:
            print("Stopping VS Code sandbox")
            raise
        finally:
            await sandbox.kill()
            print(f"sandbox killed: {sandbox.id}")


if __name__ == "__main__":
    asyncio.run(main())
