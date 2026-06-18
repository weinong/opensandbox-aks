import asyncio
import os
import subprocess
import time
from datetime import timedelta

from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.manager import SandboxManager
from opensandbox.models import SandboxState, WriteEntry


STATE_FILE = "/tmp/opensandbox-pause-renew.txt"


def stdout_text(execution) -> str:
    if not execution.logs.stdout:
        return ""
    return "".join(chunk.text for chunk in execution.logs.stdout).strip()


def batchsandbox_phase(sandbox_id: str, namespace: str) -> str:
    try:
        return subprocess.check_output(
            [
                "kubectl",
                "get",
                "batchsandbox",
                sandbox_id,
                "-n",
                namespace,
                "-o",
                "jsonpath={.status.phase}",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ""


def wait_for_phase(sandbox_id: str, namespace: str, expected: str, timeout_seconds: int) -> None:
    deadline = time.time() + timeout_seconds
    last_phase = ""
    while time.time() < deadline:
        last_phase = batchsandbox_phase(sandbox_id, namespace)
        if last_phase == expected:
            print(f"batchsandbox phase: {expected}")
            return
        time.sleep(2)

    raise RuntimeError(
        f"Timed out waiting for BatchSandbox {sandbox_id} phase {expected!r}; last phase was {last_phase!r}"
    )


async def wait_for_sandbox_state(
    sandbox_id: str,
    config: ConnectionConfig,
    expected: str,
    timeout_seconds: int,
) -> None:
    manager = await SandboxManager.create(connection_config=config)
    deadline = time.time() + timeout_seconds
    last_state = ""
    try:
        while time.time() < deadline:
            info = await manager.get_sandbox_info(sandbox_id)
            last_state = info.status.state
            if last_state == expected:
                print(f"sandbox state: {expected}")
                return
            await asyncio.sleep(2)
    finally:
        await manager.close()

    raise RuntimeError(
        f"Timed out waiting for sandbox {sandbox_id} state {expected!r}; last state was {last_state!r}"
    )


def make_connection_config(domain: str, api_key: str) -> ConnectionConfig:
    return ConnectionConfig(
        domain=domain,
        api_key=api_key,
        request_timeout=timedelta(seconds=120),
        use_server_proxy=False,
    )


async def main() -> None:
    domain = os.getenv("OPEN_SANDBOX_DOMAIN", "localhost:8080")
    api_key = os.getenv("OPEN_SANDBOX_API_KEY")
    image = os.getenv("SANDBOX_IMAGE", "python:3.12-slim")
    namespace = os.getenv("OPEN_SANDBOX_NAMESPACE", "opensandbox")
    verify_with_kubectl = os.getenv("VERIFY_WITH_KUBECTL") == "1"

    if not api_key:
        raise RuntimeError("OPEN_SANDBOX_API_KEY is required")

    config = make_connection_config(domain, api_key)

    sandbox = None
    sandbox_id = ""
    sandbox = await Sandbox.create(
        image,
        connection_config=config,
        timeout=timedelta(minutes=10),
        resource={"cpu": "500m", "memory": "512Mi"},
        metadata={"example": "pause-renew"},
    )

    sandbox_id = sandbox.id
    print(f"sandbox id: {sandbox_id}")

    try:
        renew_response = await sandbox.renew(timedelta(minutes=30))
        print(f"renewed expiration: {renew_response.expires_at}")

        await sandbox.files.write_files(
            [
                WriteEntry(
                    path=STATE_FILE,
                    data=f"state survived pause/resume for {sandbox_id}\n",
                    mode=0o644,
                )
            ]
        )
        before_pause = await sandbox.files.read_file(STATE_FILE)
        print(f"state before pause: {before_pause.strip()}")

        marker = await sandbox.commands.run("date -u +%Y-%m-%dT%H:%M:%SZ")
        print(f"timestamp before pause: {stdout_text(marker)}")

        await sandbox.pause()
        await sandbox.close()
        sandbox = None
        print("sandbox paused")

        await wait_for_sandbox_state(
            sandbox_id,
            make_connection_config(domain, api_key),
            SandboxState.PAUSED,
            timeout_seconds=180,
        )

        if verify_with_kubectl:
            wait_for_phase(sandbox_id, namespace, "Paused", timeout_seconds=180)

        sandbox = await Sandbox.resume(
            sandbox_id,
            connection_config=config,
            resume_timeout=timedelta(seconds=120),
        )
        print("sandbox resumed")

        after_resume = await sandbox.files.read_file(STATE_FILE)
        print(f"state after resume: {after_resume.strip()}")
        if after_resume != before_pause:
            raise RuntimeError("Sandbox state file changed across pause/resume")

        health = await sandbox.commands.run("echo resumed sandbox is healthy")
        print(f"command after resume: {stdout_text(health)}")
    finally:
        if sandbox is not None:
            await sandbox.close()
        if sandbox_id:
            manager = await SandboxManager.create(
                connection_config=make_connection_config(domain, api_key)
            )
            try:
                await manager.kill_sandbox(sandbox_id)
            finally:
                await manager.close()
            print(f"sandbox killed: {sandbox_id}")


if __name__ == "__main__":
    asyncio.run(main())
