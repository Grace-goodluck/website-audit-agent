"""One pass and one fail case per page check. Pure: no HTTP at all."""

import pytest

from fakes import fixture, make_page
from website_audit_agent import checks
from website_audit_agent.checks import parse_html, run_page_checks


def _run(check, html="<html></html>", **page_kwargs):
    page = make_page(html, **page_kwargs)
    return check(page, parse_html(page.html))


def _doc(head="", body=""):
    return f"<html><head>{head}</head><body>{body}</body></html>"


# --- fixtures, end to end ----------------------------------------------------------

def test_good_fixture_passes_every_page_check():
    page = make_page(fixture("good.html"))
    results = run_page_checks(page, parse_html(page.html))
    assert [r.name for r in results if not r.passed] == []


def test_broken_fixture_fails_the_expected_page_checks():
    page = make_page(fixture("broken.html"), url="http://bakery.test/")
    results = {r.name: r for r in run_page_checks(page, parse_html(page.html))}
    failed = {name for name, r in results.items() if not r.passed}
    assert failed == {"https", "title", "meta_description", "viewport", "h1", "image_alt", "open_graph"}
    assert "75 characters" in results["title"].detail
    assert results["image_alt"].items == ("/cake.jpg", "/bread.jpg")
    assert results["open_graph"].items == ("og:description", "og:image")


# --- http_status -------------------------------------------------------------------

def test_http_status_pass():
    assert _run(checks.check_http_status, status=200).passed


def test_http_status_fail():
    r = _run(checks.check_http_status, status=500)
    assert not r.passed and "500" in r.detail


def test_http_status_mentions_redirect():
    r = _run(checks.check_http_status, url="http://example.com/", final_url="https://example.com/")
    assert r.passed and "Redirected to https://example.com/" in r.detail


# --- https -------------------------------------------------------------------------

def test_https_pass():
    assert _run(checks.check_https, url="https://example.com/").passed


def test_https_fail():
    assert not _run(checks.check_https, url="http://example.com/").passed


def test_https_judged_on_final_url_after_redirect():
    assert _run(checks.check_https, url="http://example.com/", final_url="https://example.com/").passed


# --- response_time (fail when > 3 s) ------------------------------------------------

@pytest.mark.parametrize("seconds, passed", [(0.4, True), (3.0, True), (3.01, False)])
def test_response_time(seconds, passed):
    assert _run(checks.check_response_time, elapsed_s=seconds).passed is passed


# --- page_size (fail when > 2 MB) ---------------------------------------------------

@pytest.mark.parametrize("size, passed", [(50_000, True), (2 * 1024 * 1024, True), (2 * 1024 * 1024 + 1, False)])
def test_page_size(size, passed):
    assert _run(checks.check_page_size, size_bytes=size).passed is passed


# --- title (30–60 characters) -------------------------------------------------------

@pytest.mark.parametrize("length, passed", [(29, False), (30, True), (60, True), (61, False)])
def test_title_length_bounds(length, passed):
    r = _run(checks.check_title, _doc(head=f"<title>{'a' * length}</title>"))
    assert r.passed is passed


def test_title_missing():
    r = _run(checks.check_title, _doc())
    assert not r.passed and "No <title>" in r.detail


def test_title_whitespace_collapsed_before_counting():
    r = _run(checks.check_title, _doc(head=f"<title>\n   {'a' * 30}   \n</title>"))
    assert r.passed and "30 characters" in r.detail


# --- meta_description (70–160 characters) -------------------------------------------

@pytest.mark.parametrize("length, passed", [(69, False), (70, True), (160, True), (161, False)])
def test_meta_description_length_bounds(length, passed):
    r = _run(checks.check_meta_description, _doc(head=f'<meta name="description" content="{"d" * length}">'))
    assert r.passed is passed


def test_meta_description_missing():
    r = _run(checks.check_meta_description, _doc())
    assert not r.passed and "No meta description" in r.detail


def test_meta_description_name_is_case_insensitive():
    r = _run(checks.check_meta_description, _doc(head=f'<meta name="Description" content="{"d" * 80}">'))
    assert r.passed


# --- viewport ----------------------------------------------------------------------

def test_viewport_pass():
    assert _run(checks.check_viewport, _doc(head='<meta name="viewport" content="width=device-width">')).passed


def test_viewport_fail():
    assert not _run(checks.check_viewport, _doc()).passed


# --- h1 (exactly one) ---------------------------------------------------------------

def test_h1_exactly_one_passes():
    assert _run(checks.check_h1, _doc(body="<h1>One</h1>")).passed


@pytest.mark.parametrize("body", ["", "<h1>One</h1><h1>Two</h1>"], ids=["none", "two"])
def test_h1_fails_for_none_or_many(body):
    assert not _run(checks.check_h1, _doc(body=body)).passed


# --- image_alt ---------------------------------------------------------------------

def test_image_alt_pass_including_empty_decorative_alt():
    assert _run(checks.check_image_alt, _doc(body='<img src="a.png" alt="A"><img src="b.png" alt="">')).passed


def test_image_alt_fail_lists_missing():
    r = _run(checks.check_image_alt, _doc(body='<img src="a.png" alt="A"><img src="b.png">'))
    assert not r.passed and r.items == ("b.png",) and "1 of 2" in r.detail


def test_image_alt_no_images_passes():
    assert _run(checks.check_image_alt, _doc()).passed


# --- open_graph (title, description, image required; url optional) -----------------

OG_REQUIRED = (
    '<meta property="og:title" content="T">'
    '<meta property="og:description" content="D">'
    '<meta property="og:image" content="https://example.com/i.png">'
)


def test_open_graph_pass_without_optional_url():
    r = _run(checks.check_open_graph, _doc(head=OG_REQUIRED))
    assert r.passed and "og:url" in r.detail  # mentioned, not failed


def test_open_graph_fail_lists_missing_required():
    r = _run(checks.check_open_graph, _doc(head='<meta property="og:title" content="T">'))
    assert not r.passed and r.items == ("og:description", "og:image")


def test_open_graph_empty_content_counts_as_missing():
    head = OG_REQUIRED.replace('content="D"', 'content=""')
    assert not _run(checks.check_open_graph, _doc(head=head)).passed
