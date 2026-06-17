FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SANDBOX_CONFIG_PATH=/app/sandbox.toml

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.8.14 /uv /usr/local/bin/uv
RUN uv pip install --system --no-cache opensandbox-server==0.1.14

COPY deploy/opensandbox-server/k8s/batchsandbox-template.yaml /app/batchsandbox-template.yaml

EXPOSE 8080

CMD ["opensandbox-server", "--config", "/app/sandbox.toml"]
