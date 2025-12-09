# Quick save: commit and push in one command
# - Combines 'commit' and 'push' operations
# - Stages all changes, commits with message, and pushes to remote

commit "$*"
push
