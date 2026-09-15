# S08-01 — Conflict monitoring and the 360° dossier · 0.8, `RELEASE_0.8_GATE.md` row A

> **Scope:** a new conflict / defense vertical through the §4.0 pattern (new modules under `src/`, named in
> the PR), dated catalogs + registry entries under `configs/`, the dossier surface (new — a full-screen
> window in the analysis-window pattern, invariant #22, driven by `ooSubtabs`), the entity spine of S05-03
> (QIDs, Wikidata items, the Place entity), the rails it composes — news, the wiki lane (S04-09), the law
> evolution surface (S05-07), StatFigure, the Agenda, Places (S05-04) and every vertical — the
> signed-evidence export (`src/api/reporting.py`), `docs/SECURITY.md` + the hover. Must NOT touch: ACLED
> (V1-3: no code path, not even user-fetch), OpenSanctions (OUT), GDELT as a firehose (§4.6), any «conflict
> intensity score», a single casualty number, OSM-derived rows in any export (Q823 ⛔).
> **Implements:** carried V1 content — `V1_PATHWAY_2026-07-14.md` §3 (lines 297–343: the 0.8 row and the
> amendment «0.8 conflict is unchanged except that V1-3 removes OpenSanctions»), §4.0, §4.4, §8 item 4,
> ruled 2026-09-07 (V1-1, V1-2, V1-3). No sheet IDs.
> **Gated on:** the `v0.7.0` tag; S05-03 (the spine the dossier is over), S05-11 (the claim workspace and
> the Conjunction Lens the evidence trails reuse), S05-04 / S05-07 / S04-09 (the rails), S04-01 (the host
> list); Q823 ⛔ for the export's OSM rows.
> **Sequencing:** the conflict vertical first (it is a rail); the dossier second (it needs ≥ 6 rails with
> data for one entity); the licence fetches and the real-entity click-through are the operator's.

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then `V1_PATHWAY_2026-07-14.md` §3, §4.0, §4.4, §7 and §8 in full (the rulings this slice
carries live there, not in the sheet), then the sheet's §11 context. Grep the tree before building anything
— the anchors were verified at `main`@`bebcef4` on 2026-09-12 and may have moved.

## 1. The rulings this slice implements — verbatim, by ID

No sheet question ID belongs to this slice. The rulings it implements, verbatim from the V1 pathway:
- §3 line 314, the 0.8 row: «**Conflict/defense** (§4.4) · the topic-dossier surface joins news × laws ×
  wiki × stats × patents × papers × events × map · map change-tracking seed (OSM dated boundaries)». The
  seed was pulled forward (0.5 row E, 0.6 row B — Q105 = a, Q106 = a): what 0.8 owes the map is completion.
- Amendment 4's last sentence (line 330): «0.8 conflict is unchanged except that V1-3 removes OpenSanctions.»
- §8 item 4 (the 1.0 bar): «from any Lead/keyword/search → the dossier surface joins ≥6 rails (news, wiki,
  laws, stats, events, map + any vertical) with evidence trails and signed-evidence export; the Conjunction
  Lens shipped and Gecko-verified» — read under Q1128 = a (Chromium + the click-through).
- §4.4's binding honest angles: casualty figures always carry the producer's methodology and uncertainty
  («UCDP best/low/high estimates shown as ranges, never one number»); event data are reports coded by a
  project with stated rules, the coding project itself a stanced source; no «conflict intensity score» —
  counts with method + n; sanctions / arms data are legal records with dates; under-reported conflicts are
  a coverage FACT to surface, not to reproduce.
- §7 V1-2 (no key-gated source, at all); V1-3 («EXCLUDE ENTIRELY — no code path, not even user-fetch» for
  redistribution-forbidding or non-commercial terms; ACLED-class).
- Consumed from the sheet: Q1001 / Q1002 / Q1014 (hosts, hover, transport); Q1017 = a (K13 measured first);
  Q823 ⛔ (blank — no OSM-derived row in the signed export); Q1128 = a.

## 2. Where this stands in the tree — the staleness guard, with anchors

- grep-verified in this brief: `grep -rn -i dossier src/` — the word appears only as the French «dossier»
  (folder) in `src/static/locales/fr.json`: no dossier surface exists. `grep -rn -i -E
  'acled|ucdp|gdelt|opensanctions' src/ configs/` — ACLED exists ONLY as a press RSS feed
  (`configs/sources.yml:30214–30216`, `acleddata.com/feed/`), UCDP only in `src/stats/bulk.py`'s docstring
  (the ZIP parser shape): no conflict data lane exists. `src/api/reporting.py:2` «Reporting API: export
  signed, tamper-evident evidence bundles» and `src/api/custody.py:165` `verify_bundle` are the export and
  its verifier the dossier reuses; `src/api/briefing.py:133` exports a draft as evidence-carrying Markdown.
  `src/stats/bulk.py` is the network-free wide-CSV / ZIP parser (V-Dem, UCDP shapes). The analysis window
  (`#tab-analyze`, `ooSubtabs`, invariant #22) is the composition pattern; invariant #31 (a lens, never a
  second source of truth) is the rule the dossier inherits.
- V1 §4.4 (2026-07-14): no row reached ✅ — `sipri.org`, `ucdp.uu.se` www and `api.unhcr.org` docs 403'd
  the fetcher; UCDP GED + Candidate is reported CC BY 4.0 (`ucdpapi.pcr.uu.se/api/gedevents/<version>`, no
  key, version-numbered), SIPRI attribution-required / «commercial = permission», UNHCR CC BY 4.0
  (unconfirmed page), ReliefWeb (`appname`, 1,000 calls/day), HDX per-dataset, V-Dem CC BY-SA (variant to
  confirm) — every licence a ✅ fetch before any bundling decision.
- The 0.8 gate: the last release in which a schema change may be non-additive (Q102 = a) — a table the
  dossier or the vertical adds lands here or is declared additive (S08-02's audit lists it).

## 3. Slices — what to build, in order

### S1 — The conflict vertical's first slice: UCDP GED + Candidate
- **What:** after the ✅ licence fetch: the JSON API through the one guarded fetcher (robots / UA tested on
  both hosts first — the www host 403'd before), each dataset version a vintage; events onto the map (Places
  / coordinates), the Agenda (dated events) and the keyword rails with a distinct provenance class; Candidate
  events pre-labelled preliminary → the deduced / confirmed two-class convention; fatalities as best / low /
  high RANGES, never one number; the coding project's methodology and stance on every surface ×12; counts
  with method + n; the coverage gap of under-reported conflicts stated as a fact. Then, each after its own
  licence check: SIPRI arms transfers + milex, UNHCR population statistics, ReliefWeb, HDX, V-Dem.
- **Why (ruling):** §4.4's recommended first slice and binding angles; V1-2 / V1-3; §4.0 steps 1–9.
- **Acceptance:** the pure parser's negative-space fixture (an event with no coordinates · a version with
  no fatality bounds · an empty Candidate page → gaps and classes, never values); every host in
  `docs/SECURITY.md` and the hover in the same diff, refused under the kill switch with a named refusal,
  transport declared, never downgraded; the K13 freshness block records values, no bar.
- **May not decide:** SIPRI's «commercial = permission» standing (the ✅ fetch classifies it under V1-3);
  UN Comtrade (free key → V1-2: no).

### S2 — The 360° dossier over one entity of the spine
- **What:** from any Lead / keyword / search, a full-screen window (the analysis-window pattern) over ONE
  entity of S05-03's spine, composing rails as subtabs: news · wiki · laws (the evolution surface) · stats
  (StatFigure) · events (Agenda) · map (Places) · each vertical with data (climate, elections, medical,
  patents if cleared, conflict). Each rail shows its own store's rows with provenance and caveat VISIBLE
  (the informed-consent non-negotiable; the hover carries the long form), evidence trails per item (the
  claim-workspace pattern of S05-11), and a rail with no data says so — the window renders the rails it
  has, never padded to six. The dossier is a LENS: it reads each rail's store, keeps no second copy, computes
  no composite. Its signed-evidence export reuses `src/api/reporting.py`'s bundles and verifies through
  `verify_bundle`; OSM-derived rows are excluded from the export while Q823 ⛔ is blank, and the export says
  what it excluded.
- **Why (ruling):** §8 item 4; §3's 0.8 row; invariants #22 and #31; Q823 ⛔.
- **Acceptance:** the row's «one real entity's dossier is shown joining ≥ 6 rails with each rail's
  provenance and caveat visible … the signed-evidence export of that dossier verifies, and the surface is
  Chromium-verified + click-through».
- **May not decide:** the entry point's placement (a main tab vs opened from the analysis window — the V1
  text says «from any Lead/keyword/search»; where the button lives is a design note for the PR); the rail
  order.

### S3 — Diagnostics
- **What:** the conflict vertical's K13 block; the dossier's rail-availability counter per entity (which
  rails had rows; a gap is a gap).
- **Why (ruling):** §4.0 step 8; Q1017 = a.
- **Acceptance:** both in the bundle with method and n.
- **May not decide:** any bar.

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), separately, exit codes captured. Plus: the parser skeptic
matrix (negative-space lens; mutation-checked guards); the consent fixture per host (the UCDP API host and
www host, SIPRI, UNHCR, ReliefWeb, HDX, V-Dem) with the named refusal and
`tests/test_network_consent.py::test_no_new_socket_capable_importers` (grep-verified) green; the export's
verification round-trip (export → `verify_bundle` → pass, and a tampered byte → the named failure); the
no-composite walker over the dossier's payload keys (no `score` / `rating` / `ranking` / `grade` —
«degraded» contains «grade»); `node --check` on every touched `<script>` block; the three i18n gates for
every new string (the range caveats, the coding-project stance, the rail-empty states, the export's
exclusion line, the named refusals); the whole-tree guard set; the Chromium click-through record
(Q1128 = a): one real entity's dossier with ≥ 6 rails, each rail's caveat and hover, the export button and
its exclusion line, the conflict surface with ranges — in `en`, `ar` (RTL), `ru`, `fr`; then the
maintainer's pass.

## 5. Operator steps

1. The ✅ licence fetches on a networked machine: UCDP (CC BY 4.0), SIPRI's terms, UNHCR's page, ReliefWeb,
   HDX per dataset, V-Dem's variant; robots / UA on `ucdp.uu.se` and the API host → the PR body and the
   catalogue's licence lines.
2. The maintainer's runs where the sandbox's egress refuses a host (probe first; report per host).
3. The click-through on one real entity of the maintainer's corpus (the demonstration entity is theirs).

## 6. What this slice may not decide

- **Q823 ⛔** — the export's OSM rows; excluded and stated until ruled.
- **ACLED's press RSS feed** in `configs/sources.yml` is article content, not the event dataset V1-3
  excludes; whether it stays is a licence question for the maintainer, recorded — not decided here.
- **The demonstration entity, the entry-point placement, the rail order, module names** — design notes.
- **Bars** (K13, rail counts): none (Q1017 = a).
- **A schema addition after this release** must be additive (Q102 = a) — S08-02's audit is where the
  dossier's tables are listed.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.8_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every ruling in §1 in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
