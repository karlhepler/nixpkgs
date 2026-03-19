#!/usr/bin/env python3
"""Persistent Telegram bot daemon for Claude Code remote interaction.

Bridges between pending hook requests and the user's Telegram app,
enabling remote interaction from a phone.

Dependencies: Python stdlib only (urllib, json, threading, pathlib, time, os, queue)
"""

import json
import os
import pathlib
import queue
import threading
import time
import urllib.request
import urllib.error


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

BASE_DIR = pathlib.Path.home() / ".claude" / "telegram"
PENDING_DIR = BASE_DIR / "pending"
RESPONSES_DIR = BASE_DIR / "responses"
SESSIONS_DIR = BASE_DIR / "sessions"
SESSION_MAP_DIR = BASE_DIR / "session-map"
THREADS_DIR = BASE_DIR / "threads"
PID_FILE = BASE_DIR / "bot.pid"

LOG_DIR = pathlib.Path.home() / ".claude" / "metrics"
LOG_FILE = LOG_DIR / "telegram-bot.log"

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/"

# Rate limit between outbound messages (seconds)
OUTBOUND_RATE_LIMIT = 1.0
# Long-poll timeout (seconds sent to Telegram)
LONG_POLL_TIMEOUT = 25
# urllib socket timeout for long-poll requests (seconds)
LONG_POLL_SOCKET_TIMEOUT = 35
# Pending watcher poll interval (seconds)
PENDING_POLL_INTERVAL = 0.5


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_log_lock = threading.Lock()


def log(level: str, msg: str) -> None:
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    line = f"{ts} [{level}] {msg}\n"
    with _log_lock:
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(LOG_FILE, "a") as fh:
                fh.write(line)
        except Exception:
            pass


def log_info(msg: str) -> None:
    log("INFO", msg)


def log_error(msg: str) -> None:
    log("ERROR", msg)


# ---------------------------------------------------------------------------
# Telegram HTTP helper
# ---------------------------------------------------------------------------

def telegram_call(method: str, payload: dict, timeout: int = 10) -> dict | None:
    """Call a Telegram Bot API method. Returns parsed JSON or None on error."""
    url = API_BASE + method
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode()
        except Exception:
            pass
        log_error(f"telegram_call {method} HTTPError {exc.code}: {body}")
    except urllib.error.URLError as exc:
        log_error(f"telegram_call {method} URLError: {exc.reason}")
    except Exception as exc:
        log_error(f"telegram_call {method} unexpected error: {exc}")
    return None


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

def setup_directories() -> None:
    for directory in [PENDING_DIR, RESPONSES_DIR, SESSIONS_DIR, SESSION_MAP_DIR, THREADS_DIR, LOG_DIR]:
        directory.mkdir(parents=True, exist_ok=True)


def write_pid() -> None:
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))
    log_info(f"PID {os.getpid()} written to {PID_FILE}")


def startup_probe() -> None:
    """Call getUpdates with timeout=0 to displace stale long-poll sessions
    and prevent 409 Conflict on restart."""
    log_info("Running startup probe (getUpdates timeout=0)")
    result = telegram_call("getUpdates", {"timeout": 0}, timeout=10)
    if result and result.get("ok"):
        updates = result.get("result", [])
        log_info(f"Startup probe: {len(updates)} pending update(s) discarded")
    else:
        log_error(f"Startup probe failed or returned non-ok: {result}")


# ---------------------------------------------------------------------------
# Outbound queue thread
# ---------------------------------------------------------------------------

_outbound_queue: queue.Queue = queue.Queue()


def outbound_queue_worker() -> None:
    """Dequeues API calls one at a time with rate limiting."""
    log_info("Outbound queue thread started")
    while True:
        try:
            task = _outbound_queue.get()
            if task is None:
                break
            method, payload = task
            telegram_call(method, payload)
            time.sleep(OUTBOUND_RATE_LIMIT)
        except Exception as exc:
            log_error(f"outbound_queue_worker error: {exc}")


def enqueue(method: str, payload: dict) -> None:
    _outbound_queue.put((method, payload))


# ---------------------------------------------------------------------------
# Pending watcher thread
# ---------------------------------------------------------------------------

def _build_message_text(data: dict) -> str:
    machine_name = data.get("machine_name", "unknown")
    kanban_name = data.get("kanban_name", "unknown")
    question = data.get("question", "")
    options = data.get("options", [])

    header = f"\U0001f5a5 {machine_name} | {kanban_name}"
    separator = "\u2500" * 29
    lines = [
        header,
        separator,
        "",
        "\u2753 Claude is asking:",
        "",
        question,
    ]

    if options:
        lines.append("")
        for i, opt in enumerate(options):
            label = chr(ord("A") + i)
            lines.append(f"{label}) {opt}")

    return "\n".join(lines)


def _build_inline_keyboard(uuid: str, options: list[str]) -> dict:
    buttons = []
    for opt in options:
        buttons.append({"text": opt, "callback_data": f"{uuid}:{opt}"})
    more_button = {"text": "\u2753 More", "callback_data": f"more:{uuid}"}
    # Each option on its own row, More button last
    rows = [[btn] for btn in buttons]
    rows.append([more_button])
    return {"inline_keyboard": rows}


def _get_thread_root(kanban_name: str) -> int | None:
    thread_file = THREADS_DIR / kanban_name
    if thread_file.exists():
        try:
            return int(thread_file.read_text().strip())
        except Exception:
            return None
    return None


def _set_thread_root(kanban_name: str, message_id: int) -> None:
    thread_file = THREADS_DIR / kanban_name
    try:
        thread_file.write_text(str(message_id))
    except Exception as exc:
        log_error(f"_set_thread_root error for {kanban_name}: {exc}")


def pending_watcher_worker() -> None:
    """Polls the pending directory every 0.5s for new question files."""
    log_info("Pending watcher thread started")
    seen: set[str] = set()

    while True:
        try:
            for pending_file in sorted(PENDING_DIR.glob("*.json")):
                fname = pending_file.name
                if fname in seen:
                    continue
                seen.add(fname)

                try:
                    data = json.loads(pending_file.read_text())
                except Exception as exc:
                    log_error(f"Failed to parse pending file {fname}: {exc}")
                    continue

                # uuid is the filename without .json
                uuid = pending_file.stem
                options = data.get("options", [])
                kanban_name = data.get("kanban_name", "unknown")

                text = _build_message_text(data)
                reply_markup = _build_inline_keyboard(uuid, options)

                thread_root = _get_thread_root(kanban_name)

                payload: dict = {
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": text,
                    "reply_markup": reply_markup,
                }
                if thread_root is not None:
                    payload["reply_parameters"] = {"message_id": thread_root}

                # We need the message_id to set thread root if needed.
                # Direct call (not via queue) so we can capture the response.
                result = telegram_call("sendMessage", payload)
                if result and result.get("ok"):
                    sent_message_id = result["result"]["message_id"]
                    log_info(f"Sent pending {uuid} as message {sent_message_id}")
                    if thread_root is None:
                        _set_thread_root(kanban_name, sent_message_id)
                else:
                    log_error(f"sendMessage failed for {uuid}: {result}")

        except Exception as exc:
            log_error(f"pending_watcher_worker error: {exc}")

        time.sleep(PENDING_POLL_INTERVAL)


# ---------------------------------------------------------------------------
# Long-poll thread
# ---------------------------------------------------------------------------

def _handle_answer_callback(uuid: str, answer: str, callback_query_id: str, message_id: int, chat_id: str | int) -> None:
    # Acknowledge the callback
    enqueue("answerCallbackQuery", {"callback_query_id": callback_query_id})

    # Remove inline buttons
    enqueue("editMessageReplyMarkup", {
        "chat_id": chat_id,
        "message_id": message_id,
        "reply_markup": {"inline_keyboard": []},
    })

    # Write response file
    response_file = RESPONSES_DIR / f"{uuid}.json"
    response_data = {
        "answer": answer,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        response_file.write_text(json.dumps(response_data))
        log_info(f"Wrote response for {uuid}: {answer}")
    except Exception as exc:
        log_error(f"Failed to write response for {uuid}: {exc}")


def _handle_more_callback(uuid: str, callback_query_id: str, chat_id: str | int, thread_root_id: int | None) -> None:
    enqueue("answerCallbackQuery", {"callback_query_id": callback_query_id})

    pending_file = PENDING_DIR / f"{uuid}.json"
    if not pending_file.exists():
        enqueue("sendMessage", {
            "chat_id": chat_id,
            "text": "No additional context available (pending file not found).",
        })
        return

    try:
        data = json.loads(pending_file.read_text())
    except Exception as exc:
        log_error(f"_handle_more_callback failed to read {uuid}: {exc}")
        return

    context_snippets: list[str] = data.get("context_snippets", [])
    # Last 5 assistant snippets
    last_snippets = context_snippets[-5:] if context_snippets else []

    if not last_snippets:
        text = "No additional context snippets available."
    else:
        text = "\n\n---\n\n".join(last_snippets)

    payload: dict = {
        "chat_id": chat_id,
        "text": text,
    }
    if thread_root_id is not None:
        payload["reply_parameters"] = {"message_id": thread_root_id}

    enqueue("sendMessage", payload)


def _handle_stop_command(session: str, chat_id: str | int) -> None:
    session_file = SESSIONS_DIR / session
    if session_file.exists():
        session_file.unlink()
        log_info(f"/stop: removed session {session}")
        enqueue("sendMessage", {
            "chat_id": chat_id,
            "text": f"Session '{session}' stopped.",
        })
    else:
        enqueue("sendMessage", {
            "chat_id": chat_id,
            "text": f"Session '{session}' not found.",
        })


def _handle_stopall_command(chat_id: str | int) -> None:
    removed = []
    for session_file in SESSIONS_DIR.iterdir():
        try:
            session_file.unlink()
            removed.append(session_file.name)
        except Exception as exc:
            log_error(f"/stopall failed to remove {session_file.name}: {exc}")
    log_info(f"/stopall: removed {len(removed)} session(s)")
    if removed:
        names = ", ".join(removed)
        enqueue("sendMessage", {
            "chat_id": chat_id,
            "text": f"Stopped {len(removed)} session(s): {names}",
        })
    else:
        enqueue("sendMessage", {
            "chat_id": chat_id,
            "text": "No active sessions to stop.",
        })


def _process_update(update: dict) -> None:
    # Callback query (button press)
    if "callback_query" in update:
        cq = update["callback_query"]
        callback_query_id = cq["id"]
        callback_data = cq.get("data", "")
        chat_id = cq["message"]["chat"]["id"]
        message_id = cq["message"]["message_id"]

        if callback_data.startswith("more:"):
            uuid = callback_data[5:]
            # Try to look up thread root from the pending file
            try:
                data = json.loads((PENDING_DIR / f"{uuid}.json").read_text())
                kanban_name = data.get("kanban_name", "")
                thread_root_id = _get_thread_root(kanban_name)
            except Exception:
                thread_root_id = None
            _handle_more_callback(uuid, callback_query_id, chat_id, thread_root_id)
        else:
            # Format: <uuid>:<answer>
            colon_idx = callback_data.find(":")
            if colon_idx != -1:
                uuid = callback_data[:colon_idx]
                answer = callback_data[colon_idx + 1:]
                _handle_answer_callback(uuid, answer, callback_query_id, message_id, chat_id)
            else:
                log_error(f"Unrecognized callback_data format: {callback_data!r}")

    # Regular message (commands)
    elif "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "")

        if text.startswith("/stop "):
            session = text[6:].strip()
            if session:
                _handle_stop_command(session, chat_id)
            else:
                enqueue("sendMessage", {
                    "chat_id": chat_id,
                    "text": "Usage: /stop <session>",
                })
        elif text.strip() == "/stopall":
            _handle_stopall_command(chat_id)


def long_poll_worker() -> None:
    """Main long-poll loop. Calls getUpdates with timeout=25."""
    log_info("Long-poll thread started")
    offset = 0

    while True:
        try:
            payload: dict = {"timeout": LONG_POLL_TIMEOUT}
            if offset:
                payload["offset"] = offset

            result = telegram_call(
                "getUpdates",
                payload,
                timeout=LONG_POLL_SOCKET_TIMEOUT,
            )

            if result is None:
                # Network error; back off briefly before retrying
                time.sleep(5)
                continue

            if not result.get("ok"):
                log_error(f"getUpdates returned not-ok: {result}")
                time.sleep(5)
                continue

            updates = result.get("result", [])
            if updates:
                max_update_id = max(u["update_id"] for u in updates)
                offset = max_update_id + 1

                for update in updates:
                    try:
                        _process_update(update)
                    except Exception as exc:
                        log_error(f"_process_update error for update {update.get('update_id')}: {exc}")

        except Exception as exc:
            log_error(f"long_poll_worker unexpected error: {exc}")
            time.sleep(5)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    setup_directories()
    write_pid()
    startup_probe()

    log_info("Starting Telegram bot daemon")

    outbound_thread = threading.Thread(
        target=outbound_queue_worker,
        name="outbound-queue",
        daemon=True,
    )
    outbound_thread.start()

    watcher_thread = threading.Thread(
        target=pending_watcher_worker,
        name="pending-watcher",
        daemon=True,
    )
    watcher_thread.start()

    long_poll_thread = threading.Thread(
        target=long_poll_worker,
        name="long-poll",
        daemon=False,
    )
    long_poll_thread.start()

    # Block main thread until long-poll thread exits (it never does under normal operation)
    long_poll_thread.join()
    log_info("Long-poll thread exited — daemon shutting down")


if __name__ == "__main__":
    main()
