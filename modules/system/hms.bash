# Home Manager Switch: Apply Nix Home Manager configuration changes
# - Validates user.nix exists and has no placeholders
# - Backs up user.nix and overconfig.nix with timestamp
# - Temporarily tracks both files in git
# - Runs home-manager switch
# - Configures local git settings for this repo
# - Optional --expunge flag to kill tmux server for complete environment refresh

set -eou pipefail

show_help() {
  echo "hms - Home Manager Switch: Apply Nix configuration changes"
  echo
  echo "USAGE:"
  echo "  hms               Apply configuration changes"
  echo "  hms --expunge     Apply changes and restart tmux server"
  echo "  hms --help        Show this help message"
  echo
  echo "DESCRIPTION:"
  echo "  Applies your Nix Home Manager configuration from ~/.config/nixpkgs."
  echo "  This command validates configuration, creates backups, and switches"
  echo "  your environment to the new configuration."
  echo
  echo "  Before switching:"
  echo "  - Validates user.nix exists and has no placeholder values"
  echo "  - Creates timestamped backups of user.nix and overconfig.nix"
  echo "  - Temporarily tracks both files in git for the switch"
  echo
  echo "  After switching:"
  echo "  - Configures local git settings for this repository"
  echo "  - Restores git-ignore status for user.nix and overconfig.nix"
  echo "  - Optionally kills tmux server for complete environment refresh"
  echo
  echo "OPTIONS:"
  echo "  --expunge      Kill tmux server after switch for complete refresh"
  echo "                 Use when tmux-related settings change"
  echo "                 WARNING: Closes all tmux sessions"
  echo "  -h, --help     Show this help message"
  echo
  echo "EXAMPLES:"
  echo "  # Apply configuration changes"
  echo "  hms"
  echo
  echo "  # Apply changes and restart tmux (for tmux config updates)"
  echo "  hms --expunge"
  echo
  echo "BACKUPS:"
  echo "  Automatic backups saved to:"
  echo "  ~/.backup/.config/nixpkgs/user.YYYYMMDD-HHMMSS.nix"
  echo "  ~/.backup/.config/nixpkgs/overconfig.YYYYMMDD-HHMMSS.nix"
  echo
  echo "  Latest backup symlinks:"
  echo "  ~/.backup/.config/nixpkgs/user.latest.nix"
  echo "  ~/.backup/.config/nixpkgs/overconfig.latest.nix"
  echo
  echo "NOTES:"
  echo "  - Configuration must be at ~/.config/nixpkgs"
  echo "  - Edit user config: hmu"
  echo "  - Edit machine config: hmo"
  echo "  - Edit main config: hme"
}

# Parse arguments
EXPUNGE=false
for arg in "$@"; do
  if [[ "$arg" == "-h" || "$arg" == "--help" ]]; then
    show_help
    exit 0
  elif [[ "$arg" == "--expunge" ]]; then
    EXPUNGE=true
  fi
done

# Validate user.nix exists and is configured
if [[ ! -f ~/.config/nixpkgs/user.nix ]]; then
  echo "ERROR: user.nix not found!"
  echo "Please edit user.nix: hmu"
  exit 1
fi

if grep -q '= "CHANGE_ME"' ~/.config/nixpkgs/user.nix; then
  echo "ERROR: user.nix contains CHANGE_ME placeholder values"
  echo "Please edit user.nix and set all required fields: hmu"
  exit 1
fi

# Backup user.nix and overconfig.nix
mkdir -p ~/.backup/.config/nixpkgs
timestamp=$(date +%Y%m%d-%H%M%S)
cp ~/.config/nixpkgs/user.nix ~/.backup/.config/nixpkgs/user."$timestamp".nix
ln -sf user."$timestamp".nix ~/.backup/.config/nixpkgs/user.latest.nix

cp ~/.config/nixpkgs/overconfig.nix ~/.backup/.config/nixpkgs/overconfig."$timestamp".nix
ln -sf overconfig."$timestamp".nix ~/.backup/.config/nixpkgs/overconfig.latest.nix

# Temporarily track user.nix and overconfig.nix
git -C ~/.config/nixpkgs update-index --no-assume-unchanged user.nix overconfig.nix

# Run home-manager switch
home-manager switch --flake ~/.config/nixpkgs

# ============================================================================
# Install/Update Developer Tools
# ============================================================================
# Claude Code is installed via curl (not Nix) because it updates frequently
# and has its own update mechanism.
# ============================================================================

# Ensure we're not running as root (safety check)
if [ "$EUID" -eq 0 ] || [ "$USER" = "root" ]; then
  echo "ERROR: hms should not be run as root. Run as your normal user."
  exit 1
fi

# Claude Code: AI coding assistant (self-updates, just install if not present)
if ! command -v claude &>/dev/null; then
  echo "Installing Claude Code..."
  curl -fsSL https://claude.ai/install.sh | bash
fi

# Ralph Orchestrator: Multi-agent orchestration framework (version pinned via lock file)
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && git rev-parse --show-toplevel)
ralph_lock="$repo_root/modules/claude/ralph.lock"

if [[ ! -f "$ralph_lock" ]]; then
  echo "Warning: modules/claude/ralph.lock not found — skipping ralph version check"
else
  LOCKED_VERSION=$(jq -r '.version // empty' "$ralph_lock")
  if [[ -z "$LOCKED_VERSION" ]]; then
    echo "Warning: modules/claude/ralph.lock has no version field — skipping ralph version check"
  else
    CURRENT_VERSION=$(ralph --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo "")

    if [[ -z "$CURRENT_VERSION" || "$CURRENT_VERSION" != "$LOCKED_VERSION" ]]; then
      if [[ -z "$CURRENT_VERSION" ]]; then
        echo "Installing Ralph Orchestrator v$LOCKED_VERSION (locked)..."
      else
        echo "Ralph version mismatch (installed: v$CURRENT_VERSION, locked: v$LOCKED_VERSION) — installing locked version..."
      fi
      curl -fsSL "https://github.com/mikeyobrien/ralph-orchestrator/releases/download/v${LOCKED_VERSION}/ralph-cli-installer.sh" | sh
    fi

    # Check if a newer release exists and prompt user to upgrade
    LATEST_VERSION=$(curl -fsSL "https://api.github.com/repos/mikeyobrien/ralph-orchestrator/releases/latest" | jq -r '.tag_name // empty' | sed 's/^v//' || echo "")

    if [[ -n "$LATEST_VERSION" && "$LATEST_VERSION" != "$LOCKED_VERSION" ]]; then
      # Only prompt for input if stdin is a terminal (interactive shell)
      if [[ -t 0 ]]; then
        printf "ralph v%s is available (lock file pins v%s). Update lock file? [y/N] " "$LATEST_VERSION" "$LOCKED_VERSION"
        read -r response
        if [[ "$response" =~ ^[Yy]$ ]]; then
          jq --arg v "$LATEST_VERSION" '.version = $v' "$ralph_lock" > "${ralph_lock}.tmp" && mv "${ralph_lock}.tmp" "$ralph_lock"
          echo "Updated ralph.lock to v$LATEST_VERSION — installing..."
          curl -fsSL "https://github.com/mikeyobrien/ralph-orchestrator/releases/download/v${LATEST_VERSION}/ralph-cli-installer.sh" | sh
        fi
      fi
    fi
  fi
fi

# MarkText: Markdown editor (Tkaixiang maintained fork, installed from GitHub releases)
marktext_installed=$(defaults read /Applications/MarkText.app/Contents/Info.plist CFBundleShortVersionString 2>/dev/null || echo "")
marktext_latest=$(curl -fsSL "https://api.github.com/repos/Tkaixiang/marktext/releases/latest" | jq -r '.tag_name // empty' | sed 's/^v//' || echo "")

if [ -z "$marktext_latest" ]; then
  echo "Warning: Could not fetch latest MarkText version, skipping."
elif [ "$marktext_installed" != "$marktext_latest" ]; then
  if [ -z "$marktext_installed" ]; then
    echo "Installing MarkText v$marktext_latest..."
  else
    echo "Updating MarkText from v$marktext_installed to v$marktext_latest..."
  fi
  marktext_tmp=$(mktemp -d)
  curl -fsSL "https://github.com/Tkaixiang/marktext/releases/download/v${marktext_latest}/marktext-mac-arm64-${marktext_latest}.zip" -o "$marktext_tmp/marktext.zip"
  unzip -q "$marktext_tmp/marktext.zip" -d "$marktext_tmp"
  rm -rf /Applications/MarkText.app
  mv "$marktext_tmp/marktext.app" /Applications/MarkText.app
  xattr -cr /Applications/MarkText.app
  codesign --force --deep --sign - /Applications/MarkText.app
  rm -rf "$marktext_tmp"
  echo "MarkText v$marktext_latest installed."
fi

# Ensure MarkText is the default app for markdown files
if [ -d /Applications/MarkText.app ]; then
  duti -s com.electron.app .md all
fi

# Configure local git for this repo (silent, idempotent)
# USER_NAME and USER_EMAIL are provided as env vars by the nix wrapper
git -C ~/.config/nixpkgs config --local user.name "$USER_NAME" 2>/dev/null
git -C ~/.config/nixpkgs config --local user.email "$USER_EMAIL" 2>/dev/null

# Expunge tmux server for complete refresh if flag was passed
if [[ "$EXPUNGE" == "true" ]]; then
  echo "Expunging tmux server for complete environment refresh..."
  tmux kill-server 2>/dev/null || true
fi
