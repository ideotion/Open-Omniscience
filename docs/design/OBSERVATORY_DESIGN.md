# The Observatory — the corpus as a night sky (design of record)

**Status: DESIGN-ONLY — nothing built.** Maintainer-ruled 2026-07-18 (in-dialogue);
**supersedes ruling Q5a (2026-07-13)**, which had deprioritized the 3D keyword explorer,
and revives the 2026-06-16 flagship under that entry's own resolution A: **hand-rolled
canvas 2.5D / CSS-3D — no Three.js, no WebGL** (reaffirmed by the 2026-07-13 maps ruling).
Companion to — never duplicating — the 2026-07-18 super-groups brief (whose S1 stats core
is this surface's data spine), the families-entities + Leads-calibration briefs (sky
quality), and `docs/product/UI_SHELL_REDESIGN_PLAN.md`.

---

## 0. Ruled 2026-07-18 (binding)

1. The concept is revived: the keyword hierarchy rendered as a deterministic night sky.
   **Supersedes Q5a.**
2. **Placement: a dedicated main tab** beside the other sidebar tabs (the invariant-#2
   roster grows by one; the tab shows data, #8). **Whole-corpus in v1.**
3. **Name: Observatory** (translates well across the 12 locales; the brand mark is an eye —
   an observatory is where you point one at the sky). **"Telescope" is reserved** as the
   natural name for the LATER per-corpus instrument (a mini-sky inside the analysis window:
   pointing the instrument at one corpus). Explicitly not v1.
4. **Spiral arms carry tags** (the Item-AC topic axis), with the §4 cardinality guard —
   the maintainer's too-many-tags concern is answered by construction, not by pruning.
5. Everything inherits the standing rulings: no composite scores (§0.5), deterministic
   layout (the mind-map rules — no fabricated structure), cross-time recall sacred,
   anti-capping via disclosure, labeled scales (#16), the hover-bubble convention (#17),
   a11y never-the-only-path, zero network (it reads the local corpus only).

## 1. Why the metaphor is honest, not decoration

- Keyword distributions are **Zipfian**; a night sky's magnitude distribution has the same
  shape — few bright, many faint, diffuse background. The corpus already *has* the shape of
  a sky, so it looks right without distorting anything. Most themed visualizations fight
  their data; this one doesn't.
- **Constellation lines are culturally understood as drawn-on interpretation**, not physical
  fact — exactly the honesty needed for association edges (PMI): drawn explicitly, never
  implied by proximity.
- Every visual channel below carries ONE measured quantity with a stated method, or is
  explicitly declared aesthetic. No channel blends measures.

## 2. The mapping

| Sky object | App object | Bounded by (today) | Carried measure |
|---|---|---|---|
| Universe | the corpus | ~500k articles | — |
| Galaxy cluster | scaffold domain | ~12 | sum of member-galaxy measures |
| Galaxy | super-group | 77 | DEDUPED article spread (the S1 stats core) |
| Spiral arm | topic tag within a galaxy | ≤6 rendered (§4) | member count |
| Star system | ring (cross-language concept) | ~540 | aggregated cross-language spread |
| Star | keyword family / keyword | top-N rendered (§7) | mentions (brightness) |
| Planetary ring | language-share of a concept | ≤12 segments | `language_breakdown` counts |
| Planet | per-language ring member | ≤12 | that language's mentions |
| Nova (flare) | a trending spike | gated (§5) | trending_windows rate ratio |
| Nebula | the un-curated long tail | the rest of ~3M | disclosed aggregate density |

The pun lands twice: the project's *rings* render as literal planetary rings, segmented by
language share.

## 3. The polar grammar — what "radius" means (the 2026-07-18 disambiguation)

The word "radius" names three different things; each is pinned separately.

**(a) Star SIZE (the object's own radius) = mention count.** Sqrt-area scaled (the
`sqrtAreaScale` honest-viz rule), with a reference legend of three sample stars
("● this size = 100 / 1k / 10k mentions") because any workable scale is compressive on
Zipf data.

**(b) ORBITAL radius (a child's distance from its parent's centre) = the "importance"
axis — ONE measure per tier, never a blend.** The layout grammar is self-similar polar at
both upper tiers:

- **ANGLE = the categorical axis, labeled.** Universe tier: ~12 domain WEDGES (angular
  sectors). Galaxy tier: tag ARMS (§4). Within a sector/arm, residual angular jitter is a
  stable hash — disclosed as stable-but-meaningless, like alphabetical order.
- **RADIUS = the chosen measure, log-scaled, monotone centre = max, with LABELED orbit
  gridlines** (the #16 discipline; the ooChart `opts.logY` precedent makes a labeled log
  scale accepted practice). Per tier:
  - R0 universe: a galaxy's distance from centre ← the super-group's **deduped article
    spread** (default).
  - R1 galaxy: a star system's distance along its arm ← the ring's aggregated article
    spread.
  - R2 system: a planet's orbit ← **ordinal rank** by that language's mentions (innermost =
    most; uniform spacing, disclosed as rank, not linear value).
- **Default measure = article spread** at R0/R1 — breadth resists single-source flooding,
  the same independence rationale the cards use. **Switchable** via an in-view dimension
  picker (the ooMap grammar): mentions · trend rate · distinct languages · distinct source
  countries. The active measure + method are always visible.

**(c) The literal ring around a concept star** = the language-share donut — a composition
display, not a radial encoding.

## 4. Arms + the tag-cardinality guard

Measured 2026-07-18: the topic taxonomy is **eight tags** in the en baseline (politics ·
economy · health · climate · energy · science · technology · sport), 7 languages covered.
The fear is growth (analyzer-grown + user tags); the guard answers it by construction:

- **Universe tier: clusters = the scaffold's ~12 domains.** PREREQUISITE:
  `configs/keyword_supergroups.yml` names the domains only in a prose comment — an
  additive `domain:` field per group is a small data-curation slice (S0).
- **Galaxy tier: arms = the top K (K≤6) topic tags among that galaxy's members by member
  count**, each arm requiring a minimum membership (proposed ≥5); every other member lives
  in the diffuse **DISC**, labeled "untagged / other (N)" — disclosed, never hidden. A
  spiral galaxy stops reading as one above ~6 arms; the cap is visual grammar, not
  truncation (the disc carries the remainder visibly).
- **Degrade honestly:** while tag coverage is thin (the backfill is young), fewer or zero
  arms render and the disc dominates — never a fabricated arm.

## 5. Honest physics (channel → one measure + method)

- **Brightness/size** = mentions (§3a).
- **Colour** — user-switchable, never blended: **language** (12 hues; proposed default) or
  **temperature = windowed trend** (blue rising · white steady · red cooling — real stellar
  physics: hot stars are blue). Cross-time guard: red means a *measured decline vs the
  prior window, method stated*; an old-but-steady keyword stays white; temperature is a
  chosen lens, never a default that dims history.
- **Novae** = trending spikes, gated with the `supergroup_rising` discipline (count floors +
  FDR across the sky) — a 500k corpus must not render permanently on fire, or the flare
  means nothing.
- **Nebula** = the un-curated tail as diffuse density per region, with the disclosure IN
  the sky: "N stars shown · M keywords in the nebula" (anti-capping: no silent truncation,
  the cap named on the surface itself).
- **Time machine** = the ooTimeScope scrub: the sky within a window; novae flare in their
  spike weeks. Default = full corpus time (cross-time sacred); the scrub is the lens.

## 6. Constellations + determinism

- Association renders as **drawn PMI edges** (above a stated threshold, n shown) — never as
  proximity. Humans read closeness as similarity, so the layout discloses that within-sector
  position is hash-stable and meaningless; the *edges* carry the semantics.
- **Deterministic layout** (the mind-map rule): same corpus → same sky. Users build spatial
  memory, and change becomes signal — a new bright star in a familiar region is
  information. Force-directed layouts are ruled out (they shuffle the sky every visit).

## 7. Rendering + performance (the no-WebGL fit)

A starfield is the one kind of "3D" canvas 2D does beautifully — points, glows, parallax —
so the no-WebGL ruling is a fit here, not a compromise.

- Canvas 2D: glow sprites pre-rendered once on an offscreen canvas, stamped via
  `drawImage`, batched per colour bucket; no per-frame gradients or `shadowBlur`.
- 2.5D = three parallax layers panning at different rates. **Depth is NAVIGATIONAL only**
  (zoom = travel between tiers); data is never encoded in z, and marks are screen-space
  sized (billboards) so perspective can never distort magnitude (the ooViz reject-list
  rationale: 3D foreshortening fabricates area).
- **Static when idle** — no animation loops (the #17 discipline); animate only
  transitions/interactions, rAF-coalesced (the ooMap slider precedent). Zero idle CPU on
  the 2-core reference VM.
- LOD rides the hierarchy: ~12 clusters → 77 galaxies → ~540 systems → bounded top-N stars
  (≤~5k sprites) + the nebula aggregate for the tail.
- a11y: `role="img"` + aria summary + an sr-only ranked list + keyboard traversal (the
  ooMap precedent). The tabular Insights views (Trends / Families / Groups + the mind-map +
  cloud) remain the canonical access path; the Observatory is a redundant lens (#8).
- Themes: colours via the theme variables so all 17 themes inherit. A sky wants dark, but
  light themes must stay legible — the background uses the theme palette, never a
  hardcoded black.

## 8. Data spine (reuse; ONE new endpoint)

- Galaxy masses / rates / dominance ← **the super-groups brief S1 stats core** (dedup +
  windowed rate + dominance disclosure). The Observatory is that core's second consumer;
  **S1 is a hard prerequisite.**
- Star magnitudes + novae ← `/api/insights/top` + `trending-windows` (+series). Edges ←
  `associations` (PMI). Systems/planets ← the rings list + `language_breakdown`. Arms ←
  the keyword-tags facets. Scrub ← ooTimeScope.
- NEW: `GET /api/insights/observatory` — one tiered payload (clusters → galaxies → arm
  tags → systems → top stars + nebula counts), every block carrying method + caveat + n,
  behind `guarded_read` + a statement deadline (the S2.4 discipline), no score-named
  fields (walk the payload keys before shipping — the "degraded"-contains-"grade" lesson).

## 9. Build sequencing (when it builds — not now)

S0 the `domain:` field + i18n keys (tab name ×12) →
S1 the observatory payload endpoint (pure, testable in-sandbox) →
S2 `ooSky` static renderer, universe + galaxy tiers →
S3 interactions (hover = an #oo-tip readout with term · n · method; click a star →
`openAnalysisFor` — keywords are corpora; click a galaxy → zoom travel) →
S4 novae + the time scrub →
S5 arms + constellation edges + the system tier (planets / literal rings) →
S6 a11y + 17-theme sweep + perf pass.

**Gates:** (a) the super-groups S1 stats core lands first; (b) sky quality — the §8 LLM
triage + caps-furniture/entity cleanups (FOTO and VIDEO as the brightest stars would be
honest, but not the first impression to ship); (c) **browser-verify-GATED**: this surface
lives on feel and is NOT conservative-flaggable — the maintainer click-through is the ship
gate for every frontend slice.

## 10. i18n (tab-name candidates ×12; AI-drafted, native review at build)

en Observatory · fr Observatoire · de Sternwarte · es Observatorio · pt Observatório ·
ru Обсерватория · ar المرصد · zh 天文台 · ja 天文台 · hi वेधशाला · bn মানমন্দির ·
id Observatorium

## 11. Open threads (next round of thinking)

- Confirm the R0/R1 default radial measure = **article spread** (proposed; mentions is the
  alternative).
- Colour default = **language** (proposed) vs temperature-as-default.
- K (max arms) = 6 and the per-arm member floor ≥5 — proposed values.
- The Telescope (per-corpus mini-sky in the analysis window) — later, explicitly not v1.
- Whether the domain wedges get fixed compass positions (a stable "map of the heavens")
  or ordering by aggregate size — proposed: fixed positions, for sky stability.
