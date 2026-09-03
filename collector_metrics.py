from __future__ import annotations

import logging
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Any


@dataclass
class ApiMetricsSnapshot:
    calls: int
    successes: int
    failures: int
    rate_limits: int
    timeouts: int
    elapsed_seconds: float


class ApiMetrics:
    def __init__(self, platform: str, logger: logging.Logger | None = None) -> None:
        self.platform = platform
        self.logger = logger or logging.getLogger("collector.metrics")
        self._started_at = monotonic()
        self._calls = 0
        self._successes = 0
        self._failures = 0
        self._rate_limits = 0
        self._timeouts = 0
        self._lock = Lock()

    def record_success(
        self,
        *,
        operation: str,
        status_code: int | None = None,
        item_count: int | None = None,
        duration_seconds: float | None = None,
    ) -> None:
        self._record(
            operation=operation,
            status_code=status_code,
            success=True,
            item_count=item_count,
            duration_seconds=duration_seconds,
        )

    def record_failure(
        self,
        *,
        operation: str,
        status_code: int | None = None,
        error: str | None = None,
        timed_out: bool = False,
        duration_seconds: float | None = None,
    ) -> None:
        self._record(
            operation=operation,
            status_code=status_code,
            success=False,
            error=error,
            timed_out=timed_out,
            duration_seconds=duration_seconds,
        )

    def snapshot(self) -> ApiMetricsSnapshot:
        with self._lock:
            return ApiMetricsSnapshot(
                calls=self._calls,
                successes=self._successes,
                failures=self._failures,
                rate_limits=self._rate_limits,
                timeouts=self._timeouts,
                elapsed_seconds=monotonic() - self._started_at,
            )

    def _record(
        self,
        *,
        operation: str,
        status_code: int | None,
        success: bool,
        item_count: int | None = None,
        error: str | None = None,
        timed_out: bool = False,
        duration_seconds: float | None = None,
    ) -> None:
        with self._lock:
            self._calls += 1
            if success:
                self._successes += 1
            else:
                self._failures += 1
            if status_code == 429:
                self._rate_limits += 1
            if timed_out:
                self._timeouts += 1
            snapshot = ApiMetricsSnapshot(
                calls=self._calls,
                successes=self._successes,
                failures=self._failures,
                rate_limits=self._rate_limits,
                timeouts=self._timeouts,
                elapsed_seconds=monotonic() - self._started_at,
            )
        fields: dict[str, Any] = {
            "platform": self.platform,
            "operation": operation,
            "calls": snapshot.calls,
            "successes": snapshot.successes,
            "failures": snapshot.failures,
            "429": snapshot.rate_limits,
            "timeouts": snapshot.timeouts,
            "elapsedSeconds": round(snapshot.elapsed_seconds, 1),
        }
        if status_code is not None:
            fields["status"] = status_code
        if item_count is not None:
            fields["items"] = item_count
        if duration_seconds is not None:
            fields["durationSeconds"] = round(duration_seconds, 3)
        if error:
            fields["error"] = error[:160]
        self.logger.info("api_metrics %s", " ".join(f"{key}={value}" for key, value in fields.items()))
