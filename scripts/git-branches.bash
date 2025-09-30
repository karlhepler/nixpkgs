# Interactive branch selector with fzf
# - Lists branches sorted by most recent commit
# - Shows git log preview in fzf
# - Default filter: karlhepler/* branches (can override with argument)
# - Enter to checkout selected branch

branch="${1:-karlhepler/}"
output="$(git for-each-ref --sort=-committerdate --format='%(refname:short)' "refs/heads/${branch}*" "refs/remotes/${branch}*")"

# check if the script's output is connected to a terminal
if [ -t 1 ]; then
  echo "$output" | fzf --preview 'git log --color {} -p -n 3' --bind 'enter:execute(git checkout {})+abort'
else
  echo "$output"
fi
