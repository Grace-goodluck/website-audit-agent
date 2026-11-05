"""Gemini summary and ranked fixes. Never raises: a failure becomes Summary(available=False)."""

import json
import re
from collections.abc import Sequence

from website_audit_agent.models import CheckResult, Fix, Summary
from website_audit_agent.ports import LLM, LLMError
from website_audit_agent.prompts import build_summary_prompt

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


def _strip_fence(text: str) -> str:
    match = _FENCE.match(text)
    return match.group(1) if match else text.strip()


def parse_summary_reply(reply: str, failed_checks: set[str]) -> Summary:
    """Raises ValueError when the reply is not the expected JSON."""
    data = json.loads(_strip_fence(reply))
    if not isinstance(data, dict):
        raise ValueError("reply is not a JSON object")
    text = data.get("summary")
    if not isinstance(text, str) or not text.strip():
        raise ValueError('reply has no "summary" text')
    raw_fixes = data.get("fixes", [])
    if not isinstance(raw_fixes, list):
        raise ValueError('"fixes" is not a list')

    fixes: list[Fix] = []
    dropped = 0
    for item in raw_fixes:
        check = item.get("check") if isinstance(item, dict) else None
        fix = item.get("fix") if isinstance(item, dict) else None
        if isinstance(check, str) and check in failed_checks and isinstance(fix, str) and fix.strip():
            fixes.append(Fix(check=check, text=fix.strip()))
        else:
            dropped += 1  # continued #11: a fix must name a failed check
    return Summary(available=True, text=text.strip(), fixes=tuple(fixes), dropped_fixes=dropped)


def summarise(results: Sequence[CheckResult], llm: LLM) -> Summary:
    failed = {r.name for r in results if not r.passed}
    try:
        reply = llm.generate(build_summary_prompt(results))
    except LLMError as exc:
        return Summary(available=False, reason=str(exc))
    try:
        return parse_summary_reply(reply, failed)
    except ValueError as exc:  # json.JSONDecodeError is a ValueError
        return Summary(available=False, reason=f"Gemini reply could not be read: {exc}")
