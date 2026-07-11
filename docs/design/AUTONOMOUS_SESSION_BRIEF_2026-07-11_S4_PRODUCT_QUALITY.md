# SESSION 4 of 6 — TIER 3: product quality & keyword-engine remainders

**Mission:** the reader-facing quality tail — what a journalist actually touches every day.
The informed-consent instrument (caveats visible, layered hovers, ×12 locales) and the UI
invariants #1–#30 are your operating constraints, not decoration. Read
`SESSIONS_2026-07-11_CONVENTIONS.md` §0 first, then **absorb S3's carry-overs**. All
frontend ships conservative + flagged (browser-unverified; node --check + invariant guards
+ defensive states).

## Queue (top-down)

### S4.1 — Date-extraction recall: the residual tail
The hu/fa relative-day words shipped (B4); now the remaining `date-like-but-unextracted`
classes — run `datediag` over the fixture corpora FIRST (measure, then build), then close
the real gaps, including **CJK dates through the new segmenter seam** (segmented tokens
un-glue the "报道于2024-06-11发布" class; the CJK `\b`-never-fires lesson + digit-safe
lookarounds are binding). THE DISCIPLINE: every vocabulary/pattern gain lands in
`datediag.py` the SAME commit; the #590 negative-space skeptic pass (month-name word-tails,
router fallthrough, order-ambiguous forms → assert `[]`) is mandatory before push.

### S4.2 — Ring-translation frontend
Surface what the backend already computes: the cross-country ring split
(`/api/insights/ring-countries`) as a view, and `language_breakdown` + `members` on merged
keyword rows in the Trends/Home lists (original → translation already renders; show the
per-language composition on demand via the #oo-tip layering). De-US-centring in action:
a concept's coverage ACROSS languages becomes visible. ×12 keys for new chrome.

### S4.3 — The synthesized-Leads carousel (the last Home-dashboard piece)
A rolling carousel of simplified Lead cards on Home: LOCAL analytic synthesis only (never
LLM), user-controlled + keyboard-accessible + pausable, and a timed rotation may NEVER hide
a caveat (the caveat travels on every rotated face). Honest ordering (evidence tier +
recency + spread — the existing card ordering, never a hidden score). Redundancy rule #8:
every card deep-links to its real surface.

### S4.4 — B11a: the Insights search-bar absorption, verified then removed
The gate: prove the omnibar Enter→analysis-window flow fully absorbs `exploreTerm()`'s
4-endpoint view (trend + associations + context snippets + mindmap) — write the absorption
TEST that asserts each capability exists on the analysis window, then remove `#ins-term` +
the Explore button (the Desk lesson: the test is what makes removal safe). If a capability
is genuinely missing, port it first or leave the bar and record why.

### S4.5 — i18n long tail
`scripts/i18n_report.py --audit-chrome` → key the remaining static chrome clusters ×12
(slice convention: de-tag inline emphasis so strings key as full sentences; AI-drafted
non-en flagged for native review). Then the two structural pieces: **composite-string
format support** (`"${n} source(s)"`-class strings) in the i18n engine, and the
**server-built Home-card TITLE translation design** (titles carry data values → a
template-key + slot mechanism; design + a first implemented producer, conservative).

### S4.6 — The in-app `generic_terms` detector block
Fold the offline `analyze_keyword_log.py --generic-terms` DF-ubiquity detector into
`src/analytics/engine_report.py` as a `generic_terms` block (like `ring_candidates` /
`lemma_preview`), so the maintainer's routine diagnostics export carries the open-class
stoplist candidates automatically — propose, human judges, NEVER auto-apply. This closes
the FLOOD-filler loop without hand-guessing stopwords (the ledger's no-blanket-rule
discipline).

### S4.7 — Guided-wizard remaining slices
The two deferred steps of the first-launch wizard: the **encryption-choice step** (absorbs
the pre-DB choice into the guided flow — encryption-by-default preserved, no-recovery
stated honestly, length guidance; reorder never removal) and the **sources-by-theme step**
(drive it from the catalog's real tag taxonomy + the country/language-emphasis picker;
ends at the consented first collect — the ONE consent popup fires, the wizard never POSTs
the network itself; test-pinned like the existing wizard invariants).

### S4.8 — (stretch) BURY denominator rescoping
The labelled follow-up from #620: full same-language denominator rescoping with
ring-translation bridging (a source measured against the same-language corpus slice, rings
bridging labelled). Only if the queue above is done.

## Explicitly NOT yours
The FLOOD stoplist batch itself (operator: measured log sweep — S4.6 gives them the
instrument) · rulings builds (S5) · backlog features (S6) · anything networked.

## Closeout
Ledger rows + ROADMAP flips + CARRY-OVER for S5. List every browser-unverified surface for
the maintainer's click-through pass.
