# S07-03 — Laws: the rest of the world; subnational · 0.7, `RELEASE_0.7_GATE.md` row C

> **Scope:** `src/law/` (`catalog.py`, `coverage.py`, `adapters/`), `configs/legal_sources*.yml`, the
> vetting board and its script, the law lane on the substrate, the coverage report of 0.6 row C, the
> Living sources law entry, `docs/SECURITY.md` + the hover; reads S05-05's ISO 3166-2 artifacts for
> subnational identity. Must NOT touch: the adapter ORDER (Q925 ⛔), case law and bills (post-beta), the
> CONFLICT itself (recorded, never picked here), the evolution surface (S05-07).
> **Implements:** Q903 [CONFLICT: a + b], Q928. Consumes, as the gate row names them: Q107, Q314, Q912
> (the order of work), Q925 ⛔ (blank), Q118.
> **Gated on:** S06-02 (the floor report, the verification tier, the licence rules — this row extends them);
> **the maintainer's confirmation or move of row C in `RELEASE_0.7_GATE.md` §3 before the subnational half
> starts** (the gate says so); S05-05 (ISO 3166-2 admin-1); Q925 ⛔ blocks only adapters not yet ordered.
> **Sequencing:** S1 (the rest of the world) needs no confirmation and runs first; S2 (subnational) waits
> for the §3 entry; the live verification per source is the operator's.

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
§10 (Laws) and its §4 block for Q314. Grep the tree before building anything — the sheet's anchors were
verified at `main`@`bebcef4` on 2026-09-12 and may have moved.

## 1. The rulings this slice implements — verbatim, by ID

- **Q903** — **(a)** «(a) National + supranational (EU, OHADA's uniform acts for its 17 member states)
  through beta; subnational recorded for post-beta.» AND **(b)** «(b) Subnational from 0.7» [CONFLICT —
  planner's note from the JSON: «CONFLICT: (a) says subnational post-beta, (b) says from 0.7». Recorded as
  given, both sides; NOT resolved by this brief. The gate places subnational at 0.7 «as the reading that
  keeps both options' scope» — (b) is the more specific timing statement, (a)'s scope (national +
  supranational through beta) is preserved either way — and says «the maintainer confirms or moves the row
  in §3 before the slice starts». Follow the gate row.]
- **Q928** — **(a)** «(a) Post-beta backlog (Q118) unless Q903 = (b) or (c).» [placement note from the
  JSON: «its own conditional resolves to 'from 0.7' because Q903 includes (b)»]

Named by the gate row, quoted from the sheet (consumed, not re-decided):
- **Q107** = (a) «… 0.7–0.8: the rest of the world + subnational.»
- **Q314** = (a) «ISO 3166-2 (`FR-75`, `US-CA`) where OSM carries the `ISO3166-2` tag; the OSM relation id
  as the fallback identity.»
- **Q912** = (a) — the order of work (sources serving many countries first, then by population reached).
- **Q925** ⛔ — blank. PENDING: the adapter order. STOP at the seam.
- **Q118** = (a) «A `docs/product/POST_1.0_BACKLOG.md` created with the 0.9 gate, each item citing its
  ruling.» — where «subnational law beyond 0.7's reach» is written (0.9 row H).

## 2. Where this stands in the tree — the staleness guard, with anchors

- VERIFIED (sheet §10 context): 51 curated + 226 generated sources; 23 registrable rows on a fresh install;
  eight UI languages with zero tracked documents; `jurisdiction` a free `String(8)` (S04-10's model replaces
  it — re-grep); every priority portal egress-blocked from the sandbox (Q114).
- grep-verified in this brief: `grep -rn -m3 '3166-2' src/ --include=*.py` — nothing: subnational identity
  does not exist in code today; S05-05's artifacts (keyed ISO 3166-2, Q314) are its source, and
  `src/geo/osm_regions.py` carries only the nine continent-level regions. `src/law/coverage.py`
  (`law_coverage_report`, `:215`) is the report S06-02 extends and this slice extends again with a
  subnational section — one report, never a second. `docs/product/LAW_VETTING_BOARD.md` (44 rows of 277,
  catalog `as_of` 2026-07-17; `scripts/law_vetting_board.py`; `tests/test_law_vetting_board.py`) is the
  board every new row joins. `configs/legal_sources.yml:56` NPC (`cn`, `zh`) — zh coverage keeps its
  separate line (Q911's standing ruling, S06-02).
- The gate's §1 board marks row C «OPEN — placement to be confirmed».

## 3. Slices — what to build, in order

### S1 — The rest of the world, under the 0.6 rules
- **What:** breadth beyond the floor: every remaining country as a vetting-board candidate, verified live
  (reachability, robots, licence, format) before it enters a catalogue, ingested through the adapters that
  exist, in Q912's order (many-country sources first, then population reached); the coverage report gains
  the non-floor countries with the same four states (tracked / verified-not-yet-tracked / unverified / no
  eligible source); every host in `docs/SECURITY.md` and the hover in the same diff; robots refusals are the
  host's choice — recorded, never worked around. Verified rows waiting for an adapter are listed as the
  Q925 ⛔ seam.
- **Why (ruling):** Q107 = a; R14 / R15; Q912 = a; Q901 (a, b, c); Q1001 / Q1002 / Q1014.
- **Acceptance:** the report renders every country of the world with a state; the vetting board regenerates
  green.
- **May not decide:** the adapter order (Q925 ⛔).

### S2 — Subnational from 0.7 (after the §3 confirmation)
- **What:** US states, German Länder, Canadian provinces, Swiss cantons, Indian states (option (b)'s own
  list); a subnational jurisdiction identified by ISO 3166-2 where OSM carries the tag, the OSM relation id
  as fallback (Q314 = a), shown with its parent country's alpha-3 (R6); the coverage report gains a
  subnational section (tracked / verified / unverified per jurisdiction); one subnational source ingested
  end-to-end with its licence line — the row's close. National + supranational breadth is never displaced
  by subnational work in the order of work ((a)'s scope preserved).
- **Why (ruling):** Q903 (b) as chosen beside (a); Q928's conditional resolving to «from 0.7»; Q314 = a.
- **Acceptance:** the row's «the coverage report of 0.6 row C gains a subnational section … and one
  subnational source is ingested end-to-end with its licence line».
- **May not decide:** which of the five families goes first (the option lists, it does not order); whether
  any other country's subnational law enters before 1.0 (beyond 0.7's reach → the backlog).

### S3 — The hand-off to the backlog
- **What:** the subnational jurisdictions this slice did not reach, listed with their state in the gate's
  §3, for `POST_1.0_BACKLOG.md` (0.9 row H) to cite as «Q903/Q928 as confirmed».
- **Why (ruling):** Q118 = a; Q928 = a.
- **Acceptance:** the list exists in the gate's §3.
- **May not decide:** anything post-1.0.

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), separately, exit codes captured. Plus: `node --check` on touched
script blocks; the three i18n gates for every new string (the subnational section labels, the identity
badge and its fallback caveat, the licence lines, the named refusals); the whole-tree guard set; the parser
skeptic matrix for any new adapter (negative-space lens; mutation-checked guards); the consent fixture per
new host with `tests/test_network_consent.py::test_no_new_socket_capable_importers` (grep-verified) green;
the Chromium click-through record (Q1128 = a): the coverage report's world and subnational sections, a
subnational document in the reader with its jurisdiction badge and licence line, the Living sources law
entry — in `en`, `de`, `hi`, `ar` (RTL); then the maintainer's pass.

## 5. Operator steps

1. The maintainer confirms or moves row C in `RELEASE_0.7_GATE.md` §3 (the CONFLICT's owner) before S2.
2. The live verification per source — the allowlist of 0.4 row V or the maintainer's machine → the vetting
   board → the catalogue.
3. The click-through pass on the surfaces in §4.

## 6. What this slice may not decide

- **Q903's CONFLICT** — never picked by a session; this brief ships S1 regardless and S2 only after the §3
  entry; if the maintainer moves subnational post-beta, S2 becomes a backlog item (Q928's (a) reading) and
  S3 records it.
- **Q925 ⛔** — the adapter order; the seam list in S1.
- **Case law (Q929 = a) and bills and drafts (Q902 note)** — post-beta; not here.
- **The first subnational family, the population source for the order of work, OHADA's supranational
  standing** (S06-02's order) — recorded, not ruled here.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.7_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every ruling in §1 in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
