"""The real HttpClient: httpx, with the tool's User-Agent on every request.

Every network failure becomes a FetchError with a kind the link checker
can classify (continued #4). Tests pass an httpx.MockTransport.
"""

import socket
import time

import httpx

from website_audit_agent.config import MAX_REDIRECTS, USER_AGENT
from website_audit_agent.models import HttpResponse
from website_audit_agent.ports import FetchError

_DNS_MESSAGES = ("getaddrinfo failed", "name or service not known", "nodename nor servname", "no address associated")


def _is_dns_failure(exc: BaseException) -> bool:
    """httpx wraps socket.gaierror; walk the cause chain, then fall back to the message."""
    seen: BaseException | None = exc
    while seen is not None:
        if isinstance(seen, socket.gaierror):
            return True
        seen = seen.__cause__ or seen.__context__
    text = str(exc).lower()
    return any(m in text for m in _DNS_MESSAGES)


class HttpxClient:
    def __init__(
        self,
        user_agent: str = USER_AGENT,
        max_redirects: int = MAX_REDIRECTS,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            headers={"User-Agent": user_agent},
            follow_redirects=True,
            max_redirects=max_redirects,
            transport=transport,
        )

    def get(self, url: str, timeout: float) -> HttpResponse:
        return self._request("GET", url, timeout)

    def head(self, url: str, timeout: float) -> HttpResponse:
        return self._request("HEAD", url, timeout)

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, url: str, timeout: float) -> HttpResponse:
        start = time.monotonic()
        try:
            response = self._client.request(method, url, timeout=timeout)
        except httpx.TooManyRedirects as exc:
            raise FetchError("too_many_redirects", f"too many redirects: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise FetchError("timeout", f"timed out after {timeout:g} s") from exc
        except httpx.ConnectError as exc:
            kind = "dns" if _is_dns_failure(exc) else "connection"
            raise FetchError(kind, f"{'DNS failure' if kind == 'dns' else 'connection failed'}: {exc}") from exc
        except httpx.HTTPError as exc:
            raise FetchError("connection", f"request failed: {exc}") from exc
        return HttpResponse(
            url=str(response.url),
            status=response.status_code,
            headers={k.lower(): v for k, v in response.headers.items()},
            body=response.content,
            elapsed_s=time.monotonic() - start,
        )
