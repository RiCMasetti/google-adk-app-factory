FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

RUN rm -f /etc/apt/sources.list.d/yarn.list \
        /etc/apt/sources.list.d/yarn.list.save \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        build-essential \
        bubblewrap \
        ca-certificates \
        curl \
        git \
        jq \
        make \
    && rm -rf /var/lib/apt/lists/*

RUN pipx install uv
RUN curl -fsSL https://chatgpt.com/codex/install.sh -o /tmp/install-codex.sh \
    && chmod +x /tmp/install-codex.sh \
    && sudo -u vscode HOME=/home/vscode sh /tmp/install-codex.sh \
    && ln -sf /home/vscode/.local/bin/codex /usr/local/bin/codex \
    && rm -f /tmp/install-codex.sh

ENV PATH="/home/vscode/.local/bin:/usr/local/py-utils/bin:${PATH}"
