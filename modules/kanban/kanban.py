"""
Kanban CLI - File-based kanban board for agent coordination.

Cards are JSON files stored in column folders. Staff engineer owns the board;
sub-agents are kanban-unaware. This dramatically reduces context bloat.

Card format: NNN.json (e.g., 42.json)
Columns: todo, doing, review, done, canceled

ENVIRONMENT VARIABLES:
  KANBAN_HIDE_MINE     - Hide your own session's cards by default
  KANBAN_ARCHIVE_DAYS  - Days before auto-archiving done cards (default: 30)
  KANBAN_SESSION       - Override session detection (for smithers/burns)
  KANBAN_ROOT          - Override board location
"""

import argparse
import html
import json
import os
import re
import select
import subprocess
import sys
import termios
import threading
import time
import tty
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from threading import Event

# Filesystem watching (bundled via Nix Python wrapper)
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

@dataclass
class WatchState:
    output_style: str = "simple"  # "simple" | "xml" | "detail"
    session_filter: str = ""
    card_filter: str = ""
    input_mode: str = ""       # "" | "session" | "card"
    input_buffer: str = ""

COLUMNS = ["todo", "doing", "review", "done", "canceled"]
ARCHIVE_DAYS_THRESHOLD = int(os.environ.get("KANBAN_ARCHIVE_DAYS", "30"))

# Word lists for friendly session names (adjective-noun, Docker-style)
_ADJECTIVES = [
    "bold", "brave", "bright", "brisk", "calm", "clear", "cool", "crisp",
    "deft", "eager", "fair", "fast", "firm", "fond", "free", "fresh",
    "glad", "gold", "good", "grand", "great", "green", "happy", "keen",
    "kind", "lively", "lucky", "mild", "neat", "noble", "proud", "pure",
    "quick", "quiet", "rapid", "ready", "sharp", "sleek", "smart", "snappy",
    "solid", "steady", "stout", "strong", "sturdy", "sure", "sweet", "swift",
    "tidy", "trim", "true", "vivid", "warm", "wise", "witty", "zesty",
]

_NOUNS = [
    "arrow", "badge", "beam", "bell", "blade", "bloom", "bolt", "bridge",
    "brook", "cedar", "cliff", "cloud", "coral", "crane", "crest", "crown",
    "dawn", "delta", "drift", "eagle", "ember", "falcon", "fern", "field",
    "flame", "flint", "forge", "frost", "gale", "grove", "hawk", "hedge",
    "heron", "hill", "lake", "lark", "leaf", "light", "maple", "marsh",
    "mesa", "moon", "north", "oak", "orbit", "otter", "peak", "pine",
    "pond", "quartz", "rain", "reef", "ridge", "river", "rook", "sage",
    "shore", "spark", "spire", "star", "stone", "storm", "tide", "trail",
    "vale", "wave", "willow", "wind", "wing", "wren", "zenith", "zephyr",
]


# =============================================================================
# Utility functions (reused from v1)
# =============================================================================

def get_git_root() -> Path | None:
    """Find the git repository root, or None if not in a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def now_iso() -> str:
    """Get current time in ISO format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(date_str: str) -> datetime:
    """Parse ISO format date string."""
    return datetime.fromisoformat(date_str.replace("Z", "+00:00"))



def get_current_session_id() -> str | None:
    """Get session ID — env var > username for terminal."""
    if session_id := os.environ.get("KANBAN_SESSION"):
        return session_id
    try:
        return os.environ.get("USER") or os.getlogin()
    except OSError:
        return None


def resolve_session_name(uuid_prefix: str, root: Path) -> str:
    """Map UUID prefix to a friendly adjective-noun name, creating if needed."""
    sessions_file = root / "sessions.json"

    # Load existing mappings
    sessions: dict[str, str] = {}
    if sessions_file.exists():
        try:
            sessions = json.loads(sessions_file.read_text())
        except (json.JSONDecodeError, OSError):
            sessions = {}

    # Return existing mapping
    if uuid_prefix in sessions:
        return sessions[uuid_prefix]

    # Generate new name — deterministic from UUID, with collision fallback
    used_names = set(sessions.values())
    seed = int(uuid_prefix, 16)
    adj_idx = seed % len(_ADJECTIVES)
    noun_idx = (seed // len(_ADJECTIVES)) % len(_NOUNS)
    name = f"{_ADJECTIVES[adj_idx]}-{_NOUNS[noun_idx]}"

    # Handle unlikely collisions by incrementing
    while name in used_names:
        noun_idx = (noun_idx + 1) % len(_NOUNS)
        name = f"{_ADJECTIVES[adj_idx]}-{_NOUNS[noun_idx]}"

    sessions[uuid_prefix] = name
    root.mkdir(parents=True, exist_ok=True)
    sessions_file.write_text(json.dumps(sessions, indent=2) + "\n")
    return name


# =============================================================================
# Board management
# =============================================================================

def auto_archive_old_cards(root: Path, days_threshold: int = ARCHIVE_DAYS_THRESHOLD) -> None:
    """Archive done cards older than threshold days."""
    done_dir = root / "done"
    archive_base = root / "archive"
    if not done_dir.exists():
        return

    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_threshold)
    archived_count = 0

    for card_file in done_dir.glob("*.json"):
        try:
            card = json.loads(card_file.read_text())
            updated_str = card.get("updated")
            if not updated_str:
                continue
            updated = parse_iso(updated_str)
            if updated < cutoff_date:
                archive_month = updated.strftime("%Y-%m")
                archive_dir = archive_base / archive_month
                archive_dir.mkdir(parents=True, exist_ok=True)
                card_file.rename(archive_dir / card_file.name)
                archived_count += 1
        except (ValueError, KeyError, json.JSONDecodeError):
            continue

    if archived_count > 0:
        print(f"Auto-archived {archived_count} old card(s) to {archive_base}/", file=sys.stderr)


def get_root(args_root: str | None, auto_init: bool = True) -> Path:
    """Get kanban root directory with auto-init."""
    if args_root:
        root = Path(args_root)
    elif root_env := os.environ.get("KANBAN_ROOT"):
        root = Path(root_env)
    else:
        base_dir = get_git_root() or Path.cwd()
        root = base_dir / ".kanban"

    if auto_init and not root.exists():
        for col in COLUMNS:
            (root / col).mkdir(parents=True, exist_ok=True)
        (root / "archive").mkdir(parents=True, exist_ok=True)
        (root / "scratchpad").mkdir(parents=True, exist_ok=True)

    # Ensure scratchpad exists even for already-initialized boards
    if root.exists():
        (root / "scratchpad").mkdir(exist_ok=True)

    if root.exists():
        auto_archive_old_cards(root)

    return root


# =============================================================================
# Card I/O (JSON format)
# =============================================================================

def read_card(path: Path) -> dict:
    """Read a JSON card file."""
    return json.loads(path.read_text())


def write_card(path: Path, card: dict) -> None:
    """Write a JSON card file."""
    path.write_text(json.dumps(card, indent=2) + "\n")


def find_all_cards(root: Path, include_archived: bool = True) -> list[Path]:
    """Find all card files across columns and optionally archive."""
    cards = []
    for col in COLUMNS:
        col_path = root / col
        if col_path.exists():
            cards.extend(col_path.glob("*.json"))
    if include_archived:
        archive_base = root / "archive"
        if archive_base.exists():
            for archive_dir in archive_base.iterdir():
                if archive_dir.is_dir():
                    cards.extend(archive_dir.glob("*.json"))
    return cards


def find_cards_in_column(root: Path, col: str) -> list[Path]:
    """Find all cards in a column, sorted by card number."""
    col_path = root / col
    if not col_path.exists():
        return []
    cards = list(col_path.glob("*.json"))

    def safe_card_num(p: Path) -> int:
        try:
            match = re.match(r"(\d+)\.json$", p.name)
            return int(match.group(1)) if match else 0
        except (ValueError, AttributeError):
            return 0

    cards.sort(key=safe_card_num)
    return cards


def next_number(root: Path) -> int:
    """Get next available card number."""
    max_num = 0
    for card_file in find_all_cards(root):
        match = re.match(r"(\d+)\.json$", card_file.name)
        if match:
            max_num = max(max_num, int(match.group(1)))
    return max_num + 1


def find_card(root: Path, pattern: str) -> Path:
    """Find a card by number, searching columns then archive."""
    if pattern.isdigit():
        pattern = str(int(pattern))

    # Search active columns first
    for card_file in find_all_cards(root, include_archived=False):
        num_match = re.match(r"(\d+)\.json$", card_file.name)
        if num_match and num_match.group(1) == pattern:
            return card_file

    # Fall back to archive
    archive_base = root / "archive"
    if archive_base.exists():
        for archive_dir in archive_base.iterdir():
            if archive_dir.is_dir():
                for card_file in archive_dir.glob("*.json"):
                    num_match = re.match(r"(\d+)\.json$", card_file.name)
                    if num_match and num_match.group(1) == pattern:
                        return card_file

    print(f"Error: No card found matching '{pattern}'", file=sys.stderr)
    sys.exit(1)


def card_number(path: Path) -> str:
    """Extract card number from filename."""
    match = re.match(r"(\d+)\.json$", path.name)
    return match.group(1) if match else path.stem


def get_session_from_card(card: dict) -> str | None:
    """Get session from card dict."""
    return card.get("session")


def get_session_from_path(path: Path) -> str | None:
    """Get session from card file."""
    try:
        return read_card(path).get("session")
    except (json.JSONDecodeError, OSError):
        return None


# =============================================================================
# Date filter helpers
# =============================================================================

def parse_date_filter(value: str) -> datetime | None:
    """Parse a date filter string into a datetime."""
    if value == "today":
        local_midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return local_midnight.astimezone(timezone.utc)
    elif value == "yesterday":
        local_midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        return local_midnight.astimezone(timezone.utc)
    elif value == "week":
        return datetime.now(timezone.utc) - timedelta(days=7)
    elif value == "month":
        return datetime.now(timezone.utc) - timedelta(days=30)
    else:
        try:
            return parse_iso(value)
        except ValueError:
            print(f"Error: Invalid date format '{value}'", file=sys.stderr)
            sys.exit(1)


def card_in_date_range(card: dict, since: datetime | None, until: datetime | None) -> bool:
    """Check if a card's updated timestamp falls within the date range."""
    updated_str = card.get("updated", "")
    if not updated_str:
        return True
    try:
        updated = parse_iso(updated_str)
        if since and updated < since:
            return False
        if until and updated > until:
            return False
    except ValueError:
        pass
    return True


# =============================================================================
# Session filtering helpers
# =============================================================================

def resolve_session_filters(args) -> tuple[str | None, bool, bool]:
    """Resolve session filtering from args and env vars.

    Returns: (current_session, hide_own, show_only_mine)
    """
    current_session = get_current_session_id()

    hide_own_default = os.environ.get("KANBAN_HIDE_MINE", "").lower() in ["true", "1", "yes"]
    show_only_mine = getattr(args, "only_mine", False)
    hide_mine_explicit = getattr(args, "hide_mine", False)
    show_mine_explicit = getattr(args, "show_mine", False)

    # Explicit session override
    if hasattr(args, "session") and args.session:
        return args.session, False, True

    if show_only_mine:
        hide_own = False
    elif show_mine_explicit:
        hide_own = False
    elif hide_mine_explicit:
        hide_own = True
    elif hide_own_default:
        hide_own = True
    else:
        hide_own = False

    return current_session, hide_own, show_only_mine


def is_my_card(card: dict, current_session: str | None) -> bool:
    """Check if a card belongs to the current session."""
    card_session = card.get("session")
    if current_session:
        return card_session == current_session or card_session is None
    return True  # No session detected — all cards are "mine"


# =============================================================================
# Commands
# =============================================================================

def cmd_init(args) -> None:
    """Create kanban board structure."""
    if args.path:
        path = Path(args.path)
    else:
        base_dir = get_git_root() or Path.cwd()
        path = base_dir / ".kanban"

    for col in COLUMNS:
        (path / col).mkdir(parents=True, exist_ok=True)
    (path / "archive").mkdir(parents=True, exist_ok=True)
    (path / "scratchpad").mkdir(parents=True, exist_ok=True)
    print(f"Kanban board ready at: {path}")



def cmd_session_hook(args) -> None:
    """Handle SessionStart hook — extract session UUID, output kanban instructions."""
    data = json.loads(sys.stdin.read())
    session_id = data.get("session_id", "")

    if not session_id:
        return

    # Sub-agents (Task tool) have agent_type in stdin JSON — suppress for them
    if data.get("agent_type"):
        return

    # Resolve UUID to friendly name via .kanban/sessions.json
    root = get_root(None, auto_init=False)
    root.mkdir(parents=True, exist_ok=True)
    name = resolve_session_name(session_id[:8], root)

    # Always output full instructions (compact/clear may wipe context)
    print(f"🔖 Your kanban session is: {name}")
    print()
    print(f"You MUST use --session {name} on ALL kanban commands:")
    print(f"  kanban list --session {name}")
    print(f"  kanban do '{{\"intent\":\"...\",\"action\":\"...\"}}' --session {name}")
    print(f"  kanban show 5 --session {name}")
    print(f"  kanban review 5 --session {name}")
    print(f"  kanban done 5 'summary' --session {name}")

    # One-time cleanup of legacy nonce directory
    legacy = Path("/tmp/kanban-nonces")
    if legacy.exists():
        import shutil
        shutil.rmtree(legacy, ignore_errors=True)


def make_card(
    action: str,
    intent: str = "",
    read_files: list[str] | None = None,
    edit_files: list[str] | None = None,
    persona: str = "unassigned",
    model: str | None = None,
    session: str | None = None,
    criteria: list[str] | None = None,
) -> dict:
    """Build a new card dict."""
    now = now_iso()
    card = {
        "action": action,
        "intent": intent,
        "readFiles": read_files or [],
        "editFiles": edit_files or [],
        "persona": persona,
        "model": model,
        "session": session,
        "created": now,
        "updated": now,
        "activity": [{"timestamp": now, "message": "Created"}],
    }

    # Add acceptance criteria if provided
    if criteria:
        card["criteria"] = [{"text": c, "met": False} for c in criteria]

    return card


def create_card_in_column(root: Path, column: str, card: dict) -> int:
    """Write a card to a column, return its number."""
    num = next_number(root)
    filepath = root / column / f"{num}.json"
    filepath.parent.mkdir(parents=True, exist_ok=True)
    write_card(filepath, card)
    return num


def validate_and_build_card(data: dict, session: str | None) -> dict:
    """Validate card data and build card dict.

    Raises SystemExit on validation failure.
    """
    if "action" not in data:
        print("Error: JSON must include 'action' field", file=sys.stderr)
        sys.exit(1)

    # Validate action is non-empty
    if not data.get("action", "").strip():
        print("Error: Action field must be a non-empty string.", file=sys.stderr)
        sys.exit(1)

    # Validate model if provided
    model = data.get("model")
    if model and model not in ("haiku", "sonnet", "opus"):
        print(f"Error: Invalid model '{model}'. Must be one of: haiku, sonnet, opus", file=sys.stderr)
        sys.exit(1)

    # Validate editFiles/readFiles are arrays
    for field in ("editFiles", "readFiles"):
        val = data.get(field)
        if val is not None and not isinstance(val, list):
            print(f"Error: {field} must be an array, got {type(val).__name__}", file=sys.stderr)
            sys.exit(1)

    # Parse criteria from JSON (support both "criteria" and "ac" shorthand)
    criteria = data.get("criteria") or data.get("ac", [])

    # Build the card
    card = make_card(
        action=data["action"],
        intent=data.get("intent", ""),
        read_files=data.get("readFiles", []),
        edit_files=data.get("editFiles", []),
        persona=data.get("persona", "unassigned"),
        model=data.get("model"),
        session=session,
        criteria=criteria if all(isinstance(c, str) for c in criteria) else None,
    )

    # If criteria came as full objects (with text/met), use them directly
    if criteria and not all(isinstance(c, str) for c in criteria):
        card["criteria"] = criteria

    # Validate criteria count after building card
    criteria_check = card.get("criteria", [])
    if not criteria_check:
        print("Error: At least one acceptance criterion required. Add \"criteria\": [\"...\"] to JSON.", file=sys.stderr)
        sys.exit(1)

    # Remove readFiles entries that are already in editFiles (editing implies reading)
    edit_files = card.get("editFiles", [])
    read_files = card.get("readFiles", [])
    if edit_files and read_files:
        card["readFiles"] = [f for f in read_files if f not in edit_files]

    return card


def cmd_do(args) -> None:
    """Create card(s) directly in the doing column from JSON input.

    Accepts either a single JSON object or an array of objects for bulk creation.
    """
    root = get_root(args.root)

    try:
        data = json.loads(args.json_data)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    session = args.session if hasattr(args, "session") and args.session else get_current_session_id()

    # Detect array vs object
    if isinstance(data, list):
        # Bulk creation: validate all cards first (fail fast)
        cards = []
        for i, card_data in enumerate(data):
            if not isinstance(card_data, dict):
                print(f"Error: Array element {i} must be a JSON object, got {type(card_data).__name__}", file=sys.stderr)
                sys.exit(1)
            card = validate_and_build_card(card_data, session)
            cards.append(card)

        # All validation passed — create all cards
        for card in cards:
            num = create_card_in_column(root, "doing", card)
            print(num)
    elif isinstance(data, dict):
        # Single card creation (existing behavior)
        card = validate_and_build_card(data, session)
        num = create_card_in_column(root, "doing", card)
        print(num)
    else:
        print(f"Error: JSON must be an object or array, got {type(data).__name__}", file=sys.stderr)
        sys.exit(1)




def cmd_redo(args) -> None:
    """Move card from review back to doing."""
    root = get_root(args.root)
    card_path = find_card(root, args.card)
    col = card_path.parent.name
    num = card_number(card_path)

    if col != "review":
        print(f"Error: Card #{num} is in '{col}', not 'review'. Redo only works on cards in review.", file=sys.stderr)
        sys.exit(1)

    card = read_card(card_path)
    card["updated"] = now_iso()
    write_card(card_path, card)

    target = root / "doing" / card_path.name
    target.parent.mkdir(parents=True, exist_ok=True)
    card_path.rename(target)
    print(f"Redo: #{num} — moved back to doing")


def cmd_defer(args) -> None:
    """Move card from doing or review back to todo."""
    root = get_root(args.root)
    card_path = find_card(root, args.card)
    col = card_path.parent.name
    num = card_number(card_path)

    if col not in ["doing", "review"]:
        print(f"Error: Card #{num} is in '{col}', not 'doing' or 'review'. Defer only works on cards in doing or review.", file=sys.stderr)
        sys.exit(1)

    card = read_card(card_path)
    card["updated"] = now_iso()
    write_card(card_path, card)

    target = root / "todo" / card_path.name
    target.parent.mkdir(parents=True, exist_ok=True)
    card_path.rename(target)
    print(f"Deferred: #{num} — moved to todo")


def cmd_start(args) -> None:
    """Move card(s) from todo to doing (pick up queued work)."""
    root = get_root(args.root)
    card_numbers = args.card if isinstance(args.card, list) else [args.card]

    failed = False
    for card_num in card_numbers:
        try:
            card_path = find_card(root, card_num)
            col = card_path.parent.name
            num = card_number(card_path)

            if col != "todo":
                print(f"Error: Card #{num} is in '{col}', not 'todo'. Start only works on cards in todo.", file=sys.stderr)
                failed = True
                continue

            card = read_card(card_path)
            card["updated"] = now_iso()
            write_card(card_path, card)

            target = root / "doing" / card_path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            card_path.rename(target)
            print(f"Started: #{num} — moved to doing")
        except SystemExit:
            # find_card calls sys.exit(1) if card not found
            failed = True
            continue
        except (json.JSONDecodeError, OSError) as e:
            print(f"Error: Failed to process card {card_num}: {e}", file=sys.stderr)
            failed = True
            continue

    if failed:
        sys.exit(1)


def cmd_show(args) -> None:
    """Display card contents."""
    root = get_root(args.root)
    card_path = find_card(root, args.card)
    card = read_card(card_path)
    col = card_path.parent.name
    num = card_number(card_path)

    # Claude XML output style
    if getattr(args, "output_style", None) == "xml":
        print(format_card_xml(card, num, col, include_details=True))
        return

    # Default: human-friendly terminal output (simple or detail)
    bold = "\033[1m"
    dim_bold = "\033[2;1m"
    reset = "\033[0m"

    # Header
    print(f"=== Card #{num} ({col}) ===")
    print()

    # Action (main title)
    action = card.get("action", "[NO ACTION]")
    print(action)

    # Intent section
    intent = card.get("intent", "")
    if intent:
        print()
        print(f"{dim_bold}  Intent{reset}")
        # Replace literal \n with actual newlines, then wrap at ~80 chars
        intent = intent.replace("\\n", "\n")
        for paragraph in intent.split("\n"):
            words = paragraph.split()
            lines = []
            current_line = ""
            for word in words:
                if current_line and len(current_line) + len(word) + 1 > 80:
                    lines.append(current_line)
                    current_line = word
                else:
                    if current_line:
                        current_line += " " + word
                    else:
                        current_line = word
            if current_line:
                lines.append(current_line)
            for line in lines:
                print(f"  {line}")

    # Acceptance criteria section
    criteria = card.get("criteria", [])
    if criteria:
        print()
        print(f"{dim_bold}  Acceptance Criteria{reset}")
        for i, criterion in enumerate(criteria, start=1):
            checkbox = "✅" if criterion.get("met", False) else "⬜"
            text = criterion.get("text", "")
            print(f"  {checkbox} {i}. {text}")

    # Edit files section
    edit_files = card.get("editFiles") or card.get("writeFiles", [])
    if edit_files:
        print()
        print(f"{dim_bold}  Edit Files{reset}")
        for f in sorted(edit_files):
            print(f"  {f}")

    # Read files section
    read_files = card.get("readFiles", [])
    if read_files:
        print()
        print(f"{dim_bold}  Read Files{reset}")
        for f in sorted(read_files):
            print(f"  {f}")

    # Footer with metadata
    print()
    session = card.get("session", "")
    persona = card.get("persona", "unassigned")
    model = card.get("model")
    created = card.get("created", "")
    if created:
        try:
            created_date = parse_iso(created).strftime("%Y-%m-%d")
        except ValueError:
            created_date = created[:10]
    else:
        created_date = "unknown"

    footer_parts = []
    if session:
        footer_parts.append(f"Session: {session[:8]}")
    if persona and persona != "unassigned":
        footer_parts.append(f"Persona: {persona}")
    if model:
        footer_parts.append(f"Model: {model}")
    footer_parts.append(f"Created: {created_date}")

    print(f"{bold}{' · '.join(footer_parts)}{reset}")


def cmd_cancel(args) -> None:
    """Move card to canceled column."""
    root = get_root(args.root)
    card_path = find_card(root, args.card)
    card = read_card(card_path)
    num = card_number(card_path)

    # Store cancellation reason if provided
    reason = args.reason if hasattr(args, "reason") and args.reason else None
    if reason:
        card["cancelReason"] = reason

    card["updated"] = now_iso()
    write_card(card_path, card)

    target_path = root / "canceled" / card_path.name
    target_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.rename(target_path)

    # Output with reason if provided
    if reason:
        print(f"Canceled: #{num} — {reason}")
    else:
        print(f"Canceled: #{num}")


def cmd_criteria_add(args) -> None:
    """Add acceptance criterion to card."""
    root = get_root(args.root)
    card_path = find_card(root, args.card)
    card = read_card(card_path)

    # Initialize criteria list if it doesn't exist
    if "criteria" not in card:
        card["criteria"] = []

    card["criteria"].append({"text": args.text, "met": False})
    card["updated"] = now_iso()
    write_card(card_path, card)
    print(f"Added criterion to #{card_number(card_path)}: {args.text}")


def cmd_criteria_remove(args) -> None:
    """Remove acceptance criterion from card."""
    root = get_root(args.root)
    card_path = find_card(root, args.card)
    card = read_card(card_path)

    criteria = card.get("criteria", [])
    if not criteria:
        print("Error: Card has no acceptance criteria to remove", file=sys.stderr)
        sys.exit(1)

    # Validate criterion number
    criterion_idx = args.n - 1  # Convert to 0-based
    if criterion_idx < 0 or criterion_idx >= len(criteria):
        print(f"Error: Invalid criterion number {args.n}. Valid range: 1-{len(criteria)}", file=sys.stderr)
        sys.exit(1)

    # Check if removal would leave zero criteria
    if len(criteria) <= 1:
        print("Error: Cannot remove last acceptance criterion. Cards must have at least one.", file=sys.stderr)
        sys.exit(1)

    # Remove criterion and log to activity
    removed_criterion = criteria[criterion_idx]
    removed_text = removed_criterion.get("text", "")

    if "activity" not in card:
        card["activity"] = []

    card["activity"].append({
        "timestamp": now_iso(),
        "message": f"Removed AC {args.n}: '{removed_text}' — Reason: {args.reason}"
    })

    criteria.pop(criterion_idx)
    card["updated"] = now_iso()
    write_card(card_path, card)
    print(f"Removed criterion from #{card_number(card_path)}: {removed_text}")
    print(f"Reason: {args.reason}")


def cmd_criteria_check(args) -> None:
    """Mark acceptance criterion(s) as met."""
    root = get_root(args.root)
    card_path = find_card(root, args.card)
    card = read_card(card_path)

    criteria = card.get("criteria", [])
    if not criteria:
        print(f"Error: Card #{card_number(card_path)} has no acceptance criteria", file=sys.stderr)
        sys.exit(1)

    for criterion_arg in args.n:
        # Find criterion by 1-based index or text prefix match
        criterion_idx = None
        if str(criterion_arg).isdigit():
            idx = int(criterion_arg) - 1  # Convert to 0-based
            if 0 <= idx < len(criteria):
                criterion_idx = idx
        else:
            # Text prefix match (case insensitive)
            search_text = str(criterion_arg).lower()
            for i, c in enumerate(criteria):
                if c.get("text", "").lower().startswith(search_text):
                    criterion_idx = i
                    break

        if criterion_idx is None:
            print(f"Error: No criterion found matching '{criterion_arg}'", file=sys.stderr)
            sys.exit(1)

        criteria[criterion_idx]["met"] = True
        print(f"✅ Checked: {criteria[criterion_idx]['text']}")

    card["updated"] = now_iso()
    write_card(card_path, card)


def cmd_criteria_uncheck(args) -> None:
    """Mark acceptance criterion as unmet."""
    root = get_root(args.root)
    card_path = find_card(root, args.card)
    card = read_card(card_path)

    criteria = card.get("criteria", [])
    if not criteria:
        print(f"Error: Card #{card_number(card_path)} has no acceptance criteria", file=sys.stderr)
        sys.exit(1)

    # Find criterion by 1-based index or text prefix match
    criterion_idx = None
    if str(args.n).isdigit():
        idx = int(args.n) - 1  # Convert to 0-based
        if 0 <= idx < len(criteria):
            criterion_idx = idx
    else:
        # Text prefix match (case insensitive)
        search_text = str(args.n).lower()
        for i, c in enumerate(criteria):
            if c.get("text", "").lower().startswith(search_text):
                criterion_idx = i
                break

    if criterion_idx is None:
        print(f"Error: No criterion found matching '{args.n}'", file=sys.stderr)
        sys.exit(1)

    criteria[criterion_idx]["met"] = False
    card["updated"] = now_iso()
    write_card(card_path, card)
    print(f"⬜ Unchecked: {criteria[criterion_idx]['text']}")


def cmd_criteria_dispatch(args) -> None:
    """Dispatch to the appropriate criteria subcommand."""
    subcommand_map = {
        "add": cmd_criteria_add,
        "remove": cmd_criteria_remove,
        "check": cmd_criteria_check,
        "uncheck": cmd_criteria_uncheck,
    }
    handler = subcommand_map.get(args.criteria_command)
    if handler:
        handler(args)
    else:
        print(f"Error: Unknown criteria subcommand '{args.criteria_command}'", file=sys.stderr)
        sys.exit(1)


# =============================================================================
# List and view commands
# =============================================================================

def format_card_xml(card: dict, num: str, col: str, include_details: bool = False) -> str:
    """Format a single card as XML.

    Args:
        card: Card dictionary
        num: Card number string
        col: Column/status name
        include_details: Include intent, AC, and activity (for show command)
    """
    esc = html.escape
    session = card.get("session", "")
    action = card.get("action", "")

    # Card opening tag with attributes
    xml_parts = [f'<card num="{esc(num)}" session="{esc(session)}" status="{esc(col)}">']

    # Action (always included as child element)
    xml_parts.append(f"  <action>{esc(action)}</action>")

    # Intent (only in show/details mode)
    if include_details:
        intent = card.get("intent", "")
        if intent:
            xml_parts.append(f"  <intent>{esc(intent)}</intent>")

    # Acceptance criteria (only in show/details mode)
    if include_details:
        criteria = card.get("criteria", [])
        if criteria:
            xml_parts.append("  <acceptance-criteria>")
            for criterion in criteria:
                met = "true" if criterion.get("met", False) else "false"
                text = esc(criterion.get("text", ""))
                xml_parts.append(f'    <ac met="{met}">{text}</ac>')
            xml_parts.append("  </acceptance-criteria>")

    # Edit files
    edit_files = card.get("editFiles") or card.get("writeFiles", [])
    if edit_files:
        xml_parts.append("  <edit-files>")
        for f in sorted(edit_files):
            xml_parts.append(f"    <f>{esc(f)}</f>")
        xml_parts.append("  </edit-files>")

    # Read files
    read_files = card.get("readFiles", [])
    if read_files:
        xml_parts.append("  <read-files>")
        for f in sorted(read_files):
            xml_parts.append(f"    <f>{esc(f)}</f>")
        xml_parts.append("  </read-files>")

    # Activity (only in show/details mode)
    if include_details:
        activity = card.get("activity", [])
        if activity:
            xml_parts.append("  <activity>")
            for event in activity:
                timestamp = esc(event.get("timestamp", ""))
                message = esc(event.get("message", ""))
                xml_parts.append(f'    <event ts="{timestamp}">{message}</event>')
            xml_parts.append("  </activity>")

    xml_parts.append("</card>")
    return "\n".join(xml_parts)


def format_lead_time(seconds: float) -> str:
    """Format lead time in human-readable format (e.g., '2h 15m', '45m', '3d 1h')."""
    if seconds < 60:
        return f"{int(seconds)}s"

    minutes = int(seconds / 60)
    if minutes < 60:
        return f"{minutes}m"

    hours = minutes // 60
    remaining_minutes = minutes % 60
    if hours < 24:
        if remaining_minutes > 0:
            return f"{hours}h {remaining_minutes}m"
        return f"{hours}h"

    days = hours // 24
    remaining_hours = hours % 24
    if remaining_hours > 0:
        return f"{days}d {remaining_hours}h"
    return f"{days}d"


def calculate_lead_time(card: dict) -> float | None:
    """Calculate lead time in seconds for a completed card.

    Returns None if timestamps are missing or invalid.
    """
    created_str = card.get("created")
    updated_str = card.get("updated")

    if not created_str or not updated_str:
        return None

    try:
        created = parse_iso(created_str)
        updated = parse_iso(updated_str)
        return (updated - created).total_seconds()
    except (ValueError, AttributeError):
        return None


def format_card_line(card: dict, num: str, show_session: bool = False, output_style: str = "simple", is_first_card: bool = True, column: str = "") -> str:
    """Format a single card for list/view output.

    Args:
        card: Card dictionary
        num: Card number string
        show_session: Whether to show session prefix (for other sessions)
        output_style: "simple" (title only), "xml" (XML format), or "detail" (everything)
        is_first_card: Whether this is the first card (for spacing)
        column: Column name (for showing lead time on done cards)
    """
    # Note: XML output for list is now handled in cmd_list directly
    # This function only handles simple and detail styles

    # Non-claude styles use ANSI codes
    dim = "\033[2m"
    reset = "\033[0m"

    # Add blank line before card if not simple style and not first card
    prefix = ""
    if output_style != "simple" and not is_first_card:
        prefix = "\n"

    session = card.get("session", "")
    session_suffix = f" {dim}({session[:8]}){reset}" if (session and show_session) else ""
    line = f"{prefix}  #{num} {card.get('action', '[NO ACTION]')}{session_suffix}"

    # Add lead time for done cards
    if column == "done":
        lead_time_seconds = calculate_lead_time(card)
        if lead_time_seconds is not None:
            lead_time_str = format_lead_time(lead_time_seconds)
            line += f" {dim}({lead_time_str}){reset}"

    # Simple style: title only
    if output_style == "simple":
        return line

    # Build detail sections based on style
    sections = []

    # Intent section (only in "detail" style)
    if output_style == "detail" and card.get("intent"):
        intent_text = card["intent"]
        # Split into lines at 80 chars, show up to 3 lines
        intent_lines = []
        while intent_text and len(intent_lines) < 3:
            if len(intent_text) <= 80:
                intent_lines.append(intent_text)
                break
            break_point = intent_text.rfind(' ', 0, 80)
            if break_point == -1:
                break_point = 80
            intent_lines.append(intent_text[:break_point])
            intent_text = intent_text[break_point:].lstrip()

        intent_section = f"{dim}    Intent\n"
        for intent_line in intent_lines:
            intent_section += f"    {intent_line}\n"
        intent_section = intent_section.rstrip("\n") + reset
        sections.append(intent_section)

    # Acceptance Criteria section (only in "detail" style)
    if output_style == "detail":
        criteria = card.get("criteria", [])
        if criteria:
            criteria_section = f"{dim}    Acceptance Criteria\n"
            for i, criterion in enumerate(criteria, start=1):
                checkbox = "✅" if criterion.get("met", False) else "⬜"
                text = criterion.get("text", "")
                criteria_section += f"    {checkbox} {i}. {text}\n"
            criteria_section = criteria_section.rstrip("\n") + reset
            sections.append(criteria_section)

    # Metadata section (persona, model) - show in "detail" style only
    if output_style == "detail":
        metadata_parts = []
        persona = card.get("persona")
        model = card.get("model")
        if persona and persona != "unassigned":
            metadata_parts.append(f"Persona: {persona}")
        if model:
            metadata_parts.append(f"Model: {model}")

        if metadata_parts:
            metadata_section = f"{dim}    {' · '.join(metadata_parts)}{reset}"
            sections.append(metadata_section)

    # Edit Files section (show in "detail" style only - removed "xml")
    if output_style == "detail":
        edit_files = card.get("editFiles") or card.get("writeFiles", [])
        if edit_files:
            files_section = f"{dim}    Edit Files\n"
            for f in sorted(edit_files):
                files_section += f"    {f}\n"
            files_section = files_section.rstrip("\n") + reset
            sections.append(files_section)

        # Read Files section (show in "detail" style only - removed "xml")
        read_files = card.get("readFiles", [])
        if read_files:
            files_section = f"{dim}    Read Files\n"
            for f in sorted(read_files):
                files_section += f"    {f}\n"
            files_section = files_section.rstrip("\n") + reset
            sections.append(files_section)

    # Join all sections with blank lines
    if sections:
        line += "\n\n" + "\n\n".join(sections)

    return line


def calculate_throughput_metrics(root: Path) -> dict:
    """Calculate throughput metrics for done cards.

    Returns dict with:
        - cards_per_hour: Cards completed in last 60 minutes
        - cards_today: Cards completed since midnight
        - cards_all_time: Total cards in done column
        - avg_lead_time_seconds: Average lead time in seconds (or None)
    """
    done_dir = root / "done"
    if not done_dir.exists():
        return {
            "cards_per_hour": 0,
            "cards_today": 0,
            "cards_all_time": 0,
            "avg_lead_time_seconds": None,
        }

    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)
    today_midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)

    cards_per_hour = 0
    cards_today = 0
    cards_all_time = 0
    lead_times = []

    for card_file in done_dir.glob("*.json"):
        try:
            card = read_card(card_file)
            cards_all_time += 1

            # Get completion timestamp
            updated_str = card.get("updated")
            if updated_str:
                updated = parse_iso(updated_str)
                if updated >= one_hour_ago:
                    cards_per_hour += 1
                if updated >= today_midnight:
                    cards_today += 1

            # Calculate lead time
            lead_time = calculate_lead_time(card)
            if lead_time is not None:
                lead_times.append(lead_time)

        except (json.JSONDecodeError, OSError, ValueError):
            continue

    avg_lead_time = sum(lead_times) / len(lead_times) if lead_times else None

    return {
        "cards_per_hour": cards_per_hour,
        "cards_today": cards_today,
        "cards_all_time": cards_all_time,
        "avg_lead_time_seconds": avg_lead_time,
    }


def cmd_list(args) -> None:
    """Show board overview with compact format."""
    root = get_root(args.root)

    # Check for watch state or args
    watch_state = getattr(args, '_watch_state', None)
    if watch_state:
        output_style = watch_state.output_style
        session_filter = watch_state.session_filter
        card_filter = watch_state.card_filter
    else:
        output_style = getattr(args, "output_style", "simple")
        session_filter = ""
        card_filter = ""

    # Column filtering
    explicit_columns = getattr(args, "column", None)
    if explicit_columns:
        columns_to_show = []
        for col_arg in explicit_columns:
            for col in col_arg.split(","):
                col = col.strip()
                if col not in COLUMNS:
                    print(f"Error: Invalid column '{col}'", file=sys.stderr)
                    sys.exit(1)
                if col not in columns_to_show:
                    columns_to_show.append(col)
        columns_to_show = [c for c in COLUMNS if c in columns_to_show]
    else:
        show_done = getattr(args, "show_done", False)
        show_canceled = getattr(args, "show_canceled", False)
        show_all = getattr(args, "show_all", False)
        if show_all:
            columns_to_show = COLUMNS
        elif show_done and show_canceled:
            columns_to_show = COLUMNS
        elif show_done:
            columns_to_show = [c for c in COLUMNS if c != "canceled"]
        elif show_canceled:
            columns_to_show = [c for c in COLUMNS if c != "done"]
        else:
            columns_to_show = [c for c in COLUMNS if c not in ["done", "canceled"]]

    # Date filters
    since = parse_date_filter(args.since) if getattr(args, "since", None) else None
    until = parse_date_filter(args.until) if getattr(args, "until", None) else None

    # Session filters
    current_session, hide_own, show_only_mine = resolve_session_filters(args)

    # Gather cards grouped by column (flat, no session grouping for XML)
    all_cards_by_column: dict[str, list[tuple[str, dict]]] = {col: [] for col in columns_to_show}
    # Also track by session for non-XML rendering
    my_cards: dict[str, list[tuple[str, dict]]] = {col: [] for col in columns_to_show}
    other_cards: dict[str, list[tuple[str, dict]]] = {col: [] for col in columns_to_show}

    for col in columns_to_show:
        for card_path in find_cards_in_column(root, col):
            try:
                card = read_card(card_path)
            except (json.JSONDecodeError, OSError):
                continue
            if not card_in_date_range(card, since, until):
                continue
            num = card_number(card_path)

            # Apply watch filters
            if card_filter and not num.startswith(card_filter):
                continue
            if session_filter:
                card_session = card.get("session", "")
                if not card_session.lower().startswith(session_filter.lower()):
                    continue

            # Add to flat list for XML
            all_cards_by_column[col].append((num, card))

            # Also add to session-grouped lists for non-XML
            if is_my_card(card, current_session):
                my_cards[col].append((num, card))
            else:
                other_cards[col].append((num, card))

    # XML output: compact format with mine/others session delineation
    if output_style == "xml":
        esc = html.escape

        # Get session for delineation
        session_arg = getattr(args, "session", None)

        # Build session attribute for board tag
        session_attr = f' session="{esc(session_arg)}"' if session_arg else ""
        print(f"<board{session_attr}>")

        # Determine which cards are mine vs others
        if session_arg:
            # Split cards by session ownership
            mine_cards = []
            others_cards = []
            for col in columns_to_show:
                for num, card in all_cards_by_column[col]:
                    card_session = card.get("session")
                    if card_session == session_arg:
                        mine_cards.append((num, card, col))
                    else:
                        others_cards.append((num, card, col))

            # Output <mine> section
            if mine_cards:
                print("<mine>")
                for num, card, col in mine_cards:
                    action = esc(card.get("action", ""))
                    edit_files = card.get("editFiles") or card.get("writeFiles", [])
                    read_files = card.get("readFiles", [])

                    parts = [f'<c n="{esc(num)}" s="{esc(col)}">']
                    parts.append(f"<a>{action}</a>")
                    if edit_files:
                        edit_str = esc(",".join(sorted(edit_files)))
                        parts.append(f"<e>{edit_str}</e>")
                    if read_files:
                        read_str = esc(",".join(sorted(read_files)))
                        parts.append(f"<r>{read_str}</r>")
                    parts.append("</c>")
                    print("".join(parts))
                print("</mine>")

            # Output <others> section
            if others_cards:
                print("<others>")
                for num, card, col in others_cards:
                    card_session = card.get("session", "")
                    action = esc(card.get("action", ""))
                    edit_files = card.get("editFiles") or card.get("writeFiles", [])
                    read_files = card.get("readFiles", [])

                    ses_attr = f' ses="{esc(card_session)}"' if card_session else ""
                    parts = [f'<c n="{esc(num)}"{ses_attr} s="{esc(col)}">']
                    parts.append(f"<a>{action}</a>")
                    if edit_files:
                        edit_str = esc(",".join(sorted(edit_files)))
                        parts.append(f"<e>{edit_str}</e>")
                    if read_files:
                        read_str = esc(",".join(sorted(read_files)))
                        parts.append(f"<r>{read_str}</r>")
                    parts.append("</c>")
                    print("".join(parts))
                print("</others>")
        else:
            # No session arg - treat all as mine
            has_cards = False
            for col in columns_to_show:
                cards = all_cards_by_column[col]
                if cards:
                    has_cards = True
                    break

            if has_cards:
                print("<mine>")
                for col in columns_to_show:
                    for num, card in all_cards_by_column[col]:
                        action = esc(card.get("action", ""))
                        edit_files = card.get("editFiles") or card.get("writeFiles", [])
                        read_files = card.get("readFiles", [])

                        parts = [f'<c n="{esc(num)}" s="{esc(col)}">']
                        parts.append(f"<a>{action}</a>")
                        if edit_files:
                            edit_str = esc(",".join(sorted(edit_files)))
                            parts.append(f"<e>{edit_str}</e>")
                        if read_files:
                            read_str = esc(",".join(sorted(read_files)))
                            parts.append(f"<r>{read_str}</r>")
                        parts.append("</c>")
                        print("".join(parts))
                print("</mine>")

        print("</board>")
        return

    # Non-XML output: session-grouped display
    print(f"KANBAN BOARD: {root}")
    print()

    if not hide_own:
        if current_session:
            print(f"=== Your Session ({current_session[:8]}) ===")
        else:
            print("=== Your Cards ===")
        print()

        for col in columns_to_show:
            cards = my_cards[col]
            print(f"{col.upper()} ({len(cards)})")
            if cards:
                for i, (num, card) in enumerate(cards):
                    print(format_card_line(card, num, output_style=output_style, is_first_card=(i == 0), column=col))
            else:
                print("  (empty)")
            print()

    if not show_only_mine and any(other_cards[col] for col in columns_to_show):
        print("=== Other Sessions ===")
        print()
        for col in columns_to_show:
            cards = other_cards[col]
            if cards:
                print(f"{col.upper()} ({len(cards)})")
                for i, (num, card) in enumerate(cards):
                    print(format_card_line(card, num, show_session=True, output_style=output_style, is_first_card=(i == 0), column=col))
                print()

    # Show metrics summary (not in XML mode)
    metrics = calculate_throughput_metrics(root)
    dim = "\033[2m"
    reset = "\033[0m"

    print(f"{dim}─── Metrics ───{reset}")
    throughput_parts = [
        f"{metrics['cards_per_hour']} cards/hr",
        f"{metrics['cards_today']} today",
        f"{metrics['cards_all_time']} all-time",
    ]
    print(f"{dim}Throughput: {' · '.join(throughput_parts)}{reset}")

    if metrics['avg_lead_time_seconds'] is not None:
        avg_lead_str = format_lead_time(metrics['avg_lead_time_seconds'])
        print(f"{dim}Avg Lead Time: {avg_lead_str}{reset}")


def cmd_todo(args) -> None:
    """Create card(s) in todo column from JSON input (pure verb - no view mode).

    Accepts either a single JSON object or an array of objects for bulk creation.
    """
    root = get_root(args.root)

    try:
        data = json.loads(args.json_data)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    session = args.session if hasattr(args, "session") and args.session else get_current_session_id()

    # Detect array vs object
    if isinstance(data, list):
        # Bulk creation: validate all cards first (fail fast)
        cards = []
        for i, card_data in enumerate(data):
            if not isinstance(card_data, dict):
                print(f"Error: Array element {i} must be a JSON object, got {type(card_data).__name__}", file=sys.stderr)
                sys.exit(1)
            card = validate_and_build_card(card_data, session)
            cards.append(card)

        # All validation passed — create all cards
        for card in cards:
            num = create_card_in_column(root, "todo", card)
            print(num)
    elif isinstance(data, dict):
        # Single card creation (existing behavior)
        card = validate_and_build_card(data, session)
        num = create_card_in_column(root, "todo", card)
        print(num)
    else:
        print(f"Error: JSON must be an object or array, got {type(data).__name__}", file=sys.stderr)
        sys.exit(1)


def cmd_review(args) -> None:
    """Move card to review column (pure verb - no view mode)."""
    root = get_root(args.root)
    card_path = find_card(root, args.card)
    card = read_card(card_path)
    num = card_number(card_path)

    card["updated"] = now_iso()
    write_card(card_path, card)

    target = root / "review" / card_path.name
    target.parent.mkdir(parents=True, exist_ok=True)
    card_path.rename(target)
    print(f"Moved: #{num} -> review/")


def cmd_done(args) -> None:
    """Move card to done column (pure verb - no view mode)."""
    root = get_root(args.root)
    card_path = find_card(root, args.card)
    card = read_card(card_path)
    num = card_number(card_path)

    # Block if acceptance criteria are unmet
    criteria = card.get("criteria", [])
    if criteria:
        unmet = [c for c in criteria if not c.get("met", False)]
        if unmet:
            print(f"🛑 Cannot complete card #{num} — {len(unmet)} of {len(criteria)} acceptance criteria unmet:", file=sys.stderr)
            for i, criterion in enumerate(criteria, start=1):
                if not criterion.get("met", False):
                    print(f"  ⬜ {i}. {criterion.get('text', '')}", file=sys.stderr)
            print(f"\nCheck items with: kanban criteria check {num} <n>", file=sys.stderr)
            sys.exit(1)

    # Append completion message to activity
    message = args.message if hasattr(args, "message") and args.message else "Completed"
    card["activity"].append({
        "timestamp": now_iso(),
        "message": message,
    })
    card["updated"] = now_iso()
    write_card(card_path, card)

    target = root / "done" / card_path.name
    target.parent.mkdir(parents=True, exist_ok=True)
    card_path.rename(target)
    print(f"Done: #{num} — {message}")


# =============================================================================
# Watch mode (reused from v1)
# =============================================================================

def _handle_normal_mode(state: WatchState, ch: str, refresh_event: Event, stop_event: Event) -> None:
    """Handle keypresses in normal mode."""
    if ch == '?':
        # Toggle between simple and detail
        if state.output_style == "simple":
            state.output_style = "detail"
        else:
            state.output_style = "simple"
        refresh_event.set()
    elif ch == '/':
        state.input_mode = "session"
        state.input_buffer = ""
        refresh_event.set()
    elif ch == '#':
        state.input_mode = "card"
        state.input_buffer = ""
        refresh_event.set()
    elif ch == 'q':
        stop_event.set()
        refresh_event.set()


def _handle_input_mode(state: WatchState, ch: str, refresh_event: Event) -> None:
    """Handle keypresses in input mode."""
    if ch == '\x1b':  # Escape
        # Clear filter based on current mode before clearing mode
        if state.input_mode == "session":
            state.session_filter = ""
        elif state.input_mode == "card":
            state.card_filter = ""
        state.input_mode = ""
        state.input_buffer = ""
        refresh_event.set()
    elif ch == '\r' or ch == '\n':  # Enter
        state.input_mode = ""
        refresh_event.set()
    elif ch == '\x7f' or ch == '\x08':  # Backspace/Delete
        if state.input_buffer:
            state.input_buffer = state.input_buffer[:-1]
            # Live filter update
            if state.input_mode == "session":
                state.session_filter = state.input_buffer
            elif state.input_mode == "card":
                state.card_filter = state.input_buffer
            refresh_event.set()
    elif ch.isprintable():
        state.input_buffer += ch
        # Live filter update
        if state.input_mode == "session":
            state.session_filter = state.input_buffer
        elif state.input_mode == "card":
            state.card_filter = state.input_buffer
        refresh_event.set()


def _input_thread(state: WatchState, refresh_event: Event, stop_event: Event) -> None:
    """Background thread for reading keyboard input."""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while not stop_event.is_set():
            # Check for input with timeout
            ready, _, _ = select.select([sys.stdin], [], [], 0.1)
            if ready:
                ch = sys.stdin.read(1)
                if state.input_mode:
                    _handle_input_mode(state, ch, refresh_event)
                else:
                    _handle_normal_mode(state, ch, refresh_event, stop_event)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _print_status_bar(state: WatchState) -> None:
    """Print status bar showing active toggles, filters, and input prompts."""
    dim = "\033[2m"
    reset = "\033[0m"

    if state.input_mode == "session":
        prompt = f"{dim}session: {state.input_buffer}_{reset}"
        print(prompt)
    elif state.input_mode == "card":
        prompt = f"{dim}card#: {state.input_buffer}_{reset}"
        print(prompt)
    else:
        # Show hints and active filters
        hints = f"{dim}[?]detail [/]session [#]card [q]quit{reset}"
        active_filters = []
        if state.output_style != "simple":
            active_filters.append(f"style:{state.output_style}")
        if state.session_filter:
            active_filters.append(f"session:{state.session_filter}")
        if state.card_filter:
            active_filters.append(f"card:{state.card_filter}")

        if active_filters:
            filters_str = f"{dim} | {' | '.join(active_filters)}{reset}"
            print(hints + filters_str)
        else:
            print(hints)


def _render_watch(args, command_func, state: WatchState, is_interactive: bool) -> None:
    """Render the watch view with optional status bar."""
    args._watch_state = state
    command_func(args)
    if is_interactive:
        print()
        _print_status_bar(state)


def watch_and_run(args, command_func) -> None:
    """Watch .kanban/ directory and re-run command on changes."""
    root = get_root(args.root)
    refresh_event = Event()
    stop_event = Event()
    state = WatchState()
    is_interactive = sys.stdin.isatty()

    class DebounceHandler(FileSystemEventHandler):
        def on_any_event(self, event):
            if event.is_directory:
                return
            is_json_event = event.src_path.endswith(".json")
            if hasattr(event, "dest_path"):
                is_json_event = is_json_event or event.dest_path.endswith(".json")
            if is_json_event:
                refresh_event.set()

    observer = Observer()
    observer.schedule(DebounceHandler(), str(root), recursive=True)
    observer.start()

    # Start input thread if interactive
    input_thread = None
    if is_interactive:
        input_thread = threading.Thread(
            target=_input_thread,
            args=(state, refresh_event, stop_event),
            daemon=True
        )
        input_thread.start()

    if is_interactive:
        print(f"Watching {root} for changes... (Press ? for help)")
        print()
    else:
        print(f"Watching {root} for changes... (Ctrl+C to exit)")
        print()

    try:
        _render_watch(args, command_func, state, is_interactive)
        while not stop_event.is_set():
            if refresh_event.wait(timeout=0.5):
                refresh_event.clear()
                time.sleep(0.1)  # Small debounce
                refresh_event.clear()
                print("\033[2J\033[H", end="", flush=True)
                try:
                    _render_watch(args, command_func, state, is_interactive)
                except Exception as e:
                    print(f"Error: {e}", file=sys.stderr)
                    if is_interactive:
                        print()
                        _print_status_bar(state)
    except KeyboardInterrupt:
        print("\nStopping watch mode...")
    finally:
        stop_event.set()
        observer.stop()
        observer.join()
        if input_thread:
            input_thread.join(timeout=1)
        # Safety net to restore terminal
        os.system('stty sane 2>/dev/null')


# =============================================================================
# Argparse setup
# =============================================================================

def add_session_flags(parser: argparse.ArgumentParser) -> None:
    """Add common session filtering flags to a parser."""
    parser.add_argument("--session", help="Filter by session ID")
    parser.add_argument("--only-mine", action="store_true", dest="only_mine", help="Show only current session's cards")
    parser.add_argument("--show-mine", action="store_true", dest="show_mine", help="Show mine (override KANBAN_HIDE_MINE)")
    parser.add_argument("--hide-mine", action="store_true", dest="hide_mine", help="Hide current session's cards")


def add_date_flags(parser: argparse.ArgumentParser) -> None:
    """Add common date filtering flags."""
    parser.add_argument("--since", help="Filter by date (today, yesterday, week, month, or ISO)")
    parser.add_argument("--until", help="Filter until date (ISO format)")


def main() -> None:
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument("--watch", action="store_true", help="Auto-refresh on .kanban/ changes")

    parser = argparse.ArgumentParser(
        description="Kanban CLI — JSON-based kanban board for agent coordination",
    )
    parser.add_argument("--root", help="Kanban root directory (or set KANBAN_ROOT)")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # --- init ---
    p_init = subparsers.add_parser("init", parents=[parent_parser], help="Create kanban board structure")
    p_init.add_argument("path", nargs="?", default=None, help="Board path")
    add_session_flags(p_init)

    # --- session-hook ---
    p_session_hook = subparsers.add_parser("session-hook", parents=[parent_parser], help="Handle SessionStart hook (reads JSON from stdin)")
    add_session_flags(p_session_hook)

    # --- do ---
    p_do = subparsers.add_parser("do", parents=[parent_parser], help="Create card(s) in doing from JSON")
    p_do.add_argument("json_data", help="JSON object or array of objects with action, intent, readFiles, editFiles")
    add_session_flags(p_do)

    # --- show ---
    p_show = subparsers.add_parser("show", parents=[parent_parser], help="Display card contents")
    p_show.add_argument("card", help="Card number")
    p_show.add_argument("--output-style", choices=["simple", "xml", "detail"], help="Output style: xml (structured XML for machine parsing)")
    add_session_flags(p_show)

    # --- cancel ---
    p_cancel = subparsers.add_parser("cancel", parents=[parent_parser], help="Move card to canceled column")
    p_cancel.add_argument("card", help="Card number")
    p_cancel.add_argument("reason", nargs="?", default=None, help="Optional cancellation reason")
    add_session_flags(p_cancel)

    # --- redo ---
    p_redo = subparsers.add_parser("redo", parents=[parent_parser], help="Move card from review back to doing")
    p_redo.add_argument("card", help="Card number")
    add_session_flags(p_redo)

    # --- defer ---
    p_defer = subparsers.add_parser("defer", parents=[parent_parser], help="Move card from doing/review back to todo")
    p_defer.add_argument("card", help="Card number")
    add_session_flags(p_defer)

    # --- start ---
    p_start = subparsers.add_parser("start", parents=[parent_parser], help="Move card(s) from todo to doing")
    p_start.add_argument("card", nargs="+", help="Card number(s)")
    add_session_flags(p_start)

    # --- criteria (with subcommands) ---
    p_criteria = subparsers.add_parser("criteria", parents=[parent_parser], help="Manage acceptance criteria", aliases=["ac"])
    criteria_subparsers = p_criteria.add_subparsers(dest="criteria_command", help="Criteria subcommands")

    p_criteria_add = criteria_subparsers.add_parser("add", parents=[parent_parser], help="Add acceptance criterion")
    p_criteria_add.add_argument("card", help="Card number")
    p_criteria_add.add_argument("text", help="Criterion text")
    add_session_flags(p_criteria_add)

    p_criteria_remove = criteria_subparsers.add_parser("remove", parents=[parent_parser], help="Remove acceptance criterion")
    p_criteria_remove.add_argument("card", help="Card number")
    p_criteria_remove.add_argument("n", type=int, help="Criterion number (1-indexed)")
    p_criteria_remove.add_argument("reason", help="Reason for removal")
    add_session_flags(p_criteria_remove)

    p_criteria_check = criteria_subparsers.add_parser("check", parents=[parent_parser], help="Mark criterion as met")
    p_criteria_check.add_argument("card", help="Card number")
    p_criteria_check.add_argument("n", nargs="+", help="Criterion index(es) (1-based) or text prefix(es)")
    add_session_flags(p_criteria_check)

    p_criteria_uncheck = criteria_subparsers.add_parser("uncheck", parents=[parent_parser], help="Mark criterion as unmet")
    p_criteria_uncheck.add_argument("card", help="Card number")
    p_criteria_uncheck.add_argument("n", help="Criterion index (1-based) or text prefix")
    add_session_flags(p_criteria_uncheck)

    # --- list / ls ---
    for alias in ["list", "ls"]:
        p_list = subparsers.add_parser(alias, parents=[parent_parser], help="Show board overview")
        p_list.add_argument("--column", action="append", help="Filter column(s)")
        p_list.add_argument("--show-done", action="store_true", help="Include done")
        p_list.add_argument("--show-canceled", action="store_true", help="Include canceled")
        p_list.add_argument("--show-all", action="store_true", help="Include done + canceled")
        p_list.add_argument("--output-style", choices=["simple", "xml", "detail"], default="simple", help="Output style: simple (title only), xml (structured XML), detail (everything)")
        add_session_flags(p_list)
        add_date_flags(p_list)

    # --- Pure verbs: todo, review, done ---
    p_todo = subparsers.add_parser("todo", parents=[parent_parser], help="Create card(s) in todo from JSON")
    p_todo.add_argument("json_data", help="JSON object or array of objects with action, intent, readFiles, editFiles")
    add_session_flags(p_todo)

    p_review = subparsers.add_parser("review", parents=[parent_parser], help="Move card to review")
    p_review.add_argument("card", help="Card number")
    add_session_flags(p_review)

    p_done = subparsers.add_parser("done", parents=[parent_parser], help="Move card to done")
    p_done.add_argument("card", help="Card number")
    p_done.add_argument("message", nargs="?", default=None, help="Completion message")
    add_session_flags(p_done)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {
        "init": cmd_init,
        "session-hook": cmd_session_hook,
        "do": cmd_do,
        "todo": cmd_todo,
        "review": cmd_review,
        "done": cmd_done,
        "cancel": cmd_cancel,
        "redo": cmd_redo,
        "defer": cmd_defer,
        "start": cmd_start,
        "list": cmd_list,
        "ls": cmd_list,
        "show": cmd_show,
        "criteria": cmd_criteria_dispatch,
        "ac": cmd_criteria_dispatch,
    }

    command_func = commands[args.command]

    if getattr(args, "watch", False):
        watch_and_run(args, command_func)
    else:
        command_func(args)


if __name__ == "__main__":
    main()
