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
  ac-rejections                    AC reviewer rejection patterns
    [--agent AGENT] [--card-type TYPE] [--model MODEL]
    [--session SESSION] [--since DATE]
    [--summary]
"""

import argparse
import json
import math
import os
import sqlite3
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

DB_PATH = os.path.expanduser("~/.claude/metrics/claudit.db")


def connect() -> sqlite3.Connection:
    """Open a read-only connection to the metrics DB."""
    if not os.path.exists(DB_PATH):
        raise RuntimeError(f"metrics DB not found at {DB_PATH}")
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
# Structured output helpers (matching prc.py house style)
# ---------------------------------------------------------------------------

def _dict_to_xml_element(parent: ET.Element, key: str, value: Any) -> None:
    """Recursively serialize a value into an XML child element under parent."""
    child = ET.SubElement(parent, key)
    if value is None:
        child.set("null", "true")
    elif isinstance(value, bool):
        child.text = "true" if value else "false"
    elif isinstance(value, (int, float)):
        child.text = str(value)
    elif isinstance(value, str):
        child.text = value
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                item_el = ET.SubElement(child, "item")
                for k, v in item.items():
                    _dict_to_xml_element(item_el, k, v)
            else:
                item_el = ET.SubElement(child, "item")
                item_el.text = str(item) if item is not None else ""
                if item is None:
                    item_el.set("null", "true")
    elif isinstance(value, dict):
        for k, v in value.items():
            _dict_to_xml_element(child, k, v)
    else:
        child.text = str(value)


def serialize_xml(result: Dict, root_tag: str = "response") -> str:
    """Serialize a response dict to an indented XML string."""
    root = ET.Element(root_tag)
    for key, value in result.items():
        _dict_to_xml_element(root, key, value)
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode", xml_declaration=False)


def emit_result(result: Dict, fmt: str) -> None:
    """Print result to stdout in the requested format."""
    if fmt == "xml":
        print(serialize_xml(result))
    else:
        # json and human both emit JSON; human is reserved for future tabular output
        print(json.dumps(result, indent=2))


def emit_error(message: str, fmt: str, code: str = "ERROR") -> None:
    """
    Emit a structured error.

    xml/json: error goes to STDOUT as structured payload (exit 1 is caller's responsibility).
    human: error goes to STDERR as plain text (exit 1 is caller's responsibility).
    """
    error_payload = {"error": message, "error_code": code}
    if fmt in ("xml", "json"):
        emit_result(error_payload, fmt)
    else:
        print(f"Error: {message}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Command: session
# ---------------------------------------------------------------------------

def cmd_session(kanban_session: str, fmt: str) -> None:
    """Full session overview grouped by agent type."""
    conn = connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM agent_metrics WHERE kanban_session = ?",
            (kanban_session,),
        ).fetchone()
        if row is None or row["cnt"] == 0:
            emit_error(f"No data found for kanban session: {kanban_session}", fmt, "NOT_FOUND")
            sys.exit(1)

        total_agents = row["cnt"]

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

        if fmt != "human":
            result = {
                "session": kanban_session,
                "total_agents": total_agents,
                "totals": {
                    "input_tokens": totals["input_tokens"],
                    "output_tokens": totals["output_tokens"],
                    "cache_write_tokens": totals["cache_write"],
                    "cache_read_tokens": totals["cache_read"],
                    "cost_usd": totals["cost"],
                    "total_turns": totals["total_turns"],
                },
                "by_agent": [
                    {
                        "agent": r["agent"],
                        "model": r["model"],
                        "count": r["agents"],
                        "total_turns": r["total_turns"],
                        "input_tokens": r["input_tokens"],
                        "output_tokens": r["output_tokens"],
                        "cache_read_tokens": r["cache_read"],
                        "cache_write_tokens": r["cache_write"],
                        "cost_usd": r["cost"],
                    }
                    for r in by_agent
                ],
            }
            emit_result(result, fmt)
            return

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

def cmd_agents(kanban_session: str, fmt: str) -> None:
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
            emit_error(f"No agents found for kanban session: {kanban_session}", fmt, "NOT_FOUND")
            sys.exit(1)

        if fmt != "human":
            result = {
                "session": kanban_session,
                "agent_count": len(rows_raw),
                "agents": [
                    {
                        "agent": r["agent"],
                        "model": r["model"],
                        "card_number": r["card_number"],
                        "git_repo": r["git_repo"],
                        "total_turns": r["total_turns"],
                        "input_tokens": r["input_tokens"],
                        "output_tokens": r["output_tokens"],
                        "cache_read_tokens": r["cache_read_tokens"],
                        "cache_write_tokens": r["cache_write_tokens"],
                        "cost_usd": r["cost_usd"],
                        "first_seen_at": r["first_seen_at"],
                    }
                    for r in rows_raw
                ],
            }
            emit_result(result, fmt)
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

def cmd_tools(kanban_session: str, fmt: str) -> None:
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
            emit_error(f"No tool usage data found for kanban session: {kanban_session}", fmt, "NOT_FOUND")
            sys.exit(1)

        if fmt != "human":
            # Group by agent for structured output
            agents_map: Dict[str, List[Dict]] = {}
            for r in rows_raw:
                agent = fmt_str(r["agent"])
                agents_map.setdefault(agent, []).append({
                    "tool_name": r["tool_name"],
                    "bash_command": r["bash_command"],
                    "bash_subcommand": r["bash_subcommand"],
                    "calls": r["calls"],
                })
            result = {
                "session": kanban_session,
                "agents": [
                    {"agent": agent, "tools": tools}
                    for agent, tools in agents_map.items()
                ],
            }
            emit_result(result, fmt)
            return

        print(f"Session: {kanban_session}")
        print()

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

def cmd_cards(kanban_session: str, fmt: str) -> None:
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
            emit_error(f"No card events found for kanban session: {kanban_session}", fmt, "NOT_FOUND")
            sys.exit(1)

        def _compute_duration(created_at: Any, completed_at: Any) -> Optional[str]:
            if not created_at or not completed_at:
                return None
            try:
                created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
                completed = datetime.fromisoformat(str(completed_at).replace("Z", "+00:00"))
                delta = completed - created
                total_secs = int(delta.total_seconds())
                h = total_secs // 3600
                m = (total_secs % 3600) // 60
                s = total_secs % 60
                if h > 0:
                    return f"{h}h{m}m{s}s"
                if m > 0:
                    return f"{m}m{s}s"
                return f"{s}s"
            except Exception:
                return None

        if fmt != "human":
            result = {
                "session": kanban_session,
                "event_count": len(rows_raw),
                "events": [
                    {
                        "card_number": r["card_number"],
                        "card_type": r["card_type"],
                        "event_type": r["event_type"],
                        "model": r["model"],
                        "from_column": r["from_column"],
                        "to_column": r["to_column"],
                        "recorded_at": r["recorded_at"],
                        "card_created_at": r["card_created_at"],
                        "card_completed_at": r["card_completed_at"],
                        "duration": _compute_duration(r["card_created_at"], r["card_completed_at"]),
                        "persona": r["persona"],
                    }
                    for r in rows_raw
                ],
            }
            emit_result(result, fmt)
            return

        print(f"Session: {kanban_session}  ({len(rows_raw)} events)")
        print()

        headers = ["Card", "Type", "Event", "Model", "Transition", "Duration", "Recorded At"]
        rows = []
        for r in rows_raw:
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

            duration = _compute_duration(r["card_created_at"], r["card_completed_at"]) or "-"

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


def cmd_compare(session1: str, session2: str, fmt: str) -> None:
    """Delta view: side-by-side sub-agent metrics with % change."""
    conn = connect()
    try:
        a = _session_sub_totals(conn, session1)
        b = _session_sub_totals(conn, session2)

        if a is None or a["agents"] == 0:
            emit_error(f"No sub-agent data found for session: {session1}", fmt, "NOT_FOUND")
            sys.exit(1)
        if b is None or b["agents"] == 0:
            emit_error(f"No sub-agent data found for session: {session2}", fmt, "NOT_FOUND")
            sys.exit(1)

        metric_keys = [
            ("agents", "Agents"),
            ("total_turns", "Turns"),
            ("input_tokens", "Input tokens"),
            ("output_tokens", "Output tokens"),
            ("cache_read", "Cache read tokens"),
            ("cache_write", "Cache write tokens"),
            ("cost", "Cost"),
        ]

        if fmt != "human":
            metrics_data = {}
            for key, label in metric_keys:
                a_val = a[key]
                b_val = b[key]
                metrics_data[key] = {
                    "label": label,
                    session1: a_val,
                    session2: b_val,
                    "pct_change": pct_change(a_val, b_val),
                }
            result = {
                "session1": session1,
                "session2": session2,
                "metrics": metrics_data,
            }
            emit_result(result, fmt)
            return

        print(f"Sub-agent comparison (agent_id != '')")
        print()
        print(f"  {'Metric':<30} {session1:>20} {session2:>20} {'Change':>10}")
        print(f"  {'-'*30} {'-'*20} {'-'*20} {'-'*10}")

        for key, label in metric_keys:
            a_raw = a[key]
            b_raw = b[key]
            if key == "cost":
                av = fmt_cost(a_raw)
                bv = fmt_cost(b_raw)
            else:
                av = fmt_int(a_raw)
                bv = fmt_int(b_raw)
            change = pct_change(a_raw, b_raw)
            print(f"  {label:<30} {av:>20} {bv:>20} {change:>10}")

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Command: list
# ---------------------------------------------------------------------------

def cmd_list(n: int, fmt: str) -> None:
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
            emit_error("No kanban sessions found in the metrics DB.", fmt, "NOT_FOUND")
            sys.exit(1)

        if fmt != "human":
            result = {
                "sessions": [
                    {
                        "session": r["kanban_session"],
                        "agents": r["agents"],
                        "total_cost_usd": r["total_cost"],
                        "first_seen": r["first_seen"],
                        "last_seen": r["last_seen"],
                    }
                    for r in rows_raw
                ],
            }
            emit_result(result, fmt)
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


def cmd_estimate(card_type: Optional[str], model: Optional[str], batch: int, fmt: str) -> None:
    """Card completion time estimates based on historical data."""
    conn = connect()
    try:
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
            emit_error(f"No completed card data found (filters: {filter_str})", fmt, "NOT_FOUND")
            sys.exit(1)

        groups: dict[tuple, list[float]] = {}
        for r in rows_raw:
            key = (r["card_type"] or "unknown", r["model"] or "unknown")
            minutes = float(r["minutes"])
            if minutes < 0:
                continue
            groups.setdefault(key, []).append(minutes)

        if not groups:
            emit_error("No valid durations found (all filtered as negative — possible clock skew)", fmt, "NO_DATA")
            sys.exit(1)

        for key in groups:
            groups[key].sort()

        if fmt != "human":
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
            emit_result(result, fmt)
            return

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
            max_p90 = max(_percentile(v, 90) for v in groups.values())
            print(f"  Estimated wall-clock: ~{max_p90:.1f}m")

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Command: throughput
# ---------------------------------------------------------------------------

def cmd_throughput(kanban_session: Optional[str], fmt: str) -> None:
    """Cards completed per hour, optionally filtered by session."""
    conn = connect()
    try:
        if kanban_session:
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
                emit_error(f"No completed cards found for session: {kanban_session}", fmt, "NOT_FOUND")
                sys.exit(1)

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

            span_hours = None
            overall_rate = None
            if span and span["first_created"] and span["last_completed"]:
                first = datetime.fromisoformat(str(span["first_created"]).replace("Z", "+00:00"))
                last = datetime.fromisoformat(str(span["last_completed"]).replace("Z", "+00:00"))
                span_hours = (last - first).total_seconds() / 3600
                if span_hours > 0:
                    overall_rate = span["total_completed"] / span_hours

            if fmt != "human":
                by_type = []
                for r in rows_raw:
                    entry: Dict[str, Any] = {
                        "card_type": r["card_type"],
                        "completed": r["completed"],
                    }
                    if r["first_created"] and r["last_completed"]:
                        first = datetime.fromisoformat(str(r["first_created"]).replace("Z", "+00:00"))
                        last = datetime.fromisoformat(str(r["last_completed"]).replace("Z", "+00:00"))
                        sh = (last - first).total_seconds() / 3600
                        entry["rate_cards_per_hour"] = round(r["completed"] / sh, 1) if sh > 0 else None
                    else:
                        entry["rate_cards_per_hour"] = None
                    by_type.append(entry)
                result = {
                    "session": kanban_session,
                    "span_hours": round(span_hours, 1) if span_hours is not None else None,
                    "total_completed": span["total_completed"] if span else None,
                    "overall_rate_cards_per_hour": round(overall_rate, 1) if overall_rate is not None else None,
                    "by_type": by_type,
                }
                emit_result(result, fmt)
                return

            print(f"Throughput: {kanban_session}")
            print()

            if span_hours is not None and span_hours > 0 and overall_rate is not None:
                print(f"  Session span: {span_hours:.1f}h")
                print(f"  Cards completed: {span['total_completed']}")
                print(f"  Overall rate: {overall_rate:.1f} cards/hour")
            elif span:
                print(f"  Cards completed: {span['total_completed']}")
                print(f"  Session span: <1 minute")
            print()

            headers = ["Type", "Completed", "Rate (cards/hr)"]
            rows = []
            for r in rows_raw:
                if r["first_created"] and r["last_completed"]:
                    first = datetime.fromisoformat(str(r["first_created"]).replace("Z", "+00:00"))
                    last = datetime.fromisoformat(str(r["last_completed"]).replace("Z", "+00:00"))
                    sh = (last - first).total_seconds() / 3600
                    rate = r["completed"] / sh if sh > 0 else 0
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
                emit_error("No completed cards found.", fmt, "NOT_FOUND")
                sys.exit(1)

            if fmt != "human":
                sessions_data = []
                for r in rows_raw:
                    entry: Dict[str, Any] = {
                        "session": r["kanban_session"],
                        "completed": r["completed"],
                    }
                    if r["first_created"] and r["last_completed"]:
                        first = datetime.fromisoformat(str(r["first_created"]).replace("Z", "+00:00"))
                        last = datetime.fromisoformat(str(r["last_completed"]).replace("Z", "+00:00"))
                        sh = (last - first).total_seconds() / 3600
                        entry["span_hours"] = round(sh, 2)
                        entry["rate_cards_per_hour"] = round(r["completed"] / sh, 1) if sh > 0 else None
                    else:
                        entry["span_hours"] = None
                        entry["rate_cards_per_hour"] = None
                    sessions_data.append(entry)
                result = {"sessions": sessions_data}
                emit_result(result, fmt)
                return

            print("Throughput by Session (last 20)")
            print()

            headers = ["Session", "Cards", "Span", "Rate (cards/hr)"]
            rows = []
            for r in rows_raw:
                if r["first_created"] and r["last_completed"]:
                    first = datetime.fromisoformat(str(r["first_created"]).replace("Z", "+00:00"))
                    last = datetime.fromisoformat(str(r["last_completed"]).replace("Z", "+00:00"))
                    sh = (last - first).total_seconds() / 3600
                    if sh > 0:
                        rate = r["completed"] / sh
                        span_str = f"{sh:.1f}h" if sh >= 1 else f"{sh * 60:.0f}m"
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
# Command: ac-rejections
# ---------------------------------------------------------------------------

def _truncate(s: str, max_len: int) -> str:
    """Truncate a string to max_len, appending '...' if truncated."""
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def _parse_rejection_reasons(raw: Optional[str]) -> List[Dict[str, str]]:
    """Parse rejection_reasons JSON array; return empty list on failure."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def cmd_ac_rejections(
    agent: Optional[str],
    card_type: Optional[str],
    model: Optional[str],
    session: Optional[str],
    since: Optional[str],
    verbose: bool,
    summary: bool,
    fmt: str,
) -> None:
    """Show redo events with rejection reasons, with optional filters."""
    conn = connect()
    try:
        conditions = [
            "event_type = 'redo'",
            "rejection_reasons IS NOT NULL",
        ]
        params: list = []

        if agent:
            conditions.append("agent = ?")
            params.append(agent)
        if card_type:
            conditions.append("card_type = ?")
            params.append(card_type)
        if model:
            conditions.append("model = ?")
            params.append(model)
        if session:
            conditions.append("kanban_session = ?")
            params.append(session)
        if since:
            conditions.append("recorded_at >= ?")
            params.append(since)

        where = " AND ".join(conditions)

        rows_raw = conn.execute(
            f"""
            SELECT
                card_number,
                kanban_session,
                agent,
                card_type,
                model,
                recorded_at,
                rejection_reasons
            FROM kanban_card_events
            WHERE {where}
            ORDER BY recorded_at DESC
            """,
            params,
        ).fetchall()

        if not rows_raw:
            emit_error("No AC rejections found matching the given filters.", fmt, "NOT_FOUND")
            sys.exit(1)

        if summary:
            pattern_counts: Dict[Tuple[str, str, str], int] = {}
            for r in rows_raw:
                a = fmt_str(r["agent"])
                ct = fmt_str(r["card_type"])
                reasons = _parse_rejection_reasons(r["rejection_reasons"])
                for item in reasons:
                    criterion = item.get("criterion", "") if isinstance(item, dict) else str(item)
                    key = (a, ct, criterion)
                    pattern_counts[key] = pattern_counts.get(key, 0) + 1

            if not pattern_counts:
                emit_error("No parseable rejection reasons found.", fmt, "NO_DATA")
                sys.exit(1)

            if fmt != "human":
                patterns = [
                    {"agent": a, "card_type": ct, "count": count, "criterion": criterion}
                    for (a, ct, criterion), count in sorted(pattern_counts.items(), key=lambda x: -x[1])
                ]
                result = {
                    "redo_event_count": len(rows_raw),
                    "patterns": patterns,
                }
                emit_result(result, fmt)
                return

            print(f"AC Rejection Patterns ({len(rows_raw)} redo events)")
            print()

            headers = ["Agent", "Card Type", "Count", "Criterion (truncated)"]
            rows_out = []
            for (a, ct, criterion), count in sorted(
                pattern_counts.items(), key=lambda x: -x[1]
            ):
                rows_out.append([
                    a,
                    ct,
                    str(count),
                    _truncate(criterion, 60),
                ])
            print_table(headers, rows_out)

        else:
            if fmt != "human":
                events = []
                for r in rows_raw:
                    reasons = _parse_rejection_reasons(r["rejection_reasons"])
                    events.append({
                        "card_number": r["card_number"],
                        "kanban_session": r["kanban_session"],
                        "agent": r["agent"],
                        "card_type": r["card_type"],
                        "model": r["model"],
                        "recorded_at": r["recorded_at"],
                        "rejection_reasons": reasons if reasons else r["rejection_reasons"],
                    })
                result = {
                    "redo_event_count": len(rows_raw),
                    "events": events,
                }
                emit_result(result, fmt)
                return

            print(f"AC Rejections ({len(rows_raw)} redo events)")
            print()

            if verbose:
                for r in rows_raw:
                    reasons = _parse_rejection_reasons(r["rejection_reasons"])
                    print(f"Card #{fmt_str(r['card_number'])}  Session: {fmt_str(r['kanban_session'])}  "
                          f"Agent: {fmt_str(r['agent'])}  Type: {fmt_str(r['card_type'])}  "
                          f"Model: {fmt_str(r['model'])}  At: {fmt_str(r['recorded_at'])}")
                    if reasons:
                        for item in reasons:
                            if isinstance(item, dict):
                                criterion = item.get("criterion", "-")
                                reason = item.get("reason", "-")
                                print(f"  Criterion: {criterion}")
                                print(f"  Reason:    {reason}")
                            else:
                                print(f"  {item}")
                    else:
                        print(f"  (unparseable: {fmt_str(r['rejection_reasons'])})")
                    print()
            else:
                headers = ["Card", "Session", "Agent", "Type", "Model", "Timestamp", "Rejection Reasons"]
                rows_out = []
                for r in rows_raw:
                    reasons = _parse_rejection_reasons(r["rejection_reasons"])
                    if reasons:
                        parts = []
                        for item in reasons:
                            if isinstance(item, dict):
                                c = item.get("criterion", "")
                                parts.append(c)
                            else:
                                parts.append(str(item))
                        reasons_str = "; ".join(parts)
                    else:
                        reasons_str = fmt_str(r["rejection_reasons"])
                    rows_out.append([
                        fmt_str(r["card_number"]),
                        fmt_str(r["kanban_session"]),
                        fmt_str(r["agent"]),
                        fmt_str(r["card_type"]),
                        fmt_str(r["model"]),
                        fmt_str(r["recorded_at"]),
                        _truncate(reasons_str, 50),
                    ])
                print_table(headers, rows_out)

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
  claude-inspect --format json list
  claude-inspect session kind-vale
  claude-inspect agents kind-vale
  claude-inspect tools kind-vale
  claude-inspect cards kind-vale
  claude-inspect compare kind-vale swift-falcon
  claude-inspect estimate
  claude-inspect estimate --type work --model sonnet
  claude-inspect estimate --type work --batch 5
  claude-inspect --format json estimate
  claude-inspect throughput
  claude-inspect throughput kind-vale
  claude-inspect ac-rejections
  claude-inspect ac-rejections --agent swe-backend
  claude-inspect ac-rejections --card-type work --since 2025-01-01
  claude-inspect --verbose ac-rejections
  claude-inspect ac-rejections --summary
""",
    )

    # Top-level flags (apply to all subcommands)
    # NOTE: This CLI uses --format (not --output-style). The kanban CLI uses
    # --output-style=xml for historical reasons; these Python CLIs standardize
    # on --format. Coordinators must use the correct flag per tool.
    parser.add_argument(
        "--format",
        choices=["xml", "json", "human"],
        default="xml",
        help="Output format (default: xml). Note: kanban uses --output-style, not --format.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output (subcommand-specific detail)",
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

    # throughput
    throughput_parser = subparsers.add_parser("throughput", help="Cards completed per hour")
    throughput_parser.add_argument("kanban_session", nargs="?", help="Kanban session name (omit for aggregate)")

    # ac-rejections
    ac_rej_parser = subparsers.add_parser("ac-rejections", help="AC reviewer rejection patterns")
    ac_rej_parser.add_argument("--agent", help="Filter by agent/specialist name")
    ac_rej_parser.add_argument("--card-type", dest="card_type", choices=["work", "review", "research"], help="Filter by card type")
    ac_rej_parser.add_argument("--model", help="Filter by model (e.g., sonnet, haiku, opus)")
    ac_rej_parser.add_argument("--session", dest="session", help="Filter by kanban session name")
    ac_rej_parser.add_argument("--since", help="Filter by date (ISO format, e.g., 2025-01-01)")
    ac_rej_parser.add_argument("--summary", action="store_true", help="Aggregate view: top rejection reason patterns by agent and card type")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(2)

    fmt = args.format
    verbose = args.verbose

    try:
        if args.command == "session":
            cmd_session(args.kanban_session, fmt)
        elif args.command == "agents":
            cmd_agents(args.kanban_session, fmt)
        elif args.command == "tools":
            cmd_tools(args.kanban_session, fmt)
        elif args.command == "cards":
            cmd_cards(args.kanban_session, fmt)
        elif args.command == "compare":
            cmd_compare(args.session1, args.session2, fmt)
        elif args.command == "list":
            cmd_list(args.n, fmt)
        elif args.command == "estimate":
            cmd_estimate(args.card_type, args.model, args.batch, fmt)
        elif args.command == "throughput":
            cmd_throughput(args.kanban_session, fmt)
        elif args.command == "ac-rejections":
            cmd_ac_rejections(
                agent=args.agent,
                card_type=args.card_type,
                model=args.model,
                session=args.session,
                since=args.since,
                verbose=verbose,
                summary=args.summary,
                fmt=fmt,
            )
        else:
            emit_error(f"Unknown command: {args.command}", fmt, "INVALID_COMMAND")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except RuntimeError as e:
        emit_error(str(e), fmt)
        sys.exit(1)
    except Exception as e:
        emit_error(f"Unexpected error: {e}", fmt)
        sys.exit(1)


if __name__ == "__main__":
    main()
