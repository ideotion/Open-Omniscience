# S06-02 — Laws: breadth to the coverage floor · 0.6, `RELEASE_0.6_GATE.md` row C

> **Scope:** `src/law/` (`catalog.py`, `coverage.py`, `adapters/`), `configs/legal_sources.yml` +
> `legal_sources_generated.yml`, the law lane on the 0.4 row O substrate, `docs/product/LAW_VETTING_BOARD.md`
> + `scripts/law_vetting_board.py`, a new topic-classification module, the SKOS thesauri as dated
> registry-tracked artifacts, the Living sources law entry and the diagnostics member, `docs/SECURITY.md` +
> the consent hover. Reads `configs/language_countries.yml` through `src/civic/coverage_floor.py`; does NOT
> edit that file's country set. Must NOT touch: the adapter ORDER (Q925 ⛔), the evolution surface (S05-07),
> case law and bills (post-beta), the elections consumer of the floor.
> **Implements:** Q911 [TENSION: the note carries a standing ruling], Q912, Q913, Q930, Q1146. Consumes, as
> the gate row names them: Q107, Q901, Q902, Q908, Q925 ⛔ (blank).
> **Gated on:** S04-10 (the metadata model, the L0 defects, translations as tracked documents, the first
> adapters, the vetting board), S05-07, S04-08, S04-01, S04-05 / S05-02 (alpha-3). Q925 ⛔ blocks only the
> adapter order: breadth is built through whichever adapters exist, and the rest is recorded.
> **Sequencing:** runs alongside rows A, B and D; the live verification of each seed row is the operator's
> and gates every catalogue entry.

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
§10 (Laws) and its §12 block for Q1146. Grep the tree first — the anchors were verified at `main`@`bebcef4`.

## 1. The rulings this slice implements — verbatim, by ID

- **Q911** — **(a)** «(a) Take this as the 0.6 verification worklist» — NOTE (verbatim): «but are we enterly
  missing china ? Also in the UI language ? This must be a mistake I made. We should incororate china and
  chinese support throughout the app. This is important.» [TENSION — the note is a ruling: the OPEN_QUEUE
  head entry (2026-09-15) answers it (`zh` is a UI locale; the seed's `zh` row and the NPC entry exist) and
  records the emphasis as STANDING — zh first-class in every lane, its coverage reported separately.]
- **Q912** — **(a)** «(a) Floor = every country in `language_countries.yml` (official / de-facto / regional
  bases all count, labelled); order = sources serving many countries first (EU, OHADA, UN/WIPO), then by
  population reached.»
- **Q913** — **(a)** «(a) EuroVoc concepts (en/fr/de/es/pt), reached in the other seven languages through
  Wikidata's EuroVoc-ID property (P5437, FROM MEMORY) and the keyword rings; assigned by rules over titles
  and provisions, ≈ where the LLM proposes one.»
- **Q930** — **(a)** «(a) 0.6, as jurisdiction `INT` — the UN Treaty Collection (six UI languages at once)
  and WIPO Lex are the highest-yield multilingual sources on the list.»
- **Q1146** — **(a)** «(a) Adopt EuroVoc + the UNESCO Thesaurus (ar/en/fr/ru/es) + AGROVOC + IPTC Media
  Topics for topic tagging, tied to Q913.»

Named by the gate row (S04-10's JSON; consumed here, never re-decided):
- **Q107** = (a): «0.6: breadth to the language coverage floor (R15)».
- **Q901** = a, b and c — note (verbatim): «all of it, each translation should be accessible with their own
  rich metadata and individually tracked for changes, same as the official laws, with links to the other
  existing translations and to the original untranslated text».
- **Q902** = a, b and d — note (verbatim): «include to add c (bills and drafts) to the post beta».
- **Q908** = (a): one document identity (CELEX/ELI), N language versions aligned by identity; the reader
  offers the language switch. **Q925** ⛔ — blank. PENDING: the adapter order. STOP at the seam.

## 2. Where this stands in the tree — the staleness guard, with anchors

- VERIFIED (sheet §10 context): 51 curated + 226 generated sources; 24 documents → 23 registrable
  `LawDocument` rows on a fresh install; only en, pt, de, fr have a tracked document; **es, ru, ar, zh, ja,
  hi, bn, id have zero**; no enumeration anywhere (100 rows carry an unfetched `enumeration_url`); one
  adapter (CLML); `jurisdiction` a free `String(8)` (S04-10 replaces it — re-grep); every priority portal
  egress-blocked from the sandbox (Q114).
- SEARCH-VERIFIED (sheet §10): EuroVoc covers 24 EU languages (of ours: en, fr, de, es, pt), XML/SKOS, one
  result says CC0 — **confirm the licence before bundling.** FROM MEMORY: P5437 — confirm the property id.
- grep-verified in this brief: `configs/legal_sources.yml:56` NPC (China), `npc.gov.cn`, country `cn`,
  language `zh`; `:67` WIPO Lex, country `int`. `grep -rn -i -E 'eurovoc|P5437|agrovoc|iptc|unesco
  thesaurus|skos' src/ configs/` — nothing: the thesauri and the classifier are new. `src/law/coverage.py`
  (`law_coverage_report` `:215`, `official_enumerations` `:114`) keeps three coverage states apart and
  refuses to divide tracked by enumerated units — extend it, never fork it.
  `docs/product/LAW_VETTING_BOARD.md` (44 rows need a decision out of 277; `scripts/law_vetting_board.py`;
  `tests/test_law_vetting_board.py`) is the board the seed rows join. `configs/language_countries.yml`
  (`as_of: "2026-09-07"`, «clearnet check pending») EXCLUDES territories — Hong Kong and Macau by name —
  while the seed's `zh` row lists both; registry id `language-countries-floor`
  (`configs/external_artifacts.yml:344`, pinned to `src/civic/coverage_floor.py:59`).

## 3. Slices — what to build, in order

### S1 — The floor, the report, the order of work
- **What:** the floor = every country in `configs/language_countries.yml`, all three bases counted and
  LABELLED, read through `src/civic/coverage_floor.py` (one loader, not a copy); `src/law/coverage.py`'s
  report gains a per-floor-country state (tracked / verified-not-yet-tracked / unverified / no eligible
  source), the twelve-language tally, **zh reported separately**, and the floor file's own unverified
  status; the order of work: many-country sources first (EU, OHADA, UN / WIPO), then population reached.
- **Why (ruling):** Q912 = a; Q911 note; Q107 = a; R15.
- **Acceptance:** the report lists every floor country with its state, in the Living sources law entry and
  the diagnostics bundle member; "no eligible source" is a state, never a blank; `zh` is its own row.
- **May not decide:** the floor file's country set (its territory exclusion is a recorded scoping decision).

### S2 — The verification worklist: every seed row verified live before it enters a catalogue
- **What:** each row of the Q911 table (thirteen language rows + `INT`) becomes a vetting-board candidate
  with `verification.status` unverified; a row enters `legal_sources.yml` only after the live check —
  reachability, robots, licence, format — recorded by the operator (§5); the board's outcomes (enable /
  adapter / gap / drop) apply; nothing is scraped around. The `zh` row (flk.npc.gov.cn · Hong Kong
  e-Legislation · Taiwan law.moj.gov.tw · Macau · Singapore zh) is verified and tallied separately.
- **Why (ruling):** Q911 = a; Q901 (a, b, c) for what counts as formally translated; Q902 (a, b, d).
- **Acceptance:** the board regenerates with the seed rows; every catalogue entry added carries its
  verification record; `tests/test_law_vetting_board.py` green.
- **May not decide:** which adapter a verified row gets first (Q925 ⛔).

### S3 — Treaties and international instruments as jurisdiction `INT`
- **What:** the UN Treaty Collection (six UI languages at once) and WIPO Lex as `INT` sources on the lane:
  one treaty in six languages aligned by ONE document identity (Q908 = a), each version its own tracked
  document linked to the others and the original (the Q901 note); the reader's language switch; each host
  consented, in `docs/SECURITY.md` + the hover in the same diff, a named kill-switch refusal, no downgrade.
- **Why (ruling):** Q930 = a; Q902 (d); Q908 = a; Q901 note; Q1001 / Q1002 / Q1014.
- **Acceptance:** the row's "the `INT` lane ingests one treaty in six languages aligned by identity".
- **May not decide:** ILO NATLEX / FAOLEX / EUR-Lex-as-INT beyond what the verification admits.

### S4 — EuroVoc topics and the SKOS family
- **What:** EuroVoc (en/fr/de/es/pt) bundled as a dated artifact with its `*_AS_OF`, registry entry and
  licence line AFTER a ✅ licence fetch; concepts reached in the other seven languages through P5437 (id
  confirmed first) and the keyword rings; assignment by RULES over titles and provisions, the LLM's
  proposals marked ≈ (perception, never judgment); the UNESCO Thesaurus (ar/en/fr/ru/es), AGROVOC and IPTC
  Media Topics adopted the same way, each with its registry entry and licence. A topic is a lens, never a
  verdict; the caveat and the ≈ share visible ×12; measured on a labelled sample.
- **Why (ruling):** Q913 = a; Q1146 = a; the external-artifact registry ritual (CLAUDE.md).
- **Acceptance:** the row's "the topic assignment is measured on a labelled sample with the ≈ share stated";
  `tests/test_external_freshness.py::test_every_as_of_constant_is_registered` (grep-verified) green; the
  SKOS parser's negative-space fixture (an empty scheme · a concept with no label → a gap, never a label).
- **May not decide:** a precision bar for the rules (none ruled); the classifier's module home (record it).

### S5 — Breadth through the adapters that exist
- **What:** with the verified rows and the adapters 0.4 row Q shipped, ingest breadth in Q912's order; list
  every verified source that could not start for want of an adapter — the Q925 ⛔ seam — in the report + PR.
- **Why (ruling):** the gate row's PENDING clause; Q925 ⛔.
- **Acceptance:** the "verified-not-yet-tracked" state is populated honestly. **May not decide:** the order.

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), each separately, exit codes captured. Plus: `node --check` on
touched script blocks; the three i18n gates for every new string (the four coverage states, the zh line,
the topic caveat and ≈ label, the INT licence lines, the named refusals); the whole-tree guard set (new
`configs/` artifacts redden `test_utf8_file_io` and the registry guard if unregistered); the parser skeptic
matrix for the SKOS / EuroVoc and treaty parsers (negative-space lens, mutation-checked guards); the consent
fixture per new host, `tests/test_network_consent.py::test_no_new_socket_capable_importers` (grep-verified)
green; the Chromium click-through record (Q1128 = a): Law coverage with the per-country states and the zh
line, the Living sources law entry, the `INT` treaty in the reader with the language switch, a topic-tagged
document with its ≈ marker — in `en`, `zh`, `ar` (RTL), `fr`; then the maintainer's pass.

## 5. Operator steps

1. The live verification of every seed row (reachability, robots, licence, format) — on the allowlist of
   0.4 row V or the maintainer's machine; the decisions written into the vetting board → the catalogue.
2. The ✅ licence fetches: EuroVoc (CC0 to confirm), the UNESCO Thesaurus, AGROVOC, IPTC Media Topics, the
   UN Treaty Collection, WIPO Lex → the licence lines; confirm P5437 (FROM MEMORY) → the PR body.
3. Verify the floor file's rows against their per-language `source` (start with `contested: true`); flip
   `verification_status` and bump both `as_of` values together. Then the click-through pass on §4's surfaces.

## 6. What this slice may not decide

- **Q925 ⛔** — the adapter order and the first managed dataset: STOP at the seam; S5 records what waited.
- **Hong Kong, Macau, Taiwan, Singapore** under the `zh` row are sources the seed names; the floor file
  excludes territories by a recorded scoping decision — report them under zh without editing the floor set;
  whether the floor should include them is the maintainer's word.
- **The population source** for "population reached" — the session's call, recorded with its `as_of`.
- **A numeric bar** for topic precision or per-language coverage: none (V1-6, Q1017). **Q901 (c)**'s
  translations by other governments: not ordered by the sheet.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.6_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every ruling in §1 in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
