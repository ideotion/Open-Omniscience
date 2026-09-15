# S05-03 — The entity spine: QIDs, Wikidata items, the Place entity · 0.5, `RELEASE_0.5_GATE.md` row C

> **Scope:** an entity ladder keyed by Wikidata QID (reusing 0.4 row M's three-tier keyword ladder), a local
> Wikidata item cache (labels, descriptions, a claims subset) fetched at etiquette pace through the guarded
> session, a new `Place` entity with `article_mentioned_places` resolving into it, the gazetteer artifact
> (from ingested OSM `place=*` nodes joined to Wikidata) with its registry entry and freshness test, names
> ×12 with the source in the hover. Must NOT touch: the OSM ingest itself (S05-04), the keyword ladder's
> semantics (0.4 row M), the ring generator's cadence (0.4 row M's fix), any export member (Q823 ⛔ — Place
> rows are OSM-derived and stay inside the machine).
> **Implements:** Q415, Q724, Q805, Q818, Q827 (none ⛔, none 🔒); via the gate row: Q819 step 2.
> **Gated on:** 0.4 row M (the ladder); 0.4 row P (`qid` on wiki Articles, Q715; Q819 step 1); 0.4 row H
> (`docs/SECURITY.md` listing the Wikidata hosts); S05-04's first-country ingest for the gazetteer's OSM half.
> **Sequencing:** S1–S3 before S05-04's Places-as-Articles (Q817 needs the Place entity); S4 (the artifact)
> after S05-04's ingest; the operator build last.

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
own section for those questions (their verified context and option lists). Grep the tree before building
anything — the sheet's anchors were verified at `main`@`bebcef4` on 2026-09-12 and may have moved.

## 1. The rulings this slice implements — verbatim, by ID

- **Q415** — **(a)** «(a) The same ladder for entities, keyed by Wikidata QID — this is the 0.5 entity
  spine's first concrete use.»
- **Q724** — **(a)** «(a) In 0.5 (the entity spine): labels, descriptions and a claims subset (P31, P17,
  P625, P571…) per QID the corpus mentions, fetched at etiquette pace, cached locally.»
- **Q805** — **(a)** «(a) Built from the ingested OSM `place=*` nodes joined to Wikidata (population, names
  ×12, QID) at artifact-build time on your machine; shipped with a registry entry and a freshness test.»
- **Q818** — **(a)** «(a) `Place(id = OSM type+id, qid, kind, admin path, names ×12, geometry ref, as_of)`
  with `article_mentioned_places` resolving into it; its body = the Wikidata/Wikipedia description + its OSM
  metadata rendered as metadata; keywords come from that text; it is searchable and indexed.»
- **Q827** — **(a)** «(a) OSM `name:xx` first, Wikidata labels as the fallback, the source shown in the
  hover.»
- Carried by the gate row: **Q819 = (a)** «Confirm the order (1–2 in 0.4/0.5 with the wiki lane, 3 in 0.5,
  4 in 0.6).» — step 2 ("OSM objects tagged `wikidata`/`wikipedia` → the same Place as the wiki page")
  completes here; **R8** (rulings index): automated Wikidata downloads respect ≤ 1 request per 10 seconds.

## 2. Where this stands in the tree — the staleness guard, with anchors

- No `Place` class exists (grep-verified in this brief: `grep -rn 'class Place' src/` → nothing).
  `ArticleMentionedPlace` at `src/database/models.py:1821` (table `article_mentioned_places`, `country`
  `String(2)` at `:1835`) is "a disposable per-article row" (sheet §9 VERIFIED; grep-verified).
- `src/analytics/place_identity.py` — "Place canonicalization by country code", keyed on
  `ArticleMentionedPlace.kind == "country"` (grep-verified head); tests `tests/test_place_identity.py`,
  `tests/test_place_longest_match.py` exist (`ls tests/`).
- The city gazetteer today: `src/catalog/cities.py` (name → lat/lon/country; "a small sample ships") built
  by `scripts/build_city_gazetteer.py` from Wikidata (grep-verified heads) — the "existing networked
  script" Q805 (b) declined; `configs/cities.yml` is absent, only the 2 KB sample (sheet §9 VERIFIED).
- Wikidata reach today: `WDQS_ENDPOINT = "https://query.wikidata.org/sparql"` at `src/catalog/wikidata.py:23`;
  `src/catalog/discover.py` runs it through `guarded_session` (sheet `discover.py:36–41`; grep-verified:
  `sed -n '30,45p' src/catalog/discover.py`); `scripts/generate_wikidata_rings.py` sleeps 0.2 s — fifty times
  faster than R8 (sheet §5 VERIFIED); `docs/SECURITY.md` omits the Wikidata Query Service (sheet §11
  VERIFIED; 0.4 row H adds it). Only click-target links and the guarded WDQS path reach Wikidata.
- The registry template: the `natural-earth-geometry` entry at `configs/external_artifacts.yml:527–537`
  (id · title · kind · description · upstream · license · `pin: {path, sha256}` · refresh · freshness ·
  last_verified; grep-verified) and `tests/test_external_freshness.py`
  (`test_every_as_of_constant_is_registered`, `test_nothing_is_stale` — grep-verified `def` names).
- 0.4 rows M, P and H are not in the tree at this brief's writing — verify each landed before building on it.
- Lesson (`LESSONS.md`, the gazetteer-index entry): an indexed candidate path changes HOW places are found
  and must change nothing about WHAT is found — compare old and new over the whole result structure, and
  report the removed scaling dimension, not a ratio.

## 3. Slices — what to build, in order

### S1 — Entities on the ladder, keyed by QID (Q415)
- **What:** people, organisations and places resolved to a QID through the same three-tier ladder 0.4 row
  M built for keywords — the QID is the identity, the label ×12 comes from S2, the "translated from X"
  grammar is reused; no second ladder, no new tier.
- **Acceptance:** an entity fixture round-trips term → QID → label in two locales; an unresolvable entity
  stays a plain term with no QID (never a guessed one).

### S2 — The Wikidata item cache at etiquette pace (Q724, R8)
- **What:** per QID the corpus mentions — labels, descriptions, the claims subset (P31, P17, P625, P571 …) —
  fetched at ≤ 1 request per 10 seconds through `guarded_session`, under the ONE online consent, refused
  under the kill switch with a NAMED refusal, the host in `docs/SECURITY.md` and the consent hover in the
  same diff (Q1001), transport per the lane setting and never downgraded (Q1014); cached locally with
  `as_of`; a task-manager job showing fetched / pending / refused counts, never an ETA it did not measure.
- **Acceptance:** the consent + kill-switch fixture (the airplane socket guard armed: zero resolutions);
  a clock-driven etiquette test (no two requests closer than 10 s); the refusal string ×12.
- **May not decide:** which Wikidata API serves the items (§6); claims beyond the four named (§6).

### S3 — The Place entity, its body and its names (Q818, Q827)
- **What:** `Place(id = OSM type+id, qid, kind, admin path, names ×12, geometry ref, as_of)`;
  `article_mentioned_places` resolves into it; its body = the Wikidata/Wikipedia description + its OSM
  metadata rendered as metadata; keywords from that text through the real `index_article`; searchable and
  indexed; names `name:xx` first, Wikidata labels as the fallback, the source named in the hover
  (invariant #17); a missing name in a locale says so — never a fabricated one.
- **Acceptance:** a Place opens as a card (row D's clause) with body, metadata and the name-source hover in
  `en` and `ar`; a differential test of the new resolution against `place_identity`'s output (the lesson).

### S4 — The gazetteer artifact with its registry entry (Q805)
- **What:** built from the ingested OSM `place=*` nodes joined to Wikidata (population, names ×12, QID) at
  artifact-build time on the maintainer's machine; a registry entry in the `natural-earth-geometry` shape
  (`license`, `pin.sha256`, `refresh`, `freshness`, `last_verified`); a freshness test; the vintage shown
  wherever the gazetteer resolves a place.
- **Acceptance:** the registry entry with a real sha256 and vintage; the freshness test green.

### S5 — Q819 step 2 closed
- **What:** a press article's mentioned place → the gazetteer → a Place that a wiki page with the same QID
  (0.4 row P's `qid`) also resolves to.
- **Acceptance:** the gate's closing demonstration on the synthetic corpus + 0.4 row O's fixture extract.

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), each run separately with its exit code captured. Plus: the
consent and kill-switch fixtures (S2) with the named refusal ×12; the etiquette clock test; the
negative-space lens — an unknown QID, a Place with neither `name:xx` nor a label, an article with no
resolvable place — each an honest gap, never a 0 or a guess; the differential test (S3); the registry and
freshness tests (S4); the whole-tree guard set; `node --check` on touched scripts; the three i18n gates; the
Chromium click-through of a Place card and its hover in `en` and `ar`, stamped "Chromium-verified (remote
sandbox) · awaiting human UX pass".

## 5. Operator steps

1. After S05-04's first-country ingest, the networked gazetteer build on the maintainer's machine → the
   artifact, its sha256 pinned in the registry, `last_verified` set (the artifact + the registry diff).
2. The click-through of the Place card and hover (Q1128 = a) → the record on the PR.

## 6. What this slice may not decide

- Which Wikidata API serves labels/claims (the WDQS path in the tree, or the entity endpoint — a new host
  goes to `docs/SECURITY.md` + the hover in the same diff); the claims subset beyond P31, P17, P625, P571.
- The `kind` vocabulary and the `admin path` encoding of `Place`; which database file hosts the Place table
  (`osm.db` per Q719, or the corpus — the Article body lives in the corpus); whether it rides the backup.
- Q823 ⛔: Place rows are OSM-derived — no export member, bulletin line or evidence ZIP until ruled; the
  gazetteer artifact shipped in the repository is OSM-derived too — its registry `license` line carries the
  attribution, and whether Q823 reaches repo-shipped artifacts is recorded as a question, not decided.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.5_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every §1 ruling in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
