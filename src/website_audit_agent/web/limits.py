"""Demo limits (web decisions 1–3), in memory: they reset when the Space restarts.

- 3 audits per visitor per rolling hour (visitor = first X-Forwarded-For IP).
- 30 audits per day in total — the real protection.
- 15 Gemini summaries per day; past that the checks still run without a summary.
"Daily" resets at midnight Pacific time, matching Gemini's quota.
"""

import math
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from website_audit_agent.ports import LLM, LLMError

PACIFIC = ZoneInfo("America/Los_Angeles")
HOUR = timedelta(hours=1)
SUMMARY_CAP_REASON = "daily summary limit reached"


@dataclass(frozen=True)
class Limits:
    audits_per_visitor_per_hour: int = 3
    audits_per_day: int = 30
    summaries_per_day: int = 15


@dataclass(frozen=True)
class Refusal:
    message: str
    retry_after_s: int


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def seconds_until_pacific_midnight(now: datetime) -> int:
    local = now.astimezone(PACIFIC)
    midnight = datetime.combine(local.date() + timedelta(days=1), time(0), tzinfo=PACIFIC)
    # Subtract in UTC: aware datetimes sharing a tzinfo subtract by wall clock, ignoring DST.
    return max(1, math.ceil((midnight.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds()))


class Limiter:
    def __init__(self, limits: Limits = Limits(), now: Callable[[], datetime] = utc_now) -> None:
        self.limits = limits
        self._now = now
        self._lock = threading.Lock()
        self._visits: dict[str, deque[datetime]] = {}
        self._day: date | None = None
        self._audits_today = 0
        self._summaries_today = 0

    def _roll_day(self, now: datetime) -> None:  # caller holds the lock
        today = now.astimezone(PACIFIC).date()
        if today != self._day:
            self._day = today
            self._audits_today = 0
            self._summaries_today = 0
            self._visits = {v: q for v, q in self._visits.items() if q and now - q[-1] < HOUR}

    def try_start_audit(self, visitor: str) -> Refusal | None:
        """None: allowed and counted. Refusal: not counted, with a message for the visitor."""
        with self._lock:
            now = self._now()
            self._roll_day(now)
            visits = self._visits.setdefault(visitor, deque())
            while visits and now - visits[0] >= HOUR:
                visits.popleft()

            if len(visits) >= self.limits.audits_per_visitor_per_hour:
                wait = max(1, math.ceil((visits[0] + HOUR - now).total_seconds()))
                return Refusal(
                    f"You have used your {self.limits.audits_per_visitor_per_hour} audits for this hour. "
                    f"Try again in about {math.ceil(wait / 60)} minutes.",
                    wait,
                )
            if self._audits_today >= self.limits.audits_per_day:
                return Refusal(
                    f"The demo has reached its limit of {self.limits.audits_per_day} audits for today. "
                    "It resets at midnight Pacific time.",
                    seconds_until_pacific_midnight(now),
                )
            visits.append(now)
            self._audits_today += 1
            return None

    def try_use_summary(self) -> bool:
        with self._lock:
            self._roll_day(self._now())
            if self._summaries_today >= self.limits.summaries_per_day:
                return False
            self._summaries_today += 1
            return True


class GuardedLLM:
    """Wraps the shared Gemini client for the web.

    - Each call uses one of the day's summaries; past the cap it raises LLMError,
      which summarise() turns into "summary unavailable" (checks unaffected).
    - Calls run one at a time: audits run on worker threads, and the Pacer
      inside GeminiLLM is not thread-safe.
    """

    def __init__(self, inner: LLM, limiter: Limiter) -> None:
        self.model = inner.model
        self._inner = inner
        self._limiter = limiter
        self._lock = threading.Lock()

    def generate(self, prompt: str) -> str:
        if not self._limiter.try_use_summary():
            raise LLMError(SUMMARY_CAP_REASON)
        with self._lock:
            return self._inner.generate(prompt)
