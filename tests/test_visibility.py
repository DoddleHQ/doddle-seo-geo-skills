"""Answer-level visibility: denominators, gaps, staleness, and the null rules."""

import datetime
import json
import os

from doddle_seo.cli import main
from doddle_seo.visibility import analyze, classify_source, visibility_envelope

ROOT = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(ROOT, "fixtures", "visibility_answers.json")
NOW = datetime.datetime(2026, 10, 24, tzinfo=datetime.timezone.utc)
FUTURE = datetime.datetime(2026, 11, 20, tzinfo=datetime.timezone.utc)


def _payload(**kw):
    with open(FIXTURE, encoding="utf-8") as fh:
        answers = json.load(fh)
    return analyze(answers, now=NOW, **kw)


def test_rates_use_recorded_denominators_only():
    p = _payload()
    # 12 answered; brand_mentioned recorded on 11 (one observation omits it).
    assert p["totals"] == {
        "observations": 14, "answered": 12, "no_answer": 1, "error": 1,
        "collected_to": "2026-10-17T13:00:00Z",
    }
    assert p["mention"] == {"count": 6, "measured": 11, "rate": 0.5455, "percent": 54.5}
    assert p["citation"] == {"count": 3, "measured": 11, "rate": 0.2727, "percent": 27.3}


def test_missing_boolean_is_not_false():
    p = _payload()
    assert p["mention"]["measured"] == p["totals"]["answered"] - 1
    assert any("brand_mentioned not recorded" in w for w in p["warnings"])
    assert any("own_site_cited not recorded" in w for w in p["warnings"])


def test_competitor_gaps_and_source_classes():
    p = _payload()
    assert [g["prompt"] for g in p["competitor_gap"]] == ["crm pricing", "crm reviews"]
    counts = p["cited_sources"]["counts"]
    assert counts == {"owned": 3, "competitor": 1, "forum": 1, "listicle": 1, "editorial": 1}


def test_per_engine_breakdown():
    p = _payload()
    assert p["by_engine"]["chatgpt"]["mention"]["percent"] == 60.0
    assert p["by_engine"]["perplexity"]["citation"]["percent"] == 33.3
    assert p["by_engine"]["gemini"]["answered"] == 3


def test_stamp_goes_stale_after_30_days():
    env = visibility_envelope(FIXTURE, now=FUTURE)
    assert env["ok"] and env["evidence"]["stamp"] == "STALE"
    assert any("re-collect" in n for n in env["evidence"]["notes"])
    env_now = visibility_envelope(FIXTURE, now=NOW)
    assert env_now["evidence"]["stamp"] == "CURRENT"


def test_envelope_shape_and_scores():
    env = visibility_envelope(FIXTURE, now=NOW)
    assert env["ok"] and env["command"] == "visibility"
    assert env["scoring_version"] == "visibility-1"
    assert env["scores"]["composite"] == 54.5
    assert env["scores"]["tier"] == "Weak"
    assert env["scores"]["categories"]["citation"] == 27.3
    ids = [f["id"] for f in env["findings"]]
    assert ids == ["visibility.competitor_gap", "visibility.competitor_gap"]
    assert env["summary"].startswith("AI visibility (Acme CRM): 54.5% mention rate")


def test_engine_zero_mention_finding():
    answers = {"brand": "Acme", "observations": [
        {"prompt": f"p{i}", "engine": "gemini", "brand_mentioned": False, "own_site_cited": False}
        for i in range(3)
    ]}
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(answers, fh)
        path = fh.name
    try:
        env = visibility_envelope(path, now=NOW)
    finally:
        os.unlink(path)
    assert env["ok"]
    assert env["visibility"]["by_engine"]["gemini"]["mention"] == {
        "count": 0, "measured": 3, "rate": 0.0, "percent": 0.0,
    }
    ids = [f["id"] for f in env["findings"]]
    assert "visibility.engine_zero_mention" in ids
    assert "visibility.small_sample" in ids


def test_small_sample_warning_and_finding():
    answers = {"brand": "Acme", "observations": [
        {"prompt": f"p{i}", "engine": "chatgpt", "brand_mentioned": False}
        for i in range(4)
    ]}
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(answers, fh)
        path = fh.name
    try:
        env = visibility_envelope(path, now=NOW)
    finally:
        os.unlink(path)
    assert env["ok"]
    assert any("small sample" in w for w in env["visibility"]["warnings"])
    ids = [f["id"] for f in env["findings"]]
    # The 4 answers all record brand_mentioned: false, so the engine-zero finding
    # fires alongside the small-sample warning.
    assert ids == ["visibility.engine_zero_mention", "visibility.small_sample"]


def test_invalid_status_is_rejected():
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump({"observations": [{"prompt": "p", "status": "maybe"}]}, fh)
        path = fh.name
    try:
        env = visibility_envelope(path, now=NOW)
    finally:
        os.unlink(path)
    assert env["ok"] is False
    assert "invalid" in env["error"]["message"]


def test_missing_file_error_envelope():
    env = visibility_envelope("/nonexistent/answers.json")
    assert env["ok"] is False
    assert env["error"]["hint"].startswith("point dseo visibility")


def test_classify_source_rules():
    assert classify_source("https://acme.example/p", "acme.example", []) == "owned"
    assert classify_source("https://www.acme.example/p", "acme.example", []) == "owned"
    assert classify_source("https://rival.example/p", "acme.example", ["rival.example"]) == "competitor"
    assert classify_source("https://www.reddit.com/r/x", None, []) == "forum"
    assert classify_source("https://site.example/best-crm-tools", None, []) == "listicle"
    assert classify_source("https://site.example/docs", None, []) == "editorial"


def test_cli_visibility_json(capsys):
    rc = main(["visibility", FIXTURE, "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert data["ok"] and data["command"] == "visibility"
    assert data["visibility"]["mention"]["percent"] == 54.5
