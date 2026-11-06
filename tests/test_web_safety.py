"""Web decision 10: only public addresses on standard ports, checked after DNS and on every redirect."""

import socket

import httpx
import pytest

from fakes import fake_resolver
from website_audit_agent.ports import FetchError
from website_audit_agent.web.safe_http import BlockedUrl, SafeHttpxClient, UrlGuard, is_public_ip


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://127.0.0.1/",
        "http://127.8.9.10/",
        "http://10.0.0.5/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://100.64.0.1/",
        "http://0.0.0.0/",
        "http://240.0.0.1/",
        "http://[::1]/",
        "http://[fe80::1]/",
        "http://[fc00::1]/",
        "http://[::ffff:127.0.0.1]/",
    ],
)
def test_non_public_addresses_blocked(url):
    with pytest.raises(BlockedUrl, match="not a public internet address") as info:
        UrlGuard(fake_resolver()).check(url)
    assert info.value.label == "private address"


def test_hostname_resolving_to_private_address_blocked():
    guard = UrlGuard(fake_resolver({"intranet.example": ["10.1.2.3"]}))
    with pytest.raises(BlockedUrl):
        guard.check("https://intranet.example/")


def test_hostname_with_any_private_address_blocked():
    guard = UrlGuard(fake_resolver({"mixed.example": ["93.184.216.34", "192.168.0.10"]}))
    with pytest.raises(BlockedUrl):
        guard.check("https://mixed.example/")


@pytest.mark.parametrize(
    "url, message, label",
    [
        ("ftp://example.com/", "only http and https", "scheme not allowed"),
        ("file:///etc/passwd", "only http and https", "scheme not allowed"),
        ("https:///no-host", "no host name", "no host name"),
        ("https://example.com:8443/", "standard port for https", "non-standard port"),
        ("http://example.com:443/", "standard port for http", "non-standard port"),
        ("https://example.com:99999/", "invalid port", "invalid port"),
    ],
)
def test_scheme_and_port_rules(url, message, label):
    with pytest.raises(BlockedUrl, match=message) as info:
        UrlGuard(fake_resolver()).check(url)
    assert info.value.label == label


@pytest.mark.parametrize("url", ["https://example.com/", "http://example.com:80/x", "https://example.com:443/?q=1"])
def test_public_urls_on_standard_ports_allowed(url):
    UrlGuard(fake_resolver()).check(url)  # no exception


def test_dns_failure_is_a_fetch_error():
    guard = UrlGuard(fake_resolver({"nowhere.example": socket.gaierror("getaddrinfo failed")}))
    with pytest.raises(FetchError) as info:
        guard.check("https://nowhere.example/")
    assert info.value.kind == "dns"


def test_is_public_ip():
    assert is_public_ip("93.184.216.34")
    assert is_public_ip("2606:2800:220:1:248:1893:25c8:1946")
    assert not is_public_ip("224.0.0.1")  # multicast
    assert not is_public_ip("fe80::1%eth0")  # zone id stripped, still link-local


# --- SafeHttpxClient: the guard runs on every request, redirect hops included ----------

def _client(handler, resolver_table=None):
    return SafeHttpxClient(UrlGuard(fake_resolver(resolver_table)), transport=httpx.MockTransport(handler))


def test_private_start_url_never_sent():
    sent = []

    def handler(request):
        sent.append(str(request.url))
        return httpx.Response(200)

    with pytest.raises(FetchError) as info:
        _client(handler).get("http://127.0.0.1/", timeout=5)
    assert info.value.kind == "blocked" and str(info.value) == "private address"
    assert sent == []


def test_redirect_to_private_address_blocked_before_it_is_sent():
    sent = []

    def handler(request):
        sent.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})

    with pytest.raises(FetchError) as info:
        _client(handler).get("https://example.com/", timeout=5)
    assert info.value.kind == "blocked" and str(info.value) == "private address"
    assert sent == ["https://example.com/"]


def test_redirect_to_name_resolving_privately_blocked():
    sent = []

    def handler(request):
        sent.append(str(request.url))
        return httpx.Response(301, headers={"location": "https://intranet.example/"})

    with pytest.raises(FetchError) as info:
        _client(handler, {"intranet.example": ["10.0.0.7"]}).head("https://example.com/", timeout=5)
    assert info.value.kind == "blocked" and str(info.value) == "private address"
    assert sent == ["https://example.com/"]


def test_public_redirect_followed():
    def handler(request):
        if request.url.host == "example.com":
            return httpx.Response(301, headers={"location": "https://www.example.com/"})
        return httpx.Response(200, text="ok")

    response = _client(handler).get("https://example.com/", timeout=5)
    assert response.status == 200 and response.url == "https://www.example.com/"
