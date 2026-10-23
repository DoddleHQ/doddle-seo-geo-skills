"""SERP-overlap keyword clustering and GSC cannibalisation, from recorded evidence.

Both commands read a recorded file and compute; they never fetch and never guess.

``dseo cluster <serp.json>`` — Method ``cluster-1``
---------------------------------------------------
Input (JSON)::

    {
      "keywords": [
        {"keyword": "crm software",
         "results": ["https://a.example/p1", "b.example"],   # URLs or domains
         "intent": "commercial",                              # optional, from live SERP
         "volume": 900}                                       # optional, recorded metric
      ]
    }

A bare list is treated as the keywords list. Overlap between two keywords is the
**containment** of their ranking-domain sets: ``|A ∩ B| / min(|A|, |B|)`` after
``www.``-stripping. Pairs at or above ``--threshold`` (default 0.4) are joined with
union-find, so a cluster is one connected component of SERP overlap. Keywords with
no recorded results are *not measured*: excluded, with a reason in
``completeness.missing`` — never clustered by keyword string.

``dseo cannibalize <gsc-export>`` — Method ``cannibal-1``
--------------------------------------------------------
Input: a GSC-style export, either JSON (``{"rows": [...]}`` or a bare list) or CSV
with a header. Per row: ``query`` and ``page`` required; ``clicks``, ``impressions``,
``position`` optional. A column that is absent stays ``null`` (not measured), never 0.

A query *cannibalises* when it appears on two or more distinct pages. Per split:
page rows sorted by impressions, ``top_share_percent`` = top page's share of the
query's recorded impressions, and ``contested: true`` when that share is below 60
(a documented heuristic, method ``cannibal-1``). ``affected_percent`` and
``impressions_at_risk`` are computed over all recorded queries; a split whose
impressions are not recorded is excluded from the risk sum, with a warning.
"""

from __future__ import annotations

import csv
import json
from typing import Any, Dict, List, Optional, Tuple

from . import DATA_VERSION, TOOLKIT_VERSION
from .envelope import (
    CURRENT,
    DETERMINISTIC,
    HEURISTIC,
    Finding,
    Signal,
    error_envelope,
    make_envelope,
)

CLUSTER_SCORING = "cluster-1"
CANNIBAL_SCORING = "cannibal-1"
DEFAULT_THRESHOLD = 0.4
CONTESTED_BELOW = 60.0  # top page under 60% of the query's impressions = contested
MAX_SINGLETON_FINDINGS = 10


# --------------------------------------------------------------------------- cluster

def load_keywords(path: str) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        data = data.get("keywords")
    if not isinstance(data, list):
        raise ValueError("file must be a JSON list of keywords or an object with a 'keywords' list")
    return data


def _domains(results: Any) -> List[str]:
    out: List[str] = []
    if not isinstance(results, list):
        return out
    for r in results:
        if not isinstance(r, str) or not r.strip():
            continue
        text = r.strip().lower()
        if "://" in text:
            from urllib.parse import urlparse
            text = urlparse(text).netloc
        text = text.split("/")[0].split(":")[0]
        if text.startswith("www."):
            text = text[4:]
        if text and text not in out:
            out.append(text)
    return out


def cluster_keywords(keywords: List[Dict[str, Any]], threshold: float = DEFAULT_THRESHOLD) -> Dict[str, Any]:
    if not 0 < threshold <= 1:
        raise ValueError("threshold must be greater than 0 and at most 1")
    for row in keywords:
        if not str(row.get("keyword", "")).strip():
            raise ValueError("every keyword row needs a non-empty 'keyword'")

    usable = [(row, set(_domains(row.get("results")))) for row in keywords]
    usable = [(row, doms) for row, doms in usable if doms]
    excluded = [str(row.get("keyword")) for row, doms in [
        (row, set(_domains(row.get("results")))) for row in keywords
    ] if not doms]

    n = len(usable)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    pair_overlap: Dict[Tuple[int, int], float] = {}
    for i in range(n):
        for j in range(i + 1, n):
            a, b = usable[i][1], usable[j][1]
            shared = len(a & b)
            if not shared:
                continue
            ov = shared / float(min(len(a), len(b)))
            pair_overlap[(i, j)] = round(ov, 4)
            if ov >= threshold:
                parent[find(i)] = find(j)

    groups: Dict[int, List[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    clusters: List[Dict[str, Any]] = []
    for idxs in groups.values():
        idxs = sorted(idxs, key=lambda i: str(usable[i][0].get("keyword", "")).lower())
        members = []
        for i in idxs:
            row = usable[i][0]
            member: Dict[str, Any] = {"keyword": str(row.get("keyword"))}
            if isinstance(row.get("volume"), (int, float)):
                member["volume"] = row["volume"]
            if row.get("intent"):
                member["intent"] = str(row["intent"])
            members.append(member)

        overlaps = [
            pair_overlap[(min(i, j), max(i, j))]
            for pos, i in enumerate(idxs)
            for j in idxs[pos + 1:]
            if (min(i, j), max(i, j)) in pair_overlap
        ]
        intents = sorted({m["intent"] for m in members if m.get("intent")})
        volumes = [m["volume"] for m in members if isinstance(m.get("volume"), (int, float))]
        clusters.append({
            "id": "",
            "size": len(members),
            "members": members,
            "domains": sorted(set().union(*(usable[i][1] for i in idxs))),
            "overlap": (
                {"min": min(overlaps), "max": max(overlaps),
                 "avg": round(sum(overlaps) / len(overlaps), 4)}
                if overlaps else {"min": None, "max": None, "avg": None}
            ),
            "intents": intents,
            "mixed_intent": len(intents) > 1,
            "volume_total": sum(volumes) if volumes else None,
        })

    clusters.sort(key=lambda c: (-c["size"], c["members"][0]["keyword"].lower()))
    multi = [c for c in clusters if c["size"] >= 2]
    for i, c in enumerate(multi, start=1):
        c["id"] = f"C{i}"
    for c in clusters:
        if not c["id"]:
            c["id"] = f"S{len([x for x in clusters if x['id'].startswith('S')]) + 1}"

    measured = len(usable)
    clustered_kw = sum(c["size"] for c in multi)
    mixed = [c for c in multi if c["mixed_intent"]]
    return {
        "method": CLUSTER_SCORING,
        "threshold": threshold,
        "match": "ranking domains (www-stripped), containment overlap",
        "keywords_total": len(keywords),
        "keywords_measured": measured,
        "keywords_excluded": excluded,
        "cluster_count": len(multi),
        "singleton_count": len(clusters) - len(multi),
        "clustered_keywords": clustered_kw,
        "coverage_percent": None if measured == 0 else round(clustered_kw * 100.0 / measured, 1),
        "mixed_intent_clusters": [c["id"] for c in mixed],
        "clusters": [c for c in multi] + [c for c in clusters if c["size"] == 1],
    }


def cluster_envelope(path: str, threshold: float = DEFAULT_THRESHOLD) -> Dict[str, Any]:
    try:
        rows = load_keywords(path)
    except FileNotFoundError:
        return error_envelope("cluster", path, f"SERP file not found: {path}",
                              "record SERP results per keyword as JSON — see the seo-keyword-clustering skill")
    except json.JSONDecodeError as exc:
        return error_envelope("cluster", path, f"SERP file is not valid JSON: {exc}",
                              "record SERP results as JSON — see the seo-keyword-clustering skill")
    except ValueError as exc:
        return error_envelope("cluster", path, str(exc), "fix the file structure and re-run")

    try:
        payload = cluster_keywords(rows, threshold=threshold)
    except ValueError as exc:
        return error_envelope("cluster", path, str(exc), "fix the keyword rows and re-run")
    if payload["keywords_measured"] == 0:
        return error_envelope("cluster", path, "no keywords with recorded SERP results",
                              "record ranking results per keyword first (live SERP data or a saved export)")

    signals = [
        Signal("cluster.multi", float(payload["cluster_count"]), float(len(payload["clusters"])),
               DETERMINISTIC, {"singleton_count": payload["singleton_count"]}),
        Signal("cluster.coverage", payload["coverage_percent"], 100.0, DETERMINISTIC,
               {"clustered_keywords": payload["clustered_keywords"],
                "measured": payload["keywords_measured"]}),
        Signal("cluster.mixed_intent", float(len(payload["mixed_intent_clusters"])),
               float(payload["cluster_count"]), DETERMINISTIC,
               {"clusters": payload["mixed_intent_clusters"]}),
    ]

    findings: List[Finding] = []
    for cid in payload["mixed_intent_clusters"]:
        c = next(x for x in payload["clusters"] if x["id"] == cid)
        findings.append(Finding(
            id="cluster.mixed_intent", priority=len(findings) + 1, severity="medium",
            effort="medium", points_lost=0.0,
            title=f"Cluster {cid} has mixed intent ({', '.join(c['intents'])})",
            detail="One page cannot satisfy both intents — split the cluster before briefing.",
        ))
    singletons = sorted(
        (c for c in payload["clusters"] if c["size"] == 1),
        key=lambda c: (-(c["volume_total"] or 0), c["members"][0]["keyword"].lower()),
    )
    for c in singletons[:MAX_SINGLETON_FINDINGS]:
        vol = c["volume_total"]
        findings.append(Finding(
            id="cluster.singleton", priority=len(findings) + 1, severity="low",
            effort="medium", points_lost=0.0,
            title=f"{c['members'][0]['keyword']!r} shares no SERP overlap (singleton)",
            detail=(f"Recorded volume {vol}. Treat as its own page; no clustering evidence." if vol is not None
                    else "No overlap with any other keyword — treat as its own page."),
        ))
    if len(singletons) > MAX_SINGLETON_FINDINGS:
        findings.append(Finding(
            id="cluster.singleton_overflow", priority=len(findings) + 1, severity="low",
            effort="low", points_lost=0.0,
            title=f"{len(singletons) - MAX_SINGLETON_FINDINGS} more singleton keyword(s) not listed",
            detail="All singletons are in payload.clusters; only the top ones appear as findings.",
        ))

    missing = [
        f"no recorded SERP results for {k}" for k in payload["keywords_excluded"]
    ]
    env = make_envelope(
        "cluster", path,
        toolkit_version=TOOLKIT_VERSION,
        scoring_version=CLUSTER_SCORING,
        data_version=DATA_VERSION,
        evidence_stamp=CURRENT,
        pages_ok=payload["keywords_measured"],
        missing=missing,
        signal_count=sum(1 for s in signals if s.value is not None),
        signal_total=len(signals),
        signals=signals,
        findings=findings,
        scores=None,
    )
    env["cluster"] = payload
    env["summary"] = (
        f"{payload['cluster_count']} cluster(s) from {payload['keywords_measured']} keyword(s) "
        f"at threshold {threshold} ({payload['coverage_percent']}% clustered)"
        + (f"; {len(payload['mixed_intent_clusters'])} mixed-intent" if payload["mixed_intent_clusters"] else "")
    )
    return env


# ----------------------------------------------------------------------- cannibalize

def load_gsc_rows(path: str) -> List[Dict[str, Any]]:
    if path.lower().endswith(".csv"):
        with open(path, encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            return [dict(r) for r in reader]
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Fall back to CSV for exports saved without a .csv suffix.
        import io
        return [dict(r) for r in csv.DictReader(io.StringIO(text))]
    if isinstance(data, dict):
        data = data.get("rows")
    if not isinstance(data, list):
        raise ValueError("file must be a GSC export: JSON rows, or CSV with a header")
    return data


def _num(value: Any) -> Optional[float]:
    """Parse a recorded number; absent/garbage stays None (not measured), never 0."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


def cannibalize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_query: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        query = str(row.get("query") or "").strip()
        page = str(row.get("page") or "").strip()
        if not query or not page:
            raise ValueError("every row needs a non-empty 'query' and 'page'")
        by_query.setdefault(query, []).append({
            "page": page,
            "clicks": _num(row.get("clicks")),
            "impressions": _num(row.get("impressions")),
            "position": _num(row.get("position")),
        })

    splits: List[Dict[str, Any]] = []
    clean = 0
    for query, pages_raw in by_query.items():
        seen: Dict[str, Dict[str, Any]] = {}
        for p in pages_raw:
            seen.setdefault(p["page"], p)
        pages = sorted(
            seen.values(),
            key=lambda p: (p["impressions"] if p["impressions"] is not None else -1.0),
            reverse=True,
        )
        if len(pages) < 2:
            clean += 1
            continue
        has_imp = [p for p in pages if p["impressions"] is not None]
        total_impressions: Optional[float] = None
        total_clicks: Optional[float] = None
        top_share: Optional[float] = None
        if len(has_imp) == len(pages):
            total_impressions = sum(p["impressions"] for p in pages)  # type: ignore[misc]
            if total_impressions > 0:
                top_share = round(pages[0]["impressions"] * 100.0 / total_impressions, 1)  # type: ignore[operator]
        if all(p["clicks"] is not None for p in pages):
            total_clicks = sum(p["clicks"] for p in pages)  # type: ignore[misc]
        splits.append({
            "query": query,
            "url_count": len(pages),
            "pages": pages,
            "total_clicks": total_clicks,
            "total_impressions": total_impressions,
            "top_page": pages[0]["page"],
            "top_share_percent": top_share,
            "contested": top_share is not None and top_share < CONTESTED_BELOW,
        })

    splits.sort(key=lambda s: (s["total_impressions"] is not None, s["total_impressions"] or 0.0),
                reverse=True)
    warnings: List[str] = []
    sized = [s for s in splits if s["total_impressions"] is not None]
    unsized = [s for s in splits if s["total_impressions"] is None]
    risk = sum(s["total_impressions"] for s in sized) if sized else None
    if unsized:
        warnings.append(
            f"impressions not recorded for {len(unsized)} split query(s) — excluded from impressions at risk"
        )
    affected = len(splits)
    total_queries = len(by_query)
    return {
        "method": CANNIBAL_SCORING,
        "contested_rule": f"top page below {CONTESTED_BELOW}% of recorded impressions",
        "totals": {
            "queries": total_queries,
            "cannibalizing": affected,
            "clean": clean,
            "affected_percent": None if total_queries == 0 else round(affected * 100.0 / total_queries, 1),
            "impressions_at_risk": risk,
        },
        "splits": splits,
        "warnings": warnings,
    }


def cannibalize_envelope(path: str) -> Dict[str, Any]:
    try:
        rows = load_gsc_rows(path)
    except FileNotFoundError:
        return error_envelope("cannibalize", path, f"GSC export not found: {path}",
                              "point at a GSC export (CSV or JSON rows) — see the seo-keyword-clustering skill")
    except (ValueError, csv.Error) as exc:
        return error_envelope("cannibalize", path, str(exc),
                              "expected a GSC export: CSV with a header, or JSON rows")
    if not rows:
        return error_envelope("cannibalize", path, "the export contains no rows",
                              "export queries with page, clicks and impressions first")

    try:
        payload = cannibalize(rows)
    except ValueError as exc:
        return error_envelope("cannibalize", path, str(exc),
                              "every row needs 'query' and 'page' — check the header/keys")

    totals = payload["totals"]
    all_impressions = sum(
        s["total_impressions"] for s in payload["splits"] if s["total_impressions"] is not None
    )
    signals = [
        Signal("cannibal.queries", float(totals["cannibalizing"]), float(totals["queries"]),
               DETERMINISTIC, {"affected_percent": totals["affected_percent"],
                               "clean": totals["clean"]}),
        Signal("cannibal.impressions_at_risk", totals["impressions_at_risk"], float(all_impressions),
               DETERMINISTIC if all_impressions else HEURISTIC,
               {"recorded": totals["impressions_at_risk"] is not None}),
    ]

    findings: List[Finding] = []
    for s in payload["splits"]:
        contested = s["contested"]
        findings.append(Finding(
            id="cannibal.split", priority=len(findings) + 1,
            severity="high" if contested else "medium",
            effort="medium", points_lost=0.0,
            title=f"Query {s['query']!r} splits across {s['url_count']} pages",
            detail=(
                f"Top page {s['top_page']} holds {s['top_share_percent']}% of recorded impressions "
                f"(contested: {contested}). Pages: " + ", ".join(p["page"] for p in s["pages"])
                if s["top_share_percent"] is not None
                else "Impressions not recorded for this split — size it from the export first. Pages: "
                     + ", ".join(p["page"] for p in s["pages"])
            ),
        ))

    summary = (
        f"{totals['cannibalizing']} of {totals['queries']} queries split across pages "
        f"({totals['affected_percent']}% affected)"
        + (f"; {totals['impressions_at_risk']:.0f} impressions at risk"
           if totals["impressions_at_risk"] is not None else "; impressions at risk not measured")
    )
    env = make_envelope(
        "cannibalize", path,
        toolkit_version=TOOLKIT_VERSION,
        scoring_version=CANNIBAL_SCORING,
        data_version=DATA_VERSION,
        evidence_stamp=CURRENT,
        pages_ok=totals["queries"],
        notes=payload["warnings"],
        signal_count=sum(1 for s in signals if s.value is not None),
        signal_total=len(signals),
        signals=signals,
        findings=findings,
        scores=None,
    )
    env["cannibalize"] = payload
    env["summary"] = summary
    return env
