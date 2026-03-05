#!/usr/bin/env python3
"""
claude-inspect: Claude session metrics introspection CLI

Queries ~/.claude/metrics/claude-metrics.db (SQLite) to surface token usage,
tool calls, cost, and agent behavior by kanban session.

Commands:
  session <kanban-session>         Full session overview
  agents <kanban-session>          Per-agent row table
  tools <kanban-session>           Tool usage breakdown by agent role
  cards <kanban-session>           Card event timeline
  compare <session1> <session2>    Delta view (before/after optimization)
  list [N]                         Recent kanban sessions (default: 10)
"""

import argparse
import os
import sqlite3
import sys
from typing import Any, List, Optional, Tuple


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

DB_PATH = os.path.expanduser("~/.claude/metrics/claude-metrics.db")


def connect() -> sqlite3.Connection:
    """Open a read-only connection to the metrics DB."""
    if not os.path.exists(DB_PATH):
        print(f"Error: metrics DB not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def fmt_int(v: Any) -> str:
    """Format integer with comma separators; handle None."""
    if v is None:
        return "-"
    try:
        return f"{int(v):,}"
    except (TypeError, ValueError):
        return str(v)


def fmt_cost(v: Any) -> str:
    """Format cost as $X.XXXX; handle None."""
    if v is None:
        return "-"
    try:
        return f"${float(v):.4f}"
    except (TypeError, ValueError):
        return str(v)


def fmt_float(v: Any, decimals: int = 2) -> str:
    """Format float; handle None."""
    if v is None:
        return "-"
    try:
        return f"{float(v):.{decimals}f}"
    except (TypeError, ValueError):
        return str(v)


def fmt_str(v: Any) -> str:
    """Return string representation; replace None with dash."""
    if v is None:
        return "-"
    return str(v)


def pct_change(old: Any, new: Any) -> str:
    """Compute % change from old to new, return formatted string."""
    try:
        o = float(old) if old is not None else 0.0
        n = float(new) if new is not None else 0.0
        if o == 0:
            return "n/a"
        delta = ((n - o) / o) * 100
        sign = "+" if delta >= 0 else ""
        return f"{sign}{delta:.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def print_table(headers: List[str], rows: List[List[str]]) -> None:
    """Print a padded table with a header row and separator."""
    if not rows:
        widths = [len(h) for h in headers]
    else:
        widths = [max(len(h), max(len(r[i]) for r in rows)) for i, h in enumerate(headers)]

    sep = "  ".join("-" * w for w in widths)
    header_row = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(header_row)
    print(sep)
    for row in rows:
        print("  ".join(str(row[i]).ljust(widths[i]) for i in range(len(headers))))


def section(title: str) -> None:
    """Print a section header."""
    print()
    print(f"=== {title} ===")
    print()


# ---------------------------------------------------------------------------
# Command: session
# ---------------------------------------------------------------------------

def cmd_session(kanban_session: str) -> None:
    """Full session overview grouped by parent vs sub-agents."""
    conn = connect()
    try:
        # Total agent count
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM agent_metrics WHERE kanban_session = ?",
            (kanban_session,),
        ).fetchone()
        if row is None or row["cnt"] == 0:
            print(f"No data found for kanban session: {kanban_session}")
            return

        total_agents = row["cnt"]

        # Aggregate totals
        totals = conn.execute(
            """
            SELECT
                SUM(input_tokens) as input_tokens,
                SUM(output_tokens) as output_tokens,
                SUM(cache_creation_5m_tokens) as cache_creation_5m,
                SUM(cache_creation_1h_tokens) as cache_creation_1h,
                SUM(cache_read_tokens) as cache_read,
                SUM(cost_usd) as cost,
                SUM(tool_calls) as tool_calls,
                SUM(tool_errors) as tool_errors,
                SUM(turns) as turns,
                SUM(duration_seconds) as duration_secs
            FROM agent_metrics
            WHERE kanban_session = ?
            """,
            (kanban_session,),
        ).fetchone()

        # By is_sidechain
        by_chain = conn.execute(
            """
            SELECT
                is_sidechain,
                COUNT(*) as agents,
                SUM(input_tokens) as input_tokens,
                SUM(output_tokens) as output_tokens,
                SUM(cache_read_tokens) as cache_read,
                SUM(cost_usd) as cost,
                SUM(tool_calls) as tool_calls,
                SUM(turns) as turns
            FROM agent_metrics
            WHERE kanban_session = ?
            GROUP BY is_sidechain
            """,
            (kanban_session,),
        ).fetchall()

        print(f"Session: {kanban_session}")
        print(f"Total agents: {total_agents}")

        print()
        print(f"  {'Metric':<30} {'Value':>20}")
        print(f"  {'-'*30} {'-'*20}")
        print(f"  {'Input tokens':<30} {fmt_int(totals['input_tokens']):>20}")
        print(f"  {'Output tokens':<30} {fmt_int(totals['output_tokens']):>20}")
        print(f"  {'Cache creation (5m) tokens':<30} {fmt_int(totals['cache_creation_5m']):>20}")
        print(f"  {'Cache creation (1h) tokens':<30} {fmt_int(totals['cache_creation_1h']):>20}")
        print(f"  {'Cache read tokens':<30} {fmt_int(totals['cache_read']):>20}")
        print(f"  {'Total cost':<30} {fmt_cost(totals['cost']):>20}")
        print(f"  {'Total tool calls':<30} {fmt_int(totals['tool_calls']):>20}")
        print(f"  {'Total tool errors':<30} {fmt_int(totals['tool_errors']):>20}")
        print(f"  {'Total turns':<30} {fmt_int(totals['turns']):>20}")
        if totals["duration_secs"] is not None:
            minutes = int(totals["duration_secs"] // 60)
            secs = int(totals["duration_secs"] % 60)
            print(f"  {'Total duration':<30} {f'{minutes}m {secs}s':>20}")

        section("By Agent Type")
        headers = ["Type", "Agents", "Turns", "Input Tokens", "Output Tokens", "Cache Read", "Cost", "Tool Calls"]
        rows = []
        for r in by_chain:
            agent_type = "sub-agent" if r["is_sidechain"] else "parent"
            rows.append([
                agent_type,
                fmt_str(r["agents"]),
                fmt_int(r["turns"]),
                fmt_int(r["input_tokens"]),
                fmt_int(r["output_tokens"]),
                fmt_int(r["cache_read"]),
                fmt_cost(r["cost"]),
                fmt_int(r["tool_calls"]),
            ])
        print_table(headers, rows)

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Command: agents
# ---------------------------------------------------------------------------

def cmd_agents(kanban_session: str) -> None:
    """Per-agent row table sorted by recorded_at."""
    conn = connect()
    try:
        rows_raw = conn.execute(
            """
            SELECT
                role,
                model,
                turns,
                input_tokens,
                output_tokens,
                cache_read_tokens,
                cost_usd,
                tool_calls,
                is_sidechain,
                recorded_at
            FROM agent_metrics
            WHERE kanban_session = ?
            ORDER BY recorded_at ASC
            """,
            (kanban_session,),
        ).fetchall()

        if not rows_raw:
            print(f"No agents found for kanban session: {kanban_session}")
            return

        print(f"Session: {kanban_session}  ({len(rows_raw)} agents)")
        print()

        headers = ["Role", "Model", "Type", "Turns", "Input", "Output", "Cache Read", "Cost", "Tool Calls", "Recorded At"]
        rows = []
        for r in rows_raw:
            agent_type = "sub" if r["is_sidechain"] else "parent"
            role = fmt_str(r["role"])
            # Truncate long role names for readability
            if len(role) > 30:
                role = role[:27] + "..."
            rows.append([
                role,
                fmt_str(r["model"]),
                agent_type,
                fmt_int(r["turns"]),
                fmt_int(r["input_tokens"]),
                fmt_int(r["output_tokens"]),
                fmt_int(r["cache_read_tokens"]),
                fmt_cost(r["cost_usd"]),
                fmt_int(r["tool_calls"]),
                fmt_str(r["recorded_at"]),
            ])
        print_table(headers, rows)

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Command: tools
# ---------------------------------------------------------------------------

def cmd_tools(kanban_session: str) -> None:
    """Tool usage breakdown per agent role, sorted by call_count desc."""
    conn = connect()
    try:
        rows_raw = conn.execute(
            """
            SELECT
                atu.role,
                atu.tool_name,
                SUM(atu.call_count) as calls,
                SUM(atu.error_count) as errors
            FROM agent_tool_usage atu
            JOIN agent_metrics am ON atu.session_id = am.session_id
            WHERE am.kanban_session = ?
            GROUP BY atu.role, atu.tool_name
            ORDER BY atu.role ASC, calls DESC
            """,
            (kanban_session,),
        ).fetchall()

        if not rows_raw:
            print(f"No tool usage data found for kanban session: {kanban_session}")
            return

        print(f"Session: {kanban_session}")
        print()

        # Group by role for display
        current_role = None
        role_rows: List[List[str]] = []
        headers = ["Tool", "Calls", "Errors"]

        def flush_role(role: str, accumulated: List[List[str]]) -> None:
            if not accumulated:
                return
            print(f"--- {role} ---")
            print_table(headers, accumulated)
            print()

        for r in rows_raw:
            role = fmt_str(r["role"])
            if role != current_role:
                if current_role is not None:
                    flush_role(current_role, role_rows)
                current_role = role
                role_rows = []
            role_rows.append([
                fmt_str(r["tool_name"]),
                fmt_int(r["calls"]),
                fmt_int(r["errors"]),
            ])

        if current_role is not None:
            flush_role(current_role, role_rows)

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Command: cards
# ---------------------------------------------------------------------------

def cmd_cards(kanban_session: str) -> None:
    """Card event timeline with duration where available."""
    conn = connect()
    try:
        rows_raw = conn.execute(
            """
            SELECT
                card_number,
                card_type,
                event_type,
                model,
                from_column,
                to_column,
                recorded_at,
                card_created_at,
                card_completed_at,
                persona
            FROM kanban_card_events
            WHERE kanban_session = ?
            ORDER BY recorded_at ASC
            """,
            (kanban_session,),
        ).fetchall()

        if not rows_raw:
            print(f"No card events found for kanban session: {kanban_session}")
            return

        print(f"Session: {kanban_session}  ({len(rows_raw)} events)")
        print()

        headers = ["Card", "Type", "Event", "Model", "Transition", "Duration", "Recorded At"]
        rows = []
        for r in rows_raw:
            # Build column transition string
            from_col = fmt_str(r["from_column"])
            to_col = fmt_str(r["to_column"])
            if from_col != "-" and to_col != "-":
                transition = f"{from_col}->{to_col}"
            elif to_col != "-":
                transition = f"->{to_col}"
            elif from_col != "-":
                transition = f"{from_col}->"
            else:
                transition = "-"

            # Compute duration if both timestamps available
            duration = "-"
            if r["card_created_at"] and r["card_completed_at"]:
                try:
                    from datetime import datetime
                    created = datetime.fromisoformat(str(r["card_created_at"]).replace("Z", "+00:00"))
                    completed = datetime.fromisoformat(str(r["card_completed_at"]).replace("Z", "+00:00"))
                    delta = completed - created
                    total_secs = int(delta.total_seconds())
                    h = total_secs // 3600
                    m = (total_secs % 3600) // 60
                    s = total_secs % 60
                    if h > 0:
                        duration = f"{h}h{m}m{s}s"
                    elif m > 0:
                        duration = f"{m}m{s}s"
                    else:
                        duration = f"{s}s"
                except Exception:
                    duration = "-"

            rows.append([
                fmt_str(r["card_number"]),
                fmt_str(r["card_type"]),
                fmt_str(r["event_type"]),
                fmt_str(r["model"]),
                transition,
                duration,
                fmt_str(r["recorded_at"]),
            ])
        print_table(headers, rows)

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Command: compare
# ---------------------------------------------------------------------------

def _session_sub_totals(conn: sqlite3.Connection, kanban_session: str) -> Optional[sqlite3.Row]:
    """Fetch aggregate sub-agent metrics for a session."""
    return conn.execute(
        """
        SELECT
            COUNT(*) as agents,
            SUM(input_tokens) as input_tokens,
            SUM(output_tokens) as output_tokens,
            SUM(cache_read_tokens) as cache_read,
            SUM(cost_usd) as cost,
            SUM(tool_calls) as tool_calls,
            SUM(turns) as turns
        FROM agent_metrics
        WHERE kanban_session = ? AND is_sidechain = 1
        """,
        (kanban_session,),
    ).fetchone()


def cmd_compare(session1: str, session2: str) -> None:
    """Delta view: side-by-side sub-agent metrics with % change."""
    conn = connect()
    try:
        a = _session_sub_totals(conn, session1)
        b = _session_sub_totals(conn, session2)

        if a is None or a["agents"] == 0:
            print(f"No sub-agent data found for session: {session1}")
            return
        if b is None or b["agents"] == 0:
            print(f"No sub-agent data found for session: {session2}")
            return

        print(f"Sub-agent comparison (is_sidechain=1)")
        print()
        print(f"  {'Metric':<30} {session1:>20} {session2:>20} {'Change':>10}")
        print(f"  {'-'*30} {'-'*20} {'-'*20} {'-'*10}")

        metrics: List[Tuple[str, str, str]] = [
            ("Agents", fmt_int(a["agents"]), fmt_int(b["agents"])),
            ("Turns", fmt_int(a["turns"]), fmt_int(b["turns"])),
            ("Input tokens", fmt_int(a["input_tokens"]), fmt_int(b["input_tokens"])),
            ("Output tokens", fmt_int(a["output_tokens"]), fmt_int(b["output_tokens"])),
            ("Cache read tokens", fmt_int(a["cache_read"]), fmt_int(b["cache_read"])),
            ("Cost", fmt_cost(a["cost"]), fmt_cost(b["cost"])),
            ("Tool calls", fmt_int(a["tool_calls"]), fmt_int(b["tool_calls"])),
        ]

        raw_metrics = [
            ("Agents", a["agents"], b["agents"]),
            ("Turns", a["turns"], b["turns"]),
            ("Input tokens", a["input_tokens"], b["input_tokens"]),
            ("Output tokens", a["output_tokens"], b["output_tokens"]),
            ("Cache read tokens", a["cache_read"], b["cache_read"]),
            ("Cost", a["cost"], b["cost"]),
            ("Tool calls", a["tool_calls"], b["tool_calls"]),
        ]

        for (label, av, bv), (_, a_raw, b_raw) in zip(metrics, raw_metrics):
            change = pct_change(a_raw, b_raw)
            print(f"  {label:<30} {av:>20} {bv:>20} {change:>10}")

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Command: list
# ---------------------------------------------------------------------------

def cmd_list(n: int) -> None:
    """List N most recent kanban sessions with total cost and agent count."""
    conn = connect()
    try:
        rows_raw = conn.execute(
            """
            SELECT
                kanban_session,
                COUNT(*) as agents,
                SUM(cost_usd) as total_cost,
                MIN(recorded_at) as first_seen,
                MAX(last_seen_at) as last_seen
            FROM agent_metrics
            WHERE kanban_session IS NOT NULL AND kanban_session != ''
            GROUP BY kanban_session
            ORDER BY MAX(recorded_at) DESC
            LIMIT ?
            """,
            (n,),
        ).fetchall()

        if not rows_raw:
            print("No kanban sessions found in the metrics DB.")
            return

        print(f"Recent kanban sessions (last {n}):")
        print()

        headers = ["Session", "Agents", "Total Cost", "First Seen", "Last Seen"]
        rows = []
        for r in rows_raw:
            rows.append([
                fmt_str(r["kanban_session"]),
                fmt_int(r["agents"]),
                fmt_cost(r["total_cost"]),
                fmt_str(r["first_seen"]),
                fmt_str(r["last_seen"]),
            ])
        print_table(headers, rows)

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="claude-inspect",
        description="Introspect Claude session metrics from the SQLite metrics DB",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  claude-inspect list
  claude-inspect list 20
  claude-inspect session kind-vale
  claude-inspect agents kind-vale
  claude-inspect tools kind-vale
  claude-inspect cards kind-vale
  claude-inspect compare kind-vale swift-falcon
""",
    )

    subparsers = parser.add_subparsers(dest="command", help="Subcommand")

    # session
    session_parser = subparsers.add_parser("session", help="Full session overview")
    session_parser.add_argument("kanban_session", help="Kanban session name")

    # agents
    agents_parser = subparsers.add_parser("agents", help="Per-agent row table")
    agents_parser.add_argument("kanban_session", help="Kanban session name")

    # tools
    tools_parser = subparsers.add_parser("tools", help="Tool usage breakdown by agent role")
    tools_parser.add_argument("kanban_session", help="Kanban session name")

    # cards
    cards_parser = subparsers.add_parser("cards", help="Card event timeline")
    cards_parser.add_argument("kanban_session", help="Kanban session name")

    # compare
    compare_parser = subparsers.add_parser("compare", help="Delta view for two sessions")
    compare_parser.add_argument("session1", help="Baseline kanban session")
    compare_parser.add_argument("session2", help="Comparison kanban session")

    # list
    list_parser = subparsers.add_parser("list", help="List recent kanban sessions")
    list_parser.add_argument("n", nargs="?", type=int, default=10, help="Number of sessions to show (default: 10)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(2)

    try:
        if args.command == "session":
            cmd_session(args.kanban_session)
        elif args.command == "agents":
            cmd_agents(args.kanban_session)
        elif args.command == "tools":
            cmd_tools(args.kanban_session)
        elif args.command == "cards":
            cmd_cards(args.kanban_session)
        elif args.command == "compare":
            cmd_compare(args.session1, args.session2)
        elif args.command == "list":
            cmd_list(args.n)
        else:
            print(f"Unknown command: {args.command}", file=sys.stderr)
            sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
