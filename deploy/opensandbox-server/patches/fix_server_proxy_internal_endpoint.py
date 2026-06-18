"""Patch opensandbox-server to make server-proxy use internal pod endpoints.

opensandbox-server 0.2.0 accepts ``resolve_internal=True`` in the proxy route,
but the Kubernetes BatchSandbox endpoint resolver ignores it when gateway ingress
is enabled. That makes the server proxy connect to the client-facing gateway
address, which is often a local port-forward address such as 127.0.0.1:8081.
Inside the server pod that address is not reachable, so every proxy request
returns 502. Keep normal endpoint behavior unchanged, but force proxy backend
requests to use the BatchSandbox pod IP.
"""

from __future__ import annotations

import importlib.util
import py_compile
from importlib.metadata import version
from pathlib import Path


PATCHED_VERSION = "0.2.0"
installed_version = version("opensandbox-server")
if installed_version != PATCHED_VERSION:
    raise RuntimeError(
        f"This patch is pinned to opensandbox-server {PATCHED_VERSION}, "
        f"found {installed_version}"
    )

spec = importlib.util.find_spec("opensandbox_server.services.k8s.kubernetes_service")
if spec is None or spec.origin is None:
    raise RuntimeError("opensandbox_server.services.k8s.kubernetes_service not found")

path = Path(spec.origin)
source = path.read_text(encoding="utf-8")

old = """            if expires is not None:\n                endpoint = self._build_signed_endpoint(sandbox_id, port, expires)\n            else:\n                endpoint = self.workload_provider.get_endpoint_info(workload, port, sandbox_id)\n\n            if not endpoint:\n"""

new = """            if expires is not None:\n                endpoint = self._build_signed_endpoint(sandbox_id, port, expires)\n            else:\n                endpoint = None\n                if resolve_internal:\n                    parse_pod_ip = getattr(self.workload_provider, \"_parse_pod_ip\", None)\n                    if parse_pod_ip is not None:\n                        pod_ip = parse_pod_ip(workload)\n                        if pod_ip:\n                            endpoint = Endpoint(endpoint=f\"{pod_ip}:{port}\")\n                if endpoint is None:\n                    endpoint = self.workload_provider.get_endpoint_info(workload, port, sandbox_id)\n\n            if not endpoint:\n"""

if new in source:
    raise RuntimeError(f"Patch already applied to {path}")
if old not in source:
    raise RuntimeError(f"Patch target not found in {path}")

path.write_text(source.replace(old, new, 1), encoding="utf-8")
py_compile.compile(str(path), doraise=True)
print(f"Patched {path}")
