FROM debian:12-slim

ARG COPILOT_CLI_VERSION=1.0.63
ARG COPILOT_CLI_TARBALL_SHA256=64d4a80496248f316030c358f530e60b96bae670e18f0c3f62e1f91fefacaf82

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSLo /tmp/copilot-linux-x64.tar.gz \
        "https://github.com/github/copilot-cli/releases/download/v${COPILOT_CLI_VERSION}/copilot-linux-x64.tar.gz" \
    && echo "${COPILOT_CLI_TARBALL_SHA256}  /tmp/copilot-linux-x64.tar.gz" | sha256sum -c - \
    && mkdir -p /tmp/copilot \
    && tar -xzf /tmp/copilot-linux-x64.tar.gz -C /tmp/copilot \
    && install -m 0755 /tmp/copilot/copilot /usr/local/bin/copilot \
    && rm -rf /tmp/copilot /tmp/copilot-linux-x64.tar.gz

RUN groupadd -r sandbox \
    && useradd -r -g sandbox -d /home/sandbox -m sandbox \
    && mkdir -p /workspace \
    && chown -R sandbox:sandbox /home/sandbox /workspace

WORKDIR /workspace
USER sandbox

CMD ["bash"]
