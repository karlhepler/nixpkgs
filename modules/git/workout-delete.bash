#!/usr/bin/env bash
# Standalone script for deleting worktrees with confirmation
# Called from fzf execute binding

path="$1"
branch="$2"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Clear screen
printf "\033[2J\033[H"

# Validate
if [ ! -d "$path" ]; then
  echo -e "${RED}Error: Worktree not found${NC}"
  exit 1
fi
cd "$path" || exit 1

# Get branch info
current_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "$branch")
has_changes=$(git status --porcelain 2>/dev/null)

# Show dialog
echo -e "${CYAN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║${NC}${BOLD}                    DELETE WORKTREE                             ${NC}${CYAN}║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo
echo -e "  ${BOLD}Branch:${NC} ${CYAN}$current_branch${NC}"
echo -e "  ${BOLD}Path:${NC} $path"
echo

if [ -n "$has_changes" ]; then
  echo -e "  ${RED}⚠️  WARNING: UNCOMMITTED CHANGES!${NC}"
  echo -e "  ${RED}⚠️  These will be PERMANENTLY LOST!${NC}"
  echo
  echo -e "  ${BOLD}Modified files:${NC}"
  echo "$has_changes" | head -10
  count=$(echo "$has_changes" | wc -l | tr -d ' ')
  [ "$count" -gt 10 ] && echo -e "  ${YELLOW}... and $((count - 10)) more${NC}"
else
  echo -e "  ${GREEN}✓ No uncommitted changes${NC}"
fi

echo
echo -e "${CYAN}────────────────────────────────────────────────────────────────${NC}"
echo
echo -ne "  ${YELLOW}Delete this worktree? [y/N]:${NC} "

# Read from /dev/tty, wait for Enter
read -r response < /dev/tty
echo

# Check response (only y or Y confirms)
if [ "$response" = "y" ] || [ "$response" = "Y" ]; then
  echo -e "  ${BLUE}Deleting...${NC}"
  if git worktree remove "$path" --force 2>&1; then
    echo -e "  ${GREEN}✓ Deleted: $path${NC}"
  else
    echo -e "  ${RED}✗ Failed to delete${NC}"
    sleep 2
    exit 1
  fi
else
  echo -e "  ${YELLOW}✗ Cancelled${NC}"
fi

sleep 1
