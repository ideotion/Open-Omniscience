# S07-01 — Medical + patents · 0.7, `RELEASE_0.7_GATE.md` row A

> **Scope:** two new verticals through the §4.0 pattern — new modules under `src/` (named in the PR, not
> here), dated catalogs + registry entries under `configs/`, the managed-dataset posture on the 0.4 row O
> substrate, the K13 freshness block, `docs/SECURITY.md` + the consent hover, the Home producers the patents
> vertical corroborates (`src/briefing/producers.py:1288` `ip_litigation_pulse`). Must NOT touch: EPO
> BDDS/OPS, CourtListener/RECAP, EUIPO/INPI/KIPRIS/JPO (OUT), Google Patents BigQuery (excluded), PubMed/PMC
> article HTML (never scraped — sanctioned bulk/API channels only), any key-gated source (V1-2), medical
> advice of any kind, an «innovation score».
> **Implements:** carried V1 content — `V1_PATHWAY_2026-07-14.md` §3 (lines 297–343: the 0.7 row and
> amendment 3), §4.0, §4.1, §4.2, ruled 2026-09-07 (V1-1, V1-2, V1-3, V1-4) and the 2026-07-14 PubMed ruling
> inside §4.2. No sheet IDs.
> **Gated on:** the `v0.6.0` tag; the substrate holding at the 0.6 exit («the substrate gains PubMed-style
> managed datasets if the 0.6 exit shows the machinery holds» — the intake's cross-vertical note quoted by
> the gate row); **the patents PRECONDITION** (§4.1's ⚠ block) verified on the maintainer's networked
> machine BEFORE any patents build hour; Q1009 ⛔ bounds the PubMed baseline ingest (V1-4).
> **Sequencing:** the precondition check first (an operator step); medical builds regardless of its
> outcome; patents only on a pass.

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then `V1_PATHWAY_2026-07-14.md` §3, §4.0, §4.1, §4.2 and §7 in full (the rulings this slice
carries live there, not in the sheet), then the sheet's §11 context for Q1003 and Q1009. Grep the tree before
building anything — the anchors were verified at `main`@`bebcef4` on 2026-09-12 and may have moved.

## 1. The rulings this slice implements — verbatim, by ID

No sheet question ID belongs to this slice. The rulings it implements, verbatim from the V1 pathway:
- §3 line 313, the 0.7 row: «**Patents/IP** (§4.1) + **medical/PubMed** (§4.2) — both through the standard
  vertical pattern».
- Amendment 3 (lines 326–328): «0.7 splits. Medical survives fully keyless and is buildable on facts we
  hold. **Patents reduces to USPTO bulk XML + CPC and rests on one unverified fact** (see the ⚠ block in
  §4.1) — that check is a PRECONDITION on the 0.7 slot, not a risk to meet mid-build.»
- §4.1 ⚠ (lines 406–413): «if USPTO bulk is ID.me-gated, patents has no viable source under V1-2 and the
  0.7 slot is re-planned rather than quietly slipped. Check this before any 0.7 build hour is spent.»
- §4.2's maintainer ruling (2026-07-14): PubMed is «Not a privileged source» — no elevated trust anywhere;
  its content database is «architecturally separate», managed as its own dataset with its own storage
  posture, diagnostics and provenance class, never blended into news by default; the access model is
  metadata + abstracts, full text only where openly licensed (PMC OA), a paywalled text an honest gap.
- §7 V1-2: «KEEP THE DEFER RULING — no key-gated source, at all.» V1-3: «EXCLUDE ENTIRELY — no code path, not
  even user-fetch» for terms forbidding redistribution or restricting to non-commercial use. V1-4:
  «API-FIRST, corpus-driven; the baseline ingest stays behind the storage phases (the bulk-file parser is
  still built, as the preferred transport)».
- §4.2's binding constraints: retraction / correction status is first-class metadata wherever a paper is
  shown; preprint vs peer-reviewed vs retracted are provenance classes, never blended; the abstract
  copyright nuance — store in the user's local corpus, never bundle an abstract snapshot in the repo.
- Consumed from the sheet: Q1001 / Q1002 / Q1014 (every host, the hover, the transport); Q1017 = a (K13
  measured first); Q1003 = a (one substrate); Q1009 ⛔ (the storage rows — blank).

## 2. Where this stands in the tree — the staleness guard, with anchors

- grep-verified in this brief: `grep -rn -i -E 'pubmed|uspto|\bcpc\b' src/ configs/` — no PubMed and no
  USPTO code anywhere; every `cpc` hit is NOAA's Climate Prediction Center in `src/stats/oni.py` — name the
  patent-classification module so it cannot collide with that. `src/briefing/producers.py:1288`
  `ip_litigation_pulse` exists (V1 §4.1: a 12-term IP vocabulary trending in NEWS coverage, no external
  data) — the patents vertical corroborates it. `src/stats/bulk.py` (wide-CSV + ZIP, network-free) is the
  parser pattern to follow. `ls src/versioned` — absent (0.4 row O, OPEN): the managed-dataset posture this
  slice needs is that row's output.
- V1 §4.1 (2026-09-07): `data.uspto.gov` and `bulkdata.uspto.gov` answered `000` through the sandbox proxy
  while `pypi.org` answered `200` — the sandbox cannot run the precondition. V1 §4.2: no medical row reached
  ✅ (the official doc pages 403'd); the endpoints are REPORTED open: NLM baseline + daily updates (FTP/HTTPS
  gzip XML, no key), the PMC OA subset, Europe PMC (~10 req/s, no key), E-utilities (keyless 3 req/s),
  Crossref + Retraction Watch (`filter=update-type:retraction`), ClinicalTrials.gov v2 (~50 req/min),
  openFDA (keyless 1,000/day) — each a per-request figure to re-read on the networked check.
- The 0.7 gate's entry: `v0.6.0` tagged; the OSM daily tracking running on one country; the law coverage
  report in the bundle.

## 3. Slices — what to build, in order

### S0 — The patents precondition (operator; nothing patents-shaped is built before it)
- **What:** on the maintainer's networked machine: is a USPTO bulk XML file (PADX assignment daily XML,
  grants / applications, TDXF) downloadable keyless, or is it ID.me-gated? Fetch the CPC terms page ✅. Write
  the outcome, with the request / response facts, into `RELEASE_0.7_GATE.md` §3. A fail is a DECLINE
  recorded with its number, never a slip.
- **Why (ruling):** amendment 3; §4.1 ⚠; V1-2.
- **Acceptance:** «the precondition check's artifact exists either way» (the gate row).
- **May not decide:** a workaround (a user-supplied key is a key-gated source: V1-2 says no, at all).

### S1 — Medical: the managed dataset, corpus-driven
- **What:** the pure-Python XML parser over the PubMed baseline / update-file format (fixture-tested,
  negative-space skeptic: an empty update file, a record with no abstract, a retracted-in-place record →
  gaps and classes, never values); the bounded, corpus-driven ingest — only the records the user's
  investigations touch, API-first (E-utilities at its keyless etiquette through the one guarded fetcher;
  bulk files preferred as transport, Tor-friendly — §4.2's Tor caveat); metadata + abstracts into the user's
  LOCAL corpus (never a repo snapshot); full text only PMC OA; retraction / correction status first-class
  from day one (the Crossref Retraction Watch join) and rendered wherever a paper is shown; its own dataset
  on the substrate with its own storage posture, provenance class and diagnostics; papers surface BESIDE
  news with provenance visible; «this app never gives medical advice» on the surface ×12.
- **Why (ruling):** §4.2's ruling and constraints; V1-4; Q1003 = a.
- **Acceptance:** the row's «each vertical's freshness diagnostic reads from real fetches through the
  consent gate, the datasets carry registry entries and disclosure lines»; every host in `docs/SECURITY.md`
  and the hover in the same diff, refused under the kill switch with a named refusal, transport declared,
  never downgraded.
- **May not decide:** the full ~38 M-record baseline ingest (storage-phase-gated; Q1009 ⛔ blank);
  ClinicalTrials.gov / openFDA / medRxiv ordering after the first slice.

### S2 — Patents, only on S0's pass
- **What:** USPTO Patent Assignment daily XML (PADX) first — real ownership surveillance corroborating the
  shipped producers; daily files = vintages; public domain; the CPC taxonomy bundled dated (`*_AS_OF` +
  registry) only after the ✅ terms fetch; filings / grants / assignments as facts with legal-status caveats
  (an application is not a grant); counts and trends, never «innovation scores»; patent ↔ keyword linkage a
  lens (co-occurrence, never causation); litigation dockets are allegations until judgment — said on the
  surface ×12. Build against USPTO ODP, never `patentsview.org` (dead, 410 since 2025-05 per §4.1).
- **Why (ruling):** §4.1's recommended first slice; amendment 3; V1-2 / V1-3.
- **Acceptance:** the row's «patents half closed OR recorded as declined on its precondition, with the
  measurement».
- **May not decide:** the EPO / national-office return («an office proven keyless on a networked check may
  return» — that check is the maintainer's, not assumed).

### S3 — Diagnostics on the KPI board
- **What:** per-vertical coverage / freshness blocks for medical (and patents if built) riding
  `/api/diagnostics/freshness` (K13), values recorded, no bar set.
- **Why (ruling):** §4.0 step 8; Q1017 = a.
- **Acceptance:** the blocks appear in the bundle with method and n.
- **May not decide:** the K13 bar.

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), separately, exit codes captured. Plus: the parser skeptic
matrix (negative-space lens mandatory; every guard mutation-checked by name); the consent fixture per host
(NLM, PMC, Europe PMC, E-utilities, Crossref, ClinicalTrials.gov, openFDA, USPTO ODP) with the named
kill-switch refusal and `tests/test_network_consent.py::test_no_new_socket_capable_importers`
(grep-verified) green — a bulk FTP path needs its own allowance with a written reason, per that test file's
rule; `tests/test_external_freshness.py::test_every_as_of_constant_is_registered` (grep-verified) for the
CPC vintage; `node --check` on touched script blocks; the three i18n gates for every new string (the
no-medical-advice line, the retraction badge and its caveat, the legal-status and allegation caveats, the
named refusals); the whole-tree guard set; the Chromium click-through record (Q1128 = a): a search showing
papers beside news with their provenance class and a retraction badge, the medical freshness block, the
patents surface if built — in `en`, `zh`, `ar` (RTL), `de`; then the maintainer's pass.

## 5. Operator steps

1. The patents precondition on the maintainer's networked machine (§3 S0) + the CPC terms ✅ fetch → the
   gate's §3.
2. Re-verify the medical rows' terms and limits on a networked machine (no row reached ✅): NLM download
   terms and the abstract-rights note, PMC OA, Europe PMC, E-utilities, Crossref, ClinicalTrials.gov,
   openFDA; test NLM's Tor-exit behaviour on the rig.
3. The maintainer's runs where the sandbox's egress refuses a host (probe first, per the base working mode
   §6; report the per-host evidence).
4. The click-through pass on the surfaces in §4.

## 6. What this slice may not decide

- **The precondition's outcome** — the maintainer's networked check decides the patents half; a session
  never assumes it passed, and never re-plans the 0.7 slot on its own (the gate's exit admits «closed OR
  recorded as declined»).
- **Q1009 ⛔** — the storage rows: the ~38 M-record baseline ingest waits; the corpus-driven ingest does not.
- **«If the 0.6 exit shows the machinery holds»** — if the substrate did not hold, this slice reports it and
  stops; it never builds a second substrate (Q1003 = a).
- **Module names, the second medical slice's order, any keyed API even with a user's own key** (V1-2: no).

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.7_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every ruling in §1 in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
