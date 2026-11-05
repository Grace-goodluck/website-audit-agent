# Website Audit Agent — SCOPE

## Goal
Audit one web page and produce a plain-English report: what was checked, what passed, what failed, and prioritised fixes.

## Design decisions (2026-11-05)
1. Scope: one page per run (URL given on the command line). No crawling of other pages.
2. Checks are deterministic Python, no AI: HTTP status and HTTPS; response time and page size; <title> present and length; meta description present and length; viewport meta tag (mobile); exactly one <h1>; images missing alt text; Open Graph tags; favicon; broken links on the page (internal and external, at most 30 checked, 10 s timeout each).
3. One Gemini call (gemini-3.8-flash, env var AUDIT_AGENT_MODEL) writes the summary and prioritised fixes from the check results only, never from the raw page. Same cache, shared pacer and retry rules as job_application_agent (503 and dropped connections retried twice; 429 never). If the Gemini call fails, the report is still written from the checks, marked "summary unavailable".
4. Interface: command-line tool writing a Markdown report to reports/. Logic separate from input/output.

## Ethics
Audit only sites you own or have permission to audit. One page fetch plus at most 30 link checks per run; identify the tool in the User-Agent.

## Evaluation
- Unit tests use saved HTML fixtures and fake HTTP: no test touches the network or Gemini.
- A fixture page with known, deliberate problems; expected findings written by hand before running.
- Live runs on Grace's own sites (techbygrace.com and artisan-service-app.vercel.app), expected findings written before running.

## Out of scope for v1
Crawling whole sites, performance scoring like Lighthouse, accessibility beyond alt text, fixing pages automatically.
