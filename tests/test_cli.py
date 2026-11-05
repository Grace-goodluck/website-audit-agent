"""Exit codes and file output, with FakeHttp and a fake Gemini call patched in."""

import json

import pytest

from fakes import FakeHttp, fixture, html_response
from website_audit_agent import cli
from website_audit_agent.ports import FetchError

URL = "https://example.com/"


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # reports/ and results/cache/ land here
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("AUDIT_AGENT_MODEL", raising=False)
    return tmp_path


def _patch_http(monkeypatch, http):
    monkeypatch.setattr(cli, "HttpxClient", lambda: http)


def _patch_gemini(monkeypatch, reply):
    prompts = []

    def make_call(model, api_key):
        def call(prompt):
            prompts.append(prompt)
            return reply
        return call

    monkeypatch.setattr(cli, "make_gemini_call", make_call)
    return prompts


def _good_site():
    return FakeHttp({("GET", URL): html_response(URL, fixture("good.html"))})


def test_exit_0_with_summary(workdir, monkeypatch, capsys):
    _patch_http(monkeypatch, _good_site())
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    prompts = _patch_gemini(monkeypatch, json.dumps({"summary": "All good.", "fixes": []}))

    assert cli.main([URL]) == 0
    (report,) = (workdir / "reports").glob("example.com-*.md")
    assert "All good." in report.read_text(encoding="utf-8")
    assert len(prompts) == 1
    assert list((workdir / "results" / "cache").glob("*.json"))  # reply cached
    assert "Report written:" in capsys.readouterr().out


def test_exit_1_without_key_but_report_written(workdir, monkeypatch, capsys):
    _patch_http(monkeypatch, _good_site())
    assert cli.main([URL]) == 1
    (report,) = (workdir / "reports").glob("*.md")
    assert "Summary unavailable" in report.read_text(encoding="utf-8")
    assert "GEMINI_API_KEY is not set" in capsys.readouterr().err


def test_exit_1_when_page_cannot_be_fetched(workdir, monkeypatch):
    _patch_http(monkeypatch, FakeHttp({URL: FetchError("timeout", "timed out after 20 s")}, default=None))
    assert cli.main([URL]) == 1
    (report,) = (workdir / "reports").glob("*.md")
    assert "Page could not be fetched" in report.read_text(encoding="utf-8")


def test_exit_2_for_non_http_url(workdir):
    with pytest.raises(SystemExit) as info:
        cli.main(["ftp://example.com/"])
    assert info.value.code == 2
