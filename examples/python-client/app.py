import asyncio
import os
import subprocess
import time
from datetime import timedelta

from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.models import WriteEntry


def first_stdout_text(execution) -> str:
    if not execution.logs.stdout:
        return ""
    return "".join(chunk.text for chunk in execution.logs.stdout).strip()


async def main() -> None:
    domain = os.getenv("OPEN_SANDBOX_DOMAIN", "localhost:8080")
    api_key = os.getenv("OPEN_SANDBOX_API_KEY", "dev-api-key")
    image = os.getenv("SANDBOX_IMAGE", "python:3.12-slim")

    config = ConnectionConfig(
        domain=domain,
        api_key=api_key,
        request_timeout=timedelta(seconds=90),
        use_server_proxy=False,
    )

    sandbox = await Sandbox.create(
        image,
        connection_config=config,
        timeout=timedelta(minutes=10),
        resource={"cpu": "500m", "memory": "512Mi"},
        metadata={"example": "aks-kata"},
    )

    async with sandbox:
        try:
            hello = await sandbox.commands.run("echo hello from opensandbox on aks kata")
            print(f"command output: {first_stdout_text(hello)}")

            uname = await sandbox.commands.run("uname -a")
            print(f"sandbox kernel: {first_stdout_text(uname)}")

            await sandbox.files.write_files([
                WriteEntry(path="/tmp/opensandbox-kata.txt", data="kata example", mode=0o644)
            ])
            content = await sandbox.files.read_file("/tmp/opensandbox-kata.txt")
            print(f"file roundtrip: {content}")

            if os.getenv("VERIFY_KATA_WITH_KUBECTL") == "1":
                namespace = os.getenv("OPEN_SANDBOX_NAMESPACE", "opensandbox")
                for _ in range(30):
                    pods = subprocess.check_output(
                        [
                            "kubectl",
                            "get",
                            "pods",
                            "-n",
                            namespace,
                            "-o",
                            "jsonpath={range .items[*]}{.metadata.name}{'\\t'}{.spec.runtimeClassName}{'\\n'}{end}",
                        ],
                        text=True,
                    )
                    if "kata-optimized" in pods:
                        print("runtime class: kata-optimized")
                        break
                    time.sleep(1)
                else:
                    raise RuntimeError("No live sandbox pod used runtimeClassName=kata-optimized")
        finally:
            await sandbox.kill()


if __name__ == "__main__":
    asyncio.run(main())
