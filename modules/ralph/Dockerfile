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

# Install Claude Code CLI (latest version) - Linux binary
# CACHE_BUST=${CACHE_BUST} forces this layer to rebuild, getting latest Claude
# Download Linux binary directly (installer detects macOS host incorrectly)
RUN CLAUDE_VERSION=$(curl -fsSL "https://storage.googleapis.com/claude-code-dist-86c565f3-f756-42ad-8dfa-d59b1c096819/claude-code-releases/latest") && \
    CLAUDE_URL="https://storage.googleapis.com/claude-code-dist-86c565f3-f756-42ad-8dfa-d59b1c096819/claude-code-releases/${CLAUDE_VERSION}/claude-linux-aarch64" && \
    mkdir -p /root/.local/bin && \
    curl -fsSL "$CLAUDE_URL" -o /root/.local/bin/claude-binary && \
    chmod +x /root/.local/bin/claude-binary

# Final stage: Chainguard distroless with git
# - No shell, no package manager (maximum security)
# - Includes git + ca-certificates (needed for Ralph operations)
# - Very small image (~20-30MB)
FROM cgr.dev/chainguard/git:latest

COPY --from=downloader /root/.cargo/bin/ralph /usr/local/bin/ralph
COPY --from=downloader /root/.local/bin/claude-binary /usr/local/bin/claude

WORKDIR /workspace

ENTRYPOINT ["ralph"]
