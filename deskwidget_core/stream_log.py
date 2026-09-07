"""Local, append-only record of each talent's live-start/live-end transitions
(see refresh.py's check_one(), which is the only writer), read back by
menus.py's stream history viewer. One JSON object per line rather than a
single JSON array so a crash mid-write only ever loses the last unflushed
line instead of corrupting the whole file.
"""
import json
import threading
import time

from .paths import ROOT, log_error

STREAM_LOG_PATH = ROOT / "stream_history.jsonl"
# Keeps the file from growing without bound over a long uptime; trimmed in
# batches (see _TRIM_CHECK_INTERVAL) rather than on every single write, so a
# busy VT-variant refresh cycle (many talents, many transitions at once)
# doesn't pay a full read-rewrite of the file per event.
MAX_ENTRIES = 2000
_TRIM_CHECK_INTERVAL = 100

_lock = threading.Lock()
_writes_since_trim = 0


def record_event(production_id, name, event, title=None, url=None):
    """event is "start" or "end". Called from refresh_worker()'s background
    threads (one per talent), so the file write itself is guarded by _lock --
    multiple talents can transition in the same refresh cycle.
    """
    global _writes_since_trim
    entry = {"ts": time.time(), "production_id": production_id, "name": name, "event": event}
    if title:
        entry["title"] = title
    if url:
        entry["url"] = url
    line = json.dumps(entry, ensure_ascii=False)
    with _lock:
        try:
            with STREAM_LOG_PATH.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError as error:
            log_error("stream_log", error)
            return
        _writes_since_trim += 1
        if _writes_since_trim >= _TRIM_CHECK_INTERVAL:
            _writes_since_trim = 0
            _trim_locked()


def _trim_locked():
    # Must only be called with _lock already held.
    try:
        lines = STREAM_LOG_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) <= MAX_ENTRIES:
        return
    try:
        STREAM_LOG_PATH.write_text("\n".join(lines[-MAX_ENTRIES:]) + "\n", encoding="utf-8")
    except OSError as error:
        log_error("stream_log", error)


def load_events(limit=None):
    """Newest-first list of event dicts. A line that fails to parse (rare --
    e.g. truncated by a crash mid-write, see the module docstring) is skipped
    rather than aborting the whole read.
    """
    try:
        lines = STREAM_LOG_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    events = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    events.reverse()
    return events[:limit] if limit is not None else events
