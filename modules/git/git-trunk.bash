#!/usr/bin/env bash
set -eou pipefail

# Switch to trunk branch and optionally pull latest changes
# - Trunk is origin/HEAD when set, otherwise the first local branch named
#   main, master or develop
# - Updates local trunk branch with remote changes (unless --no-pull)
# - --print only prints the trunk branch name; it touches nothing and never
#   uses the network (other scripts call it instead of re-detecting trunk)

show_help() {
  echo "git-trunk - Switch to trunk branch and pull latest"
  echo
  echo "USAGE:"
  echo "  git-trunk              Checkout trunk and pull latest changes"
  echo "  git-trunk --no-pull    Checkout trunk without pulling"
  echo "  git-trunk --print      Print the trunk branch name and exit"
  echo
  echo "DESCRIPTION:"
  echo "  Switches to the trunk branch and pulls the latest changes from the"
  echo "  remote. Trunk is whatever origin/HEAD points at; if that is not set,"
  echo "  the first local branch named main, master or develop."
  echo
  echo "OPTIONS:"
  echo "  --no-pull    Skip pulling latest changes (just checkout trunk)"
  echo "  --print      Print the trunk branch name only (no checkout, no network)"
  echo
  echo "EXAMPLES:"
  echo "  # Switch to trunk and update"
  echo "  git-trunk"
  echo
  echo "  # Switch to trunk without updating"
  echo "  git-trunk --no-pull"
  echo
  echo "  # Which branch is trunk?"
  echo "  git-trunk --print"
  echo
  echo "NOTES:"
  echo "  - Pulls latest changes after checkout (unless --no-pull)"
  echo "  - Use git-sync to merge trunk into current branch instead"
}

# Print the trunk branch name, or fail
print_trunk() {
  local ref branch
  if ref="$(git symbolic-ref -q refs/remotes/origin/HEAD)"; then
    echo "${ref#refs/remotes/origin/}"
    return 0
  fi
  for branch in main master develop; do
    if git show-ref --verify --quiet "refs/heads/$branch"; then
      echo "$branch"
      return 0
    fi
  done
  echo "git-trunk: could not determine the trunk branch (try: git remote set-head origin --auto)" >&2
  return 1
}

# Parse arguments
mode=switch
case "${1:-}" in
  -h|--help)
    show_help
    exit 0
    ;;
  --print)
    mode=print
    ;;
  --no-pull)
    mode=no-pull
    ;;
esac

if [ "$mode" = print ]; then
  print_trunk
  exit 0
fi

if [ "$mode" = switch ]; then
  git remote set-head origin -a # make sure there is an origin/HEAD
fi
git checkout "$(print_trunk)"

if [ "$mode" = switch ]; then
  git pull
fi
