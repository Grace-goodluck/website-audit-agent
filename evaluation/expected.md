# Expected findings — written by hand before running

## Fixture: tests/fixtures/broken.html

Scenario (as faked in tests/test_audit.py): served at `http://bakery.test/` with HTTP 200 in
0.4 s; `/menu-3` returns 404, `/menu-4` returns 403, `/favicon.ico` returns 404, every
other link returns 200.

| Check | Expected | Why |
|---|---|---|
| http_status | PASS | 200 |
| https | FAIL | served over http |
| response_time | PASS | 0.4 s ≤ 3 s |
| page_size | PASS | a few KB |
| title | FAIL | 75 characters, aim 30–60 |
| meta_description | FAIL | missing |
| viewport | FAIL | missing |
| h1 | FAIL | two `<h1>` |
| image_alt | FAIL | 2 of 3 images (`/cake.jpg`, `/bread.jpg`) have no alt |
| open_graph | FAIL | missing og:description, og:image (og:url optional, also missing) |
| favicon | FAIL | no `<link rel="icon">`; `/favicon.ico` 404 |
| broken_links | FAIL | 35 unique links (duplicates, `#prices`, mailto, tel, javascript, `#top` skipped); first 30 checked, 5 not checked; 1 broken (`/menu-3`, 404); 1 unknown, blocked (`/menu-4`, 403) |

Requests made: 1 page GET, 1 favicon HEAD, 30 link HEADs = 32.

## Live: techbygrace.com

_To be written by Grace before the first live run._

## Live: artisan-service-app.vercel.app

_To be written by Grace before the first live run._
