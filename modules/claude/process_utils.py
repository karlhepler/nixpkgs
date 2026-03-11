"""Shared process tree utilities for burns and smithers.

Injected at build time by default.nix into both scripts.
Do not add imports here — only stdlib modules that both scripts already import
(os, signal, subprocess, time) are available in the injection context.
"""


def get_all_descendants(pid):
    """Atomically snapshot all descendant PIDs of a given process.

    Takes a single ps snapshot of the entire process table, then walks the
    parent-child relationships in memory. This avoids the race condition where
    a process dies mid-traversal, gets reparented to launchd, and becomes
    invisible to subsequent pgrep -P calls.

    Works across session boundaries because ps captures PPID regardless of
    session membership — so even processes that called setsid() (e.g. Claude
    CLI spawned by ralph's portable-pty) are included as long as they were
    alive at snapshot time.
    """
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid,ppid"],
            capture_output=True,
            text=True,
            check=False
        )
        # Build parent → children map from the snapshot
        children_of: dict[int, list[int]] = {}
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) == 2:
                try:
                    child_pid = int(parts[0])
                    parent_pid = int(parts[1])
                    children_of.setdefault(parent_pid, []).append(child_pid)
                except ValueError:
                    pass  # Skip header line

        # BFS/DFS walk from the root pid using the in-memory snapshot
        descendants = []
        queue = list(children_of.get(pid, []))
        while queue:
            current = queue.pop()
            descendants.append(current)
            queue.extend(children_of.get(current, []))
        return descendants
    except Exception:
        return []  # Ignore errors during tree traversal


def kill_process_tree(pid):
    """Kill a process and all its descendants, with graceful shutdown.

    Takes an atomic snapshot of the entire process tree BEFORE sending any
    signals, then attempts a graceful SIGTERM first, waits up to 4 seconds
    for processes to exit cleanly, and escalates to SIGKILL for any survivors.

    The atomic snapshot prevents the race condition where a killed parent gets
    reparented before pgrep can find its children.

    Works across session boundaries because portable-pty calls setsid() but
    the PPID relationship is preserved and captured atomically by
    get_all_descendants.
    """
    # Capture entire descendant tree atomically before sending any signals
    all_pids = [pid] + get_all_descendants(pid)

    # Send SIGTERM to all PIDs (children first, then parents)
    for target_pid in reversed(all_pids):
        try:
            os.kill(target_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass  # Process already exited
        except PermissionError:
            pass  # Can't signal (shouldn't happen for our own processes)
        except Exception:
            pass  # Ignore other errors

    # Wait up to 4 seconds for processes to exit cleanly after SIGTERM
    deadline = time.time() + 4
    remaining = list(all_pids)
    while remaining and time.time() < deadline:
        still_alive = []
        for target_pid in remaining:
            try:
                os.kill(target_pid, 0)  # Signal 0: probe existence only
                still_alive.append(target_pid)
            except ProcessLookupError:
                pass  # Exited cleanly
            except PermissionError:
                still_alive.append(target_pid)  # Exists but we can't check
            except Exception:
                pass
        remaining = still_alive
        if remaining:
            time.sleep(0.1)

    # Escalate to SIGKILL for any survivors
    for target_pid in reversed(remaining):
        try:
            os.kill(target_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass  # Exited between the check and SIGKILL
        except PermissionError:
            pass
        except Exception:
            pass

    # Small delay to let kernel clean up
    time.sleep(0.1)
