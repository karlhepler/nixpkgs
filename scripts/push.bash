# Smart git push with automatic upstream tracking
# - Pushes changes to remote branch
# - Automatically sets upstream tracking on first push
# - Passes through additional arguments to git push

git_push='git push'
if ! git rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
  git_push="$git_push --set-upstream"
fi
$git_push "$@"
