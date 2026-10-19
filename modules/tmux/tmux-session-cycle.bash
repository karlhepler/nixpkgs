# Switch the client to the next or previous tmux session, ordered by session id
# and wrapping around at either end.
#
# USAGE: tmux-session-cycle next|prev

direction="${1:?usage: tmux-session-cycle next|prev}"

# session_id is "$N"; strip the "$" so the sort is numeric on the id.
sessions=$(tmux list-sessions -F '#{session_id}:#S' | sed 's/^\$//' | sort -t: -k1,1n | cut -d: -f2-)
current=$(tmux display-message -p '#S')
count=$(echo "$sessions" | wc -l | tr -d ' ')

idx=0
i=0
while IFS= read -r s; do
  i=$((i + 1))
  if [ "$s" = "$current" ]; then idx=$i; fi
done <<< "$sessions"

case "$direction" in
  next) n=$((idx % count + 1)) ;;
  prev) n=$(((idx - 2 + count) % count + 1)) ;;
  *) echo "usage: tmux-session-cycle next|prev" >&2; exit 1 ;;
esac

tmux switch-client -t "$(echo "$sessions" | sed -n "${n}p")"
