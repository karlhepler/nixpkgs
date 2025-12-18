#!/usr/bin/env bash
set -eou pipefail

# Interactive branch selector with fzf
# - Lists branches sorted by most recent commit with relative dates
# - Shows git log preview in fzf
# - Default filter: karlhepler/* branches (can override with argument)
# - Enter to checkout selected branch

show_help() {
  echo "git-branches - Interactive branch selector with fzf"
  echo
  echo "USAGE:"
  echo "  git-branches [filter]    List branches matching filter (default: karlhepler/)"
  echo "  git-branches --help      Show this help message"
  echo
  echo "DESCRIPTION:"
  echo "  Lists git branches sorted by most recent commit with relative dates."
  echo "  Operates in two modes depending on output destination:"
  echo
  echo "  Interactive mode (terminal): Shows fzf selector with branch preview"
  echo "  - Press Enter to checkout selected branch"
  echo "  - Preview shows last 3 commits with diff"
  echo
  echo "  Non-interactive mode (pipe): Outputs branch names only"
  echo "  - Used by scripts like git-resume"
  echo "  - Sorted by most recent commit"
  echo
  echo "ARGUMENTS:"
  echo "  filter    Optional branch filter pattern (default: karlhepler/)"
  echo "            Searches both local (refs/heads/) and remote (refs/remotes/)"
  echo
  echo "EXAMPLES:"
  echo "  # Show karlhepler/* branches interactively"
  echo "  git-branches"
  echo
  echo "  # Show all feature/* branches"
  echo "  git-branches feature/"
  echo
  echo "  # Show all branches"
  echo "  git-branches ''"
  echo
  echo "  # Use in scripts (non-interactive mode)"
  echo "  git-branches | head -1"
  echo
  echo "NOTES:"
  echo "  - Requires fzf for interactive mode"
  echo "  - Branches sorted by commit date (newest first)"
  echo "  - Both local and remote branches shown"
}

# Parse arguments
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

branch="${1:-karlhepler/}"

# check if the script's output is connected to a terminal
if [ -t 1 ]; then
  # Interactive mode: show branch names with relative dates, formatted for fzf
  git for-each-ref --sort=-committerdate --format='%(refname:short)|%(committerdate:relative)' "refs/heads/${branch}*" "refs/remotes/${branch}*" \
    | awk -F'|' '{printf "%-50s (%s)\n", $1, $2}' \
    | fzf --preview 'git log --color {1} -p -n 3' --bind 'enter:execute(git checkout {1})+abort'
else
  # Non-interactive mode: output branch names only (for scripts like git-resume)
  git for-each-ref --sort=-committerdate --format='%(refname:short)' "refs/heads/${branch}*" "refs/remotes/${branch}*"
fi
