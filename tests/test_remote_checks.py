"""Favicon and broken links, against FakeHttp."""

import pytest

from fakes import FakeHttp, fixture, make_page
from website_audit_agent.checks import parse_html
from website_audit_agent.ports import FetchError
from website_audit_agent.remote_checks import (
    check_favicon,
    check_links,
    classify_status,
    collect_links,
    probe,
)

BAKERY = "http://bakery.test/"


def _links(html, url="https://example.com/"):
    page = make_page(html, url=url)
    return collect_links(page, parse_html(page.html))


# --- collect_links -----------------------------------------------------------------

def test_collect_links_skips_mailto_tel_javascript_and_anchors_and_dedupes():
    assert _links(fixture("good.html")) == [
        "https://example.com/about",
        "https://example.com/projects",
        "https://example.org/",
    ]


def test_collect_links_broken_fixture_has_35_unique_in_page_order():
    links = _links(fixture("broken.html"), url=BAKERY)
    assert len(links) == 35
    assert links[:3] == [f"{BAKERY}menu-1", f"{BAKERY}menu-2", f"{BAKERY}menu-3"]
    assert links[-1] == f"{BAKERY}menu-35"


def test_collect_links_resolves_against_base_href():
    html = '<html><head><base href="https://cdn.example.com/docs/"></head><body><a href="page">x</a></body></html>'
    assert _links(html) == ["https://cdn.example.com/docs/page"]


def test_collect_links_skip_prefixes_are_case_insensitive():
    assert _links('<a href="MAILTO:x@example.com">m</a><a href="JavaScript:void(0)">j</a>') == []


# --- classification (continued #4) --------------------------------------------------

@pytest.mark.parametrize(
    "status, outcome",
    [(200, "ok"), (301, "ok"), (404, "broken"), (410, "broken"), (500, "broken"), (503, "broken"),
     (401, "blocked"), (403, "blocked"), (429, "blocked"), (400, "unknown"), (418, "unknown")],
)
def test_classify_status(status, outcome):
    assert classify_status("u", status).outcome == outcome


@pytest.mark.parametrize(
    "kind, label",
    [("dns", "DNS failure"), ("timeout", "timeout"), ("too_many_redirects", "too many redirects")],
)
def test_fetch_errors_are_broken(kind, label):
    http = FakeHttp({"https://x.test/": FetchError(kind, "boom")})
    status = probe("https://x.test/", http)
    assert status.outcome == "broken" and status.detail == label


@pytest.mark.parametrize("refused", [405, 501])
def test_head_falls_back_to_get(refused):
    http = FakeHttp({("HEAD", "https://x.test/"): refused, ("GET", "https://x.test/"): 200})
    assert probe("https://x.test/", http).outcome == "ok"
    assert [m for m, _, _ in http.calls] == ["HEAD", "GET"]


def test_head_404_does_not_fall_back():
    http = FakeHttp({("HEAD", "https://x.test/"): 404})
    assert probe("https://x.test/", http).outcome == "broken"
    assert [m for m, _, _ in http.calls] == ["HEAD"]


# --- check_links: cap and timeout ---------------------------------------------------

def test_link_cap_is_30():
    links = [f"https://example.com/p{i}" for i in range(35)]
    http = FakeHttp()
    result = check_links(links, http)
    assert http.urls() == links[:30]  # first 30, in page order, nothing more
    assert "Checked 30 of 35 links (5 beyond the 30-link cap not checked)" in result.detail


def test_every_link_request_uses_10s_timeout():
    links = [f"https://example.com/p{i}" for i in range(5)]
    http = FakeHttp({("HEAD", links[0]): 405})  # the GET fallback must use 10 s too
    check_links(links, http)
    assert http.calls and {t for _, _, t in http.calls} == {10.0}


def test_broken_link_fails_check_and_blocked_does_not():
    links = ["https://a.test/", "https://b.test/", "https://c.test/"]
    http = FakeHttp({"https://b.test/": 404, "https://c.test/": 403})
    result = check_links(links, http)
    assert not result.passed
    assert "1 broken, 1 unknown (blocked)" in result.detail
    assert result.items == ("BROKEN (404) https://b.test/", "UNKNOWN, blocked (403) https://c.test/")

    only_blocked = check_links(["https://c.test/"], http)
    assert only_blocked.passed


def test_no_links_passes_without_requests():
    http = FakeHttp(default=None)
    assert check_links([], http).passed
    assert http.calls == []


# --- favicon (continued #5) ---------------------------------------------------------

def test_favicon_link_tag_passes_with_no_request():
    page = make_page(fixture("good.html"))
    http = FakeHttp(default=None)  # any request fails the test
    assert check_favicon(page, parse_html(page.html), http).passed
    assert http.calls == []


def test_favicon_shortcut_icon_rel_counts():
    page = make_page('<link rel="shortcut icon" href="/f.ico">')
    assert check_favicon(page, parse_html(page.html), FakeHttp(default=None)).passed


def test_favicon_fallback_makes_one_request_to_favicon_ico():
    page = make_page("<html></html>", url="https://example.com/blog/post")
    http = FakeHttp({"https://example.com/favicon.ico": 200}, default=None)
    assert check_favicon(page, parse_html(page.html), http).passed
    assert http.calls == [("HEAD", "https://example.com/favicon.ico", 10.0)]


def test_favicon_fails_when_no_tag_and_favicon_ico_missing():
    page = make_page("<html></html>")
    http = FakeHttp({"https://example.com/favicon.ico": 404}, default=None)
    result = check_favicon(page, parse_html(page.html), http)
    assert not result.passed and "404" in result.detail
