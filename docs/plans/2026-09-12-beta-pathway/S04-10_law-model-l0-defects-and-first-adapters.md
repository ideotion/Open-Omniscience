# S04-10 — Laws: the metadata model, the L0 defects, the first bulk adapters · 0.4, `RELEASE_0.4_GATE.md` row Q

> **Scope:** `src/law/` (model, adapter framework, the CLML adapter, track, corpus, coverage, catalog),
> `src/api/law.py` and the law reader, `configs/legal_sources*.yml` (new fields, no order chosen), `law.db` on
> S04-08's substrate, the vetting-board tooling, `pyproject.toml` (`[pdf]` into the default install). NOT:
> the adapter order or the first managed dataset (Q925 ⛔ PENDING); the evolution surface or the reader's
> language switch (0.5, S05-07); breadth (0.6, S06-02); subnational law (Q903 is a recorded CONFLICT); bills /
> drafts (post-beta, S09-01 backlog); case law (Q902's (e) not chosen).
> **Implements:** Q107, Q901 (a, b, c + note), Q902 (a, b, d + note), Q904, Q905, Q906, Q907, Q908, Q909,
> Q910, Q914, Q915, Q917, Q919, Q921, Q922, Q923, Q924, Q925 ⛔ (PENDING — stop at the seam), Q927.
> **Gated on:** S04-08 (substrate, `law.db`, lanes, the synthetic jurisdiction); S04-05 (the alpha-3 display
> rule); live checks need row V's allowlist or the maintainer's machine; the vetting board is the operator step.
> **Sequencing:** the L0 defects FIRST (Q917), then the model, then the framework + CLML; the board runs in
> parallel; S1–S4 land before S05-07 can exist.

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
own section for those questions (§10 — its VERIFIED context and SEARCH-VERIFIED open-data facts; §2 for
Q107). Grep the tree before building anything — the sheet's anchors were verified at `main`@`bebcef4` on
2026-09-12 and may have moved; this brief re-checked them at `7ca142e`.

## 1. The rulings this slice implements — verbatim, by ID

- **Q107** — **(a)** «0.4: the metadata model + the L0 defects + the first bulk adapters; 0.5: the evolution
  surface; 0.6: breadth to the language coverage floor (R15); 0.7–0.8: the rest of the world + subnational.»
  [0.4; 0.5 = S05-07; 0.6 = S06-02; 0.7-0.8 = S07-03 / S08-02]
- **Q901** — **(a)** «An official translation by the issuing state or its designated body» + **(b)** «Also
  translations published by intergovernmental bodies» + **(c)** «Also any government's translation of
  another state's law» — NOTE (verbatim): «all of it, each translation should be accessible with their own
  rich metadata and individually tracked for changes, same as the official laws, with links to the other
  existing translations and to the original untranslated text»
- **Q902** — **(a)** «Constitutions, statutes and codes (consolidated).» + **(b)** «Regulations, decrees,
  ordinances (executive instruments).» + **(d)** «Treaties and international instruments» — NOTE (verbatim):
  «include to add c (bills and drafts) to the post beta» [c recorded for post-beta (S09-01 backlog)]
- **Q904** — **(a)** «Act / code level by default; per-provision rows for sources that arrive pre-split (LEGI,
  CLML, USLM, e-Gov XML, EUR-Lex Formex).»
- **Q905** — **(a)** «Point-in-time consolidated versions with `valid_from` / `valid_to` (the
  legislation.gov.uk and Légifrance model); an observed snapshot without official dating becomes a version
  dated by observation and labelled so.»
- **Q906** — **(a)** «Akoma-Ntoso-lite: document → versions → provisions with stable addresses, plus a
  metadata block (ELI / CELEX / ECLI / act number, issuing body, dates, status, language, translation
  provenance, licence); one adapter per source format (CLML, LEGI XML, USLM, e-Gov XML, Formex/HTML,
  gesetze-im-internet XML, Akoma Ntoso itself where a portal serves it); text-only sources fill the same
  model with one provision.»
- **Q907** — **(a)** «Confirm.» (the sheet's proposed field list, §10)
- **Q908** — **(a)** «One document identity (CELEX/ELI), N language versions aligned by identity — no ring
  needed; the reader offers the language switch; cross-language search finds it through any version.»
  [identity in 0.4; the reader's language switch = S05-07]
- **Q909** — **(a)** «Bulk open data first wherever it exists (LEGI, legislation.gov.uk, gesetze-im-internet
  XML, e-Gov API, US Code XML + govinfo, Canada's XML, Austria's RIS, Portugal's DRE API, Spain's BOE open
  data, Brazil's LexML), then enumeration adapters (crawl an index politely), then gazette feeds for countries
  with neither.»
- **Q910** — **(a)** «Treated as key-gated → excluded under V1-2; EU law comes through the open per-document
  API, the Cellar SPARQL endpoint and the weekly public RDF bulk.»
- **Q914** — **(a)** «Confirm the five (1–2 in 0.4 on the small corpus, 3–5 in 0.5).» [1-2 in 0.4; 3-5 =
  S05-07] (1 per-provision diff timeline · 2 amendment velocity per jurisdiction over time)
- **Q915** — **(a)** «Daily for gazettes and bulk deltas; weekly for consolidated portals without deltas;
  on-demand for a document the user opens; every fetch within the adaptive per-pass budget and the host's
  politeness.»
- **Q917** — **(a)** «Confirm, in 0.4 before anything else in this section.» (the sheet's L0 defects: the
  reader shows `latest_text` with a version selector; diffs against the previous revision, the baseline diff a
  derived view; the adapter's three dates persisted)
- **Q919** — **(a)** «Each law authority is a `Source` row with `source_type="law"`, so the Sources tab,
  coverage and qualification see it like any other source.»
- **Q921** — **(a)** «Declare `counts_documents` per official count so the coverage diagnostic can divide
  where units are commensurable and refuse where not.»
- **Q922** — **(a)** «Yes: 63 of 275 sources are PDF-only.»
- **Q923** — **(a)** «Run it as the 0.4 law operator step.» [operator step]
- **Q924** — **(a)** «Yes: each source carries `verified: live | fixture | unverified` with a date; the UI
  shows it.»
- **Q925** ⛔ — [PENDING — blank on a ⛔; STOP at the seam] «Adapter order and the first managed dataset (was
  Q65)»: no letter, no note; nothing is defaulted — the framework + the existing CLML adapter only.
- **Q927** — **(a)** «Recorded per document (OGL, Licence Ouverte 2.0, Japan's Standard Terms, the EU reuse
  notice, US public domain, …), shown in the reader, and stated at every export point (Q1008); a source whose
  terms forbid redistribution is excluded under V1-3.»

**Register round 2026-09-15 (L6):** «Promote [pdf] into the default» — `[pdf]` joins the default install
(`pyproject.toml`); both venv profiles re-verified when deps change; the coverage report's «without [pdf]» wording
is retired in the same PR.

**RC round 2026-09-15 — BLANK (0 of 22 `ANSWER` lines carry a letter); §0's blank rules applied, nothing resolved.** Nothing in this slice moved: L6 («Promote [pdf] into the
default») is a NEW RULING with no CONFLICT and was never an RC question, so `[pdf]` still joins the default
install, both venv profiles are still re-verified per the deps ritual, and the coverage report's «without
[pdf]» wording is still retired in the same PR. The adapter ORDER (Q925 ⛔) remains PENDING for its own
reason, unrelated to this round.

## 2. Where this stands in the tree — the staleness guard, with anchors

- Sheet §10 (VERIFIED): 51 curated + 226 generated sources; 24 documents → 23 registrable `LawDocument` rows
  on a fresh install; only en, pt, de, fr have a tracked document; no enumeration anywhere (100 rows carry an
  unfetched `enumeration_url` — 107 such LINES in `configs/legal_sources_generated.yml` today, 0 in
  `legal_sources.yml`; lines are not rows); one adapter, CLML, never run on a fetched document;
  `diff_provisions` has no caller (only its definition, `src/law/adapters/diff.py:133`); `LawRevision.full_text`
  written at `src/law/track.py:221` / `:342`, read nowhere in `src/api/law.py` or `src/law/corpus.py`; the
  reader renders `doc.baseline_text` at `src/api/law.py:417`; `jurisdiction` is `String(8)` at
  `src/database/models.py:2244`; `[pdf]` is an optional extra at `pyproject.toml:165` — all grep-verified.
- The board: `docs/product/LAW_VETTING_BOARD.md` reads "44 rows need a decision out of 277 catalog sources
  (catalog `as_of` 2026-07-17)", generated by `scripts/law_vetting_board.py`, re-derived by
  `tests/test_law_vetting_board.py`. The catalog reads `gazette_feed_verification.status` at
  `src/law/catalog.py:97–155`; Q924's `verified:` tier is absent from `configs/legal_sources*.yml`.
  `src/law/coverage.py:92` reads `official_count` and REFUSES to divide (`:26`, `:120`, `:332`);
  `counts_documents` exists nowhere; `Source.source_type` is `String(50)` default `"news"` at `models.py:426`
  and no `"law"` value is written anywhere. The CLML adapter's dates: `src/law/adapters/clml.py:123`,
  `:207–223`; the fixture `tests/fixtures/law/example_act.clml.xml` + `PROVENANCE.md` — grep-verified.
- Open-data facts (sheet, SEARCH-VERIFIED): legislation.gov.uk XML by `/data.xml`, OGL; LEGI / KALI / JORF
  under Licence Ouverte at `echanges.dila.gouv.fr` (the daily-delta structure FROM MEMORY — confirm before
  building on it); the e-Gov Law API GET, no key, XML; Cellar SPARQL + weekly RDF bulk; the EU-Login dump is
  account-gated; EuroVoc "one result says CC0 (confirm)". Every priority portal is egress-blocked (Q114).

## 3. Slices — what to build, in order

### S1 — The L0 defects, before anything else (Q917)
- **What:** the reader shows `latest_text` with a version selector (today `baseline_text`); diffs run against
  the PREVIOUS revision, the baseline diff kept as a derived view (`diff_provisions` gets its first caller);
  the adapter's three dates persisted. Reproduce each defect on a two-revision fixture, then pin the fix.
  **Acceptance:** the L0 fixes have tests (gate), mutation-checked; the reader Chromium-verified.

### S2 — The Akoma-Ntoso-lite model in `law.db` (Q906, Q907, Q905, Q904, Q908, Q901 + note, Q902, Q927)
- **What:** document → versions → provisions with the Q907 block in `law.db`; Q905's observed-snapshot versions
  LABELLED so (×12); Q904's granularity; Q908's one identity with N language versions AND the Q901 note —
  each translation its OWN tracked document with rich metadata and provenance (original / official
  translation by X / intergovernmental body / another government), linked to the other translations and the
  original; treaties under `INT`; Q927's licence recorded per document, shown in the reader, stated at export
  through S04-03's Q1008 hook, redistribution-forbidding sources excluded (V1-3); jurisdiction stored alpha-3
  + level in the new block (the legacy `String(8)` column is S04-05's / 0.5's); bills and drafts in the S09-01
  backlog only. Full skeptic matrix. **Acceptance:** the synthetic jurisdiction exercises versions +
  provisions end-to-end (gate); a fixture translation links both ways and is tracked as its own document.

### S3 — The adapter framework and the CLML adapter — STOP at Q925 (Q906, Q909, Q910, Q915, Q919, Q921–Q924)
- **What:** one adapter per source format; three declared source classes (bulk / enumeration / gazette
  feed); text-only sources fill one provision; Q915's cadence inside the adaptive per-pass budget on S04-08's
  law lane; fed ONLY by the CLML adapter re-targeted to the model; the EU open paths recorded as allowed, the
  EU-Login dump excluded as key-gated, no EU adapter built; each authority a `Source` row with
  `source_type="law"` (a catalogue-to-Source migration under the skeptic matrix, domain-keyed — Q1102's feed
  key is 0.5); `counts_documents` per official count with a validator so `coverage.py` divides where
  commensurable and refuses where not; `verified: live | fixture | unverified` + date per source, shown in the
  UI and read by the board script; `[pdf]` in the default install (`pypdf` into core; both venv profiles;
  the registry rule if a pin changes). **Acceptance:** the CLML fixture round-trips into the model and the
  reader shows its latest text with the licence line (gate); a second adapter fits without code changes but
  none is added; the coverage diagnostic divides with `counts_documents` and refuses without.

### S4 — Analytics 1–2 on the small corpus, and the live half (Q914)
- **What:** the per-provision diff timeline and amendment velocity per jurisdiction — counts with method +
  caveat + n, sparse → bars (invariant #16), never a verdict. The live half: a fetched CLML document
  round-trips through S3 only when `www.legislation.gov.uk` answers an HTTP status from the sandbox (row V) or
  on the maintainer's machine; through the one consented path, refused under the kill switch by NAME.
  **Acceptance:** fixture counts; `not-measurable-here` for the live half until the probe answers.

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), each run separately with its exit code captured; ratchet numbers
from `ci.yml` (470 / 231 today); `node --check` on touched script blocks; the three i18n gates for every new
string (version labels, "dated by observation", licence lines, the verified tier, provenance); the whole-tree
guard set after every file addition; the full skeptic matrix on S2 and the Source migration (a document with
no official dates never gets an invented one; a redistribution-forbidding source never enters);
mutation-check every guard by name; `tests/test_law_vetting_board.py` re-derives the board after the new
fields; the consent fixture for the live half (engage airplane mode first); the Chromium click-through
record (Q1128 = a) of the reader (version selector, licence, provenance, verified tier) in en / fr / ar; the
`shipped.csv` numstat + duplicate scan.

## 5. Operator steps

1. **The 44-row vetting board (Q923):** fill the Decision column on the maintainer's machine, re-run
   `scripts/law_vetting_board.py`, commit the regenerated board — the run's report is the gate's artifact.
2. Live adapter checks on the maintainer's machine until row V's allowlist lands (`not-measurable-here`).
3. The click-through of the reader surfaces (Q1128 = a).
4. **Q925 ⛔:** the adapter order and the first managed dataset — recorded in `OPEN_QUEUE.md` and
   `RULINGS_INDEX.md` in the turn it is given; until then S3 stops at CLML.

## 6. What this slice may not decide

- **Q925 ⛔** — nothing defaulted, no second adapter. **Q903 (CONFLICT)** — subnational timing, recorded both
  ways, never picked; nothing subnational built.
- **Q901 note vs Q908** — if they do not compose cleanly the PR body states the tension and the shape chosen;
  the maintainer's word settles it. **Q913 (topics)** — not in this slice's JSON; read it before storing them.
- **Q1008** — S04-03 states the licence at export; this slice only records it. **FROM MEMORY / confirm:**
  LEGI's daily-delta structure; EuroVoc's licence.
- **S04-12's Q1101** — whether law-authority `Source` rows ever enter the press trial-fetch pipeline is open;
  the PR body states how they are kept apart, or not.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.4_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every ruling in §1 in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
