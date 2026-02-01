"""
Kanban CLI - File-based kanban board for agent coordination.

Cards are markdown files with YAML frontmatter, stored in column folders.
Priority field controls ordering within columns (lower = higher in list).
"""

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

COLUMNS = ["todo", "doing", "waiting", "done"]
WORK_COLUMNS = ["waiting", "doing", "todo"]  # Priority order for next command


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


def get_root(args_root: str | None, auto_init: bool = True) -> Path:
    """Get kanban root directory from args, environment, or auto-compute.

    Priority:
    1. Explicit --root argument
    2. KANBAN_ROOT environment variable
    3. Git root + .kanban/ (if in a git repo)
    4. Current directory + .kanban/ (fallback)
    """
    if args_root:
        return Path(args_root)
    if root := os.environ.get("KANBAN_ROOT"):
        return Path(root)

    # Use git root if available, otherwise current directory
    base_dir = get_git_root() or Path.cwd()
    root = base_dir / ".kanban"

    # Auto-initialize if needed
    if auto_init and not root.exists():
        for col in COLUMNS:
            (root / col).mkdir(parents=True, exist_ok=True)

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


def find_all_cards(root: Path) -> list[Path]:
    """Find all card files across all columns."""
    cards = []
    for col in COLUMNS:
        col_path = root / col
        if col_path.exists():
            cards.extend(col_path.glob("*.md"))
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
    return f"{max_num + 1:03d}"


def find_card(root: Path, pattern: str) -> Path:
    """Find a card by number or name pattern."""
    # Normalize number patterns
    if pattern.isdigit():
        pattern = f"{int(pattern):03d}"

    matches = []
    for card in find_all_cards(root):
        if card.name.startswith(pattern) or pattern in card.name:
            matches.append(card)

    if not matches:
        print(f"Error: No card found matching '{pattern}'", file=sys.stderr)
        sys.exit(1)

    if len(matches) > 1:
        print(f"Error: Multiple cards match '{pattern}'. Be more specific.", file=sys.stderr)
        sys.exit(1)

    return matches[0]


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

    print(f"Kanban board ready at: {path}")


def cmd_add(args) -> None:
    """Add a new card with insertion sort."""
    root = get_root(args.root)
    target_column = args.status

    # Show current column if no position specified
    todo = get_todo_context(root) if target_column == "todo" else []

    # Determine priority based on position args
    if args.top:
        # Insert at top (lowest priority number)
        min_priority = min((p for p, _, _ in todo), default=0)
        priority = min_priority - 10
    elif args.bottom:
        # Insert at bottom (highest priority number)
        max_priority = max((p for p, _, _ in todo), default=0)
        priority = max_priority + 10
    elif args.after:
        # Insert after specified card
        ref_card = find_card(root, args.after)
        ref_priority = get_priority(ref_card)
        priority = ref_priority + 5
    elif args.before:
        # Insert before specified card
        ref_card = find_card(root, args.before)
        ref_priority = get_priority(ref_card)
        priority = ref_priority - 5
    else:
        # No position specified - show todo and require position
        if todo:
            print("Current todo:", file=sys.stderr)
            print(file=sys.stderr)
            for p, name, _ in todo:
                print(f"  [{p:4d}] {name}", file=sys.stderr)
            print(file=sys.stderr)
            print("Error: Position required. Use --top, --bottom, --after <card>, or --before <card>", file=sys.stderr)
            sys.exit(1)
        else:
            # Empty todo, just use 0
            priority = 0

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
    content = f"""---
persona: {args.persona or 'unassigned'}
priority: {priority}
created: {now}
updated: {now}
---

# {args.title}

{body_content}
"""
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

    update_card(card_path, {})  # Just updates timestamp
    card_path.rename(target_path)
    print(f"Moved: {card_path.name} -> {args.column}/")


def cmd_up(args) -> None:
    """Move card up in priority."""
    root = get_root(args.root)
    card_path = find_card(root, args.card)
    current = get_priority(card_path)
    new_priority = current - 10
    update_card(card_path, {"priority": new_priority})
    print(f"Moved up: {card_path.name} (priority: {new_priority})")


def cmd_down(args) -> None:
    """Move card down in priority."""
    root = get_root(args.root)
    card_path = find_card(root, args.card)
    current = get_priority(card_path)
    new_priority = current + 10
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

    new_priority = min_priority - 10
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
    update_card(card_path, {"priority": new_priority})
    print(f"Moved to bottom: {card_path.name} (priority: {new_priority})")


def cmd_next(args) -> None:
    """Get the next card to work on (right-to-left priority, skip done)."""
    root = get_root(args.root)
    persona_filter = args.persona
    skip = args.skip or 0

    # Search columns right-to-left: waiting -> in-progress -> backlog
    found_cards = []
    for col in WORK_COLUMNS:
        cards = find_cards_in_column(root, col)
        for card in cards:
            if persona_filter:
                if get_persona(card) == persona_filter:
                    found_cards.append((col, card))
            else:
                found_cards.append((col, card))

    if not found_cards:
        if persona_filter:
            print(f"No cards found for persona '{persona_filter}'")
        else:
            print("No cards to work on")
        sys.exit(0)

    if skip >= len(found_cards):
        print(f"No more cards (skip={skip}, found={len(found_cards)})")
        sys.exit(0)

    col, card = found_cards[skip]
    print(f"=== NEXT CARD ({col}) ===")
    print(f"Card: {card.name}")
    print()
    print(card.read_text())


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
    """Show completed cards with optional date filtering."""
    root = get_root(args.root)
    done_cards = find_cards_in_column(root, "done")

    if not done_cards:
        print("No completed cards")
        return

    # Parse date filters
    since = None
    until = None

    if args.since:
        if args.since == "today":
            since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        elif args.since == "yesterday":
            since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
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
        if persona and persona != "unassigned":
            print(f"  - {name} ({persona}) - {updated_str[:10] if updated_str else 'unknown'}")
        else:
            print(f"  - {name} - {updated_str[:10] if updated_str else 'unknown'}")

    print()
    print(f"Total: {count} cards")


def cmd_list(args) -> None:
    """Show board overview."""
    root = get_root(args.root)

    print(f"KANBAN BOARD: {root}")
    print()

    for col in COLUMNS:
        print(f"## {col}")
        col_path = root / col

        if col_path.exists():
            cards = list(col_path.glob("*.md"))
            # Sort by priority
            cards.sort(key=get_priority)

            if cards:
                for card in cards:
                    name = card.stem
                    content = card.read_text()
                    frontmatter, _ = parse_frontmatter(content)
                    persona = frontmatter.get("persona", "")

                    if persona and persona != "unassigned":
                        print(f"  - {name} ({persona})")
                    else:
                        print(f"  - {name}")
            else:
                print("  (empty)")
        else:
            print("  (empty)")
        print()


def cmd_show(args) -> None:
    """Display card contents."""
    root = get_root(args.root)
    card_path = find_card(root, args.card)

    print(f"=== {card_path.name} ===")
    print()
    print(card_path.read_text())


def cmd_view(args) -> None:
    """View cards in a column with bat markdown highlighting."""
    root = get_root(args.root)
    column = args.column

    cards = find_cards_in_column(root, column)

    if not cards:
        print(f"No cards in {column}")
        return

    # Build output
    lines = []
    for i, card in enumerate(cards):
        if i > 0:
            lines.append("\n" + "=" * 60 + "\n")
        lines.append(f"=== {card.name} ===")
        lines.append("")
        lines.append(card.read_text())
    output = "\n".join(lines)

    # Pipe through bat with markdown highlighting, no line numbers
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


def cmd_clear(args) -> None:
    """Delete all cards from all columns."""
    root = get_root(args.root)

    # Count cards first
    count = 0
    for col in COLUMNS:
        col_path = root / col
        if col_path.exists():
            count += len(list(col_path.glob("*.md")))

    if count == 0:
        print("No cards to clear")
        return

    # Confirm unless --yes flag is passed
    if not args.yes:
        response = input(f"Delete all {count} cards from kanban board? [y/N] ")
        if response.lower() != "y":
            print("Aborted")
            return

    # Now delete
    deleted = 0
    for col in COLUMNS:
        col_path = root / col
        if col_path.exists():
            for card in col_path.glob("*.md"):
                card.unlink()
                deleted += 1

    print(f"Cleared {deleted} cards from kanban board")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Kanban CLI - File-based kanban board for agent coordination"
    )
    parser.add_argument("--root", help="Kanban root directory (or set KANBAN_ROOT)")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # init
    p_init = subparsers.add_parser("init", help="Create kanban board structure")
    p_init.add_argument("path", nargs="?", default=None, help="Board path (default: auto-computed from cwd)")

    # add (with position requirement)
    p_add = subparsers.add_parser("add", help="Add card to todo (position required)")
    p_add.add_argument("title", help="Card title")
    p_add.add_argument("--persona", help="Persona for the card")
    p_add.add_argument("--content", "-c", help="Card body content (e.g., task description)")
    p_add.add_argument("--status", choices=COLUMNS, default="todo", help="Starting column (default: todo)")
    p_add.add_argument("--top", action="store_true", help="Insert at top of column")
    p_add.add_argument("--bottom", action="store_true", help="Insert at bottom of column")
    p_add.add_argument("--after", help="Insert after specified card")
    p_add.add_argument("--before", help="Insert before specified card")

    # delete
    p_delete = subparsers.add_parser("delete", help="Delete a card")
    p_delete.add_argument("card", help="Card number or name")

    # edit
    p_edit = subparsers.add_parser("edit", help="Edit a card's content or metadata")
    p_edit.add_argument("card", help="Card number or name")
    p_edit.add_argument("--content", "-c", help="New card body content (use '-' for stdin)")
    p_edit.add_argument("--persona", help="Update persona")
    p_edit.add_argument("--append", "-a", action="store_true", help="Append to content instead of replacing")

    # move
    p_move = subparsers.add_parser("move", help="Move card to column")
    p_move.add_argument("card", help="Card number or name")
    p_move.add_argument("column", help="Target column")

    # up
    p_up = subparsers.add_parser("up", help="Move card up in priority")
    p_up.add_argument("card", help="Card number or name")

    # down
    p_down = subparsers.add_parser("down", help="Move card down in priority")
    p_down.add_argument("card", help="Card number or name")

    # top
    p_top = subparsers.add_parser("top", help="Move card to top of column")
    p_top.add_argument("card", help="Card number or name")

    # bottom
    p_bottom = subparsers.add_parser("bottom", help="Move card to bottom of column")
    p_bottom.add_argument("card", help="Card number or name")

    # next
    p_next = subparsers.add_parser("next", help="Get next card to work on")
    p_next.add_argument("--persona", help="Filter by persona")
    p_next.add_argument("--skip", type=int, default=0, help="Skip N cards (for blocked cards)")

    # comment
    p_comment = subparsers.add_parser("comment", help="Add comment to card")
    p_comment.add_argument("card", help="Card number or name")
    p_comment.add_argument("message", help="Comment message")

    # history
    p_history = subparsers.add_parser("history", help="Show completed cards")
    p_history.add_argument("--since", help="Filter by date (today, yesterday, week, month, or ISO date)")
    p_history.add_argument("--until", help="Filter until date (ISO format)")

    # list (with ls alias)
    subparsers.add_parser("list", help="Show board overview")
    subparsers.add_parser("ls", help="Show board overview (alias for list)")

    # show
    p_show = subparsers.add_parser("show", help="Display card contents")
    p_show.add_argument("card", help="Card number or name")

    # Column view commands (kanban <column>)
    for col in COLUMNS:
        p_col = subparsers.add_parser(col, help=f"View cards in {col}")
        p_col.set_defaults(column=col)

    # clear
    p_clear = subparsers.add_parser("clear", help="Delete all cards from all columns")
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
        "next": cmd_next,
        "comment": cmd_comment,
        "history": cmd_history,
        "list": cmd_list,
        "ls": cmd_list,
        "show": cmd_show,
        "todo": cmd_view,
        "doing": cmd_view,
        "waiting": cmd_view,
        "done": cmd_view,
        "clear": cmd_clear,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
