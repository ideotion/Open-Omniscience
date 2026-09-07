# Prompt 23 — The V1 pathway: new verticals and the user-centric flagship

> **Scope:** planning first, then the verticals the maintainer approves.
> **⛔ Gated on G1 (V1-2 … V1-9 — eight rulings), G2 (elections), G4 (IPCC).**
> **Sequencing:** last. Nothing here is urgent and everything here is large; it exists so the direction is
> written down rather than rediscovered.

## 0. Working mode

Read `_WORKING_MODE.md`, then `docs/design/V1_PATHWAY_2026-07-14.md` in full, then the
FUTURE_DEVELOPMENTS sections on user-centric reflections and on elections.

The first deliverable of this prompt is **not code**. It is the eight open rulings answered and the version
train confirmed, because every vertical below is a multi-week build and building one against an unratified
plan is how the largest kind of work gets thrown away.

## 1. The recorded frame

The mission: a free, local-first 360° instrument over the open internet, for citizens and journalists,
worldwide languages, honest AI enhancement, cross-language keyword analytics over news, laws, Wikipedia and
OSM, with track-changes. The V1 plan's own headline is the **recursive improvement loop** —
sense → compare → plan → build → verify → merge and record — human-supervised, explicitly **not** autonomous
self-modification, with the ethics layer constitutionally outside the loop's optimisation reach. The K1–K14
KPI board stands alone per metric, with no composite.

The version train 0.3 → 1.0 is gate-driven across roughly four quarters: 0.4 living sources (laws first, then
one small wiki edition, then editions behind storage milestones), 0.5 the investigator's desk, 0.6
elections and climate, 0.7 patents and medical, 0.8 conflict and the 360° dossier, 0.9 the hardening RC, 1.0.

## 2. Slices

### S1 — Answer the eight rulings (G1)

V1-2 user-supplied API keys; V1-3 restrictive-license policy (the ACLED class); V1-4 PubMed bulk versus API;
V1-5 Windows and macOS at 1.0; V1-6 the KPI bars; V1-7 the storage rulings (already prompt 22's C4; the
**"urgent because create-time irreversible" framing was STALE — corrected 2026-09-07**: §1a
`auto_vacuum=INCREMENTAL` was ruled 2026-07-17 and §1b `page_size=16384` shipped on its evidence pair, and
both are already the defaults in `src/database/connect.py`, so no window is closing); V1-8 whether elections are required for 1.0; V1-9 the
Wikipedia edition-count bar at 1.0.

### S2 — G2: elections, with the coverage floor and the projection tiers

The ruled floor: cover **at least** every country whose official or major language is among the twelve UI
languages, from a dated sourced language→country mapping — never guessed. That becomes the elections
component of the K13 bar.

The three-tier confidence model and its rules belong to prompt 19's agenda work; what belongs here is the
**acquisition**: a parallel internet-connected session researching per-country recurrence rules and official
electoral-authority sources into a dated sourced snapshot (config plus `*_AS_OF` plus a registry entry plus a
freshness test), layered with the Wikidata CC0 snapshot and per-user ElectionGuide freshness where the terms
allow.

The framing rulings that shaped the whole vertical are worth restating because they invert the obvious
design: never "politically neutral" but **plural and transparent about the app's own bias**; never "voting
implications" but **evidence trails the user navigates** — and being LLM-less here is the asset, not the
limitation; never "detect candidates or sentiment or momentum" but curated **sourced** scaffolding plus
descriptive caveated analytics. No horse-race number. No auto-detected candidates. No per-candidate sentiment
verdict. No poll-of-polls forecast.

Poll analysis is an **audit of method**, never of results: build Tier 2 first — a transparency **checklist**,
never a score, plus verbatim question and answer-structure display where the data allows, because that is the
language-agnostic fact and therefore the strongest and safest signal. Non-disclosure always outranks
disclosed imperfection, or the tool punishes transparency.

### S3 — The remaining scenario and manipulation cards

~~Six of nine manipulation cards ship. What is left: the **bury** half of flood/bury (it needs a real external
trigger), the event-timed operation (it needs the elections candidate roster, so it follows S2), and
outrage-intensity, which is secondary by design — it annotates another card and is never a standalone Lead.~~
**CORRECTED 2026-09-07 by the staleness guard this prompt mandates (tree-anchored `main` @ 965e3e54): it is
EIGHT of nine.** The **bury** half SHIPS — `buried_topic` / `find_buried_topics` / `BURY_CAVEAT`, registered
and catalogued, landed in PR #568; its "real external trigger" is the REST OF THE CORPUS (a two-proportion
z-test of the source's topic share against the rest-of-corpus share, BH-FDR corrected). **Outrage-intensity
SHIPS** as `src/analytics/outrage.py`, annotating `headline_body.py` — which is its spec, not a deferral.
**Only #9 (event-timed operation) is open**, and V1-8 (2026-09-07) puts it past 1.0 by ruling, since the
calendar is the 1.0 bar and #9 needs the candidate roster.
`disputed_chronology` and `story_propagation` exist; check before rebuilding. The news-desert atlas and
"warnings existed" remain unbuilt.

The spine that keeps these honest: effective-independent **origins**, not article count; Benjamini–Hochberg
FDR across the daily scan; surprise measured against the corpus's **own** baseline; and convergence as an AND
gate rather than a multiplied probability. Detect **structure**, never deception, intent or truth — labelling
would make this a censorship engine. Every card shows the innocent explanation beside the pattern, and every
producer carries "absence of a flag is not absence of manipulation". A microscope, never a detector.

### S4 — The four new verticals

Each rides the mandatory vertical pattern, in this order, with no step skipped: a dated catalog → a guarded
fetch → a pure parser with a negative-space skeptic → a vintaged store → the three rails (Article, StatFigure,
Agenda) → a distinct provenance class → a surface with visible caveats → per-vertical freshness diagnostics →
the ledger.

- **Climate and environment:** OWID CSVs are the best-verified global data and need only a CSV parser;
  quakes, fires and air quality are largely key-gated (V1-2); ONI is already flagged pending verification.
- **Patents and IP** and **conflict/defense**: no code today.
- **PubMed (V1-4):** the standing is recorded and is not a trust statement — PubMed is **not** a privileged
  source and its "evidence-based" character is a descriptive stance-claim like any statistics agency's. But
  its content database is **architecturally** separate at ~38M records: the managed-dataset pattern, its own
  storage posture on the storage milestones, its own diagnostics, its own filterable provenance class, never
  blended into the news corpus by default. Ingest metadata plus **abstracts** (the always-available layer);
  full text only where open access; a paywalled full text is an honest gap — link out, never scrape around.

The research tables carry per-row verification status (fetched / search-verified / unverified lead) and
fabrication is banned; GDELT-firehose, BigQuery-only and bundled-key sources are de-prioritised for stated
reasons.

### S5 — The user-centric flagship (Plan A)

A1 the **Claim Workspace** — a guided evidence-trail pipeline for non-scientific users that ends in a trail
rather than a verdict — is the flagship and the 0.5 milestone. Around it: A2 the corpus passport, A3 "Your
lens", A6 mention-context honesty, A8 saved analyses, A9 "since you last looked". These are recorded in
FUTURE_DEVELOPMENTS and none is built.

The paradox is recorded and is the reason the promise is worded as it is: an honest tool withholds the simple
answer the audience wants, so the promise changes to *"read the coverage yourself, and catch the manipulation
aimed at you"*.

### S6 — Record-only, so they are not lost

Voice-only mode (accessibility-first, all GUI ethics carried, local STT/TTS via the Ollama path, the mic as a
consent surface, hardware tiers **measured** never asserted). The Open Commons Mirror as a **separate sister
project** — a new repository, only when this one is mature, hosting public open data, never user corpora.
The offline LLM kit. **PRH-34:** the supervised-training track from PR #49. **PRH-35:** the
language-manipulation detector from the maintainer's own never-merged idea file — fallacies, sophism,
euphemism, dysphemism, doublespeak, gaslighting, weasel claims, framing effect, slippery slope, false analogy,
circular reasoning, red herring — and the article-versus-source publication-date delta.

## 3. Scope fence

Do not start a vertical before its ruling. Do not blend a new content database into the news corpus by
default. Do not build a linker, a credibility score, or anything that grades a source's editorial merit.
