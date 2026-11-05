"""Deterministic page checks (decision 2). Pure: no network, no AI.

Each check takes the fetched page and its parsed HTML and returns one
CheckResult. The two checks that may need the network (favicon fallback,
broken links) live in remote_checks.py.
"""

from collections.abc import Callable
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from website_audit_agent.config import (
    LARGE_PAGE_BYTES,
    META_DESC_MAX,
    META_DESC_MIN,
    SLOW_RESPONSE_S,
    TITLE_MAX,
    TITLE_MIN,
)
from website_audit_agent.models import CheckResult, FetchedPage

REQUIRED_OG = ("og:title", "og:description", "og:image")  # continued #6
OPTIONAL_OG = ("og:url",)


def parse_html(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


def _meta_content(soup: BeautifulSoup, *, name: str | None = None, prop: str | None = None) -> str | None:
    """Content of the first matching <meta>, case-insensitive on name/property. None if absent."""
    for tag in soup.find_all("meta"):
        if name is not None and str(tag.get("name", "")).lower() == name:
            return _clean(tag.get("content"))
        if prop is not None and str(tag.get("property", "")).lower() == prop:
            return _clean(tag.get("content"))
    return None


def _length_check(name: str, label: str, value: str | None, lo: int, hi: int) -> CheckResult:
    if value is None:
        return CheckResult(name, False, f"No {label} found.")
    if not value:
        return CheckResult(name, False, f"The {label} is empty.")
    n = len(value)
    if not lo <= n <= hi:
        return CheckResult(name, False, f"The {label} is {n} characters; aim for {lo}–{hi}.", (value,))
    return CheckResult(name, True, f"The {label} is {n} characters (within {lo}–{hi}).", (value,))


def check_http_status(page: FetchedPage, soup: BeautifulSoup) -> CheckResult:
    passed = 200 <= page.status < 300
    detail = f"The page returned HTTP {page.status}."
    if page.final_url != page.requested_url:
        detail += f" Redirected to {page.final_url}."
    return CheckResult("http_status", passed, detail)


def check_https(page: FetchedPage, soup: BeautifulSoup) -> CheckResult:
    scheme = urlparse(page.final_url).scheme.lower()
    if scheme == "https":
        return CheckResult("https", True, "The page is served over HTTPS.")
    return CheckResult("https", False, f"The page is served over {scheme or 'an unknown scheme'}, not HTTPS.")


def check_response_time(page: FetchedPage, soup: BeautifulSoup) -> CheckResult:
    t = page.elapsed_s
    if t > SLOW_RESPONSE_S:
        return CheckResult("response_time", False, f"The page took {t:.2f} s to load; aim for {SLOW_RESPONSE_S:g} s or less.")
    return CheckResult("response_time", True, f"The page took {t:.2f} s to load.")


def check_page_size(page: FetchedPage, soup: BeautifulSoup) -> CheckResult:
    mb = page.size_bytes / (1024 * 1024)
    limit_mb = LARGE_PAGE_BYTES / (1024 * 1024)
    if page.size_bytes > LARGE_PAGE_BYTES:
        return CheckResult("page_size", False, f"The HTML is {mb:.2f} MB; aim for {limit_mb:g} MB or less.")
    return CheckResult("page_size", True, f"The HTML is {page.size_bytes / 1024:.1f} KB.")


def check_title(page: FetchedPage, soup: BeautifulSoup) -> CheckResult:
    title = _clean(soup.title.get_text()) if soup.title is not None else None
    return _length_check("title", "<title>", title, TITLE_MIN, TITLE_MAX)


def check_meta_description(page: FetchedPage, soup: BeautifulSoup) -> CheckResult:
    desc = _meta_content(soup, name="description")
    return _length_check("meta_description", "meta description", desc, META_DESC_MIN, META_DESC_MAX)


def check_viewport(page: FetchedPage, soup: BeautifulSoup) -> CheckResult:
    content = _meta_content(soup, name="viewport")
    if content is None:
        return CheckResult("viewport", False, "No viewport meta tag; the page may not display well on phones.")
    if not content:
        return CheckResult("viewport", False, "The viewport meta tag is empty.")
    return CheckResult("viewport", True, f'Viewport meta tag present: "{content}".')


def check_h1(page: FetchedPage, soup: BeautifulSoup) -> CheckResult:
    h1s = [_clean(h.get_text()) for h in soup.find_all("h1")]
    if len(h1s) == 1:
        return CheckResult("h1", True, "Exactly one <h1>.", tuple(h1s))
    if not h1s:
        return CheckResult("h1", False, "No <h1> found; use exactly one.")
    return CheckResult("h1", False, f"{len(h1s)} <h1> elements found; use exactly one.", tuple(h1s))


def check_image_alt(page: FetchedPage, soup: BeautifulSoup) -> CheckResult:
    """A missing alt attribute fails; alt="" is valid for decorative images."""
    images = soup.find_all("img")
    missing = [str(img.get("src") or "(no src)") for img in images if isinstance(img, Tag) and not img.has_attr("alt")]
    if not images:
        return CheckResult("image_alt", True, "No images on the page.")
    if missing:
        return CheckResult("image_alt", False, f"{len(missing)} of {len(images)} images have no alt text.", tuple(missing))
    return CheckResult("image_alt", True, f"All {len(images)} images have alt text.")


def check_open_graph(page: FetchedPage, soup: BeautifulSoup) -> CheckResult:
    missing = [p for p in REQUIRED_OG if not _meta_content(soup, prop=p)]
    missing_optional = [p for p in OPTIONAL_OG if not _meta_content(soup, prop=p)]
    note = f" Optional {', '.join(missing_optional)} is also missing." if missing_optional else ""
    if missing:
        return CheckResult("open_graph", False, f"Missing Open Graph tags: {', '.join(missing)}.{note}", tuple(missing))
    return CheckResult("open_graph", True, f"Required Open Graph tags present.{note}")


PageCheck = Callable[[FetchedPage, BeautifulSoup], CheckResult]

PAGE_CHECKS: tuple[PageCheck, ...] = (
    check_http_status,
    check_https,
    check_response_time,
    check_page_size,
    check_title,
    check_meta_description,
    check_viewport,
    check_h1,
    check_image_alt,
    check_open_graph,
)


def run_page_checks(page: FetchedPage, soup: BeautifulSoup) -> list[CheckResult]:
    return [check(page, soup) for check in PAGE_CHECKS]
