# Expected findings: Artisaan's Crib

Written by Grace on 2026-11-06, before the first live run.

URL: `https://artisan-service-app.vercel.app`

| Check | Prediction |
|---|---|
| http_status | pass |
| https | pass |
| response_time | unsure |
| page_size | pass |
| title | unsure |
| meta_description | unsure |
| viewport | pass |
| h1 | unsure |
| image_alt | unsure |
| open_graph | fail |
| favicon | unsure |
| broken_links | unsure |

## After the run

First run: 2026-11-06 11:08:47.
Report: [reports/artisan-service-app.vercel.app-20261106-110847.md](../reports/artisan-service-app.vercel.app-20261106-110847.md).
Exit code: 1. All 12 checks ran, but the summary is unavailable: Gemini returned 503 UNAVAILABLE (high demand) on the first try and on both retries. The report was written from the checks alone (decision 3).

| Check | Prediction | Actual | Detail |
|---|---|---|---|
| http_status | pass | PASS ✓ | HTTP 200 |
| https | pass | PASS ✓ | served over HTTPS |
| response_time | unsure | PASS | 2.70 s, just under the 3 s limit |
| page_size | pass | PASS ✓ | 25.3 KB |
| title | unsure | FAIL | "Artisaan's Crib" is 15 characters (aim for 30–60) |
| meta_description | unsure | FAIL | "Find skilled artisans near you across Nigeria" is 45 characters (aim for 70–160) |
| viewport | pass | PASS ✓ | `width=device-width, initial-scale=1.0` |
| h1 | unsure | PASS | exactly one `<h1>` |
| image_alt | unsure | PASS | both images have alt text |
| open_graph | fail | FAIL ✓ | og:title, og:description and og:image missing (og:url too) |
| favicon | unsure | FAIL | no `<link rel="icon">`; `/favicon.ico` returned 404 |
| broken_links | unsure | PASS | 13 of 13 links checked, none broken; none unknown |

Wrong predictions: none. All 5 definite predictions were correct.
The 7 "unsure" checks: 4 passed (response_time, h1, image_alt, broken_links) and 3 failed (title, meta_description, favicon).

Notes:
- response_time passed by only 0.3 s, so it may flip on another run.
- The summary still needs a successful Gemini run. A rerun will not hit the cache: the failed reply was not stored, and the prompt changes with the response time.
