# Home Manager Switch: Apply Nix Home Manager configuration changes
# - Validates user.nix exists and has no placeholders
# - Backs up user.nix and overconfig.nix with timestamp
# - Temporarily tracks both files in git
# - Runs home-manager switch
# - Configures local git settings for this repo
# - Optional --expunge flag to kill tmux server for complete environment refresh

# Parse arguments
EXPUNGE=false
for arg in "$@"; do
  if [[ "$arg" == "--expunge" ]]; then
    EXPUNGE=true
  fi
done

# Validate user.nix exists and is configured
if [[ ! -f ~/.config/nixpkgs/user.nix ]]; then
  echo "ERROR: user.nix not found!"
  echo "Please edit user.nix: hmu"
  exit 1
fi

if grep -q "CHANGE_ME" ~/.config/nixpkgs/user.nix; then
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
USER_NAME=$(grep 'userName = ' ~/.config/nixpkgs/user.nix | sed 's/.*userName = "\(.*\)";/\1/')
USER_EMAIL=$(grep 'userEmail = ' ~/.config/nixpkgs/user.nix | sed 's/.*userEmail = "\(.*\)";/\1/')
git -C ~/.config/nixpkgs config --local user.name "$USER_NAME" 2>/dev/null
git -C ~/.config/nixpkgs config --local user.email "$USER_EMAIL" 2>/dev/null

# Expunge tmux server for complete refresh if flag was passed
if [[ "$EXPUNGE" == "true" ]]; then
  echo "Expunging tmux server for complete environment refresh..."
  tmux kill-server 2>/dev/null || true
fi
