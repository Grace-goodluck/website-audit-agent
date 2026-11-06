"""Blocks requests to non-public addresses (web decision 10).

Strangers choose the URL, so every request the audit makes — the page, the
favicon, every link and every redirect hop — must go to a public address on
a standard port. UrlGuard checks one URL after DNS resolution;
SafeHttpxClient runs it as an httpx request hook, which httpx calls for
each request it sends, redirect hops included.

Known limit: the guard resolves the name, then httpx resolves it again to
connect, so a DNS answer that changes in between (DNS rebinding) is not caught.
"""

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx

from website_audit_agent.http_client import HttpxClient
from website_audit_agent.ports import FetchError

DEFAULT_PORTS = {"http": 80, "https": 443}

Resolver = Callable[[str, int], list[str]]


class BlockedUrl(ValueError):
    """The URL may not be requested. The message says why in plain English; `label` is the
    short form used in link results, e.g. "private address"."""

    def __init__(self, message: str, label: str) -> None:
        super().__init__(message)
        self.label = label


def system_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def is_public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])  # drop an IPv6 zone id
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped  # ::ffff:127.0.0.1 is loopback
    return ip.is_global and not ip.is_multicast


class UrlGuard:
    def __init__(self, resolver: Resolver = system_resolver) -> None:
        self._resolver = resolver

    def check(self, url: str) -> None:
        """Return quietly, or raise BlockedUrl (not allowed) / FetchError("dns") (cannot resolve)."""
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        if scheme not in DEFAULT_PORTS:
            raise BlockedUrl("only http and https URLs are allowed", "scheme not allowed")
        host = parts.hostname
        if not host:
            raise BlockedUrl("the URL has no host name", "no host name")
        try:
            port = parts.port
        except ValueError as exc:
            raise BlockedUrl("the URL has an invalid port", "invalid port") from exc
        if port is not None and port != DEFAULT_PORTS[scheme]:
            raise BlockedUrl(
                f"only the standard port for {scheme} ({DEFAULT_PORTS[scheme]}) is allowed", "non-standard port"
            )

        try:
            addresses = self._resolver(host, DEFAULT_PORTS[scheme])
        except OSError as exc:
            raise FetchError("dns", f"DNS failure: could not resolve {host}") from exc
        if not addresses:
            raise FetchError("dns", f"DNS failure: no address for {host}")
        if not all(is_public_ip(a) for a in addresses):
            # "private address" covers every non-public address: loopback, private, link-local, reserved.
            raise BlockedUrl(f"{host} is not a public internet address", "private address")


class SafeHttpxClient(HttpxClient):
    """HttpxClient that refuses non-public destinations, including redirect targets."""

    def __init__(self, guard: UrlGuard, **kwargs) -> None:
        super().__init__(**kwargs)
        self._guard = guard
        self._client.event_hooks = {"request": [self._check_request], "response": []}

    def _check_request(self, request: httpx.Request) -> None:
        try:
            self._guard.check(str(request.url))
        except BlockedUrl as exc:
            # Links get "unknown (blocked: <label>)", not broken (web decision 12).
            raise FetchError("blocked", exc.label) from exc
