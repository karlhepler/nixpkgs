# Switch to trunk branch (main/master) and pull latest changes
# - Automatically detects whether trunk is 'main' or 'master'
# - Updates local trunk branch with remote changes

git remote set-head origin -a # make sure there is an origin/HEAD
trunk="$(git symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/origin/@@')"
git checkout "$trunk"
git pull
