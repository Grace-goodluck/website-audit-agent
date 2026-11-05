"""Whole audit with FakeHttp + FakeLLM. Scenario matches evaluation/expected.md."""

import json
from datetime import datetime

from fakes import FakeHttp, FakeLLM, fixture, html_response
from website_audit_agent.audit import NO_KEY_REASON, run_audit
from website_audit_agent.ports import FetchError, LLMError
from website_audit_agent.report import UNAVAILABLE, write_report

BAKERY = "http://bakery.test/"
NOW = datetime(2026, 11, 5, 14, 3, 22)
ALL_CHECKS = [
    "http_status", "https", "response_time", "page_size", "title", "meta_description",
    "viewport", "h1", "image_alt", "open_graph", "favicon", "broken_links",
]
EXPECTED_FAILED = {
    "https", "title", "meta_description", "viewport", "h1", "image_alt", "open_graph", "favicon", "broken_links",
}


def _bakery_http():
    return FakeHttp({
        ("GET", BAKERY): html_response(BAKERY, fixture("broken.html"), elapsed_s=0.4),
        ("HEAD", f"{BAKERY}menu-3"): 404,
        ("HEAD", f"{BAKERY}menu-4"): 403,
        ("HEAD", f"{BAKERY}favicon.ico"): 404,
    })


def _good_reply():
    return json.dumps({"summary": "Several basics are missing.",
                       "fixes": [{"check": "viewport", "fix": "Add a viewport meta tag."}]})


def test_broken_fixture_matches_hand_written_expectations():
    http = _bakery_http()
    llm = FakeLLM([_good_reply()])
    report = run_audit(BAKERY, http, llm, "fake-model", now=NOW)

    assert [r.name for r in report.checks] == ALL_CHECKS
    assert {r.name for r in report.checks if not r.passed} == EXPECTED_FAILED
    links = report.checks[-1]
    assert "Checked 30 of 35 links (5 beyond the 30-link cap not checked). 1 broken, 1 unknown (blocked)." == links.detail
    assert len(http.calls) == 32  # 1 page + 1 favicon + 30 links (Ethics budget)
    assert report.ok


def test_summary_prompt_built_after_all_checks_from_results_only():
    llm = FakeLLM([_good_reply()])
    run_audit(BAKERY, _bakery_http(), llm, "fake-model", now=NOW)
    (prompt,) = llm.prompts
    for name in ALL_CHECKS:
        assert f'"name": "{name}"' in prompt
    assert "FIXTURE-MARKER-BROKEN" not in prompt
    assert "<body" not in prompt


def test_report_still_written_when_gemini_fails(tmp_path):
    llm = FakeLLM([LLMError("Gemini call failed: 503 UNAVAILABLE")])
    report = run_audit(BAKERY, _bakery_http(), llm, "fake-model", now=NOW)

    assert not report.summary.available and not report.ok
    assert [r.name for r in report.checks] == ALL_CHECKS  # nothing lost

    path = write_report(report, tmp_path)
    text = path.read_text(encoding="utf-8")
    assert path.name == "bakery.test-20261105-140322.md"
    assert UNAVAILABLE in text and "503 UNAVAILABLE" in text
    for name in ALL_CHECKS:
        assert f"| {name} |" in text
    assert "- **viewport**:" in text  # failed checks listed in place of ranked fixes


def test_unexpected_exception_from_llm_still_gives_report():
    class Exploding:
        model = "x"

        def generate(self, prompt):
            raise RuntimeError("bug")

    report = run_audit(BAKERY, _bakery_http(), Exploding(), "x", now=NOW)
    assert not report.summary.available and len(report.checks) == 12


def test_no_api_key_runs_checks_and_marks_summary_unavailable():
    report = run_audit(BAKERY, _bakery_http(), None, "fake-model", now=NOW)
    assert report.summary.reason == NO_KEY_REASON
    assert len(report.checks) == 12 and not report.ok


def test_fetch_failure_gives_short_report_and_no_other_requests():
    http = FakeHttp({BAKERY: FetchError("dns", "DNS failure: getaddrinfo failed")}, default=None)
    llm = FakeLLM([])  # any call fails the test
    report = run_audit(BAKERY, http, llm, "fake-model", now=NOW)
    assert report.fetch_error and not report.ok
    assert [r.name for r in report.checks] == ["http_status"]
    assert len(http.calls) == 1 and llm.prompts == []


def test_non_2xx_page_gives_short_report():
    http = FakeHttp({BAKERY: html_response(BAKERY, "<h1>Not found</h1>", status=404)}, default=None)
    report = run_audit(BAKERY, http, FakeLLM([]), "fake-model", now=NOW)
    assert report.fetch_error == "HTTP 404"
    assert [r.name for r in report.checks] == ["http_status"] and not report.checks[0].passed
    assert len(http.calls) == 1
