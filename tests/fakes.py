"""Fakes for the two ports. No test touches the network or Gemini."""

import ipaddress
from datetime import datetime, timedelta, timezone
from pathlib import Path

from website_audit_agent.models import FetchedPage, HttpResponse

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def make_page(
    html: str,
    url: str = "https://example.com/",
    status: int = 200,
    elapsed_s: float = 0.5,
    size_bytes: int | None = None,
    final_url: str | None = None,
) -> FetchedPage:
    return FetchedPage(
        requested_url=url,
        final_url=final_url or url,
        status=status,
        headers={"content-type": "text/html; charset=utf-8"},
        html=html,
        size_bytes=len(html.encode("utf-8")) if size_bytes is None else size_bytes,
        elapsed_s=elapsed_s,
    )


def html_response(url: str, html: str, status: int = 200, elapsed_s: float = 0.5) -> HttpResponse:
    return HttpResponse(
        url=url,
        status=status,
        headers={"content-type": "text/html; charset=utf-8"},
        body=html.encode("utf-8"),
        elapsed_s=elapsed_s,
    )


class FakeHttp:
    """Routes keyed by (METHOD, url) or url. A route is an HttpResponse, an int
    status, or an Exception (raised). Unrouted URLs get `default` (None: fail the test).
    Every call is recorded as (method, url, timeout)."""

    def __init__(self, routes: dict | None = None, default: object | None = 200) -> None:
        self.routes = dict(routes or {})
        self.default = default
        self.calls: list[tuple[str, str, float]] = []

    def get(self, url: str, timeout: float) -> HttpResponse:
        return self._respond("GET", url, timeout)

    def head(self, url: str, timeout: float) -> HttpResponse:
        return self._respond("HEAD", url, timeout)

    def close(self) -> None:
        pass

    def _respond(self, method: str, url: str, timeout: float) -> HttpResponse:
        self.calls.append((method, url, timeout))
        entry = self.routes.get((method, url), self.routes.get(url, self.default))
        if entry is None:
            raise AssertionError(f"FakeHttp got an unexpected {method} {url}")
        if isinstance(entry, Exception):
            raise entry
        if isinstance(entry, int):
            return HttpResponse(url=url, status=entry, headers={}, body=b"", elapsed_s=0.01)
        return entry

    def urls(self, method: str | None = None) -> list[str]:
        return [u for m, u, _ in self.calls if method is None or m == method]


class FakeClock:
    """Stands in for time.monotonic/time.sleep: sleeping advances the clock."""

    def __init__(self) -> None:
        self.t = 1000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


PUBLIC_IP = "93.184.216.34"


def fake_resolver(table: dict[str, object] | None = None):
    """DNS stand-in for UrlGuard. IP literals resolve to themselves; `localhost` to 127.0.0.1;
    other names to `table[name]` (a list of addresses, or an exception to raise), else PUBLIC_IP."""
    table = {"localhost": ["127.0.0.1", "::1"], **(table or {})}

    def resolve(host: str, port: int) -> list[str]:
        try:
            ipaddress.ip_address(host)
            return [host]
        except ValueError:
            pass
        value = table.get(host, [PUBLIC_IP])
        if isinstance(value, Exception):
            raise value
        return list(value)

    return resolve


class FakeNow:
    """Stands in for utc_now in the web limiter; advance() moves time on."""

    def __init__(self, start: datetime = datetime(2026, 11, 6, 20, 0, tzinfo=timezone.utc)) -> None:
        self.t = start

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **delta: float) -> None:
        self.t += timedelta(**delta)


class ImmediateExecutor:
    """Runs a web job synchronously, so tests need no threads."""

    def submit(self, fn, /, *args):
        fn(*args)


class FakeLLM:
    """Returns scripted replies in order and records every prompt.

    A scripted item that is an Exception instance is raised instead.
    """

    def __init__(self, replies: list[object], model: str = "fake-model") -> None:
        self.model = model
        self._replies = list(replies)
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._replies:
            raise AssertionError(f"FakeLLM got an unexpected call #{len(self.prompts)}:\n{prompt[:300]}")
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
