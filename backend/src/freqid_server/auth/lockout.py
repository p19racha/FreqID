# Copyright 2026 FreqID Authors. Apache-2.0 License.
"""
lockout.py: Progressive account and IP lockout manager for brute-force defense.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock


@dataclass
class LockoutRecord:
    consecutive_failures: int = 0
    lockout_count: int = 0
    locked_until: float = 0.0


class LockoutManager:
    """
    Thread-safe progressive lockout tracker per username and IP.
    Default threshold: 5 failed attempts triggers initial 900s (15 min) lockout,
    doubling with each repeated lockout.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        base_lockout_seconds: int = 900,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.base_lockout_seconds = base_lockout_seconds
        self._records: dict[str, LockoutRecord] = {}
        self._lock = Lock()

    def _get_key(self, target: str, prefix: str) -> str:
        return f"{prefix}:{target.lower()}"

    def is_locked(self, username: str, ip: str | None = None) -> tuple[bool, int]:
        """
        Checks whether username or IP is currently locked out.
        Returns (is_locked, remaining_seconds).
        """
        now = time.time()
        with self._lock:
            # Check username
            u_key = self._get_key(username, "user")
            if u_key in self._records:
                rec = self._records[u_key]
                if now < rec.locked_until:
                    return True, int(rec.locked_until - now)

            # Check IP
            if ip:
                ip_key = self._get_key(ip, "ip")
                if ip_key in self._records:
                    rec = self._records[ip_key]
                    if now < rec.locked_until:
                        return True, int(rec.locked_until - now)

        return False, 0

    def record_failure(self, username: str, ip: str | None = None) -> tuple[bool, int]:
        """
        Records a failed authentication attempt.
        Returns (is_locked, remaining_seconds).
        """
        now = time.time()
        with self._lock:
            u_key = self._get_key(username, "user")
            rec = self._records.setdefault(u_key, LockoutRecord())
            rec.consecutive_failures += 1

            if rec.consecutive_failures >= self.failure_threshold:
                rec.lockout_count += 1
                duration = self.base_lockout_seconds * (2 ** (rec.lockout_count - 1))
                rec.locked_until = now + duration
                return True, int(duration)

            if ip:
                ip_key = self._get_key(ip, "ip")
                ip_rec = self._records.setdefault(ip_key, LockoutRecord())
                ip_rec.consecutive_failures += 1
                if ip_rec.consecutive_failures >= (self.failure_threshold * 2):
                    duration = self.base_lockout_seconds
                    ip_rec.locked_until = now + duration
                    return True, int(duration)

        return False, 0

    def record_success(self, username: str, ip: str | None = None) -> None:
        """Clears failure counters upon successful authentication."""
        with self._lock:
            u_key = self._get_key(username, "user")
            if u_key in self._records:
                self._records[u_key].consecutive_failures = 0

            if ip:
                ip_key = self._get_key(ip, "ip")
                if ip_key in self._records:
                    self._records[ip_key].consecutive_failures = 0

    def unlock(self, username: str) -> bool:
        """Manually unlocks an account."""
        with self._lock:
            u_key = self._get_key(username, "user")
            if u_key in self._records:
                del self._records[u_key]
                return True
        return False
