"""
Kanban CLI - File-based kanban board for agent coordination.

Cards are markdown files with YAML frontmatter, stored in column folders.
Priority field controls ordering within columns (lower number = higher priority = top of list).

INSERTION SORT WORKFLOW:
When adding cards to any column, think like insertion sort:
1. Read ALL existing cards in the target column
2. Understand their priorities and relative importance
3. Determine where your new card fits in the sorted order
4. Use position flags (--top, --bottom, --after, --before) to insert correctly
5. System uses large number spacing (1000, 2000, 3000) to leave room for future insertions

PRIORITY RULES:
- Minimum priority: 0 (no negative numbers allowed)
- Empty column: First card defaults to priority 1000 (no position needed!)
- Non-empty column: Use position flags to specify where card belongs
- Recommended spacing: 1000 between cards for easy future insertions
- Lower number = higher priority = appears earlier in list

PICKING NEXT WORK:
1. Run 'kanban list' to see full board state
2. Filter to your session's cards if working in multi-agent scenario
3. Take card with highest priority (lowest number) from your todo
4. Work order is determined by priority within your session/column

COLUMN SEMANTICS (when to use each column):
  todo     - Things that need to be done next, in priority order. Not yet started.
  doing    - Things currently being worked on. Active work in progress.
  blocked  - Things that started but are now blocked waiting for something
             (external dependency, user input, another card, etc.). Not just
             'queued for later' - must have a specific blocking reason.
  done     - Completed work. Archive of what's been accomplished.
  canceled - Work that was abandoned, became obsolete, or is no longer needed.
             Not completed. Kept for historical context and learning.

ENVIRONMENT VARIABLES:
  KANBAN_HIDE_MINE          - Set to "true" to hide your own session's cards by default
                              (show only other sessions). Useful when you're primarily
                              monitoring other agents' work. Can override with --only-mine flag.
  KANBAN_ARCHIVE_DAYS       - Number of days before auto-archiving done cards (default: 30)
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from threading import Event

COLUMNS = ["todo", "doing", "blocked", "done", "canceled"]
ARCHIVE_DAYS_THRESHOLD = int(os.environ.get("KANBAN_ARCHIVE_DAYS", "30"))


def get_git_root() -> Path | None:
    """Find the git repository root, or None if not in a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True
        )
        return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def migrate_waiting_to_blocked(root: Path) -> None:
    """Migrate legacy 'waiting' directory to 'blocked' if it exists."""
    waiting_dir = root / "waiting"
    blocked_dir = root / "blocked"

    if waiting_dir.exists() and not blocked_dir.exists():
        waiting_dir.rename(blocked_dir)
        print(f"Migrated: {waiting_dir} -> {blocked_dir}", file=sys.stderr)
    elif waiting_dir.exists() and blocked_dir.exists():
        # Both exist - merge waiting into blocked
        for card in waiting_dir.glob("*.md"):
            target = blocked_dir / card.name
            if not target.exists():
                card.rename(target)
            else:
                print(f"Warning: Skipping {card.name} (already exists in blocked/)", file=sys.stderr)
        # Remove empty waiting directory
        try:
            waiting_dir.rmdir()
            print("Merged and removed legacy 'waiting' directory", file=sys.stderr)
        except OSError:
            print("Warning: Could not remove 'waiting' directory (not empty)", file=sys.stderr)


def auto_archive_old_cards(root: Path, days_threshold: int = ARCHIVE_DAYS_THRESHOLD) -> None:
    """Archive done cards older than threshold days to archive/YYYY-MM/ folders.

    This runs automatically on every kanban command to keep the done column clean.
    Cards are moved based on their 'updated' timestamp.
    """
    done_dir = root / "done"
    archive_base = root / "archive"

    if not done_dir.exists():
        return

    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_threshold)
    archived_count = 0

    for card in done_dir.glob("*.md"):
        try:
            content = card.read_text()
            frontmatter, _ = parse_frontmatter(content)
            updated_str = frontmatter.get("updated")

            if not updated_str:
                # Skip cards without updated timestamp (fail-safe)
                continue

            updated = parse_iso(updated_str)

            if updated < cutoff_date:
                # Determine archive folder based on updated month
                archive_month = updated.strftime("%Y-%m")
                archive_dir = archive_base / archive_month
                archive_dir.mkdir(parents=True, exist_ok=True)

                # Move card to archive
                target = archive_dir / card.name
                card.rename(target)
                archived_count += 1
        except (ValueError, KeyError):
            # Skip cards with invalid dates (fail-safe)
            continue

    if archived_count > 0:
        print(f"Auto-archived {archived_count} old card(s) to {archive_base}/", file=sys.stderr)


def get_root(args_root: str | None, auto_init: bool = True) -> Path:
    """Get kanban root directory from args, environment, or auto-compute.

    Priority:
    1. Explicit --root argument
    2. KANBAN_ROOT environment variable
    3. Git root + .kanban/ (if in a git repo)
    4. Current directory + .kanban/ (fallback)
    """
    if args_root:
        root = Path(args_root)
    elif root_env := os.environ.get("KANBAN_ROOT"):
        root = Path(root_env)
    else:
        # Use git root if available, otherwise current directory
        base_dir = get_git_root() or Path.cwd()
        root = base_dir / ".kanban"

    # Auto-migrate legacy 'waiting' directory to 'blocked'
    if root.exists():
        migrate_waiting_to_blocked(root)

    # Auto-initialize if needed
    if auto_init and not root.exists():
        for col in COLUMNS:
            (root / col).mkdir(parents=True, exist_ok=True)
        # Create archive directory
        (root / "archive").mkdir(parents=True, exist_ok=True)

    # Auto-archive old done cards
    if root.exists():
        auto_archive_old_cards(root)

    return root


def slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    return re.sub(r"[^a-z0-9-]", "", text.lower().replace(" ", "-"))


def now_iso() -> str:
    """Get current time in ISO format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(date_str: str) -> datetime:
    """Parse ISO format date string."""
    return datetime.fromisoformat(date_str.replace("Z", "+00:00"))


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown content."""
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    frontmatter = {}
    for line in parts[1].strip().split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            frontmatter[key.strip()] = value.strip()

    return frontmatter, "---".join(["", parts[1], parts[2]])


def serialize_frontmatter(frontmatter: dict, body: str) -> str:
    """Serialize frontmatter and body back to markdown."""
    lines = ["---"]
    for key, value in frontmatter.items():
        lines.append(f"{key}: {value}")
    lines.append("---")

    # Body already starts with ---, so we need to handle that
    if body.startswith("---"):
        # Extract body after frontmatter markers
        parts = body.split("---", 2)
        if len(parts) >= 3:
            return "\n".join(lines) + parts[2]

    return "\n".join(lines) + "\n" + body


def find_all_cards(root: Path, include_archived: bool = True) -> list[Path]:
    """Find all card files across all columns and optionally archive."""
    cards = []
    for col in COLUMNS:
        col_path = root / col
        if col_path.exists():
            cards.extend(col_path.glob("*.md"))

    # Include archived cards if requested
    if include_archived:
        archive_base = root / "archive"
        if archive_base.exists():
            # Search all YYYY-MM subdirectories
            for archive_dir in archive_base.iterdir():
                if archive_dir.is_dir():
                    cards.extend(archive_dir.glob("*.md"))

    return cards


def find_cards_in_column(root: Path, col: str) -> list[Path]:
    """Find all cards in a specific column, sorted by priority."""
    col_path = root / col
    if not col_path.exists():
        return []
    cards = list(col_path.glob("*.md"))
    cards.sort(key=get_priority)
    return cards


def next_number(root: Path) -> str:
    """Get next available card number."""
    max_num = 0
    for card in find_all_cards(root):
        match = re.match(r"(\d+)-", card.name)
        if match:
            num = int(match.group(1))
            max_num = max(max_num, num)
    return str(max_num + 1)


def find_card(root: Path, pattern: str) -> Path:
    """Find a card by number or name pattern, searching columns and archive."""
    # Normalize number patterns (no zero-padding)
    if pattern.isdigit():
        pattern = str(int(pattern))

    matches = []

    # First search active columns
    for card in find_all_cards(root, include_archived=False):
        if card.name.startswith(pattern + "-") or pattern in card.name:
            matches.append(card)

    # If not found in active columns, search archive
    if not matches:
        archive_base = root / "archive"
        if archive_base.exists():
            for archive_dir in archive_base.iterdir():
                if archive_dir.is_dir():
                    for card in archive_dir.glob("*.md"):
                        if card.name.startswith(pattern + "-") or pattern in card.name:
                            matches.append(card)

    if not matches:
        print(f"Error: No card found matching '{pattern}'", file=sys.stderr)
        sys.exit(1)

    if len(matches) > 1:
        print(f"Error: Multiple cards match '{pattern}'. Be more specific.", file=sys.stderr)
        sys.exit(1)

    return matches[0]


def validate_priority(priority: int) -> int:
    """Validate priority value - must be >= 0.

    Raises SystemExit with error message if invalid.
    Returns validated priority value.
    """
    if priority < 0:
        print(f"Error: Priority must be >= 0 (got {priority})", file=sys.stderr)
        sys.exit(1)
    return priority


def get_priority(card_path: Path) -> int:
    """Get priority from card frontmatter."""
    content = card_path.read_text()
    frontmatter, _ = parse_frontmatter(content)
    return int(frontmatter.get("priority", 0))


def get_persona(card_path: Path) -> str:
    """Get persona from card frontmatter."""
    content = card_path.read_text()
    frontmatter, _ = parse_frontmatter(content)
    return frontmatter.get("persona", "unassigned")


def get_model(card_path: Path) -> str | None:
    """Get model from card frontmatter."""
    content = card_path.read_text()
    frontmatter, _ = parse_frontmatter(content)
    return frontmatter.get("model")


def update_card(card_path: Path, updates: dict) -> None:
    """Update card frontmatter fields."""
    content = card_path.read_text()
    frontmatter, body = parse_frontmatter(content)

    frontmatter.update(updates)
    frontmatter["updated"] = now_iso()

    card_path.write_text(serialize_frontmatter(frontmatter, body))


def get_todo_context(root: Path) -> list[tuple[int, str, Path]]:
    """Get todo cards with their priorities for display."""
    cards = find_cards_in_column(root, "todo")
    result = []
    for card in cards:
        priority = get_priority(card)
        result.append((priority, card.stem, card))
    return result


def cmd_init(args) -> None:
    """Create kanban board structure."""
    if args.path:
        path = Path(args.path)
    else:
        # Use git root if available, otherwise current directory
        base_dir = get_git_root() or Path.cwd()
        path = base_dir / ".kanban"

    for col in COLUMNS:
        (path / col).mkdir(parents=True, exist_ok=True)

    # Create archive directory
    (path / "archive").mkdir(parents=True, exist_ok=True)

    print(f"Kanban board ready at: {path}")


def cmd_add(args) -> None:
    """Add a new card using insertion sort pattern.

    Insertion Sort Workflow:
    1. Reads ALL existing cards in target column
    2. Requires position specification (--top, --bottom, --after, --before) for non-empty columns
    3. Assigns priority to maintain sorted order
    4. Uses large number spacing (1000, 2000, 3000) for easy future insertions

    Priority Assignment:
    - Empty column: Defaults to 1000 (baseline for first card)
    - --top: Places card at top (lowest priority number)
    - --bottom: Places card at bottom (highest priority number)
    - --after <card>: Places card after specified card
    - --before <card>: Places card before specified card

    All priorities are validated to be >= 0 (no negative numbers).
    """
    root = get_root(args.root)
    target_column = args.status

    # Get current session for filtering
    current_session = get_current_session_id()

    # STEP 1: Read ALL existing cards in target column
    # Priority calculations need ALL cards (priorities are global)
    column_cards = find_cards_in_column(root, target_column)

    # Filter to MY cards for "is empty for me" check (session-aware)
    def is_my_card(card: Path) -> bool:
        card_session = get_session(card)
        if current_session:
            return card_session == current_session or card_session is None
        return True  # No session detected - all cards are "mine"

    my_column_cards = [c for c in column_cards if is_my_card(c)]
    is_empty_column = len(my_column_cards) == 0

    # Show current column state for user guidance (session-filtered)
    todo = []
    if target_column == "todo":
        for card in my_column_cards:
            priority = get_priority(card)
            todo.append((priority, card.stem, card))

    # STEP 2: Determine priority based on position flags
    # This is the core "insertion sort" logic - we're figuring out where
    # in the sorted list the new card belongs, then assigning a priority
    # that positions it correctly.
    if args.top:
        # Insert at top of column (highest priority = lowest number)
        if is_empty_column:
            # Empty column: use 1000 as baseline (leaves room below for future inserts)
            priority = 1000
        else:
            # Find current minimum and go lower (but not below 0)
            min_priority = min((get_priority(c) for c in column_cards), default=0)
            priority = max(0, min_priority - 10)  # Ensure non-negative
    elif args.bottom:
        # Insert at bottom of column (lowest priority = highest number)
        if is_empty_column:
            # Empty column: use 1000 as baseline (consistent with --top)
            priority = 1000
        else:
            # Find current maximum and go higher
            max_priority = max((get_priority(c) for c in column_cards), default=0)
            priority = max_priority + 10
    elif args.after:
        # Insert after specified card (slightly higher number = lower priority)
        ref_card = find_card(root, args.after)
        ref_priority = get_priority(ref_card)
        priority = ref_priority + 5  # Small gap for future insertions
    elif args.before:
        # Insert before specified card (slightly lower number = higher priority)
        ref_card = find_card(root, args.before)
        ref_priority = get_priority(ref_card)
        priority = max(0, ref_priority - 5)  # Ensure non-negative
    else:
        # No position specified - this is where we enforce "think before you add"
        if is_empty_column:
            # Empty column: default to 1000 (no position needed for first card)
            priority = 1000
        elif todo:
            # Non-empty todo column: REQUIRE position specification
            # This forces users to think about relative importance (insertion sort mindset)
            print("Current todo:", file=sys.stderr)
            print(file=sys.stderr)
            for p, name, _ in todo:
                print(f"  [{p:4d}] {name}", file=sys.stderr)
            print(file=sys.stderr)
            print("Error: Position required. Use --top, --bottom, --after <card>, or --before <card>", file=sys.stderr)
            sys.exit(1)
        else:
            # Non-empty non-todo column: default to 0 (backward compatibility)
            priority = 0

    # STEP 3: Validate priority is non-negative before creating card
    priority = validate_priority(priority)

    num = next_number(root)
    slug = slugify(args.title)
    filename = f"{num}-{slug}.md"
    filepath = root / target_column / filename
    now = now_iso()

    # Content can come from --content flag or stdin (if --content is "-")
    if args.content == "-":
        body_content = sys.stdin.read().strip()
    elif args.content:
        body_content = args.content
    else:
        body_content = ""

    # Build frontmatter fields
    frontmatter_lines = [
        f"persona: {args.persona or 'unassigned'}",
        f"priority: {priority}",
    ]

    # Determine session: explicit > auto-detect > none (if --no-session)
    if hasattr(args, 'no_session') and args.no_session:
        pass  # Explicitly sessionless - don't add session field
    elif args.session:
        frontmatter_lines.append(f"session: {args.session}")
    else:
        # Auto-detect current session
        current_session = get_current_session_id()
        if current_session:
            frontmatter_lines.append(f"session: {current_session}")

    if args.model:
        frontmatter_lines.append(f"model: {args.model}")
    frontmatter_lines.extend([
        f"created: {now}",
        f"updated: {now}",
    ])

    content = f"""---
{chr(10).join(frontmatter_lines)}
---

# {args.title}

{body_content}
"""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content)
    print(f"Created: {target_column}/{filename} (priority: {priority})")


def cmd_delete(args) -> None:
    """Delete a card."""
    root = get_root(args.root)
    card_path = find_card(root, args.card)
    col = card_path.parent.name
    card_path.unlink()
    print(f"Deleted: {col}/{card_path.name}")


def cmd_move(args) -> None:
    """Move card to a different column."""
    root = get_root(args.root)

    if args.column not in COLUMNS:
        print(f"Error: Invalid column '{args.column}'. Must be one of: {', '.join(COLUMNS)}", file=sys.stderr)
        sys.exit(1)

    card_path = find_card(root, args.card)
    target_path = root / args.column / card_path.name

    # Ensure target directory exists
    target_path.parent.mkdir(parents=True, exist_ok=True)

    update_card(card_path, {})  # Just updates timestamp
    card_path.rename(target_path)
    print(f"Moved: {card_path.name} -> {args.column}/")


def cmd_up(args) -> None:
    """Move card up in priority."""
    root = get_root(args.root)
    card_path = find_card(root, args.card)
    current = get_priority(card_path)
    new_priority = max(0, current - 10)  # Ensure non-negative
    new_priority = validate_priority(new_priority)
    update_card(card_path, {"priority": new_priority})
    print(f"Moved up: {card_path.name} (priority: {new_priority})")


def cmd_down(args) -> None:
    """Move card down in priority."""
    root = get_root(args.root)
    card_path = find_card(root, args.card)
    current = get_priority(card_path)
    new_priority = current + 10
    new_priority = validate_priority(new_priority)
    update_card(card_path, {"priority": new_priority})
    print(f"Moved down: {card_path.name} (priority: {new_priority})")


def cmd_top(args) -> None:
    """Move card to top of column."""
    root = get_root(args.root)
    card_path = find_card(root, args.card)
    col = card_path.parent

    min_priority = 0
    for other in col.glob("*.md"):
        if other != card_path:
            min_priority = min(min_priority, get_priority(other))

    new_priority = max(0, min_priority - 10)  # Ensure non-negative
    new_priority = validate_priority(new_priority)
    update_card(card_path, {"priority": new_priority})
    print(f"Moved to top: {card_path.name} (priority: {new_priority})")


def cmd_bottom(args) -> None:
    """Move card to bottom of column."""
    root = get_root(args.root)
    card_path = find_card(root, args.card)
    col = card_path.parent

    max_priority = 0
    for other in col.glob("*.md"):
        if other != card_path:
            max_priority = max(max_priority, get_priority(other))

    new_priority = max_priority + 10
    new_priority = validate_priority(new_priority)
    update_card(card_path, {"priority": new_priority})
    print(f"Moved to bottom: {card_path.name} (priority: {new_priority})")


def cmd_comment(args) -> None:
    """Add a comment to a card."""
    root = get_root(args.root)
    card_path = find_card(root, args.card)

    content = card_path.read_text()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    # Append comment to end of file
    comment_line = f"\n- [{now}] {args.message}"

    # Check if there's already a comments section
    if "\n## Activity\n" not in content:
        content += "\n\n## Activity\n"

    content += comment_line
    card_path.write_text(content)

    # Update timestamp
    update_card(card_path, {})

    print(f"Added comment to: {card_path.name}")


def cmd_history(args) -> None:
    """Show completed cards with optional date and session filtering."""
    root = get_root(args.root)
    done_cards = find_cards_in_column(root, "done")

    # Include canceled cards if --include-canceled flag is set
    include_canceled = getattr(args, 'include_canceled', False)
    if include_canceled:
        canceled_cards = find_cards_in_column(root, "canceled")
        done_cards.extend(canceled_cards)

    # Include archived cards
    archive_base = root / "archive"
    if archive_base.exists():
        for archive_dir in archive_base.iterdir():
            if archive_dir.is_dir():
                done_cards.extend(archive_dir.glob("*.md"))

    # Get current session for filtering
    current_session = get_current_session_id()

    # Check environment variable for hiding own session by default
    hide_own_default = os.environ.get("KANBAN_HIDE_MINE", "").lower() in ["true", "1", "yes"]

    # Check flags
    show_only_mine = getattr(args, 'only_mine', False)  # Show ONLY mine (hide others)
    hide_mine_explicit = getattr(args, 'hide_mine', False)  # Hide mine explicitly
    show_mine_explicit = getattr(args, 'show_mine', False)  # Show mine explicitly (override env var)

    # Determine display behavior
    # Priority: --only-mine > --show-mine > --hide-mine > explicit --session > env var > default (show all)
    if hasattr(args, 'session') and args.session:
        # Explicit session filter - show only that session
        done_cards = [c for c in done_cards if get_session(c) == args.session]
    elif show_only_mine:
        # Show only current session's cards (and sessionless)
        if current_session:
            done_cards = [c for c in done_cards if get_session(c) in (current_session, None)]
    elif hide_mine_explicit or (hide_own_default and not show_mine_explicit):
        # Hide current session's cards (show only other sessions)
        if current_session:
            done_cards = [c for c in done_cards if get_session(c) not in (current_session, None)]
    # Default: show all sessions (history is reference material)

    if not done_cards:
        print("No completed cards")
        return

    # Parse date filters
    since = None
    until = None

    if args.since:
        if args.since == "today":
            # Midnight in local time, converted to UTC
            local_midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            since = local_midnight.astimezone(timezone.utc)
        elif args.since == "yesterday":
            # Midnight yesterday in local time, converted to UTC
            local_midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
            since = local_midnight.astimezone(timezone.utc)
        elif args.since == "week":
            since = datetime.now(timezone.utc) - timedelta(days=7)
        elif args.since == "month":
            since = datetime.now(timezone.utc) - timedelta(days=30)
        else:
            try:
                since = parse_iso(args.since)
            except ValueError:
                print(f"Error: Invalid date format '{args.since}'", file=sys.stderr)
                sys.exit(1)

    if args.until:
        try:
            until = parse_iso(args.until)
        except ValueError:
            print(f"Error: Invalid date format '{args.until}'", file=sys.stderr)
            sys.exit(1)

    print("## Completed Cards")
    print()

    count = 0
    for card in done_cards:
        content = card.read_text()
        frontmatter, _ = parse_frontmatter(content)
        updated_str = frontmatter.get("updated", "")
        persona = frontmatter.get("persona", "")
        session = frontmatter.get("session", "")

        # Filter by date
        if updated_str and (since or until):
            try:
                updated = parse_iso(updated_str)
                if since and updated < since:
                    continue
                if until and updated > until:
                    continue
            except ValueError:
                pass

        count += 1
        name = card.stem
        model = frontmatter.get("model")

        # Show archive location if archived
        location = ""
        if card.parent.name != "done" and card.parent.name != "canceled":
            location = f" [archived: {card.parent.name}]"

        display = f"  - {name}"
        if persona and persona != "unassigned":
            display += f" ({persona})"
        if model:
            display += f" [model: {model}]"
        if session:
            display += f" [{session[:8]}]"
        display += f" - {updated_str[:10] if updated_str else 'unknown'}"
        display += location
        print(display)

    print()
    print(f"Total: {count} cards")


def cmd_list(args) -> None:
    """Show board overview with grouped session display."""
    root = get_root(args.root)

    print(f"KANBAN BOARD: {root}")
    print()

    # Parse date filters
    since = None
    until = None

    if hasattr(args, 'since') and args.since:
        if args.since == "today":
            # Midnight in local time, converted to UTC
            local_midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            since = local_midnight.astimezone(timezone.utc)
        elif args.since == "yesterday":
            # Midnight yesterday in local time, converted to UTC
            local_midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
            since = local_midnight.astimezone(timezone.utc)
        elif args.since == "week":
            since = datetime.now(timezone.utc) - timedelta(days=7)
        elif args.since == "month":
            since = datetime.now(timezone.utc) - timedelta(days=30)
        else:
            try:
                since = parse_iso(args.since)
            except ValueError:
                print(f"Error: Invalid date format '{args.since}'", file=sys.stderr)
                sys.exit(1)

    if hasattr(args, 'until') and args.until:
        try:
            until = parse_iso(args.until)
        except ValueError:
            print(f"Error: Invalid date format '{args.until}'", file=sys.stderr)
            sys.exit(1)

    # Filter columns based on --show-done, --show-canceled, and --show-all flags
    show_done = getattr(args, 'show_done', False)
    show_canceled = getattr(args, 'show_canceled', False)
    show_all = getattr(args, 'show_all', False)

    if show_all:
        # Show everything (done + canceled + active columns)
        columns_to_show = COLUMNS
    elif show_done and show_canceled:
        # Show done and canceled (all columns)
        columns_to_show = COLUMNS
    elif show_done:
        # Show done but not canceled
        columns_to_show = [c for c in COLUMNS if c != "canceled"]
    elif show_canceled:
        # Show canceled but not done
        columns_to_show = [c for c in COLUMNS if c != "done"]
    else:
        # Default: hide both done and canceled
        columns_to_show = [c for c in COLUMNS if c not in ["done", "canceled"]]

    # Check environment variable for hiding own session by default
    hide_own_default = os.environ.get("KANBAN_HIDE_MINE", "").lower() in ["true", "1", "yes"]

    # Check flags
    show_only_mine = getattr(args, 'only_mine', False)  # Show ONLY mine (hide others)
    hide_mine_explicit = getattr(args, 'hide_mine', False)  # Hide mine explicitly
    show_mine_explicit = getattr(args, 'show_mine', False)  # Show mine explicitly (override env var)

    # Determine display behavior
    # Priority: --only-mine > --show-mine > --hide-mine > env var > default (show both)
    if show_only_mine:
        hide_own_session = False  # Show only mine (hide others)
    elif show_mine_explicit:
        hide_own_session = False  # Explicitly show mine (overrides env var)
    elif hide_mine_explicit:
        hide_own_session = True  # Hide mine explicitly
    elif hide_own_default:
        hide_own_session = True  # Hide mine from env var
    else:
        hide_own_session = False  # Default: show both

    # Get current session for grouping
    current_session = get_current_session_id()

    # Explicit session override
    if hasattr(args, 'session') and args.session:
        # Show only specific session
        current_session = args.session
        show_only_mine = True
        hide_own_session = False

    # Group cards by session
    my_cards = {col: [] for col in columns_to_show}
    other_cards = {col: [] for col in columns_to_show}

    for col in columns_to_show:
        col_path = root / col
        if not col_path.exists():
            continue

        cards = list(col_path.glob("*.md"))
        cards.sort(key=get_priority)

        # Apply date filtering if specified
        if since or until:
            filtered_cards = []
            for card in cards:
                content = card.read_text()
                frontmatter, _ = parse_frontmatter(content)
                updated_str = frontmatter.get("updated", "")

                if updated_str:
                    try:
                        updated = parse_iso(updated_str)
                        if since and updated < since:
                            continue
                        if until and updated > until:
                            continue
                    except ValueError:
                        pass  # Skip cards with invalid dates

                filtered_cards.append(card)

            cards = filtered_cards

        for card in cards:
            card_session = get_session(card)
            # Determine ownership
            if current_session and (card_session == current_session or card_session is None):
                my_cards[col].append(card)
            elif not current_session:
                # No session detected - show all as "mine" for backwards compatibility
                my_cards[col].append(card)
            else:
                other_cards[col].append(card)

    # Display: Your Session section (unless explicitly hiding)
    if not hide_own_session:
        if current_session:
            print(f"=== Your Session ({current_session[:8]}) ===")
        else:
            print("=== Your Cards ===")
        print()

        for col in columns_to_show:
            cards = my_cards[col]
            print(f"{col.upper()} ({len(cards)})")

            if cards:
                for card in cards:
                    name = card.stem
                    content = card.read_text()
                    frontmatter, _ = parse_frontmatter(content)
                    persona = frontmatter.get("persona", "")
                    model = frontmatter.get("model")

                    # Format: #number: title (persona) [model]
                    display = f"  {name}"
                    if persona and persona != "unassigned":
                        display += f" ({persona})"
                    if model:
                        display += f" [model: {model}]"
                    print(display)
            else:
                print("  (empty)")
            print()

    # Display: Other Sessions section (if not --only-mine flag)
    if not show_only_mine and any(other_cards[col] for col in columns_to_show):
        print("=== Other Sessions ===")
        print()

        for col in columns_to_show:
            cards = other_cards[col]
            if cards:
                print(f"{col.upper()} ({len(cards)})")
                for card in cards:
                    name = card.stem
                    content = card.read_text()
                    frontmatter, _ = parse_frontmatter(content)
                    persona = frontmatter.get("persona", "")
                    session = frontmatter.get("session", "")
                    model = frontmatter.get("model")

                    # Format: #number: title (persona) [model] [session]
                    display = f"  {name}"
                    if persona and persona != "unassigned":
                        display += f" ({persona})"
                    if model:
                        display += f" [model: {model}]"
                    if session:
                        display += f" [session: {session[:8]}]"
                    print(display)
                print()


def cmd_show(args) -> None:
    """Display card contents."""
    root = get_root(args.root)
    card_path = find_card(root, args.card)

    output = f"=== {card_path.name} ===\n\n{card_path.read_text()}"

    # Pipe through bat with markdown highlighting and paging (no decorations)
    try:
        proc = subprocess.Popen(
            ["bat", "--language", "md", "--style", "plain"],
            stdin=subprocess.PIPE,
            text=True
        )
        proc.communicate(input=output)
    except (FileNotFoundError, BrokenPipeError):
        print(output)


def get_session(card_path: Path) -> str | None:
    """Get session ID from card frontmatter."""
    content = card_path.read_text()
    frontmatter, _ = parse_frontmatter(content)
    return frontmatter.get("session")


def get_encoded_project_path() -> str:
    """Get the encoded project path format Claude uses.

    Claude encodes paths by replacing '/' with '-' and '.' with '-'.
    Example: /Users/foo/.config/bar -> -Users-foo--config-bar
    """
    cwd = Path.cwd()
    return str(cwd).replace('/', '-').replace('.', '-')


def find_claude_pid() -> int | None:
    """Walk up the process tree to find the Claude Code process PID."""
    try:
        pid = os.getpid()
        for _ in range(10):
            result = subprocess.run(
                ['ps', '-o', 'ppid=,command=', '-p', str(pid)],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                break
            parts = result.stdout.strip().split(None, 1)
            if len(parts) < 2:
                break
            ppid_str, cmd = parts[0], parts[1].lower()
            if 'claude' in cmd and 'python' not in cmd:
                return int(ppid_str)
            pid = int(ppid_str)
            if pid <= 1:
                break
    except (ValueError, OSError):
        pass
    return None


def cmd_nonce(args) -> None:
    """Output session identifier for session detection.

    If KANBAN_SESSION env var is set (by smithers/burns), output that value.
    Otherwise, generate a unique nonce for the current Claude session.

    Run this command first in a new session. The output gets logged
    to the session file, allowing subsequent kanban commands to identify
    which session they belong to.
    """
    # If session is pre-set (smithers/burns), output that
    if session_id := os.environ.get('KANBAN_SESSION'):
        print(session_id)
        return

    # Otherwise generate a new nonce for Claude session
    import uuid
    import time

    # Nonce includes timestamp for recency detection
    nonce = f"KANBAN_NONCE_{uuid.uuid4().hex}_{int(time.time() * 1000)}"
    print(nonce)


def get_current_session_id() -> str | None:
    """Get session ID - env var > Claude nonce > username for terminal.

    Detection logic:
    1. Check KANBAN_SESSION env var (for smithers/burns persistent sessions)
    2. Check if running inside a Claude process (process tree)
    3. If inside Claude: search for KANBAN_NONCE to identify the session
    4. If NOT inside Claude (terminal): use username as session ID

    This ensures:
    - smithers/burns maintain persistent sessions across Ralph invocations
    - Concurrent Claude sessions are isolated (each must run 'kanban nonce')
    - Terminal usage gets username as session ID
    - A terminal won't accidentally pick up a Claude session's nonce

    Returns:
        Session ID string (persistent for smithers/burns, UUID for Claude, username for terminal)
    """
    # First: Check for explicit session ID from environment (smithers/burns)
    if session_id := os.environ.get('KANBAN_SESSION'):
        return session_id

    # Second: are we inside a Claude process?
    claude_pid = find_claude_pid()

    if claude_pid is None:
        # Not inside Claude - use username for terminal usage
        return os.environ.get('USER') or os.getlogin()

    # Inside Claude - search for existing KANBAN_NONCE in session files
    # User must run 'kanban nonce' first to establish session identity
    try:
        project_path = get_encoded_project_path()
        projects_dir = Path.home() / '.claude' / 'projects' / project_path

        if not projects_dir.exists():
            return None

        session_files = list(projects_dir.glob('*.jsonl'))
        if not session_files:
            return None

        # Search for ANY KANBAN_NONCE pattern across all session files
        # Pattern: KANBAN_NONCE_<uuid>_<timestamp>
        best_match = None  # (timestamp, session_file_stem)

        for session_file in session_files:
            result = subprocess.run(
                ['rg', '-o', r'KANBAN_NONCE_[a-f0-9]+_[0-9]+', str(session_file)],
                capture_output=True,
                text=True
            )

            if result.returncode == 0 and result.stdout.strip():
                # Found nonce(s) in this session file - get the most recent
                for line in result.stdout.strip().split('\n'):
                    # Extract timestamp from nonce (last part after final _)
                    parts = line.split('_')
                    if len(parts) >= 3:
                        try:
                            timestamp = int(parts[-1])
                            if best_match is None or timestamp > best_match[0]:
                                best_match = (timestamp, session_file.stem)
                        except ValueError:
                            continue

        if best_match:
            return best_match[1]

        # No nonce found - user needs to run 'kanban nonce' first
        return None

    except (OSError, ValueError, subprocess.SubprocessError) as e:
        print(f"Error detecting session: {e}", file=sys.stderr)
        return None


def cmd_view(args) -> None:
    """View cards in a column with two-tiered display: full details for your session, summaries for others."""
    root = get_root(args.root)
    column = args.column

    cards = find_cards_in_column(root, column)

    if not cards:
        print(f"No cards in {column}")
        return

    # Parse date filters
    since = None
    until = None

    if hasattr(args, 'since') and args.since:
        if args.since == "today":
            # Midnight in local time, converted to UTC
            local_midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            since = local_midnight.astimezone(timezone.utc)
        elif args.since == "yesterday":
            # Midnight yesterday in local time, converted to UTC
            local_midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
            since = local_midnight.astimezone(timezone.utc)
        elif args.since == "week":
            since = datetime.now(timezone.utc) - timedelta(days=7)
        elif args.since == "month":
            since = datetime.now(timezone.utc) - timedelta(days=30)
        else:
            try:
                since = parse_iso(args.since)
            except ValueError:
                print(f"Error: Invalid date format '{args.since}'", file=sys.stderr)
                sys.exit(1)

    if hasattr(args, 'until') and args.until:
        try:
            until = parse_iso(args.until)
        except ValueError:
            print(f"Error: Invalid date format '{args.until}'", file=sys.stderr)
            sys.exit(1)

    # Filter cards by date if filters are provided
    if since or until:
        filtered_cards = []
        for card in cards:
            content = card.read_text()
            frontmatter, _ = parse_frontmatter(content)
            updated_str = frontmatter.get("updated", "")

            if updated_str:
                try:
                    updated = parse_iso(updated_str)
                    if since and updated < since:
                        continue
                    if until and updated > until:
                        continue
                except ValueError:
                    pass  # Skip cards with invalid dates

            filtered_cards.append(card)

        cards = filtered_cards

        if not cards:
            print(f"No cards in {column} matching date filters")
            return

    # Get current session
    current_session = get_current_session_id()

    # Check environment variable for hiding own session by default
    hide_own_default = os.environ.get("KANBAN_HIDE_MINE", "").lower() in ["true", "1", "yes"]

    # Check flags
    show_only_mine = getattr(args, 'only_mine', False)  # Show ONLY mine (hide others)
    hide_mine_explicit = getattr(args, 'hide_mine', False)  # Hide mine explicitly
    show_mine_explicit = getattr(args, 'show_mine', False)  # Show mine explicitly (override env var)

    # Determine display behavior
    # Priority: --only-mine > --show-mine > --hide-mine > env var > default (show both)
    if show_only_mine:
        hide_own_session = False  # Show only mine (hide others)
    elif show_mine_explicit:
        hide_own_session = False  # Explicitly show mine (overrides env var)
    elif hide_mine_explicit:
        hide_own_session = True  # Hide mine explicitly
    elif hide_own_default:
        hide_own_session = True  # Hide mine from env var
    else:
        hide_own_session = False  # Default: show both

    # Explicit session override
    explicit_session_filter = hasattr(args, 'session') and args.session
    if explicit_session_filter:
        current_session = args.session
        show_only_mine = True
        hide_own_session = False

    # Group cards by ownership
    my_cards = []
    other_cards = []

    for card in cards:
        card_session = get_session(card)
        # When explicitly filtering by --session, match ONLY that session (no sessionless cards)
        # When viewing your own session, include sessionless cards too
        if explicit_session_filter:
            if card_session == current_session:
                my_cards.append(card)
            else:
                other_cards.append(card)
        elif current_session and (card_session == current_session or card_session is None):
            my_cards.append(card)
        elif not current_session:
            # No session detected - show all as "mine" for backwards compatibility
            my_cards.append(card)
        else:
            other_cards.append(card)

    # Display: Your Session - Full Details (unless explicitly hiding)
    if my_cards and not hide_own_session:
        if current_session:
            print("=== Your Session - Full Details ===")
        else:
            print("=== Your Cards - Full Details ===")
        print()
        sys.stdout.flush()  # Ensure header prints before bat output

        # Build output for your cards
        lines = []
        for i, card in enumerate(my_cards):
            if i > 0:
                lines.append("\n" + "=" * 60 + "\n")
            lines.append(f"Card {card.name}")
            lines.append("")
            lines.append(card.read_text())
        output = "\n".join(lines)

        # Pipe through bat with markdown highlighting
        try:
            proc = subprocess.Popen(
                ["bat", "--language", "md", "--style", "plain"],
                stdin=subprocess.PIPE,
                text=True
            )
            proc.communicate(input=output)
        except (FileNotFoundError, BrokenPipeError):
            print(output)

    # Display: Other Sessions - Abbreviated Content (for coordination)
    if other_cards and not show_only_mine:
        print()
        print("=== Other Sessions - Abbreviated Content ===")
        print()
        sys.stdout.flush()  # Ensure header prints before bat output

        # Build output for other sessions' cards
        lines = []
        for i, card in enumerate(other_cards):
            content = card.read_text()
            frontmatter, body = parse_frontmatter(content)
            persona = frontmatter.get("persona", "")
            session = frontmatter.get("session", "")
            model = frontmatter.get("model")

            # Extract actual body after frontmatter delimiters
            body_parts = body.split("---", 2)
            actual_body = body_parts[2].strip() if len(body_parts) >= 3 else body.strip()

            # Stop before Activity section (comments)
            if "\n## Activity\n" in actual_body:
                abbreviated = actual_body.split("\n## Activity\n")[0].strip()
            elif "\n## Activity" in actual_body:
                abbreviated = actual_body.split("\n## Activity")[0].strip()
            else:
                abbreviated = actual_body

            # Build header with metadata
            if i > 0:
                lines.append("\n" + "-" * 40 + "\n")
            header = f"**{card.stem}**"
            if persona and persona != "unassigned":
                header += f" ({persona})"
            if model:
                header += f" [model: {model}]"
            if session:
                header += f" [session: {session[:8]}]"
            lines.append(header)
            lines.append("")
            lines.append(abbreviated)

        output = "\n".join(lines)

        # Pipe through bat with markdown highlighting
        try:
            proc = subprocess.Popen(
                ["bat", "--language", "md", "--style", "plain"],
                stdin=subprocess.PIPE,
                text=True
            )
            proc.communicate(input=output)
        except (FileNotFoundError, BrokenPipeError):
            print(output)


def cmd_edit(args) -> None:
    """Edit an existing card's content or metadata."""
    root = get_root(args.root)
    card_path = find_card(root, args.card)

    content = card_path.read_text()
    frontmatter, body = parse_frontmatter(content)

    # Update persona if provided
    if args.persona:
        frontmatter["persona"] = args.persona

    # Handle content update
    if args.content is not None:
        # Get new content from stdin or argument
        if args.content == "-":
            new_content = sys.stdin.read().strip()
        else:
            new_content = args.content

        # Extract the actual body content (after frontmatter)
        # body from parse_frontmatter starts with ---
        parts = body.split("---", 2)
        actual_body = parts[2] if len(parts) >= 3 else ""

        # Extract title from body (first # heading)
        title_match = re.search(r"^# (.+)$", actual_body, re.MULTILINE)
        title = title_match.group(1) if title_match else card_path.stem

        if args.append:
            # Append to existing body content
            body = actual_body.rstrip() + "\n\n" + new_content + "\n"
        else:
            # Replace body content (keep title)
            body = f"\n# {title}\n\n{new_content}\n"

    # Update timestamp
    frontmatter["updated"] = now_iso()

    card_path.write_text(serialize_frontmatter(frontmatter, body))
    print(f"Updated: {card_path.parent.name}/{card_path.name}")


def cmd_assign(args) -> None:
    """Change or remove session ownership from cards."""
    root = get_root(args.root)

    # Validate mutually exclusive flags
    if args.no_session and args.session:
        print("Error: Cannot specify both --session and --no-session", file=sys.stderr)
        sys.exit(1)

    # Bulk reassignment mode
    if args.from_session:
        if not args.to_session and not args.no_session:
            print("Error: Bulk reassignment requires --to <session> or --no-session", file=sys.stderr)
            sys.exit(1)

        # Find all cards with the source session
        all_cards = find_all_cards(root)
        cards_to_reassign = [c for c in all_cards if get_session(c) == args.from_session]

        if not cards_to_reassign:
            print(f"No cards found with session '{args.from_session}'")
            return

        # Confirm bulk operation
        if not args.yes:
            target = "no session (sessionless)" if args.no_session else f"session '{args.to_session}'"
            response = input(f"Reassign {len(cards_to_reassign)} card(s) from '{args.from_session}' to {target}? [y/N] ")
            if response.lower() != "y":
                print("Aborted")
                return

        # Perform bulk reassignment
        for card_path in cards_to_reassign:
            content = card_path.read_text()
            frontmatter, body = parse_frontmatter(content)

            if args.no_session:
                # Remove session field
                if "session" in frontmatter:
                    del frontmatter["session"]
            else:
                # Assign to new session
                frontmatter["session"] = args.to_session

            frontmatter["updated"] = now_iso()
            card_path.write_text(serialize_frontmatter(frontmatter, body))

        target = "sessionless" if args.no_session else args.to_session
        print(f"Reassigned {len(cards_to_reassign)} card(s) from '{args.from_session}' to {target}")
        return

    # Single card reassignment mode
    if not args.card:
        print("Error: Card number/name required (or use --from for bulk reassignment)", file=sys.stderr)
        sys.exit(1)

    card_path = find_card(root, args.card)
    content = card_path.read_text()
    frontmatter, body = parse_frontmatter(content)

    old_session = frontmatter.get("session")

    if args.no_session:
        # Remove session field
        if "session" in frontmatter:
            del frontmatter["session"]
            new_session = "sessionless"
        else:
            print(f"Card {card_path.name} is already sessionless")
            return
    elif args.session:
        # Assign to specific session
        frontmatter["session"] = args.session
        new_session = args.session
    else:
        # Assign to auto-detected current session
        current_session = get_current_session_id()
        if not current_session:
            print("Error: Could not auto-detect current session. Use --session <id> or --no-session", file=sys.stderr)
            sys.exit(1)
        frontmatter["session"] = current_session
        new_session = current_session

    frontmatter["updated"] = now_iso()
    card_path.write_text(serialize_frontmatter(frontmatter, body))

    # Format output message
    old_label = old_session if old_session else "sessionless"
    new_label = new_session if new_session != "sessionless" else "sessionless"
    print(f"Reassigned {card_path.name}: {old_label} -> {new_label}")


def cmd_clear(args) -> None:
    """Delete all cards from specified columns (or all columns if none specified)."""
    root = get_root(args.root)

    # Determine which columns to clear
    if args.columns:
        # Validate column names
        invalid_columns = [col for col in args.columns if col not in COLUMNS]
        if invalid_columns:
            print(f"Error: Invalid column(s): {', '.join(invalid_columns)}", file=sys.stderr)
            print(f"Valid columns: {', '.join(COLUMNS)}", file=sys.stderr)
            sys.exit(1)
        columns_to_clear = args.columns
    else:
        # Default: clear all columns
        columns_to_clear = COLUMNS

    # Count cards in target columns
    count = 0
    for col in columns_to_clear:
        col_path = root / col
        if col_path.exists():
            count += len(list(col_path.glob("*.md")))

    if count == 0:
        if args.columns:
            print(f"No cards to clear in: {', '.join(columns_to_clear)}")
        else:
            print("No cards to clear")
        return

    # Confirm unless --yes flag is passed
    if not args.yes:
        if args.columns:
            response = input(f"Delete {count} card(s) from {', '.join(columns_to_clear)}? [y/N] ")
        else:
            response = input(f"Delete all {count} cards from kanban board? [y/N] ")
        if response.lower() != "y":
            print("Aborted")
            return

    # Now delete
    deleted = 0
    for col in columns_to_clear:
        col_path = root / col
        if col_path.exists():
            for card in col_path.glob("*.md"):
                card.unlink()
                deleted += 1

    if args.columns:
        print(f"Cleared {deleted} card(s) from {', '.join(columns_to_clear)}")
    else:
        print(f"Cleared {deleted} cards from kanban board")


def watch_and_run(args, command_func) -> None:
    """Watch .kanban/ directory and re-run command on changes.

    Features:
    - Monitors .kanban/ directory for file changes (create, modify, delete)
    - Debounces rapid changes (max 1 refresh per second)
    - Clear screen and re-execute command on changes
    - Clean Ctrl+C exit

    Args:
        args: Parsed command-line arguments
        command_func: Command function to execute (e.g., cmd_list)
    """
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        print("Error: watchdog library not available. Install with: pip install watchdog", file=sys.stderr)
        sys.exit(1)

    root = get_root(args.root)

    # Event to signal when a refresh is needed
    refresh_event = Event()
    last_refresh = [time.time()]  # Use list for mutable reference in closure

    class DebounceHandler(FileSystemEventHandler):
        """Handler that debounces file system events."""

        def on_any_event(self, event):
            # Ignore directory events and non-.md files
            if event.is_directory:
                return
            if not event.src_path.endswith('.md'):
                return

            # Debounce: only trigger if more than 1 second since last refresh
            now = time.time()
            if now - last_refresh[0] >= 1.0:
                last_refresh[0] = now
                refresh_event.set()

    # Set up observer
    observer = Observer()
    handler = DebounceHandler()
    observer.schedule(handler, str(root), recursive=True)
    observer.start()

    print(f"Watching {root} for changes... (Press Ctrl+C to exit)")
    print()

    try:
        # Initial run
        command_func(args)

        # Watch loop
        while True:
            # Wait for refresh event or timeout
            if refresh_event.wait(timeout=0.5):
                # Clear screen using ANSI escape sequences (more reliable than os.system)
                print('\033[2J\033[H', end='', flush=True)

                # Re-run command
                try:
                    command_func(args)
                except Exception as e:
                    print(f"Error running command: {e}", file=sys.stderr)

                # Reset event
                refresh_event.clear()

    except KeyboardInterrupt:
        print("\nStopping watch mode...")
    finally:
        observer.stop()
        observer.join()


def main() -> None:
    # Parent parser for subcommands to inherit --watch flag
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument("--watch", action="store_true", help="Auto-refresh output when .kanban/ files change")

    parser = argparse.ArgumentParser(
        description="Kanban CLI - File-based kanban board for agent coordination",
        epilog="""
INSERTION SORT WORKFLOW:
  Think like insertion sort when adding cards - consider where they belong in priority order.

  1. Run 'kanban list' to see existing cards and their priorities
  2. Determine where new card fits relative to others (more/less important?)
  3. Use position flags (--top, --bottom, --after, --before) to place correctly
  4. System maintains sorted order using priority numbers (lower = higher priority)

PRIORITY SYSTEM:
  - Empty column: First card defaults to priority 1000
  - Non-empty column: Position flags required for todo (helps maintain order)
  - Spacing: Uses increments of 5-10 to allow future insertions
  - Minimum: Priority must be >= 0 (no negative numbers)

PICKING NEXT WORK:
  1. Run 'kanban list' to see full board
  2. Filter to your session if in multi-agent scenario
  3. Work cards in priority order (lowest number first)

WATCH MODE:
  Add --watch to any command to auto-refresh on file changes
  Example: kanban list --watch  OR  kanban --watch list

ENVIRONMENT VARIABLES:
  KANBAN_ROOT          Override board location (default: auto-detect from git root or cwd)
  KANBAN_SESSION       Override session ID (used by smithers/burns for persistent tracking)
  KANBAN_HIDE_MINE     Hide own session's cards by default (set to 'true', '1', or 'yes')
  KANBAN_ARCHIVE_DAYS  Days before archiving done/canceled cards (default: 30)

SESSIONS:
  Sessions track which Claude instance owns a card. This enables multi-agent coordination
  by allowing different Claude sessions to work on the same board without interfering.
  Use --session flags to filter or assign cards to specific sessions.
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--root", help="Kanban root directory (or set KANBAN_ROOT)")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # init
    p_init = subparsers.add_parser("init", parents=[parent_parser], help="Create kanban board structure")
    p_init.add_argument("path", nargs="?", default=None, help="Board path (default: auto-computed from cwd)")

    # add (with position requirement)
    p_add = subparsers.add_parser(
        "add",
        parents=[parent_parser],
        help="Add card using insertion sort pattern (position required for non-empty columns)",
        description="""
Add a new card to the kanban board using insertion sort workflow.

For non-empty todo columns, you MUST specify position (--top, --bottom, --after, --before).
This enforces the insertion sort mindset: think about where the card belongs in priority order.

Empty columns default to priority 1000 (baseline for first card).
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p_add.add_argument("title", help="Card title")
    p_add.add_argument("--persona", help="Persona for the card (default: unassigned)")
    p_add.add_argument("--content", "-c", help="Card body content (e.g., task description)")
    p_add.add_argument("--status", choices=COLUMNS, default="todo", help="Starting column (default: todo)")
    p_add.add_argument("--session", help="Session ID for the card (auto-detected if not specified)")
    p_add.add_argument("--no-session", action="store_true", help="Create card without session (visible to all)")
    p_add.add_argument("--model", choices=["sonnet", "opus", "haiku"], help="AI model used for this card (sonnet, opus, haiku)")
    p_add.add_argument("--top", action="store_true", help="Insert at top (highest priority, lowest number)")
    p_add.add_argument("--bottom", action="store_true", help="Insert at bottom (lowest priority, highest number)")
    p_add.add_argument("--after", help="Insert after specified card (by number or name)")
    p_add.add_argument("--before", help="Insert before specified card (by number or name)")

    # delete
    p_delete = subparsers.add_parser("delete", parents=[parent_parser], help="Delete a card (WARNING: Permanently deletes card)")
    p_delete.add_argument("card", help="Card number (e.g., 23) or filename pattern")

    # edit
    p_edit = subparsers.add_parser("edit", parents=[parent_parser], help="Edit a card's content or metadata")
    p_edit.add_argument("card", help="Card number (e.g., 23) or filename pattern")
    p_edit.add_argument("--content", "-c", help="New card body content (use '-' for stdin)")
    p_edit.add_argument("--persona", help="Update persona")
    p_edit.add_argument("--append", "-a", action="store_true", help="Append to content instead of replacing")

    # move
    p_move = subparsers.add_parser("move", parents=[parent_parser], help="Move card to column")
    p_move.add_argument("card", help="Card number (e.g., 23) or filename pattern")
    p_move.add_argument("column", help="Target column (valid: todo, doing, blocked, done, canceled)")

    # up
    p_up = subparsers.add_parser("up", parents=[parent_parser], help="Move card up in priority (decreases priority by 10)")
    p_up.add_argument("card", help="Card number (e.g., 23) or filename pattern")

    # down
    p_down = subparsers.add_parser("down", parents=[parent_parser], help="Move card down in priority (increases priority by 10)")
    p_down.add_argument("card", help="Card number (e.g., 23) or filename pattern")

    # top
    p_top = subparsers.add_parser("top", parents=[parent_parser], help="Move card to top of column (highest priority, lowest number)")
    p_top.add_argument("card", help="Card number (e.g., 23) or filename pattern")

    # bottom
    p_bottom = subparsers.add_parser("bottom", parents=[parent_parser], help="Move card to bottom of column (lowest priority, highest number)")
    p_bottom.add_argument("card", help="Card number (e.g., 23) or filename pattern")

    # comment
    p_comment = subparsers.add_parser("comment", parents=[parent_parser], help="Add comment to card")
    p_comment.add_argument("card", help="Card number (e.g., 23) or filename pattern")
    p_comment.add_argument("message", help="Comment message")

    # history
    p_history = subparsers.add_parser("history", parents=[parent_parser], help="Show completed cards")
    p_history.add_argument("--since", help="Filter by date (today, yesterday, week, month, or ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ). Default: all time")
    p_history.add_argument("--until", help="Filter until date (ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ)")
    p_history.add_argument("--include-canceled", action="store_true", help="Include canceled cards in history")
    p_history.add_argument("--session", help="Filter by session ID (sessions track which Claude instance owns a card)")
    p_history.add_argument("--only-mine", action="store_true", dest="only_mine", help="Show only current session's cards")
    p_history.add_argument("--show-mine", action="store_true", dest="show_mine", help="Show current session's cards (overrides KANBAN_HIDE_MINE env var)")
    p_history.add_argument("--hide-mine", action="store_true", dest="hide_mine", help="Hide current session's cards (show only other sessions). Can also set KANBAN_HIDE_MINE=true")

    # list (with ls alias)
    p_list = subparsers.add_parser("list", parents=[parent_parser], help="Show board overview (default: shows todo, doing, blocked columns; hides done, canceled)")
    p_list.add_argument("--show-done", action="store_true", help="Include done column in output")
    p_list.add_argument("--show-canceled", action="store_true", help="Include canceled column in output")
    p_list.add_argument("--show-all", action="store_true", help="Include both done and canceled columns in output")
    p_list.add_argument("--session", help="Filter by session ID (sessions track which Claude instance owns a card)")
    p_list.add_argument("--only-mine", action="store_true", dest="only_mine", help="Show only current session's cards")
    p_list.add_argument("--show-mine", action="store_true", dest="show_mine", help="Show current session's cards (overrides KANBAN_HIDE_MINE env var)")
    p_list.add_argument("--hide-mine", action="store_true", dest="hide_mine", help="Hide current session's cards (show only other sessions). Can also set KANBAN_HIDE_MINE=true")
    p_list.add_argument("--since", help="Filter by date (today, yesterday, week, month, or ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ)")
    p_list.add_argument("--until", help="Filter until date (ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ)")
    p_ls = subparsers.add_parser("ls", parents=[parent_parser], help="Show board overview (alias for list)")
    p_ls.add_argument("--show-done", action="store_true", help="Include done column in output")
    p_ls.add_argument("--show-canceled", action="store_true", help="Include canceled column in output")
    p_ls.add_argument("--show-all", action="store_true", help="Include both done and canceled columns in output")
    p_ls.add_argument("--session", help="Filter by session ID (sessions track which Claude instance owns a card)")
    p_ls.add_argument("--only-mine", action="store_true", dest="only_mine", help="Show only current session's cards")
    p_ls.add_argument("--show-mine", action="store_true", dest="show_mine", help="Show current session's cards (overrides KANBAN_HIDE_MINE env var)")
    p_ls.add_argument("--hide-mine", action="store_true", dest="hide_mine", help="Hide current session's cards (show only other sessions). Can also set KANBAN_HIDE_MINE=true")
    p_ls.add_argument("--since", help="Filter by date (today, yesterday, week, month, or ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ)")
    p_ls.add_argument("--until", help="Filter until date (ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ)")

    # show
    p_show = subparsers.add_parser("show", parents=[parent_parser], help="Display card contents")
    p_show.add_argument("card", help="Card number (e.g., 23) or filename pattern")

    # Column view commands (kanban <column>)
    for col in COLUMNS:
        p_col = subparsers.add_parser(col, parents=[parent_parser], help=f"View cards in {col} (default: all sessions, full details for yours)")
        p_col.add_argument("--session", help="Filter by session ID (sessions track which Claude instance owns a card)")
        p_col.add_argument("--only-mine", action="store_true", dest="only_mine", help="Show only current session's cards")
        p_col.add_argument("--show-mine", action="store_true", dest="show_mine", help="Show current session's cards (overrides KANBAN_HIDE_MINE env var)")
        p_col.add_argument("--hide-mine", action="store_true", dest="hide_mine", help="Hide current session's cards (show only other sessions). Can also set KANBAN_HIDE_MINE=true")
        p_col.add_argument("--since", help="Filter by date (today, yesterday, week, month, or ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ)")
        p_col.add_argument("--until", help="Filter until date (ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ)")
        p_col.set_defaults(column=col)

    # nonce - for session detection
    p_nonce = subparsers.add_parser(
        "nonce",
        parents=[parent_parser],
        help="Output a unique nonce for session detection (run first in new Claude sessions)"
    )

    # assign
    p_assign = subparsers.add_parser(
        "assign",
        parents=[parent_parser],
        help="Change or remove session ownership from cards",
        description="""
Reassign cards to different sessions or make them sessionless.

SINGLE CARD MODES:
  kanban assign <card#>                    # Assign to auto-detected current session
  kanban assign <card#> --session <id>     # Assign to specific session
  kanban assign <card#> --no-session       # Remove session (make sessionless)

BULK REASSIGNMENT:
  kanban assign --from <old> --to <new>    # Reassign all cards from old to new session
  kanban assign --from <old> --no-session  # Make all cards from old session sessionless
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p_assign.add_argument("card", nargs="?", help="Card number or name (required for single card mode)")
    p_assign.add_argument("--session", help="Assign to specific session ID")
    p_assign.add_argument("--no-session", action="store_true", help="Remove session (make sessionless)")
    p_assign.add_argument("--from", dest="from_session", help="Bulk reassignment: source session ID")
    p_assign.add_argument("--to", dest="to_session", help="Bulk reassignment: target session ID")
    p_assign.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt (bulk operations)")

    # clear
    p_clear = subparsers.add_parser("clear", parents=[parent_parser], help="Delete all cards from all columns (or specific columns if provided)")
    p_clear.add_argument("columns", nargs="*", help=f"Column(s) to clear ({', '.join(COLUMNS)}). If omitted, clears all columns.")
    p_clear.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {
        "init": cmd_init,
        "add": cmd_add,
        "delete": cmd_delete,
        "edit": cmd_edit,
        "move": cmd_move,
        "up": cmd_up,
        "down": cmd_down,
        "top": cmd_top,
        "bottom": cmd_bottom,
        "comment": cmd_comment,
        "history": cmd_history,
        "list": cmd_list,
        "ls": cmd_list,
        "show": cmd_show,
        "todo": cmd_view,
        "doing": cmd_view,
        "blocked": cmd_view,
        "done": cmd_view,
        "canceled": cmd_view,
        "assign": cmd_assign,
        "clear": cmd_clear,
        "nonce": cmd_nonce,
    }

    command_func = commands[args.command]

    # Execute in watch mode if --watch flag is set
    if getattr(args, 'watch', False):
        watch_and_run(args, command_func)
    else:
        command_func(args)


if __name__ == "__main__":
    main()
