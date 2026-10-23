"""Render any ``dseo`` envelope as a self-contained HTML deliverable.

Method: presentation only. Every number, class, and finding is copied from the input
envelope; nothing is recomputed, re-ranked, or re-labelled. All envelope text is
HTML-escaped — findings carry excerpts from crawled pages, which are data, never markup
and never instructions.

House rules live in ``.claude/skills/common/report-standard.md``:

- one self-contained document — inline CSS, no scripts, no external assets;
- unique title ``<command> <target> — YYYY-MM-DD``;
- mandatory methodology footer (toolkit/scoring/data versions, generated_at, evidence
  stamp, reproduce command);
- ``null`` renders as "not measured", never 0.
"""

from __future__ import annotations

import datetime
import html
import json
from typing import Any, Dict, List

STANDARD_KEYS = frozenset({
    "ok", "command", "target", "generated_at", "toolkit_version", "scoring_version",
    "data_version", "evidence", "completeness", "scores", "signals", "findings",
    "error", "summary", "markdown",
})

_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  margin: 0; padding: 2rem 1rem; background: #f6f7f9; color: #1b1f24; line-height: 1.5; }
main { max-width: 960px; margin: 0 auto; background: #fff; border: 1px solid #d8dde3;
  border-radius: 10px; padding: 2rem; }
h1 { font-size: 1.35rem; margin: 0 0 .25rem; }
h2 { font-size: 1.05rem; margin: 1.75rem 0 .5rem; border-bottom: 1px solid #e4e8ec; padding-bottom: .3rem; }
.meta { color: #57606a; font-size: .85rem; margin-bottom: 1rem; }
.badge { display: inline-block; font-size: .75rem; font-weight: 600; padding: .1rem .5rem;
  border-radius: 999px; vertical-align: middle; }
.stamp-CURRENT { background: #dafbe1; color: #116329; }
.stamp-PARTIAL { background: #fff8c5; color: #7d4e00; }
.stamp-STALE { background: #ffebe9; color: #a40e26; }
.sev-critical, .sev-high { background: #ffebe9; color: #a40e26; }
.sev-medium { background: #fff8c5; color: #7d4e00; }
.sev-low { background: #ddf4ff; color: #0969da; }
.klass { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .78rem;
  background: #eef1f4; border-radius: 4px; padding: .05rem .35rem; }
.summary { font-size: 1.02rem; background: #f0f6ff; border: 1px solid #c9ddff; border-radius: 8px;
  padding: .75rem 1rem; margin: .75rem 0; }
.error { background: #ffebe9; border: 1px solid #ffcecb; border-radius: 8px; padding: .75rem 1rem; }
.error b { color: #a40e26; }
.score { font-size: 1.6rem; font-weight: 700; }
.tier { color: #57606a; font-weight: 600; }
table { border-collapse: collapse; width: 100%; font-size: .88rem; margin: .4rem 0 1rem; }
th { text-align: left; background: #f0f2f4; font-weight: 600; }
th, td { border: 1px solid #d8dde3; padding: .4rem .55rem; vertical-align: top; }
td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.null { color: #8b949e; font-style: italic; }
.detail { color: #57606a; font-size: .82rem; }
.note { color: #57606a; font-size: .85rem; margin: .15rem 0; }
.payload pre { background: #f6f8fa; border: 1px solid #d8dde3; border-radius: 6px;
  padding: .6rem; overflow-x: auto; font-size: .8rem; }
footer { max-width: 960px; margin: 1rem auto 0; color: #57606a; font-size: .8rem; }
footer code { background: #eef1f4; padding: .05rem .3rem; border-radius: 4px; }
@media print { body { background: #fff; padding: 0; } main { border: 0; padding: 0; } }
"""

_SEV_CLASS = {
    "critical": "sev-critical", "high": "sev-high",
    "medium": "sev-medium", "low": "sev-low",
}


def e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _fmt_num(value: Any) -> str:
    if value is None:
        return '<span class="null">not measured</span>'
    if isinstance(value, float) and value.is_integer():
        return e(int(value))
    if isinstance(value, bool):
        return e(value)
    return e(value)


def _detail_text(detail: Any) -> str:
    if detail is None or detail == {} or detail == []:
        return '<span class="null">not measured</span>'
    if isinstance(detail, dict):
        return e(", ".join(f"{k}={_scalar(v)}" for k, v in detail.items()))
    if isinstance(detail, list):
        return e(", ".join(_scalar(v) for v in detail))
    return e(detail)


def _scalar(value: Any) -> str:
    if value is None:
        return "not measured"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _table(headers: List[str], rows: List[List[str]], classes: str = "") -> str:
    if not rows:
        return ""
    head = "".join(f"<th>{e(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    cls = f' class="{classes}"' if classes else ""
    return f"<table{cls}><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _payload_html(key: str, value: Any) -> str:
    out = [f'<section class="payload"><h2>{e(key)}</h2>']
    if isinstance(value, dict):
        rows = [[f"<b>{e(k)}</b>", _fmt_num(v) if not isinstance(v, (dict, list))
                 else f'<pre>{e(json.dumps(v, indent=2, ensure_ascii=False))}</pre>']
                for k, v in value.items()]
        out.append(_table(["Field", "Value"], rows))
    elif isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
        keys: List[str] = []
        for item in value:
            for k in item:
                if k not in keys:
                    keys.append(k)
        rows = [[_fmt_num(item.get(k)) if not isinstance(item.get(k), (dict, list))
                 else f'<pre>{e(json.dumps(item[k], ensure_ascii=False))}</pre>'
                 for k in keys] for item in value]
        out.append(_table(keys, rows))
    elif isinstance(value, list):
        rows = [[_fmt_num(v)] for v in value]
        out.append(_table([key], rows))
    else:
        out.append(f"<pre>{e(value)}</pre>")
    out.append("</section>")
    return "\n".join(out)


def render_html(env: Dict[str, Any], title: str = "") -> str:
    """Render one envelope as a complete HTML document."""
    command = str(env.get("command") or "report")
    target = str(env.get("target") or "")
    generated = str(env.get("generated_at") or "")
    date = generated[:10] if generated else datetime.date.today().isoformat()
    title = title or (f"{command}: {target} — {date}" if target else f"{command} — {date}")

    stamp = str((env.get("evidence") or {}).get("stamp") or "PARTIAL")
    parts: List[str] = []
    parts.append(f"<span class=\"badge stamp-{e(stamp)}\">evidence {e(stamp)}</span>")
    if not env.get("ok", True):
        err = env.get("error") or {}
        parts.append(
            f'<div class="error"><b>ERROR</b> {e(err.get("message", "unknown error"))}<br>'
            f'<span class="detail">{e(err.get("hint", ""))}</span></div>'
        )
    if env.get("summary"):
        parts.append(f'<p class="summary">{e(env["summary"])}</p>')

    scores = env.get("scores")
    if scores:
        composite = scores.get("composite")
        tier = scores.get("tier") or "Not scored"
        parts.append(
            '<h2>Score</h2>'
            f'<span class="score">{_fmt_num(composite)}</span>'
            f' <span class="tier">{e(tier)}</span>'
        )
        cats = scores.get("categories") or {}
        if cats:
            rows = [[e(k), _fmt_num(v)] for k, v in cats.items()]
            parts.append(_table(["Category", "Value"], rows))

    signals = env.get("signals") or []
    if signals:
        rows = []
        for s in signals:
            skipped = (f'<span class="detail">{e(s["skipped_reason"])}</span>'
                       if s.get("skipped_reason") else '<span class="null">—</span>')
            rows.append([
                e(s.get("id", "")),
                _fmt_num(s.get("value")),
                _fmt_num(s.get("max")),
                f'<span class="klass">{e(s.get("class", ""))}</span>',
                _detail_text(s.get("detail")),
                skipped,
            ])
        parts.append("<h2>Signals</h2>")
        parts.append(_table(["Signal", "Value", "Max", "Class", "Detail", "Skipped"], rows))

    findings = env.get("findings") or []
    if findings:
        rows = []
        for f in findings:
            sev = str(f.get("severity") or "low")
            badge = f'<span class="badge {_SEV_CLASS.get(sev, "sev-low")}">{e(sev)}</span>'
            rows.append([
                _fmt_num(f.get("priority")), badge, e(f.get("effort", "")),
                f"<b>{e(f.get('title', ''))}</b><br><span class=\"detail\">{e(f.get('detail', ''))}</span>",
            ])
        parts.append("<h2>Findings (ranked)</h2>")
        parts.append(_table(["#", "Severity", "Effort", "Finding"], rows))

    evidence = env.get("evidence") or {}
    notes = evidence.get("notes") or []
    missing = (env.get("completeness") or {}).get("missing") or []
    if notes or missing:
        parts.append("<h2>Evidence gaps</h2>")
        for n in notes:
            parts.append(f'<p class="note">note: {e(n)}</p>')
        for m in missing:
            parts.append(f'<p class="note">missing: {e(m)}</p>')

    for key, value in env.items():
        if key in STANDARD_KEYS or value in (None, {}, []):
            continue
        parts.append(_payload_html(key, value))

    if not parts:
        parts.append('<p class="note">Envelope carried no sections.</p>')

    reproduce = f"dseo {command} {target}".strip()
    footer = (
        "<footer><p><b>Methodology.</b> Rendered by <code>dseo html</code> from the recorded "
        f"envelope — no number was recomputed. Toolkit {e(env.get('toolkit_version', 'unknown'))}, "
        f"scoring {e(env.get('scoring_version', 'unknown'))}, data "
        f"{e(env.get('data_version', 'unknown'))}, generated {e(generated or 'unknown')} "
        f"(evidence {e(stamp)}). Reproduce: <code>{e(reproduce)}</code>. "
        "A <i>null</i> value means not measured, never zero. "
        "Signal classes: <code>deterministic</code>, <code>heuristic</code>, "
        "<code>live</code>, <code>advisory</code>.</p></footer>"
    )

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{e(title)}</title>\n<style>{_CSS}</style>\n</head>\n<body>\n"
        f"<main>\n<h1>{e(title)}</h1>\n"
        f'<p class="meta">{e(command)} · {e(target)} · {e(generated)}</p>\n'
        + "\n".join(parts)
        + "\n</main>\n"
        + footer
        + "\n</body>\n</html>\n"
    )
