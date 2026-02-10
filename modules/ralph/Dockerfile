# syntax=docker/dockerfile:1
# Multi-stage build for Ralph Orchestrator with Chainguard distroless base

FROM debian:bookworm-slim AS downloader
ARG RALPH_VERSION=2.5.0
ARG RALPH_ARCH=aarch64
ARG CACHE_BUST=unknown

# Install curl and xz-utils (installer scripts need them for extraction)
RUN apt-get update && \
    apt-get install -y curl xz-utils bash && \
    rm -rf /var/lib/apt/lists/*

# Install ralph using official installer script
RUN curl -fsSL "https://github.com/mikeyobrien/ralph-orchestrator/releases/download/v${RALPH_VERSION}/ralph-cli-installer.sh" | sh

# Install Claude Code CLI (latest version)
# CACHE_BUST=${CACHE_BUST} forces this layer to rebuild, getting latest Claude
RUN curl -fsSL https://claude.ai/install.sh | bash

# Find the Claude binary path and create a stable symlink
RUN CLAUDE_VERSION=$(ls /root/.local/share/claude/versions/ | sort -V | tail -1) && \
    ln -sf /root/.local/share/claude/versions/$CLAUDE_VERSION /root/.local/bin/claude-target

# Final stage: Chainguard distroless with git
# - No shell, no package manager (maximum security)
# - Includes git + ca-certificates (needed for Ralph operations)
# - Very small image (~20-30MB)
FROM cgr.dev/chainguard/git:latest

COPY --from=downloader /root/.cargo/bin/ralph /usr/local/bin/ralph
COPY --from=downloader /root/.local/bin/claude-target /usr/local/bin/claude

WORKDIR /workspace

ENTRYPOINT ["ralph"]
