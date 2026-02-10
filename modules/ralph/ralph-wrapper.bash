#!/usr/bin/env bash
set -eou pipefail

# Ralph Docker Wrapper
# Transparent Docker execution wrapper for Ralph Orchestrator
# Maintains CLI compatibility while running in isolated container

# Image configuration
RALPH_IMAGE="ralph-orchestrator:latest"
RALPH_VERSION_CACHE="$HOME/.local/share/ralph/version"
RALPH_DOCKERFILE="$HOME/.local/share/ralph/Dockerfile"
PULL_INTERVAL_DAYS=7

# Detect architecture for binary selection
ARCH=$(uname -m)
if [ "$ARCH" = "arm64" ] || [ "$ARCH" = "aarch64" ]; then
  RALPH_ARCH="aarch64"
else
  RALPH_ARCH="x86_64"
fi

# Wait for Docker daemon to be ready
wait_for_docker() {
  local attempt=0
  local max_attempts=30
  while ! docker ps &>/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ $attempt -ge $max_attempts ]; then
      echo "Error: Docker daemon failed to start after ${max_attempts}s" >&2
      exit 1
    fi
    sleep 1
  done
}

# Detect and start Docker runtime (priority: OrbStack > Docker Desktop > Colima)
if [ -d "/Applications/OrbStack.app" ] || command -v orb &>/dev/null; then
  # OrbStack installed
  if ! docker ps &>/dev/null 2>&1; then
    echo "Starting OrbStack..." >&2
    open -a OrbStack
    wait_for_docker
  fi
elif [ -d "/Applications/Docker.app" ]; then
  # Docker Desktop installed
  if ! docker ps &>/dev/null 2>&1; then
    echo "Starting Docker Desktop..." >&2
    open -a Docker
    wait_for_docker
  fi
else
  # Fall back to Colima
  if ! command -v colima &>/dev/null; then
    echo "Error: No Docker runtime found (OrbStack, Docker Desktop, or Colima)" >&2
    echo "Run 'hms' to install Colima" >&2
    exit 1
  fi

  if ! colima status &>/dev/null 2>&1; then
    echo "Starting Colima..." >&2
    colima start --cpu 2 --memory 4 --disk 50 --arch aarch64 --vm-type=vz --mount-type=virtiofs
    wait_for_docker
  fi
fi

# Extract Claude credentials from Keychain if not set
if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  ANTHROPIC_API_KEY=$(security find-generic-password -s "Claude Code" -w 2>/dev/null || echo "")
  if [[ -z "$ANTHROPIC_API_KEY" ]]; then
    echo "Error: No Claude Code credentials found in Keychain" >&2
    echo "Please log in to Claude Code first" >&2
    exit 1
  fi
fi

# Function to build Ralph image
build_ralph_image() {
  local version="${1:-latest}"

  # Get latest version if not specified
  if [ "$version" = "latest" ]; then
    version=$(gh api repos/mikeyobrien/ralph-orchestrator/releases/latest --jq '.tag_name' 2>/dev/null | sed 's/^v//' || echo "2.5.0")
  fi

  echo "Building Ralph image v$version for $RALPH_ARCH..." >&2

  # Verify Dockerfile exists
  if [ ! -f "$RALPH_DOCKERFILE" ]; then
    echo "Error: Dockerfile not found at $RALPH_DOCKERFILE" >&2
    echo "Run 'hms' to deploy the Dockerfile" >&2
    return 1
  fi

  # Build image using deployed Dockerfile
  # Note: Docker buildx cannot handle Nix store symlinks properly, so we copy to temp dir
  BUILD_DIR=$(mktemp -d)
  trap 'rm -rf "$BUILD_DIR"' EXIT

  cp "$RALPH_DOCKERFILE" "$BUILD_DIR/Dockerfile"

  if docker build \
    --build-arg RALPH_VERSION="$version" \
    --build-arg RALPH_ARCH="$RALPH_ARCH" \
    -t "$RALPH_IMAGE" \
    "$BUILD_DIR" >/dev/null 2>&1; then

    # Cache version on success
    mkdir -p "$(dirname "$RALPH_VERSION_CACHE")"
    echo "$version" > "$RALPH_VERSION_CACHE"
    echo "Ralph image v$version built successfully" >&2
    return 0
  else
    echo "Warning: Ralph image build failed" >&2
    return 1
  fi
}

# Check if image needs to be built/rebuilt
if ! docker image inspect "$RALPH_IMAGE" >/dev/null 2>&1; then
  # Image doesn't exist - build it
  echo "Ralph image not found, building..." >&2
  build_ralph_image || {
    echo "Error: Failed to build Ralph image on first run" >&2
    exit 1
  }
elif [ -f "$RALPH_VERSION_CACHE" ]; then
  # Image exists - check if we should update (weekly)
  CACHED_VERSION=$(cat "$RALPH_VERSION_CACHE")
  LAST_CHECK=$(stat -c %Y "$RALPH_VERSION_CACHE" 2>/dev/null || echo 0)
  NOW=$(date +%s)
  DAYS_SINCE_CHECK=$(( (NOW - LAST_CHECK) / 86400 ))

  if [ $DAYS_SINCE_CHECK -ge $PULL_INTERVAL_DAYS ]; then
    # Time to check for updates
    LATEST_VERSION=$(gh api repos/mikeyobrien/ralph-orchestrator/releases/latest --jq '.tag_name' 2>/dev/null | sed 's/^v//')

    if [ -n "$LATEST_VERSION" ] && [ "$LATEST_VERSION" != "$CACHED_VERSION" ]; then
      echo "New Ralph version available: v$LATEST_VERSION (current: v$CACHED_VERSION)" >&2
      build_ralph_image "$LATEST_VERSION" || echo "Warning: Update failed, using cached version v$CACHED_VERSION" >&2
    else
      # No update needed, touch cache to reset timer
      touch "$RALPH_VERSION_CACHE"
    fi
  fi
else
  # Image exists but no version cache - create it
  mkdir -p "$(dirname "$RALPH_VERSION_CACHE")"
  echo "2.5.0" > "$RALPH_VERSION_CACHE"
fi

# Get current working directory and git root
CWD="$(pwd)"
GIT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "$CWD")"

# Prepare environment variables to pass through
ENV_VARS=()
for var in ANTHROPIC_API_KEY GEMINI_API_KEY Q_API_KEY RALPH_MAX_ITERATIONS RALPH_MAX_RUNTIME KANBAN_SESSION NPM_TOKEN; do
  if [[ -n "${!var:-}" ]]; then
    ENV_VARS+=("-e" "$var=${!var}")
  fi
done

# Run Ralph in Docker with security isolation
# Security controls:
# - --user: Run as non-root (UID:GID of current user)
# - --cap-drop=ALL: Drop all Linux capabilities
# - --security-opt=no-new-privileges: Prevent privilege escalation
# - --read-only: Root filesystem read-only
# - --tmpfs /tmp: Writable temp directory (ephemeral)
# - --memory: Limit to 4GB RAM
# - --cpus: Limit to 2 CPUs
# - --pids-limit: Limit to 512 processes
# - --network=host: Use host network (for gh CLI, git operations)
#
# Volume mounts:
# - Git repo root: Mount as /workspace (read-write for commits/pushes)
# - HOME: Mount ~/.config/git (XDG git config), ~/.ssh, ~/.config/gh for git/gh operations
exec docker run --rm -i \
  --user "$(id -u):$(id -g)" \
  --cap-drop=ALL \
  --security-opt=no-new-privileges:true \
  --read-only \
  --tmpfs /tmp:rw,exec,nosuid,nodev,size=1g \
  --memory=4g \
  --cpus=2 \
  --pids-limit=512 \
  --network=host \
  -v "$GIT_ROOT:/workspace:rw" \
  -v "$HOME/.config/git:/root/.config/git:ro" \
  -v "$HOME/.ssh:/root/.ssh:ro" \
  -v "$HOME/.config/gh:/root/.config/gh:ro" \
  -w /workspace \
  "${ENV_VARS[@]}" \
  "$RALPH_IMAGE" \
  "$@"
