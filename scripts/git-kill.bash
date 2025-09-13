#!/usr/bin/env bash
set -euo pipefail

# Environment setup
readonly DATE_FORMAT='%Y-%m-%d %H:%M:%S'

# Color codes for output (if terminal supports it)
if [[ -t 1 ]]; then
    readonly RED='\033[0;31m'
    readonly GREEN='\033[0;32m'
    readonly YELLOW='\033[1;33m'
    readonly BLUE='\033[0;34m'
    readonly NC='\033[0m' # No Color
else
    readonly RED=''
    readonly GREEN=''
    readonly YELLOW=''
    readonly BLUE=''
    readonly NC=''
fi

# Trap for cleanup on failure or interruption
trap 'handle_exit $?' EXIT INT TERM

# Main entry point
main() {

    validate_git_repository

    local repo_root
    repo_root="$(git rev-parse --show-toplevel)"
    cd "$repo_root"

    local current_branch
    current_branch="$(get_current_branch)"

    status "Starting git-kill for: $repo_root"

    handle_uncommitted_changes
    reset_submodules
    clear_git_operation_states
    perform_hard_reset "$current_branch"
    clean_untracked_files
    restore_lfs_files
    handle_special_worktrees
    refresh_git_index

    report_success "$current_branch" "$repo_root"
}

# Validation functions
validate_git_repository() {
    if ! git rev-parse --git-dir &>/dev/null; then
        error "Not in a git repository"
    fi
}

# Git state functions
get_current_branch() {
    git symbolic-ref --short HEAD 2>/dev/null || git rev-parse HEAD
}

get_reset_target() {
    local branch="$1"

    if git ls-remote --exit-code --heads origin "$branch" &>/dev/null; then
        echo "origin/$branch"
    else
        echo "HEAD"
    fi
}

# Safety functions
handle_uncommitted_changes() {
    if has_uncommitted_changes; then
        status "Creating safety stash for uncommitted changes..."
        local stash_msg
        stash_msg="git-kill safety stash: $(date "+$DATE_FORMAT")"

        if git stash push -u -m "$stash_msg"; then
            info "Changes stashed (recover with: git stash pop)"
        fi
    fi
}

has_uncommitted_changes() {
    ! git diff-index --quiet HEAD -- 2>/dev/null ||
    [ -n "$(git ls-files --others --exclude-standard)" ]
}

# Submodule handling
reset_submodules() {
    if ! has_submodules; then
        return 0
    fi

    status "Resetting submodules recursively..."

    # shellcheck disable=SC2016
    git submodule foreach --recursive '
        if command -v git-kill &>/dev/null; then
            echo "  Running git-kill in $displaypath"
            git-kill
        else
            # Fallback if git-kill not available in submodule context
            git reset --hard
            git clean -fdx
        fi
    '

    git submodule update --init --recursive --force
}

has_submodules() {
    [ -f .gitmodules ] && [ -n "$(git submodule status 2>/dev/null)" ]
}

# Core reset operations
clear_git_operation_states() {
    status "Clearing any in-progress operations..."

    local state_files=(
        ".git/rebase-merge"
        ".git/rebase-apply"
        ".git/MERGE_HEAD"
        ".git/CHERRY_PICK_HEAD"
        ".git/BISECT_START"
        ".git/BISECT_LOG"
    )

    for file in "${state_files[@]}"; do
        rm -rf "$file" 2>/dev/null || true
    done
}

perform_hard_reset() {
    local current_branch="$1"
    local reset_target
    reset_target="$(get_reset_target "$current_branch")"

    status "Hard reset to $reset_target..."
    git reset --hard "$reset_target"
}

clean_untracked_files() {
    status "Removing ALL untracked files and directories..."
    git clean -fdx
}

# LFS handling
restore_lfs_files() {
    if ! has_lfs_files; then
        return 0
    fi

    status "Restoring LFS files..."
    if ! git lfs pull; then
        warn "LFS pull failed - files may be pointers"
    fi
}

has_lfs_files() {
    command -v git-lfs &>/dev/null &&
    git lfs ls-files &>/dev/null 2>&1 &&
    [ -n "$(git lfs ls-files 2>/dev/null)" ]
}

# Special worktree handling
handle_special_worktrees() {
    handle_sparse_checkout
    handle_partial_clone
    refresh_file_permissions
}

handle_sparse_checkout() {
    if [ ! -f .git/info/sparse-checkout ]; then
        return 0
    fi

    status "Reapplying sparse-checkout..."
    git read-tree -m -u HEAD
}

handle_partial_clone() {
    if ! git config --get remote.origin.promisor &>/dev/null; then
        return 0
    fi

    status "Detected partial clone - refreshing..."
    git fetch --refetch 2>/dev/null || true
}

refresh_file_permissions() {
    if [ ! -f .gitattributes ]; then
        return 0
    fi

    if grep -q "\\* text=auto" .gitattributes 2>/dev/null; then
        status "Refreshing file permissions..."
        git checkout-index -f -a 2>/dev/null || true
    fi
}

# Index operations
refresh_git_index() {
    status "Refreshing git index..."
    git update-index --refresh --really-refresh 2>/dev/null || true
}

# Reporting functions
report_success() {
    local branch="$1"
    local location="$2"

    echo -e "${GREEN}✅ git-kill complete!${NC}"
    echo "   Branch: $branch"
    echo "   Location: $location"

    report_stash_status
}

report_stash_status() {
    local stash_count
    stash_count=$(git stash list | wc -l)

    if [ "$stash_count" -gt 0 ]; then
        local latest_stash
        latest_stash=$(git stash list -1 --format='%gs')
        echo -e "${YELLOW}💡 You have $stash_count stash(es). Latest: $latest_stash${NC}"
    fi
}

# Output functions
status() {
    echo -e "${BLUE}→${NC} $1"
}

info() {
    echo -e "  ${GREEN}✓${NC} $1"
}

warn() {
    echo -e "  ${YELLOW}⚠️${NC}  $1" >&2
}

error() {
    echo -e "${RED}❌ Error:${NC} $1" >&2
    exit 1
}

# Exit handling
handle_exit() {
    local exit_code=$1

    if [ "$exit_code" -ne 0 ]; then
        echo -e "${YELLOW}⚠️  git-kill interrupted or failed (exit code: $exit_code)${NC}" >&2
        echo "Repository may be in an inconsistent state. Consider running 'git status' to check." >&2
    fi

    exit "$exit_code"
}

# Execute main function with all arguments
main "$@"