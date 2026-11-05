"""The two checks that may make requests: favicon fallback and broken links.

Request budget per run (Ethics): at most one /favicon.ico request plus at
most LINK_CAP link checks, each with its own LINK_TIMEOUT_S.
"""

from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from website_audit_agent.config import LINK_CAP, LINK_TIMEOUT_S
from website_audit_agent.models import CheckResult, FetchedPage, LinkStatus
from website_audit_agent.ports import FetchError, HttpClient

_SKIP_PREFIXES = ("mailto:", "tel:", "javascript:", "#")  # continued #3
_FALLBACK_TO_GET = (405, 501)  # continued #4
_BLOCKED = (401, 403, 429)
_GONE = (404, 410)
_FETCH_ERROR_LABELS = {
    "dns": "DNS failure",
    "timeout": "timeout",
    "too_many_redirects": "too many redirects",
    "connection": "connection failed",
}


# --- links ----------------------------------------------------------------------

def _base_url(page: FetchedPage, soup: BeautifulSoup) -> str:
    base = soup.find("base", href=True)
    return urljoin(page.final_url, str(base["href"]).strip()) if base is not None else page.final_url


def collect_links(page: FetchedPage, soup: BeautifulSoup) -> list[str]:
    """Unique absolute http(s) links in page order, fragments removed."""
    base = _base_url(page, soup)
    seen: set[str] = set()
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        if not href or href.lower().startswith(_SKIP_PREFIXES):
            continue
        url, _fragment = urldefrag(urljoin(base, href))
        if urlparse(url).scheme.lower() not in ("http", "https"):
            continue
        if url not in seen:
            seen.add(url)
            links.append(url)
    return links


def classify_status(url: str, status: int) -> LinkStatus:
    if status in _GONE or status >= 500:
        return LinkStatus(url, "broken", str(status))
    if status in _BLOCKED:
        return LinkStatus(url, "blocked", str(status))
    if status < 400:
        return LinkStatus(url, "ok", str(status))
    return LinkStatus(url, "unknown", str(status))  # other 4xx: not listed as broken


def probe(url: str, http: HttpClient, timeout: float = LINK_TIMEOUT_S) -> LinkStatus:
    """HEAD, falling back to GET when the server refuses HEAD."""
    try:
        response = http.head(url, timeout)
        if response.status in _FALLBACK_TO_GET:
            response = http.get(url, timeout)
    except FetchError as exc:
        return LinkStatus(url, "broken", _FETCH_ERROR_LABELS.get(exc.kind, exc.kind))
    return classify_status(url, response.status)


def check_links(
    links: list[str],
    http: HttpClient,
    cap: int = LINK_CAP,
    timeout: float = LINK_TIMEOUT_S,
) -> CheckResult:
    if not links:
        return CheckResult("broken_links", True, "No links found on the page.")

    to_check = links[:cap]
    skipped = len(links) - len(to_check)
    statuses = [probe(url, http, timeout) for url in to_check]
    broken = [s for s in statuses if s.outcome == "broken"]
    blocked = [s for s in statuses if s.outcome == "blocked"]
    unknown = [s for s in statuses if s.outcome == "unknown"]

    detail = f"Checked {len(to_check)} of {len(links)} links"
    detail += f" ({skipped} beyond the {cap}-link cap not checked)." if skipped else "."
    detail += f" {len(broken)} broken"
    if blocked:
        detail += f", {len(blocked)} unknown (blocked)"
    if unknown:
        detail += f", {len(unknown)} unknown (other status)"
    detail += "."

    items = tuple(
        [f"BROKEN ({s.detail}) {s.url}" for s in broken]
        + [f"UNKNOWN, blocked ({s.detail}) {s.url}" for s in blocked]
        + [f"UNKNOWN ({s.detail}) {s.url}" for s in unknown]
    )
    return CheckResult("broken_links", not broken, detail, items)


# --- favicon --------------------------------------------------------------------

def _has_icon_link(soup: BeautifulSoup) -> str | None:
    for link in soup.find_all("link", href=True):
        rel = link.get("rel") or []
        tokens = [r.lower() for r in (rel if isinstance(rel, list) else str(rel).split())]
        if "icon" in tokens:
            return str(link["href"])
    return None


def check_favicon(page: FetchedPage, soup: BeautifulSoup, http: HttpClient, timeout: float = LINK_TIMEOUT_S) -> CheckResult:
    """<link rel="icon"> passes with no request; otherwise one request to /favicon.ico (continued #5)."""
    href = _has_icon_link(soup)
    if href is not None:
        return CheckResult("favicon", True, f'Favicon declared with <link rel="icon">: {href}.')

    url = urljoin(page.final_url, "/favicon.ico")
    status = probe(url, http, timeout)
    if status.outcome == "ok":
        return CheckResult("favicon", True, f'No <link rel="icon">, but {url} exists.')
    return CheckResult(
        "favicon",
        False,
        f'No <link rel="icon"> and {url} returned {status.detail}.',
    )
