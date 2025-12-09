# Smart git pull with automatic upstream tracking
# - Pulls changes from remote branch
# - Automatically sets upstream tracking if not configured
# - Handles missing tracking information gracefully

set +e # keep going
git pull 2> >(
  must_set_upstream=
  while IFS= read -r line; do
    if [[ $line == 'There is no tracking information for the current branch.' ]]; then
      must_set_upstream=true
      break
    fi
    echo "$line" >&2
  done

  git_pull_exit_code=$?
  if [[ $must_set_upstream != true ]]; then
    exit $git_pull_exit_code
  fi

  set -e # reset error handling
  branch="$(git symbolic-ref --short HEAD)"
  git branch --set-upstream-to="origin/$branch" "$branch"
  git pull
)
