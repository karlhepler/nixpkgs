# Home Manager Switch: Apply Nix Home Manager configuration changes
# - Backs up overconfig.nix with timestamp
# - Temporarily tracks overconfig.nix in git
# - Runs home-manager switch
# - Optional --expunge flag to kill tmux server for complete environment refresh

# Parse arguments
EXPUNGE=false
for arg in "$@"; do
  if [[ "$arg" == "--expunge" ]]; then
    EXPUNGE=true
  fi
done

# Backup overconfig.nix
mkdir -p ~/.backup/.config/nixpkgs
timestamp=$(date +%Y%m%d-%H%M%S)
cp ~/.config/nixpkgs/overconfig.nix ~/.backup/.config/nixpkgs/overconfig."$timestamp".nix
ln -sf overconfig."$timestamp".nix ~/.backup/.config/nixpkgs/overconfig.latest.nix

# Temporarily track overconfig.nix
git -C ~/.config/nixpkgs update-index --no-assume-unchanged overconfig.nix

# Run home-manager switch
home-manager switch --flake ~/.config/nixpkgs

# Expunge tmux server for complete refresh if flag was passed
if [[ "$EXPUNGE" == "true" ]]; then
  echo "Expunging tmux server for complete environment refresh..."
  tmux kill-server 2>/dev/null || true
fi
