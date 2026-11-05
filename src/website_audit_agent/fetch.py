"""The one page fetch per run. FetchError propagates to the caller."""

import re

from website_audit_agent.config import PAGE_TIMEOUT_S
from website_audit_agent.models import FetchedPage
from website_audit_agent.ports import HttpClient

_CHARSET = re.compile(r"charset=[\"']?([\w.:-]+)", re.IGNORECASE)


def decode_body(body: bytes, content_type: str) -> str:
    match = _CHARSET.search(content_type or "")
    if match:
        try:
            return body.decode(match.group(1), errors="replace")
        except LookupError:  # unknown charset name
            pass
    return body.decode("utf-8", errors="replace")


def fetch_page(url: str, http: HttpClient, timeout: float = PAGE_TIMEOUT_S) -> FetchedPage:
    response = http.get(url, timeout)
    return FetchedPage(
        requested_url=url,
        final_url=response.url,
        status=response.status,
        headers=response.headers,
        html=decode_body(response.body, response.headers.get("content-type", "")),
        size_bytes=len(response.body),
        elapsed_s=response.elapsed_s,
    )
