# Autonomous session brief — entity families at real scale: filters, rings, and the curation surface (2026-07-18)

**Mission.** The maintainer reviewed Insights → Families on the live ~500k-article corpus
(416k indexed · 4,644,445 keywords · 142,605 entities · 34M mentions) and exported the
top-80 entity list plus the observed UI behavior. Three problem classes: (1) the top
entities are dominated by CAPS publishing furniture (FOTO #3, VIDEO #4, LIVE, INFO,
PREMIUM, PDF, RSS) and pure Roman numerals (XIV, III); (2) the same real-world entity is
fractured across scripts/languages (USA / США / ABD / EUA; FSB / ФСБ; NBA / НБА;
NHL / НХЛ) with no layer merging them; (3) the surface itself misbehaves — the kind
dropdown's people/orgs/places return EMPTY lists, "all" returns TWO items, entity
families are single-member by construction so the "you decide" review list offers
nothing to decide, and the blurb describes a model that no longer exists. **Maintainer
doctrine (2026-07-18): everything automated; the manual curation surface moves to
Settings.** This session fixes the filters, automates the grouping, and relocates the
plumbing. **The trusted keyword index is never touched — every grouping change is
display-layer, provenance-carrying, reversible.**

**Executor:** one Claude Code CLI session, LOCAL only (no egress — the networked ring
generation stays an operator step; a curated seed covers the observed cases). Branch
`claude/families-entities-*` off a freshly-fetched `origin/main`, ONE draft PR,
commit-per-slice. House gates: staleness guard on every anchor (verified at `7bb4c0a`,
2026-07-18); adversarial skeptic with the negative-space lens on S2 (the Roman-numeral
rule has real collisions — see there); full local suite green; ledger + shipped.csv rows;
frontend conservative + flagged per fork-3/Q6a (no browser here).

---

## §0 The field evidence (the acceptance cases)

| # | Observed | Defect | Post-fix expectation |
|---|---|---|---|
| 1 | "all" in the kind dropdown → **2 items** (USA, fifa) | `loadFamilies` fetches overall top-80 then filters `kind !== "term"` CLIENT-side — filter-after-limit | "all" aggregates every non-term kind SERVER-side; a full list |
| 2 | people / orgs / places → **empty lists** | the extractor only ever assigns `entity`/`term` (2026-06-16 field log); the dropdown offers taxonomy the data doesn't have | options reflect reality: per-kind counts shown, or dead options removed with an honest note — never a silent empty |
| 3 | FOTO (4274) · VIDEO (4122) · LIVE · INFO · PREMIUM · PDF · RSS as top "entities" | caps headline/web furniture passes the acronym detector (`_ACRONYM_STOP` is tiny: ok/vs/ceo…) | furniture never detected as entities; existing rows clear on the next re-index |
| 4 | XIV · III as entities | pure Roman numerals pass the all-caps rule | strict Roman-numeral tokens excluded — with the collision allowlist (see S2) |
| 5 | USA · США · ABD · EUA all top-80, separately; FSB+ФСБ; NBA+НБА; NHL+НХЛ | families group per-language surface variants only; rings cover lowercase concept terms, not uppercase acronym forms | one grouped display entity per real-world entity, QID/curated-sourced, provenance visible |
| 6 | every entity family has exactly ONE member; blurb says "Trump = Trump's = Donald Trump" | entities are acronym-only since 2026-06-16 (multiword names are terms) — the blurb describes the retired model; single-member rows = nothing to decide | honest blurb; the review list shows only rows where a decision exists |
| 7 | clicking ✕ on a single member wrote `split: USA usa`, `split: ЦСКА цска` | a split override on a family's only member is a meaningless write | guarded no-op (with the hover explaining why); the maintainer's two accidental overrides are theirs to delete via the existing control — do not touch data |
| 8 | the merge/split curation UI lives on a content tab | violates content-first (invariant #8: the UI shows DATA, never plumbing) | curation relocates to Settings; Insights keeps the data view |

## §1 Ground truth (anchors verified at `7bb4c0a`; re-verify — the repo moves fast)

- **Frontend:** `src/static/app.js:9078 loadFamilies` — the filter-after-limit bug is
  `api("/api/insights/top?group=true&limit=80" + kind…)` then
  `top.terms.filter(f => f.kind !== "term")`; the dropdown is `#fam-kind`
  (`index.html:~945`, options `entity|person|org|location|""`); `familySplit` chips
  (the ✕) at `:9091`; `renderFamOverrides:9105` + the override DELETE at `:9140`.
- **Backend:** `/api/insights/top` (grouped path → `queries.top_terms`; verify how its
  `kind` param filters — server-side kind filtering exists for the specific kinds, the
  gap is the "all" aggregation); overrides API `src/api/insights.py:1660–1725`.
- **Entity model:** acronym-only, stored UPPERCASE (`src/analytics/extract.py` — the
  2026-06-16 ruling; `_ACRONYM_STOP:139`; residual emphasis-acronym noise was
  CONSCIOUSLY accepted "to be iterated away via the diagnostics logs" — this export is
  that log, the iteration is due). Kinds `person/org/location` come only from
  gazetteer/spaCy promotion in `extract()` — the 2026-06-16 field log found only
  `entity`/`term` ever assigned; VERIFY with a counts query on the fixture corpus and
  treat the answer as data for S1.2.
- **Rings:** `src/analytics/equivalence.py` (`load_rings`/`ring_of` — language-qualified
  lowercase terms; check the case handling: entity norms are UPPERCASE, so ring lookup
  for entities needs a deliberate seam, not an accident); curated
  `configs/keyword_equivalents.yml` + generated `configs/keyword_rings_generated.yml`
  (curated wins); the generator `scripts/generate_wikidata_rings.py` (networked,
  maintainer-run) already fetches labels+ALIASES via `wbgetentities` — aliases carry
  the acronym forms (Q30 → USA/США/EUA/ABD).
- **Relocation target:** the Settings → Keywords explorer subtab (Item AC S3b,
  `#set-keywords`, `loadKeywordExplorer`) — the established curation home.
- **Precedents that bind:** content-first invariant #8; the stoplist architecture
  lesson (collision behavior per channel); "a wrong merge is worse than none"; the
  no-score walkers; visible provenance (`conflated_by`, ring `members`).

## §2 The slices

### S1 — The kind-filter bugs (backend-first, testable here)
1. **"all" aggregates server-side.** Give the grouped top endpoint an explicit
   non-term mode (e.g. `kinds=` list or `families=1`) that applies the kind filter
   BEFORE the limit and returns the top-N across entity+person+org+location. The
   frontend's client-side `filter(kind !== "term")` goes away entirely — display
   only. Pin with a fixture where terms outnumber entities 100:1: "all" must still
   return the full entity list (§0 row 1).
2. **The dead options tell the truth.** Query the real kind distribution. If
   person/org/location are unpopulated (expected), the dropdown must not offer them
   as silent empties: either drop them until a real NER/gazetteer pass populates the
   kinds (out of scope here), or keep them with live counts ("people (0)") plus the
   honest note that the extractor does not yet assign these kinds. Choose the
   simpler; never fabricate taxonomy (§0 row 2).

### S2 — Furniture + Roman numerals out of the acronym detector (⚠ skeptic slice)
1. Extend the acronym stoplist with the CAPS-furniture batch evidenced by the export:
   FOTO, VIDEO, LIVE, INFO, PREMIUM, PDF, RSS (review the export's tail for more
   candidates — e.g. APP-class tokens — but ship only what the evidence shows;
   speculative additions are forbidden). COLLISION SAFETY by construction: the stop
   operates at the acronym-DETECTION layer on standalone ALL-CAPS tokens only — the
   lowercase content words (it/es/pt "foto", en "live"…) are untouched terms. State
   this in the code comment.
2. Exclude STRICT well-formed Roman numerals (canonical-form validation, length ≥ 2,
   e.g. II, III, IV, XIV, XVI, MMXXVI) from entity detection. ⚠ **Negative space the
   skeptic must attack:** real acronyms that ARE valid Roman numerals — LIV (LIV
   Golf), DC, CD, MI, DI, XL… The conservative shape: exclude only when the token
   validates as a canonical Roman numeral AND is not on a small evidence-grown
   allowlist (seed: LIV, DC, CD, XL, MC, DM, CM); the skeptic enumerates further
   collisions before push. A wrong exclusion (a real org vanishing) is worse than a
   leftover numeral.
3. Forward-only, like all extraction changes: existing corpus rows clear on the next
   "Clean up keywords" re-index — an OPERATOR step, stated in the PR body.
4. Update the keyword self-test + engine-report goldens that touch acronym behavior
   (grep the test tree for the affected tokens first — the stale-anchor lesson).

### S3 — Cross-script entity unification (the automation the maintainer asked for)
1. **Curated seed now** (no network needed): add entity alias rings for the export's
   observed cases to `configs/keyword_equivalents.yml` — united-states
   (USA/США/EUA/ABD + the lowercase concept members already ringed), fsb (FSB/ФСБ),
   nba (NBA/НБА), nhl (NHL/НХЛ). Hand-curated, common-knowledge verifiable, the same
   legitimacy as the existing curated rings.
2. **The case seam:** entity norms are UPPERCASE; ring membership is lowercase — make
   the ring lookup for entity-kind keywords deliberate (case-aware member matching or
   explicit uppercase members), never an accidental miss. Grouped views
   (`top_terms`/`trending`/families display) then merge them with the ring's visible
   `members`/`language_breakdown` provenance — the existing honest-merge machinery.
3. **Generator extension** (the scale path, runs on the maintainer's networked
   machine): `generate_wikidata_rings.py` gains an alias/acronym emission — the
   `wbgetentities` payloads it ALREADY fetches carry the per-language aliases; emit
   uppercase acronym members alongside the lowercase labels, QID-sourced. Pure-parse
   fns fixture-tested offline, as before. The RUN is the operator's.

### S4 — The surface: automate-by-default, curation to Settings (conservative + flagged)
1. Relocate the merge/split curation (the checkboxes, Merge button, ✕ chips, the
   overrides list) to Settings — beside the Keywords explorer subtab, its natural
   home (the Sources/Collect/Wikipedia precedent). Insights → Families keeps the
   DATA view: the grouped families with provenance pills, no curation controls.
   Nothing is lost (the Desk rule) — absorption-guarded by an invariant test.
2. The relocated review list shows only rows where a DECISION exists: multi-member
   families, ring-merged groups, and rows with manual overrides — never thousands of
   single-member rows (§0 row 6).
3. Fix the blurb: entities are standalone acronyms; multiword names are terms; the
   Trump example goes (§0 row 6).
4. Guard the single-member ✕: no override write, a hover explaining there is nothing
   to split (§0 row 7). The maintainer's two accidental overrides stay untouched —
   theirs to delete via the existing control.
5. i18n: keyed strings ×12 where the surface is keyed; the un-keyed-English
   convention where it is not — match the neighborhood, state which.

## §3 Binding honesty rules

Never fabricate kinds or merges: a grouping either has QID/curated provenance or it
does not happen. Every automated merge stays visibly provenanced (ring members /
`conflated_by`) and reversible (split overrides win — user wins over every automatic
rule, unchanged). The trusted index (`extract.py` normalization, stored keywords,
FTS) is untouched except the DETECTION stoplists in S2 — which prevent junk from
being extracted at all, exactly like every stopword batch before them (forward-only,
re-index clears history). No score anywhere; the no-score walkers run on changed
payloads. Empty is shown as empty with the reason, never silently.

## §4 Out of scope

Populating person/org/location kinds (real NER = the LLM-perception track, gated on
its eval harness); the §8 LLM keyword triage (parked, operator rig); reclassifying
Russian common-noun abbreviations (СМИ/БПЛА/НПЗ — descriptive kind, harmless);
lemmatization (its own merged brief); any change to ranking.

## §5 Definition of done

§0 rows pinned as tests and green (the "all" aggregation fixture; furniture/numeral
negative-space both directions; the ring seam merges USA/США in a grouped view;
the single-member guard); skeptic recorded on S2; full suite green; node --check +
invariant guards on S4; ledger + shipped.csv; one draft PR onto `main` whose body
maps each §0 row to what the same click now shows. Field acceptance: the maintainer
re-opens Families on the live corpus — "all" lists everything, the top entities read
FIFA/NATO/BBC/CNN instead of FOTO/VIDEO, and USA appears once.
