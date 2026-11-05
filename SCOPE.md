# Website Audit Agent — SCOPE

## Goal
Audit one web page and produce a plain-English report: what was checked, what passed, what failed, and prioritised fixes.

## Design decisions (2026-11-05)
1. Scope: one page per run (URL given on the command line). No crawling of other pages.
2. Checks are deterministic Python, no AI: HTTP status and HTTPS; response time and page size; <title> present and length; meta description present and length; viewport meta tag (mobile); exactly one <h1>; images missing alt text; Open Graph tags; favicon; broken links on the page (internal and external, at most 30 checked, 10 s timeout each).
3. One Gemini call (gemini-3.8-flash, env var AUDIT_AGENT_MODEL) writes the summary and prioritised fixes from the check results only, never from the raw page. Same cache, shared pacer and retry rules as job_application_agent (503 and dropped connections retried twice; 429 never). If the Gemini call fails, the report is still written from the checks, marked "summary unavailable".
4. Interface: command-line tool writing a Markdown report to reports/. Logic separate from input/output.

## Decisions (2026-11-05, continued)
1. No GEMINI_API_KEY: still write the checks-only report marked "summary unavailable", then exit 1.
2. Thresholds: title 30–60 characters; meta description 70–160 characters; response slower than 3 s fails; page larger than 2 MB fails.
3. Links: the first 30 unique links in page order are checked. Skip mailto:, tel:, javascript: and #anchors.
4. A link is broken on 404/410, any 5xx, DNS failure, timeout or too many redirects. 401/403/429 is reported as "unknown (blocked)", not broken. Each link gets a HEAD request, falling back to GET on 405/501.
5. Favicon: a `<link rel="icon">` passes. Otherwise /favicon.ico is tried as one extra request.
6. Open Graph: og:title, og:description and og:image are required; og:url is optional. No Twitter cards in v1.
7. HTML is parsed with BeautifulSoup.
8. If the page itself cannot be fetched, write a short report and exit 1. The main page timeout is 20 s (each link check stays at 10 s).
9. Keep the job agent's pacer (13 s between calls).
10. Report filename: `<host>-YYYYMMDD-HHMMSS.md`. Commit reports/ and results/cache/.
11. Gemini replies in JSON: a summary plus ranked fixes. Each fix must name a failed check, otherwise it is dropped.
12. User-Agent: `TechByGrace-WebsiteAudit/0.1 (+https://techbygrace.com)`.

## Decisions (2026-11-05, implementation)
1. Twelve checks, one thing each: http_status, https, response_time, page_size, title, meta_description, viewport, h1, image_alt, open_graph, favicon, broken_links. This way each fix names a single check.
2. Other 4xx codes on a link (400, 418, …) are reported as "unknown (other status)", not broken.
3. A refused connection or SSL error on a link counts as broken.
4. If the main page returns a non-2xx status (e.g. 404), it is treated like a fetch failure: short report, exit 1.
5. If there is no `<link rel="icon">` and /favicon.ico returns 401/403/429, the favicon check fails.
6. Viewport passes when the meta tag is present and non-empty; `width=device-width` is not required.
7. An image with no alt attribute fails; `alt=""` passes (the correct markup for decorative images).
8. Timeouts are httpx's per-step timeouts (connect, then each read), not a hard limit on the whole request, so a very slow server can take longer than 10 s / 20 s in total.
9. Exit codes: 0 when the report has a summary; 1 when the report is written but the summary is unavailable or the page could not be fetched; 2 for bad command-line arguments, including a URL that isn't http(s).

## Ethics
Audit only sites you own or have permission to audit. One page fetch, at most one /favicon.ico request, plus at most 30 link checks per run; identify the tool in the User-Agent.

## Evaluation
- Unit tests use saved HTML fixtures and fake HTTP: no test touches the network or Gemini.
- A fixture page with known, deliberate problems; expected findings written by hand before running.
- Live runs on Grace's own sites (techbygrace.com and artisan-service-app.vercel.app), expected findings written before running.

## Out of scope for v1
Crawling whole sites, performance scoring like Lighthouse, accessibility beyond alt text, fixing pages automatically.
