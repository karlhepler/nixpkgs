#!/usr/bin/env python3
"""
claude-inspect: Claude session metrics introspection CLI

Queries ~/.claude/metrics/claudit.db (SQLite) to surface token usage,
tool calls, cost, and agent behavior by kanban session.

Commands:
  session <kanban-session>         Full session overview
  agents <kanban-session>          Per-agent row table
  tools <kanban-session>           Tool usage breakdown by agent role
  cards <kanban-session>           Card event timeline
  compare <session1> <session2>    Delta view (before/after optimization)
  list [N]                         Recent kanban sessions (default: 10)
  estimate [--type TYPE] [--model MODEL] [--batch N]
                                   Card completion time estimates from historical data
  throughput [kanban-session]      Cards completed per hour
"""

import argparse
import math
import os
import sqlite3
import sys
from datetime import datetime
from typing import Any, List, Optional, Tuple


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

DB_PATH = os.path.expanduser("~/.claude/metrics/claudit.db")


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
    """Full session overview grouped by agent type."""
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
                SUM(cache_read_tokens) as cache_read,
                SUM(cache_write_tokens) as cache_write,
                SUM(cost_usd) as cost,
                SUM(total_turns) as total_turns
            FROM agent_metrics
            WHERE kanban_session = ?
            """,
            (kanban_session,),
        ).fetchone()

        # By agent type
        by_agent = conn.execute(
            """
            SELECT
                agent,
                model,
                COUNT(*) as agents,
                SUM(input_tokens) as input_tokens,
                SUM(output_tokens) as output_tokens,
                SUM(cache_read_tokens) as cache_read,
                SUM(cache_write_tokens) as cache_write,
                SUM(cost_usd) as cost,
                SUM(total_turns) as total_turns
            FROM agent_metrics
            WHERE kanban_session = ?
            GROUP BY agent, model
            ORDER BY cost DESC
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
        print(f"  {'Cache write tokens':<30} {fmt_int(totals['cache_write']):>20}")
        print(f"  {'Cache read tokens':<30} {fmt_int(totals['cache_read']):>20}")
        print(f"  {'Total cost':<30} {fmt_cost(totals['cost']):>20}")
        print(f"  {'Total turns':<30} {fmt_int(totals['total_turns']):>20}")

        section("By Agent Type")
        headers = ["Agent", "Model", "Count", "Turns", "Input Tokens", "Output Tokens", "Cache Read", "Cache Write", "Cost"]
        rows = []
        for r in by_agent:
            rows.append([
                fmt_str(r["agent"]),
                fmt_str(r["model"]),
                fmt_str(r["agents"]),
                fmt_int(r["total_turns"]),
                fmt_int(r["input_tokens"]),
                fmt_int(r["output_tokens"]),
                fmt_int(r["cache_read"]),
                fmt_int(r["cache_write"]),
                fmt_cost(r["cost"]),
            ])
        print_table(headers, rows)

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Command: agents
# ---------------------------------------------------------------------------

def cmd_agents(kanban_session: str) -> None:
    """Per-agent row table sorted by first_seen_at."""
    conn = connect()
    try:
        rows_raw = conn.execute(
            """
            SELECT
                agent,
                model,
                card_number,
                git_repo,
                total_turns,
                input_tokens,
                output_tokens,
                cache_read_tokens,
                cache_write_tokens,
                cost_usd,
                first_seen_at
            FROM agent_metrics
            WHERE kanban_session = ?
            ORDER BY first_seen_at ASC
            """,
            (kanban_session,),
        ).fetchall()

        if not rows_raw:
            print(f"No agents found for kanban session: {kanban_session}")
            return

        print(f"Session: {kanban_session}  ({len(rows_raw)} agents)")
        print()

        headers = ["Agent", "Model", "Card", "Repo", "Turns", "Input", "Output", "Cache Read", "Cache Write", "Cost", "First Seen"]
        rows = []
        for r in rows_raw:
            agent = fmt_str(r["agent"])
            if len(agent) > 20:
                agent = agent[:17] + "..."
            rows.append([
                agent,
                fmt_str(r["model"]),
                fmt_str(r["card_number"]),
                fmt_str(r["git_repo"]),
                fmt_int(r["total_turns"]),
                fmt_int(r["input_tokens"]),
                fmt_int(r["output_tokens"]),
                fmt_int(r["cache_read_tokens"]),
                fmt_int(r["cache_write_tokens"]),
                fmt_cost(r["cost_usd"]),
                fmt_str(r["first_seen_at"]),
            ])
        print_table(headers, rows)

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Command: tools
# ---------------------------------------------------------------------------

def cmd_tools(kanban_session: str) -> None:
    """Tool usage breakdown per agent, sorted by call_count desc."""
    conn = connect()
    try:
        rows_raw = conn.execute(
            """
            SELECT
                am.agent,
                atu.tool_name,
                atu.bash_command,
                atu.bash_subcommand,
                SUM(atu.call_count) as calls
            FROM agent_tool_usage atu
            JOIN agent_metrics am ON atu.session_id = am.session_id AND atu.agent_id = am.agent_id
            WHERE am.kanban_session = ?
            GROUP BY am.agent, atu.tool_name, atu.bash_command, atu.bash_subcommand
            ORDER BY am.agent ASC, calls DESC
            """,
            (kanban_session,),
        ).fetchall()

        if not rows_raw:
            print(f"No tool usage data found for kanban session: {kanban_session}")
            return

        print(f"Session: {kanban_session}")
        print()

        # Group by agent for display
        current_agent = None
        agent_rows: List[List[str]] = []
        headers = ["Tool", "Command", "Subcommand", "Calls"]

        def flush_agent(agent: str, accumulated: List[List[str]]) -> None:
            if not accumulated:
                return
            print(f"--- {agent} ---")
            print_table(headers, accumulated)
            print()

        for r in rows_raw:
            agent = fmt_str(r["agent"])
            if agent != current_agent:
                if current_agent is not None:
                    flush_agent(current_agent, agent_rows)
                current_agent = agent
                agent_rows = []
            agent_rows.append([
                fmt_str(r["tool_name"]),
                fmt_str(r["bash_command"]) if r["bash_command"] else "-",
                fmt_str(r["bash_subcommand"]) if r["bash_subcommand"] else "-",
                fmt_int(r["calls"]),
            ])

        if current_agent is not None:
            flush_agent(current_agent, agent_rows)

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
    """Fetch aggregate sub-agent metrics for a session (agent_id != '' means sub-agent)."""
    return conn.execute(
        """
        SELECT
            COUNT(*) as agents,
            SUM(input_tokens) as input_tokens,
            SUM(output_tokens) as output_tokens,
            SUM(cache_read_tokens) as cache_read,
            SUM(cache_write_tokens) as cache_write,
            SUM(cost_usd) as cost,
            SUM(total_turns) as total_turns
        FROM agent_metrics
        WHERE kanban_session = ? AND agent_id != ''
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

        print(f"Sub-agent comparison (agent_id != '')")
        print()
        print(f"  {'Metric':<30} {session1:>20} {session2:>20} {'Change':>10}")
        print(f"  {'-'*30} {'-'*20} {'-'*20} {'-'*10}")

        metrics: List[Tuple[str, str, str]] = [
            ("Agents", fmt_int(a["agents"]), fmt_int(b["agents"])),
            ("Turns", fmt_int(a["total_turns"]), fmt_int(b["total_turns"])),
            ("Input tokens", fmt_int(a["input_tokens"]), fmt_int(b["input_tokens"])),
            ("Output tokens", fmt_int(a["output_tokens"]), fmt_int(b["output_tokens"])),
            ("Cache read tokens", fmt_int(a["cache_read"]), fmt_int(b["cache_read"])),
            ("Cache write tokens", fmt_int(a["cache_write"]), fmt_int(b["cache_write"])),
            ("Cost", fmt_cost(a["cost"]), fmt_cost(b["cost"])),
        ]

        raw_metrics = [
            ("Agents", a["agents"], b["agents"]),
            ("Turns", a["total_turns"], b["total_turns"]),
            ("Input tokens", a["input_tokens"], b["input_tokens"]),
            ("Output tokens", a["output_tokens"], b["output_tokens"]),
            ("Cache read tokens", a["cache_read"], b["cache_read"]),
            ("Cache write tokens", a["cache_write"], b["cache_write"]),
            ("Cost", a["cost"], b["cost"]),
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
                MIN(first_seen_at) as first_seen,
                MAX(last_seen_at) as last_seen
            FROM agent_metrics
            WHERE kanban_session IS NOT NULL AND kanban_session != '' AND kanban_session != 'unknown'
            GROUP BY kanban_session
            ORDER BY MAX(last_seen_at) DESC
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
# Command: estimate
# ---------------------------------------------------------------------------

def _percentile(sorted_values: List[float], p: float) -> float:
    """Compute the p-th percentile (0-100) from a sorted list of values."""
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_values[int(k)]
    return sorted_values[f] * (c - k) + sorted_values[c] * (k - f)


def cmd_estimate(card_type: Optional[str], model: Optional[str], batch: int, json_output: bool) -> None:
    """Card completion time estimates based on historical data."""
    conn = connect()
    try:
        # Build query with optional filters
        conditions = ["event_type = 'done'", "card_created_at IS NOT NULL", "card_completed_at IS NOT NULL"]
        params: list = []

        if card_type:
            conditions.append("card_type = ?")
            params.append(card_type)
        if model:
            conditions.append("model = ?")
            params.append(model)

        where = " AND ".join(conditions)

        rows_raw = conn.execute(
            f"""
            SELECT
                card_type,
                model,
                (julianday(card_completed_at) - julianday(card_created_at)) * 24 * 60 as minutes
            FROM kanban_card_events
            WHERE {where}
            ORDER BY card_type, model
            """,
            params,
        ).fetchall()

        if not rows_raw:
            filters = []
            if card_type:
                filters.append(f"type={card_type}")
            if model:
                filters.append(f"model={model}")
            filter_str = ", ".join(filters) if filters else "none"
            print(f"No completed card data found (filters: {filter_str})")
            return

        # Group by (card_type, model)
        groups: dict[tuple, list[float]] = {}
        for r in rows_raw:
            key = (r["card_type"] or "unknown", r["model"] or "unknown")
            minutes = float(r["minutes"])
            if minutes < 0:
                continue
            groups.setdefault(key, []).append(minutes)

        if not groups:
            print("No valid durations found (all filtered as negative — possible clock skew)")
            return

        # Sort each group for percentile calculation
        for key in groups:
            groups[key].sort()

        if json_output:
            import json as json_mod
            result: dict = {}
            for (ct, mdl), values in sorted(groups.items()):
                bucket_key = f"{ct}/{mdl}"
                p50 = _percentile(values, 50)
                p75 = _percentile(values, 75)
                p90 = _percentile(values, 90)
                entry = {
                    "n": len(values),
                    "p50_minutes": round(p50, 1),
                    "p75_minutes": round(p75, 1),
                    "p90_minutes": round(p90, 1),
                    "min_minutes": round(values[0], 1),
                    "max_minutes": round(values[-1], 1),
                }
                if batch > 1:
                    entry["batch_size"] = batch
                    entry["batch_p90_minutes"] = round(p90, 1)
                    entry["note"] = "parallel cards — wall clock equals single card time"
                result[bucket_key] = entry
            print(json_mod.dumps(result, indent=2))
            return

        # Human-readable output
        print("Card Completion Estimates (from historical data)")
        print()

        headers = ["Type/Model", "N", "P50", "P75", "P90", "Min", "Max"]
        rows = []
        for (ct, mdl), values in sorted(groups.items()):
            p50 = _percentile(values, 50)
            p75 = _percentile(values, 75)
            p90 = _percentile(values, 90)
            rows.append([
                f"{ct}/{mdl}",
                str(len(values)),
                f"{p50:.1f}m",
                f"{p75:.1f}m",
                f"{p90:.1f}m",
                f"{values[0]:.1f}m",
                f"{values[-1]:.1f}m",
            ])
        print_table(headers, rows)

        if batch > 1:
            print()
            print(f"Batch estimate ({batch} parallel cards):")
            print(f"  Wall-clock time equals single card P90 (parallel execution).")
            # Show the slowest P90 across all groups as the batch estimate
            max_p90 = max(_percentile(v, 90) for v in groups.values())
            print(f"  Estimated wall-clock: ~{max_p90:.1f}m")

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Command: throughput
# ---------------------------------------------------------------------------

def cmd_throughput(kanban_session: Optional[str]) -> None:
    """Cards completed per hour, optionally filtered by session."""
    conn = connect()
    try:
        if kanban_session:
            # Session-specific throughput
            rows_raw = conn.execute(
                """
                SELECT
                    card_type,
                    COUNT(*) as completed,
                    MIN(card_created_at) as first_created,
                    MAX(card_completed_at) as last_completed
                FROM kanban_card_events
                WHERE kanban_session = ? AND event_type = 'done'
                    AND card_created_at IS NOT NULL AND card_completed_at IS NOT NULL
                GROUP BY card_type
                """,
                (kanban_session,),
            ).fetchall()

            if not rows_raw:
                print(f"No completed cards found for session: {kanban_session}")
                return

            # Overall session span
            span = conn.execute(
                """
                SELECT
                    MIN(card_created_at) as first_created,
                    MAX(card_completed_at) as last_completed,
                    COUNT(*) as total_completed
                FROM kanban_card_events
                WHERE kanban_session = ? AND event_type = 'done'
                    AND card_created_at IS NOT NULL AND card_completed_at IS NOT NULL
                """,
                (kanban_session,),
            ).fetchone()

            print(f"Throughput: {kanban_session}")
            print()

            if span and span["first_created"] and span["last_completed"]:

                first = datetime.fromisoformat(str(span["first_created"]).replace("Z", "+00:00"))
                last = datetime.fromisoformat(str(span["last_completed"]).replace("Z", "+00:00"))
                span_hours = (last - first).total_seconds() / 3600
                if span_hours > 0:
                    rate = span["total_completed"] / span_hours
                    print(f"  Session span: {span_hours:.1f}h")
                    print(f"  Cards completed: {span['total_completed']}")
                    print(f"  Overall rate: {rate:.1f} cards/hour")
                else:
                    print(f"  Cards completed: {span['total_completed']}")
                    print(f"  Session span: <1 minute")
            print()

            headers = ["Type", "Completed", "Rate (cards/hr)"]
            rows = []
            for r in rows_raw:

                if r["first_created"] and r["last_completed"]:
                    first = datetime.fromisoformat(str(r["first_created"]).replace("Z", "+00:00"))
                    last = datetime.fromisoformat(str(r["last_completed"]).replace("Z", "+00:00"))
                    span_hours = (last - first).total_seconds() / 3600
                    rate = r["completed"] / span_hours if span_hours > 0 else 0
                    rows.append([
                        fmt_str(r["card_type"]),
                        str(r["completed"]),
                        f"{rate:.1f}",
                    ])
                else:
                    rows.append([
                        fmt_str(r["card_type"]),
                        str(r["completed"]),
                        "-",
                    ])
            print_table(headers, rows)

        else:
            # Aggregate throughput across all sessions
            rows_raw = conn.execute(
                """
                SELECT
                    kanban_session,
                    COUNT(*) as completed,
                    MIN(card_created_at) as first_created,
                    MAX(card_completed_at) as last_completed
                FROM kanban_card_events
                WHERE event_type = 'done'
                    AND card_created_at IS NOT NULL AND card_completed_at IS NOT NULL
                    AND kanban_session IS NOT NULL AND kanban_session != ''
                GROUP BY kanban_session
                ORDER BY MAX(card_completed_at) DESC
                LIMIT 20
                """,
            ).fetchall()

            if not rows_raw:
                print("No completed cards found.")
                return

            print("Throughput by Session (last 20)")
            print()

            headers = ["Session", "Cards", "Span", "Rate (cards/hr)"]
            rows = []
            for r in rows_raw:

                if r["first_created"] and r["last_completed"]:
                    first = datetime.fromisoformat(str(r["first_created"]).replace("Z", "+00:00"))
                    last = datetime.fromisoformat(str(r["last_completed"]).replace("Z", "+00:00"))
                    span_hours = (last - first).total_seconds() / 3600
                    if span_hours > 0:
                        rate = r["completed"] / span_hours
                        if span_hours >= 1:
                            span_str = f"{span_hours:.1f}h"
                        else:
                            span_str = f"{span_hours * 60:.0f}m"
                        rows.append([
                            fmt_str(r["kanban_session"]),
                            str(r["completed"]),
                            span_str,
                            f"{rate:.1f}",
                        ])
                    else:
                        rows.append([
                            fmt_str(r["kanban_session"]),
                            str(r["completed"]),
                            "<1m",
                            "-",
                        ])
                else:
                    rows.append([
                        fmt_str(r["kanban_session"]),
                        str(r["completed"]),
                        "-",
                        "-",
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
  claude-inspect estimate
  claude-inspect estimate --type work --model sonnet
  claude-inspect estimate --type work --batch 5
  claude-inspect estimate --json
  claude-inspect throughput
  claude-inspect throughput kind-vale
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

    # estimate
    estimate_parser = subparsers.add_parser("estimate", help="Card completion time estimates from historical data")
    estimate_parser.add_argument("--type", dest="card_type", choices=["work", "review", "research"], help="Filter by card type")
    estimate_parser.add_argument("--model", help="Filter by model (e.g., sonnet, haiku, opus)")
    estimate_parser.add_argument("--batch", type=int, default=1, help="Estimate wall-clock for N parallel cards (default: 1)")
    estimate_parser.add_argument("--json", dest="json_output", action="store_true", help="Output as JSON (for programmatic consumption)")

    # throughput
    throughput_parser = subparsers.add_parser("throughput", help="Cards completed per hour")
    throughput_parser.add_argument("kanban_session", nargs="?", help="Kanban session name (omit for aggregate)")

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
        elif args.command == "estimate":
            cmd_estimate(args.card_type, args.model, args.batch, args.json_output)
        elif args.command == "throughput":
            cmd_throughput(args.kanban_session)
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
