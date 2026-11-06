"""Runs one audit: fetch → checks → summary → Report. No file writes, no printing.

All checks finish before Gemini is touched, and nothing the summary does
can remove them from the report (decision 3).
"""

from datetime import datetime

from website_audit_agent.checks import parse_html, run_page_checks
from website_audit_agent.config import LINK_CAP, LINK_TIMEOUT_S
from website_audit_agent.fetch import fetch_page
from website_audit_agent.models import CheckResult, Report, Summary
from website_audit_agent.ports import LLM, FetchError, HttpClient
from website_audit_agent.remote_checks import check_favicon, check_links, collect_links
from website_audit_agent.summary import summarise

NO_KEY_REASON = "GEMINI_API_KEY is not set"
FETCH_FAILED_REASON = "the page could not be fetched, so there is nothing to summarise"


def _short_report(url: str, final_url: str | None, now: datetime, model: str, error: str, status: CheckResult) -> Report:
    return Report(
        url=url,
        final_url=final_url,
        audited_at=now,
        model=model,
        checks=(status,),
        summary=Summary(available=False, reason=FETCH_FAILED_REASON),
        fetch_error=error,
    )


def run_audit(
    url: str,
    http: HttpClient,
    llm: LLM | None,
    model: str,
    now: datetime | None = None,
    *,
    link_cap: int = LINK_CAP,
    link_timeout: float = LINK_TIMEOUT_S,
) -> Report:
    """link_cap / link_timeout default to the command-line values; the web demo passes 15 and 5 s."""
    now = now or datetime.now()

    try:
        page = fetch_page(url, http)
    except FetchError as exc:
        status = CheckResult("http_status", False, f"The page could not be fetched: {exc}.")
        return _short_report(url, None, now, model, str(exc), status)

    soup = parse_html(page.html)
    results = run_page_checks(page, soup)  # http_status is first
    if not results[0].passed:  # continued #8: a non-2xx page is a fetch failure
        return _short_report(url, page.final_url, now, model, f"HTTP {page.status}", results[0])

    results.append(check_favicon(page, soup, http, timeout=link_timeout))
    results.append(check_links(collect_links(page, soup), http, cap=link_cap, timeout=link_timeout))

    if llm is None:
        summary = Summary(available=False, reason=NO_KEY_REASON)
    else:
        try:
            summary = summarise(results, llm)
        except Exception as exc:  # summarise should never raise; this is the last line of defence
            summary = Summary(available=False, reason=f"unexpected error: {exc}")

    return Report(
        url=url,
        final_url=page.final_url,
        audited_at=now,
        model=model,
        checks=tuple(results),
        summary=summary,
    )
