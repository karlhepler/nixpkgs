#!/usr/bin/env bash
# post-commit hook: records the new commit as a Claudit timeline annotation.
# Invoked by git after every successful commit in this repo.
# Wired via home.activation.nixpkgsPostCommitHook in modules/claudit/default.nix.
set -euo pipefail

short_sha=$(git rev-parse --short HEAD)
subject=$(git log -1 --format='%s' HEAD)
message="${short_sha}: ${subject}"

# Run in background so hook latency is invisible.
# Errors are silently swallowed — a metrics write failure must never abort a commit.
claudit-annotate --tags "git-commit" "${message}" >/dev/null 2>&1 || true
