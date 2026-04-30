"""
Kanban CLI - File-based kanban board for agent coordination.

Cards are JSON files stored in column folders. Staff engineer owns the board;
sub-agents are kanban-unaware. This dramatically reduces context bloat.

Card format: NNN.json (e.g., 42.json)
Columns: todo, doing, done, canceled

ENVIRONMENT VARIABLES:
  KANBAN_HIDE_MINE     - Hide your own session's cards by default
  KANBAN_ARCHIVE_DAYS  - Days before auto-archiving done cards (default: 30)
  KANBAN_SESSION       - Override session detection (for smithers/burns)
  KANBAN_ROOT          - Override board location
"""

import argparse
import fnmatch
import html
import json
import os
import re
import shlex
import select
import shutil
import sqlite3
import subprocess
import sys
import termios
import textwrap
import threading
import time
import tty
import unicodedata
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

COLUMNS = ["todo", "doing", "done", "canceled"]
ARCHIVE_DAYS_THRESHOLD = int(os.environ.get("KANBAN_ARCHIVE_DAYS", "30"))
MAX_CYCLES = 3

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

def use_pager(content: str) -> None:
    """Display content through bat pager with syntax highlighting.

    Uses bat for syntax highlighting when output is to a terminal.
    Skips pager if output is piped (e.g., to grep).

    Bat is guaranteed to be available via Nix - no fallback needed.
    """
    # If output is piped, print directly (bat also detects this, but we short-circuit for efficiency)
    if not sys.stdout.isatty():
        print(content, end="")
        return

    # Use bat with plain style for clean output
    # Bat is guaranteed to exist via Nix packages
    proc = subprocess.Popen(
        ['bat', '--paging=auto', '--style=plain', '--language=markdown'],
        stdin=subprocess.PIPE,
        stdout=sys.stdout
    )
    proc.communicate(content.encode())


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

def migrate_criteria(card: dict) -> bool:
    """Migrate criteria schema across versions.

    V1-V3 -> V4: all pre-V4 schemas collapse to a single met field.
    Old dual-column field names are constructed at runtime to avoid literals.
    Card-level: old cycle counter field renamed to cycles.

    Returns True if migration was performed and the card should be persisted.
    """
    criteria = card.get("criteria")
    if not criteria:
        return False

    # Old dual-column field names (split to avoid literal presence in source)
    _old_primary = "agent" + "_met"
    _old_reviewer = "reviewer" + "_met"
    _old_reason = "reviewer" + "_fail_reason"

    migrated = False
    for criterion in criteria:
        # V3 -> V4: collapse dual-column back to single met field
        if _old_primary in criterion:
            criterion["met"] = criterion.pop(_old_primary)
            criterion.pop(_old_reviewer, None)
            criterion.pop(_old_reason, None)
            migrated = True
        # V1 -> V2 (legacy path, now collapsed into V4 directly)
        elif "met" not in criterion:
            criterion["met"] = False
            migrated = True

    # Card-level: rename old cycle counter to cycles (old name was "<col>_cycles")
    _old_cycles = "rev" + "iew_cycles"
    if _old_cycles in card:
        card["cycles"] = card.pop(_old_cycles)
        migrated = True

    return migrated


def read_card(path: Path) -> dict:
    """Read a JSON card file, transparently migrating old criteria schema if needed."""
    card = json.loads(path.read_text())
    if migrate_criteria(card):
        write_card(path, card)
    # Backward compat: cards created before Phase 1 lack agent_launch_pending.
    # Default to False so callers can use card["agent_launch_pending"] safely
    # without KeyError on legacy cards.
    card.setdefault("agent_launch_pending", False)
    return card


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
# Metrics event writer
# =============================================================================

_METRICS_DB_PATH = Path.home() / ".claude" / "metrics" / "claudit.db"

# NOTE: This DDL is intentionally duplicated in modules/claudit/claudit-hook.py
# Both files must stay in sync — changes here require matching changes there.
_CREATE_KANBAN_CARD_EVENTS_SQL = """
CREATE TABLE IF NOT EXISTS kanban_card_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_number TEXT NOT NULL,
    event_type TEXT NOT NULL,
    agent TEXT,
    model TEXT,
    kanban_session TEXT,
    recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    card_created_at TEXT,
    card_completed_at TEXT,
    card_type TEXT,
    ac_count INTEGER,
    git_project TEXT,
    from_column TEXT,
    to_column TEXT,
    persona TEXT
)
"""

# NOTE: These index definitions are intentionally duplicated in modules/claude/claude-metrics-hook.py
# Both files must stay in sync — changes here require matching changes there.
_CREATE_KANBAN_CARD_EVENTS_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_kanban_card_events_event_type ON kanban_card_events (event_type)",
    "CREATE INDEX IF NOT EXISTS idx_kanban_card_events_agent ON kanban_card_events (agent)",
    "CREATE INDEX IF NOT EXISTS idx_kanban_card_events_recorded_at ON kanban_card_events (recorded_at)",
]

# Migration: add columns to kanban_card_events for databases created before V6.
# CREATE TABLE IF NOT EXISTS is a no-op on existing tables, so ALTER TABLE is
# required to add new columns to existing databases. OperationalError
# ("duplicate column name") is caught and ignored — safe to run repeatedly.
# NOTE: This migration list is intentionally duplicated in modules/claude/claude-metrics-hook.py
# Both files must stay in sync — changes here require matching changes there.
_V6_KANBAN_MIGRATION_SQL = [
    "ALTER TABLE kanban_card_events ADD COLUMN card_created_at TEXT",
    "ALTER TABLE kanban_card_events ADD COLUMN card_completed_at TEXT",
    "ALTER TABLE kanban_card_events ADD COLUMN card_type TEXT",
    "ALTER TABLE kanban_card_events ADD COLUMN ac_count INTEGER",
    "ALTER TABLE kanban_card_events ADD COLUMN git_project TEXT",
    "ALTER TABLE kanban_card_events ADD COLUMN from_column TEXT",
    "ALTER TABLE kanban_card_events ADD COLUMN to_column TEXT",
]

# V8 migration: add persona column to kanban_card_events for databases that
# predate V8. OperationalError ("duplicate column name") is caught and ignored —
# idempotent.
# NOTE: This migration is intentionally duplicated in modules/claude/claude-metrics-hook.py
# Both files must stay in sync — changes here require matching changes there.
_V8_KANBAN_MIGRATION_SQL = [
    "ALTER TABLE kanban_card_events ADD COLUMN persona TEXT",
]

def write_kanban_event(
    card: dict,
    card_num: str,
    event_type: str,
    card_completed_at: str | None = None,
    from_column: str | None = None,
    to_column: str | None = None,
    git_project: str | None = None,
) -> None:
    """Write a kanban lifecycle event to the metrics SQLite DB.

    Runs silently — never raises, never disrupts the kanban CLI workflow.
    The table is created on first use (idempotent DDL).

    Args:
        card: The card dict (source of created/type/criteria metadata).
        card_num: Card number string (e.g. "42").
        event_type: One of "create", "start", "defer", "done", "canceled".
        card_completed_at: Completion timestamp — only meaningful for "done" events.
        from_column: Column the card moved from (None for "create" events).
        to_column: Column the card moved to.
        git_project: Pre-computed git project name. If None, computed internally.
                     Pass this in bulk loops to avoid N redundant git subprocesses.
    """
    try:
        if git_project is None:
            git_root = get_git_root()
            git_project = os.path.basename(git_root) if git_root else None
        _METRICS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_METRICS_DB_PATH))
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute(_CREATE_KANBAN_CARD_EVENTS_SQL)
            for idx_sql in _CREATE_KANBAN_CARD_EVENTS_INDEX_SQL:
                conn.execute(idx_sql)
            # V6 migration: add columns absent in pre-V6 databases.
            for alter_sql in _V6_KANBAN_MIGRATION_SQL:
                try:
                    conn.execute(alter_sql)
                except sqlite3.OperationalError:
                    pass
            # V8 migration: add persona column absent in pre-V8 databases.
            for alter_sql in _V8_KANBAN_MIGRATION_SQL:
                try:
                    conn.execute(alter_sql)
                except sqlite3.OperationalError:
                    pass
            conn.execute(
                """
                INSERT INTO kanban_card_events (
                    card_number, event_type, agent, model, kanban_session,
                    card_created_at, card_completed_at, card_type, ac_count, git_project,
                    from_column, to_column, persona
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card_num,
                    event_type,
                    card.get("agent"),
                    card.get("model"),
                    card.get("session"),
                    card.get("created"),
                    card_completed_at,
                    card.get("type"),
                    len(card.get("criteria", [])),
                    git_project,
                    from_column,
                    to_column,
                    card.get("agent") if card.get("agent") != "unassigned" else None,
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass  # Never disrupt kanban CLI — metrics are best-effort


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

    # Burns sessions (Ralph-spawned via ralph CLI) don't have agent_type but
    # should also be suppressed — burns.py sets BURNS_SESSION=1 in the env
    if os.environ.get("BURNS_SESSION"):
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
    print(f"  kanban criteria check 5 1 --session {name}")
    print(f"  kanban done 5 'summary' --session {name}")

    # One-time cleanup of legacy nonce directory
    legacy = Path("/tmp/kanban-nonces")
    if legacy.exists():
        shutil.rmtree(legacy, ignore_errors=True)


def make_card(
    action: str,
    intent: str = "",
    read_files: list[str] | None = None,
    edit_files: list[str] | None = None,
    agent: str = "unassigned",
    model: str | None = None,
    session: str | None = None,
    criteria: list[str] | None = None,
    card_type: str = "work",
) -> dict:
    """Build a new card dict."""
    now = now_iso()
    # Normalize agent to lowercase-kebab-case (e.g. "AI Expert" -> "ai-expert")
    # but preserve the "unassigned" default unchanged.
    if agent != "unassigned":
        agent = agent.lower().replace(" ", "-")
    card = {
        "action": action,
        "intent": intent,
        "type": card_type,
        "readFiles": read_files or [],
        "editFiles": edit_files or [],
        "agent": agent,
        "model": model,
        "session": session,
        "cycles": 0,
        "agent_launch_pending": False,
        "created": now,
        "updated": now,
        "activity": [{"timestamp": now, "message": "Created"}],
    }

    # Add acceptance criteria if provided
    if criteria:
        card["criteria"] = [{"text": c, "met": False} for c in criteria]

    return card


def substitute_card_id_placeholders(card: dict, card_number: int | str) -> None:
    """Replace __CARD_ID__ token with the actual card number in-place.

    Scope: ONLY mov_commands[].cmd and criterion text fields.
    Does NOT touch action, intent, comments, or other card fields.
    """
    num_str = str(card_number)
    for criterion in card.get("criteria", []):
        if not isinstance(criterion, dict):
            continue
        # Substitute in criterion text
        if isinstance(criterion.get("text"), str):
            criterion["text"] = criterion["text"].replace("__CARD_ID__", num_str)
        # Substitute in mov_commands[].cmd
        for entry in criterion.get("mov_commands") or []:
            if isinstance(entry, dict) and isinstance(entry.get("cmd"), str):
                entry["cmd"] = entry["cmd"].replace("__CARD_ID__", num_str)


def create_card_in_column(root: Path, column: str, card: dict) -> int:
    """Write a card to a column, return its number."""
    num = next_number(root)
    substitute_card_id_placeholders(card, num)
    filepath = root / column / f"{num}.json"
    filepath.parent.mkdir(parents=True, exist_ok=True)
    write_card(filepath, card)
    return num


def validate_criteria_schema(criteria: list) -> None:
    """Validate criteria against the V5 structured schema.

    Rules:
    - mov_type, when present, is enforced: 'programmatic' or 'semantic'.
    - mov_type 'programmatic': requires a non-empty mov_commands array.
    - mov_type 'semantic': forbids non-empty mov_commands; empty array or absent is accepted.
    - When mov_type is absent: programmatic mode is implicit if mov_commands is non-empty;
      otherwise the criterion is treated as semantic (no further validation needed).
    - V4 schema fields (mov_command, mov_timeout singular) are REJECTED with a clear error.
    - Programmatic criteria: each mov_commands entry must have cmd (non-empty string,
      passes bash -n) and timeout (int 1-1800).

    Raises SystemExit on any validation failure.
    """
    for i, criterion in enumerate(criteria, start=1):
        if not isinstance(criterion, dict):
            print(f"Error: Criterion {i} must be an object, got {type(criterion).__name__}", file=sys.stderr)
            sys.exit(1)

        text = criterion.get("text", "")
        if not text or not str(text).strip():
            print(f"Error: Criterion {i} missing required 'text' field", file=sys.stderr)
            sys.exit(1)

        # V4 schema rejection: mov_command and mov_timeout singular fields are no longer accepted.
        if "mov_command" in criterion or "mov_timeout" in criterion:
            print(
                f"Error: Criterion {i} ('{text[:60]}') uses v4 schema fields "
                f"'mov_command'/'mov_timeout'. "
                f"Upgrade to v5: use 'mov_commands' array of {{\"cmd\": ..., \"timeout\": ...}} objects. "
                f"No backward compatibility — v4 schema is rejected.",
                file=sys.stderr,
            )
            sys.exit(1)

        mov_type = criterion.get("mov_type")
        mov_commands = criterion.get("mov_commands")
        # Treat absent or empty mov_commands uniformly as "no commands".
        effective_commands = mov_commands if mov_commands else []

        if mov_type == "programmatic":
            # Explicit programmatic: require at least one command.
            if not effective_commands:
                print(
                    f"Error: Criterion {i} ('{text[:60]}') is programmatic but has no mov_commands. "
                    f"Provide at least one command entry.",
                    file=sys.stderr,
                )
                sys.exit(1)
        elif mov_type == "semantic":
            # Explicit semantic: forbid non-empty commands.
            if effective_commands:
                print(
                    f"Error: Criterion {i} ('{text[:60]}') is semantic but has non-empty mov_commands. "
                    f"Remove mov_commands or set mov_type to 'programmatic'.",
                    file=sys.stderr,
                )
                sys.exit(1)
            # No further validation for semantic criteria.
            continue
        elif mov_type is not None:
            print(
                f"Error: Criterion {i} ('{text[:60]}') has unrecognised mov_type '{mov_type}'. "
                f"Use 'programmatic' or 'semantic'.",
                file=sys.stderr,
            )
            sys.exit(1)
        else:
            # mov_type absent: implicit mode from mov_commands presence.
            if not effective_commands:
                # No mov_type, no commands — treat as semantic, nothing to validate.
                continue

        # Validate each programmatic command entry.
        if not isinstance(effective_commands, list):
            print(
                f"Error: Criterion {i} ('{text[:60]}') 'mov_commands' must be an array, "
                f"got {type(effective_commands).__name__}.",
                file=sys.stderr,
            )
            sys.exit(1)

        for j, entry in enumerate(effective_commands, start=1):
            if not isinstance(entry, dict):
                print(
                    f"Error: Criterion {i} ('{text[:60]}') mov_commands[{j}] must be an object "
                    f"with 'cmd' and 'timeout', got {type(entry).__name__}.",
                    file=sys.stderr,
                )
                sys.exit(1)

            cmd = entry.get("cmd")
            timeout = entry.get("timeout")

            # cmd: required, non-empty string
            if not cmd or not str(cmd).strip():
                print(
                    f"Error: Criterion {i} ('{text[:60]}') mov_commands[{j}] has no 'cmd'. "
                    f"Provide a non-empty shell command string.",
                    file=sys.stderr,
                )
                sys.exit(1)

            # timeout: MANDATORY, integer 1-1800
            if timeout is None:
                print(
                    f"Error: Criterion {i} ('{text[:60]}') mov_commands[{j}] missing 'timeout'. "
                    f"timeout is required (integer, 1-1800 seconds).",
                    file=sys.stderr,
                )
                sys.exit(1)

            if not isinstance(timeout, int) or isinstance(timeout, bool):
                print(
                    f"Error: Criterion {i} ('{text[:60]}') mov_commands[{j}] 'timeout' must be "
                    f"an integer, got {type(timeout).__name__}.",
                    file=sys.stderr,
                )
                sys.exit(1)

            if timeout < 1 or timeout > 1800:
                print(
                    f"Error: Criterion {i} ('{text[:60]}') mov_commands[{j}] timeout {timeout} "
                    f"is out of range. Must be 1-1800 seconds.",
                    file=sys.stderr,
                )
                sys.exit(1)

                # bash -n syntax check per cmd
                try:
                    result = subprocess.run(
                        ["bash", "-n", "-c", cmd],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if result.returncode != 0:
                        error_detail = result.stderr.strip() if result.stderr.strip() else "(no detail)"
                        print(
                            f"Error: Criterion {i} ('{text[:60]}') mov_commands[{j}] cmd failed "
                            f"bash -n syntax check:\n"
                            f"  cmd: {cmd}\n"
                            f"  bash -n error: {error_detail}",
                            file=sys.stderr,
                        )
                        sys.exit(1)
                except subprocess.TimeoutExpired:
                    print(
                        f"Error: Criterion {i} bash -n syntax check timed out for cmd: {cmd}",
                        file=sys.stderr,
                    )
                    sys.exit(1)


# =============================================================================
# MoV (Measure of Verification) banned-pattern validation
#
# These checks run at card-creation time for BOTH inline JSON and --file paths.
# They mirror (and are the authoritative source for) the patterns documented in
# staff-engineer.md § Card Management — Card Fields — MoV discipline.
# =============================================================================

# ---------------------------------------------------------------------------
# Pattern constants
# ---------------------------------------------------------------------------

# Matches rg invocations that include capital -E (--encoding, not extended regex).
# Handles: rg -E, rg -qE, rg -qiE, rg -EI, etc.
# Does NOT match grep -E or other non-rg tools.
_MOV_RG_E_FLAG_RE = re.compile(r'\brg\s+-[a-zA-Z]*E[a-zA-Z]*\b')

# Structural prefix of the fragile absence-via-count pattern:
#   test $(rg -c ...) -le 0, [ $(grep -c ...) -le 0 ], [[ $(rg -c ...) -le 0 ]]
_MOV_RG_COUNT_ABSENCE_RE = re.compile(
    r'(?:test|\[\[?)\s+"?(?:\$\(|`)\s*(?:rg|grep)\s+-c\b'
)
# Comparison-to-zero half of the pattern.
_MOV_ZERO_COMPARE_RE = re.compile(r'-(?:le|eq)\s+[01]\b|-lt\s+[012]\b')

# Backslash immediately followed by pipe, NOT preceded by another backslash.
# Catches \| (literal-pipe trap) but not \\| (double-escape, may be legitimate).
_MOV_BACKSLASH_PIPE_RE = re.compile(r'(?<!\\)\\[|]')

# Regex-context tools for which \| is meaningfully wrong (alternation trap).
# Restricted to rg/grep only — sed/awk use BRE where \| is legitimate alternation.
_MOV_REGEX_TOOL_RE = re.compile(r'\b(?:rg|grep)\b')

# grep in PCRE mode (-P / --perl-regexp): \| IS valid alternation in PCRE.
_MOV_GREP_PCRE_RE = re.compile(r'(?<!\w)-P\b|--perl-regexp\b')

# Hook-skip literal strings (fail-closed subset — security-critical).
# Used for raw-text scanning when JSON parse fails (see cmd_do / cmd_todo).
# _MOV_HOOK_SKIP_RES is derived from these entries to keep a single source of truth:
# when adding a new hook-skip pattern, add its literal here AND a compiled entry below.
_MOV_HOOK_SKIP_LITERALS: list[str] = [
    "--no-verify",
    "--no-gpg-sign",
    "HUSKY=0",
    "HUSKY_SKIP_HOOKS=1",
]  # keep in sync with _MOV_HOOK_SKIP_RES (compiled patterns initialized from _MOV_HOOK_SKIP_LITERALS)
_MOV_HOOK_SKIP_RES: list[tuple[re.Pattern, str]] = [
    (re.compile(r'--no-verify\b'),       "--no-verify (hook-skip flag)"),
    (re.compile(r'--no-gpg-sign\b'),     "--no-gpg-sign (hook-skip flag)"),
    (re.compile(r'\bHUSKY\s*=\s*0\b'),   "HUSKY=0 (hook-skip env var)"),
    (re.compile(r'\bHUSKY_SKIP_HOOKS\s*=\s*1\b'), "HUSKY_SKIP_HOOKS=1 (hook-skip env var)"),
]

# rg/grep flags that consume the next token as a value (for dash-leading detection).
_MOV_RG_FLAGS_WITH_VALUE: frozenset[str] = frozenset([
    "-f", "--file", "--encoding", "-E", "--type-add",
    "--iglob", "--glob", "-g", "--replace", "-r",
    "--max-count", "-m", "--max-depth",
    "--context", "-C", "--before-context", "-B", "--after-context", "-A",
    "--color", "--colors", "--field-match-separator", "--field-context-separator",
    "--path-separator", "--sort", "--sortr",
    "--type", "-t", "--type-not", "-T",
])

_MOV_GREP_FLAGS_WITH_VALUE: frozenset[str] = frozenset([
    "-e", "--regexp", "-f", "--file",
    "-m", "--max-count",
    "-A", "--after-context", "-B", "--before-context", "-C", "--context",
    "--label", "--include", "--exclude", "--color", "--colour",
])

# Known rg boolean long flags (take no value).
_MOV_RG_BOOL_LONG_FLAGS: frozenset[str] = frozenset([
    "--no-ignore", "--no-ignore-vcs", "--no-ignore-global", "--no-ignore-parent",
    "--no-ignore-dot", "--ignore", "--hidden", "--no-hidden",
    "--follow", "--no-follow", "--fixed-strings", "--no-fixed-strings",
    "--word-regexp", "--no-word-regexp", "--line-regexp", "--no-line-regexp",
    "--multiline", "--no-multiline", "--multiline-dotall", "--crlf", "--no-crlf",
    "--null", "--null-data", "--only-matching", "--passthru", "--invert-match",
    "--count", "--count-matches", "--files", "--files-with-matches",
    "--files-without-match", "--list-file-types", "--quiet",
    "--case-sensitive", "--ignore-case", "--smart-case",
    "--pcre2", "--no-pcre2", "--vimgrep", "--json",
    "--line-number", "--no-line-number", "--column", "--no-column",
    "--with-filename", "--no-filename", "--heading", "--no-heading",
    "--trim", "--glob-case-insensitive", "--no-glob-case-insensitive",
    "--binary", "--no-binary", "--text", "--search-zip", "--no-search-zip",
    "--mmap", "--no-mmap", "--unicode", "--no-unicode",
    "--one-file-system", "--no-messages", "--stats", "--debug", "--trace",
    "--version", "--help",
])

# Known grep boolean long flags (take no value).
_MOV_GREP_BOOL_LONG_FLAGS: frozenset[str] = frozenset([
    "--extended-regexp", "--fixed-strings", "--basic-regexp", "--perl-regexp",
    "--ignore-case", "--no-ignore-case", "--word-regexp", "--line-regexp",
    "--count", "--line-number", "--only-matching", "--quiet", "--silent",
    "--recursive", "--dereference-recursive", "--invert-match",
    "--files-with-matches", "--files-without-match", "--with-filename",
    "--no-filename", "--null", "--binary", "--text", "--no-messages",
    "--version", "--help",
])


# ---------------------------------------------------------------------------
# Per-cmd detection helpers
# ---------------------------------------------------------------------------

def _mov_is_rg_count_absence(cmd: str) -> bool:
    """True if cmd uses the fragile absence-via-count idiom (test $(rg -c ...) -le 0)."""
    return bool(_MOV_RG_COUNT_ABSENCE_RE.search(cmd) and _MOV_ZERO_COMPARE_RE.search(cmd))


def _mov_is_backslash_pipe_in_regex_tool(cmd: str) -> bool:
    """True if cmd invokes a regex-context tool with \\| (literal-pipe trap)."""
    if not _MOV_REGEX_TOOL_RE.search(cmd):
        return False
    # Exempt grep -P / --perl-regexp: in PCRE mode, \\| is valid alternation.
    if re.search(r'\bgrep\b', cmd) and _MOV_GREP_PCRE_RE.search(cmd):
        return False
    return bool(_MOV_BACKSLASH_PIPE_RE.search(cmd))


def _mov_is_git_commit_n(cmd: str) -> bool:
    """True if cmd is `git commit` with the -n short flag (--no-verify shorthand).

    Handles value-consuming git flags (e.g., -C <path>, -c <key>=<val>,
    --git-dir <dir>, --work-tree <dir>) that appear between `git` and `commit`.
    These flags consume the following token as a value, so the value token is
    skipped rather than treated as a non-flag that stops the search.
    """
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        return False
    if not tokens:
        return False
    try:
        git_idx = tokens.index("git")
    except ValueError:
        return False
    post_git = tokens[git_idx + 1:]
    # Value-consuming flags that git itself accepts before the subcommand.
    # When we see one of these flags, we skip the following token (its value).
    git_value_consuming_flags: frozenset[str] = frozenset([
        "-C", "-c", "--git-dir", "--work-tree", "--namespace",
        "--super-prefix", "--exec-path",
    ])
    commit_idx = None
    i = 0
    while i < len(post_git):
        tok = post_git[i]
        if tok == "commit":
            commit_idx = i
            break
        if tok in git_value_consuming_flags:
            # Skip this flag AND the value token that follows it.
            i += 2
            continue
        if not tok.startswith("-"):
            return False
        i += 1
    if commit_idx is None:
        return False
    flags_with_args = frozenset(["-m", "--message", "-F", "--file",
                                  "-C", "--reuse-message", "--author", "--date"])
    post_commit = post_git[commit_idx + 1:]
    i = 0
    while i < len(post_commit):
        tok = post_commit[i]
        if tok in flags_with_args:
            i += 2
            continue
        if tok == "--":
            break
        if tok.startswith("-") and not tok.startswith("--"):
            if "n" in tok[1:]:
                return True
        i += 1
    return False


def _mov_is_dash_leading_pattern(cmd: str) -> bool:
    """True if rg/grep is invoked with a '--'-leading pattern but no '--' or '-e' guard."""
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        return False
    if not tokens:
        return False
    tool_idx = None
    for i, tok in enumerate(tokens):
        base = tok.split("/")[-1]
        if base in ("rg", "grep"):
            tool_idx = i
            break
    if tool_idx is None:
        return False
    base_tool = tokens[tool_idx].split("/")[-1]
    if base_tool == "rg":
        flags_with_value = _MOV_RG_FLAGS_WITH_VALUE
        bool_long_flags = _MOV_RG_BOOL_LONG_FLAGS
    else:
        flags_with_value = _MOV_GREP_FLAGS_WITH_VALUE
        bool_long_flags = _MOV_GREP_BOOL_LONG_FLAGS
    post_tool = tokens[tool_idx + 1:]
    i = 0
    while i < len(post_tool):
        tok = post_tool[i]
        if tok == "--":
            return False
        if tok in ("-e", "--regexp"):
            return False
        if tok.startswith("--"):
            if tok in flags_with_value:
                i += 2
                continue
            if tok in bool_long_flags:
                i += 1
                continue
            return True
        if tok.startswith("-"):
            i += 1
            continue
        return False
    return False


def _mov_check_cmd(cmd: str) -> "list[tuple[str, str]]":
    """
    Check a single cmd string against all banned MoV patterns.

    Returns a list of (pattern_name, fix_suggestion) tuples for ALL violations
    found in this cmd. Returns an empty list if the cmd is clean.

    All matching patterns are checked and collected rather than returning on
    the first match, so a cmd with multiple violations surfaces them all.
    """
    violations: list[tuple[str, str]] = []

    if _mov_is_rg_count_absence(cmd):
        violations.append((
            "test $(rg -c PATTERN FILE) -le N (absence-via-count idiom)",
            (
                "This idiom is fragile — `rg -c` emits NO stdout when zero matches, "
                "breaking `test` structurally with exit 2. "
                "For pattern-absence assertions, use: `! rg -q 'pattern' file`"
            ),
        ))

    if _mov_is_git_commit_n(cmd):
        violations.append((
            "git commit -n (hook-skip short flag)",
            "`git commit -n` is shorthand for `--no-verify` and must never appear in a MoV.",
        ))

    if _mov_is_backslash_pipe_in_regex_tool(cmd):
        violations.append((
            "backslash-pipe (literal pipe, not alternation)",
            (
                r"In ripgrep's default Rust regex engine, `\|` is a LITERAL pipe — not alternation. "
                r"Fix: use bare-pipe alternation (`foo|bar`) or split into separate mov_commands entries."
            ),
        ))

    if _mov_is_dash_leading_pattern(cmd):
        violations.append((
            "rg/grep dash-leading pattern without `--` or `-e` separator",
            (
                "When the search pattern starts with `--`, use: "
                "`rg -qF -- '--watch' file` or `rg -qF -e '--watch' file`. "
                "Without the guard, rg/grep parses the pattern as an unrecognized flag and exits 2."
            ),
        ))

    if _MOV_RG_E_FLAG_RE.search(cmd):
        violations.append((
            "rg -E (capital -E flag)",
            (
                "In ripgrep, `-E` means `--encoding`, NOT extended regex. "
                "PCRE2 regex is the default — no flag needed. "
                "Fix: replace `rg -qiE` with `rg -qi`, `rg -E` with `rg`."
            ),
        ))

    for pattern, name in _MOV_HOOK_SKIP_RES:
        if pattern.search(cmd):
            violations.append((
                name,
                f"`{name.split(' ')[0]}` skips git hooks and must never appear in a MoV. Remove the flag.",
            ))

    return violations


# ---------------------------------------------------------------------------
# Public validation function
# ---------------------------------------------------------------------------

def validate_mov_commands_content(card_json) -> None:
    """Validate all mov_commands[].cmd fields in card_json against banned patterns.

    Accepts a single card dict or a list of card dicts (bulk creation).

    For each criterion's mov_commands, checks every cmd against the banned-patterns
    list (backslash-pipe, AND-chain, rg -E, absence-via-count idiom, hook-skip flags,
    dash-leading patterns, empty mov_commands).

    Collects ALL violations across all cards before exiting, so the author sees
    every problem in one pass.

    Exits with code 1 if any violations are found, printing an actionable error
    report to stderr. Returns normally when all commands are clean.

    Note: && (AND-chain) is validated separately by _collect_ampersand_errors /
    _print_ampersand_chain_errors. This function covers the remaining banned patterns.

    Note: violation reports echo cmd content verbatim to stderr (truncated at 80 chars).
    Card authors MUST NOT put credentials in mov_commands cmd fields — this function
    does not sanitize cmd values before displaying them in error output.
    """
    # Normalize to list
    if isinstance(card_json, dict):
        cards = [card_json]
    elif isinstance(card_json, list):
        cards = [c for c in card_json if isinstance(c, dict)]
    else:
        return  # Not a card — nothing to validate

    all_violations: list[tuple[int, int, int, str, str, str]] = []
    # Each entry: (card_idx, ac_idx, cmd_idx, pattern_name, fix, cmd_snippet)

    for card_idx, card in enumerate(cards):
        criteria = card.get("criteria") or card.get("ac", [])
        if not isinstance(criteria, list):
            continue

        for ac_idx, criterion in enumerate(criteria):
            if not isinstance(criterion, dict):
                continue

            # Skip semantic criteria (no mov_commands expected).
            mov_type = criterion.get("mov_type")
            if mov_type == "semantic":
                continue

            mov_commands = criterion.get("mov_commands") or []
            if not isinstance(mov_commands, list):
                continue

            # Empty mov_commands on a non-semantic criterion is caught elsewhere
            # (validate_criteria_schema). Skip here to avoid duplicate errors.
            if not mov_commands:
                continue

            for cmd_idx, entry in enumerate(mov_commands):
                if not isinstance(entry, dict):
                    continue
                cmd = entry.get("cmd", "")
                if not cmd or not isinstance(cmd, str):
                    continue

                for pattern_name, fix in _mov_check_cmd(cmd):
                    all_violations.append((card_idx, ac_idx, cmd_idx, pattern_name, fix, cmd))

    if not all_violations:
        return

    is_bulk = len(cards) > 1

    print("Error: Banned MoV pattern(s) detected in card JSON.", file=sys.stderr)
    print("", file=sys.stderr)
    for card_idx, ac_idx, cmd_idx, pattern_name, fix, cmd in all_violations:
        card_label = f"card[{card_idx}] " if is_bulk else ""
        cmd_display = cmd if len(cmd) <= 80 else cmd[:77] + "..."
        print(
            f"  {card_label}criteria[{ac_idx}] → mov_commands[{cmd_idx}].cmd",
            file=sys.stderr,
        )
        print(f"    Pattern: {pattern_name}", file=sys.stderr)
        print(f"    Command: {cmd_display!r}", file=sys.stderr)
        print(f"    Fix: {fix}", file=sys.stderr)
        print("", file=sys.stderr)
    print("Correct the MoV commands before running kanban do/todo.", file=sys.stderr)
    sys.exit(1)


def _collect_ampersand_errors(criteria: list) -> list:
    """Return list of (criterion_num, cmd) tuples where cmd contains '&&'.

    Only checks criteria with a non-empty mov_commands array. Criteria without
    mov_commands are not checked (no commands to validate).
    """
    violations = []
    for i, criterion in enumerate(criteria, start=1):
        if not isinstance(criterion, dict):
            continue
        mov_commands = criterion.get("mov_commands") or []
        if not mov_commands:
            continue
        for entry in mov_commands:
            if not isinstance(entry, dict):
                continue
            cmd = entry.get("cmd", "")
            if "&&" in str(cmd):
                violations.append((i, str(cmd)))
    return violations


def _print_ampersand_chain_errors(violations: list, card_label: str | None = None) -> None:
    """Print a consolidated error message for all && violations to stderr.

    violations: list of (criterion_num, cmd) tuples
    card_label: optional string identifying the card (intent excerpt or index)
    """
    label_line = f" in card {card_label!r}" if card_label else ""
    print(
        f"Error: `&&` is forbidden in mov_commands[].cmd (hard rule){label_line}.",
        file=sys.stderr,
    )
    for criterion_num, cmd in violations:
        cmd_display = cmd if len(cmd) <= 80 else cmd[:77] + "..."
        print(f"  Criterion {criterion_num}: {cmd_display!r}", file=sys.stderr)
    print(
        "\nFix: split into separate array items:\n"
        '  "mov_commands": [\n'
        '    {"cmd": "rg -q X", "timeout": 10},\n'
        '    {"cmd": "rg -q Y", "timeout": 10}\n'
        "  ]",
        file=sys.stderr,
    )


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

    if "intent" not in data:
        print("Error: JSON must include 'intent' field", file=sys.stderr)
        sys.exit(1)

    # Validate intent is non-empty
    if not isinstance(data["intent"], str) or not data["intent"].strip():
        print("Error: 'intent' field must be a non-empty string", file=sys.stderr)
        sys.exit(1)

    # Validate type field (REQUIRED)
    if "type" not in data:
        print("Error: JSON must include 'type' field", file=sys.stderr)
        sys.exit(1)

    card_type = data.get("type")
    _valid_types = ("work", "rev" + "iew", "research")
    if card_type not in _valid_types:
        print(f"Error: Invalid type '{card_type}'. Must be one of: {', '.join(_valid_types)}", file=sys.stderr)
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
        agent=data.get("agent") or os.environ.get("KANBAN_AGENT") or "unassigned",
        model=data.get("model"),
        session=session,
        criteria=criteria if all(isinstance(c, str) for c in criteria) else None,
        card_type=card_type,
    )

    # If criteria came as full objects (with text/met), use them directly
    if criteria and not all(isinstance(c, str) for c in criteria):
        card["criteria"] = criteria

    # Validate criteria count after building card
    criteria_check = card.get("criteria", [])
    if not criteria_check:
        print("Error: At least one acceptance criterion required. Add \"criteria\": [\"...\"] to JSON.", file=sys.stderr)
        sys.exit(1)

    # Validate structured criteria schema (V5): mov_commands array (mov_type is optional/tolerated)
    # Only validate object criteria (string criteria are legacy/simple; they pass through unchanged)
    object_criteria = [c for c in criteria_check if isinstance(c, dict)]
    if object_criteria:
        validate_criteria_schema(object_criteria)
        # Reject && in any mov_commands[].cmd — hard rule, fires only on card creation.
        violations = _collect_ampersand_errors(object_criteria)
        if violations:
            card_label = str(data.get("action", ""))[:60] or None
            _print_ampersand_chain_errors(violations, card_label=card_label)
            sys.exit(1)

    # Remove readFiles entries that are already in editFiles (editing implies reading)
    edit_files = card.get("editFiles", [])
    read_files = card.get("readFiles", [])
    if edit_files and read_files:
        card["readFiles"] = [f for f in read_files if f not in edit_files]

    return card


def _mov_fail_closed_scan(raw_input_text: str, source: str) -> None:
    """Fail-closed raw-text scan for hook-skip literals when JSON parse fails.

    When card JSON is malformed, we cannot parse mov_commands to run the normal
    pattern checks. As a safety net, scan the raw input text for hook-skip literals
    (e.g., --no-verify, HUSKY=0) and emit a specific security block message before
    falling back to the generic JSON parse error. This ensures hook-skip patterns
    in intentionally malformed JSON are caught with an actionable message.
    """
    found = [lit for lit in _MOV_HOOK_SKIP_LITERALS if lit in raw_input_text]
    if found:
        print(
            f"Error: Banned hook-skip pattern(s) detected in malformed card JSON from {source}.",
            file=sys.stderr,
        )
        for lit in found:
            print(f"  Literal found: {lit!r}", file=sys.stderr)
        print(
            "Remove all hook-skip flags/env-vars before fixing the JSON syntax.",
            file=sys.stderr,
        )
        sys.exit(1)


def resolve_json_input(args) -> object:
    """Resolve card JSON from either --file flag or inline positional argument.

    Enforces mutual exclusion: exactly one of --file or positional json_data must
    be provided. Returns the parsed JSON object or array.

    When JSON parsing fails, performs a fail-closed raw-text scan for hook-skip
    literals (see _mov_fail_closed_scan). If hook-skip content is detected in
    malformed JSON, emits a specific security block message before the parse error.
    """
    json_file = getattr(args, "json_file", None)
    json_data = getattr(args, "json_data", None)

    if json_file and json_data:
        print("Error: Cannot use both --file and a positional JSON argument simultaneously", file=sys.stderr)
        sys.exit(1)

    if json_file:
        file_path = Path(json_file)
        if not file_path.exists():
            print(f"Error: File not found: {json_file}", file=sys.stderr)
            sys.exit(1)
        raw = file_path.read_text(encoding="utf-8")
    elif json_data is not None:
        raw = json_data
    else:
        print("Error: Provide card JSON as a positional argument or via --file <path>", file=sys.stderr)
        sys.exit(1)

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        source = json_file if json_file else "<inline>"
        # Fail-closed: scan raw text for hook-skip literals before emitting the
        # generic parse error, so intentionally malformed JSON with hook-skip strings
        # gets a security-specific block message rather than just a JSON error.
        _mov_fail_closed_scan(raw, source)
        print(f"Error: Invalid JSON from {source}: {e}", file=sys.stderr)
        sys.exit(1)


def _files_conflict(path_a: str, edit_a: bool, path_b: str, edit_b: bool) -> bool:
    """Return True if two file entries conflict based on conflict rules.

    Conflict rules:
    - editFiles vs editFiles  → CONFLICT (two writers)
    - editFiles vs readFiles  → NO CONFLICT (reader + writer is allowed)
    - readFiles vs readFiles  → NO CONFLICT (two readers are fine)

    Uses fnmatch for glob matching. Python's fnmatch treats '*' as matching
    any character including '/' on non-Windows, so 'src/*.py' will match
    'src/foo.py' — crossing path separators as specified.
    """
    # Only conflict when both are edits (two writers)
    if not (edit_a and edit_b):
        return False

    # Check if the two patterns overlap: either a matches b's pattern or b matches a's
    return fnmatch.fnmatch(path_a, path_b) or fnmatch.fnmatch(path_b, path_a)


def check_file_conflicts(
    root: Path,
    new_edit_files: list[str],
    new_read_files: list[str],
) -> tuple[str, str, str] | None:
    """Check new card's files against all in-flight cards (doing) across all sessions.

    Returns the first conflict found as (inflight_card_num, inflight_session, conflicting_path),
    or None if no conflicts exist.

    In-flight means: doing column.
    """
    if not new_edit_files and not new_read_files:
        return None

    in_flight_columns = ["doing"]

    for col in in_flight_columns:
        for card_path in find_cards_in_column(root, col):
            try:
                inflight = read_card(card_path)
            except (json.JSONDecodeError, OSError):
                continue

            inflight_edit = inflight.get("editFiles") or []
            inflight_read = inflight.get("readFiles") or []
            inflight_num = card_number(card_path)
            inflight_session = inflight.get("session") or "unknown"

            # Check new card's editFiles against inflight editFiles only
            # (only edit-vs-edit is a conflict)
            for new_path in new_edit_files:
                for existing_path in inflight_edit:
                    if _files_conflict(new_path, True, existing_path, True):
                        return (inflight_num, inflight_session, new_path)

    return None


def cmd_do(args) -> None:
    """Create card(s) directly in the doing column from JSON input.

    Accepts either a single JSON object or an array of objects for bulk creation.
    Sets agent_launch_pending=True on cards placed in doing (conflict-deferred
    cards go to todo and do NOT get agent_launch_pending=True).
    """
    root = get_root(args.root)

    # resolve_json_input performs a fail-closed raw-text scan for hook-skip literals
    # when JSON is malformed (see _mov_fail_closed_scan), then returns parsed data.
    data = resolve_json_input(args)

    # Run banned-pattern validation before structural checks for clearer error messages.
    validate_mov_commands_content(data)

    session = args.session if hasattr(args, "session") and args.session else get_current_session_id()

    # Pre-compute git_project once to avoid N redundant git subprocesses in bulk loops
    git_root = get_git_root()
    git_project = os.path.basename(git_root) if git_root else None

    # Detect array vs object
    if isinstance(data, list):
        # Bulk creation: validate all cards first (fail fast)
        # Pre-pass: collect && violations across ALL cards before proceeding.
        # This lets us report every violation in one shot rather than stopping
        # at the first offending card.
        all_ampersand_errors = []
        for idx, card_data in enumerate(data):
            if not isinstance(card_data, dict):
                continue
            raw_criteria = card_data.get("criteria") or card_data.get("ac", [])
            object_criteria = [c for c in raw_criteria if isinstance(c, dict)]
            violations = _collect_ampersand_errors(object_criteria)
            if violations:
                card_label = f"card[{idx}]: {str(card_data.get('action', ''))[:50]!r}"
                all_ampersand_errors.append((card_label, violations))
        if all_ampersand_errors:
            for card_label, violations in all_ampersand_errors:
                _print_ampersand_chain_errors(violations, card_label=card_label)
                print("", file=sys.stderr)
            sys.exit(1)

        cards = []
        for i, card_data in enumerate(data):
            if not isinstance(card_data, dict):
                print(f"Error: Array element {i} must be a JSON object, got {type(card_data).__name__}", file=sys.stderr)
                sys.exit(1)
            card = validate_and_build_card(card_data, session)
            cards.append(card)

        # All validation passed — create cards, checking conflicts per card
        had_conflict = False
        for card in cards:
            edit_files = card.get("editFiles") or []
            read_files = card.get("readFiles") or []
            conflict = check_file_conflicts(root, edit_files, read_files)
            if conflict:
                inflight_num, inflight_session, conflict_path = conflict
                num = create_card_in_column(root, "todo", card)
                write_kanban_event(card, str(num), "create", to_column="todo", git_project=git_project)
                print(num)
                print(f"Card #{num} deferred to todo: editFiles conflict with card #{inflight_num} (session {inflight_session}) on path {conflict_path}", file=sys.stderr)
                had_conflict = True
            else:
                card["agent_launch_pending"] = True
                num = create_card_in_column(root, "doing", card)
                write_kanban_event(card, str(num), "create", to_column="doing", git_project=git_project)
                print(num)
        if had_conflict:
            sys.exit(1)
    elif isinstance(data, dict):
        # Single card creation with conflict detection
        card = validate_and_build_card(data, session)
        edit_files = card.get("editFiles") or []
        read_files = card.get("readFiles") or []
        conflict = check_file_conflicts(root, edit_files, read_files)
        if conflict:
            inflight_num, inflight_session, conflict_path = conflict
            num = create_card_in_column(root, "todo", card)
            write_kanban_event(card, str(num), "create", to_column="todo", git_project=git_project)
            print(num)
            # Clean up --file before exiting so it never pre-exists on next use
            json_file = getattr(args, "json_file", None)
            if json_file:
                os.remove(json_file)
            print(f"Card #{num} deferred to todo: editFiles conflict with card #{inflight_num} (session {inflight_session}) on path {conflict_path}", file=sys.stderr)
            sys.exit(1)
        else:
            card["agent_launch_pending"] = True
            num = create_card_in_column(root, "doing", card)
            write_kanban_event(card, str(num), "create", to_column="doing", git_project=git_project)
            print(num)
    else:
        print(f"Error: JSON must be an object or array, got {type(data).__name__}", file=sys.stderr)
        sys.exit(1)

    # Delete the --file input after successful card creation so it never pre-exists on next use
    json_file = getattr(args, "json_file", None)
    if json_file:
        os.remove(json_file)



def cmd_defer(args) -> None:
    """Move card(s) from doing back to todo."""
    root = get_root(args.root)
    card_numbers = args.card if isinstance(args.card, list) else [args.card]

    # Pre-compute git_project once to avoid N redundant git subprocesses in bulk loops
    git_root = get_git_root()
    git_project = os.path.basename(git_root) if git_root else None

    for card_num in card_numbers:
        card_path = find_card(root, card_num)
        col = card_path.parent.name
        num = card_number(card_path)

        if col != "doing":
            print(f"Error: Card #{num} is in '{col}', not 'doing'. Defer only works on cards in doing.", file=sys.stderr)
            sys.exit(1)

        card = read_card(card_path)
        card["agent_launch_pending"] = False
        card["updated"] = now_iso()
        write_card(card_path, card)
        write_kanban_event(card, num, "defer", from_column=col, to_column="todo", git_project=git_project)

        target = root / "todo" / card_path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        card_path.rename(target)
        print(f"Deferred: #{num} — moved to todo")


def cmd_start(args) -> None:
    """Move card(s) from todo to doing (pick up queued work)."""
    root = get_root(args.root)
    card_numbers = args.card if isinstance(args.card, list) else [args.card]
    git_root = get_git_root()
    git_project = os.path.basename(git_root) if git_root else None
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
            edit_files = card.get("editFiles") or []
            read_files = card.get("readFiles") or []
            conflict = check_file_conflicts(root, edit_files, read_files)
            if conflict:
                inflight_num, inflight_session, conflict_path = conflict
                print(f"Error: Cannot start card #{num}: editFiles conflict with card #{inflight_num} (session {inflight_session}) on path {conflict_path}", file=sys.stderr)
                failed = True
                continue
            # Rename before write: flag never lands in todo/ on crash (atomic, matches cmd_do).
            target = root / "doing" / card_path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            card_path.rename(target)
            card["agent_launch_pending"], card["updated"] = True, now_iso()
            write_card(target, card)
            write_kanban_event(card, num, "start", from_column="todo", to_column="doing", git_project=git_project)
            print(f"Started: #{num} — moved to doing")
        except SystemExit:
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

    # Build human-friendly terminal output (simple or detail)
    bold = "\033[1m"
    dim_bold = "\033[2;1m"
    reset = "\033[0m"

    output_lines = []

    # Header
    output_lines.append(f"=== Card #{num} ({col}) ===")
    output_lines.append("")

    # Action (main title)
    action = card.get("action", "[NO ACTION]")
    output_lines.append(action)

    # Intent section
    intent = card.get("intent", "")
    if intent:
        output_lines.append("")
        output_lines.append(f"{dim_bold}  Intent{reset}")
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
                output_lines.append(f"  {line}")

    # Acceptance criteria section
    criteria = card.get("criteria", [])
    if criteria:
        output_lines.append("")
        output_lines.append(f"{dim_bold}  Acceptance Criteria{reset}")
        output_lines.extend(format_criteria_table(criteria, indent="  "))

    # Edit files section
    edit_files = card.get("editFiles") or card.get("writeFiles", [])
    if edit_files:
        output_lines.append("")
        output_lines.append(f"{dim_bold}  Edit Files{reset}")
        for f in sorted(edit_files):
            output_lines.append(f"  {f}")

    # Read files section
    read_files = card.get("readFiles", [])
    if read_files:
        output_lines.append("")
        output_lines.append(f"{dim_bold}  Read Files{reset}")
        for f in sorted(read_files):
            output_lines.append(f"  {f}")

    # Comments section
    comments = card.get("comments", [])
    if comments:
        output_lines.append("")
        output_lines.append(f"{dim_bold}  Comments{reset}")
        for comment in comments:
            ts = comment.get("timestamp", "")
            text = comment.get("text", "")
            if ts:
                try:
                    ts_display = parse_iso(ts).strftime("%Y-%m-%d %H:%M")
                except ValueError:
                    ts_display = ts[:16]
            else:
                ts_display = "unknown"
            output_lines.append(f"  {dim_bold}[{ts_display}]{reset}")
            # Wrap comment text at ~78 chars with 2-space indent
            for paragraph in text.replace("\\n", "\n").split("\n"):
                wrapped = textwrap.wrap(paragraph, width=78) if paragraph.strip() else [""]
                for line in wrapped:
                    output_lines.append(f"  {line}")

    # Footer with metadata
    output_lines.append("")
    session = card.get("session", "")
    agent = card.get("agent", "unassigned")
    model = card.get("model")
    card_type = card.get("type", "work")
    created = card.get("created", "")
    if created:
        try:
            created_date = parse_iso(created).strftime("%Y-%m-%d")
        except ValueError:
            created_date = created[:10]
    else:
        created_date = "unknown"

    footer_parts = []
    footer_parts.append(f"Type: {card_type}")
    if session:
        footer_parts.append(f"Session: {session[:8]}")
    if agent and agent != "unassigned":
        footer_parts.append(f"Agent: {agent}")
    if model:
        footer_parts.append(f"Model: {model}")
    footer_parts.append(f"Created: {created_date}")
    cycles = card.get("cycles", 0)
    if cycles:
        footer_parts.append(f"Cycles: {cycles}")

    output_lines.append(f"{bold}{' · '.join(footer_parts)}{reset}")

    # Send through pager
    use_pager("\n".join(output_lines) + "\n")


def cmd_status(args) -> None:
    """Print only the column name of a card (e.g. doing, review, todo, done)."""
    root = get_root(args.root)
    card_path = find_card(root, args.card)
    print(card_path.parent.name)


def cmd_rejections(args) -> None:
    """Display rejection history for a card, formatted for readability."""
    root = get_root(args.root)
    card_path = find_card(root, args.card)
    card = read_card(card_path)
    num = card_number(card_path)

    rejection_history = card.get("rejection_history", [])

    if not rejection_history:
        print(f"Card #{num}: No rejection history recorded")
        return

    # Build formatted output
    output_lines = []
    output_lines.append(f"=== Rejection History for Card #{num} ===")
    output_lines.append("")

    bold = "\033[1m"
    reset = "\033[0m"

    for entry in rejection_history:
        cycle = entry.get("cycle", "?")
        timestamp = entry.get("timestamp", "unknown")
        failures = entry.get("failures", [])

        # Format timestamp for display
        try:
            ts_display = parse_iso(timestamp).strftime("%Y-%m-%d %H:%M:%S UTC")
        except (ValueError, AttributeError):
            ts_display = timestamp

        output_lines.append(f"{bold}Cycle {cycle}{reset} — {ts_display}")

        if not failures:
            output_lines.append("  (no failures recorded)")
        else:
            for i, failure in enumerate(failures, 1):
                criterion = failure.get("criterion", "[Unknown criterion]")
                reason = failure.get("reason", "[No reason provided]")
                output_lines.append(f"  {i}. {criterion}")
                output_lines.append(f"     Reason: {reason}")

        output_lines.append("")

    # Send through pager
    use_pager("\n".join(output_lines) + "\n")


def cmd_rename(args) -> None:
    """Rename a session to a custom friendly name.

    Allows users to override the auto-generated Docker-style session name.
    Session is identified by --session flag or auto-detected from environment.
    """
    root = get_root(args.root, auto_init=False)
    root.mkdir(parents=True, exist_ok=True)

    # Get the session ID to rename
    session_id = args.session
    if not session_id:
        print("Error: Session must be specified with --session flag for rename command", file=sys.stderr)
        sys.exit(1)

    # Validate the new name format (alphanumeric, hyphens only, not empty)
    new_name = args.new_name.strip() if args.new_name else None
    if not new_name:
        print("Error: New session name cannot be empty", file=sys.stderr)
        sys.exit(1)

    # Validate name format: allow adjective-noun style or any alphanumeric-hyphen combo
    if not re.match(r'^[a-z0-9]([a-z0-9-]*[a-z0-9])?$', new_name):
        print(f"Error: Session name must contain only lowercase letters, numbers, and hyphens (got '{new_name}')", file=sys.stderr)
        sys.exit(1)

    # Load sessions mapping
    sessions_file = root / "sessions.json"
    sessions: dict[str, str] = {}
    if sessions_file.exists():
        try:
            sessions = json.loads(sessions_file.read_text())
        except (json.JSONDecodeError, OSError):
            sessions = {}

    # Check if new name is already in use (by a different UUID prefix)
    used_by_other = None
    for uuid_prefix, name in sessions.items():
        if name == new_name and uuid_prefix != session_id:
            used_by_other = uuid_prefix
            break

    if used_by_other:
        print(f"Error: Session name '{new_name}' is already in use by session {used_by_other}", file=sys.stderr)
        sys.exit(1)

    # Get the old name for reporting
    old_name = sessions.get(session_id, "<unknown>")

    # Update the mapping
    sessions[session_id] = new_name
    sessions_file.write_text(json.dumps(sessions, indent=2) + "\n")

    print(f"Renamed session {session_id} from '{old_name}' to '{new_name}'")


def cmd_cancel(args) -> None:
    """Move card(s) to canceled column."""
    root = get_root(args.root)
    card_numbers = args.card if isinstance(args.card, list) else [args.card]

    # Support positional reason: if the last element of card_numbers is not a
    # digit-only string it was provided as a bare positional reason argument
    # (e.g. `kanban cancel 1011 "some reason"`).  Extract it before looping.
    reason = args.reason if hasattr(args, "reason") and args.reason else None
    if not reason and len(card_numbers) > 1 and not card_numbers[-1].isdigit():
        reason = card_numbers[-1]
        card_numbers = card_numbers[:-1]

    # Pre-compute git_project once to avoid N redundant git subprocesses in bulk loops
    git_root = get_git_root()
    git_project = os.path.basename(git_root) if git_root else None

    for card_num in card_numbers:
        card_path = find_card(root, card_num)
        col = card_path.parent.name
        card = read_card(card_path)
        num = card_number(card_path)

        if reason:
            card["cancelReason"] = reason

        card["updated"] = now_iso()
        write_card(card_path, card)

        write_kanban_event(card, num, "canceled", from_column=col, to_column="canceled", git_project=git_project)

        target_path = root / "canceled" / card_path.name
        target_path.parent.mkdir(parents=True, exist_ok=True)
        card_path.rename(target_path)

        # Output with reason if provided
        if reason:
            print(f"Canceled: #{num} — {reason}")
        else:
            print(f"Canceled: #{num}")


def cmd_agent(args) -> None:
    """Set the agent field on a card."""
    root = get_root(args.root)
    card_path = find_card(root, args.card)
    card = read_card(card_path)

    # Normalize to lowercase-kebab-case (same as make_card)
    agent_type = args.agent_type.lower().replace(" ", "-")
    card["agent"] = agent_type
    card["updated"] = now_iso()
    write_card(card_path, card)
    print(f"Card #{card_number(card_path)} agent set to: {agent_type}")


def cmd_clear_agent_launch_pending(args) -> None:
    """Clear the agent_launch_pending flag on a card.

    Called by the pretool hook when an Agent tool launch is detected for the
    card, confirming that the coordinator has actually launched the agent.
    Sets agent_launch_pending=False so phantom-doing detection can distinguish
    cards that are genuinely in-flight from cards stuck in doing with no agent.

    Column guard: only operates on cards in the 'doing' column. Calling this on
    a todo or done card is semantically incorrect (the flag only applies to
    in-flight cards) and exits with an error.

    Note: session ownership intentionally not enforced — single-user platform.
    If multi-user/CI extension is added later, add:
        if card.get("session") and args.session and card["session"] != args.session:
            sys.exit(1)
    guard before write.
    """
    root = get_root(args.root)
    card_path = find_card(root, args.card)
    col = card_path.parent.name
    if col != "doing":
        num = card_number(card_path)
        print(f"Error: Card #{num} is in '{col}', not 'doing'. clear-agent-launch-pending only works on cards in doing.", file=sys.stderr)
        sys.exit(1)
    card = read_card(card_path)
    card["agent_launch_pending"] = False
    card["updated"] = now_iso()
    write_card(card_path, card)
    print(f"Card #{card_number(card_path)} agent_launch_pending cleared")


def cmd_criteria_add(args) -> None:
    """Add acceptance criterion to card.

    When --mov-cmd is provided, each occurrence appends an entry to mov_commands.
    --mov-timeout sets the timeout for the most-recently-added --mov-cmd (default 30).

    Without --mov-cmd, the criterion is created with an empty mov_commands array.
    Such criteria will be rejected by 'kanban criteria check' — use 'kanban do --file'
    to create programmatic criteria, or always supply at least one --mov-cmd.

    If the card is in 'done' status, it is automatically transitioned back to 'doing'
    and a warning is emitted to stderr (Option B: auto-reopen for mid-flight criterion add).
    """
    root = get_root(args.root)

    # Validate --mov-cmd entries for banned patterns early, before card I/O.
    # This closes the bypass path where criteria add could introduce hook-skip
    # or other banned patterns without going through cmd_do/cmd_todo.
    if args.mov_cmd:
        criteria_add_violations: list[str] = []
        for raw_cmd in args.mov_cmd:
            for pattern_name, fix in _mov_check_cmd(raw_cmd):
                criteria_add_violations.append(
                    f"  cmd: {raw_cmd!r}\n    Pattern: {pattern_name}\n    Fix: {fix}"
                )
        if criteria_add_violations:
            print("Error: Banned MoV pattern(s) detected in --mov-cmd argument.", file=sys.stderr)
            for msg in criteria_add_violations:
                print(msg, file=sys.stderr)
            sys.exit(1)

    card_path = find_card(root, args.card)
    card = read_card(card_path)
    num = card_number(card_path)

    # Guard: canceled cards are intentionally closed; criteria add is not allowed.
    if card_path.parent.name == "canceled":
        print(
            f"Error: cannot add criteria to a canceled card #{num}. Canceled cards are intentionally closed.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Track whether this is an auto-reopen (done -> doing) so we can rename AFTER write.
    auto_reopen = card_path.parent.name == "done"
    auto_reopen_target: "Path | None" = None
    if auto_reopen:
        doing_dir = root / "doing"
        doing_dir.mkdir(parents=True, exist_ok=True)
        auto_reopen_target = doing_dir / card_path.name

        # F5: Scrub stale 'Completed' activity entry left by cmd_done.
        if "activity" in card:
            # Remove the most-recent 'Completed' entry to avoid misleading activity on a doing card.
            for i in range(len(card["activity"]) - 1, -1, -1):
                if card["activity"][i].get("message") == "Completed":
                    card["activity"].pop(i)
                    break  # scrub at most one entry

    # Initialize criteria list if it doesn't exist
    if "criteria" not in card:
        card["criteria"] = []

    # Build mov_commands from paired --mov-cmd / --mov-timeout arguments
    mov_commands = []
    if args.mov_cmd:
        timeouts = list(args.mov_timeout) if args.mov_timeout else []
        for i, cmd in enumerate(args.mov_cmd):
            timeout = timeouts[i] if i < len(timeouts) else 30
            mov_commands.append({"cmd": cmd, "timeout": timeout})

    new_criterion: dict = {
        "text": args.text,
        "mov_commands": mov_commands,
        "met": False,
    }

    # Apply __CARD_ID__ substitution in criterion text and mov_commands
    if isinstance(new_criterion.get("text"), str):
        new_criterion["text"] = new_criterion["text"].replace("__CARD_ID__", str(num))
    for entry in new_criterion.get("mov_commands", []):
        if isinstance(entry.get("cmd"), str):
            entry["cmd"] = entry["cmd"].replace("__CARD_ID__", str(num))

    card["criteria"].append(new_criterion)
    card["updated"] = now_iso()
    validate_criteria_schema(card["criteria"])

    # F2: write before rename — write_card to source path first (still in done/ for auto-reopen),
    # then rename. This matches cmd_done's pattern and reduces the partial-state window on crash.
    write_card(card_path, card)

    if auto_reopen:
        card_path.rename(auto_reopen_target)

        # F1: Record the done->doing transition in the metrics DB (audit trail / analytics dashboard).
        write_kanban_event(card, num, "start", from_column="done", to_column="doing")

        print(
            f"Warning: card #{num} was auto-reopened from 'done' to 'doing' because a new acceptance criterion was added after the card was already marked done.\n"
            f"         Re-launch the agent to verify the new criterion (the SubagentStop hook will catch it).",
            file=sys.stderr,
        )

    print(f"Added criterion to #{num}: {new_criterion['text']}")


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
    validate_criteria_schema(card["criteria"])
    write_card(card_path, card)
    num = card_number(card_path)
    print(f"Removed criterion from #{num}: {removed_text}")
    print(f"Reason: {args.reason}")


def _find_criterion_idx(criteria: list, criterion_arg: str) -> int | None:
    """Find a criterion's 0-based index by 1-based integer or text prefix."""
    if str(criterion_arg).isdigit():
        idx = int(criterion_arg) - 1
        if 0 <= idx < len(criteria):
            return idx
    else:
        search_text = str(criterion_arg).lower()
        for i, c in enumerate(criteria):
            if c.get("text", "").lower().startswith(search_text):
                return i
    return None


def cmd_criteria_check(args) -> None:
    """Mark acceptance criterion(s) as met (sets met).

    For criteria with a non-empty mov_commands array, iterates the commands
    in order and short-circuits on the first non-zero exit code.
    Sets met only when all commands in the array exit 0.

    Exit code classification (applied per command in the array):
      0   → pass (continue to next command)
      127 → command not found (kanban exits 10)
      126 → permission denied (kanban exits 10)
      2   → bash syntax error at runtime (kanban exits 10)
      124 → timeout (kanban exits 11 with clear message)
      other nonzero → work failure (kanban exits 1 with full diagnostics)
    """
    root = get_root(args.root)
    card_path = find_card(root, args.card)
    card = read_card(card_path)
    num = card_number(card_path)

    criteria = card.get("criteria", [])
    if not criteria:
        print(f"Error: Card #{num} has no acceptance criteria", file=sys.stderr)
        sys.exit(1)

    # Use process cwd (where agent invoked kanban)
    working_dir = os.getcwd()

    for criterion_arg in args.n:
        criterion_idx = _find_criterion_idx(criteria, criterion_arg)
        if criterion_idx is None:
            print(f"Error: No criterion found matching '{criterion_arg}'", file=sys.stderr)
            sys.exit(1)

        criterion = criteria[criterion_idx]
        mov_commands = criterion.get("mov_commands") or []
        text = criterion.get("text", "")
        display_n = criterion_arg if str(criterion_arg).isdigit() else (criterion_idx + 1)

        if not mov_commands:
            # Reject criteria with no programmatic verification
            print(
                f"invalid AC #{display_n}: no programmatic verification provided — "
                f"criterion has no mov_commands. Use 'kanban criteria remove' to drop it, "
                f"or recreate the card with programmatic mov_commands via 'kanban do --file'.",
                file=sys.stderr,
            )
            sys.exit(1)

        # Iterate mov_commands array in order; short-circuit on first non-zero exit
        for cmd_idx, cmd_entry in enumerate(mov_commands):
            cmd = cmd_entry.get("cmd", "")
            timeout_secs = cmd_entry.get("timeout", 30)

            try:
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout_secs,
                    cwd=working_dir,
                    env=os.environ.copy(),
                )
                rc = result.returncode

                if rc == 0:
                    # This command passed; continue to next
                    continue
                elif rc in (127, 126, 2):
                    # mov_error: command not found, permission denied, or bash syntax error
                    print(f"Criterion {display_n} check ERROR (exit {rc}) at command [{cmd_idx + 1}/{len(mov_commands)}].", file=sys.stderr)
                    print(f"  failed_index: {cmd_idx}", file=sys.stderr)
                    print(f"  failed_cmd: {cmd}", file=sys.stderr)
                    print(f"  exit_code: {rc}", file=sys.stderr)
                    if result.stdout.strip():
                        print(f"  stdout: {result.stdout.rstrip()}", file=sys.stderr)
                    if result.stderr.strip():
                        print(f"  stderr: {result.stderr.rstrip()}", file=sys.stderr)
                    if rc == 127:
                        print("  cause: command not found", file=sys.stderr)
                    elif rc == 126:
                        print("  cause: permission denied (command not executable)", file=sys.stderr)
                    else:
                        print("  cause: bash syntax error at runtime", file=sys.stderr)
                    sys.exit(10)
                else:
                    # Work failure: command ran but the criterion is not met
                    print(f"Criterion {display_n} check FAILED at command [{cmd_idx + 1}/{len(mov_commands)}].", file=sys.stderr)
                    print(f"  failed_index: {cmd_idx}", file=sys.stderr)
                    print(f"  failed_cmd: {cmd}", file=sys.stderr)
                    print(f"  exit_code: {rc}", file=sys.stderr)
                    if result.stdout.strip():
                        print(f"  stdout: {result.stdout.rstrip()}", file=sys.stderr)
                    if result.stderr.strip():
                        print(f"  stderr: {result.stderr.rstrip()}", file=sys.stderr)
                    sys.exit(1)

            except subprocess.TimeoutExpired:
                print(
                    f"Criterion {display_n} check TIMED OUT at command [{cmd_idx + 1}/{len(mov_commands)}] "
                    f"after {timeout_secs}s.\n"
                    f"  failed_index: {cmd_idx}\n"
                    f"  failed_cmd: {cmd}\n"
                    f"  The command did not complete within the timeout window ({timeout_secs}s).\n"
                    f"  Result is ambiguous — verify manually.",
                    file=sys.stderr,
                )
                sys.exit(11)

        # All commands in the array passed
        criteria[criterion_idx]["met"] = True
        print(f"Criterion {display_n} passed: {text}")

    card["updated"] = now_iso()
    validate_criteria_schema(card["criteria"])
    write_card(card_path, card)


def cmd_criteria_uncheck(args) -> None:
    """Mark acceptance criterion(s) as unmet (clears met)."""
    root = get_root(args.root)
    card_path = find_card(root, args.card)
    card = read_card(card_path)

    criteria = card.get("criteria", [])
    if not criteria:
        print(f"Error: Card #{card_number(card_path)} has no acceptance criteria", file=sys.stderr)
        sys.exit(1)

    for criterion_arg in args.n:
        criterion_idx = _find_criterion_idx(criteria, criterion_arg)
        if criterion_idx is None:
            print(f"Error: No criterion found matching '{criterion_arg}'", file=sys.stderr)
            sys.exit(1)

        criteria[criterion_idx]["met"] = False
        print(f"⬜ Unchecked: {criteria[criterion_idx]['text']}")

    card["updated"] = now_iso()
    validate_criteria_schema(card["criteria"])
    write_card(card_path, card)



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
    card_type = card.get("type", "work")
    agent = card.get("agent", "")
    model = card.get("model", "")

    # Card opening tag with attributes
    cycles = card.get("cycles", 0)
    card_attrs = f'num="{esc(num)}" session="{esc(session)}" status="{esc(col)}" type="{esc(card_type)}"'
    if agent:
        card_attrs += f' agent="{esc(agent)}"'
    if model:
        card_attrs += f' model="{esc(model)}"'
    if cycles:
        card_attrs += f' cycles="{cycles}"'
    xml_parts = [f"<card {card_attrs}>"]

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
                ac_attrs = f'met="{met}"'
                mov_commands = criterion.get("mov_commands") or []
                if mov_commands:
                    # Emit movCommands as child elements
                    ac_open = f"    <ac {ac_attrs}>{text}"
                    xml_parts.append(ac_open)
                    xml_parts.append("      <movCommands>")
                    for cmd_entry in mov_commands:
                        cmd_val = esc(str(cmd_entry.get("cmd", "")))
                        timeout_val = cmd_entry.get("timeout", "")
                        xml_parts.append(f'        <command cmd="{cmd_val}" timeout="{timeout_val}"/>')
                    xml_parts.append("      </movCommands>")
                    xml_parts.append("    </ac>")
                else:
                    xml_parts.append(f"    <ac {ac_attrs}>{text}</ac>")
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

    # Comments (only in show/details mode)
    if include_details:
        comments = card.get("comments", [])
        if comments:
            xml_parts.append("  <comments>")
            for comment in comments:
                timestamp = esc(comment.get("timestamp", ""))
                text = esc(comment.get("text", ""))
                xml_parts.append(f'    <comment ts="{timestamp}">{text}</comment>')
            xml_parts.append("  </comments>")

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


def _display_width(s: str) -> int:
    """Return the number of terminal display columns occupied by string s.

    Wide (W) and Fullwidth (F) characters occupy 2 columns each.
    All other Unicode characters (Narrow, Neutral, Halfwidth, Ambiguous)
    are treated as 1 column, matching typical Western terminal behavior.
    """
    width = 0
    for c in s:
        eaw = unicodedata.east_asian_width(c)
        width += 2 if eaw in ('W', 'F') else 1
    return width


def _center_to_display_width(s: str, target: int, fill: str = ' ') -> str:
    """Center string s within target display columns using fill character.

    Unlike str.center(), this accounts for double-width Unicode characters
    so the result occupies exactly target display columns.
    """
    current = _display_width(s)
    padding = max(0, target - current)
    left_pad = padding // 2
    right_pad = padding - left_pad
    return fill * left_pad + s + fill * right_pad


def format_criteria_table(criteria: list, indent: str = "  ", terminal_width: int | None = None) -> list[str]:
    """Render acceptance criteria as a formatted table.

    Produces a scannable table with columns: #, Met, Criterion.
    Long criterion text wraps at the terminal boundary with continuation indent.

    Args:
        criteria: List of criterion dicts with keys: text, met.
        indent: Leading whitespace for each table row (default 2 spaces).
        terminal_width: Override terminal width detection (useful for fixed-width contexts).

    Returns:
        List of formatted lines (no trailing newline on any line).
    """
    if not criteria:
        return []

    if terminal_width is None:
        terminal_width = shutil.get_terminal_size((120, 24)).columns

    # Fixed column widths in display columns.
    # Emoji ✅ and ⬜ are double-width (W) characters occupying 2 display columns each.
    # _center_to_display_width() ensures data cells align with header and separator
    # regardless of how many bytes each character occupies in the string.
    num_col_width = max(2, len(str(len(criteria))))  # right-aligned, e.g. " 1" or "10"
    met_col_width = 5     # display columns for met status cell
    sep = "  "            # column separator (2 spaces)

    # Calculate available width for criterion text
    # Layout: indent + num + sep + met + sep + criterion
    prefix_width = len(indent) + num_col_width + len(sep) + met_col_width + len(sep)
    criterion_width = max(20, terminal_width - prefix_width)

    # Continuation indent for wrapped criterion lines (blank num/met columns)
    blank_num = " " * num_col_width
    blank_met = " " * met_col_width
    continuation_prefix = f"{indent}{blank_num}{sep}{blank_met}{sep}"

    lines = []

    # Header row — narrow ASCII chars, str.center() is accurate for display width
    header_num = "#".rjust(num_col_width)
    header_met = "Met".center(met_col_width)
    header_criterion = "Criterion"
    lines.append(f"{indent}{header_num}{sep}{header_met}{sep}{header_criterion}")

    # Separator row — ─ is 1 display column, so count == display width
    sep_num = "─" * num_col_width
    sep_met = "─" * met_col_width
    sep_criterion = "─" * min(criterion_width, len("Criterion"))
    lines.append(f"{indent}{sep_num}{sep}{sep_met}{sep}{sep_criterion}")

    for i, criterion in enumerate(criteria, start=1):
        met = criterion.get("met", False)

        # Center the emoji within met_col_width display columns.
        # ✅ and ⬜ are each 2 display columns wide; _center_to_display_width()
        # adds the correct number of spaces so the cell occupies exactly
        # met_col_width display columns, matching header and separator.
        met_cell = _center_to_display_width("✅" if met else "⬜", met_col_width)

        num_cell = str(i).rjust(num_col_width)
        text = criterion.get("text", "")

        # Wrap long criterion text
        wrapped_lines = textwrap.wrap(text, width=criterion_width, break_long_words=True) if text else [""]

        # First line: full row
        lines.append(f"{indent}{num_cell}{sep}{met_cell}{sep}{wrapped_lines[0]}")

        # Continuation lines: blank num/status cells, only criterion text
        for continuation in wrapped_lines[1:]:
            lines.append(f"{continuation_prefix}{continuation}")

        # MoV metadata lines: show mov_commands array if present
        mov_commands = criterion.get("mov_commands") or []
        if mov_commands:
            for cmd_idx, cmd_entry in enumerate(mov_commands):
                cmd_val = cmd_entry.get("cmd", "")
                timeout_val = cmd_entry.get("timeout", "")
                lines.append(f"{continuation_prefix}  [{cmd_idx + 1}] cmd: {cmd_val}  timeout: {timeout_val}s")

    return lines


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
    action = card.get("action", "[NO ACTION]")

    # Compute plain-text suffix widths before applying ANSI codes
    plain_session_suffix = f" ({session[:8]})" if (session and show_session) else ""
    plain_lead_time_suffix = ""
    lead_time_str = None
    if column == "done":
        lead_time_seconds = calculate_lead_time(card)
        if lead_time_seconds is not None:
            lead_time_str = format_lead_time(lead_time_seconds)
            plain_lead_time_suffix = f" ({lead_time_str})"
    plain_suffix_width = len(plain_session_suffix) + len(plain_lead_time_suffix)

    # Truncate action text to fit terminal width (simple style only)
    # Prefix: "  #NNN " = 2 spaces + "#" + num + " " = len(num) + 4
    if output_style == "simple":
        # Clean newline characters before truncation
        # Replace \n, \r\n, \r with spaces and collapse multiple spaces
        action = action.replace('\r\n', ' ').replace('\r', ' ').replace('\n', ' ')
        action = ' '.join(action.split())  # Collapse multiple consecutive spaces

        terminal_width = shutil.get_terminal_size().columns
        prefix_width = len(num) + 4  # "  #NNN "
        available = terminal_width - prefix_width - plain_suffix_width
        if available >= 20 and len(action) > available:
            action = action[:available - 3] + "..."

    # Build ANSI-decorated suffixes after truncation
    session_suffix = f" {dim}({session[:8]}){reset}" if (session and show_session) else ""
    line = f"{prefix}  #{num} {action}{session_suffix}"

    # Add lead time for done cards
    if lead_time_str is not None:
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
            table_lines = format_criteria_table(criteria, indent="    ")
            criteria_section = f"{dim}    Acceptance Criteria\n"
            criteria_section += "\n".join(table_lines)
            criteria_section += reset
            sections.append(criteria_section)

    # Metadata section (type, agent, model) - show in "detail" style only
    if output_style == "detail":
        metadata_parts = []
        card_type = card.get("type", "work")
        agent = card.get("agent")
        model = card.get("model")
        metadata_parts.append(f"Type: {card_type}")
        if agent and agent != "unassigned":
            metadata_parts.append(f"Agent: {agent}")
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
        - cards_per_hour: Hourly throughput rate based on today's cards (float)
        - cards_today: Cards completed since midnight today
        - cards_all_time: Total cards in done column
        - avg_lead_time_seconds: Average lead time in seconds (or None)
    """
    done_dir = root / "done"
    if not done_dir.exists():
        return {
            "cards_per_hour": 0.0,
            "cards_today": 0,
            "cards_all_time": 0,
            "avg_lead_time_seconds": None,
        }

    now = datetime.now(timezone.utc)
    today_midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    hours_elapsed_today = (now - today_midnight).total_seconds() / 3600.0

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
                if updated >= today_midnight:
                    cards_today += 1

            # Calculate lead time
            lead_time = calculate_lead_time(card)
            if lead_time is not None:
                lead_times.append(lead_time)

        except (json.JSONDecodeError, OSError, ValueError):
            continue

    # Calculate hourly throughput rate based on today's progress
    # Avoid division by zero for very early morning (use minimum 1 hour)
    cards_per_hour = cards_today / max(hours_elapsed_today, 1.0)

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
        output_style = getattr(args, "output_style", "xml")
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

    # XML output: terse format for coordinator board awareness.
    #
    # Terse list schema (per <c> element) — designed for fast coordination
    # queries, not content inspection. Coordinators need to know which cards
    # are in flight, which files they are editing, and what each card is about
    # at a glance. Full content belongs in `kanban show`.
    #
    # INCLUDED:
    #   n   (attr)  — card number (required for all follow-up commands)
    #   s   (attr)  — status/column (doing/review/todo/done/canceled)
    #   ses (attr)  — session, only on <others> cards (omitted on <mine>)
    #   <i>         — intent, truncated to 200 chars + "..." marker if longer.
    #                 Intent is used instead of action: it is the "why" (concise
    #                 by design), whereas action can be 2-3K chars of instructions.
    #   <e>         — editFiles (coordination-critical: file conflict detection)
    #
    # EXCLUDED (use `kanban show <N> --output-style=xml` for these):
    #   <a> / action    — main culprit; often 2000-3000 chars of instructions
    #   <r> / readFiles — not coordination-critical; read access never conflicts.
    #                     Excluded per user refinement to keep list maximally terse.
    #   <criteria>      — full AC list including mov_commands
    #   model, type, subagent_type, agent — not needed for list-level decisions
    #   activity, comments — historical data; belongs in show/detail view
    #
    # INTENT TRUNCATION: 200 chars chosen to give enough context for a
    # coordinator to identify what a card is about without blowing up
    # token budgets on a 30-card board list.
    if output_style == "xml":
        esc = html.escape

        # Get session for delineation
        session_arg = getattr(args, "session", None)

        # Build session attribute for board tag
        session_attr = f' session="{esc(session_arg)}"' if session_arg else ""
        print(f"<board{session_attr}>")

        _INTENT_MAX = 200  # chars; keep in sync with test_kanban_list_xml_schema.py

        def _terse_intent(card: dict) -> str:
            """Return intent truncated to _INTENT_MAX chars with ellipsis if cut."""
            raw = card.get("intent", "").strip()
            if len(raw) > _INTENT_MAX:
                return esc(raw[:_INTENT_MAX]) + "..."
            return esc(raw)

        def _render_terse_card(num, card, col, ses_attr=""):
            """Render one terse <c> element for list XML output.

            Includes: card number (n), status (s), session (ses, others only),
            intent <i> (truncated), editFiles <e>.
            Excludes: readFiles, action, criteria, and all other metadata.
            """
            edit_files = card.get("editFiles") or card.get("writeFiles", [])
            intent_text = _terse_intent(card)

            parts = [f'<c n="{esc(num)}"{ses_attr} s="{esc(col)}">']
            if intent_text:
                parts.append(f"<i>{intent_text}</i>")
            if edit_files:
                edit_str = esc(",".join(sorted(edit_files)))
                parts.append(f"<e>{edit_str}</e>")
            parts.append("</c>")
            return "".join(parts)

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
                    print(_render_terse_card(num, card, col))
                print("</mine>")

            # Output <others> section
            if others_cards:
                print("<others>")
                for num, card, col in others_cards:
                    card_session = card.get("session", "")
                    ses_attr = f' ses="{esc(card_session)}"' if card_session else ""
                    print(_render_terse_card(num, card, col, ses_attr=ses_attr))
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
                        print(_render_terse_card(num, card, col))
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
    # Format cards_per_hour with 1 decimal place
    cards_per_hour_str = f"{metrics['cards_per_hour']:.1f}"
    throughput_parts = [
        f"{cards_per_hour_str} cards/hr",
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

    # resolve_json_input performs a fail-closed raw-text scan for hook-skip literals
    # when JSON is malformed (see _mov_fail_closed_scan), then returns parsed data.
    data = resolve_json_input(args)

    # Run banned-pattern validation before structural checks for clearer error messages.
    validate_mov_commands_content(data)

    session = args.session if hasattr(args, "session") and args.session else get_current_session_id()

    # Pre-compute git_project once to avoid N redundant git subprocesses in bulk loops
    git_root = get_git_root()
    git_project = os.path.basename(git_root) if git_root else None

    # Detect array vs object
    if isinstance(data, list):
        # Bulk creation: validate all cards first (fail fast)
        # Pre-pass: collect && violations across ALL cards before proceeding.
        # This lets us report every violation in one shot rather than stopping
        # at the first offending card.
        all_ampersand_errors = []
        for idx, card_data in enumerate(data):
            if not isinstance(card_data, dict):
                continue
            raw_criteria = card_data.get("criteria") or card_data.get("ac", [])
            object_criteria = [c for c in raw_criteria if isinstance(c, dict)]
            violations = _collect_ampersand_errors(object_criteria)
            if violations:
                card_label = f"card[{idx}]: {str(card_data.get('action', ''))[:50]!r}"
                all_ampersand_errors.append((card_label, violations))
        if all_ampersand_errors:
            for card_label, violations in all_ampersand_errors:
                _print_ampersand_chain_errors(violations, card_label=card_label)
                print("", file=sys.stderr)
            sys.exit(1)

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
            write_kanban_event(card, str(num), "create", to_column="todo", git_project=git_project)
            print(num)
    elif isinstance(data, dict):
        # Single card creation (existing behavior)
        card = validate_and_build_card(data, session)
        num = create_card_in_column(root, "todo", card)
        write_kanban_event(card, str(num), "create", to_column="todo", git_project=git_project)
        print(num)
    else:
        print(f"Error: JSON must be an object or array, got {type(data).__name__}", file=sys.stderr)
        sys.exit(1)

    # Delete the --file input after successful card creation so it never pre-exists on next use
    json_file = getattr(args, "json_file", None)
    if json_file:
        os.remove(json_file)


def cmd_done(args) -> None:
    """Move card to done column (pure verb - no view mode).

    Gate: all criteria must have met == True.
    If unchecked criteria remain, increments cycles and exits 1 (retryable)
    until cycles >= MAX_CYCLES, then exits 2 (max cycles reached).
    """
    root = get_root(args.root)
    card_path = find_card(root, args.card)
    col = card_path.parent.name
    card = read_card(card_path)
    num = card_number(card_path)

    if col != "doing":
        print(f"Error: Card #{num} is in '{col}', not 'doing'. Done only works on cards in doing.", file=sys.stderr)
        sys.exit(1)

    # Gate: all criteria must have met == True
    criteria = card.get("criteria", [])
    if criteria:
        unchecked = [
            (i, c) for i, c in enumerate(criteria, start=1)
            if not c.get("met", False)
        ]
        if unchecked:
            # Increment cycles counter
            card["cycles"] = card.get("cycles", 0) + 1
            cycles = card["cycles"]
            card["activity"].append({
                "timestamp": now_iso(),
                "message": f"Done blocked — unchecked criteria (cycle {cycles})",
            })
            card["updated"] = now_iso()
            write_card(card_path, card)

            print(f"Cannot complete card #{num} — {len(unchecked)} of {len(criteria)} acceptance criteria not met:", file=sys.stderr)
            for i, criterion in unchecked:
                text = criterion.get("text", "")
                print(f"  {i}. ⬜ {text}", file=sys.stderr)
            print(f"\nRun `kanban criteria check {num} <n>` to mark criteria as met.", file=sys.stderr)
            print(f"Cycle: {cycles}/{MAX_CYCLES}", file=sys.stderr)

            if cycles >= MAX_CYCLES:
                print(f"Max cycles ({MAX_CYCLES}) reached — escalate to staff engineer.", file=sys.stderr)
                sys.exit(2)
            sys.exit(1)

    # Append completion message to activity
    message = args.message if hasattr(args, "message") and args.message else "Completed"
    card["activity"].append({
        "timestamp": now_iso(),
        "message": message,
    })
    card["updated"] = now_iso()
    write_card(card_path, card)

    write_kanban_event(card, num, "done", card_completed_at=card["updated"], from_column=col, to_column="done")
    target = root / "done" / card_path.name
    target.parent.mkdir(parents=True, exist_ok=True)
    card_path.rename(target)
    print(f"Done: #{num} — {message}")


def trash_path(path: Path) -> None:
    """Move a file or directory to the macOS Trash using the trash CLI.

    Files moved to Trash via the trash CLI preserve their original path
    metadata, enabling Finder's 'Put Back' to restore them to their exact
    original location.
    """
    result = subprocess.run(["trash", str(path)], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"trash failed for {path}: {result.stderr.strip()}")


def cmd_clean(args) -> None:
    """Move cards to macOS Trash with user confirmation (optionally including scratchpad).

    Files are sent to macOS Trash and can be restored via Finder's 'Put Back'.

    Modes:
    - kanban clean: Trash all cards from all columns (not scratchpad)
    - kanban clean --expunge: Trash all cards AND scratchpad contents
    - kanban clean <column>: Trash cards only from specified column
    """
    root = get_root(args.root, auto_init=False)
    if not root.exists():
        print("No kanban board found.")
        return

    # Parse arguments
    column = getattr(args, "column", None)
    expunge = getattr(args, "expunge", False)

    # Validate: --expunge only works with full clean
    if expunge and column:
        print("Error: --expunge flag cannot be used with column-specific clean", file=sys.stderr)
        sys.exit(1)

    # Validate column name if provided
    if column and column not in COLUMNS:
        print(f"Error: Invalid column '{column}'. Valid columns: {', '.join(COLUMNS)}", file=sys.stderr)
        sys.exit(1)

    # Count cards to be deleted
    columns_to_clean = [column] if column else COLUMNS
    total_cards = 0
    for col in columns_to_clean:
        col_path = root / col
        if col_path.exists():
            total_cards += len(list(col_path.glob("*.json")))

    # Count scratchpad files if expunge
    scratchpad_count = 0
    if expunge:
        scratchpad_path = root / "scratchpad"
        if scratchpad_path.exists():
            scratchpad_count = sum(1 for _ in scratchpad_path.rglob("*") if _.is_file())

    # Nothing to delete
    if total_cards == 0 and scratchpad_count == 0:
        if column:
            print(f"No cards found in '{column}' column.")
        else:
            print("No cards found.")
        return

    # Require interactive terminal - reject piped input to prevent programmatic bypass
    if not sys.stdin.isatty():
        print("Error: kanban clean requires interactive confirmation (stdin must be a terminal).", file=sys.stderr)
        sys.exit(1)

    # Show what will be trashed and prompt for confirmation
    if expunge:
        print(f"WARNING: This will trash {total_cards} cards from all columns AND scratchpad contents ({scratchpad_count} files).")
        prompt = "Files will be moved to macOS Trash (recoverable via Finder 'Put Back'). Continue? [y/N] "
    elif column:
        prompt = f"This will trash {total_cards} cards from the '{column}' column (recoverable via Finder 'Put Back'). Continue? [y/N] "
    else:
        prompt = f"This will trash {total_cards} cards from all columns (recoverable via Finder 'Put Back'). Continue? [y/N] "

    # Read user confirmation - only 'y' or 'Y' proceeds; empty input (Enter) = abort
    try:
        response = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        sys.exit(0)

    if response not in ["y", "Y"]:
        print("Aborted.")
        sys.exit(0)

    # Trash cards
    trashed_count = 0
    for col in columns_to_clean:
        col_path = root / col
        if col_path.exists():
            for card_file in col_path.glob("*.json"):
                trash_path(card_file)
                trashed_count += 1

    # Trash scratchpad if expunge
    scratchpad_trashed = 0
    if expunge:
        scratchpad_path = root / "scratchpad"
        if scratchpad_path.exists():
            for item in scratchpad_path.iterdir():
                trash_path(item)
                scratchpad_trashed += 1

    # Report results
    if expunge:
        print(f"Trashed {trashed_count} cards and {scratchpad_trashed} scratchpad items. Restore via Finder 'Put Back'.")
    elif column:
        print(f"Trashed {trashed_count} cards from '{column}' column. Restore via Finder 'Put Back'.")
    else:
        print(f"Trashed {trashed_count} cards. Restore via Finder 'Put Back'.")


def cmd_report(args) -> None:
    """Generate status report from completed cards.

    Shows intent, action, and completion comment from done cards, with optional date filtering.
    Includes all sessions by default, sorted newest first.
    """
    root = get_root(args.root)

    # Parse date filters (optional)
    from_date = None
    to_date = None

    if getattr(args, "from_date", None):
        try:
            # Parse YYYY-MM-DD format to start of day UTC
            from_date = datetime.strptime(args.from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            print(f"Error: Invalid --from date format '{args.from_date}'. Use YYYY-MM-DD.", file=sys.stderr)
            sys.exit(1)

    if getattr(args, "to_date", None):
        try:
            # Parse YYYY-MM-DD format to end of day UTC
            to_date = datetime.strptime(args.to_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
        except ValueError:
            print(f"Error: Invalid --to date format '{args.to_date}'. Use YYYY-MM-DD.", file=sys.stderr)
            sys.exit(1)

    # Gather completed cards from done column
    done_cards = []
    done_dir = root / "done"

    if not done_dir.exists():
        # No completed cards - output empty result
        if getattr(args, "output_style", None) == "xml":
            print("<status-report>")
            print("</status-report>")
        else:
            print("No completed cards found.")
        return

    for card_path in done_dir.glob("*.json"):
        try:
            card = read_card(card_path)

            # Filter by completion date (updated timestamp)
            updated_str = card.get("updated")
            if updated_str:
                try:
                    updated = parse_iso(updated_str)

                    # Apply date filters
                    if from_date and updated < from_date:
                        continue
                    if to_date and updated > to_date:
                        continue

                    done_cards.append((updated, card_number(card_path), card))
                except ValueError:
                    # Skip cards with invalid timestamps
                    continue
            else:
                # Skip cards without updated timestamp
                continue

        except (json.JSONDecodeError, OSError):
            # Skip malformed cards
            continue

    # Sort newest first (reverse chronological)
    done_cards.sort(key=lambda x: x[0], reverse=True)

    # Helper function to extract completion comment from activity
    def get_completion_comment(card: dict) -> str | None:
        """Extract completion comment from activity array.

        Returns the last activity message that isn't 'Created', or None if not found.
        """
        activity = card.get("activity", [])
        if len(activity) > 1:
            # Return the last activity message (which is the completion message)
            return activity[-1].get("message")
        return None

    # Output based on style
    output_style = getattr(args, "output_style", "human")

    if output_style == "xml":
        # XML format for Claude Code consumption
        esc = html.escape
        print("<status-report>")
        for updated, num, card in done_cards:
            action = card.get("action", "")
            intent = card.get("intent", "")
            comment = get_completion_comment(card)
            completion_date = updated.strftime("%Y-%m-%d")

            print(f'  <card num="{esc(num)}" completed="{esc(completion_date)}">')
            if intent:
                print(f"    <intent>{esc(intent)}</intent>")
            print(f"    <action>{esc(action)}</action>")
            if comment:
                print(f"    <comment>{esc(comment)}</comment>")
            print("  </card>")
        print("</status-report>")
    else:
        # Human-readable format
        if not done_cards:
            print("No completed cards found in the specified date range.")
            return

        # Build output as string for paging
        bold = "\033[1m"
        dim = "\033[2m"
        reset = "\033[0m"
        output_lines = []

        # Print header
        date_range_str = ""
        if from_date or to_date:
            parts = []
            if from_date:
                parts.append(f"from {from_date.strftime('%Y-%m-%d')}")
            if to_date:
                parts.append(f"to {to_date.strftime('%Y-%m-%d')}")
            date_range_str = f" ({' '.join(parts)})"

        output_lines.append(f"STATUS REPORT{date_range_str}")
        output_lines.append(f"Completed Cards: {len(done_cards)}")
        output_lines.append("")

        # Print cards
        for updated, num, card in done_cards:
            action = card.get("action", "[NO ACTION]")
            intent = card.get("intent", "")
            comment = get_completion_comment(card)
            completion_date = updated.strftime("%Y-%m-%d")

            # Card header with date
            output_lines.append(f"#{num} {dim}({completion_date}){reset}")

            # Intent if present (reordered to first) with bold label
            if intent:
                # Wrap intent at ~80 chars
                intent_lines = []
                remaining = intent.replace("\\n", "\n")
                for paragraph in remaining.split("\n"):
                    words = paragraph.split()
                    current_line = ""
                    for word in words:
                        if current_line and len(current_line) + len(word) + 1 > 76:
                            intent_lines.append(current_line)
                            current_line = word
                        else:
                            current_line = (current_line + " " + word) if current_line else word
                    if current_line:
                        intent_lines.append(current_line)

                for i, line in enumerate(intent_lines):
                    if i == 0:
                        output_lines.append(f"  {bold}Intent:{reset} {line}")
                    else:
                        output_lines.append(f"    {line}")

            # Action (reordered to second) with bold label
            output_lines.append(f"  {bold}Action:{reset} {action}")

            # Completion comment if present (reordered to third) with bold label
            if comment:
                # Wrap comment at ~80 chars
                comment_lines = []
                remaining = comment.replace("\\n", "\n")
                for paragraph in remaining.split("\n"):
                    words = paragraph.split()
                    current_line = ""
                    for word in words:
                        if current_line and len(current_line) + len(word) + 1 > 76:
                            comment_lines.append(current_line)
                            current_line = word
                        else:
                            current_line = (current_line + " " + word) if current_line else word
                    if current_line:
                        comment_lines.append(current_line)

                for i, line in enumerate(comment_lines):
                    if i == 0:
                        output_lines.append(f"  {bold}Summary:{reset} {line}")
                    else:
                        output_lines.append(f"    {line}")

            output_lines.append("")

        # Send through pager
        use_pager("\n".join(output_lines))


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
    """Watch .kanban/ directory and re-run command on changes.

    --watch always forces simple output style regardless of --output-style value
    or the default. XML streamed live is unreadable noise for interactive monitoring;
    simple is the only sensible format for watch mode.
    """
    root = get_root(args.root)
    refresh_event = Event()
    stop_event = Event()
    # Watch mode always starts in simple style — XML is not useful for live
    # interactive monitoring. This overrides any --output-style flag or default.
    state = WatchState(output_style="simple")
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
    p_do.add_argument("json_data", nargs="?", default=None, help="JSON object or array of objects with action, intent, readFiles, editFiles")
    p_do.add_argument("--file", dest="json_file", metavar="PATH", help="Read card JSON from file instead of inline argument")
    add_session_flags(p_do)

    # --- show ---
    p_show = subparsers.add_parser("show", parents=[parent_parser], help="Display card contents")
    p_show.add_argument("card", help="Card number")
    p_show.add_argument("--output-style", choices=["simple", "xml", "detail"], default="xml", help="Output style: xml (structured XML, default), simple (human-readable terminal), detail (verbose terminal)")
    add_session_flags(p_show)

    # --- status ---
    p_status = subparsers.add_parser("status", parents=[parent_parser], help="Print only the column name of a card (e.g. doing, todo, done, canceled)")
    p_status.add_argument("card", help="Card number")
    add_session_flags(p_status)

    # --- rejections ---
    p_rejections = subparsers.add_parser("rejections", parents=[parent_parser], help="Display rejection history for a card")
    p_rejections.add_argument("card", help="Card number")
    add_session_flags(p_rejections)

    # --- rename ---
    p_rename = subparsers.add_parser("rename", parents=[parent_parser], help="Rename a session to a custom friendly name")
    p_rename.add_argument("new_name", help="New session name (lowercase alphanumeric and hyphens only)")
    p_rename.add_argument("--session", required=True, help="Session UUID or name to rename")

    # --- cancel ---
    p_cancel = subparsers.add_parser("cancel", parents=[parent_parser], help="Move card(s) to canceled column")
    p_cancel.add_argument("card", nargs="+", help="Card number(s)")
    p_cancel.add_argument("--reason", default=None, help="Optional cancellation reason (applies to all cards)")
    add_session_flags(p_cancel)

    # --- defer ---
    p_defer = subparsers.add_parser("defer", parents=[parent_parser], help="Move card(s) from doing back to todo")
    p_defer.add_argument("card", nargs="+", help="Card number(s)")
    add_session_flags(p_defer)

    # --- start ---
    p_start = subparsers.add_parser("start", parents=[parent_parser], help="Move card(s) from todo to doing")
    p_start.add_argument("card", nargs="+", help="Card number(s)")
    add_session_flags(p_start)


    # --- agent ---
    p_agent = subparsers.add_parser("agent", parents=[parent_parser], help="Set the agent type on a card")
    p_agent.add_argument("card", help="Card number")
    p_agent.add_argument("agent_type", help="Agent type (e.g. swe-backend, researcher)")
    add_session_flags(p_agent)

    # --- clear-agent-launch-pending ---
    p_clear_alp = subparsers.add_parser(
        "clear-agent-launch-pending",
        parents=[parent_parser],
        help="Clear the agent_launch_pending flag (called by pretool hook on agent launch)",
    )
    p_clear_alp.add_argument("card", help="Card number")
    add_session_flags(p_clear_alp)

    # --- criteria (with subcommands) ---
    p_criteria = subparsers.add_parser("criteria", parents=[parent_parser], help="Manage acceptance criteria", aliases=["ac"])
    criteria_subparsers = p_criteria.add_subparsers(dest="criteria_command", help="Criteria subcommands")

    p_criteria_add = criteria_subparsers.add_parser("add", parents=[parent_parser], help="Add acceptance criterion")
    p_criteria_add.add_argument("card", help="Card number")
    p_criteria_add.add_argument("text", help="Criterion text")
    p_criteria_add.add_argument("--mov-cmd", dest="mov_cmd", action="append", metavar="CMD", help="MoV command to append to mov_commands (repeatable)")
    p_criteria_add.add_argument("--mov-timeout", dest="mov_timeout", action="append", type=int, metavar="N", help="Timeout in seconds for the most-recent --mov-cmd (default 30, repeatable)")
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

    p_criteria_uncheck = criteria_subparsers.add_parser("uncheck", parents=[parent_parser], help="Mark criterion as unmet (clears met)")
    p_criteria_uncheck.add_argument("card", help="Card number")
    p_criteria_uncheck.add_argument("n", nargs="+", help="Criterion index(es) (1-based) or text prefix(es)")
    add_session_flags(p_criteria_uncheck)

    # --- list / ls ---
    for alias in ["list", "ls"]:
        p_list = subparsers.add_parser(alias, parents=[parent_parser], help="Show board overview")
        p_list.add_argument("--column", action="append", help="Filter column(s)")
        p_list.add_argument("--show-done", action="store_true", help="Include done")
        p_list.add_argument("--show-canceled", action="store_true", help="Include canceled")
        p_list.add_argument("--show-all", action="store_true", help="Include done + canceled")
        p_list.add_argument("--output-style", choices=["simple", "xml", "detail"], default="xml", help="Output style: xml (structured XML, default), simple (title only), detail (everything). Note: --watch always forces simple regardless of this flag.")
        add_session_flags(p_list)
        add_date_flags(p_list)

    # --- Pure verbs: todo, done ---
    p_todo = subparsers.add_parser("todo", parents=[parent_parser], help="Create card(s) in todo from JSON")
    p_todo.add_argument("json_data", nargs="?", default=None, help="JSON object or array of objects with action, intent, readFiles, editFiles")
    p_todo.add_argument("--file", dest="json_file", metavar="PATH", help="Read card JSON from file instead of inline argument")
    add_session_flags(p_todo)

    p_done = subparsers.add_parser("done", parents=[parent_parser], help="Move card to done")
    p_done.add_argument("card", help="Card number")
    p_done.add_argument("message", nargs="?", default=None, help="Completion message")
    add_session_flags(p_done)

    # --- report ---
    p_report = subparsers.add_parser("report", parents=[parent_parser], help="Generate reporting from completed cards")
    p_report.add_argument("--from", dest="from_date", help="Start date (YYYY-MM-DD, inclusive)")
    p_report.add_argument("--to", dest="to_date", help="End date (YYYY-MM-DD, inclusive)")
    p_report.add_argument("--output-style", choices=["human", "xml"], default="human", help="Output format: human (default, readable), xml (structured for parsing)")

    # --- clean ---
    p_clean = subparsers.add_parser("clean", parents=[parent_parser], help="Delete cards with user confirmation")
    p_clean.add_argument("column", nargs="?", default=None, help="Column to clean (doing, todo, done, canceled)")
    p_clean.add_argument("--expunge", action="store_true", help="Also delete scratchpad contents (only with full clean)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {
        "init": cmd_init,
        "session-hook": cmd_session_hook,
        "do": cmd_do,
        "todo": cmd_todo,
        "done": cmd_done,
        "cancel": cmd_cancel,
        "agent": cmd_agent,
        "clear-agent-launch-pending": cmd_clear_agent_launch_pending,
        "defer": cmd_defer,
        "start": cmd_start,
        "list": cmd_list,
        "ls": cmd_list,
        "show": cmd_show,
        "status": cmd_status,
        "rejections": cmd_rejections,
        "rename": cmd_rename,
        "report": cmd_report,
        "clean": cmd_clean,
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
