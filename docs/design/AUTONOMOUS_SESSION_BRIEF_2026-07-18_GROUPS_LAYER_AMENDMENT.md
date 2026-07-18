# Amendment brief — the GROUPS layer: naming, the circle grammar, group stats, the concept map (2026-07-18)

**This AMENDS and extends `AUTONOMOUS_SESSION_BRIEF_2026-07-18_SUPERGROUPS.md` — one and
the same executing session delivers both.** Read that brief first; its sequencing
(after the Leads-calibration + Families-entities executions), house gates, and honesty
rules all apply unchanged. This amendment adds four maintainer-ruled pieces
(2026-07-18): the user-facing NAMING of the keyword hierarchy, the universal CIRCLE
marking (with theme-safe color emphasis), GROUP-level statistics sharing the same
primitive, and the cross-country concept-map upgrades (picker, clickable countries,
deep links).

---

## §A The naming sweep — keyword → group → super-group (UI-only, ×12)

**Ruling.** The user-facing hierarchy is **keyword → group → super-group**. The
containment lives in the morphology itself — *super-X contains X* reads correctly in
every locale (supergroupe / Supergruppe / supergrupo / супергруппа / 超组 /
スーパーグループ / supergrup) — no metaphor to translate. "Theme/concept" was
considered and REJECTED (ambiguous containment direction; uneven translation).

- **"ring" disappears from the UI entirely** (it stays the internal name, exactly like
  `briefing` after the cards→Leads rename): the `ring·N` pills in the curation chrome,
  the map header "Pick a cross-language ring…" (`index.html:972`), the add-a-ring
  controls, every user-visible occurrence → "group". A group's defining property —
  ONE keyword counted across every language — moves to the subtitle/hover, not the name.
- **Resolve today's collision:** the Insights subtab currently labelled "Groups" shows
  SUPER-groups — after the sweep, labels must say what they hold (the subtab becomes
  "Super-groups" or the two-level surface; pick the cleaner and state it).
- **Families stay invisible as a layer:** automatic variant-collapsing WITHIN the
  keyword level (the maintainer's "three layers, simple" framing) — never presented as
  a fourth navigable tier.
- Keyed strings ×12 where the surface is keyed (the map header is static
  `index.html` = keyable); the un-keyed-English convention where the neighborhood is
  un-keyed (the sg curation chrome) — match, and state which in the PR. NO internal
  identifier / API path / config key changes (the Lead-rename precedent: user-facing
  labels only).

## §B The circle grammar — one circle = group, two circles = super-group

**Ruling.** Level marking is UNIFORM across the entire UI: plain chip = keyword,
**single circle = group**, **double circle = super-group**. The circle COUNT encodes
the level (one grouping applied; a grouping of groupings) — containment made visual
with no metaphor.

1. **Mechanics:** two CSS classes (e.g. `.lvl-group` / `.lvl-super`) drawing one/two
   ring outlines (box-shadow rings — no layout shift; invariant-#3 constant-footprint
   discipline). Applied EVERYWHERE a level appears: chips, headers, pickers, the
   breadcrumb, search results, the coming super-group cards, the keyword→group chips
   from the sibling brief's S3. One MutationObserver-free, class-based convention —
   like the #oo-tip marking, it must be impossible to forget on future surfaces
   (an invariant test greps for the classes on the known surfaces).
2. **Color emphasis (maintainer: yes, if theme-compatible):** two semantic variables
   (e.g. `--lvl-group` / `--lvl-super`) defined ONCE, derived from each theme's own
   tokens via `color-mix` (never hardcoded hues) — all 17 themes inherit
   automatically. **The #23 caveat-color lesson is binding:** verify contrast by MATH
   across all 17 themes' panels before shipping (the hardcoded-hue attempt failed
   8/17). Color is the REINFORCING signal only — never the sole differentiator
   (color-blind/monochrome users read the circle count).
3. **A11y:** every marked element carries the translated hover ("a group: one keyword
   counted across every language" / "a super-group: several groups under one theme")
   + an aria-label stating the level — the standing hover-for-information convention.
4. **The breadcrumb:** the "path" chip renders wherever any level appears —
   `⦾⦾ Climate change ▸ ⦾ temperature ▸ температура (ru)` — every segment clickable
   (the breadcrumb IS the level navigation). Plural super-group membership = multiple
   ⦾⦾ segments offered, never silently picking one (consistent with the sibling
   brief's S3 chips).

## §C Group-level statistics — the same primitive, one level down

The sibling brief's S1 resolution primitive (member keyword-ids → windowed
series/rate via the existing rollup + trending grammar) serves BOTH levels: a group
is simply a smaller member set (its per-language terms). Add the group-level stats
endpoint/payloads with the disclosure ADAPTED to the level: for super-groups it is
top-MEMBER dominance; **for groups it is top-LANGUAGE dominance** ("ru carries 61% of
this group") — the honest equivalent one level down, fed by the existing
`language_breakdown`. Same rules: counts/ratios only, no composite, `basis`/as-of
disclosed, deadline-guarded. The `supergroup_rising` producer stays super-group-level
ONLY (77 groups is a reviewable card population; 540 is not — a group-level card
family is explicitly OUT of scope this session).

## §D The cross-country concept map (the surface the maintainer praised)

Anchors (verified at `fbcc307`): `src/analytics/queries.py:528 ring_country_split` ·
`src/api/insights.py:1480 /ring-countries` (cached `_ckey:1496`) · the frontend view
at `src/static/app.js:9197` + the header at `index.html:972`.

1. **Kill the dropdown — the two-tier circled browse:** the picker becomes super-group
   chips (⦾⦾) → click one → its group chips (⦾), plus a type-ahead filter box
   (omnibar grammar) for direct access over the ~540 group ids/labels/members. The
   picker itself teaches double-contains-single on first use. Keep keyboard
   navigation (the ooSubtabs/roving-tabindex conventions).
2. **Clickable countries (the maintainer's found bug):** every country row/bar drills
   into the exact corpus — the group's member keyword-ids ∩ producing-source country
   → article ids → `openAnalysisForIds` (the established exact-set seeding; resolve
   ids via the mention tables by keyword-id + the denormalised source country — NEVER
   the keyword→articles codec join). **The "not mapped" bucket is clickable too** —
   unlocated-source coverage is an investigable corpus (in the maintainer's export it
   was the largest bucket: 717 articles); an honest label without a door contradicts
   the door-everywhere principle.
3. **Arrive-from-anywhere:** every ⦾ group chip in the app deep-links to this map
   pre-seeded (analysis window, search, the super-group view) — the map stops being a
   destination you configure.
4. **The located-share honesty line:** the map states that its coverage grows as
   source countries are filled in (the ~49% unlocated share is the data lever — the
   standing Wikidata source-country generator run, operator-side; not a UI fix).
   Keep every existing honesty line (null bucket never dropped, counts only, never a
   credibility ranking, the conservative unknown-language exclusion).

## Verification additions (on top of the sibling brief's §5)

- The naming sweep: `--audit-chrome`/i18n gates stay green; a grep-level guard that
  "ring" no longer appears in user-visible strings on the swept surfaces (internal
  names exempt).
- The circle grammar: the contrast MATH check across 17 themes recorded in the PR
  body (the #23 precedent); an invariant test pins the classes + variables + the
  a11y hovers on the known surfaces.
- The map drills: a fixture test that country-drill ids == (group member ids ∩
  country) exactly — a wrong id set silently seeding the analysis window is the
  §1-Conjunction-lens hazard class; and the null-bucket drill returns the unlocated
  set.
- Frontend remains conservative + flagged per fork-3/Q6a (browser-unverified here);
  the maintainer's click-through of the map is the field acceptance: pick a group in
  two clicks, click Italy, land in the Italian-source temperature corpus.
