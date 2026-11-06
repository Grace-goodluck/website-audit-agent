"""The web layer, in-process: FakeHttp, FakeLLM, fake DNS, fake clock, jobs run immediately."""

import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from fakes import FakeHttp, FakeLLM, FakeNow, ImmediateExecutor, fake_resolver, fixture, html_response
from website_audit_agent.ports import FetchError, LLMError
from website_audit_agent.web import app as web_app
from website_audit_agent.web.app import create_app
from website_audit_agent.web.limits import Limiter, Limits
from website_audit_agent.web.safe_http import SafeHttpxClient, UrlGuard

URL = "https://example.com/"
BAKERY = "http://bakery.test/"
CHECKS = [
    "http_status", "https", "response_time", "page_size", "title", "meta_description",
    "viewport", "h1", "image_alt", "open_graph", "favicon", "broken_links",
]
NOTICE = "Audit only sites you own or have permission to audit."


def good_reply(text="Looks healthy overall."):
    return json.dumps({"summary": text, "fixes": []})


def make_client(http=None, llm="default", limits=Limits(), now=None):
    http = http or FakeHttp({("GET", URL): html_response(URL, fixture("good.html"))})
    llm = FakeLLM([good_reply()] * 20) if llm == "default" else llm
    app = create_app(
        http=http,
        llm=llm,
        model="fake-model",
        guard=UrlGuard(fake_resolver()),
        limiter=Limiter(limits, now=now or FakeNow()),
        executor=ImmediateExecutor(),
    )
    return TestClient(app), http, llm


def submit(client, url=URL, confirm=True, ip="203.0.113.7"):
    data = {"url": url, **({"confirm": "yes"} if confirm else {})}
    return client.post("/audit", data=data, headers={"X-Forwarded-For": f"{ip}, 10.0.0.1"}, follow_redirects=False)


def audit(client, **kwargs):
    response = submit(client, **kwargs)
    assert response.status_code == 303, response.text
    return client.get(response.headers["location"])


# --- form, notice, validation --------------------------------------------------------

def test_form_shows_notice_and_required_checkbox():
    client, _, _ = make_client()
    page = client.get("/")
    assert page.status_code == 200
    assert NOTICE in page.text
    assert 'name="confirm" value="yes" required' in page.text


def test_checkbox_is_mandatory():
    client, http, _ = make_client()
    response = submit(client, confirm=False)
    assert response.status_code == 400
    assert "confirm that you own this site" in response.text
    assert http.calls == []


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1/admin", "http://localhost/", "https://example.com:8080/", "ftp://example.com/", "not a url"],
)
def test_blocked_or_invalid_urls_rejected_before_any_request(url):
    client, http, _ = make_client()
    response = submit(client, url=url)
    assert response.status_code == 400 and "can&#39;t be audited" in response.text
    assert http.calls == []


def test_rejected_urls_do_not_use_up_the_visitor_quota():
    client, _, _ = make_client()
    for _ in range(5):
        assert submit(client, url="http://10.0.0.1/").status_code == 400
    for _ in range(3):
        assert submit(client).status_code == 303


# --- happy path and web link limits --------------------------------------------------

def test_audit_shows_all_checks_and_summary():
    client, _, llm = make_client()
    page = audit(client)
    assert page.status_code == 200
    for name in CHECKS:
        assert f"<td>{name}</td>" in page.text
    assert "Looks healthy overall." in page.text
    assert "12 of 12 checks passed" in page.text
    assert NOTICE in page.text
    assert len(llm.prompts) == 1


def test_web_audit_checks_15_links_at_5s_each():
    http = FakeHttp({("GET", BAKERY): html_response(BAKERY, fixture("broken.html"))})
    client, _, _ = make_client(http=http)
    page = audit(client, url=BAKERY)
    assert "Checked 15 of 35 links (20 beyond the 15-link cap not checked)" in page.text
    gets = [c for c in http.calls if c[0] == "GET"]
    heads = [c for c in http.calls if c[0] == "HEAD"]
    assert gets == [("GET", BAKERY, 20.0)]  # the page itself keeps its 20 s timeout
    assert len(heads) == 1 + 15  # favicon + 15 links
    assert {t for _, _, t in heads} == {5.0}


def test_page_content_is_escaped():
    # Entities in the source give the literal text "<script>alert(1)</script>" as the title (25 chars, so the
    # title check fails and its value is listed on the page) — it must come out escaped, not as a tag.
    evil = "<html><head><title>&lt;script&gt;alert(1)&lt;/script&gt;</title></head><body></body></html>"
    http = FakeHttp({("GET", URL): html_response(URL, evil)})
    client, _, _ = make_client(http=http, llm=FakeLLM([good_reply()]))
    page = audit(client)
    assert "<script>" not in page.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text


def test_private_address_links_are_unknown_blocked_and_never_requested():
    """Real SafeHttpxClient over MockTransport: private links are refused before sending (web decision 12)."""
    page_html = (
        '<html><head><link rel="icon" href="/favicon.svg"></head><body>'
        '<a href="http://10.0.0.1/admin">router</a>'
        '<a href="https://intranet.example/">intranet</a>'
        '<a href="/ok">ok</a>'
        "</body></html>"
    )
    sent = []

    def handler(request):
        sent.append(str(request.url))
        if request.method == "GET" and str(request.url) == URL:
            return httpx.Response(200, text=page_html, headers={"content-type": "text/html; charset=utf-8"})
        return httpx.Response(200)

    guard = UrlGuard(fake_resolver({"intranet.example": ["10.0.0.7"]}))
    app = create_app(
        http=SafeHttpxClient(guard, transport=httpx.MockTransport(handler)),
        llm=FakeLLM([good_reply()]),
        model="fake-model",
        guard=guard,
        limiter=Limiter(now=FakeNow()),
        executor=ImmediateExecutor(),
    )
    page = audit(TestClient(app))

    assert "Checked 3 of 3 links. 0 broken, 2 unknown (blocked)." in page.text
    assert "UNKNOWN, blocked (private address) http://10.0.0.1/admin" in page.text
    assert "UNKNOWN, blocked (private address) https://intranet.example/" in page.text
    assert '<td class="pass">PASS</td>' in page.text.split("<td>broken_links</td>", 1)[1][:200]
    assert sent == [URL, "https://example.com/ok"]  # the private links never reached the network layer


# --- summary unavailable ---------------------------------------------------------------

def test_gemini_failure_still_shows_checks_with_a_generic_reason():
    client, _, _ = make_client(llm=FakeLLM([LLMError("Gemini call failed: 503 UNAVAILABLE internal-detail")]))
    page = audit(client)
    assert "Summary unavailable" in page.text and "the AI service is busy or failed" in page.text
    assert "503" not in page.text and "internal-detail" not in page.text
    for name in CHECKS:
        assert f"<td>{name}</td>" in page.text


def test_no_key_runs_checks_and_says_summary_not_configured():
    client, _, _ = make_client(llm=None)
    page = audit(client)
    assert "the AI summary is not configured on this demo" in page.text
    assert "<td>broken_links</td>" in page.text


def test_fetch_failure_shows_short_result():
    http = FakeHttp({URL: FetchError("timeout", "timed out after 20 s")}, default=None)
    client, _, llm = make_client(http=http)
    page = audit(client)
    assert "Page could not be fetched" in page.text and "timed out after 20 s" in page.text
    assert llm.prompts == []


# --- limits through the web --------------------------------------------------------------

def test_fourth_audit_in_an_hour_is_refused_with_retry_after():
    client, http, _ = make_client()
    for _ in range(3):
        assert submit(client).status_code == 303
    calls_before = len(http.calls)

    refused = submit(client)
    assert refused.status_code == 429
    assert int(refused.headers["retry-after"]) > 0
    assert "3 audits for this hour" in refused.text
    assert len(http.calls) == calls_before  # nothing fetched

    assert submit(client, ip="198.51.100.2").status_code == 303  # another visitor


def test_visitor_is_the_first_forwarded_ip():
    client, _, _ = make_client(limits=Limits(audits_per_visitor_per_hour=1))
    assert submit(client, ip="203.0.113.7").status_code == 303
    response = client.post(
        "/audit", data={"url": URL, "confirm": "yes"},
        headers={"X-Forwarded-For": "203.0.113.7, 192.0.2.99"}, follow_redirects=False,
    )
    assert response.status_code == 429  # same first IP, different later hop


def test_daily_total_cap_refuses_new_visitors():
    client, _, _ = make_client(limits=Limits(audits_per_day=2))
    assert submit(client, ip="192.0.2.1").status_code == 303
    assert submit(client, ip="192.0.2.2").status_code == 303
    refused = submit(client, ip="192.0.2.3")
    assert refused.status_code == 429 and "limit of 2 audits for today" in refused.text


def test_summary_cap_runs_checks_but_skips_gemini():
    llm = FakeLLM([good_reply("First summary.")])
    client, _, _ = make_client(llm=llm, limits=Limits(summaries_per_day=1))
    assert "First summary." in audit(client).text

    page = audit(client)
    assert "daily limit of AI summaries has been reached" in page.text
    assert "<td>open_graph</td>" in page.text
    assert len(llm.prompts) == 1  # the second audit never reached Gemini


# --- results, download, logs, secrets ---------------------------------------------------

def test_unknown_job_is_404():
    client, _, _ = make_client()
    assert client.get("/audit/not-a-real-id").status_code == 404
    assert client.get("/audit/not-a-real-id/report.md").status_code == 404


def test_markdown_download_uses_public_reason():
    client, _, _ = make_client(llm=FakeLLM([LLMError("503 internal-detail")]))
    location = submit(client).headers["location"]
    download = client.get(f"{location}/report.md")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("text/markdown")
    assert 'filename="example.com-' in download.headers["content-disposition"]
    assert "the AI service is busy or failed" in download.text
    assert "internal-detail" not in download.text


def test_logs_have_host_and_result_but_never_path_or_query(caplog):
    secret_url = "https://example.com/private/path?token=abc123"
    http = FakeHttp({("GET", secret_url): html_response(secret_url, fixture("good.html"))})
    client, _, _ = make_client(http=http)
    with caplog.at_level(logging.INFO, logger="website_audit_agent.web"):
        audit(client, url=secret_url)
    text = caplog.text
    assert "host=example.com" in text and "12/12_passed,summary" in text
    assert "private" not in text and "token" not in text and "abc123" not in text


def test_healthz():
    client, _, _ = make_client()
    assert client.get("/healthz").text == "ok"


def test_default_app_reads_key_from_env_and_never_shows_it(monkeypatch, tmp_path):
    secret = "test-secret-key-do-not-show"
    seen = {}

    def fake_make_call(model, api_key):
        seen["key"] = api_key
        return lambda prompt: good_reply()

    monkeypatch.setenv("GEMINI_API_KEY", secret)
    monkeypatch.setenv("AUDIT_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(web_app, "make_gemini_call", fake_make_call)

    client = TestClient(web_app.build_default_app())
    assert seen["key"] == secret
    for path in ("/", "/healthz", "/audit/nope"):
        assert secret not in client.get(path).text
