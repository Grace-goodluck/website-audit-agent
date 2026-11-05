"""The summary prompt is built from check results only — never the raw page (decision 3)."""

import inspect
import json

from fakes import FakeHttp, fixture, make_page
from website_audit_agent.checks import parse_html, run_page_checks
from website_audit_agent.models import CheckResult
from website_audit_agent.prompts import build_summary_prompt
from website_audit_agent.remote_checks import check_favicon, check_links, collect_links


def _payload(prompt: str) -> list[dict]:
    return json.loads(prompt.split("Check results:\n", 1)[1])


def _all_results(name: str, url: str) -> list[CheckResult]:
    page = make_page(fixture(name), url=url)
    soup = parse_html(page.html)
    http = FakeHttp()
    return run_page_checks(page, soup) + [check_favicon(page, soup, http), check_links(collect_links(page, soup), http)]


def test_builder_takes_only_check_results():
    assert list(inspect.signature(build_summary_prompt).parameters) == ["results"]


def test_prompt_contains_every_check_name_result_and_detail():
    results = [
        CheckResult("title", False, "The <title> is 75 characters; aim for 30–60."),
        CheckResult("viewport", True, "Viewport meta tag present."),
    ]
    payload = _payload(build_summary_prompt(results))
    assert payload == [
        {"name": "title", "passed": False, "detail": "The <title> is 75 characters; aim for 30–60.", "items": []},
        {"name": "viewport", "passed": True, "detail": "Viewport meta tag present.", "items": []},
    ]


def test_items_capped_at_10_with_a_count_of_the_rest():
    result = CheckResult("broken_links", False, "d", tuple(f"BROKEN (404) https://x.test/{i}" for i in range(14)))
    items = _payload(build_summary_prompt([result]))[0]["items"]
    assert len(items) == 11 and items[-1] == "... and 4 more"


def test_prompt_never_contains_raw_html():
    for name, url, marker in [
        ("broken.html", "http://bakery.test/", "FIXTURE-MARKER-BROKEN"),
        ("good.html", "https://example.com/", "FIXTURE-MARKER-GOOD"),
    ]:
        html = fixture(name)
        prompt = build_summary_prompt(_all_results(name, url))
        assert marker in html
        assert marker not in prompt
        for tag in ("<html", "<head", "<body", "<meta", "<img", "<a href", "<!doctype"):
            assert tag not in prompt.lower()
        assert html not in prompt
