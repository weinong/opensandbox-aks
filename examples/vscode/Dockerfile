FROM debian:12-slim

ARG CODE_SERVER_VERSION=4.124.2
ARG CODE_SERVER_DEB_SHA256=d71187f76f77d7b01269eee6de365811d87849a5aaab61d1d6528652e5c1d731

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        git \
        python3 \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSLo /tmp/code-server.deb \
        "https://github.com/coder/code-server/releases/download/v${CODE_SERVER_VERSION}/code-server_${CODE_SERVER_VERSION}_amd64.deb" \
    && echo "${CODE_SERVER_DEB_SHA256}  /tmp/code-server.deb" | sha256sum -c - \
    && apt-get update \
    && apt-get install -y --no-install-recommends /tmp/code-server.deb \
    && rm -rf /var/lib/apt/lists/* /tmp/code-server.deb

RUN groupadd -r vscode \
    && useradd -r -g vscode -d /home/vscode -m vscode \
    && mkdir -p /workspace \
    && chown -R vscode:vscode /home/vscode /workspace

WORKDIR /workspace
USER vscode

CMD ["bash"]
