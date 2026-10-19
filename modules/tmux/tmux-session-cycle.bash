# Switch the client to the next or previous tmux session, ordered by session id
# (creation order) and wrapping around at either end.
#
# Sessions are addressed by id ($N), never by name: some session names contain dots
# ("N.E.R.D."), which tmux would read as a window/pane separator in a target.
#
# USAGE: tmux-session-cycle next|prev

direction="${1:?usage: tmux-session-cycle next|prev}"

# session_id is "$N"; strip the "$" so the sort is numeric on the id.
mapfile -t ids < <(tmux list-sessions -F '#{session_id}' | tr -d '$' | sort -n)
current="$(tmux display-message -p '#{session_id}')"
current="${current#\$}"
count="${#ids[@]}"

idx=0
for i in "${!ids[@]}"; do
  if [ "${ids[$i]}" = "$current" ]; then idx=$((i + 1)); fi
done

case "$direction" in
  next) n=$((idx % count + 1)) ;;
  prev) n=$(((idx - 2 + count) % count + 1)) ;;
  *) echo "usage: tmux-session-cycle next|prev" >&2; exit 1 ;;
esac

tmux switch-client -t "\$${ids[$((n - 1))]}"
