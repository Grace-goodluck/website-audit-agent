"""Configuration from environment variables only — never loads a .env file.

Paths are relative to the current working directory: run the tool from the
project root so the cache lands in results/cache/ and reports in reports/.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL = "gemini-3.8-flash"
USER_AGENT = "TechByGrace-WebsiteAudit/0.1 (+https://techbygrace.com)"  # continued #12

PAGE_TIMEOUT_S = 20.0  # continued #8
LINK_TIMEOUT_S = 10.0  # decision 2
LINK_CAP = 30  # decision 2
MAX_REDIRECTS = 10

TITLE_MIN, TITLE_MAX = 30, 60  # continued #2
META_DESC_MIN, META_DESC_MAX = 70, 160
SLOW_RESPONSE_S = 3.0
LARGE_PAGE_BYTES = 2 * 1024 * 1024

MIN_CALL_SPACING_S = 13.0  # job agent's pacer (continued #9)
GEMINI_RETRY_WAITS_S = (30.0, 60.0)  # 503 / dropped connection; a 429 is never retried

CACHE_DIR = Path("results/cache")
REPORTS_DIR = Path("reports")


@dataclass(frozen=True)
class Config:
    gemini_api_key: str | None  # None: run the checks, mark the summary unavailable (continued #1)
    model: str = DEFAULT_MODEL
    cache_dir: Path = CACHE_DIR
    reports_dir: Path = REPORTS_DIR


def load_config(env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env
    api_key = env.get("GEMINI_API_KEY", "").strip() or None
    model = env.get("AUDIT_AGENT_MODEL", "").strip() or DEFAULT_MODEL
    return Config(gemini_api_key=api_key, model=model)
