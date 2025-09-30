# Create/recreate temporary branch for experiments
# - Deletes existing karlhepler/tmp branch if it exists
# - Creates fresh karlhepler/tmp branch from current HEAD
# - Useful for throwaway work and experiments

git branch -D karlhepler/tmp || true
git checkout -b karlhepler/tmp
