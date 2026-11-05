"""HttpxClient against httpx.MockTransport — no network."""

import httpx
import pytest

from website_audit_agent.config import USER_AGENT
from website_audit_agent.http_client import HttpxClient
from website_audit_agent.ports import FetchError


def _client(handler, **kwargs):
    return HttpxClient(transport=httpx.MockTransport(handler), **kwargs)


def test_user_agent_identifies_the_tool_on_get_and_head():
    seen = []

    def handler(request):
        seen.append((request.method, request.headers["user-agent"]))
        return httpx.Response(200, text="ok")

    client = _client(handler)
    client.get("https://example.com/", timeout=20)
    client.head("https://example.com/", timeout=10)
    assert seen == [("GET", USER_AGENT), ("HEAD", USER_AGENT)]
    assert USER_AGENT == "TechByGrace-WebsiteAudit/0.1 (+https://techbygrace.com)"


def test_redirects_followed_and_final_url_reported():
    def handler(request):
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "https://example.com/new"})
        return httpx.Response(200, text="<html></html>", headers={"Content-Type": "text/html"})

    response = _client(handler).get("https://example.com/old", timeout=20)
    assert response.url == "https://example.com/new"
    assert response.status == 200
    assert response.body == b"<html></html>"
    assert response.headers["content-type"] == "text/html"  # keys lower-cased


def test_too_many_redirects():
    def handler(request):
        return httpx.Response(302, headers={"location": str(request.url)})

    with pytest.raises(FetchError) as info:
        _client(handler, max_redirects=3).get("https://loop.test/", timeout=10)
    assert info.value.kind == "too_many_redirects"


def test_timeout():
    def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(FetchError) as info:
        _client(handler).head("https://slow.test/", timeout=10)
    assert info.value.kind == "timeout"
    assert "10 s" in str(info.value)


def test_dns_failure():
    def handler(request):
        raise httpx.ConnectError("[Errno 11001] getaddrinfo failed", request=request)

    with pytest.raises(FetchError) as info:
        _client(handler).head("https://nowhere.invalid/", timeout=10)
    assert info.value.kind == "dns"


def test_connection_refused():
    def handler(request):
        raise httpx.ConnectError("[Errno 111] Connection refused", request=request)

    with pytest.raises(FetchError) as info:
        _client(handler).head("https://refused.test/", timeout=10)
    assert info.value.kind == "connection"
