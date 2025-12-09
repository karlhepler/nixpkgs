# Merge trunk branch (main/master) into current branch
# - Fetches latest trunk from remote
# - Merges trunk changes into current working branch
# - Keeps you on your current branch after sync

# Determine trunk branch (main or master)
git remote set-head origin -a
trunk="$(git symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/origin/@@')"

# Fetch latest trunk from remote and merge into current branch
git fetch origin "$trunk"
git merge "origin/$trunk"
