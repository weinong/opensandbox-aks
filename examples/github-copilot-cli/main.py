import asyncio
import os
import shlex
import subprocess
from datetime import timedelta

from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.models.sandboxes import (
    Credential,
    CredentialBinding,
    CredentialProxyConfig,
    NetworkPolicy,
    NetworkRule,
)


FAKE_COPILOT_TOKEN = "github_pat_fake_token_inside_sandbox"
COPILOT_CREDENTIAL_HOSTS = [
    "api.github.com",
    "github.com",
    "api.enterprise.githubcopilot.com",
]
COPILOT_EGRESS_HOSTS = [
    "api.github.com",
    "github.com",
    "copilot-proxy.githubusercontent.com",
    "api.githubcopilot.com",
    "api.enterprise.githubcopilot.com",
    "copilot-telemetry.githubusercontent.com",
    "telemetry.enterprise.githubcopilot.com",
]
ALLOWED_CREDENTIAL_HOSTS = set(COPILOT_CREDENTIAL_HOSTS)


def required_github_token() -> str:
    token = os.getenv("COPILOT_GITHUB_TOKEN")
    if not token:
        raise RuntimeError("COPILOT_GITHUB_TOKEN is required")
    return token


def execution_stdout(execution) -> str:
    return "".join(chunk.text for chunk in execution.logs.stdout).strip()


def execution_stderr(execution) -> str:
    return "".join(chunk.text for chunk in execution.logs.stderr).strip()


async def print_execution_logs(label: str, execution) -> None:
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


async def run_checked(sandbox: Sandbox, label: str, command: str):
    execution = await sandbox.commands.run(command)
    await print_execution_logs(label, execution)
    if execution.error:
        raise RuntimeError(f"{label} failed: {execution.error.name}: {execution.error.value}")
    if execution.exit_code != 0:
        raise RuntimeError(f"{label} exited with code {execution.exit_code}")
    return execution


async def wait_for_commands(sandbox: Sandbox, timeout_seconds: int) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    last_error = ""
    while asyncio.get_running_loop().time() < deadline:
        try:
            execution = await sandbox.commands.run("true")
            if execution.exit_code == 0 and not execution.error:
                return
            if execution.error:
                last_error = f"{execution.error.name}: {execution.error.value}"
            else:
                last_error = f"exit code {execution.exit_code}"
        except Exception as exc:
            last_error = str(exc)
        await asyncio.sleep(1)
    raise RuntimeError(f"Timed out waiting for sandbox commands: {last_error}")


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


def hosts_from_env(name: str, defaults: list[str]) -> list[str]:
    value = os.getenv(name)
    if not value:
        return defaults
    hosts = [host.strip() for host in value.split(",") if host.strip()]
    if not hosts:
        raise RuntimeError(f"{name} must contain at least one host when set")
    return hosts


def credential_hosts_from_env() -> list[str]:
    hosts = hosts_from_env("COPILOT_CREDENTIAL_HOSTS", COPILOT_CREDENTIAL_HOSTS)
    unsupported_hosts = sorted(set(hosts) - ALLOWED_CREDENTIAL_HOSTS)
    if unsupported_hosts:
        raise RuntimeError(
            "COPILOT_CREDENTIAL_HOSTS can only include: "
            + ",".join(sorted(ALLOWED_CREDENTIAL_HOSTS))
        )
    return hosts


async def configure_credential_vault(
    sandbox: Sandbox,
    github_token: str,
    auth_hosts: list[str],
) -> None:
    state = await sandbox.credential_vault.create(
        credentials=[
            Credential(name="copilot-github-token", source={"value": github_token}),
        ],
        bindings=[
            CredentialBinding(
                name="copilot-github-bearer",
                match={
                    "schemes": ["https"],
                    "ports": [443],
                    "hosts": auth_hosts,
                },
                auth={"type": "bearer", "credential": "copilot-github-token"},
            ),
        ],
    )
    print(
        "credential vault configured: "
        f"{len(state.credentials)} credential(s), {len(state.bindings)} binding(s)"
    )


async def main() -> None:
    domain = os.getenv("OPEN_SANDBOX_DOMAIN", "localhost:8080")
    api_key = os.getenv("OPEN_SANDBOX_API_KEY", "dev-api-key")
    github_token = required_github_token()
    namespace = os.getenv("OPEN_SANDBOX_NAMESPACE", "opensandbox")
    image = os.getenv("SANDBOX_IMAGE", "opensandbox-copilot-cli:latest")
    credential_hosts = credential_hosts_from_env()
    egress_hosts = hosts_from_env("COPILOT_EGRESS_HOSTS", COPILOT_EGRESS_HOSTS)
    prompt = os.getenv(
        "COPILOT_PROMPT",
        "Explain this shell command without running it: kubectl get pods -n opensandbox",
    )
    sandbox = await Sandbox.create(
        image,
        connection_config=ConnectionConfig(
            domain=domain,
            api_key=api_key,
            request_timeout=timedelta(seconds=120),
            use_server_proxy=False,
        ),
        env={
            "COPILOT_GITHUB_TOKEN": FAKE_COPILOT_TOKEN,
            "GH_TOKEN": FAKE_COPILOT_TOKEN,
            "IS_SANDBOX": "1",
        },
        network_policy=NetworkPolicy(
            defaultAction="deny",
            egress=[
                NetworkRule(action="allow", target=host)
                for host in sorted(set(egress_hosts + credential_hosts))
            ],
        ),
        credential_proxy=CredentialProxyConfig(enabled=True),
        timeout=timedelta(minutes=15),
        ready_timeout=timedelta(minutes=2),
        resource={"cpu": "1", "memory": "1Gi"},
        metadata={"example": "aks-kata-github-copilot-cli"},
        skip_health_check=True,
    )

    async with sandbox:
        try:
            print(f"sandbox id: {sandbox.id}")
            print("credential hosts: " + ",".join(credential_hosts))
            print("egress hosts: " + ",".join(egress_hosts))
            await wait_for_commands(sandbox, 120)
            await configure_credential_vault(sandbox, github_token, credential_hosts)

            await run_checked(sandbox, "copilot-version", "copilot --version")

            copilot = await run_checked(
                sandbox,
                "copilot-prompt",
                "copilot --no-auto-update --disable-builtin-mcps -p "
                + shlex.quote(prompt)
                + " -s --no-ask-user --allow-all --deny-tool=shell --deny-tool=write",
            )
            if not execution_stdout(copilot) and not execution_stderr(copilot):
                raise RuntimeError("GitHub Copilot CLI returned no output")

            if os.getenv("VERIFY_KATA_WITH_KUBECTL") == "1":
                await verify_kata_runtime(namespace, sandbox.id)
        finally:
            await sandbox.kill()
            print(f"sandbox killed: {sandbox.id}")


if __name__ == "__main__":
    asyncio.run(main())
