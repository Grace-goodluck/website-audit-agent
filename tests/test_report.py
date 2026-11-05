from datetime import datetime

from website_audit_agent.models import CheckResult, Fix, Report, Summary
from website_audit_agent.report import UNAVAILABLE, render_markdown, report_filename, write_report

NOW = datetime(2026, 11, 5, 9, 7, 5)
CHECKS = (
    CheckResult("title", False, "The <title> is 75 characters; aim for 30–60."),
    CheckResult("viewport", True, "Viewport meta tag present."),
    CheckResult("image_alt", False, "1 of 2 images have no alt text.", ("/cake.jpg",)),
)


def _report(summary, checks=CHECKS, url="https://techbygrace.com/", fetch_error=None):
    return Report(url=url, final_url=url, audited_at=NOW, model="gemini-3.8-flash",
                  checks=checks, summary=summary, fetch_error=fetch_error)


def test_filename_is_host_and_timestamp():
    assert report_filename(_report(Summary(True, "s"))) == "techbygrace.com-20261105-090705.md"
    assert report_filename(_report(Summary(True, "s"), url="http://localhost:8000/x")) == "localhost-20261105-090705.md"


def test_available_summary_with_ranked_fixes():
    summary = Summary(True, "Two problems.", (Fix("image_alt", "Add alt text."), Fix("title", "Shorten it.")))
    text = render_markdown(_report(summary))
    assert "Two problems." in text
    assert "1. **image_alt**: Add alt text.\n2. **title**: Shorten it." in text
    assert "- Result: 1 of 3 checks passed" in text
    assert "| title | FAIL |" in text and "| viewport | PASS |" in text
    assert "### image_alt\n\n- /cake.jpg" in text
    assert UNAVAILABLE not in text


def test_dropped_fixes_noted():
    text = render_markdown(_report(Summary(True, "s", (), dropped_fixes=2)))
    assert "2 suggested fixes were dropped" in text


def test_unavailable_summary_lists_failed_checks_unranked():
    text = render_markdown(_report(Summary(False, reason="GEMINI_API_KEY is not set")))
    assert f"**{UNAVAILABLE}** (GEMINI_API_KEY is not set)" in text
    assert "- **title**: The <title> is 75 characters" in text
    assert "- **image_alt**:" in text
    assert "- **viewport**:" not in text  # passed checks are not fixes


def test_pipe_in_detail_is_escaped_in_table():
    checks = (CheckResult("title", True, "a | b"),)
    assert "| title | PASS | a \\| b |" in render_markdown(_report(Summary(True, "s"), checks=checks))


def test_blocked_links_shown_even_when_check_passes():
    checks = (CheckResult("broken_links", True, "Checked 1 of 1 links. 0 broken, 1 unknown (blocked).",
                          ("UNKNOWN, blocked (403) https://x.test/",)),)
    text = render_markdown(_report(Summary(True, "s"), checks=checks))
    assert "### broken_links\n\n- UNKNOWN, blocked (403) https://x.test/" in text


def test_fetch_failure_short_report():
    checks = (CheckResult("http_status", False, "The page could not be fetched: DNS failure."),)
    text = render_markdown(_report(Summary(False, reason="the page could not be fetched"), checks=checks,
                                   fetch_error="DNS failure"))
    assert "## Page could not be fetched" in text
    assert "No other checks were run." in text
    assert "## Checks" not in text


def test_write_report_creates_directory(tmp_path):
    path = write_report(_report(Summary(True, "s")), tmp_path / "reports")
    assert path.parent == tmp_path / "reports"
    assert path.read_text(encoding="utf-8").startswith("# Website audit: https://techbygrace.com/")
