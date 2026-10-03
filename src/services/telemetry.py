"""Telemetry and token usage monitoring service.

Tracks LLM invocations, token usage, non-LLM deterministic resolutions,
and estimated cost savings in real time.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TelemetryStats:
    total_messages: int = 0
    llm_calls: int = 0
    non_llm_messages: int = 0
    llm_fallbacks: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    estimated_cost_usd: float = 0.0
    start_time: float = field(default_factory=time.time)


class TelemetryManager:
    """Thread-safe singleton for tracking LLM usage efficiency."""

    _instance: TelemetryManager | None = None
    _lock = threading.Lock()

    def __new__(cls) -> TelemetryManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._stats = TelemetryStats()
                cls._instance._channel_stats = {}
            return cls._instance

    def record_message(
        self,
        channel: str = "general",
        is_llm: bool = False,
        is_fallback: bool = False,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_est: float = 0.0,
    ) -> None:
        """Record an incoming message or LLM invocation event."""
        with self._lock:
            # Global
            self._stats.total_messages += 1
            if is_llm:
                self._stats.llm_calls += 1
                if is_fallback:
                    self._stats.llm_fallbacks += 1
                self._stats.tokens_in += tokens_in
                self._stats.tokens_out += tokens_out
                self._stats.estimated_cost_usd += cost_est
            else:
                self._stats.non_llm_messages += 1

            # Per channel
            if channel not in self._channel_stats:
                self._channel_stats[channel] = TelemetryStats()
            ch_s = self._channel_stats[channel]
            ch_s.total_messages += 1
            if is_llm:
                ch_s.llm_calls += 1
                if is_fallback:
                    ch_s.llm_fallbacks += 1
                ch_s.tokens_in += tokens_in
                ch_s.tokens_out += tokens_out
                ch_s.estimated_cost_usd += cost_est
            else:
                ch_s.non_llm_messages += 1

    @property
    def total_messages(self) -> int:
        with self._lock:
            return self._stats.total_messages

    @property
    def llm_calls(self) -> int:
        with self._lock:
            return self._stats.llm_calls

    @property
    def non_llm_messages(self) -> int:
        with self._lock:
            return self._stats.non_llm_messages

    def get_metrics(self) -> dict[str, Any]:
        """Return current metrics dictionary."""
        with self._lock:
            total = self._stats.total_messages
            llm = self._stats.llm_calls
            non_llm = self._stats.non_llm_messages
            efficiency_pct = (non_llm / total * 100.0) if total > 0 else 100.0

            uptime_sec = time.time() - self._stats.start_time

            return {
                "total_messages": total,
                "llm_calls": llm,
                "non_llm_messages": non_llm,
                "llm_fallbacks": self._stats.llm_fallbacks,
                "efficiency_percentage": round(efficiency_pct, 1),
                "ratio_saved_percentage": round(efficiency_pct, 1),
                "tokens_in": self._stats.tokens_in,
                "tokens_out": self._stats.tokens_out,
                "total_tokens": self._stats.tokens_in + self._stats.tokens_out,
                "estimated_cost_usd": round(self._stats.estimated_cost_usd, 6),
                "uptime_seconds": round(uptime_sec, 1),
                "channels": {
                    ch: {
                        "total_messages": s.total_messages,
                        "llm_calls": s.llm_calls,
                        "non_llm_messages": s.non_llm_messages,
                        "efficiency_percentage": round((s.non_llm_messages / s.total_messages * 100.0) if s.total_messages > 0 else 100.0, 1),
                        "ratio_saved_percentage": round((s.non_llm_messages / s.total_messages * 100.0) if s.total_messages > 0 else 100.0, 1),
                    }
                    for ch, s in self._channel_stats.items()
                },
            }

    def reset(self) -> None:
        """Reset metrics (useful for testing)."""
        with self._lock:
            self._stats = TelemetryStats()
            self._channel_stats.clear()


# Helper instance
telemetry = TelemetryManager()
