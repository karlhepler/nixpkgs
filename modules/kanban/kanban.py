"""
Kanban CLI - File-based kanban board for agent coordination.

Cards are markdown files with YAML frontmatter, stored in column folders.
Priority field controls ordering within columns (lower = higher in list).
"""

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

COLUMNS = ["backlog", "in-progress", "waiting", "done"]


def get_root(args_root: str | None) -> Path:
    """Get kanban root directory from args or environment."""
    if args_root:
        return Path(args_root)
    if root := os.environ.get("KANBAN_ROOT"):
        return Path(root)
    print("Error: KANBAN_ROOT not set. Use --root or set KANBAN_ROOT env var.", file=sys.stderr)
    sys.exit(1)


def slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    return re.sub(r"[^a-z0-9-]", "", text.lower().replace(" ", "-"))


def now_iso() -> str:
    """Get current time in ISO format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def update_card(card_path: Path, updates: dict) -> None:
    """Update card frontmatter fields."""
    content = card_path.read_text()
    frontmatter, body = parse_frontmatter(content)

    frontmatter.update(updates)
    frontmatter["updated"] = now_iso()

    card_path.write_text(serialize_frontmatter(frontmatter, body))


def cmd_init(args) -> None:
    """Create kanban board structure."""
    path = Path(args.path)
    for col in COLUMNS:
        (path / col).mkdir(parents=True, exist_ok=True)

    print(f"Created kanban board at: {path}")
    print()
    print("Set KANBAN_ROOT to use:")
    print(f'  export KANBAN_ROOT="{path}"')


def cmd_add(args) -> None:
    """Add a new card to backlog."""
    root = get_root(args.root)
    num = next_number(root)
    slug = slugify(args.title)
    filename = f"{num}-{slug}.md"
    filepath = root / "backlog" / filename
    now = now_iso()

    content = f"""---
persona: {args.persona or 'unassigned'}
priority: 0
created: {now}
updated: {now}
---

# {args.title}
"""
    filepath.write_text(content)
    print(f"Created: backlog/{filename}")


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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Kanban CLI - File-based kanban board for agent coordination"
    )
    parser.add_argument("--root", help="Kanban root directory (or set KANBAN_ROOT)")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # init
    p_init = subparsers.add_parser("init", help="Create kanban board structure")
    p_init.add_argument("path", nargs="?", default="./kanban", help="Board path")

    # add
    p_add = subparsers.add_parser("add", help="Add card to backlog")
    p_add.add_argument("title", help="Card title")
    p_add.add_argument("--persona", help="Persona for the card")

    # delete
    p_delete = subparsers.add_parser("delete", help="Delete a card")
    p_delete.add_argument("card", help="Card number or name")

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

    # list
    subparsers.add_parser("list", help="Show board overview")

    # show
    p_show = subparsers.add_parser("show", help="Display card contents")
    p_show.add_argument("card", help="Card number or name")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {
        "init": cmd_init,
        "add": cmd_add,
        "delete": cmd_delete,
        "move": cmd_move,
        "up": cmd_up,
        "down": cmd_down,
        "top": cmd_top,
        "bottom": cmd_bottom,
        "list": cmd_list,
        "show": cmd_show,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
