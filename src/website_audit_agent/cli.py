"""Command line: website-audit <url>. Wires real clients, writes the report.

Exit codes: 0 report with summary; 1 report written but summary unavailable
or page not fetched (continued #1, #8); 2 bad command-line arguments.
"""

import argparse
import sys
from urllib.parse import urlparse

from website_audit_agent.audit import run_audit
from website_audit_agent.config import load_config
from website_audit_agent.gemini_client import DiskCache, GeminiLLM, make_gemini_call
from website_audit_agent.http_client import HttpxClient
from website_audit_agent.pacing import Pacer
from website_audit_agent.report import write_report


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="website-audit",
        description="Audit one web page you own or have permission to audit, and write a Markdown report to reports/.",
    )
    parser.add_argument("url", help="full page URL, e.g. https://techbygrace.com/")
    args = parser.parse_args(argv)
    parsed = urlparse(args.url)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        parser.error(f"not an http(s) URL: {args.url!r}")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    config = load_config()

    llm = None
    if config.gemini_api_key:
        call = make_gemini_call(config.model, config.gemini_api_key)
        llm = GeminiLLM(config.model, call, DiskCache(config.cache_dir), Pacer())

    http = HttpxClient()
    try:
        report = run_audit(args.url, http, llm, config.model)
    finally:
        http.close()

    path = write_report(report, config.reports_dir)
    print(f"Report written: {path}")
    if report.fetch_error is not None:
        print(f"Page could not be fetched: {report.fetch_error}", file=sys.stderr)
    elif not report.summary.available:
        print(f"Summary unavailable: {report.summary.reason}", file=sys.stderr)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
