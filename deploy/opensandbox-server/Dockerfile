FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SANDBOX_CONFIG_PATH=/app/sandbox.toml

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.8.14 /uv /usr/local/bin/uv
RUN uv pip install --system --no-cache opensandbox-server==0.2.0

# Patch a pinned opensandbox-server 0.2.0 server-proxy regression until upstream includes the fix.
COPY deploy/opensandbox-server/patches/fix_server_proxy_internal_endpoint.py /tmp/fix_server_proxy_internal_endpoint.py
RUN python /tmp/fix_server_proxy_internal_endpoint.py && rm /tmp/fix_server_proxy_internal_endpoint.py

COPY deploy/opensandbox-server/k8s/batchsandbox-template.yaml /app/batchsandbox-template.yaml

EXPOSE 8080

CMD ["opensandbox-server", "--config", "/app/sandbox.toml"]
