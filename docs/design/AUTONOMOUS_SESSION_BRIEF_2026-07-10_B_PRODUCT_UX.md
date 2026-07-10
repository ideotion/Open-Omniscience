# Autonomous Session Brief — SESSION B: "Product Quality & UX" (frontend + analytics correctness)

**Date:** 2026-07-10 · **Authority:** maintainer ruled "1a 2a 3a 4a" (full autonomy; the
segmenter is CLEARED to pick & ship; all pending rulings delegated incl. design defaults;
the doc-archival pass is cleared) + the standing "always choose autonomously / I don't want
to be asked anything" rulings (2026-06-15 / 2026-06-21).
**You run in PARALLEL with Session A** (brief: `AUTONOMOUS_SESSION_BRIEF_2026-07-10_A_SCALE_BACKEND.md`).

## 0. Read first, non-negotiable

1. **Read `CLAUDE.md` in full** (the binding ledger — rulings, UI invariants #1–#30,
   lessons; everything below defers to it on conflict).
2. Read `docs/ROADMAP.md` (the board), and for your items: the field-test ledger
   `docs/product/field-test-2026-07-08/LEDGER.md` (Items 1, 2, 8, 9) and the design docs
   named per item below.
3. Execute the queue top-down; skip only with a recorded reason. NEVER ask the maintainer —
   pick the most honest, conservative default and record it in the ledger.

## 1. Territory contract (collision-proofing with Session A — HARD RULES)

**YOU OWN (edit freely):** `src/static/**` (ALL frontend: app.js/app.css/index.html/
reader/tasks/locales — the i18n hot files are yours alone this round) ·
`src/analytics/{extract,dateextract,datediag,families,selftest,engine_report}.py` ·
`src/services/stopwords.py` + `scripts/build_stopwords.py` · `src/signals/**` ·
`src/stats/**` · `configs/**` data files (feeds, stopwords, baselines, rings) · `docs/`
archival work · your own tests.

**FORBIDDEN (Session A's territory — do not edit, at all):** `src/scheduler/**` ·
`src/backup/**` · `src/database/**` · `src/monitoring/**` · `src/safety/**` ·
`src/analytics/{rollup_serve,map_serve,columnar,readmodel,corpus_epoch}.py` ·
`migrations/**` · `install.sh`. If your feature needs a schema/backend-core change, ship
what you own + record "backend → Session A / follow-up" in the PR body.

**SHARED EDGE FILES (both sessions may touch — surgical, function-scoped edits;
`git fetch origin 0.2` + rebase immediately before every push):** `src/api/insights.py`,
`src/api/diagnostics.py`, `src/api/main.py` wiring lines.

**SHARED APPEND-TARGETS (additive merges ONLY — never revert the other session's lines;
the PR #548 stale-base revert is the cautionary tale):** `CLAUDE.md`,
`docs/ledger/shipped.csv`, `docs/ledger/SHIPPED_LOG.md`, `docs/ROADMAP.md`,
`configs/external_artifacts.yml`, `tests/test_repo_invariants.py` (append, never reorder).

**Branch prefix:** name every branch `claude/b-<slug>`.

## 2. Working mode

- Small **draft PRs onto `0.2`**, each cut from a **freshly fetched** `origin/0.2`; verify
  `git show origin/0.2:pyproject.toml` reads `0.2.0` before trusting the base. Maintainer
  fast-merges; re-fetch after each merge.
- **Verify-before-push is a hard gate** (#542 lesson): adversarial skeptics COMPLETE before
  push. For ANY extractor/date/keyword work the **NEGATIVE-SPACE lens is mandatory**
  (#590 Jalali lesson: enumerate word-tail fragments, router failure paths, order-ambiguous
  forms — each must assert `[]`).
- **Extractor lockstep rule:** every `dateextract.py` vocabulary/pattern gain lands in
  `datediag.py` the SAME commit, or the probe reports phantom gaps.
- **Frontend is BROWSER-UNVERIFIED here (fork-3):** ship conservative + flagged — 
  `node --check` every touched JS, extend `test_repo_invariants`/`test_ui_invariants`
  guards, defensive empty/error states, "browser-unverified, needs click-through" in the PR.
  The UI invariants (#1–#30) and the informed-consent-by-layering rules are binding: caveats
  visible by default, translated hover bubbles, no scores, honest empty states.
- **i18n:** new chrome strings keyed ×12 (`python scripts/i18n_report.py --min 100` stays
  green; AI-drafted non-en flagged for native review) OR English-fallback via `t()` where
  the surrounding surface is un-keyed — follow each surface's existing convention.
- **Test env:** try the py3.13 venv (`python3.13 -m venv .venv && .venv/bin/pip install -e
  ".[analysis,dev]"`); else py3.11 + the ledger's CI-only patterns (standalone pure-module
  repros; `pip install mypy==2.1.0` + per-file mypy). Full-suite health check after every
  merged wave; never switch branches mid-suite.
- Ledger discipline: shipped.csv row per item; lessons → SHIPPED_LOG + Session-rituals;
  decisions → CLAUDE.md same turn; roadmap statuses updated.

## 3. Work queue (priority order — get through as much as possible)

### B1 — THE SEGMENTER (ruled 2a: pick & ship; the maintainer's #1-value pending ruling)
zh/ja/th keywords are junk at scale (zh 46K + th 21K + ja 12K junk keywords; Heaps β≈0.95;
prune finds 0 orphans — segmentation is the only lever), and ko/vi/mr lack stoplists.
**Do:** select license-clean, pure-local, offline segmenters — evaluate (at minimum) jieba
(MIT, pure-Python) for zh · Janome (Apache-2.0, pure-Python, bundled dict) for ja ·
PyThaiNLP's newmm (Apache-2.0) for th. **Prefer pip-installable optional-extra packaging**
(a new `[segmentation]` extra) over vendoring into the repo (avoids the 100 MB rule and
license-file duplication); vendor only if pip is impossible, sha256-pinned + registry entry.
Wire through the extraction seam (`analytics/extract.py` / the UNSEGMENTED language status),
with GRACEFUL DEGRADE when the extra is absent (current behaviour preserved byte-identically)
and the language-status report flipping unsegmented→functional when present. Stoplists: check
stopwords-iso coverage for ko/vi/mr and vendor what exists via the established
`build_stopwords.py` channel (never fabricate a list; sr/az remain honestly uncovered unless
a real source exists). **Measure** the junk reduction on fixture corpora + add per-language
selftest golden cases; document the retroactive path (keyword-only re-index applies it to an
existing corpus). Registry entries for every dated artifact, same commit (the protocol test
enforces this).

### B2 — Indices board: the FRED ISO-3→ISO-2 bug (field-test Item 1 — user-visible, quick win)
The OECD `SPASTT01<ISO3>M661N` feed ids use 3-letter codes but FRED uses 2-letter → every
OECD feed 404s → Europe/Asia(ex-Nikkei)/Africa/S.America/Oceania boards are EMPTY. The
19-row correction table is in `docs/product/field-test-2026-07-08/LEDGER.md` Item 1. Apply
it in `configs/index_feeds.yml`; if the sandbox network permits, live-verify a sample of the
corrected ids against FRED; either way the feeds fail LOUDLY on a wrong id (never fabricate).
Add a test pinning the 2-letter convention.

### B3 — FLOOD / BURY language-aware cohorts (field-test Item 8, 4th batch)
`signals/flood` surfaces stoplist-leaked filler (nl "kijk"/"zien") as topics; `signals/bury`
flags non-English sources for "burying" English keywords they simply write in their own
language. Fix: same-language cohort scoping (a source is only compared against sources
publishing in the same language for a keyword of that language; ring translations may
bridge, labelled), plus stoplist hygiene from B1's work. No scores; the honest components +
innocent-explanation stay. These endpoints are shared-edge (`api/insights.py`) — surgical.

### B4 — Date-extraction recall (Persian 0% · Hungarian 22% · overall 62.1%)
MEASURE FIRST on the current tree (the #590 Jalali claim-on-route work may already have
moved fa — run datediag on fixtures before building). Then close the real gaps (fa
calendar/numerals; hu morphology; the residual `date-like-but-unextracted` classes).
The #590 negative-space discipline is BINDING here (month-name substrings, router
fallthrough, day-first ambiguity → assert `[]`; `_MIN_YEAR` leak risk). datediag lockstep
same commit.

### B5 — Backup UX truth-telling (field-test Item 9; the backend/endpoints exist — this is YOUR frontend half)
(a) `api()`/`_uxPoll` has NO timeout/retry: one dropped `/volumes/status` poll shows a fatal
"Backup failed: NetworkError" while the job keeps running. Fix: retry with backoff +
job-state-as-truth (only a backend-reported error state may say "failed"); a transient poll
failure shows an honest "connection hiccup — retrying". (b) Wire the shipped verify job
(`POST /api/backup/v2/volumes/verify`) + pause/resume + the paused-state label into the
backup UI (Session A may add a folder-manifest verify endpoint — wire it too if merged, else
note it). (c) The `#toast` duration fix already shipped (#612) — don't redo it.

### B6 — Diagnostics `/all` job UI (P1.9's remaining half)
The backend job exists (#600 D2). Add the Settings→Diagnostics button that starts it, polls
job status, and offers the download when done — replacing the 36-minute blocking click.

### B7 — Dead default calendar feeds (finding E, still open)
Drop the robots-disallowed/dead bundled feeds (google-hol-*, webcal.guru religious,
cantonbecker/floern etc. per the 2026-06-13 + 07-08 preflights) from the DEFAULTS; keep the
working set (wph-*, monkeyness moons, ose-calendar). Honest fail-closed stays for anything a
user adds themselves.

### B8 — Home dashboard remainder + "Latest in your corpus"
Home (§2 dashboard ruling): top ooChart graphs · the synthesized-Leads carousel (LOCAL
analytic synthesis, never LLM; pausable + keyboard a11y; a timed rotation may never hide a
caveat) · most-recent-articles-by-tag. Then "Latest in your corpus" S1→S3 per
`docs/FUTURE_DEVELOPMENTS.md` → "Home 'Latest in your corpus'": S1 recency endpoint
(`created_at` order + min-words/min-cited-sources GATES the user sets and sees — transparent
filters, never a quality score; script-aware length rule for zh/ja/th; near-dup collapse via
`src/signals/near_dup.py`), S2 the Home panel (each shown article displays its REAL values),
S3 per-content-type defaults + dim-with-values (autonomous call: dim + toggle, never
silently hide). Redundancy rule #8 holds: every element deep-links to its real tab.

### B9 — Keyword hover-stats, Slice 2 (ruled 3a: YOU decide the stats)
The clickable in-article keywords (slice 1 shipped) gain a #oo-tip-style hover of REAL
stats. Decide the set — recommended: mention count + distinct-article spread (n) · the
disclosed trend rate over the preset windows · ring translation (original → translation) ·
top 3 co-occurring keywords. Counts only, NO score, method+caveat in the bubble, ×12 via the
existing translated-title mechanism. PERF-SAFE reads via the article_id-indexed mention
tables (NEVER the keyword→articles codec join — the ledger perf trap). Record the chosen
set as a ruling-executed note in CLAUDE.md.

### B10 — i18n long-tail burn-down
`python scripts/i18n_report.py --audit-chrome` → key the remaining static chrome clusters
×12 (the locale files are yours alone this round — no parallel-session conflict). Follow the
established slice pattern (de-tag inline emphasis so strings key as full sentences; skip
security-dense paragraphs only if a faithful translation is doubtful — flag them).

### B11 — Chrome absorption items
(a) Remove the Insights search bar (#ins-term + Explore) — GATED on verifying the omnibar +
spawned-analysis-tab flow fully absorbs term-exploration (the Desk lesson: absorption test
first, then remove). (b) An editable keybindings panel in Settings + shortcuts list in Help
(UI-shell §4 remainder). (c) The FTS present/absent probe contradiction — verify search
works and the integrity sweep's deadline-interrupted probe reports honestly (may be
display-only).

### B12 — Rulings delegated to you (3a) — decide + record each in CLAUDE.md
- **Rare-earths source:** implement the recommended USGS supply-data ingestion
  (`src/stats/` — descriptive supply figures, clearly NOT spot prices, honest labelling).
- **`global`/`transnational` region value:** add to the source schema vocabulary +
  catalog handling (the "International" bodies that deliberately have no ISO code).
- **Multilingual sentiment:** pyproject BANS torch/onnx/transformers — so the honest
  decision space is (i) the subjectivity/loaded-language pivot feeding the manipulation
  cards via rule-based/lexicon methods, or (ii) a recorded deferral. Decide, record, and if
  (i), build the first slice with per-language honesty (never a fabricated neutral).
- **Lemmatization default-on:** STAYS measure-gated (the gold set is corpus-specific and
  maintainer-made — you cannot honestly synthesize it). Record the deferral; surface the
  `lemma_preview` more visibly if cheap.

### B13 — Doc archival pass (ruled 4a: cleared)
Exactly like the merged roadmap cleanup (#612), non-lossy `git mv` + retargeted links +
index READMEs: spent `docs/design/AUTONOMOUS_SESSION_BRIEF_*.md` + `AUTONOMOUS_BUILD_BRIEF_
DATA_ARCH.md` → `docs/archive/session-briefs/` (**EXCEPT the two live 2026-07-10 A/B briefs
— they stay until their sessions complete**); `RELEASE_0.0.8_PLAN*.md`, `RELEASE_0.1_PLAN.md`,
`RELEASE_0.1_RC_GATE.md`, `V01_ALPHA_ACTION_PLANS.md`, `V01_FIELD_TEST_BASELINE.md` →
`docs/archive/releases/`; the three `field-test-*` dirs → `docs/archive/field-tests/`.
Retarget EVERY inbound link (grep before and after); nothing deleted; `docs/README.md` +
`docs/archive/` READMEs updated.

## 4. Definition of done (per item and for the session)

Tests green (full suite where runnable; CI-noted where not) · skeptics (incl. negative-space
for extractors) completed pre-push · node --check + invariant guards for every UI change ·
i18n gate green · draft PR with honest status (shipped / browser-unverified-needs-
click-through / blocked-with-reason) · ledger row + roadmap statuses updated · no
forbidden-territory edits · shared files merged additively. End with a summary PR comment:
what shipped, what needs the maintainer's click-through, what's blocked and why.
