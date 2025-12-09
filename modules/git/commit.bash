# Git commit with automatic staging
# - Stages all changes in repository root before committing
# - Special case: 'noop' message creates empty commit

msg="$*"
if [ "$msg" == 'noop' ]; then
  git commit --allow-empty -m "$msg"
else
  git add "$(git rev-parse --show-toplevel)"
  git commit -m "$msg"
fi
