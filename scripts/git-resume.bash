# Resume work on most recently used branch
# - Checks out the most recently committed branch
# - Uses git-branches command to find most recent branch

git checkout "$(git branches | head -1)"
