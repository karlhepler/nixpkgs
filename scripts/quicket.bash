#!/usr/bin/env bash

set -eou pipefail

: "${EDITOR:?EDITOR is not set. Please export it before running this script.}"
: "${JIRA_API_TOKEN:?JIRA_API_TOKEN is not set. Please export it before running this script.}"

main() {
	local cmd="${1:-next}"

	# get summary and body
	local input_file; input_file="$(mktemp)"
	"$EDITOR" "$input_file" # create summary and body in editor
	local summary; summary="$(get_summary_from_file "$input_file")"
	local body; body="$(get_body_from_file "$input_file")"

	"cmd_$cmd" "$summary" "$body"
}

cmd_next() {
	local summary="${1:?cmd_next <summary> [body]}" body="$2" issue_number
	create_jira_issue "$summary" "$body"
}

cmd_now() {
	local summary="${1:?cmd_now <summary> [body]}" body="$2" issue_number
	issue_number="$(create_jira_issue "$summary" "$body" '--custom-story-points=1')"
	transition_issue_to_development "$issue_number"
}

get_summary_from_file() {
	local file="${1:?get_summary_from_file <file>}"
	head -n 1 "$file"
}

get_body_from_file() {
	local file="${1:?get_body_from_file <file>}"
	local copy; copy="$(mktemp)"
	cp "$file" "$copy"
	sed '1d' "$copy" | sed '/./,$!d'
}

create_jira_issue() {
	local summary="${1:?create_jira_issue <summary>}"
	local body="$2"
	local custom_jira_args="${3:-}"
	local stdout_file; stdout_file="$(mktemp)"

	# shellcheck disable=SC2086
	jira issue create --no-input \
		--type Task \
		--summary "$summary" \
		--body "$body" \
		--assignee "$(jira me)" \
		--custom investment-area='Infrastructure Platform' \
		$custom_jira_args \
		| tee "$stdout_file" >&2

	sed -n 's/.*\(DEV-[0-9]\{1,\}\).*/\1/p' "$stdout_file"
}

get_current_sprint_id() {
	jira sprint list --plain --no-headers --state active --table --columns ID
}

add_issue_to_sprint() {
	local errmsg='add_issue_to_sprint <sprint_id> <issue_number>'
	local sprint_id="${1:?$errmsg}"
	local issue_number="${2:?$errmsg}"
	jira sprint add "$sprint_id" "$issue_number"
}

transition_issue_to_development() {
	local issue_number="${1:?transition_issue_to_development <issue_number>}"
	jira issue move "$issue_number" 'Development'
}

main "$@"
