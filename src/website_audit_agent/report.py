"""Markdown report: render (pure) and write to reports/<host>-YYYYMMDD-HHMMSS.md."""

import re
from pathlib import Path
from urllib.parse import urlparse

from website_audit_agent.models import Report

UNAVAILABLE = "Summary unavailable"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def report_filename(report: Report) -> str:
    host = urlparse(report.url).hostname or "page"
    host = re.sub(r"[^A-Za-z0-9.-]", "_", host)
    return f"{host}-{report.audited_at:%Y%m%d-%H%M%S}.md"


def render_markdown(report: Report) -> str:
    lines = [f"# Website audit: {report.url}", ""]
    lines.append(f"- Audited: {report.audited_at:%Y-%m-%d %H:%M:%S}")
    if report.final_url and report.final_url != report.url:
        lines.append(f"- Final URL: {report.final_url}")
    lines.append(f"- Summary model: {report.model}")

    if report.fetch_error is not None:
        lines += ["", "## Page could not be fetched", "", f"{report.checks[0].detail}", ""]
        lines += ["No other checks were run.", "", f"_{UNAVAILABLE}: {report.summary.reason}._", ""]
        return "\n".join(lines)

    passed = sum(r.passed for r in report.checks)
    lines.append(f"- Result: {passed} of {len(report.checks)} checks passed")
    failed = [r for r in report.checks if not r.passed]

    lines += ["", "## Summary", ""]
    if report.summary.available:
        lines.append(report.summary.text)
    else:
        lines.append(f"**{UNAVAILABLE}** ({report.summary.reason}). The check results below are complete.")

    lines += ["", "## Prioritised fixes", ""]
    if report.summary.available:
        if report.summary.fixes:
            lines += [f"{i}. **{f.check}**: {f.text}" for i, f in enumerate(report.summary.fixes, 1)]
        else:
            lines.append("No fixes suggested.")
        if report.summary.dropped_fixes:
            n = report.summary.dropped_fixes
            lines += ["", f"_{n} suggested fix{'es were' if n != 1 else ' was'} dropped for not naming a failed check._"]
    elif failed:
        lines.append("Not prioritised (no summary). Failed checks:")
        lines.append("")
        lines += [f"- **{r.name}**: {r.detail}" for r in failed]
    else:
        lines.append("All checks passed.")

    lines += ["", "## Checks", "", "| Check | Result | Detail |", "|---|---|---|"]
    lines += [f"| {r.name} | {'PASS' if r.passed else 'FAIL'} | {_cell(r.detail)} |" for r in report.checks]

    # Failed checks, plus broken_links when it passed but has unknown (blocked) links to show.
    with_items = [r for r in report.checks if r.items and (not r.passed or r.name == "broken_links")]
    if with_items:
        lines += ["", "## Details"]
        for r in with_items:
            lines += ["", f"### {r.name}", ""]
            lines += [f"- {item}" for item in r.items]

    lines.append("")
    return "\n".join(lines)


def write_report(report: Report, directory: Path) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / report_filename(report)
    path.write_text(render_markdown(report), encoding="utf-8")
    return path
