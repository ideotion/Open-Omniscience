# S05-11 — The approved desk, carried from the V1 train · 0.5, `RELEASE_0.5_GATE.md` row K

> **Scope:** the Claim Workspace A1 (the action plan's step A-2), the cross-vertical entity / topic dossier
> SEED on S05-03's spine, the Conjunction Lens across verticals (`src/analytics/conjunction.py` + its UI in
> the analysis window), the onboarding tour, signed-evidence export polish (`src/bulletin/evidence.py`,
> `src/bulletin/privacy.py`, `src/custody/signing.py`). Must NOT build: a verdict, a score or any composite
> (the non-negotiable), an LLM as the default voice of a trail (the A-2 comment), the dossier's 1.0 bar
> (V1 §8 item 4, ≥ 6 rails — 0.8 row A owes it), an onboarding step that narrows the corpus, any evidence
> ZIP member carrying an OSM-derived row (Q823 ⛔).
> **Implements:** no question IDs — carried from `V1_PATHWAY_2026-07-14.md` §3 (the 0.5 row) as ruled
> 2026-09-07 (V1-1: themes and order stand) and kept by Q105 = a («(a) Yes — amend the contents, keep the
> themes.»). Design of record: `docs/FUTURE_DEVELOPMENTS.md` §"User-centric reflections" A1–A9 and
> `docs/archive/releases/V01_ALPHA_ACTION_PLANS.md` Plan A (A-1 … A-4, each with a "Done when").
> **Gated on:** S05-03 (the entity spine, for the dossier seed); S05-01 (the omnibar rule Q608 — Enter opens
> the analysis window, so the workspace opens by an explicit command); Q823 ⛔ for the evidence export.
> **Sequencing:** last in 0.5; each item is its own draft PR; the tour after the shell's ring dial (S05-09).

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
own section for those questions (their verified context and option lists). Grep the tree before building
anything — the sheet's anchors were verified at `main`@`bebcef4` on 2026-09-12 and may have moved.

## 1. The rulings this slice implements — verbatim, by ID

- No question IDs. The V1 train's 0.5 row (`V1_PATHWAY_2026-07-14.md` §3, verbatim): «Claim workspace A1
  (evidence trails) · entity spine v1 (entity→QID; the cross-vertical entity/topic dossier page) ·
  Conjunction Lens across verticals · onboarding tour · signed-evidence export polish», gated on «0.4's
  Article generality (dossiers need it)». Ruled 2026-09-07 (V1-1: «the themes and order stand»); kept by
  **Q105 = (a)** «(a) Yes — amend the contents, keep the themes.» — the amendment adds S05-01, S05-03 and
  S05-04/05 beside the desk; it removes nothing from it.
- The gate row K's own words: «the claim workspace A1 with evidence trails, the cross-vertical entity /
  topic dossier seed on the spine of row C, the Conjunction Lens across verticals, the onboarding tour,
  signed-evidence export polish … their own open design questions are in the V1 pathway and the 23-prompt
  plan, not re-asked here». The 1.0 bar (V1 §8 item 4: «the dossier surface joins ≥6 rails … with evidence
  trails and signed-evidence export; the Conjunction Lens shipped») is NOT owed here.
- Cross-cutting rulings that bind every item: Q608 = a (Enter opens the analysis window; static commands
  need an explicit selection); Q1008 = a (attribution lines on every evidence ZIP; OSM lines wait on Q823
  ⛔); Q1128 = a (the verification bar); the informed-consent non-negotiable (caveats visible, ×12).

## 2. Where this stands in the tree — the staleness guard, with anchors

- The Conjunction Lens core is SHIPPED: `src/analytics/conjunction.py` ("deep keyword analytics over N
  keywords (planning §1)"; grep-verified head) and its UI in the analysis window's Keywords subtab at
  `src/static/app-corpus.js:869–955` (`anConjunctionHtml`, calling `/api/insights/corpus-algebra`; the
  comment still says "Browser-unverified per fork-3"; grep-verified). `FUTURE_DEVELOPMENTS.md:2817`
  records it EXECUTED despite its section's "DESIGN-ONLY" banner. `LESSONS.md` (2026-09-09):
  `per_article_intensity` and `conditional_trend` shipped with no caller — "work that exists and cannot be
  reached is indistinguishable from work that does not exist"; the design plan §6 wants "3 newly-wired
  Conjunction-Lens panels". Tests: `tests/test_conjunction.py`, `tests/test_conjunction_picker.py`.
- No claim workspace exists (grep-verified in this brief: `grep -rn -i 'claim workspace\|claim_workspace'
  src/` → nothing); `INVENTORY.md` row V1-E marks A1 UNBUILT. The design: `FUTURE_DEVELOPMENTS.md:1794`
  (A1, six steps ① related articles (FTS) → ② grouped by INDEPENDENCE → ③ who-said-what-when → ④ consented
  corroboration → ⑤ the "what's missing" checklist → ⑥ export the trail, signed) and the action plan's A-2
  ("Build slice 1 with steps ①②③⑤ only; ④ and ⑥ bolt on"; "Done when: a claim typed in the omnibar can
  open the workspace; each step shows its method sentence; the independence grouping is tested against a
  seeded wire-echo fixture; ×12; browser-verified") (grep-verified `sed -n '40,120p'`).
- Onboarding today: the guided wizard IS the first-run entry (`app-backup.js:1947–1965`, ruled 2026-06-13;
  the "corpus is empty" bubble retired 2026-06-17) and the airplane coachmark at `index.html:3175`
  (grep-verified); no tour exists (grep-verified: `grep -rn -i 'onboarding\|guided tour' src/static/` hits
  only those two). The tour has no design of record beyond its name (V1 §3; `OPEN_QUEUE.md` S6.7–S6.9
  "the onboarding tour"). `LESSONS.md` (2026-07-12): an onboarding picker MUST default to everything —
  emphasis ≠ exclusion.
- Signed evidence today: `src/bulletin/evidence.py` ("The owner-only evidence archive … design record §9
  'two exits, one record' and §18"), `src/bulletin/privacy.py` (what a reader of an exported artifact can
  see, §18), `src/custody/signing.py` (grep-verified); `INVENTORY.md` AI-02: the §18 export-privacy
  enumeration shipped 2026-09-07. The dossier: no surface; the entity spine is S05-03.

## 3. Slices — what to build, in order

### S1 — The Claim Workspace A1, slice 1 (steps ① ② ③ ⑤)
- **What:** one entry point opened by an explicit command (never by Enter — Q608 = a): paste or select a
  claim → ① related corpus articles (FTS, the advanced search's compiled query) → ② grouped by
  INDEPENDENCE through lineage + shared-origin links (three echoes of one wire = one path, said so; "we
  found no shared origin" stated as absence of evidence, never as independence) → ③ the who-said-what-when
  timeline → ⑤ the "what's missing" checklist (silent countries / languages / source types; what evidence
  WOULD discriminate). Every step carries its method sentence; the output is a trail, never a verdict; no
  LLM voice by default.
- **Acceptance:** the A-2 "Done when" — the independence grouping tested against a seeded wire-echo
  fixture; each step's method sentence ×12; Chromium-verified in `en` and `ar`.

### S2 — The Claim Workspace, steps ④ and ⑥
- **What:** ④ consented corroboration offers (each behind the ONE online consent, the queried host named
  with the metadata shadow the request reveals — A7); ⑥ export the whole trail as a signed evidence bundle
  through `evidence.py` / `signing.py`, the §18 privacy enumeration and Q1008's attribution lines applied —
  no OSM-derived row until Q823 ⛔ is ruled.
- **Acceptance:** a signed bundle verifies with `custody`; a negative-space fixture proves an OSM-derived
  row is refused from the bundle.

### S3 — The Conjunction Lens across verticals
- **What:** the shipped core reached from every vertical's corpus (press, wiki, law, Places once S05-03
  lands) — the "3 newly-wired panels" of the design plan, each public function of `conjunction.py` given a
  caller or removed (the 2026-09-09 lesson); counts only, the bounded flag and method surfaced.
- **Acceptance:** a grep proving every public name has a call site outside its tests; the Chromium record
  of the picker on two verticals.

### S4 — The dossier seed on the entity spine
- **What:** one entity / topic page joining the rails that exist (news, wiki, law, map, Places) by QID —
  a SEED: it states which rails it joins and which it does not; the ≥ 6 rails bar is 0.8's.
- **Acceptance:** a QID page renders from fixture rows with its rail list and the corpus passport (A-1).

### S5 — The onboarding tour and the signed-evidence polish
- **What:** a tour of the surfaces at the user's Ring (S05-09), skippable, never a narrowing choice
  (defaults to everything; emphasis ≠ exclusion); polish on the evidence export's review screen and
  completion message (R4's shape: what the bundle contains, listed).
- **Acceptance:** the tour driven in `en` and `ar`; the completion message lists the members.

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), each run separately with its exit code captured. Plus: the
wire-echo independence fixture (S1); the signed-bundle verification and the OSM-row refusal fixture (S2);
the call-site grep (S3); the negative-space lens — a claim with zero related articles (the Socratic empty
state, A5: what WOULD be needed), a single-source trail (no independence claim), an entity with one rail;
no field named `score` / `rating` / `ranking` / `grade` in any payload (walk the keys — `"degraded"`
contains `"grade"`); `node --check`; the three i18n gates; the whole-tree guard set; the Chromium
click-through of the workspace, the lens on two verticals, the dossier seed and the tour in `en` and `ar`,
stamped "Chromium-verified (remote sandbox) · awaiting human UX pass".

## 5. Operator steps

1. The maintainer's click-through of each shipped item (Q1128 = a) → the record on each PR.
2. Optional: an evidence bundle exported from the live corpus and verified on a second machine → the
   verification transcript (`not-measurable-here` beyond the fixture).

## 6. What this slice may not decide

- The workspace's placement (a main tab, a palette command, an analysis-window subtab): the design says
  "one entry point"; invariant #2's roster and Q608 constrain it; proposed in the PR body, asked.
- The tour's content and length — no design of record; the brief proposes surfaces-at-the-user's-Ring and
  asks; it never narrows the corpus.
- Which rails the dossier seed joins in 0.5 — stated per PR, never claimed beyond what renders.
- Q823 ⛔: no OSM-derived row in any evidence bundle; the OSM attribution line waits (Q1008).
- Any LLM summary of a trail (optional, labelled, never the default — the A-2 comment) — not built here.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.5_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every §1 ruling in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
