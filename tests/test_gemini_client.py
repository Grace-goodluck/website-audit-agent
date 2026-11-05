"""Ported from job_application_agent: same cache, pacer and retry rules (decision 3)."""

import httpx
import pytest

from fakes import FakeClock
from website_audit_agent.gemini_client import DiskCache, GeminiLLM
from website_audit_agent.pacing import Pacer
from website_audit_agent.ports import LLMError


class RecordingCall:
    def __init__(self, reply: object = "reply") -> None:
        self.reply = reply
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def _llm(tmp_path, call, clock=None, model="gemini-test"):
    clock = clock or FakeClock()
    pacer = Pacer(13.0, clock.clock, clock.sleep)
    return GeminiLLM(model, call, DiskCache(tmp_path), pacer, sleep=clock.sleep), clock


def test_cache_hit_skips_api_and_pacer(tmp_path):
    call = RecordingCall("hello")
    llm, clock = _llm(tmp_path, call)

    assert llm.generate("p") == "hello"
    assert llm.generate("p") == "hello"
    assert call.prompts == ["p"]  # second answer came from disk
    assert clock.sleeps == []


def test_cache_survives_a_new_client(tmp_path):
    first, _ = _llm(tmp_path, RecordingCall("cached"))
    first.generate("p")

    second_call = RecordingCall("fresh")
    second, _ = _llm(tmp_path, second_call)
    assert second.generate("p") == "cached"
    assert second_call.prompts == []


def test_cache_keyed_by_model_and_full_prompt(tmp_path):
    cache = DiskCache(tmp_path)
    cache.put("model-a", "prompt", "A")
    assert cache.get("model-a", "prompt") == "A"
    assert cache.get("model-b", "prompt") is None
    assert cache.get("model-a", "prompt ") is None


def test_fresh_calls_spaced_at_least_13s(tmp_path):
    llm, clock = _llm(tmp_path, RecordingCall())
    llm.generate("one")
    clock.t += 5.0
    llm.generate("two")
    llm.generate("three")
    assert clock.sleeps == [pytest.approx(8.0), pytest.approx(13.0)]


def test_sdk_failure_raises_llm_error_and_is_not_cached(tmp_path):
    llm, _ = _llm(tmp_path, RecordingCall(RuntimeError("network down")))
    with pytest.raises(LLMError, match="network down"):
        llm.generate("p")
    assert DiskCache(tmp_path).get("gemini-test", "p") is None


# --- retries ----------------------------------------------------------------------

class FakeAPIError(Exception):
    """Shaped like google.genai.errors.APIError: an int .code and a 'CODE STATUS. {...}' message."""

    def __init__(self, code: int, status: str) -> None:
        super().__init__(f"{code} {status}. {{'error': {{'code': {code}}}}}")
        self.code = code


class ScriptedCall:
    """Raises or returns each scripted outcome in turn; the last one repeats."""

    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        self.calls += 1
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_503_retried_twice_then_reported(tmp_path):
    call = ScriptedCall([FakeAPIError(503, "UNAVAILABLE")])
    llm, clock = _llm(tmp_path, call)
    with pytest.raises(LLMError, match=r"Gemini call failed: 503 UNAVAILABLE"):
        llm.generate("p")
    assert call.calls == 3  # first try + 2 retries
    assert clock.sleeps == [30.0, 60.0]
    assert DiskCache(tmp_path).get("gemini-test", "p") is None


def test_429_not_retried(tmp_path):
    call = ScriptedCall([FakeAPIError(429, "RESOURCE_EXHAUSTED")])
    llm, clock = _llm(tmp_path, call)
    with pytest.raises(LLMError, match="429 RESOURCE_EXHAUSTED"):
        llm.generate("p")
    assert call.calls == 1
    assert clock.sleeps == []


def test_success_on_retry_is_used_and_cached(tmp_path):
    call = ScriptedCall([FakeAPIError(503, "UNAVAILABLE"), "ok"])
    llm, clock = _llm(tmp_path, call)
    assert llm.generate("p") == "ok"
    assert call.calls == 2
    assert clock.sleeps == [30.0]
    assert DiskCache(tmp_path).get("gemini-test", "p") == "ok"


def test_503_detected_from_message_without_code(tmp_path):
    call = ScriptedCall([Exception("503 UNAVAILABLE. high demand"), "ok"])
    llm, _ = _llm(tmp_path, call)
    assert llm.generate("p") == "ok"
    assert call.calls == 2


@pytest.mark.parametrize(
    "exc",
    [
        httpx.RemoteProtocolError("Server disconnected without sending a response."),
        httpx.ReadTimeout("timed out"),
        ConnectionResetError("reset by peer"),
    ],
    ids=["server-disconnected", "read-timeout", "connection-reset"],
)
def test_dropped_connection_or_timeout_is_retried(tmp_path, exc):
    call = ScriptedCall([exc, "ok"])
    llm, clock = _llm(tmp_path, call)
    assert llm.generate("p") == "ok"
    assert call.calls == 2
    assert clock.sleeps == [30.0]


def test_dropped_connection_retried_twice_then_reported(tmp_path):
    call = ScriptedCall([httpx.RemoteProtocolError("Server disconnected without sending a response.")])
    llm, clock = _llm(tmp_path, call)
    with pytest.raises(LLMError, match="Server disconnected"):
        llm.generate("p")
    assert call.calls == 3
    assert clock.sleeps == [30.0, 60.0]


def test_empty_reply_raises_llm_error(tmp_path):
    llm, _ = _llm(tmp_path, RecordingCall("   "))
    with pytest.raises(LLMError):
        llm.generate("p")
