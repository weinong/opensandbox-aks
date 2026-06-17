import asyncio
import inspect
import os
import socket
import subprocess
import urllib.error
import urllib.request
from datetime import timedelta
from urllib.parse import urlparse

from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.models.execd import RunCommandOpts


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


def free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def get_sandbox_endpoint(sandbox: Sandbox, port: int):
    endpoint = sandbox.get_endpoint(port)
    if inspect.isawaitable(endpoint):
        return await endpoint
    return endpoint


def normalize_gateway_url(endpoint) -> str:
    value = getattr(endpoint, "endpoint", endpoint)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"Unexpected sandbox endpoint response: {endpoint!r}")
    url = value if value.startswith(("http://", "https://")) else f"http://{value}"
    return url if url.endswith("/") else f"{url}/"


def parse_gateway_route(gateway_url: str) -> tuple[str, int, str]:
    parsed = urlparse(gateway_url)
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise RuntimeError(
            "This local example expects the gateway endpoint to be localhost, "
            f"got: {gateway_url}"
        )
    route_prefix = parsed.path.rstrip("/")
    if not route_prefix:
        raise RuntimeError(f"Gateway endpoint URL has no route prefix: {gateway_url}")
    target_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.hostname, target_port, route_prefix


def rewrite_request(data: bytes, route_prefix: str, target_host: str, target_port: int) -> bytes:
    header_end = data.find(b"\r\n\r\n")
    if header_end < 0:
        return data

    headers = data[:header_end].decode("iso-8859-1")
    body = data[header_end:]
    lines = headers.split("\r\n")
    is_websocket = any(
        line.lower().startswith("upgrade:") and "websocket" in line.lower()
        for line in lines[1:]
    )

    parts = lines[0].split(" ", 2)
    if len(parts) == 3:
        method, path, version = parts
        if path.startswith("/") and path != route_prefix and not path.startswith(
            route_prefix + "/"
        ):
            path = route_prefix + path
        lines[0] = f"{method} {path} {version}"

    rewritten = [lines[0]]
    has_connection = False
    for line in lines[1:]:
        lower = line.lower()
        if is_websocket and lower.startswith("origin:"):
            continue
        if lower.startswith("host:"):
            rewritten.append(f"Host: {target_host}:{target_port}")
        elif lower.startswith("connection:") and not is_websocket:
            rewritten.append("Connection: close")
            has_connection = True
        else:
            rewritten.append(line)

    if not is_websocket and not has_connection:
        rewritten.append("Connection: close")
    return "\r\n".join(rewritten).encode("iso-8859-1") + body


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()


async def proxy_gateway_request(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    target_host: str,
    target_port: int,
    route_prefix: str,
) -> None:
    try:
        data = await client_reader.readuntil(b"\r\n\r\n")
        gateway_reader, gateway_writer = await asyncio.open_connection(
            target_host, target_port
        )
        gateway_writer.write(
            rewrite_request(data, route_prefix, target_host, target_port)
        )
        await gateway_writer.drain()
        await asyncio.gather(
            pipe(client_reader, gateway_writer),
            pipe(gateway_reader, client_writer),
        )
    except Exception:
        client_writer.close()


async def start_gateway_route_proxy(
    gateway_url: str, local_port: int
) -> asyncio.AbstractServer:
    target_host, target_port, route_prefix = parse_gateway_route(gateway_url)
    return await asyncio.start_server(
        lambda reader, writer: proxy_gateway_request(
            reader, writer, target_host, target_port, route_prefix
        ),
        "127.0.0.1",
        local_port,
    )


def request_once(url: str) -> None:
    with urllib.request.urlopen(url, timeout=1):
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
    local_code_port = int(os.getenv("VSCODE_LOCAL_PORT") or free_local_port())
    proxy_server = None

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
            start_exec = await sandbox.commands.run(
                "sh -lc "
                f"'code-server --bind-addr 0.0.0.0:{code_port} --auth none /workspace "
                ">/tmp/code-server.log 2>&1'",
                opts=RunCommandOpts(background=True),
            )
            await print_logs("code-server", start_exec)
            await wait_for_code_server(sandbox, code_port)
            print(f"code-server ready on sandbox port {code_port}")

            gateway_url = normalize_gateway_url(
                await get_sandbox_endpoint(sandbox, code_port)
            )
            proxy_server = await start_gateway_route_proxy(gateway_url, local_code_port)
            vscode_url = f"http://127.0.0.1:{local_code_port}/"
            await wait_for_http(vscode_url, 30)

            print(f"gateway route: {gateway_url}")
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
            if proxy_server:
                proxy_server.close()
                await proxy_server.wait_closed()
            await sandbox.kill()
            print(f"sandbox killed: {sandbox.id}")


if __name__ == "__main__":
    asyncio.run(main())
