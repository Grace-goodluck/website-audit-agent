# Expected findings: techbygrace.com

Written by Grace on 2026-11-05, before the first live run.

URL: `https://techbygrace.com/`

| Check | Prediction |
|---|---|
| http_status | pass |
| https | pass |
| response_time | pass |
| page_size | unsure |
| title | unsure |
| meta_description | unsure |
| viewport | pass |
| h1 | unsure |
| image_alt | unsure |
| open_graph | fail |
| favicon | unsure |
| broken_links | unsure |

## After the run

An earlier attempt on 2026-11-05 22:31 could not connect to the site (timed out after 20 s; curl also failed to connect), so no checks ran. Report: [reports/techbygrace.com-20261105-223146.md](../reports/techbygrace.com-20261105-223146.md).

First full run: 2026-11-06 11:22:16.
Report: [reports/techbygrace.com-20261106-112216.md](../reports/techbygrace.com-20261106-112216.md).
Exit code: 1. All 12 checks ran, but the summary is unavailable: Gemini returned 503 UNAVAILABLE (high demand) on the first try and on both retries. The report was written from the checks alone (decision 3).

| Check | Prediction | Actual | Detail |
|---|---|---|---|
| http_status | pass | PASS ✓ | HTTP 200 |
| https | pass | PASS ✓ | served over HTTPS |
| response_time | pass | PASS ✓ | 1.86 s |
| page_size | unsure | PASS | 680.7 KB (limit 2 MB) |
| title | unsure | PASS | 36 characters (within 30–60) |
| meta_description | unsure | FAIL | no meta description |
| viewport | pass | PASS ✓ | `width=device-width, initial-scale=1.0` |
| h1 | unsure | PASS | exactly one `<h1>` |
| image_alt | unsure | PASS | both images have alt text |
| open_graph | fail | FAIL ✓ | og:title, og:description and og:image missing (og:url too) |
| favicon | unsure | FAIL | no `<link rel="icon">`; `/favicon.ico` returned 404 |
| broken_links | unsure | FAIL | 21 of 21 links checked: reported 2 broken, 3 unknown (blocked); see the tool issue below |

Wrong predictions: none. All 5 definite predictions were correct.
The 7 "unsure" checks: 4 passed (page_size, title, h1, image_alt) and 3 failed (meta_description, favicon, broken_links).

Links:
- BROKEN (404) https://wvs-happiness-analysis.vercel.app (a real broken link).
- Reported BROKEN (999) https://www.linkedin.com/in/grace-nwakama-it/. This is a false positive: 999 is LinkedIn's bot-blocking response, not a 5xx. The tool counts any status ≥ 500 as broken, but decision 4 says 5xx. With 500–599 only, this link would be "unknown", and broken_links would still fail on the 404 above.
- UNKNOWN, blocked (403) for 3 Udemy certificate links (ude.my).

Notes:
- The page is 680.7 KB of HTML, a third of the 2 MB limit.
- The summary still needs a successful Gemini run. A rerun will not hit the cache: the failed reply was not stored, and the prompt changes with the response time.
