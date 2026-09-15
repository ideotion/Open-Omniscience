# S06-03 — Wikipedia: the coverage report and located data · 0.6, `RELEASE_0.6_GATE.md` row D

> **Scope:** the Wikipedia lane (`src/wiki/`, on the 0.4 row O substrate — S04-09's stream and HOT tier,
> S05-06's WARM tier and tail walk), the Living sources view, the all-diagnostics bundle
> (`src/api/diagnostics.py`), the local OSM address index of S05-04 (Q820), the map's Places layer
> (S04-09 steps 1–2, S05-04 step 3), the press place extractor (`src/timemap/locextract.py`). Must NOT
> touch: dumps (R12 rules them out), the tail-walk budget (S05-06), the address index itself (S05-04 owns
> it), any external geocoder (Q820: never).
> **Implements:** Q723. Consumes, as the gate row names them: Q108, Q819 · step 4, Q820.
> **Gated on:** S04-09 (the lane and the ≥ 72 h run that gives the counters), S05-06 (WARM + the walk),
> S04-08 (the Living sources view and the per-kind diagnostics member), S05-04 (the address index of the
> user's countries), S05-03 (the Place entity), S04-01 (the host list — the Wikipedia Action API is one of
> the hosts the sheet's §11 context says `docs/SECURITY.md` omits).
> **Sequencing:** last of the 0.6 breadth rows; the report reads the lane's OWN counters, so it renders
> honestly (zeros with the reason) before the operator run and closes after it.

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
own section for those questions (§8 Wikipedia, and §9 for Q819/Q820: the verified context and the option
lists). Grep the tree before building anything — the sheet's anchors were verified at `main`@`bebcef4` on
2026-09-12 and may have moved.

## 1. The rulings this slice implements — verbatim, by ID

- **Q723** — **(a)** «(a) Per edition: pages seen / edition total (from `siteinfo` statistics), full-text
  share, last event time, gap history — in the Living sources view and the diagnostics bundle.»

Named by the gate row, quoted from the sheet (S04-09 / S05-04's JSON; consumed, not re-decided):
- **Q108** = (a) «0.4: the stream (metadata for every edit, all twelve editions) + HOT full text; 0.5: WARM +
  the tail walk under budget; 0.6: the coverage report per edition.»
- **Q819** = (a) «Confirm the order (1–2 in 0.4/0.5 with the wiki lane, 3 in 0.5, 4 in 0.6).» — step 4 =
  free-text addresses in articles and wiki infoboxes → the local OSM address index (Q820).
- **Q820** = (a) «Yes, for the countries the user ingested, disclosed ("addresses outside your OSM countries
  are not located"); never an external geocoding service.»

## 2. Where this stands in the tree — the staleness guard, with anchors

- VERIFIED (sheet §8 context, `src/wiki/`, 13 files): nothing is watched by default; `list=recentchanges`
  has a client and no consumer; no EventStreams anywhere; three Wikimedia hosts through `guarded_session`,
  the bot UA (`client.py:21`), `maxlag=5`, a 1.0 s per-process interval; robots.txt is not consulted for
  API/dump endpoints by design (`fetcher.py:173–175`). S04-09 and S05-06 replace most of this — re-grep for
  what landed before building on any of it.
- SEARCH-VERIFIED (sheet §8, September 2026 unless noted): article counts en 7.24 M · de 3.15 M (2024) ·
  fr 2.75 M · es 2.13 M · ru 2.11 M · zh 1.54 M · ja 1.51 M · ar 1.33 M · pt 1.18 M · id 0.79 M · bn 0.19 M
  · hi ≈ 0.17 M (older) — ≈ 24 M across the twelve; up to 50 titles per request, serial. These are the
  order of magnitude the "edition total" column will show; the report reads the live `siteinfo` figure,
  never these.
- grep-verified in this brief: `grep -rn -i siteinfo src/` — nothing: the `meta=siteinfo` statistics read
  is new; `src/wiki/client.py` (`WikiClient`, `_get` at `:59`, `fetch_recentchanges` at `:81`) is where it
  belongs. `src/wiki/languages.py:223` `UI_LOCALE_CODES` names the twelve editions. `src/api/wiki.py:491–507`:
  the reader's lexical strip peels templates and infoboxes away — the infobox address extractor must read
  the STORED wikitext before that strip, never the rendered text. `src/api/diagnostics.py:3489`
  `debug_bundle` is the all-diagnostics bundle the member joins. `src/timemap/locextract.py` and
  `src/catalog/cities.py` carry the press-side place path (R17 step 3); `configs/cities.yml` is absent
  (sheet VERIFIED: only the 2 KB sample). `ls src/versioned` — absent (0.4 row O, OPEN).

## 3. Slices — what to build, in order

### S1 — The per-edition coverage report
- **What:** for each of the twelve editions: pages seen (the lane's own counter) / edition total (the
  edition's `siteinfo` statistics, read through the lane's transport under the one consent, its as-of
  stored), full-text share (HOT + WARM of the pages seen), last event time (the stream's last event), gap
  history (the substrate's gap detection: every gap with its start, end and reason). Rendered in the Living
  sources view and written as a diagnostics bundle member; the row closes on the numbers READ BACK from that
  member. A young install's small share renders as-is (the 52-of-77 Observatory precedent); a lane that has
  never run renders zeros with "no run yet", never a fabricated share; an edition whose `siteinfo` read
  failed shows the last stored total with its date and the failure named (an airplane refusal is named as
  such — #14e's corollary).
- **Why (ruling):** Q723 = a; Q108 = a; anti-capping and the gap-is-a-gap rules (base working mode §7).
- **Acceptance:** the report renders for all twelve editions from the lane's counters; the bundle member
  round-trips the same numbers; the `siteinfo` host / purpose line is in `docs/SECURITY.md` and the hover in
  the same diff (Q1001/Q1002) if S04-01 did not already list the Action API for this purpose.
- **May not decide:** a coverage bar per edition (V1-6, Q1017: measured first); the V1-9 "one full edition"
  choice (the report shows which edition is closest; the maintainer picks).

### S2 — R17 step 4: free-text addresses onto the map
- **What:** a pure, fixture-tested address-candidate extractor over article text and over the stored
  wikitext of infobox fields, resolved ONLY against S05-04's local OSM address index of the user's ingested
  countries; the disclosure "addresses outside your OSM countries are not located" visible wherever a
  located datum or its absence is shown, ×12; provenance in the hover (which article or page, which
  infobox field, which OSM object, the extract vintage); the located datum joins the map's Places layer with
  its provenance class. Never an external geocoder; never a guess for an address the index cannot resolve
  (an unresolved address is counted, not placed).
- **Why (ruling):** Q819 = a (step 4 in 0.6); Q820 = a; invariant #17 (the hover carries the long form).
- **Acceptance:** the row's "a located address from a wiki infobox appears on the map with its provenance
  in the hover"; the negative-space fixture (an address in a country not ingested · a string that only looks
  like an address · an infobox with no address field) yields no point and the right counter.
- **May not decide:** which languages' address grammars the extractor covers (state the covered set; the
  rest is a recorded gap); whether a located wiki address becomes a Place entity (S05-03 owns the entity).

### S3 — The located-share counters
- **What:** the report gains "addresses found / located / outside your countries" per edition and per
  press lane, feeding K8's located-share (`src/monitoring/kpi.py` K8, `target: pending-ruling-V1-6`).
- **Why (ruling):** the vertical pattern step 8; Q1017 (a resolver ships before any bar).
- **Acceptance:** the numbers appear in the bundle member; no bar is set.
- **May not decide:** the K8 bar.

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), separately, exit codes captured. Plus: `node --check` on touched
script blocks; the three i18n gates (the report's column labels, the gap reasons, the "no run yet" and
"outside your OSM countries" disclosures, the named refusal); the whole-tree guard set; the parser skeptic
matrix for the address extractor (negative-space lens mandatory; mutation-check each guard by name); the
consent fixture — the `siteinfo` read refused under the kill switch with the named refusal,
`tests/test_network_consent.py::test_no_new_socket_capable_importers` (grep-verified) green; the Chromium
click-through record (Q1128 = a): the Living sources view's twelve edition rows, the bundle member opened
from the diagnostics surface, the map with one located infobox address and its hover — in `en`, `zh`, `ar`
(RTL), `hi`; then the maintainer's pass.

## 5. Operator steps

1. The ≥ 72 h lane run of 0.4 row P on the maintainer's machine, so the counters exist (before it, the
   report shows "no run yet" — that is the honest state, not a failure).
2. One OSM country ingested (S05-04's operator step), so the address index exists for at least one country.
3. The click-through pass on the surfaces in §4, including the located-address hover.

## 6. What this slice may not decide

- **Q1009 ⛔** (the storage round-2 rows) bounds the tail walk's depth (0.5 row F); the report states the
  depth the walk reached — it does not assume a store that is not ruled.
- **Q701 ⛔ = c** is ruled (stream + the `allpages` walk); dumps stay out (R12) — nothing here reads one.
- **Per-edition edit rates** are FROM MEMORY in the sheet — the report measures its own rates; nothing is
  built on the remembered figure.
- **Address grammars per language**, **the Place-entity question**, **the K8 bar**: open, as §3 says.
- **Which edition is "the one full edition" of V1-9**: the maintainer's, from this report.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.6_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every ruling in §1 in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
