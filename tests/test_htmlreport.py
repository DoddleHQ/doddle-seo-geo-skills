"""HTML deliverable: escaped, self-contained, methodology always present."""

import json
import os

from doddle_seo.cli import main
from doddle_seo.htmlreport import render_html
from doddle_seo.visibility import visibility_envelope

ROOT = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(ROOT, "fixtures", "visibility_answers.json")


def _env():
    return visibility_envelope(FIXTURE)


def test_render_is_self_contained():
    doc = render_html(_env())
    assert doc.startswith("<!DOCTYPE html>")
    assert "<title>" in doc and "</html>" in doc
    low = doc.lower()
    assert "<script" not in low
    assert 'src="' not in low and "@import" not in low  # no external assets


def test_unique_title_carries_command_target_and_date():
    doc = render_html(_env())
    env = _env()
    date = env["generated_at"][:10]
    assert f"<title>visibility: {FIXTURE} — {date}</title>" in doc
    custom = render_html(_env(), title="Q4 Client Report")
    assert "<title>Q4 Client Report</title>" in custom


def test_methodology_footer_always_present():
    env = _env()
    doc = render_html(env)
    assert "Methodology." in doc
    assert "no number was recomputed" in doc
    assert f"Reproduce: <code>dseo visibility {FIXTURE}</code>" in doc
    assert f"Toolkit {env['toolkit_version']}" in doc
    assert "scoring visibility-1" in doc
    assert "not measured, never zero" in doc


def test_fetched_text_is_escaped_never_markup():
    env = _env()
    env["findings"][0]["detail"] = "<script>alert('xss')</script> and <b>bold</b>"
    env["summary"] = 'Odd "quote" & <img src=x onerror=alert(1)>'
    doc = render_html(env)
    assert "<script>alert" not in doc
    assert "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in doc
    assert "&lt;img src=x onerror=alert(1)&gt;" in doc
    assert "onerror=alert" not in doc.split("<style>")[0].split("Methodology")[0].replace(
        "&lt;img src=x onerror=alert(1)&gt;", ""
    )


def test_null_renders_as_not_measured():
    env = _env()
    env["signals"][0]["value"] = None
    doc = render_html(env)
    assert '<span class="null">not measured</span>' in doc
    assert "<td>None</td>" not in doc


def test_scores_and_payload_sections_rendered():
    doc = render_html(_env())
    assert "<h2>Score</h2>" in doc
    assert "<h2>Signals</h2>" in doc and "visibility.mention_rate" in doc
    assert "<h2>Findings (ranked)</h2>" in doc
    assert "<h2>visibility</h2>" in doc       # command payload rendered generically
    assert "cited_sources" in doc and "listicle" in doc


def test_error_envelope_renders_error_box():
    env = visibility_envelope("/nonexistent.json")
    doc = render_html(env)
    assert 'class="error"' in doc
    assert "answers file not found" in doc


def test_cli_html_stdout(capsys):
    envelope_path = os.path.join(ROOT, "fixtures", "_tmp_env.json")
    with open(envelope_path, "w", encoding="utf-8") as fh:
        json.dump(_env(), fh)
    try:
        rc = main(["html", envelope_path])
        out = capsys.readouterr().out
    finally:
        os.unlink(envelope_path)
    assert rc == 0
    assert out.startswith("<!DOCTYPE html>")


def test_cli_html_out_writes_file(tmp_path, capsys):
    env_path = tmp_path / "env.json"
    out_path = tmp_path / "report.html"
    env_path.write_text(json.dumps(_env()), encoding="utf-8")
    rc = main(["html", str(env_path), "--out", str(out_path), "--title", "Client report"])
    receipt = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert receipt["ok"] and receipt["out"] == str(out_path)
    doc = out_path.read_text(encoding="utf-8")
    assert "<title>Client report</title>" in doc


def test_cli_html_rejects_non_envelope(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    rc = main(["html", str(bad), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["ok"] is False
    assert "not a dseo envelope" in payload["error"]["message"]
