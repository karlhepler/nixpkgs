#!/usr/bin/env bash

set -eou pipefail

: "${EDITOR:?EDITOR is not set. Please export it before running this script.}"
: "${JIRA_API_TOKEN:?JIRA_API_TOKEN is not set. Please export it before running this script.}"
: "${GITHUB_TOKEN:?GITHUB_TOKEN is not set. Please export it before running this script.}"

main() {
	local body summary
	local issue_number="${1:-}"

	if [ -z "$issue_number" ]; then
		# get summary and body
		local input_file; input_file="$(mktemp)"
		"$EDITOR" "$input_file" # create summary and body in editor
		summary="$(get_summary_from_file "$input_file")"
		body="$(get_body_from_file "$input_file")"

		# create jira issue
		issue_number="$(create_jira_issue "$summary" "$body")"

		# add the issue to the current sprint
		local sprint_id; sprint_id="$(get_current_sprint_id)"
		add_issue_to_sprint "$sprint_id" "$issue_number"
		transition_issue_to_development "$issue_number"
	else
		summary="$(get_summary_from_issue "$issue_number")"
		body="$(get_body_from_issue "$issue_number")"
	fi

	# exit early if not git repository
	if ! is_git_repository; then
		>&2 echo 'Not a git repository. Exiting.'
		exit
	fi

	# check out a new branch and push a noop commit
	git_trunk
	branch="karlhepler/${issue_number}_$(branchify_string "$summary")"
	git checkout -b "$branch"
	git commit --allow-empty -m 'initial commit'
	git push

	# create a draft pull request for this branch
	gh pr create --draft --title "${issue_number}: $summary" --body "$body"
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
	local summary="${1:?create_jira_issue <summary> [body]}"
	local body="$2" # this can be empty
	local stdout_file; stdout_file="$(mktemp)"
	jira issue create \
		--type Task \
		--summary "$summary" \
		--body "$body" \
		--assignee "$(jira me)" \
		--custom story-points=1 \
		--custom investment-area='Infrastructure Platform' \
		--no-input \
		| tee "$stdout_file" >&2

	sed -n 's/.*\(PEP-[0-9]\{1,\}\).*/\1/p' "$stdout_file"
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

is_git_repository() {
	git rev-parse --is-inside-work-tree > /dev/null 2>&1
}

git_trunk() {
	git remote set-head origin -a
	trunk="$(git symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/origin/@@')"
	git checkout "$trunk"
	git pull
}

branchify_string() {
	local string="${1:?branchify_string <string>}"
	local max_length=30
	branchified="$(sed 's/ /_/g; s/[^A-z0-9]//g; s/[A-Z]/\L&/g' <<< "$string")"
	echo "${branchified:0:max_length}"
}

get_summary_from_issue() {
	local issue_number="${1:?get_summary_from_issue <issue_number>}"
	jira issue view "$issue_number" --raw | jq --raw-output '.fields.summary'
}

get_body_from_issue() {
	local issue_number="${1:?get_body_from_issue <issue_number>}"
	jira issue view "$issue_number" --raw | jq --raw-output '.fields.description.content[0].content[0].text'
}

main "$@"
