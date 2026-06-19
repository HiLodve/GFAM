# -*- coding: utf-8 -*-
"""Cross-process file lock for GFAM modules.

Used to serialize Gun/retireGun and Equip/retire requests between the
A-10 resource farming module and the follow-module manufacturing daemon,
which run as separate OS processes on the same game account.

The lock uses atomic file-creation (O_CREAT | O_EXCL) as the locking
primitive.  Stale locks older than ``STALE_TIMEOUT`` seconds are
automatically reaped so that a crashed process does not block others
indefinitely.
"""

import os
import time
import json
import random
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
LOCK_FILE = ROOT_DIR / ".gfam_retire.lock"

STALE_TIMEOUT = 45          # seconds – lock older than this is reaped
LOCK_RETRY_DELAY = 0.3      # seconds between acquisition attempts
DEFAULT_TIMEOUT = 8         # seconds to wait before giving up


class RetireLock:
    """Lightweight cross-process advisory lock for retirement API calls.

    Usage::

        lock = RetireLock()
        if lock.acquire(timeout=8):
            try:
                # ... send Gun/retireGun or Equip/retire ...
            finally:
                lock.release()
        else:
            # lock not acquired – skip or retry later
    """

    def __init__(self):
        self._held = False
        self._token = "%d_%d_%d" % (os.getpid(), int(time.time() * 1000) % 1000000,
                                    random.randint(1, 99999))

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
            time.sleep(LOCK_RETRY_DELAY + random.random() * 0.1)

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
            raise TimeoutError("Could not acquire cross-process retire lock within %ds" % DEFAULT_TIMEOUT)
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
            # Corrupted or unreadable lock file – remove it
            try:
                LOCK_FILE.unlink()
            except OSError:
                pass
