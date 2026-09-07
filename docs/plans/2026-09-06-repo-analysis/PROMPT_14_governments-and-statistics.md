# Prompt 14 — Governments, official statistics, and the bloc lens

> **Scope:** `src/stats/`, `src/catalog/blocs.py`, `src/api/governments.py`.
> **Gated on:** F1 ⛔ (S1, S5, S6 need egress), G1 (key-gated sources), G4 (IPCC), G5 (the agency research
> pass).
> **Sequencing:** independent. S2, S3 and S4 are buildable without egress.

## 0. Working mode

Read `_WORKING_MODE.md`, then the CLAUDE.md **"FIELD FEEDBACK 2026-08-07"** entry with its 47 rulings and the
2026-08-20 execution board, then `docs/design/INTERNET_SESSION_PROMPT_*.md`.

**Rule 5 of that prompt is the one that matters most here and it was learned expensively:** read the URL you
were **served**, never the one you asked for. A research pass asked for `…&page=2`, was served page 1 with no
error three times over two endpoints, and was one check away from publishing *"page=2 returns page 1,
pagination is broken at the publisher"* — a confident, wrong, undetectable claim about someone else's API
that would then have justified "fixing" our own working pagination.

## 1. What shipped, so it is not rebuilt

Aggregates have their own surface with `classify_ref_area` deciding what appears where, asserted in both
directions. Two-country side-by-side with per-side years. Every aggregation strategy side by side, refusing by
default on incomplete coverage with an explicit publish-anyway override carrying the missing members **in the
payload**. Membership vintage on every bloc surface. Both lenses (WB-published and computed), never blended,
with intensive indicators refused for summation **at the API**, not merely hidden. One Article per
indicator×country through `index_article`. The suspension-episode model (a list of intervals — Mali has been
suspended twice, so a single `suspended_from`/`suspended_until` pair cannot hold it).

## 2. Slices

### S1 — ⛔ The 36 World Bank indicator codes (one command, on a networked machine)

`scripts/verify_worldbank_indicators.py` checks all 36 catalog codes, refuses the `fetched` tier on a
served-versus-requested URL mismatch, and separates a wrong code from an area that simply does not report it.
It has never been run against the live API. `api.worldbank.org` is `CONNECT`-refused here.

Recorded at the call site and needing the same run: `EN.ATM.CO2E.PC` is at risk against the newer
`EN.GHG.CO2.PC.CE.AR5` — fetch both and compare.

### S2 — SDMX message versions (buildable, but needs one real body)

`parse_sdmx_json` handles one message shape. OECD is SDMX-JSON 1.0 and IMF 3.0; OECD serves both via a
`format` parameter, so **pin, never sniff**. The docstring that said "SDMX-JSON 2.1" named a version that
does not exist (message formats are 1.0 and 2.0; 2.0/2.1/3.0 version the information *model*) and was
corrected — and the correction mattered, because an unmapped message resolved every dimension to nothing and
`series_id or ""` appended the row anyway: a real figure with no country, no indicator and no year, which no
reader could tell from a fact. That refusal is now in place; extending to a second message shape must keep it.

Which dimension sits at which level is decided by the request's `dimensionAtObservation`, not by the concept —
OECD's own documented example passes `AllDimensions` — so `ref_area` and `series_id` must be looked up at
observation level as well as series level.

### S3 — The bloc rosters (G3 — its own networked session)

The registry ships deliberately **empty**: thirteen political blocs with no membership data, because "a
partial roster is more dangerous than none". Membership is time-varying and getting it wrong is undetectable
— BRICS was five members until 2024, NATO gained Finland in 2023 and Sweden in 2024, the EU lost the UK in
2020, so a bloc figure computed with today's roster over a 1995 series is wrong in a way no reader can see.

The acquisition rule that decides the whole task: **the publisher's own page is an interested party for a
membership fact.** One search returned four mutually incompatible states for Saudi Arabia in BRICS, with the
bloc's own page the most confident and the least reliable. A roster page corroborates membership and cannot
settle a contested one; that needs the acceding state's own statement, and where none exists the honest answer
is a permanent `joined: UNVERIFIED`.

Also open: region membership is currently undated (`dates_apply` is `False`, stated, cross-vintage unsafe),
and a country that did not exist in the requested year lands in the coverage gap beside non-reporters —
both need sourced independence and accession dates from the same session.

### S4 — The default strategy, open to overturn

For intensive indicators with no exact weighting, the default view is a plain member mean rather than
population-weighted — a two-line flip in `_default_strategy`, flagged as a judgement call. Note the arithmetic
that makes the alternative defensible: a population-weighted mean of a per-capita indicator **equals**
`Σ numerator / Σ denominator`, the true aggregate rather than an approximation, provided the numerator is
reconstructed and the weight series is real for the same members and year. Gini is refused entirely (pooling
biases it low).

### S5 — G5: `news_url` for the statistics agencies

29 agencies ship with `news_url` **empty**; the directory should reach roughly 150. This is a networked
research pass in the law-batches pattern — never a fabricated endpoint, every row tiered. Without it, enabling
a statistics agency would crawl a dataset portal rather than its newsroom, which is why the field exists.

### S6 — The rest of the operator list

The BRICS Joint Statistical Publication; AfDB and UNECA continental endpoints (the WB lens has **no**
continental-Africa figure at all — "Sub-Saharan Africa" excludes Egypt, Libya, Tunisia, Algeria and Morocco,
which is precisely why both lenses ship); OECD and IMF message-version verification; the two task-2 loose ends
(confirm `page=2` against a cache-disabled request, and read the tail of page 1).

### S7 — PRH-24 and the parser families

A "Registered statistics sources" view was designed and never built. CSV/OWID, JSON-stat/PxWeb and bulk-ZIP
(V-Dem, UCDP) parsers were scoped; verify what `src/stats/bulk.py` already covers before writing any of them.
The revision-anomaly detector over `StatFigure` vintages — flag a new vintage that moves a past official
figure into the tail of its own revision history — is the on-mission kernel here and needs no model.

## 3. Scope fence

Aggregation is indicator-aware: extensive indicators may be summed, intensive ones may **not** — a summed
percentage is a fabricated statistic and must be refused, not greyed out. Declare `extensive` explicitly per
catalog entry, never infer it from a unit string. Always display the spread beside a central figure. Never
average producers; show them side by side.
