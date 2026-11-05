import json

import pytest

from fakes import FakeLLM
from website_audit_agent.models import CheckResult, Fix
from website_audit_agent.ports import LLMError
from website_audit_agent.summary import summarise

RESULTS = [
    CheckResult("title", False, "75 characters"),
    CheckResult("viewport", False, "missing"),
    CheckResult("https", True, "served over HTTPS"),
]


def _reply(summary="Two problems.", fixes=None):
    return json.dumps({"summary": summary, "fixes": fixes if fixes is not None else []})


def test_valid_reply_keeps_ranked_fixes():
    llm = FakeLLM([_reply(fixes=[{"check": "viewport", "fix": "Add a viewport tag."},
                                 {"check": "title", "fix": "Shorten the title."}])])
    summary = summarise(RESULTS, llm)
    assert summary.available and summary.text == "Two problems."
    assert summary.fixes == (Fix("viewport", "Add a viewport tag."), Fix("title", "Shorten the title."))
    assert summary.dropped_fixes == 0
    assert len(llm.prompts) == 1


def test_fenced_json_reply_is_accepted():
    llm = FakeLLM(["```json\n" + _reply() + "\n```"])
    assert summarise(RESULTS, llm).available


def test_fixes_not_naming_a_failed_check_are_dropped():
    llm = FakeLLM([_reply(fixes=[
        {"check": "https", "fix": "passed check"},
        {"check": "made_up", "fix": "unknown check"},
        {"fix": "no check named"},
        {"check": "title", "fix": "Shorten the title."},
        "not an object",
    ])])
    summary = summarise(RESULTS, llm)
    assert summary.fixes == (Fix("title", "Shorten the title."),)
    assert summary.dropped_fixes == 4


def test_llm_error_gives_unavailable_summary():
    summary = summarise(RESULTS, FakeLLM([LLMError("Gemini call failed: 429 RESOURCE_EXHAUSTED")]))
    assert not summary.available and "429" in summary.reason


@pytest.mark.parametrize(
    "reply",
    ["not json at all", "[]", json.dumps({"fixes": []}), json.dumps({"summary": "  "}),
     json.dumps({"summary": "ok", "fixes": "nope"})],
    ids=["not-json", "not-object", "no-summary", "blank-summary", "fixes-not-list"],
)
def test_unreadable_reply_gives_unavailable_summary(reply):
    summary = summarise(RESULTS, FakeLLM([reply]))
    assert not summary.available and "could not be read" in summary.reason
