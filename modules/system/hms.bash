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

# Configure local git for this repo (silent, idempotent)
# USER_NAME and USER_EMAIL are provided as env vars by the nix wrapper
git -C ~/.config/nixpkgs config --local user.name "$USER_NAME" 2>/dev/null
git -C ~/.config/nixpkgs config --local user.email "$USER_EMAIL" 2>/dev/null

# Expunge tmux server for complete refresh if flag was passed
if [[ "$EXPUNGE" == "true" ]]; then
  echo "Expunging tmux server for complete environment refresh..."
  tmux kill-server 2>/dev/null || true
fi
