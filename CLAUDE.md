# CLAUDE.md — long-term session memory (maintainer-mandated)

Read this first, every session. It exists because UI/UX work regressed between
sessions (the Wikipedia language dropdown became a text input); the maintainer
requires this never to happen again. **Critical invariants below are ALSO
enforced by `tests/test_repo_invariants.py::test_ui_invariants` — extend that
test whenever you add one here.**

## Non-negotiables (project §0.5 + maintainer rulings)
- Local-first, loopback-only; the ONLY external service call is the gated,
  off-by-default DuckDuckGo topic discovery. Producers/briefing/discovery NEVER
  touch the network. App boot makes zero network calls.
- robots.txt fail-closed, per-host politeness, honest bot UA, single fetch path
  (`EthicalFetcher`), **global network kill switch** (`src/ingest`
  activate/clear_kill_switch — the Collect Stop button trips it).
- Honesty by construction: no composite trust/quality scores (CardSchemaError
  enforces); every signal carries method + caveat + n; degrade loudly.
- Whole roadmap ships under cycle branch `0.08` ⇒ release 0.0.8 (maintainer:
  do NOT open 0.09 until told). Version single-sourced from pyproject.
- No bundling of Ollama/models in the repo (GitHub 100 MB limit; decided
  2026-06). Model catalog must stay date-stamped (`CATALOG_AS_OF` + freshness
  test). Clearnet is a stated install prerequisite for model downloads.

## UI invariants (maintainer-ruled; do not regress)
1. **Wikipedia edition picker is a `<select>` dropdown** (id `wiki-lang`), fed
   by `/api/wiki/languages` with continent `<optgroup>`s. Never a free-text input.
2. **Left sidebar lists all tabs and stays visible** — it may collapse to an
   icon rail, but must never disappear off-canvas above 600 px width.
3. **Top bar elements have constant footprints**: `.act-host` keeps its 160 px
   slot even when empty; `#llm` and `#health` have fixed min-widths; nothing on
   the right may shift as fetch hosts/labels change.
4. **A persistent compact vitals strip** (`#vitals-mini`: CPU · RAM · ↓ rate)
   lives in the top bar; the version number is NOT displayed in the chrome.
5. **The brand mark is the ASCII eye** (`assets/logo.txt`) as vector — the
   pointed-oval + grid-iris SVG in `index.html` and `assets/icon.svg`.
6. Article links in analytics/insights lead to the LOCAL reader
   (`/api/articles/{id}/view`) first; the external original is a secondary
   "source ↗" link. The reader shows "Related in your corpus" (shared-keyword
   overlap counts).

## Session rituals
- Verify with BOTH venv profiles when deps change; `pytest -q` full suite must
  stay green; mypy ratchet ≤ baseline in CI; `node --check` every `<script>`
  block after UI edits; locale files must stay 100% (scripts/i18n_report.py)
  when adding chrome strings (12 languages, Arabic is RTL).
- Maintainer merges PRs fast: after `git push`, if the output says
  "[new branch]", the previous PR was merged — open a NEW PR onto `0.08`.
- Never use backticks inside `git commit -m` heredocs (shell substitution).

## Open queue (when maintainer says proceed)
- **Insights mindmap**: multi-layer zoom (keyword → family → supergroup) —
  data exists (`keyword_supergroups`, families API); needs zoomable rendering +
  proper legend on the trend graph above it. (Maintainer expected this; treat
  as the next feature item.)
- **World stock indices don't download** in live test — diagnose via
  `data/source_preflight.jsonl` + the import response (suspect robots fail-closed
  on fred/stooq or network posture); fix honestly, never bypass robots.
- **Interactive charts** (maintainer, live test): commodity/markets graphs need
  zoom (wheel/drag) + discrete per-graph adjustable legends — "the user should
  feel closer to the data". Same treatment for the Insights trend graph.
- **Tag-driven corpora** (maintainer): multi-tag selection in Sources (selected
  tags change colour; AND-combination) and a "make this selection a corpus"
  flow -- per-corpus article counts, keyword trends, analyses.
- **Commodities depth**: 1-month windows say "not enough points" (fix window/
  interpolation honesty); S&P500 is an INDEX not a commodity (reclassify);
  expand feeds: rare earths, oil, natural gas, LNG, sand, corn/cereals, sugar.
- **Library tab**: anchor should be #library not #database; drop the Refresh
  button if data is live; country data must be stored ISO-2 and DISPLAYED as
  full names via one conversion (US=1553 vs "United States"=210 split shows
  mixed encodings today).
- **Custody tab UX**: most users won't get it -- rename/explain/guided steps.
- Offline LLM kit (RM-08 release artifact). DuckDuckGo discovery channel only
  after RM-03 gate UX proves out.
