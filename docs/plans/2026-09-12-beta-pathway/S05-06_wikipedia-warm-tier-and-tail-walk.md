# S05-06 — Wikipedia: the WARM tier and the `allpages` tail walk · 0.5, `RELEASE_0.5_GATE.md` row F

> **Scope:** the Wikipedia lane of 0.4 row P on 0.4 row O's substrate (`src/wiki/` today: `client.py`,
> `mediawiki.py`, `track.py`, `corpus.py`), the WARM tier ingest under the per-edition daily budget, a new
> `allpages` walker (50 titles per request, serial, per-edition coverage counters, a resumable cursor), the
> walk's fetch history written to 0.4 row K's fetch-history member, transport per the user's setting (Tor
> included), analytics 4–5, the budget surface's growth line. Must NOT build: a dump baseline (R12; Q701 (b)
> rejected), the Phase-C store (Q1009 ⛔ PENDING), the coverage REPORT per edition (0.6, S06-03), Q727's gap
> fallback (0.4), any Tor → clearnet downgrade.
> **Implements:** Q701 ⛔ = c (answered; its NOTE is a cross-cutting ruling built in S04-04), Q722 = b,
> Q1009 ⛔ (PENDING — stop at the seam); via the gate row: Q707 (WARM / COLD), Q712 · 4–5, Q108, Q727.
> **Gated on:** 0.4 row O (`wiki.db`, the substrate, the fixture edition); 0.4 row P (the stream, HOT, the
> budget wizard); 0.4 row K (the fetch-history member + its trust toggle); the operator's run and transport
> choice; Q1009 ⛔ for full depth.
> **Sequencing:** after 0.4 rows K, O and P; the walk starts once WARM exists; the run closes the row.

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
own section for those questions (their verified context and option lists). Grep the tree before building
anything — the sheet's anchors were verified at `main`@`bebcef4` on 2026-09-12 and may have moved.

## 1. The rulings this slice implements — verbatim, by ID

- **Q701** ⛔ — **(c)** «(c) Stream-forward plus a slow `allpages` walk for the tail, batched 50 per
  request, serial, under the storage budget (Q707), coverage reported per edition.» — NOTE (verbatim):
  «!!!IMPORTANT NOTE!!!: we need to incorporate EVERY page request and download and history in backups so
  that a fresh install with an old backup doesn't re-downloads the same pages over and prioritizes other
  downloads / fetches, THIS IS TRUE NOT ONLY FOR WIKIPEDIA BUT FOR EVERYTHING DOWNLOADED WITH THE APP, web
  fetch/web scrapping history should be backed-up, and at install and import, users should be given the
  choice to trust or not the history with a "trust the backup scrapping history" toggle» [placement: the
  walk is 0.5 (Q108); the NOTE is a cross-cutting backup ruling built in S04-04 — this slice WRITES to that
  member and honours the toggle; it does not build a second history. The reason dumps are out, which the
  question asked for as a NOTE, was not given — it stays unstated here.]
- **Q722** — **(b)** «(b) Everything follows the transport setting, including the walk over Tor.»
  [placement: applies to the stream from 0.4 too]
- **Q1009** ⛔ — PENDING — blank on a ⛔ (the storage round-2 rulings, register C4, rows 3–6: blob-store
  dedup · pack AEAD OOENC2 or `age` · keyed-HMAC blob addressing + opaque pack names · the sqlite3mc
  benchmark trial); STOP at the seam [placement: blocks the Phase-C store the tail walk needs at scale].
- Carried by the gate row: **Q707 = (a)** «Three tiers under a per-edition daily budget the first-run wizard
  sets (default proposed: 20 GB total, published): HOT = pages the corpus already mentions, tracked pages,
  and the pageview top-1,000 (full text + `index_article` on every change); WARM = every other changed page
  (full text, indexed lazily under the daily budget); COLD = the tail reached by the walk (metadata now;
  text as budget allows).» — WARM and COLD are this slice; **Q712 = (a)** «Confirm the five and the order
  (1–3 in 0.4, 4–5 in 0.5).» — 4 cross-edition divergence for one QID, 5 attention (pageviews) versus
  coverage in the press corpus; **Q108 = (a)** 0.5 = WARM + the tail walk under budget.

## 2. Where this stands in the tree — the staleness guard, with anchors

- `src/wiki/` holds `client.py corpus.py dump_index.py dump_sizes.py dumpread.py dumps.py flagging.py
  languages.py mediawiki.py ores.py track.py` (sheet "13 files" VERIFIED; grep-verified `ls src/wiki`).
  `WikiPage(` is constructed only at `src/wiki/track.py:47`; only the latest text becomes an Article at
  `corpus.py:324`; the bot UA `OpenOmniscienceBot/{OO_VERSION} (+https://github.com/ideotion/…)` sits at
  `client.py:21` (sheet VERIFIED; grep-verified `sed -n '45,49p' src/wiki/track.py`, `sed -n '322,336p'
  src/wiki/corpus.py`, `sed -n '19,23p' src/wiki/client.py`).
- The 50-per-request unit already lives in the tree: `src/wiki/mediawiki.py:142–151` "Params for the FULL
  TEXT of specific revisions (batched, <=50 per call)", `revids[:50]`; `client.py:81`
  `fetch_recentchanges(limit=50)` (grep-verified). No `allpages` anywhere (grep-verified in this brief:
  `grep -rn allpages src/` → nothing). No fetch-history member exists yet (grep-verified:
  `grep -rln 'fetch_history\|scrape_history' src/` → nothing — 0.4 row K builds it).
- `src/ingest/tor_throughput.py` — "the per-kind bandwidth ladder + segmented-download math" (grep-verified
  head) — the instrument for Q722's measured throughput per transport. `/api/wiki/languages` at
  `src/api/wiki.py:308`, `/changes` at `:217`, `/pages/{id}/revisions` at `:234` (grep-verified).
- Scale (sheet, SEARCH-VERIFIED): ≈ 24 M articles across the twelve editions (en 7.24 M · de 3.15 M, a 2024
  figure · fr 2.75 M · es 2.13 M · ru 2.11 M · zh 1.54 M · ja 1.51 M · ar 1.33 M · pt 1.18 M · id 0.79 M ·
  bn 0.19 M · hi ≈ 0.17 M, older); up to 50 titles per request, serial. The sheet's ARITHMETIC — ~480 k
  requests, ~5.6 days per pass at 1 request/s on clearnet, 150–250 GB of wikitext at ~10 KB/page FROM MEMORY
  — is a planning figure the row replaces with the measured first-week rate. Per-edition edit rates and
  EventStreams' 7-day retention are FROM MEMORY — confirm before building on them.
- Lesson (`LESSONS.md`, 2026-09-12): a scale claim inherits the fetch granularity it assumed — name the
  per-request unit and where the limit was read before any duration or request count enters a plan.
- 0.4 rows K, O and P are not in the tree at this brief's writing — verify each landed before building.

## 3. Slices — what to build, in order

### S1 — The WARM tier under the daily budget (Q707, Q1006)
- **What:** every other changed page, full text, indexed lazily under the per-edition daily budget the
  wizard set; per-tier counts on the Living sources view; the budget surface's growth line computed from
  MEASURED bytes ("at your current rate this lane grows ~N GB/month"), never a projection without a rate.
- **Acceptance:** the fixture edition of 0.4 row O ingests WARM pages up to the budget and stops, saying so.

### S2 — The `allpages` walker (Q701 ⛔ = c, the Q701 note)
- **What:** per edition, `allpages` batched 50 titles per request (the unit read from the sheet's
  SEARCH-VERIFIED etiquette and `mediawiki.py:142–151`), serial, under the storage budget, a resumable
  cursor per edition; COLD = metadata now, text as budget allows; every page request written to 0.4 row K's
  fetch-history member so a restored install with "trust the backup scrapping history" ON skips fetched
  pages and prioritises the rest, and with it OFF re-fetches; coverage counters per edition (pages seen /
  edition total) read from ONE artifact; a task-manager job with counts, no fabricated ETA.
- **Acceptance:** the fixture walk with the socket guard armed; the fetch-history round-trip (walk → backup
  → restore, trust ON → no re-fetch; trust OFF → re-fetch); the counters artifact.

### S3 — Transport (Q722 = b, Q1014)
- **What:** the walk follows the transport setting, Tor included — it WAITS for the transport the user
  chose and never downgrades; the consent hover declares the lane's transport; the measured throughput on
  each transport recorded through the `tor_throughput.py` ladder.
- **Acceptance:** a fixture proving the walk idles (named reason ×12) rather than switching transport.

### S4 — Analytics 4–5 (Q712)
- **What:** cross-edition divergence for one QID (size, edit rate, existence across the twelve); attention
  (pageviews) versus coverage in the press corpus — counts, n, co-occurrence never causation, `ooChart`
  (invariant #16) with the sparse-bar rule.
- **Acceptance:** both render from real rows of the run (the gate's clause), n shown.

### S5 — The run (operator) and the depth statement (Q1009 ⛔)
- **What:** the walk runs for a stated period on the reference VM inside the budget; with Q1009 blank it
  runs under the EXISTING store and the row states the depth reached — no dedup, no pack format, no keyed
  addressing, no sqlite3mc trial.
- **Acceptance:** the coverage counters and the measured rate per transport in the PR body.

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), each run separately with its exit code captured. Plus: the
consent + named kill-switch refusal fixture; the fixture pipeline with the airplane socket guard armed (zero
resolutions); the negative-space lens — an edition answering fewer than 50 titles, a missing continuation
token, a page deleted mid-walk, a budget already spent — each a recorded gap, never a 0 or a retry storm;
the budget-stop test; the fetch-history round-trip (S2); the whole-tree guard set; the three i18n gates;
the Chromium click-through of the Living sources view and the budget surface in `en` and `ar`, stamped
"Chromium-verified (remote sandbox) · awaiting human UX pass". The run itself is `not-measurable-here`.

## 5. Operator steps

1. Choose the transport (Tor or clearnet); run the lane for a stated period on the reference VM inside the
   budget → the artifact: pages seen / edition total per edition, bytes per day, the measured rate on the
   chosen transport (both transports if the period allows) — `not-measurable-here`.
2. The click-through of the §4 surfaces (Q1128 = a) → the record on the PR.

## 6. What this slice may not decide

- **Q1009 ⛔** rows 3–6 — no default; the walk runs under the existing store and states its depth.
- The reason dumps are out — Q701 asked for it as a NOTE and none was given; it is not to be invented.
- The walk's per-edition ORDER (largest first, UI-locale first, round-robin) — not ruled; proposed in the PR.
- Where the coverage counters live — the Living sources view's own placement (main tab or Home family) is
  0.4 row O's open detail (Q1016's "your call in a NOTE", not given).
- The trust toggle's copy and the member's format are 0.4 row K's; this slice consumes them unchanged.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.5_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every §1 ruling in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
