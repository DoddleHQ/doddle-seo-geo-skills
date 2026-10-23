# Changelog

All notable changes to `doddle-seo-geo-skills` are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/); versioning follows
[Semantic Versioning](https://semver.org/).

## [0.3.0] - 2026-10-24

Client-deliverable standard and review discipline, learned from openSEO's workflow depth.

### Added

- **`dseo html <envelope.json> [--out FILE] [--title T]`**: renders *any* saved `dseo`
  envelope as one self-contained HTML document — inline CSS, no scripts, no external
  assets; unique `<command> <target> — YYYY-MM-DD` title; scores/signals/findings tables
  with signal classes and severity badges; generic payload rendering; evidence-gap section;
  mandatory methodology footer (versions, `generated_at`, stamp, reproduce command,
  `null` rule). All envelope text is HTML-escaped — crawled-page excerpts stay data.
- **`common/report-standard.md`** (lint-enforced): the contract around the renderer —
  rendered-never-hand-built, unique title, methodology footer, `null` as "not measured",
  sharing gate with `DRAFT` naming, chat discipline (three bullets plus artifact path),
  re-run-don't-edit revisions. Wired into `geo-report` and `seo-reporting`.
- **Striking-distance sub-flow** in `seo-keyword-research`: GSC-first quick wins
  (positions 8–20, ≥50 impressions — aligned with `reporting-methodology.md`), reported as
  its own bucket ahead of new discovery, filtering done by the tool.
- **Second-pass review gates** in `seo-audit` (new step 6) and `geo-audit` (new step 6):
  trace every recommendation to an envelope field, reason for each de-emphasised finding,
  named runner-up, and the second-agent question — *"which of these numbers is not in the
  envelope?"* — plus a Common Mistakes row each.
- **Tests**: 10 renderer tests (`test_htmlreport.py`), incl. XSS-escape and
  self-containment checks. 65 tests total. CI smoke for `dseo html`.

### Changed

- Toolkit `0.2.0` → `0.3.0`; all skills/blueprints → `0.3.0` (manifests too).
- `geo-report` toolkit/workflow now covers the HTML deliverable path.

## [0.2.0] - 2026-10-24

Two deterministic commands for answer-level AI visibility and keyword cannibalisation,
plus the skills that narrate them. Skills learned from comparing against openSEO's
workflow depth: honest denominators, warnings-first reporting, and a second-agent-style
review gate are in the new skills; the rates and splits are computed, never narrated.

### Added

- **`dseo visibility <answers.json>`** (method `visibility-1`): brand mention and site
  citation rates over a recorded prompt/answer set, with per-engine/per-topic breakdowns,
  competitor-gap detection, heuristic cited-source classification
  (`owned`/`competitor`/`forum`/`listicle`/`editorial`), small-sample and
  not-recorded warnings, and a 30-day `STALE` evidence stamp. Missing booleans are
  excluded from denominators — never counted as `false`; `no_answer`/`error` observations
  never enter a denominator.
- **`dseo cluster <serp.json>`** (method `cluster-1`): keyword grouping by containment
  overlap of recorded ranking domains (default threshold 0.4, union-find), with
  mixed-intent flags, coverage percent, and exclusion (not guessing) of keywords that have
  no recorded SERP results.
- **`dseo cannibalize <gsc-export>`** (method `cannibal-1`, contested rule: top page under
  60% of recorded impressions): queries ranking more than one page from a GSC CSV/JSON
  export, with `affected_percent`, `impressions_at_risk` (unsized splits excluded, not
  zeroed), `top_share_percent`, and impressions-ranked findings.
- **2 skills**: `geo-visibility` (geo-specialist), `seo-keyword-clustering`
  (seo-strategist) — full contract sections, blueprints, warnings-first workflows.
- **Tests**: 26 new tests (`test_visibility.py`, `test_clustering.py`), fixtures for
  answers/serp/GSC, CI smoke for the three new commands. 55 tests total.

### Changed

- Toolkit `0.1.0` → `0.2.0`; `data_version` → `ai-crawlers-2026-10-2` (source-classification
  registry). All skill/blueprint versions → `0.2.0`.
- `error_envelope()` now defaults the version fields (previously required callers to pass
  them; the new commands are its first callers).
- Skill inventory: 30 → 32 (GEO 11, SEO 21); README, matrix, manifests updated.

## [0.1.0] - 2026-10-18

First release. Doddle SEO & GEO OS — a DoddleOS peer pack.

### Added

- **Deterministic toolkit** (`scripts/doddle_seo/`, stdlib-only, Python 3.9+, CLI `dseo`):
  - `fetch` (HTTPS-only, SSRF guard, gzip/deflate, local files), `htmlparse` (stdlib
    `html.parser`), `citability` (7 signals), `robots` + a 27-entry AI-crawler registry,
    `llmstxt` (parse/validate/generate), `schema` (JSON-LD validation + entity signals),
    `scoring` (technical + citability + findings), `audit` (site crawl + weighted
    categories), `report` (markdown), versioned `envelope`.
  - Commands: `score`, `audit`, `citability`, `technical`, `schema`, `robots`, `llmstxt`,
    `report`, `version`, `doctor`.
- **30 skills** (`.claude/skills/`), a hybrid of agent-agnostic `SKILL.md` and DoddleOS
  `blueprint.yaml`:
  - GEO (10): `geo-audit`, `geo-citability`, `geo-crawlers`, `geo-llmstxt`, `geo-schema`,
    `geo-report`, `geo-brand-entity`, `geo-platform`, `geo-monitor`, `geo-content`
  - SEO (20): `seo-audit`, `seo-technical`, `seo-onpage`, `seo-schema`,
    `seo-internal-linking`, `seo-hreflang`, `seo-keyword-research`, `seo-topical-map`,
    `seo-content-brief`, `seo-competitor`, `seo-backlinks`, `seo-digital-pr`, `seo-local`,
    `seo-ecommerce`, `seo-strategy`, `seo-reporting`, `seo-sxo`, `seo-programmatic`,
    `seo-migration`, `seo-geo-fundamentals`
- **5 agents** (`.claude/agents/`): `geo-specialist`, `seo-strategist`, `technical-auditor`,
  `schema-architect`, `entity-strategist`.
- **Shared references** (`.claude/skills/common/`): `response-contract.md`,
  `data-reliability.md`, `fundamentals.md`, `scoring-methodology.md`,
  `mcp-integration-guide.md`.
- **Manifests**: `plugin.json`, `marketplace.json`, `package.json`.
- **Validation**: `scripts/lint_pack.py` and 29 tests (`tests/`), plus CI.
- **Docs**: `README.md`, `skills-matrix.md`, `AGENTS.md`.

### Principles

- Deterministic first: the toolkit computes, skills narrate.
- `null` means not measured, never zero.
- No hardcoded market statistics (linter-enforced).
- Fetched page text is data, never instructions.

[0.3.0]: https://github.com/DoddleHQ/doddle-seo-geo-skills/releases/tag/v0.3.0
[0.2.0]: https://github.com/DoddleHQ/doddle-seo-geo-skills/releases/tag/v0.2.0
[0.1.0]: https://github.com/DoddleHQ/doddle-seo-geo-skills/releases/tag/v0.1.0
