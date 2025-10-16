# Interactive branch selector with fzf
# - Lists branches sorted by most recent commit with relative dates
# - Shows git log preview in fzf
# - Default filter: karlhepler/* branches (can override with argument)
# - Enter to checkout selected branch

branch="${1:-karlhepler/}"

# check if the script's output is connected to a terminal
if [ -t 1 ]; then
  # Interactive mode: show branch names with relative dates, formatted for fzf
  git for-each-ref --sort=-committerdate --format='%(refname:short)|%(committerdate:relative)' "refs/heads/${branch}*" "refs/remotes/${branch}*" \
    | awk -F'|' '{printf "%-50s (%s)\n", $1, $2}' \
    | fzf --preview 'git log --color {1} -p -n 3' --bind 'enter:execute(git checkout {1})+abort'
else
  # Non-interactive mode: output branch names only (for scripts like git-resume)
  git for-each-ref --sort=-committerdate --format='%(refname:short)' "refs/heads/${branch}*" "refs/remotes/${branch}*"
fi
