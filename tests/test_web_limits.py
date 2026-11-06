"""Web decisions 1–3: per-visitor, daily total and daily summary limits, reset at Pacific midnight."""

from datetime import datetime, timezone

import pytest

from fakes import FakeLLM, FakeNow
from website_audit_agent.ports import LLMError
from website_audit_agent.web.limits import (
    SUMMARY_CAP_REASON,
    GuardedLLM,
    Limiter,
    Limits,
    seconds_until_pacific_midnight,
)

# 2026-11-06 is after the 2026-11-01 DST change: Pacific midnight is 08:00 UTC.
JUST_BEFORE_PACIFIC_MIDNIGHT = datetime(2026, 11, 7, 7, 59, tzinfo=timezone.utc)


def test_defaults_match_scope():
    assert Limits() == Limits(audits_per_visitor_per_hour=3, audits_per_day=30, summaries_per_day=15)


# --- per visitor -------------------------------------------------------------------

def test_three_audits_per_visitor_per_rolling_hour():
    now = FakeNow()
    limiter = Limiter(now=now)
    for _ in range(3):
        assert limiter.try_start_audit("203.0.113.7") is None
        now.advance(minutes=10)

    refusal = limiter.try_start_audit("203.0.113.7")
    assert refusal is not None and "3 audits for this hour" in refusal.message
    assert refusal.retry_after_s == 30 * 60  # first audit was 30 min ago

    assert limiter.try_start_audit("198.51.100.2") is None  # another visitor is unaffected

    now.advance(minutes=30)  # the first audit is now an hour old
    assert limiter.try_start_audit("203.0.113.7") is None


def test_refused_attempts_are_not_counted():
    now = FakeNow()
    limiter = Limiter(Limits(audits_per_visitor_per_hour=1, audits_per_day=2), now=now)
    assert limiter.try_start_audit("a") is None
    for _ in range(5):
        assert limiter.try_start_audit("a") is not None
    assert limiter.try_start_audit("b") is None  # the daily total only counted 2


# --- daily total -------------------------------------------------------------------

def test_thirty_audits_per_day_in_total():
    limiter = Limiter(now=FakeNow())
    for i in range(30):
        assert limiter.try_start_audit(f"visitor-{i}") is None
    refusal = limiter.try_start_audit("visitor-new")
    assert refusal is not None and "limit of 30 audits for today" in refusal.message
    assert "midnight Pacific" in refusal.message


def test_daily_total_resets_at_pacific_midnight_not_utc_midnight():
    now = FakeNow(datetime(2026, 11, 6, 23, 0, tzinfo=timezone.utc))  # 15:00 Pacific
    limiter = Limiter(Limits(audits_per_visitor_per_hour=100, audits_per_day=1), now=now)
    assert limiter.try_start_audit("a") is None
    assert limiter.try_start_audit("a") is not None

    now.advance(hours=2)  # 01:00 UTC on the 7th, still the 6th in Pacific time
    assert limiter.try_start_audit("a") is not None

    now.t = JUST_BEFORE_PACIFIC_MIDNIGHT
    refusal = limiter.try_start_audit("a")
    assert refusal is not None and refusal.retry_after_s == 60

    now.advance(minutes=2)  # 00:01 Pacific on the 7th
    assert limiter.try_start_audit("a") is None


@pytest.mark.parametrize(
    "utc, seconds",
    [
        (datetime(2026, 11, 7, 7, 59, tzinfo=timezone.utc), 60),  # PST, UTC-8
        (datetime(2026, 7, 1, 6, 59, tzinfo=timezone.utc), 60),  # PDT, UTC-7
        (datetime(2026, 3, 8, 8, 0, tzinfo=timezone.utc), 23 * 3600),  # DST starts that day: a 23-hour day
    ],
)
def test_seconds_until_pacific_midnight(utc, seconds):
    assert seconds_until_pacific_midnight(utc) == seconds


# --- daily summaries ---------------------------------------------------------------

def test_fifteen_summaries_per_day_then_reset():
    now = FakeNow(JUST_BEFORE_PACIFIC_MIDNIGHT)
    limiter = Limiter(now=now)
    assert all(limiter.try_use_summary() for _ in range(15))
    assert not limiter.try_use_summary()
    now.advance(minutes=2)
    assert limiter.try_use_summary()


def test_guarded_llm_stops_calling_gemini_at_the_cap():
    limiter = Limiter(Limits(summaries_per_day=2), now=FakeNow())
    inner = FakeLLM(["one", "two"])
    llm = GuardedLLM(inner, limiter)

    assert llm.generate("p1") == "one"
    assert llm.generate("p2") == "two"
    with pytest.raises(LLMError, match=SUMMARY_CAP_REASON):
        llm.generate("p3")
    assert inner.prompts == ["p1", "p2"]  # the third prompt never reached Gemini
    assert llm.model == "fake-model"
