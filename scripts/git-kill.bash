#!/usr/bin/env bash
set -euo pipefail

# Command line flags
NUCLEAR_MODE=false
DRY_RUN=false
AUTO_CONFIRM=false

# Parse command line arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --nuclear)
                NUCLEAR_MODE=true
                shift
                ;;
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            --auto-confirm)
                AUTO_CONFIRM=true
                shift
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                error "Unknown option: $1"
                ;;
        esac
    done
}

show_help() {
    echo "git-kill - Safe repository reset tool"
    echo
    echo "USAGE:"
    echo "  git-kill                Reset repository safely (respects .gitignore)"
    echo "  git-kill --dry-run      Show what would be done without executing"
    echo "  git-kill --nuclear      🚨 DANGEROUS: Delete everything (ignores .gitignore)"
    echo
    echo "DESCRIPTION:"
    echo "  Resets your repository to the last commit, removing uncommitted changes"
    echo "  and untracked files. By default, respects .gitignore patterns to preserve"
    echo "  local configuration, build caches, and IDE settings."
    echo
    echo "  --nuclear mode is equivalent to:"
    echo "    rm -rf * && git clone <repo> ."
    echo
    echo "OPTIONS:"
    echo "  --dry-run    Show preview without making changes"
    echo "  --nuclear    🚨 Delete everything (requires 'NUKE IT' confirmation)"
    echo "  --help, -h   Show this help message"
}

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
    parse_args "$@"

    validate_git_repository

    local repo_root
    repo_root="$(git rev-parse --show-toplevel)"
    cd "$repo_root"

    local current_branch
    current_branch="$(get_current_branch)"

    status "Starting git-kill for: $repo_root"

    # Show preview and get confirmation
    if [ "$AUTO_CONFIRM" != true ]; then
        if ! show_preview_and_confirm "$current_branch"; then
            info "Operation cancelled by user"
            exit 0
        fi
    fi

    if [ "$DRY_RUN" = true ]; then
        info "Dry run complete - no changes made"
        exit 0
    fi

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
        else
            error "Failed to create safety stash - aborting for safety"
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
            git-kill --auto-confirm
        else
            # Fallback if git-kill not available in submodule context
            git reset --hard
            git clean -fd
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
    if [ "$NUCLEAR_MODE" = true ]; then
        status "🚨 NUCLEAR MODE: Removing ALL untracked files (ignoring .gitignore)..."
        git clean -fdx
    else
        status "Removing untracked files (respecting .gitignore)..."
        git clean -fd
    fi
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

# Preview and confirmation system
show_preview_and_confirm() {
    local current_branch="$1"

    if [ "$NUCLEAR_MODE" = true ]; then
        show_nuclear_warning
        if ! confirm_nuclear; then
            return 1
        fi
    fi

    echo
    echo -e "${BLUE}📋 git-kill preview for branch: $current_branch${NC}"
    echo "==========================================="
    echo

    show_file_preview

    if [ "$DRY_RUN" = true ]; then
        return 0
    fi

    echo
    if [ "$NUCLEAR_MODE" = true ]; then
        return 0  # Already confirmed above
    else
        confirm_safe_operation
    fi
}

show_nuclear_warning() {
    echo
    echo -e "${RED}🚨🚨🚨 NUCLEAR MODE ACTIVATED 🚨🚨🚨${NC}"
    echo
    echo -e "${RED}This will DELETE EVERYTHING not committed, including:${NC}"
    echo -e "${RED}❌ ALL local configuration files${NC}"
    echo -e "${RED}❌ ALL build caches (node_modules, Unity Library/, etc.)${NC}"
    echo -e "${RED}❌ ALL IDE settings (.idea, .vscode)${NC}"
    echo -e "${RED}❌ ALL environment files (.env, .envrc)${NC}"
    echo -e "${RED}❌ EVERYTHING in .gitignore${NC}"
    echo
    echo -e "${RED}This is equivalent to:${NC}"
    echo -e "${RED}rm -rf * && git clone <repo> .${NC}"
    echo
}

confirm_nuclear() {
    echo -e "${RED}Are you ABSOLUTELY SURE?${NC}"
    echo -n "Type 'NUKE IT' to confirm: "
    read -r confirmation

    if [ "$confirmation" = "NUKE IT" ]; then
        return 0
    else
        return 1
    fi
}

confirm_safe_operation() {
    echo -n "Proceed with git-kill? (y/N): "
    read -r confirmation

    case "$confirmation" in
        [yY]|[yY][eE][sS])
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

show_file_preview() {
    local tracked_changes untracked_files ignored_files
    local tracked_count untracked_count ignored_count

    # Get tracked files with changes
    tracked_changes=$(git diff --name-only HEAD 2>/dev/null || true)
    tracked_count=$(echo "$tracked_changes" | wc -l | tr -d ' ')
    # Ensure tracked_count is a valid integer
    tracked_count=$((tracked_count + 0))

    # Get untracked files (respecting .gitignore unless nuclear)
    if [ "$NUCLEAR_MODE" = true ]; then
        untracked_files=$(git ls-files --others --exclude-standard 2>/dev/null || true)
        ignored_files=$(git ls-files --others --ignored --exclude-standard 2>/dev/null || true)
    else
        untracked_files=$(git ls-files --others --exclude-standard 2>/dev/null || true)
        ignored_files=""  # Don't show ignored files in safe mode
    fi

    if [ -n "$untracked_files" ]; then
        untracked_count=$(echo "$untracked_files" | wc -l | tr -d ' ')
    else
        untracked_count=0
    fi
    # Ensure untracked_count is a valid integer
    untracked_count=$((untracked_count + 0))

    if [ -n "$ignored_files" ]; then
        ignored_count=$(echo "$ignored_files" | wc -l | tr -d ' ')
    else
        ignored_count=0
    fi
    # Ensure ignored_count is a valid integer
    ignored_count=$((ignored_count + 0))

    # Nuclear mode shows everything that will be deleted
    if [ "$NUCLEAR_MODE" = true ]; then
        echo "❌ DELETE EVERYTHING:"
        echo
    fi

    # Show files that will be reset
    if [ "$tracked_count" -gt 0 ]; then
        echo "🔶 Reset: $tracked_count files"
        while IFS= read -r file; do
            if [ -n "$file" ]; then
                echo "  $file"
            fi
        done <<< "$tracked_changes"
        echo
    fi

    # Show files that will be deleted
    if [ "$untracked_count" -gt 0 ]; then
        echo "❌ Delete: $untracked_count untracked files"
        while IFS= read -r file; do
            if [ -n "$file" ]; then
                if [ -f "$file" ]; then
                    echo "  $file"
                elif [ -d "$file" ]; then
                    local file_count dir_size
                    file_count=$(find "$file" -type f 2>/dev/null | wc -l | tr -d ' ')
                    dir_size=$(du -sh "$file" 2>/dev/null | cut -f1 || echo "?")
                    echo "  $file/ ($dir_size, $file_count files)"
                else
                    echo "  $file"
                fi
            fi
        done <<< "$untracked_files"
        echo
    fi

    # Show ignored files that will be deleted in nuclear mode
    if [ "$NUCLEAR_MODE" = true ] && [ "$ignored_count" -gt 0 ]; then
        echo "❌ Delete: $ignored_count ignored files (normally preserved)"
        while IFS= read -r file; do
            if [ -n "$file" ]; then
                if [ -f "$file" ]; then
                    echo "  $file"
                elif [ -d "$file" ]; then
                    local file_count dir_size
                    file_count=$(find "$file" -type f 2>/dev/null | wc -l | tr -d ' ')
                    dir_size=$(du -sh "$file" 2>/dev/null | cut -f1 || echo "?")
                    echo "  $file/ ($dir_size, $file_count files)"
                else
                    echo "  $file"
                fi
            fi
        done <<< "$ignored_files"
        echo
    fi

    # Show stash information if there are uncommitted changes
    if has_uncommitted_changes; then
        echo "💾 Stash: Uncommitted changes will be saved (recover with: git stash pop)"
    fi

    # Show total size for nuclear mode
    if [ "$NUCLEAR_MODE" = true ]; then
        local total_size
        total_size=$(du -sh . 2>/dev/null | cut -f1 || echo "?")
        echo "Total cleanup: ~$total_size"
        echo
    fi

    if [ "$tracked_count" -eq 0 ] && [ "$untracked_count" -eq 0 ] && [ "$ignored_count" -eq 0 ]; then
        echo "✅ Repository is already clean - no changes needed"
    fi
}


# Execute main function with all arguments
main "$@"