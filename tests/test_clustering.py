"""SERP-overlap clustering and GSC cannibalisation from recorded evidence."""

import json
import os

from doddle_seo.cli import main
from doddle_seo.clustering import (
    DEFAULT_THRESHOLD,
    cannibalize,
    cannibalize_envelope,
    cluster_envelope,
    cluster_keywords,
    load_gsc_rows,
)

ROOT = os.path.dirname(os.path.abspath(__file__))
SERP = os.path.join(ROOT, "fixtures", "serp_keywords.json")
GSC = os.path.join(ROOT, "fixtures", "gsc_rows.json")


def _rows():
    with open(SERP, encoding="utf-8") as fh:
        return json.load(fh)["keywords"]


# ------------------------------------------------------------------------ cluster

def test_containment_joins_serp_overlap():
    p = cluster_keywords(_rows())
    multi = [c for c in p["clusters"] if c["size"] >= 2]
    assert p["cluster_count"] == 2
    c1 = next(c for c in multi if c["id"] == "C1")
    assert {m["keyword"] for m in c1["members"]} == {
        "crm software", "best crm software", "crm software for small business",
    }
    assert c1["overlap"]["min"] == 0.6667 and c1["overlap"]["max"] == 0.75
    c2 = next(c for c in multi if c["id"] == "C2")
    assert {m["keyword"] for m in c2["members"]} == {"crm pricing", "crm cost"}


def test_threshold_gates_membership():
    strict = cluster_keywords(_rows(), threshold=0.9)
    assert strict["cluster_count"] == 0
    assert strict["singleton_count"] == 7


def test_keywords_without_results_are_excluded_not_guessed():
    p = cluster_keywords(_rows())
    assert p["keywords_excluded"] == ["what is crm"]
    assert p["keywords_measured"] == 7
    assert p["coverage_percent"] == 71.4
    env = cluster_envelope(SERP)
    assert env["ok"]
    assert env["completeness"]["missing"] == ["no recorded SERP results for what is crm"]


def test_mixed_intent_cluster_flagged():
    p = cluster_keywords(_rows())
    c1 = next(c for c in p["clusters"] if c["id"] == "C1")
    assert c1["mixed_intent"] and c1["intents"] == ["commercial", "informational"]
    env = cluster_envelope(SERP)
    assert [f["id"] for f in env["findings"]][0] == "cluster.mixed_intent"


def test_cluster_is_deterministic():
    assert cluster_keywords(_rows()) == cluster_keywords(_rows())


def test_cluster_rejects_bad_threshold():
    try:
        cluster_keywords(_rows(), threshold=0.0)
    except ValueError as exc:
        assert "threshold" in str(exc)
    else:
        raise AssertionError("threshold 0 must be rejected")


def test_cli_cluster_json(capsys):
    rc = main(["cluster", SERP, "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out)["cluster"]["cluster_count"] == 2


# --------------------------------------------------------------------- cannibalize

def test_cannibalize_totals_and_contested():
    p = cannibalize(load_gsc_rows(GSC))
    assert p["totals"] == {
        "queries": 4, "cannibalizing": 3, "clean": 1,
        "affected_percent": 75.0, "impressions_at_risk": 1770.0,
    }
    by_query = {s["query"]: s for s in p["splits"]}
    assert by_query["crm software"]["top_share_percent"] == 61.5
    assert by_query["crm software"]["contested"] is False
    assert by_query["best crm"]["top_share_percent"] == 42.6
    assert by_query["best crm"]["contested"] is True
    assert "crm pricing" not in by_query  # single page: not a split


def test_missing_impressions_are_null_not_zero():
    p = cannibalize(load_gsc_rows(GSC))
    reviews = next(s for s in p["splits"] if s["query"] == "crm reviews")
    assert reviews["total_impressions"] is None
    assert reviews["top_share_percent"] is None
    assert reviews["contested"] is False
    # 1300 + 470 only: the unsized split is excluded, never counted as 0.
    assert p["totals"]["impressions_at_risk"] == 1770.0
    assert any("excluded from impressions at risk" in w for w in p["warnings"])


def test_cannibalize_envelope_findings_ranked_by_impressions():
    env = cannibalize_envelope(GSC)
    assert env["ok"] and env["scoring_version"] == "cannibal-1"
    titles = [f["title"] for f in env["findings"]]
    assert titles[0] == "Query 'crm software' splits across 2 pages"
    assert titles[1] == "Query 'best crm' splits across 3 pages"
    severities = [f["severity"] for f in env["findings"]]
    assert severities == ["medium", "high", "medium"]  # contested query is high
    assert env["summary"].startswith("3 of 4 queries split across pages (75.0% affected)")


def test_csv_export_roundtrip(tmp_path):
    csv_path = tmp_path / "gsc.csv"
    csv_path.write_text(
        "query,page,clicks,impressions\n"
        "crm tool,https://a.example/one,3,300\n"
        "crm tool,https://a.example/two,1,100\n"
        "other,https://a.example/three,9,900\n",
        encoding="utf-8",
    )
    rows = load_gsc_rows(str(csv_path))
    p = cannibalize(rows)
    assert p["totals"]["queries"] == 2
    assert p["totals"]["cannibalizing"] == 1
    assert p["totals"]["impressions_at_risk"] == 400.0
    env = cannibalize_envelope(str(csv_path))
    assert env["ok"]


def test_missing_page_row_is_an_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"query": "q"}]), encoding="utf-8")
    env = cannibalize_envelope(str(bad))
    assert env["ok"] is False
    assert "'page'" in env["error"]["message"]


def test_cli_cannibalize_json(capsys):
    rc = main(["cannibalize", GSC, "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out)["cannibalize"]["totals"]["affected_percent"] == 75.0


def test_default_threshold_exported():
    assert DEFAULT_THRESHOLD == 0.4
