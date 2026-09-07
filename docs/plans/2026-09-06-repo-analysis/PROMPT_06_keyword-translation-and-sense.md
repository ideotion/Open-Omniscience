# Prompt 06 — Cross-language keyword search: the remaining slices

> **Scope:** `src/analytics/equivalence.py`, `src/analytics/month_occupancy.py`, the ring corpus,
> `scripts/generate_wikidata_rings.py`.
> **Gated on:** E1 ⏳ (the month-occupancy number, operator), E2 ⏳ (`dumps.wikimedia.org` allowlist),
> E3, E4.
> **Sequencing:** independent. S1 is buildable the moment E1 arrives; S2 cannot start without E2.

## 0. Working mode

Read `_WORKING_MODE.md`, then
`docs/design/KEYWORD_TRANSLATION_DISAMBIGUATION_2026-09-05.md` in full — it is the design of record and it
carries §8b, which is how to READ the month-occupancy number and matters more than the number itself.

Three rulings govern this area and none of them is up for revisiting: **R1** cross-language expansion is on
by default and disclosed; **R2** sense identity is keyed on Wikidata QID; **R2a** that identity is a
**query-time user choice**, never a stored per-mention link — the linker was measured at 0.335 F1 on news
and is out of the plan until a news-domain measurement changes, not merely deferred.

## 1. What shipped on 2026-09-05, so you do not rebuild it

Slice 1 (the ring dictionary read by search, expansion on by default, disclosed, with a refusal for the 91
measured within-language collisions and the per-sense pick over them), slice 3b (both misfiled stoplist
blocks re-filed with a script guard), the Maghrebi calendar ride-along (1/8 → 7/8 forms, with `ماي` withheld
for a within-Arabic collision a language gate cannot separate), and slice 2 — the instrument:
`src/analytics/month_occupancy.py` plus `GET /api/diagnostics/month-occupancy`, riding the bundle, built on
a new `extract_dates_with_spans` seam.

## 2. Slices

### S1 — Slice 3: the date-aware month block (gated on E1)

Eighty-two month forms are globally banned, so the keyword engine cannot see the planet **Mars**, the
**March** on Washington, **Theresa May**, **April Ryan** or **August Landmesser** — not ranked low, absent,
while FTS still finds them in article bodies, so the index and the engine disagree about whether these topics
exist.

The fix is mechanism-matched: drop a month token only where the **date extractor claimed its span**. The
seam exists. What is missing is the number that decides how much this recovers and how many datelines leak
back — and §8b says how to read it: the denominator is unigram occurrences while the ban also kills every
n-gram containing a banned token, so the figure is a **floor** on what is deleted; and a dateline the
extractor misses counts as outside, so it **over-states** what a date-aware block would newly admit. Two
bounds pointing in opposite directions, neither corrected, because correcting either needs a number nobody
has. `by_language` is where the decision lives and `by_token` makes a partial fix decidable.

Requires a re-index. Say so, and size it.

### S2 — Slice 4: the ambiguity map (gated on E2)

Harvest the surface-form → candidate-QID index from the same Wikidata fetch that grows the rings — group
labels and aliases by (normalized string, language), keep groups of ≥2, attach `P31`. The disambiguation-item
route (`P31 = Q4167410`) is a **dead end** and is recorded as one: those items model no concept and carry
sitelinks, not senses. Anyone building this reaches for that QID first.

The one open number is whether an ambiguous-only twelve-language index fits under the 100 MB file limit. The
cost-per-row measurement exists (35.8 bytes gzipped, sorted TSV ⇒ ~2.8M forms per 100 MB, a floor since
synthetic QIDs compress worst). `held_back.ambiguous_language` from the triage proposal — 59,206 terms
existing under several languages — is a free corpus-derived ambiguity map and an input to both this and S1.

### S3 — Slices 5 and 6: coverage (operator-gated)

Ring expansion is a networked run; the 168-seed batch is prepared with its prevetting CSV and runbook. Two
empirical facts recorded before that batch ships, because both cost a run: the generator **OVERWRITES** its
`-o` target with only the current run's rings despite a docstring saying "augments", and the default `-o` is
the live rings file — so always resolve to a temp file and append-merge as a deliberate text splice. And
`nuclear fusion` is a known repeat-offender seed already resolved wrong and dropped once.

Slice 6 is permanently the **inventory** half (R2a), not a linker.

### S4 — Slice 7: the synonym tier (gated on E3/E4)

OMW is refuted as a shipped tier and the refutation is worth keeping: only `omw-en` carries relations at all,
and the translated synsets have already leaked the hypernym in (Spanish `car` contains `vehículo`), so an OMW
synonym tier ships the exact `car`↔`vehicle` failure the caution was written about — unevenly, silently, and
only in the non-English languages. PanLex is disqualified (CC BY-NC-SA 4.0 on the publisher's live licence
page; the CC0 belief traces to a cached 2019 snippet).

That leaves Wiktextract, which needs **E3** — it is a 3.0/4.0 revision mixture and only 4.0 has a declared
one-way path into GPLv3 — and the SKOS thesaurus family (UNESCO, EuroVoc, AGROVOC, IPTC Media Topics), which
needs **E4** because "open access" is not a licence identifier. UNESCO is the interesting one: it covers ru
and ar, which OMW cannot supply at all, and `skos:broader` keeps the hierarchy **outside** the synonym set by
construction — structurally the property OMW was found to lack.

### S5 — The ring lifecycle (buildable now)

Two agreed mechanisms, neither built. First, institutionalise the refresh cadence: the gap-digest →
`--from-log` generate → vet → merge pass becomes a named per-cycle ritual, and `translation_coverage` joins
the KPI board so coverage decay is seen rather than discovered. Second, a `--refresh` mode for the generator:
re-run `wbgetentities` over the already-vetted QIDs, diff the member lists, emit **only the additions** for
review. That absorbs within-concept alias and rename drift (the coronavirus → COVID-19 class) at low vetting
cost, because the QID judgement was made once.

Rings are never pruned — cross-time recall is sacred and a dead concept's ring keeps serving history.

### S6 — Per-language month scoping (the complement to S1)

Recorded as structurally impossible in the obvious place and worth stating so nobody re-proposes it:
`stopwords_extra/*.yml` is language-agnostic by construction, and the real scoped channel is unreachable for
`en` and `fr` because `get_stopwords` tests `language_stopwords` first and those are its only two keys. So
per-language month scoping is a stoplist-**architecture** change, not a data-file edit — and it recovers three
of seven named losses, because `march`/`may`/`april`/`august` are English months in English documents. It and
S1 are complements, not alternatives.

## 3. Scope fence

Do not store a sense against a mention (R2a). Do not add a linker. Do not widen a ring without the
cross-language vetting pass. Do not point the generator at the live rings file.
