"""Plain data passed between the pieces. No behaviour, no I/O."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class HttpResponse:
    url: str  # final URL after redirects
    status: int
    headers: Mapping[str, str]  # keys lower-cased
    body: bytes
    elapsed_s: float


@dataclass(frozen=True)
class FetchedPage:
    requested_url: str
    final_url: str
    status: int
    headers: Mapping[str, str]
    html: str
    size_bytes: int
    elapsed_s: float


LinkOutcome = Literal["ok", "broken", "blocked", "unknown"]


@dataclass(frozen=True)
class LinkStatus:
    url: str
    outcome: LinkOutcome
    detail: str  # e.g. "404", "timeout", "DNS failure"


@dataclass(frozen=True)
class CheckResult:
    name: str  # "title", "meta_description", "broken_links", ...
    passed: bool
    detail: str  # plain English
    items: tuple[str, ...] = ()  # e.g. image srcs missing alt, broken URLs


@dataclass(frozen=True)
class Fix:
    check: str  # name of the failed check it addresses
    text: str


@dataclass(frozen=True)
class Summary:
    available: bool
    text: str = ""
    fixes: tuple[Fix, ...] = ()  # highest priority first
    dropped_fixes: int = 0  # fixes that did not name a failed check (continued #11)
    reason: str = ""  # why unavailable


@dataclass(frozen=True)
class Report:
    url: str
    final_url: str | None
    audited_at: datetime
    model: str
    checks: tuple[CheckResult, ...]
    summary: Summary
    fetch_error: str | None = None  # set: the page itself could not be fetched (short report)

    @property
    def ok(self) -> bool:
        """Exit 0 only when the page was fetched and the summary was written."""
        return self.fetch_error is None and self.summary.available
