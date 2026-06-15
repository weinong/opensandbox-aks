FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SANDBOX_CONFIG_PATH=/app/sandbox.toml

WORKDIR /app

RUN pip install --no-cache-dir opensandbox-server==0.1.14

COPY examples/opensandbox-kata/k8s/batchsandbox-template.yaml /app/batchsandbox-template.yaml

EXPOSE 8080

CMD ["opensandbox-server", "--config", "/app/sandbox.toml"]
