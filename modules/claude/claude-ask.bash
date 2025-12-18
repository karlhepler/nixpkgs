#!/usr/bin/env bash

# Claude Quick Question Assistant
# Takes model as first argument (haiku, sonnet, opus)
# Combines remaining arguments into a single question
# Adds contextual information and calls claude without TUI

# Check if claude CLI is available
if ! command -v claude &> /dev/null; then
    echo "Error: claude CLI is not installed" >&2
    echo "Install from: https://claude.ai/code" >&2
    exit 1
fi

# Get model from first argument
model="$1"
shift  # Remove model arg, leaving user's question

# Validate model argument
if [[ ! "$model" =~ ^(haiku|sonnet|opus)$ ]]; then
    echo "Error: Invalid model '$model'. Expected haiku, sonnet, or opus." >&2
    exit 1
fi

# Combine remaining arguments into question
question="$*"

# Validate question is provided
if [ -z "$question" ]; then
    echo "Error: No question provided" >&2
    echo "Usage: q|qq|qqq <your question here>" >&2
    exit 1
fi

# Gather context information
user_name="@USER_NAME@"  # Will be substituted by Nix
current_dir="$PWD"
system_info="$(uname -s) $(uname -m)"
current_date="$(date +%Y-%m-%d)"

# Build context-prefixed prompt
context="[Context: User: $user_name | Dir: $current_dir | System: $system_info | Date: $current_date]"
full_prompt="$context

$question"

# Call claude with appropriate flags
claude --print \
       --output-format text \
       --model "$model" \
       "$full_prompt"
