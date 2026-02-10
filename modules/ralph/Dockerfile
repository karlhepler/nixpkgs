# syntax=docker/dockerfile:1
# Multi-stage build for Ralph Orchestrator with Chainguard distroless base

FROM debian:bookworm-slim AS downloader
ARG RALPH_VERSION=2.5.0
ARG RALPH_ARCH=aarch64

# Install curl and xz-utils (installer script needs xz for tar.xz extraction)
RUN apt-get update && \
    apt-get install -y curl xz-utils && \
    rm -rf /var/lib/apt/lists/*

# Install ralph using official installer script
RUN curl -fsSL "https://github.com/mikeyobrien/ralph-orchestrator/releases/download/v${RALPH_VERSION}/ralph-cli-installer.sh" | sh

# Final stage: Chainguard distroless with git
# - No shell, no package manager (maximum security)
# - Includes git + ca-certificates (needed for Ralph operations)
# - Very small image (~20-30MB)
FROM cgr.dev/chainguard/git:latest

COPY --from=downloader /root/.cargo/bin/ralph /usr/local/bin/ralph

WORKDIR /workspace

ENTRYPOINT ["ralph"]
