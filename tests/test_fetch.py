import pytest

from fakes import FakeHttp, html_response
from website_audit_agent.fetch import decode_body, fetch_page
from website_audit_agent.models import HttpResponse
from website_audit_agent.ports import FetchError

URL = "https://example.com/"


def test_one_get_with_20s_timeout():
    http = FakeHttp({URL: html_response(URL, "<html></html>", elapsed_s=1.25)}, default=None)
    page = fetch_page(URL, http)
    assert http.calls == [("GET", URL, 20.0)]
    assert page.elapsed_s == 1.25
    assert page.size_bytes == len(b"<html></html>")
    assert page.html == "<html></html>"


def test_final_url_after_redirect_is_kept():
    http = FakeHttp({URL: html_response("https://www.example.com/", "<html></html>")}, default=None)
    page = fetch_page(URL, http)
    assert page.requested_url == URL and page.final_url == "https://www.example.com/"


def test_charset_from_content_type():
    body = "café".encode("latin-1")
    http = FakeHttp(
        {URL: HttpResponse(URL, 200, {"content-type": "text/html; charset=ISO-8859-1"}, body, 0.1)},
        default=None,
    )
    assert fetch_page(URL, http).html == "café"


def test_unknown_charset_falls_back_to_utf8():
    assert decode_body("é".encode(), "text/html; charset=not-a-charset") == "é"


def test_fetch_error_propagates():
    http = FakeHttp({URL: FetchError("dns", "DNS failure")}, default=None)
    with pytest.raises(FetchError):
        fetch_page(URL, http)
