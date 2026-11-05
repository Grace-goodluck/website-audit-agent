"""The two outside services the agent depends on, as interfaces.

The real implementations live in http_client.py and gemini_client.py;
tests pass fakes, so no test touches the network or Gemini.
"""

from typing import Literal, Protocol

from website_audit_agent.models import HttpResponse

FetchErrorKind = Literal["dns", "timeout", "too_many_redirects", "connection"]


class FetchError(Exception):
    """A request got no HTTP response at all."""

    def __init__(self, kind: FetchErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind


class HttpClient(Protocol):
    def get(self, url: str, timeout: float) -> HttpResponse:
        """Follow redirects; return the final response or raise FetchError."""
        ...

    def head(self, url: str, timeout: float) -> HttpResponse:
        """As get(), with an empty body."""
        ...


class LLMError(Exception):
    """A Gemini call failed (network, quota, empty reply...)."""


class LLM(Protocol):
    model: str

    def generate(self, prompt: str) -> str:
        """Return the model's reply text, or raise LLMError."""
        ...
