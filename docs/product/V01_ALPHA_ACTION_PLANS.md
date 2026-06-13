# V0.1 ALPHA — The Two Action Plans (canonical, retrievable)

> **Status:** maintainer-commissioned 2026-06-12; awaiting maintainer review.
> This file is THE retrievable home of both plans. The analyses they come
> from: FUTURE_DEVELOPMENTS § "User-centric reflections" (the thinking
> behind Plan A) and `docs/audit/07_TRANSVERSAL_AUDIT_V01.md` (the findings
> behind Plan B). The RC gate (`RELEASE_0.1_RC_GATE.md`) carries the
> arbitration rows.

## The commission (verbatim, for recall)

> "make an overall user centric / user based approach and think of user
> scenarios and come up with reflective and rational critical comments
> about our app. These analysis, based on contradictory reflections should
> help you deduce new functionalities, new tools, UI enhancements and
> overall new app functionality. These reflections should be inserted into
> the future development plan for me to review later on. Be reflective.
> Step back in order to reflect on this app's core truth-seeking, ethically
> and scientifically sound intentions. Think of anything that would help
> users. Think of anything that would help those users who might not have a
> scientifically sound approach, so that the app guides them through
> scientifically sound approaches in order to reflect on what is true and
> deducible from the app. Then make an action plan into future
> developments. After you're done with all this, I'd like you to perform a
> transversal audit of the app. The audit shall cover all topics: each and
> every tool's rational (is it science proof? Does it convey the truth? To
> what extent? Is the user fully informed through the GUI?) can the app be
> tampered with? Does it have enough performance after long use? What data
> does it miss to convey? What types of data sources should it incorporate
> to increase / extend the user's world view? Is the data properly
> reflected through the algorithms? How can we measure data neutrality and
> proper representation? What about missing data? What about
> over-represented data? What about the aggregator's biases? Which types of
> biases does the app suffer from? How can we correct them? Can it be
> solved through updates? If yes, how? These are only preliminary
> questions, there are many many more we should ask ourselves. Please make
> a thorough and critical analysis and deduce a multi step approach to
> resolve everything with a sound, ethically and rationally oriented
> approach. Make another action plan with your findings."
> — maintainer, 2026-06-12 (toward V0.1, the first ALPHA)

---

# ACTION PLAN A — the user-guidance track

*Goal: a user WITHOUT scientific training can walk from "I saw a claim" to
a defensible, honest conclusion, guided by the app — without the app ever
issuing a verdict.* Steps are ordered; each carries its rationale and my
comment, as asked.

### A-1 · Disclosure pair: corpus passport + lexical-limits caveat
**What.** (i) A compact, constant strip on every analytics surface stating
what the view was computed on: *n articles · sources · countries ·
languages · date span*. (ii) A stated caveat on every keyword surface:
counting words is not reading meaning (negation, quotation, sarcasm are
not understood).
**Rationale.** The deepest structural risk is a SAMPLE read as the WORLD
(contradiction C1) and WORDS read as MEANING (C5). Both are cured first by
visibility, not by features; everything later in this plan stands on the
user knowing what the numbers are made of. Cheapest step, largest
honesty-per-line ratio — that is why it is first.
**My comment.** Resist making the passport collapsible-by-default; the
informed-consent ruling says visible-by-default, layered detail on hover.
The risk is banner-blindness — keep it one line, data-dense, no prose.
**Done when.** Passport renders on Insights/trends/corpus windows/cards
header; caveat on keyword views; both ×12 locales; invariant-tested.
**Depends on.** Nothing — existing substrates.

### A-2 · The Claim Workspace (flagship)
**What.** One entry point: the user pastes or selects a CLAIM. The app
walks a visible, stated pipeline: ① related corpus articles (FTS) →
② grouped by INDEPENDENCE (lineage + shared-origin links: three echoes of
one wire = ONE path, displayed as one) → ③ who-said-what-when timeline →
④ consented corroboration offers (weather now; statistics/IPCC when those
land) → ⑤ the "what's missing" checklist (which countries, languages,
source types are silent; what evidence WOULD discriminate the claim) →
⑥ export the whole trail as a signed evidence bundle.
**Rationale.** Users come asking "is it true?" and the app rightly refuses
verdicts (no composite scores — non-negotiable). The honest resolution of
that contradiction (C3) is an ANSWER-SHAPED process: the workspace gives a
verdict's rigor without a verdict's arrogance, and it TEACHES method by
doing — exactly the commissioned "guide them through scientifically sound
approaches". It is the single highest-leverage feature for the
non-scientific user, and ~80% of its machinery already exists (FTS,
lineage, article_links, evidence bundles, the corroboration cards) — this
is composition, not invention. That is why it is the flagship and not a
moonshot.
**My comment.** Two design risks to hold the line on: (a) step ② must
never present independence as certainty — "we found no shared origin" is
absence of evidence, said so; (b) the temptation will be to summarize the
trail with an LLM — fine as an OPTIONAL, labeled convenience, never as the
default voice of the result. Build slice 1 with steps ①②③⑤ only; ④ and ⑥
bolt on.
**Done when.** A claim typed in the omnibar can open the workspace; each
step shows its method sentence; the independence grouping is tested
against a seeded wire-echo fixture; ×12; browser-verified.
**Depends on.** A-1 (the passport frames the workspace's honesty).

### A-3 · "Your lens" — the corpus self-portrait
**What.** One dedicated view unifying the existing diet/coverage signals:
corpus composition vs ≥2 DECLARED baselines (population, internet users —
each labeled as a normative choice), concentration (Gini/entropy),
single-origin share, wire-dependence share, collection-time regularity;
with one-click "broaden" suggestions from under-represented regions of the
catalog. Descriptive ONLY.
**Rationale.** The app cannot and must not curate the user's sources
(sovereignty), yet a self-selected corpus is a bubble the analytics will
faithfully describe (C2). The only ethical counterweight is a mirror, not
a hand on the wheel: make the skew impossible to miss and one click away
from acting on — the user stays the agent. Plural baselines because
"neutral" has no single definition (audit §5); declaring them is the
honesty.
**My comment.** The danger is moralizing. Numbers and a "broaden"
affordance, zero judgment language. Auto-reweighting remains forbidden —
it would be silent editorializing (audit's hard line).
**Done when.** The view exists with ≥2 baselines side by side + the three
share metrics; every metric carries method+n; ×12.
**Depends on.** A-1; audit B-4 (same dashboard — built once, listed in
both plans deliberately).

### A-4 · Teaching recipes (guided investigations)
**What.** Narrated multi-step recipes chaining REAL tools: "Follow a story
to its origin", "Watch one event through five countries", "Test a folk
belief with multiple-comparison discipline" (the lunar framework as
curriculum).
**Rationale.** S5 (educators) and S2 (citizens) learn method by walking
it, not by reading about it; the recipe machinery (cards → /investigate)
already exists, so the cost is authoring, not engineering. Placed after
A-2 because the workspace IS the primary guided path; recipes generalize
it.
**My comment.** Keep each recipe ≤5 steps and end every one at a "what
this does NOT prove" panel — the lesson is the limit.
**Done when.** ≥3 recipes ship, each browser-walked, ×12.
**Depends on.** A-2.

### A-5 · The Socratic empty state
**What.** Wherever data cannot answer, the surface says what WOULD be
needed (more sources from region X, a longer window, an independent data
type) instead of showing a thin result.
**Rationale.** Thin results invite over-reading — the exact failure mode
of the untrained user (S2). Saying "not answerable yet, and here is why"
is more scientific than any chart; it generalizes the power-style
"what's missing" already queued for evidence-tiered cards.
**My comment.** This is a sweep across existing surfaces, not a feature;
batch it with A-1's caveat sweep to touch each surface once.
**Done when.** The major analytics views render the guidance under a
defined n-threshold; ×12.
**Depends on.** A-1 (same sweep).

### A-6 · Mention-context honesty (negation/quotes)
**What.** Slice 1: per-language heuristic FLAGS on mentions — negated
("no drought"), quoted speech — shown as split counts, labeled heuristic.
**Rationale.** C5 again, but now structural instead of disclosed: the
single most misleading artifact of lexical counting becomes visible.
Heuristics (negation windows, quote spans) are honest if labeled; full
semantics is out of scope and said so.
**My comment.** Per-language quality will vary wildly — ship with a
per-language coverage note, and let A-1's caveat carry the residual.
**Done when.** en+fr negation/quote flags measured against a hand-checked
sample (precision reported in-repo), counts split in the UI.
**Depends on.** A-1 shipped (the caveat covers languages the heuristics
don't).

### A-7 · Consent metadata-shadow line
**What.** One sentence in every network-consent popup naming what the
queried host could infer from the request pattern (e.g., weather fetches
reveal which places/windows your corpus examines).
**Rationale.** Informed consent (the app-wide ruling) currently names the
ACTION; the inference shadow is the half not yet said. Cheap, ×12, and
squarely in the project's honesty DNA (C6).
**My comment.** Keep it factual, not scary — one clause, hover for the
long form.
**Done when.** All ensureOnline reasons carry the line; ×12.
**Depends on.** Nothing.

### A-8 · Saved analyses with corpus-state stamps
**What.** A re-runnable record of an analysis: query/params + the corpus
passport at run time; re-running shows then-vs-now.
**Rationale.** Reproducibility for one's own past conclusions (S3) — and
for S2 it quietly teaches that conclusions are dated: the same question on
a grown corpus may answer differently, which is the scientific posture in
miniature.
**My comment.** Storage is trivial (one table); the honest subtlety is
that old runs are NOT re-creatable exactly (the corpus moved) — show the
two passports side by side rather than pretending to time-travel.
**Done when.** Save/list/re-run with passport diffs; rides the backup.
**Depends on.** A-1 (passport is the stamp).

### A-9 · "What changed since I last looked"
**What.** A since-last-visit factual diff: new sources' first articles,
new flagged edits, watch-rule hits (when T19 lands).
**Rationale.** Honest retention: S2 returns to facts, not to an
engagement feed. Last because it is value-add, not integrity.
**My comment.** No badges, no streaks, no red dots — the anti-engagement
discipline is the point.
**Done when.** One Home block, dismissible, ×12.
**Depends on.** Nothing hard; better after A-1.

**Plan-A sequencing rationale.** A-1 first because every later surface
inherits its honesty; A-2 second because it is the commissioned core
(guide the untrained) with the best leverage-to-cost; A-3 third as the
standing counterweight to self-selection; the rest are sweeps and
compounding gains ordered by integrity-before-convenience.

---

# ACTION PLAN B — the audit-remediation track

*Goal: every audit finding either fixed, measured, or permanently and
visibly disclosed — never silently accepted.* Findings live in
`docs/audit/07_TRANSVERSAL_AUDIT_V01.md`; steps below carry rationale +
my comment, as asked.

### B-0 · Maintainer arbitration of severities
**What.** You confirm/adjust the proposed severities (B-1 proposed
RC-BLOCKING; B-2/3/4 SHOULD; rest POST) in the RC gate rows already added.
**Rationale.** Severity is a values call, not an engineering call — the
audit proposes, the maintainer disposes (the project's own propose/dispose
ethic applied to ourselves).
**My comment.** I deliberately did NOT pre-mark everything blocking:
an alpha with honest disclosures beats a delayed alpha chasing
completeness — disclosure converts known gaps into informed-consent
items, which is the app's own standard for itself.

### B-1 · The disclosure sweep (proposed RC-BLOCKING)
**What.** Eight statements, visible-by-default, ×12, test-enforced:
VADER tone = English-only (other languages unscored — said where tone
shows); LLM outputs labeled "generated by a local model — verify against
the stored text"; lexical-limits caveat (shared with A-1); text-only
modality statement; CJK keyword gap stated while unfixed; permissive-host
survivorship sentence on coverage surfaces; "your record begins
YYYY-MM" on trend views; Wikipedia systemic-bias note in the manual.
**Rationale.** These are the audit's only two ❌-class findings plus their
siblings: places where the app currently lets a user believe an analysis
covers more than it does. They are cheap (strings + tests), and they are
the difference between "honest by construction" being a slogan or a
property. Proposed blocking because shipping an alpha that silently
under-analyzes non-English corpora would contradict the project's first
principle.
**My comment.** Enforce each in `test_repo_invariants` — disclosures
regress silently otherwise (the project learned this lesson once already
with the Wikipedia dropdown).

### B-2 · The local fixity audit tool (proposed SHOULD)
**What.** On-click: re-hash every stored article against its capture
hash; loud report of any divergence; nothing auto-fixed.
**Rationale.** The reliable-memory pillar turned inward — the app
preaches tamper-EVIDENCE for the world's data; its own corpus deserves
the same check. The substrate (per-article hashes) already exists, so
this is a day's work with outsized trust value.
**My comment.** Divergence will occasionally be benign (encoding
migrations); report, never auto-repair, and keep the tool's own output
exportable as evidence.

### B-3 · Scale proof at 100k articles (proposed SHOULD)
**What.** Extend `scripts/perf_harness.py` with a 100k profile; measure
briefing recompute, corpus windows, FTS rebuild, backup, migration;
fix what breaches the existing thresholds; DESIGN (not build) consented
archiving.
**Rationale.** T1 proved the measure→fix→re-measure loop at the reported
scale; a year of continuous collection is ~15× that, and the honest
position is "measured", not "should be fine". Archiving is design-only
because silent deletion is forbidden and the right UX needs the
maintainer's eye.
**My comment.** The wiki per-revision full-text store (just ruled) is the
newest unknown — include a heavily-edited-pages profile in the harness.

### B-4 · "Your lens" dashboard v1 (proposed SHOULD)
**What/Rationale/Comment.** = Plan A-3 — one build, two mandates. Listed
in both plans on purpose so neither review misses it.

### B-5 · Language-equity slice (proposed SHOULD)
**What.** CJK segmentation as an optional extra (jieba-class for zh,
equivalent for ja) + an in-app per-language capability matrix (which
analyses actually function per language).
**Rationale.** The audit's sharpest inequity: the UI ships in zh/ja while
keyword extraction silently does ~nothing for them. Disclosure (B-1)
makes it honest; this step makes it BETTER — in that order, so honesty
never waits on engineering.
**My comment.** Segmenter quality varies; the capability matrix should
mark these "heuristic, newly enabled" for a release rather than
over-promising parity.

### B-6 · Design notes, no build (POST)
**What.** Three short designs: cross-transport spot-check protocol
(against source-side cloaking — consented, sampled, divergence = a
finding); consented archiving UX; new-source onboarding order (official
statistics → scholarly+retractions → fact-checks-as-stanced-sources →
PR-wires-as-origin-detectors → courts/NGO).
**Rationale.** Each touches ethics or scope enough that building before a
maintainer pass would be presumptuous; writing the designs now keeps the
weekend's momentum without overstepping.
**My comment.** The retraction feed is the one I'd pull forward if you
want a quick truth-seeking win — small surface, high signal.

### B-7 · Re-audit delta + alpha go/no-go
**What.** Re-run audit 07's checklist against the fixed state; publish
the delta; alpha ships when every RC-BLOCKING row is ✅.
**Rationale.** An audit without a re-audit is a press release. The delta
document is also the alpha's honesty artifact — shippable in release
notes, in the project's voice.
**My comment.** Keep audit 07 immutable and write `08_DELTA`; history
unrewritten, per the project's deepest pillar.

**Plan-B sequencing rationale.** B-0 gates everything (severities are
yours); B-1 before all features (honesty first, always); B-2..B-5
parallelize cleanly (different files, different skills); B-6 stays
design-only pending your pass; B-7 closes the loop. Interleave with Plan
A as: B-1+A-1 (one disclosure batch) → A-2 → B-4/A-3 → B-2 → B-3 →
A-4..A-9 + B-5 → B-6/B-7.

---

*Both plans await your review; nothing here builds before your pass except
where a step is already independently ruled. Every step above names its
rationale; every comment is mine and marked as such.*
