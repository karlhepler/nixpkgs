# Change to git repository root
# - Gets repository root using git rev-parse
# - Outputs cd command for parent shell to evaluate
# - Requires zsh wrapper function to actually change directory

# Check if in git repository
if ! git rev-parse --show-toplevel > /dev/null 2>&1; then
  echo "Error: Not in a git repository" >&2
  exit 1
fi

# Get root path and output cd command
root_path="$(git rev-parse --show-toplevel)"
echo "cd '$root_path'"
