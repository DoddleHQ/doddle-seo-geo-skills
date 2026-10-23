"""Answer-level AI visibility from a recorded prompt/answer set.

The recorded answers file is evidence. This module computes rates from it and never
infers anything that is not in it: a missing ``brand_mentioned`` is *not recorded*,
not ``False``, and is excluded from the denominator.

Input shape (JSON)::

    {
      "brand": "Acme CRM",                  # optional, overridable via CLI
      "site": "acme-crm.example",           # optional, for citation classification
      "competitors": ["rivalcrm.example"],  # optional, for citation classification
      "observations": [
        {
          "prompt": "best crm for small business",   # required
          "engine": "chatgpt",                       # default "unspecified"
          "topic": "crm-software",                   # optional grouping
          "collected_at": "2026-10-15T10:00:00Z",    # optional ISO-8601
          "status": "answered",                      # answered | no_answer | error
          "brand_mentioned": true,                   # bool or absent (not recorded)
          "own_site_cited": true,                    # bool or absent (not recorded)
          "competitors_mentioned": ["rivalcrm.example"],
          "citations": ["https://acme-crm.example/blog"]
        }
      ]
    }

A bare list is treated as the observations list.

Method ``visibility-1``
-----------------------
- ``mention_rate``  = answers with ``brand_mentioned: true`` / answers where it was recorded.
- ``citation_rate`` = answers with ``own_site_cited: true`` / answers where it was recorded.
- Rates cover answered observations only; ``no_answer`` and ``error`` never enter a denominator.
- ``evidence.stamp`` is ``STALE`` when the newest ``collected_at`` is older than 30 days.
- Citation sources are classified ``owned`` / ``competitor`` / ``forum`` / ``listicle`` /
  ``editorial`` by URL — a documented heuristic, reported as ``heuristic`` in the skill.
"""

from __future__ import annotations

import datetime
import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from . import DATA_VERSION, TOOLKIT_VERSION
from .envelope import (
    CURRENT,
    DETERMINISTIC,
    STALE,
    Finding,
    Signal,
    error_envelope,
    make_envelope,
    tier_for,
)

VISIBILITY_SCORING = "visibility-1"
MAX_AGE_DAYS = 30
SMALL_SAMPLE = 10
VALID_STATUSES = ("answered", "no_answer", "error")

# Source classification is heuristic data, not magic: host registry + URL patterns.
FORUM_DOMAINS = frozenset({
    "reddit.com", "quora.com", "stackoverflow.com", "stackexchange.com",
    "news.ycombinator.com", "answers.yahoo.com", "discourse.org",
})
LISTICLE_RE = re.compile(
    r"(^|/)(best|top\d*|vs|alternative|alternatives|compare)([-/]|$)", re.IGNORECASE
)


def _norm_host(value: str) -> str:
    value = (value or "").strip().lower()
    if "://" in value:
        value = urlparse(value).netloc
    value = value.split("/")[0].split(":")[0]
    if value.startswith("www."):
        value = value[4:]
    return value


def _host_matches(host: str, domain: str) -> bool:
    domain = _norm_host(domain)
    return bool(domain) and (host == domain or host.endswith("." + domain))


def classify_source(url: str, site: Optional[str], competitors: List[str]) -> str:
    """Classify one citation URL. Heuristic: exact rules, documented order."""
    host = _norm_host(url)
    if site and _host_matches(host, site):
        return "owned"
    if any(_host_matches(host, c) for c in competitors):
        return "competitor"
    if host in FORUM_DOMAINS:
        return "forum"
    path = urlparse(url if "://" in url else "https://" + url).path
    if LISTICLE_RE.search(path):
        return "listicle"
    return "editorial"


def _is_bool(value: Any) -> bool:
    return isinstance(value, bool)


def _rate(count: int, measured: int) -> Dict[str, Any]:
    return {
        "count": count,
        "measured": measured,
        "rate": None if measured == 0 else round(count / measured, 4),
        "percent": None if measured == 0 else round(count * 100.0 / measured, 1),
    }


def _parse_ts(value: Any) -> Optional[datetime.datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def load_answers(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, list):
        data = {"observations": data}
    if not isinstance(data, dict) or not isinstance(data.get("observations"), list):
        raise ValueError(
            "file must be a JSON list of observations or an object with an 'observations' list"
        )
    return data


def analyze(
    answers: Dict[str, Any],
    brand: Optional[str] = None,
    site: Optional[str] = None,
    competitors: Optional[List[str]] = None,
    now: Optional[datetime.datetime] = None,
) -> Dict[str, Any]:
    """Compute the visibility payload from a loaded answers file."""
    brand = brand or answers.get("brand") or None
    site = _norm_host(site or answers.get("site") or "") or None
    if competitors is None:
        competitors = answers.get("competitors") or []
    competitors = [_norm_host(c) for c in competitors if c]
    obs = [o for o in answers["observations"] if isinstance(o, dict)]

    if not obs:
        raise ValueError("no observations recorded in the answers file")
    for o in obs:
        if not str(o.get("prompt", "")).strip():
            raise ValueError("every observation needs a non-empty 'prompt'")
        status = o.get("status") or "answered"
        if status not in VALID_STATUSES:
            raise ValueError(
                f"observation status {status!r} is invalid — use one of {', '.join(VALID_STATUSES)}"
            )

    now = now or datetime.datetime.now(datetime.timezone.utc)
    statuses = [o.get("status") or "answered" for o in obs]
    answered = [o for o, s in zip(obs, statuses) if s == "answered"]
    no_answer = statuses.count("no_answer")
    error_count = statuses.count("error")

    mention_rows = [o for o in answered if _is_bool(o.get("brand_mentioned"))]
    citation_rows = [o for o in answered if _is_bool(o.get("own_site_cited"))]
    mention = _rate(sum(1 for o in mention_rows if o["brand_mentioned"]), len(mention_rows))
    citation = _rate(sum(1 for o in citation_rows if o["own_site_cited"]), len(citation_rows))

    def _breakdown(rows: List[Dict[str, Any]], key: str) -> Dict[str, Dict[str, Any]]:
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for o in rows:
            groups.setdefault(str(o.get(key) or "unspecified"), []).append(o)
        out: Dict[str, Dict[str, Any]] = {}
        for name in sorted(groups):
            rows_g = groups[name]
            m = [o for o in rows_g if _is_bool(o.get("brand_mentioned"))]
            c = [o for o in rows_g if _is_bool(o.get("own_site_cited"))]
            out[name] = {
                "answered": len(rows_g),
                "mention": _rate(sum(1 for o in m if o["brand_mentioned"]), len(m)),
                "citation": _rate(sum(1 for o in c if o["own_site_cited"]), len(c)),
            }
        return out

    by_engine = _breakdown(answered, "engine")
    by_topic = _breakdown(answered, "topic") if any(o.get("topic") for o in answered) else {}

    gap = [
        {
            "prompt": o.get("prompt"),
            "engine": str(o.get("engine") or "unspecified"),
            "competitors_mentioned": list(o.get("competitors_mentioned") or []),
        }
        for o in answered
        if o.get("brand_mentioned") is False and o.get("competitors_mentioned")
    ]

    source_counts = {"owned": 0, "competitor": 0, "forum": 0, "listicle": 0, "editorial": 0}
    source_examples: Dict[str, List[str]] = {k: [] for k in source_counts}
    for o in answered:
        for url in o.get("citations") or []:
            if not isinstance(url, str) or not url.strip():
                continue
            cls = classify_source(url, site, competitors)
            source_counts[cls] += 1
            if len(source_examples[cls]) < 5:
                source_examples[cls].append(url)

    warnings: List[str] = []
    missing_mention = len(answered) - len(mention_rows)
    missing_citation = len(answered) - len(citation_rows)
    if not answered:
        warnings.append("no answered observations — mention and citation rates are not measured")
    if missing_mention:
        warnings.append(
            f"brand_mentioned not recorded on {missing_mention} answer(s) — excluded from the denominator"
        )
    if missing_citation:
        warnings.append(
            f"own_site_cited not recorded on {missing_citation} answer(s) — excluded from the denominator"
        )
    if answered and len(mention_rows) < SMALL_SAMPLE:
        warnings.append(
            f"small sample: {len(mention_rows)} answer(s) with recorded mention data (<{SMALL_SAMPLE}) — "
            "treat rates as directional, not as market share"
        )
    if not competitors:
        warnings.append("competitors not declared — citations are not classified as competitor sources")

    stamps = [d for d in (_parse_ts(o.get("collected_at")) for o in answered) if d]
    stamp = CURRENT
    newest: Optional[datetime.datetime] = max(stamps) if stamps else None
    if newest is None:
        warnings.append("no collected_at dates recorded — freshness of the answers is unknown")
    else:
        age = (now - newest).days
        if age > MAX_AGE_DAYS:
            stamp = STALE
            warnings.append(
                f"newest answer recorded {age} days ago (>{MAX_AGE_DAYS}) — re-collect before drawing conclusions"
            )

    return {
        "brand": brand,
        "site": site,
        "method": VISIBILITY_SCORING,
        "totals": {
            "observations": len(obs),
            "answered": len(answered),
            "no_answer": no_answer,
            "error": error_count,
            "collected_to": newest.isoformat().replace("+00:00", "Z") if newest else None,
        },
        "mention": mention,
        "citation": citation,
        "by_engine": by_engine,
        "by_topic": by_topic,
        "competitor_gap": gap,
        "cited_sources": {"counts": source_counts, "examples": source_examples},
        "warnings": warnings,
        "_stamp": stamp,
    }


def visibility_envelope(
    path: str,
    brand: Optional[str] = None,
    site: Optional[str] = None,
    competitors: Optional[List[str]] = None,
    now: Optional[datetime.datetime] = None,
) -> Dict[str, Any]:
    try:
        answers = load_answers(path)
    except FileNotFoundError:
        return error_envelope(
            "visibility", path,
            f"answers file not found: {path}",
            "point dseo visibility at a recorded prompt/answer JSON file",
        )
    except json.JSONDecodeError as exc:
        return error_envelope(
            "visibility", path,
            f"answers file is not valid JSON: {exc}",
            "record answers as JSON — see the geo-visibility skill for the schema",
        )
    except ValueError as exc:
        return error_envelope("visibility", path, str(exc), "fix the answers file structure and re-run")

    try:
        payload = analyze(answers, brand=brand, site=site, competitors=competitors, now=now)
    except ValueError as exc:
        return error_envelope("visibility", path, str(exc), "fix the answers file and re-run")

    stamp = payload.pop("_stamp")
    mention, citation = payload["mention"], payload["citation"]
    gap = payload["competitor_gap"]

    signals = [
        Signal("visibility.mention_rate", mention["percent"], 100.0, DETERMINISTIC,
               {"count": mention["count"], "measured": mention["measured"], "rate": mention["rate"]}),
        Signal("visibility.citation_rate", citation["percent"], 100.0, DETERMINISTIC,
               {"count": citation["count"], "measured": citation["measured"], "rate": citation["rate"]}),
        Signal("visibility.sample", float(payload["totals"]["answered"]),
               float(payload["totals"]["observations"]), DETERMINISTIC, dict(payload["totals"])),
        Signal("visibility.competitor_gap", float(len(gap)), float(mention["measured"]),
               DETERMINISTIC, {"prompts": [g["prompt"] for g in gap]}),
    ]

    findings: List[Finding] = []
    for g in gap:
        findings.append(Finding(
            id="visibility.competitor_gap", priority=len(findings) + 1, severity="high",
            effort="medium", points_lost=0.0,
            title=f"Competitor cited where the brand is absent: {g['prompt']!r}",
            detail=f"On {g['engine']}: {', '.join(g['competitors_mentioned'])} mentioned, brand not mentioned.",
        ))
    for engine, stats in payload["by_engine"].items():
        m, c = stats["mention"], stats["citation"]
        if m["measured"] >= 3 and m["count"] == 0:
            findings.append(Finding(
                id="visibility.engine_zero_mention", priority=len(findings) + 1, severity="high",
                effort="medium", points_lost=0.0,
                title=f"Brand never mentioned on {engine} (0 of {m['measured']} answers)",
                detail="Every recorded answer on this engine omitted the brand.",
            ))
        elif m["count"] > 0 and c["measured"] >= 3 and c["count"] == 0:
            findings.append(Finding(
                id="visibility.engine_zero_citation", priority=len(findings) + 1, severity="medium",
                effort="medium", points_lost=0.0,
                title=f"Mentioned but never cited on {engine} ({m['count']} mentions, 0 citations)",
                detail="The brand is named without a link to the site on this engine.",
            ))
    if 0 < mention["measured"] < SMALL_SAMPLE:
        findings.append(Finding(
            id="visibility.small_sample", priority=len(findings) + 1, severity="low",
            effort="low", points_lost=0.0,
            title=f"Small sample: {mention['measured']} answer(s) with recorded mention data",
            detail=f"Below {SMALL_SAMPLE} — rates are directional; record more prompts before acting.",
        ))

    missing: List[str] = []
    if payload["totals"]["answered"] == 0:
        missing.append("no answered observations")
    if mention["measured"] < payload["totals"]["answered"]:
        missing.append("brand_mentioned not recorded on some answers")
    if citation["measured"] < payload["totals"]["answered"]:
        missing.append("own_site_cited not recorded on some answers")

    summary_bits = [
        "mention not measured" if mention["percent"] is None else f"{mention['percent']}% mention rate",
        "citation not measured" if citation["percent"] is None else f"{citation['percent']}% citation rate",
    ]
    summary = (
        f"AI visibility ({payload['brand'] or 'brand'}): {', '.join(summary_bits)} "
        f"across {payload['totals']['answered']} answered prompt(s)"
        + (f"; {len(gap)} competitor gap(s)" if gap else "")
    )

    env = make_envelope(
        "visibility", path,
        toolkit_version=TOOLKIT_VERSION,
        scoring_version=VISIBILITY_SCORING,
        data_version=DATA_VERSION,
        evidence_stamp=stamp,
        pages_ok=payload["totals"]["answered"],
        notes=payload["warnings"],
        missing=missing,
        signal_count=sum(1 for s in signals if s.value is not None),
        signal_total=len(signals),
        scores={
            "composite": mention["percent"],
            "tier": tier_for(mention["percent"]),
            "categories": {"mention": mention["percent"], "citation": citation["percent"]},
        },
        signals=signals,
        findings=findings,
    )
    env["visibility"] = payload
    env["summary"] = summary
    return env
