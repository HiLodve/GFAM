# -*- coding: utf-8 -*-
"""Global cross-process API lock for GFAM modules.

Serializes ALL GFL server API requests between independent OS processes
(A-10 resource farming, follow-module manufacturing, greyzone, etc.)
that share the same game account.

The lock uses atomic file-creation (O_CREAT | O_EXCL) as the locking
primitive, with automatic stale-lock reaping.

Usage – call once at module import time::

    from gfam_api_lock import patch_gfl_client
    patch_gfl_client()

After patching, every ``GFLClient.send_request()`` call across all
instances in this process will acquire the cross-process API lock,
send the request, then release the lock.
"""

import os
import time
import json
import random
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
LOCK_FILE = ROOT_DIR / ".gfam_api.lock"

STALE_TIMEOUT = 20           # seconds – lock older than this is reaped
LOCK_RETRY_DELAY = 0.15      # seconds between acquisition attempts
DEFAULT_TIMEOUT = 15         # seconds to wait before giving up


class ApiLock:
    """Lightweight cross-process advisory lock for GFL API calls.

    Usage::

        lock = ApiLock()
        if lock.acquire(timeout=15):
            try:
                # ... send any API request ...
            finally:
                lock.release()
    """

    def __init__(self):
        self._held = False
        self._token = "%d_%d_%d" % (
            os.getpid(),
            int(time.time() * 1000) % 1000000,
            random.randint(1, 99999),
        )

    # ── public API ──────────────────────────────────────────────────

    def acquire(self, timeout=DEFAULT_TIMEOUT):
        """Try to acquire the lock within *timeout* seconds.

        Returns True on success, False on timeout.
        """
        deadline = time.time() + timeout
        while True:
            self._reap_stale()
            if self._try_acquire():
                return True
            if time.time() >= deadline:
                return False
            time.sleep(LOCK_RETRY_DELAY + random.random() * 0.05)

    def release(self):
        """Release the lock if currently held."""
        if self._held:
            try:
                LOCK_FILE.unlink()
            except OSError:
                pass
            self._held = False

    def __enter__(self):
        ok = self.acquire()
        if not ok:
            raise TimeoutError(
                "Could not acquire cross-process API lock within %ds" % DEFAULT_TIMEOUT
            )
        return self

    def __exit__(self, *exc):
        self.release()
        return False

    # ── internal helpers ────────────────────────────────────────────

    def _try_acquire(self):
        """Attempt one atomic lock-file creation."""
        try:
            fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, json.dumps({
                "pid": os.getpid(),
                "time": time.time(),
                "token": self._token,
            }).encode("utf-8"))
            os.close(fd)
            self._held = True
            return True
        except (FileExistsError, OSError):
            return False

    def _reap_stale(self):
        """Remove lock files that are older than STALE_TIMEOUT."""
        try:
            if not LOCK_FILE.exists():
                return
            raw = LOCK_FILE.read_text(encoding="utf-8", errors="replace")
            data = json.loads(raw)
            lock_time = float(data.get("time", 0))
            if time.time() - lock_time > STALE_TIMEOUT:
                LOCK_FILE.unlink()
        except (json.JSONDecodeError, OSError, ValueError, TypeError, KeyError):
            try:
                LOCK_FILE.unlink()
            except OSError:
                pass


# ── GFLClient monkey-patch ─────────────────────────────────────────

_patched = False


def patch_gfl_client():
    """Monkey-patch GFLClient.send_request to use the global API lock.

    Safe to call multiple times – only patches once.
    ENABLED by default. Set env GFAM_DISABLE_API_LOCK=1 to disable.
    """
    global _patched
    if _patched:
        return
    if str(os.environ.get("GFAM_DISABLE_API_LOCK") or "").strip().lower() in ("1", "true", "yes", "on"):
        return
    try:
        from gflzirc import GFLClient
    except ImportError:
        return

    _original_send = GFLClient.send_request

    def _locked_send_request(self, endpoint, payload, max_retries=3, timeout=15):
        lock = ApiLock()
        acquired = lock.acquire(timeout=DEFAULT_TIMEOUT)
        if not acquired:
            # Lock contention too high – still try the request without lock
            # (better to risk error:7 than to block indefinitely)
            pass
        try:
            return _original_send(self, endpoint, payload, max_retries, timeout)
        finally:
            if acquired:
                lock.release()

    GFLClient.send_request = _locked_send_request
    _patched = True
