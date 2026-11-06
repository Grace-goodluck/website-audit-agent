# Website Audit Agent

Audits one web page and writes a plain-English report: what was checked, what passed, what failed,
and prioritised fixes. The checks are deterministic Python; one Gemini call writes the summary from
the check results only, never from the raw page. See [SCOPE.md](SCOPE.md) for every decision.

**Audit only sites you own or have permission to audit.**

## Checks

HTTP status, HTTPS, response time (≤ 3 s), page size (≤ 2 MB), `<title>` length (30–60), meta
description length (70–160), viewport meta tag, exactly one `<h1>`, image alt text, Open Graph
(og:title, og:description, og:image), favicon, and broken links.

## Command line

```sh
uv sync
GEMINI_API_KEY=... uv run website-audit https://example.com/
```

The report is written to `reports/<host>-YYYYMMDD-HHMMSS.md`. Exit codes: 0 report with summary;
1 report written without a summary, or the page could not be fetched; 2 bad arguments.
Without `GEMINI_API_KEY` the checks still run and the summary is marked unavailable.

## Web demo (Render)

A FastAPI layer over the same audit, with limits for a public demo: 3 audits per visitor per hour,
30 audits and 15 AI summaries per day (reset at midnight Pacific time), 15 links per audit at 5 s each,
and requests to localhost, private, link-local and reserved addresses blocked.

Run locally:

```sh
uv sync --extra web
uv run website-audit-web          # http://localhost:8000 (or the port in $PORT)
```

Deploy on Render as a free **Web Service** with runtime **Docker** (it builds the `Dockerfile`):

- Environment: add `GEMINI_API_KEY` as a secret environment variable in the Render dashboard; it is
  never stored in the code or the repo. Optionally set `AUDIT_AGENT_MODEL`.
- Health check path: `/health` (answers `ok` at once; runs no audit and no Gemini call).
- The app listens on the port Render provides in `PORT`.

Free Render services sleep when idle; an UptimeRobot monitor pings `/health` to keep the demo awake.
Limits are kept in memory, so they reset whenever the service restarts.

## Tests

```sh
uv run pytest
```

No test touches the network or Gemini.
