import asyncio
import inspect
import json
import os
import socket
import subprocess
import sys
from urllib.parse import urlparse
import urllib.error
import urllib.request
from datetime import timedelta

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


def free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def find_sandbox_pod(namespace: str, sandbox_id: str) -> tuple[str, str]:
    for _ in range(60):
        batchsandbox = subprocess.run(
            [
                "kubectl",
                "get",
                "batchsandbox",
                sandbox_id,
                "-n",
                namespace,
                "-o",
                "json",
            ],
            capture_output=True,
            check=False,
            text=True,
        )
        endpoints: set[str] = set()
        if batchsandbox.returncode == 0:
            try:
                batchsandbox_json = json.loads(batchsandbox.stdout)
                endpoints_annotation = (
                    batchsandbox_json.get("metadata", {})
                    .get("annotations", {})
                    .get("sandbox.opensandbox.io/endpoints", "[]")
                )
                endpoints = set(json.loads(endpoints_annotation))
            except json.JSONDecodeError:
                endpoints = set()

        if endpoints:
            pods = subprocess.run(
                ["kubectl", "get", "pods", "-n", namespace, "-o", "json"],
                capture_output=True,
                check=False,
                text=True,
            )
            if pods.returncode == 0:
                try:
                    pod_items = json.loads(pods.stdout).get("items", [])
                except json.JSONDecodeError:
                    pod_items = []
                for pod in pod_items:
                    status = pod.get("status", {})
                    if status.get("phase") == "Running" and status.get("podIP") in endpoints:
                        return pod["metadata"]["name"], status["podIP"]

        await asyncio.sleep(1)

    raise RuntimeError(f"Could not find a running pod for sandbox {sandbox_id}")


def create_proxy_pod(
    namespace: str,
    name: str,
    image: str,
    target_host: str,
    target_port: int,
    listen_port: int,
) -> None:
    proxy_code = r'''
import os
import socket
import threading

target = (os.environ["TARGET_HOST"], int(os.environ["TARGET_PORT"]))
listen_port = int(os.environ["LISTEN_PORT"])

def close(sock):
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except Exception:
        pass
    try:
        sock.close()
    except Exception:
        pass

def pipe(src, dst):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    finally:
        close(src)
        close(dst)

def handle(client):
    try:
        upstream = socket.create_connection(target, timeout=10)
    except Exception:
        close(client)
        return
    threading.Thread(target=pipe, args=(client, upstream), daemon=True).start()
    threading.Thread(target=pipe, args=(upstream, client), daemon=True).start()

listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listener.bind(("0.0.0.0", listen_port))
listener.listen(128)
print(f"proxy listening on {listen_port} -> {target[0]}:{target[1]}", flush=True)

while True:
    client, _ = listener.accept()
    threading.Thread(target=handle, args=(client,), daemon=True).start()
'''
    manifest = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {"app.kubernetes.io/name": "opensandbox-vscode-proxy"},
        },
        "spec": {
            "automountServiceAccountToken": False,
            "restartPolicy": "Never",
            "terminationGracePeriodSeconds": 1,
            "securityContext": {
                "runAsNonRoot": True,
                "runAsUser": 1000,
                "runAsGroup": 1000,
                "seccompProfile": {"type": "RuntimeDefault"},
            },
            "containers": [
                {
                    "name": "proxy",
                    "image": image,
                    "imagePullPolicy": "IfNotPresent",
                    "command": ["python3", "-c", proxy_code],
                    "securityContext": {
                        "allowPrivilegeEscalation": False,
                        "capabilities": {"drop": ["ALL"]},
                    },
                    "env": [
                        {"name": "TARGET_HOST", "value": target_host},
                        {"name": "TARGET_PORT", "value": str(target_port)},
                        {"name": "LISTEN_PORT", "value": str(listen_port)},
                    ],
                    "ports": [{"containerPort": listen_port, "name": "http"}],
                    "resources": {
                        "requests": {"cpu": "50m", "memory": "64Mi"},
                        "limits": {"cpu": "250m", "memory": "128Mi"},
                    },
                }
            ],
        },
    }
    apply = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=json.dumps(manifest),
        capture_output=True,
        check=False,
        text=True,
    )
    if apply.returncode != 0:
        raise RuntimeError(f"Failed to create proxy pod:\n{apply.stderr or apply.stdout}")


def wait_for_proxy_pod(namespace: str, name: str) -> None:
    wait = subprocess.run(
        [
            "kubectl",
            "wait",
            "--for=condition=Ready",
            f"pod/{name}",
            "-n",
            namespace,
            "--timeout=120s",
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    if wait.returncode == 0:
        return

    logs = subprocess.run(
        ["kubectl", "logs", f"pod/{name}", "-n", namespace, "--tail=80"],
        capture_output=True,
        check=False,
        text=True,
    )
    raise RuntimeError(
        "Proxy pod did not become ready:\n"
        f"{wait.stderr or wait.stdout}\n{logs.stderr or logs.stdout}"
    )


def delete_proxy_pod(namespace: str, name: str) -> None:
    subprocess.run(
        ["kubectl", "delete", "pod", name, "-n", namespace, "--ignore-not-found"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def start_port_forward(namespace: str, pod_name: str, local_port: int, remote_port: int):
    return subprocess.Popen(
        [
            "kubectl",
            "-n",
            namespace,
            "port-forward",
            "--address",
            "127.0.0.1",
            f"pod/{pod_name}",
            f"{local_port}:{remote_port}",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def start_gateway_route_proxy(gateway_url: str, local_port: int):
    parsed = urlparse(gateway_url)
    if not parsed.hostname:
        raise RuntimeError(f"Could not parse gateway endpoint URL: {gateway_url}")
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise RuntimeError(
            "Gateway mode for this local example requires the gateway endpoint "
            f"to be localhost, got: {gateway_url}"
        )
    target_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    route_prefix = parsed.path.rstrip("/")
    if not route_prefix:
        raise RuntimeError(f"Gateway endpoint URL has no route prefix: {gateway_url}")

    proxy_code = r'''
import os
import socket
import threading

target = (os.environ["TARGET_HOST"], int(os.environ["TARGET_PORT"]))
listen_port = int(os.environ["LISTEN_PORT"])
route_prefix = os.environ["ROUTE_PREFIX"].rstrip("/")

def close(sock):
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except Exception:
        pass
    try:
        sock.close()
    except Exception:
        pass

def pipe(src, dst):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    finally:
        close(src)
        close(dst)

def rewrite_request(data):
    try:
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
            method, target_path, version = parts
            if target_path.startswith("/") and not (
                target_path == route_prefix or target_path.startswith(route_prefix + "/")
            ):
                target_path = route_prefix + target_path
            lines[0] = f"{method} {target_path} {version}"
        rewritten_lines = [lines[0]]
        for line in lines[1:]:
            lower_line = line.lower()
            if is_websocket and lower_line.startswith("origin:"):
                continue
            if lower_line.startswith("host:"):
                rewritten_lines.append(f"Host: {target[0]}:{target[1]}")
            else:
                rewritten_lines.append(line)
        lines = rewritten_lines
        if not is_websocket:
            for index, line in enumerate(lines[1:], 1):
                if line.lower().startswith("connection:"):
                    lines[index] = "Connection: close"
                    break
            else:
                lines.append("Connection: close")
        return "\r\n".join(lines).encode("iso-8859-1") + body
    except Exception:
        return data

def handle(client):
    data = b""
    try:
        client.settimeout(10)
        while b"\r\n\r\n" not in data and len(data) < 65536:
            chunk = client.recv(65536)
            if not chunk:
                close(client)
                return
            data += chunk
        upstream = socket.create_connection(target, timeout=10)
        upstream.sendall(rewrite_request(data))
        client.settimeout(None)
        upstream.settimeout(None)
    except Exception:
        close(client)
        return
    threading.Thread(target=pipe, args=(client, upstream), daemon=True).start()
    threading.Thread(target=pipe, args=(upstream, client), daemon=True).start()

listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listener.bind(("127.0.0.1", listen_port))
listener.listen(128)
print(
    f"gateway route proxy listening on 127.0.0.1:{listen_port} -> "
    f"{target[0]}:{target[1]}{route_prefix}",
    flush=True,
)

while True:
    client, _ = listener.accept()
    threading.Thread(target=handle, args=(client,), daemon=True).start()
'''
    return subprocess.Popen(
        [sys.executable, "-u", "-c", proxy_code],
        env={
            **os.environ,
            "TARGET_HOST": parsed.hostname,
            "TARGET_PORT": str(target_port),
            "LISTEN_PORT": str(local_port),
            "ROUTE_PREFIX": route_prefix,
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def normalize_browser_url(endpoint) -> str:
    value = getattr(endpoint, "endpoint", endpoint)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"Unexpected sandbox endpoint response: {endpoint!r}")
    if value.startswith("http://") or value.startswith("https://"):
        url = value
    else:
        url = f"http://{value}"
    return url if url.endswith("/") else f"{url}/"


async def get_sandbox_endpoint(sandbox: Sandbox, port: int):
    endpoint = sandbox.get_endpoint(port)
    if inspect.isawaitable(endpoint):
        return await endpoint
    return endpoint


async def wait_for_http(url: str, process: subprocess.Popen, timeout_seconds: int) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    last_error = ""
    while asyncio.get_running_loop().time() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            raise RuntimeError(f"kubectl port-forward exited early:\n{output}")
        try:
            with urllib.request.urlopen(url, timeout=1):
                return
        except urllib.error.HTTPError:
            return
        except Exception as exc:
            last_error = str(exc)
            await asyncio.sleep(1)

    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def first_stdout_text(execution) -> str:
    if not execution.logs.stdout:
        return ""
    return "".join(chunk.text for chunk in execution.logs.stdout).strip()


def first_stderr_text(execution) -> str:
    if not execution.logs.stderr:
        return ""
    return "".join(chunk.text for chunk in execution.logs.stderr).strip()


async def wait_for_code_server(sandbox: Sandbox, code_port: int) -> None:
    for _ in range(60):
        probe = await sandbox.commands.run(
            f"curl -fsS http://127.0.0.1:{code_port}/ >/dev/null && echo READY"
        )
        if probe.exit_code == 0 and first_stdout_text(probe) == "READY":
            return

        status = await sandbox.commands.run(
            "test -s /tmp/code-server.log && tail -n 40 /tmp/code-server.log || true"
        )
        log_text = first_stdout_text(status) or first_stderr_text(status)
        lower_log = log_text.lower()
        if (
            "bind:" in lower_log
            or "address already in use" in lower_log
            or "permission denied" in lower_log
            or "code-server: not found" in lower_log
        ):
            raise RuntimeError(f"code-server failed to start:\n{log_text}")

        await asyncio.sleep(1)

    logs = await sandbox.commands.run(
        "test -s /tmp/code-server.log && tail -n 80 /tmp/code-server.log || true"
    )
    log_text = first_stdout_text(logs) or first_stderr_text(logs)
    raise RuntimeError(f"Timed out waiting for code-server on port {code_port}:\n{log_text}")


async def main() -> None:
    domain = os.getenv("OPEN_SANDBOX_DOMAIN", "localhost:8080")
    api_key = os.getenv("OPEN_SANDBOX_API_KEY", "dev-api-key")
    image = os.getenv("SANDBOX_IMAGE", "opensandbox-vscode:latest")
    proxy_image = os.getenv("VSCODE_PROXY_IMAGE", "python:3.12-slim")
    access_mode = os.getenv("VSCODE_ACCESS_MODE", "helper-proxy")
    code_port = int(os.getenv("CODE_PORT", "8443"))
    local_code_port = int(os.getenv("VSCODE_LOCAL_PORT") or free_local_port())
    keepalive_seconds = int(os.getenv("KEEPALIVE_SECONDS", "600"))
    namespace = os.getenv("OPEN_SANDBOX_NAMESPACE", "opensandbox")

    config = ConnectionConfig(
        domain=domain,
        api_key=api_key,
        request_timeout=timedelta(seconds=90),
        use_server_proxy=access_mode != "gateway",
    )

    sandbox = await Sandbox.create(
        image,
        connection_config=config,
        timeout=timedelta(minutes=15),
        resource={"cpu": "1", "memory": "2Gi"},
        metadata={"example": "aks-kata-vscode"},
    )

    port_forward = None
    proxy_pod_name = f"vscode-proxy-{sandbox.id}"
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

            if access_mode == "gateway":
                endpoint = await get_sandbox_endpoint(sandbox, code_port)
                gateway_url = normalize_browser_url(endpoint)
                port_forward = start_gateway_route_proxy(gateway_url, local_code_port)
                vscode_url = f"http://127.0.0.1:{local_code_port}/"
                await wait_for_http(vscode_url, port_forward, 30)
                print(f"gateway route: {gateway_url}")
                print("access mode: shared OpenSandbox ingress gateway")
            elif access_mode == "helper-proxy":
                pod_name, sandbox_ip = await find_sandbox_pod(namespace, sandbox.id)
                print(f"sandbox pod: {pod_name}")
                print(f"sandbox endpoint ip: {sandbox_ip}")
                create_proxy_pod(
                    namespace,
                    proxy_pod_name,
                    proxy_image,
                    sandbox_ip,
                    code_port,
                    code_port,
                )
                wait_for_proxy_pod(namespace, proxy_pod_name)
                port_forward = start_port_forward(
                    namespace, proxy_pod_name, local_code_port, code_port
                )
                vscode_url = f"http://127.0.0.1:{local_code_port}/"
                await wait_for_http(vscode_url, port_forward, 30)
                print("access mode: temporary helper proxy pod")
            else:
                raise RuntimeError(
                    "VSCODE_ACCESS_MODE must be 'gateway' or 'helper-proxy'"
                )

            print("VS Code Web endpoint:")
            print(f"  {vscode_url}")

            if os.getenv("VERIFY_KATA_WITH_KUBECTL") == "1":
                for _ in range(30):
                    result = subprocess.run(
                        [
                            "kubectl",
                            "get",
                            "batchsandbox",
                            sandbox.id,
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
                        break
                    await asyncio.sleep(1)
                else:
                    raise RuntimeError(
                        f"Sandbox {sandbox.id} did not use runtimeClassName=kata-optimized"
                    )

            print(f"Keeping sandbox alive for {keepalive_seconds} seconds.")
            print("Press Ctrl+C to stop and delete the sandbox.")
            await asyncio.sleep(keepalive_seconds)
        except KeyboardInterrupt:
            print("Stopping VS Code sandbox")
        finally:
            if port_forward and port_forward.poll() is None:
                port_forward.terminate()
                try:
                    port_forward.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    port_forward.kill()
            delete_proxy_pod(namespace, proxy_pod_name)
            await sandbox.kill()
            print(f"sandbox killed: {sandbox.id}")


if __name__ == "__main__":
    asyncio.run(main())
