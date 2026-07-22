# Autonomous session brief — super-groups: honest statistics, a Leads family, navigation, cleanup (2026-07-18)

**Mission.** The maintainer reviewed Insights → Groups (super-groups) on the live
~500k-article corpus and exported the full surface (2026-07-18, pasted verbatim into the
session). Verdict: the curated scaffold (~77 concept groups over the ring set) is healthy,
but (a) the headline totals are broken by generic-word contamination and within-group
double counting, and (b) the layer has no STATISTICS at all — no trend, no rising/falling,
no cards, no way to reach a keyword's super-group from search. Maintainer asks, ruled:
**super-group statistics (is a theme rising?), a Leads family for super-groups, and
keyword → super-group navigation** — plus the cleanup the export demands. The maintainer
doctrine stands: automated by default; curation surfaces belong in Settings.

**Sequencing (binding):** this session runs AFTER the two sibling briefs merge their
executions — `…2026-07-18_LEADS_CALIBRATION.md` (S1 builds the shared generic-term/
DF-ubiquity gate) and `…2026-07-18_FAMILIES_ENTITIES.md` (S3 builds the case-aware ring
seams). CONSUME those primitives; never duplicate them. Staleness guard applies doubly:
verify what those sessions actually shipped before building.

**Executor:** one Claude Code CLI session, LOCAL only. Branch `claude/supergroups-*` off a
freshly-fetched `origin/main`, ONE draft PR, commit-per-slice. House gates: skeptics
complete before push on the statistics slices (negative-space lens: inputs that should
produce NO stat/card must produce none); full local suite green; ledger + shipped.csv;
frontend conservative + flagged per fork-3/Q6a.

---

## §0 The field evidence (acceptance cases from the 2026-07-18 export)

| # | Observed | Defect / gap | Post-fix expectation |
|---|---|---|---|
| 1 | "Artificial intelligence · 43,067 mentions" — but the plain member **data = 36,507 (85%)** | a generic homograph-prone word dominates the total; the total reads as a theme statistic | every group stat carries a DOMINANCE disclosure (top member + its share); generic-ubiquitous members flagged via the shared gate |
| 2 | the same *data* also sits in "Data &amp; privacy" as a ring; *logic* ring in BOTH Mathematics and Philosophy | cross-group overlap is legitimate (Venn) but undisclosed | overlap disclosed on the stat ("also counted in …"), never silently summed as if exclusive |
| 3 | AI group mixes grains: plain families *model / models / modèles / ia / données / intelligence artificielle* beside rings covering the same concepts (plain *ai 12* beside the *ai* ring 1,555) | a term that is ALSO a ring member in the same group counts its mentions twice in the group total | within-group member keyword-ids DEDUPED before any sum; the legacy plain-family residue migrated or removed (curation data fix) |
| 4 | *deficiency* ring inside "Money &amp; banking" (1,474 mentions) | looks like a deficit/deficiency conflation in the scaffold | verified against the ring's members; re-scoped or removed (hand-verified, never guessed) |
| 5 | *copyrighted* as a ring lemma; `diaspora*` with a stray asterisk | scaffold/label data bugs | fixed in the config; a lint catches malformed labels |
| 6 | *universe* ring·68 at 16,393 mentions (#1 in Cosmology, above *star* 2,491); *creation* 4,618 (87% of "Social cohesion"); *sentence* 5,430 carrying "Justice"; *marketplace* 4,555; *identity* 1,133 | homograph members inflate ring counts in SOME language | investigate the top-dominance outliers member-by-member (which language contributes the bulk — the ring language_breakdown shows it); a homograph member is removed from the ring or the ring from the group, evidence-first |
| 7 | dozens of zero-mention members rendered flat | display noise | zero-mention members collapsed behind a count ("+N with no mentions yet") |
| 8 | no trend/rise/fall anywhere on the surface; no cards; no path from a keyword to its group | the feature gap this brief exists for | S1–S3 below |
| 9 | merge/split-style curation (add family / add ring / delete) lives on a content tab | content-first (invariant #8) | curation relocates to Settings beside the Families curation home (coordinate with the Families session's S4 — same destination, do not build a second home) |

## §1 Ground truth (anchors verified at `45b38a4`; re-verify)

- **Model:** `KeywordSuperGroupMember` (member = a family `normalized_term` OR a ring via
  `ring_id`; migration f4a5b6c7d8e9). Scaffold: `src/analytics/supergroup_seed.py:72
  seed_supergroups` over `configs/keyword_supergroups.yml` (~77 groups; retire-only-
  untouched + user-edit-wins conventions — respect them in every cleanup).
- **Backend:** `src/api/insights.py` — `_supergroup_totals:1748` (a ring member aggregates
  over ALL the ring's cross-language terms), `list_supergroups:1829`,
  `add_supergroup_members:1935` (validates rings via `ring_meta`).
- **Rings:** `src/analytics/equivalence.py` — `ring_of:136`, `ring_meta:149`; ring
  `members`/`language_breakdown` are the existing disclosure vocabulary.
- **Windowed machinery to reuse (never rebuild):** `queries.trending`/`trending_windows`
  (the disclosed recent-vs-prior RATE grammar), the `keyword_daily` rollup +
  `src/analytics/rollup_serve.py` (windowed per-keyword daily counts, epoch-guarded),
  `ooChart` for series display. Perf discipline: resolve member keyword-ids ONCE, sum
  over the mention/rollup tables by id — NEVER the keyword→articles codec join.
- **Cards substrate:** `src/briefing/producers.py` + the Card schema
  (`assert_no_score_fields`); the Leads-calibration session's shared gates
  (generic-term/DF-ubiquity; FDR patterns already in `supply_chain_ripple`).
- **UI:** `src/static/app.js` — `loadSuperGroups:9238`, `sgCard:9268`, `sgAddRing`; the
  Insights Groups subtab (`cat === "supergroups"`). The analysis window's Keywords
  subtab + search results are the navigation targets for S3.

## §2 The slices

### S1 — Honest super-group statistics (backend core; ⚠ skeptic slice)
1. **Member resolution + dedup:** one function resolves a super-group to its DISTINCT
   member keyword-id set (families → member ids; rings → every cross-language term's
   id; the union DEDUPED — §0 row 3). This is the primitive every stat uses.
2. **The stats:** per group — windowed mention counts (daily series over the rollup
   machinery), recent-vs-baseline RATE ratio (the existing trending grammar, stated
   windows), distinct sources, language spread (per-language counts via the ring
   breakdowns). Counts and ratios only; NO composite score (the no-score walkers run).
3. **The disclosures, mandatory on every payload:** top-member DOMINANCE (name + share
   — §0 row 1: "data = 85% of this total"); cross-group overlap ("N members also in:
   …" — §0 row 2); `basis`/as-of when served from the rollup. A stat without its
   dominance line must not render.
4. **Endpoint** (`GET /api/insights/supergroups/stats` or extend `list_supergroups` —
   pick the cleaner): bounded, deadline-guarded per the S2.4 conventions.
5. **UI:** the Groups surface shows per-group trend sparklines (`dashChartSvg`, Item-Y
   bars when sparse) + the rate + the dominance line; zero-mention members collapse
   (§0 row 7). Conservative + flagged.

### S2 — The `supergroup_rising` Leads producer (scale-aware from birth)
Fires when a group's recent share rises against ITS OWN baseline. Birth constraints
(the Leads-calibration lessons are prerequisites, not future fixes): FDR correction
across the ~77 groups; count floors (no z-theater on tiny counts); share-normalized
against daily corpus volume (never raw counts); a rise DRIVEN by one member states it
in the card ("driven almost entirely by 'data'") — and a rise driven by a
generic-ubiquitous member (the shared gate) is NOT a Lead at all. Bucket: watch/context
— never urgent (the ruled alert boundary). Card carries the exact member set → the
analysis window via the id-seeding path. Negative-space tests: a flat group, a
one-generic-word spike, and a tiny-n spike each produce NO card.

### S3 — Keyword → super-group navigation
A reverse lookup (normalized term → family → ring → super-group(s)) exposed cheaply
(the membership rows are already in the DB; cache per process, invalidate on curation
writes). Surface: a "part of ⊕ <group>" chip in the analysis window's Keywords subtab
and on search-result keyword rows, linking to the group view (its trend + members).
PLURAL membership renders as multiple chips — never silently picking one. Conservative
+ flagged; keyed strings ×12 or the English-fallback convention, matching the
neighborhood.

### S4 — Scaffold + data cleanup (evidence-first, never a sweep)
1. Within-group grain dedup as DATA: migrate the AI group's legacy plain-family
   residue (model/models/modèles/ia/données/intelligence artificielle…) into the
   covering rings or drop the redundant members — honoring user-edit-wins (only
   seeded, untouched groups are touched; the seed_supergroups conventions).
2. The scaffold bugs: *deficiency*-in-Money (verify the ring's actual members, then
   re-scope/remove), *copyrighted* → *copyright*, the `diaspora*` asterisk. Add a
   config lint (labels well-formed, ring ids resolve, no duplicate member within a
   group) to the existing test that validates the scaffold.
3. The §0 row 6 homograph outliers: per outlier, read the ring's language_breakdown,
   identify the inflating member(s), fix the DATA (remove the homograph member from
   the ring, or the ring from the group) — hand-verified case by case, recorded in
   the PR body. Never an automated purge.

### S5 — Curation to Settings
Relocate add-family/add-ring/delete controls to the Settings curation home the
Families session establishes (§0 row 9). If that session has not run yet, build the
minimal shared destination it specifies rather than a second home. Insights keeps the
data view (groups + stats + members with provenance). Absorption-guarded (the Desk
rule: nothing lost).

## §3 Binding honesty rules

No composite scores anywhere (walk changed payloads). Every stat carries its
dominance + overlap disclosures — a super-group number without them misleads by
construction (this export proved it). Curation conventions unchanged: user wins,
seeded-untouched only, everything reversible, nothing in the keyword store changes.
Cleanup is evidence-first and hand-verified per case — never a category sweep.
Degrade loudly: a group whose stats cannot be computed (rollup unavailable) says so.

## §4 Out of scope

Growing the ring set (540→~2000 stays the corpus-driven generator track, operator-
run); the finer ~200-group concept cut (gated on the ring growth, per the standing
plan); LLM anything; ranking changes; the Families/Leads sessions' own territory
(consume, don't rebuild).

## §5 Definition of done

§0 rows pinned as tests where fixturable (dedup, dominance, overlap disclosure, the
producer's negative space) and hand-verified where data (rows 4–6, recorded in the PR
body); skeptic recorded on S1/S2; full suite green; node --check + invariant guards;
ledger + shipped.csv; one draft PR onto `main`. Field acceptance: the maintainer
re-opens Groups on the live corpus — the AI total no longer reads as 43k-of-which-85%-
is-"data" without saying so, a group trend is visible with its dominance line, a
rising theme can surface as a Lead, and clicking a keyword anywhere offers its
super-group.
