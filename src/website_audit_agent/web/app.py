"""FastAPI web demo over the unchanged audit (decisions 2026-11-06: web demo).

Run with `website-audit-web` (main() below): listens on $PORT, which Render sets, else 8000.

create_app() takes every dependency as an argument so tests pass fakes;
build_default_app() wires the real clients from environment variables.
"""

import logging
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from website_audit_agent.audit import FETCH_FAILED_REASON, NO_KEY_REASON, run_audit
from website_audit_agent.config import USER_AGENT, load_config
from website_audit_agent.gemini_client import DiskCache, GeminiLLM, make_gemini_call
from website_audit_agent.models import Report
from website_audit_agent.pacing import Pacer
from website_audit_agent.ports import LLM, FetchError, HttpClient
from website_audit_agent.report import render_markdown, report_filename
from website_audit_agent.web.jobs import Executor, JobStore
from website_audit_agent.web.limits import SUMMARY_CAP_REASON, GuardedLLM, Limiter, Limits
from website_audit_agent.web.safe_http import BlockedUrl, SafeHttpxClient, UrlGuard

log = logging.getLogger("website_audit_agent.web")
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))  # autoescapes .html

PUBLIC_REASONS = {
    SUMMARY_CAP_REASON: "the demo's daily limit of AI summaries has been reached; it resets at midnight Pacific time",
    NO_KEY_REASON: "the AI summary is not configured on this demo",
    FETCH_FAILED_REASON: "the page could not be fetched",
}
PUBLIC_BUSY = "the AI service is busy or failed"


@dataclass(frozen=True)
class WebSettings:
    link_cap: int = 15  # web decision 4
    link_timeout_s: float = 5.0  # web decision 4
    gemini_retry_waits_s: tuple[float, ...] = (10.0,)  # web decision 6: one retry after 10 s
    limits: Limits = field(default_factory=Limits)
    cache_dir: Path = Path("/tmp/website-audit-cache")
    max_concurrent_audits: int = 2


def visitor_id(request: Request) -> str:
    """First IP in X-Forwarded-For (web decision 2), else the direct peer."""
    first = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return first or (request.client.host if request.client else "unknown")


def public_report(report: Report) -> Report:
    """Replace internal failure detail (Gemini errors) with a public reason."""
    if report.summary.available:
        return report
    reason = PUBLIC_REASONS.get(report.summary.reason, PUBLIC_BUSY)
    return replace(report, summary=replace(report.summary, reason=reason))


def result_label(report: Report) -> str:
    if report.fetch_error is not None:
        return "fetch_failed"
    passed = sum(r.passed for r in report.checks)
    summary = "summary" if report.summary.available else "no_summary"
    return f"{passed}/{len(report.checks)}_passed,{summary}"


def create_app(
    *,
    http: HttpClient,
    llm: LLM | None,
    model: str,
    guard: UrlGuard,
    limiter: Limiter,
    settings: WebSettings = WebSettings(),
    executor: Executor | None = None,
) -> FastAPI:
    app = FastAPI(title="Website Audit Agent", docs_url=None, redoc_url=None, openapi_url=None)
    guarded_llm = GuardedLLM(llm, limiter) if llm is not None else None

    def run(url: str) -> Report:
        report = run_audit(
            url, http, guarded_llm, model,
            link_cap=settings.link_cap, link_timeout=settings.link_timeout_s,
        )
        log.info("audit host=%s result=%s", urlsplit(url).hostname, result_label(report))  # web decision 8
        return public_report(report)

    jobs = JobStore(run, executor, max_workers=settings.max_concurrent_audits)

    def page(request: Request, name: str, status: int = 200, headers: dict | None = None, **context) -> Response:
        context = {"limits": settings.limits, "link_cap": settings.link_cap, "user_agent": USER_AGENT, **context}
        return TEMPLATES.TemplateResponse(request, name, context, status_code=status, headers=headers)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> Response:
        return page(request, "index.html")

    @app.post("/audit")
    def start_audit(request: Request, url: str = Form(""), confirm: str = Form("")) -> Response:
        url = url.strip()
        if confirm != "yes":  # web decision 5
            return page(request, "index.html", 400, url=url,
                        error="Please confirm that you own this site or have permission to audit it.")
        try:
            guard.check(url)  # web decision 10; the HTTP client checks again on every request
        except (BlockedUrl, FetchError) as exc:
            return page(request, "index.html", 400, url=url, error=f"This URL can't be audited: {exc}.")

        refusal = limiter.try_start_audit(visitor_id(request))
        if refusal is not None:
            log.info("refused host=%s result=limit", urlsplit(url).hostname)
            return page(request, "index.html", 429, {"Retry-After": str(refusal.retry_after_s)},
                        url=url, error=refusal.message)

        job = jobs.submit(url)
        return RedirectResponse(f"/audit/{job.id}", status_code=303)

    @app.get("/audit/{job_id}", response_class=HTMLResponse)
    def show_audit(request: Request, job_id: str) -> Response:
        job = jobs.get(job_id)
        if job is None:
            return page(request, "index.html", 404, error="That audit was not found. Results are kept for a limited time.")
        return page(request, "result.html", job=job)

    @app.get("/audit/{job_id}/report.md")
    def download_report(job_id: str) -> Response:
        job = jobs.get(job_id)
        if job is None or job.report is None:
            return PlainTextResponse("Not found", status_code=404)
        return PlainTextResponse(
            render_markdown(job.report),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{report_filename(job.report)}"'},
        )

    @app.api_route("/health", methods=["GET", "HEAD"])  # UptimeRobot's HTTP monitors send HEAD
    def health() -> Response:
        """For Render and UptimeRobot: answers at once, no audit, no Gemini call."""
        return PlainTextResponse("ok")

    return app


def build_default_app() -> FastAPI:
    """Real wiring. GEMINI_API_KEY comes from the host's secret environment settings (web decision 7)."""
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s")
    log.setLevel(logging.INFO)  # our lines carry only time, host and result; httpx's (full URLs) stay at WARNING

    settings = WebSettings(cache_dir=Path(os.environ.get("AUDIT_CACHE_DIR", "/tmp/website-audit-cache")))
    config = load_config()
    llm = None
    if config.gemini_api_key:
        llm = GeminiLLM(
            config.model,
            make_gemini_call(config.model, config.gemini_api_key),
            DiskCache(settings.cache_dir),
            Pacer(),
            retry_waits=settings.gemini_retry_waits_s,
        )
    guard = UrlGuard()
    return create_app(
        http=SafeHttpxClient(guard),
        llm=llm,
        model=config.model,
        guard=guard,
        limiter=Limiter(settings.limits),
        settings=settings,
    )


DEFAULT_PORT = 8000


def port_from_env(env: dict[str, str] | None = None) -> int:
    """Render provides the port in PORT; locally fall back to 8000. A bad value fails loudly."""
    value = (os.environ if env is None else env).get("PORT", "").strip()
    return int(value) if value else DEFAULT_PORT


def main() -> None:
    """Entry point `website-audit-web` (used by the Dockerfile)."""
    import uvicorn  # only in the `web` extra

    uvicorn.run(
        "website_audit_agent.web.app:build_default_app",
        factory=True,
        host="0.0.0.0",
        port=port_from_env(),
        access_log=False,  # web decision 8: no full URLs or client IPs in the logs
    )
