# SESSION 5 of 6 — TIER 4: decided-but-unbuilt rulings + the measurement instruments

**Mission:** turn the decided rulings into working code, and build the INSTRUMENTS that
unblock the measure-gated ones. The doctrine here is measure-before-trust: where a ruling
waits on maintainer data (gold sets, keyword logs, live numbers), your job is to make
producing that data nearly effortless — never to synthesize it. Read
`SESSIONS_2026-07-11_CONVENTIONS.md` §0 first, then **absorb S4's carry-overs**.

## Queue (top-down)

### S5.1 — USGS minerals supply ingestion (rare-earths ruling, decided: build the parser)
Per the B12 decision: USGS **Mineral Commodity Summaries** SUPPLY data (annual production /
reserves / net-import-reliance) — explicitly labelled supply figures, NEVER spot prices (no
free spot source exists; nothing is fabricated). Build: a `us-usgs` stats-agency entry +
a pure parser under `src/stats/` (the `sdmx.py` pattern: network-free, fixture-tested,
provenance-rich `StatFigure` rows, vintaged, gaps stored NULL) against a HAND-BUILT fixture
mirroring the documented MCS format (clearly marked fixture). The commodities board gains an
honest "supply data, not prices" surface for rare earths. The real data fetch is NETWORKED →
operator list, with the exact fetch instructions.

### S5.2 — The subjectivity / loaded-language engine (sentiment ruling, decided: the pivot)
The model path is banned (no torch/onnx); build the rule-based engine + seam:
- `src/analytics/subjectivity.py`: a per-language lexicon loader (the stopwords-iso vendored
  pattern: `configs/subjectivity/<lang>.txt`, dated, registry entries) + a scorer that emits
  DESCRIPTIVE components (loaded-term density, term list with spans, n) — never a composite
  score, never a fabricated neutral; languages without a lexicon report
  `available:false, reason` (the honest gap, like VADER's English-only).
- Feed the manipulation cards (outrage-intensity annotates, never a standalone verdict) +
  a labelled per-article surface (three-class provenance discipline).
- Ship with FIXTURE lexicons proving the mechanism ×3 scripts; REAL license-clean lexicon
  sourcing is NETWORKED → operator list with vetting criteria (license, provenance,
  per-language review). Investigate honestly whether the already-bundled VADER lexicon can
  seed an English-only slice (it is intensity-annotated); if its semantics don't map to
  subjectivity, say so and don't force it.

### S5.3 — The IR gold-set BUILDER (unblocks lemmatization + BM25F, both measure-gated)
The gold set must be maintainer-made — so make making it trivial: a Settings → Diagnostics
grading surface that (a) samples real queries from the corpus (top keywords + omnibar
history if stored — check what exists; never invent queries), (b) shows the live results
for each, (c) lets the maintainer grade 0/1/2 per result with keyboard-speed UX, and
(d) writes the exact `ir_eval` gold-set JSON (`load_gold_set` format, validated on save).
Include a "coverage meter" (queries graded per language/axis, n shown). The A/B endpoint +
harness already exist — this closes the last gap in the measure-before-trust loop for
`OO_FAMILY_LEMMA` and the BM25F default.

### S5.4 — `lemma_preview` surfacing polish
Make the existing lemma-conflation preview visible where the decision will be made (the
Diagnostics panel next to the gold-set builder): the candidate merge groups, would-merge
counts, denylist affordance (a wrong merge → a `_MISLEMMA_DENYLIST` entry the maintainer
can note). The default STAYS off — this is the review instrument, not the flip.

### S5.5 — Small decided items
- **S&P 500 reclassification — VERIFY-ONLY:** already done (`idx_sp500` in
  `configs/index_feeds.yml`, the commodities board excludes `index` symbols per the recorded
  ruling in `src/api/markets.py`). Confirm + flip the stale ROADMAP ⬜ row; build nothing.
- **`int` country curation seam:** the "Global" region shipped (B12) but individual
  International sources still lack `country: int` — add the deterministic, hand-review-able
  candidate list (an Explore agent over the catalog for unambiguous transnational bodies —
  UN/EU/WHO-class names only; propose in a reviewable file, apply only the unambiguous ones,
  per the wrong-country-is-worse-than-none rule).
- **Retention decision memo check:** S3 wrote it; verify the instrumentation it asked for
  exists so the maintainer's next export carries the numbers.

### S5.6 — (stretch) Secondary-source `cited` provenance slices (forward-pull from S6.1b)
Content-provenance S1→S3 was found ALREADY SHIPPED (S6.1 verify-marks it) — the live
forward-pull target is S6.1b: the `cited` provenance remaining slices (the background
citing-resolve job at scale, denormalize `citing_source_id`, surface the citing trail, wire
the dormant `external_sources`). Pull it forward only if your queue is genuinely done;
S6.1b carries the matching "if S5 didn't take it" guard.

## Explicitly NOT yours
Grading the gold set, fetching USGS/lexicon data, the keyword-log export (operator) ·
backlog features beyond S5.6 (S6) · anything networked.

## Closeout
Ledger rows + ROADMAP flips (§5 outcome board: 3 and 9 → built-awaiting-data) + CARRY-OVER
for S6, and the OPERATOR list: the USGS fetch, lexicon sourcing/vetting, and "grade the
gold set" (with the builder now one click away).
