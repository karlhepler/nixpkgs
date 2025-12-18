#!/usr/bin/env bash
set -eou pipefail

# Claude Quick Question Assistant
# Takes model as first argument (haiku, sonnet, opus)
# Combines remaining arguments into a single question
# Adds contextual information and calls claude without TUI

show_help() {
  echo "claude-ask - Quick question assistant for Claude Code"
  echo
  echo "USAGE:"
  echo "  q <question>      Ask Claude using haiku model (fastest)"
  echo "  qq <question>     Ask Claude using sonnet model (balanced)"
  echo "  qqq <question>    Ask Claude using opus model (most capable)"
  echo "  claude-ask --help Show this help message"
  echo
  echo "DESCRIPTION:"
  echo "  Quick question tool that sends questions directly to Claude without"
  echo "  starting the full interactive TUI. Automatically gathers context:"
  echo "  - Current username"
  echo "  - Current directory"
  echo "  - System information (OS and architecture)"
  echo "  - Current date"
  echo
  echo "  The context is prepended to your question to help Claude provide"
  echo "  more relevant answers."
  echo
  echo "MODELS:"
  echo "  haiku    Fastest model for simple questions (q alias)"
  echo "  sonnet   Balanced model for most questions (qq alias)"
  echo "  opus     Most capable model for complex questions (qqq alias)"
  echo
  echo "EXAMPLES:"
  echo "  # Quick question with haiku"
  echo "  q What is the capital of France?"
  echo
  echo "  # More complex question with sonnet"
  echo "  qq How do I parse JSON in bash?"
  echo
  echo "  # Complex analysis with opus"
  echo "  qqq Explain the trade-offs between microservices and monoliths"
  echo
  echo "NOTES:"
  echo "  - Requires claude CLI installed (https://claude.ai/code)"
  echo "  - q/qq/qqq aliases defined in zsh configuration"
  echo "  - Output format is plain text (no TUI)"
  echo "  - Use --print flag for non-interactive output"
}

# Parse arguments for help flag
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

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
