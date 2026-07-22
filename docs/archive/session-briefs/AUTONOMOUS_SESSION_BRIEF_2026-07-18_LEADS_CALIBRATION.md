# Autonomous session brief — Leads/card-system calibration at real scale (2026-07-18)

**Mission.** The maintainer ran the card system on a live ~half-million-article corpus and
exported the resulting Home Leads feed (2026-07-18, pasted verbatim into the session — the
defect examples below are quoted from it). Verdict: **the honesty layer held, the selection
layer broke.** Every card states its method and caveats truthfully, but the producers were
calibrated on a ~2k-article corpus; at 500k the base rates invert and the feed is dominated
by artifacts that are each "honestly described" yet collectively bury the real signals.
This session fixes the selection layer: wire the existing noise filters into the producers,
fix two genuine statistical artifacts, add per-language capability gates, make thresholds
corpus-relative, add cross-card dedup, and close the loop with a repeatable leads-quality
diagnostic. **No new producers. No new judgment. The honesty conventions are untouched.**

**Executor:** one Claude Code CLI session, LOCAL only (no egress needed — every fix is
analytic). Branch `claude/leads-calibration-*` off a freshly-fetched `origin/main`, ONE
draft PR, commit-per-slice. House gates apply: staleness guard FIRST on every anchor
(this file was anchor-verified at `56c0e86`, 2026-07-18 — re-verify, the repo moves fast);
adversarial skeptics complete BEFORE push on every statistical change (negative-space
lens mandatory: feed each fixed producer inputs that SHOULD produce nothing and assert
they do); full local suite green; ledger + shipped.csv rows at close.

---

## §0 The calibration corpus (the maintainer's 2026-07-18 export — the acceptance cases)

The observed defects, verbatim from the live feed. Every slice below must turn its rows
into pinned regression tests (fixture-level where the data can be synthesized; the
expectation column is the acceptance bar):

| # | Card as observed | Defect | Post-fix expectation |
|---|---|---|---|
| 1 | source laundering: "77 sources, one origin: **policies.google.com**" (n=3807) | infrastructure/boilerplate domain as "origin" | never a candidate origin |
| 2 | source laundering: **policies.google.com again** as a second card (55 sources, n=3780) | same origin fired twice | one card per registrable origin domain |
| 3 | source laundering: **addtoany.com** (share widget), **creativecommons.org** (license footer) | page furniture as origins | never candidates |
| 4 | flooded topic: RTV SLO "flooding **vir**" (Slovenian for "source" — the "Vir: STA" attribution line) and "**lani**" ("last year") | publishing furniture / language artifact as a topic | furniture terms never flood-candidates |
| 5 | flooded topic: Dainik Bhaskar "**टिकट**", z=5.85 on **3 articles** | z-test on a count where the normal approximation is invalid | count floor (or exact test); no card at n=3 |
| 6 | lonely signal: **three cards, all GIGAZINE** | single-source is the NORM at 500k; no per-source cap | per-source cap + scale-aware selection |
| 7 | capacity implausible: "**Imported newsletters (.eml)** averaged ~176/day" | the user's own bulk-import channel flagged as a suspicious publisher | internal channels exempt (disclosed in method) |
| 8 | space-time convergence: "99 sources converge on **Venezuela**", Iran, "**Usa (US)**", Washington | country-level convergence on major-news countries is the base rate; "Usa" casing; members include off-topic articles | surprise vs the place's own baseline; canonical country display |
| 9 | weather corroboration: separate cards for "**Allemagne (DE)**" and "**Deutschland (DE)**" | same country, two surface strings → two cards | dedup by country code, not surface name |
| 10 | weather/convergence members like "*La Libre.be - Suivez en direct toute l'actualité…*", "*People : toutes les infos sur…*" | homepage/section captures as evidence articles | suspected non-articles excluded from members |
| 11 | ownership change: "*Israelul merge la urne… Netanyahu*" (Romanian election piece) | English deal-verb regex matched cross-language | gate on language the verb list covers |
| 12 | headline-body mismatch: four cards, all lexical_div = **1.0**, incl. two Estonian | inflected-language surface forms can never match → guaranteed divergence | per-language capability gate; those inputs produce no card |
| 13 | supply-chain ripple: "**LEAD** co-moves with *end / run / down / life*", r=+0.98 | (a) commodity symbol matched the English word *lead*; (b) raw daily-count series → total-volume confound: all common words co-move | exact-symbol/label keyword mapping; share-normalized series; those pairs produce no card |
| 14 | price narrative: CORN r=0.17 **p=0.721**; COFFEE p=0.712; BRENT p=0.514 | statistically null results surfaced as Leads | null results stay in the exploration view, never a Lead |
| 15 | story propagation: "**data**", "**media**", "**social**", "trump" spread across 100+ sources | generic open-class terms as "stories"; ubiquitous spread is the base rate | DF-ubiquity gate; generic terms never candidates |
| 16 | diet self audit: "leans on a few sources" at top-3 share = **14%** of 2,117 sources | headline contradicts the number at scale | scale-aware wording/threshold |
| 17 | severity alert: "Info: 5 alert signal(s)" re-counting convergences shown two cards earlier | a meta-card duplicating other cards | suppressed when it only re-counts cards already in the feed |

What worked (do NOT regress): law-change, through-time, recycled-claim framing, the
weather-corroboration concept, and every card's method/caveat disclosure — which is
exactly what made this export diagnosable from a copy-paste.

---

## §1 Ground truth — the anchors (verified at `56c0e86`; re-verify before editing)

**Producers (the defect sites):**
- `src/analytics/laundering.py:48 find_source_laundering` — origin noise filter at :45 is
  `is_social(dom) or is_commerce_domain(dom)` ONLY.
- `src/briefing/producers.py` — `price_narrative:436` · `lonely_signal:796` ·
  `capacity_implausible:857` · ownership-change verb regex `:1033` (English-only) ·
  `flooded_topic:2065`; `src/analytics/concentration.py:46 find_flooded_topics`.
- `src/analytics/convergence.py` (space-time) · `src/analytics/corroboration.py` (weather)
  · `src/analytics/headline_body.py` · `src/analytics/story_propagation.py` ·
  `src/analytics/supply_chain_ripple.py` (`:110` resolves a commodity to a stored keyword
  via label/symbol/"significant words of the label" — the homograph; `_daily_series:143`
  builds raw article-COUNT series — the volume confound; its own docstring `:13` states
  "daily article-COUNT series").

**Existing assets, built but NOT consumed by the producers (wiring, not invention):**
- `src/discovery/channels.py:108 is_infrastructure_domain` — already lists
  `policies.google.com`, `creativecommons.org`, `fonts.googleapis.com`, `schema.org`… (the
  2026-07-10 discovery noise filter). Wire it; extend the list only with evidence
  (`addtoany.com` and its widget family are evidenced by row 3).
- `src/analytics/engine_report.py:278 _generic_terms` — the #530 DF-ubiquity detector
  (proposes generic terms). The gate for flooding/propagation candidates wants the same
  MEASURE (per-language document-frequency ubiquity), computed inline, not the review
  worklist itself.
- `src/briefing/leads.py` — the shipped, unwired §2 Leads-2.0 core: `sort_leads:91`
  (disclosed order-key, never a score) · `explain_order:96` · `is_major:109` (the floor) ·
  `cluster_by_article_ids:136`. The isolated Settings→Leads preview + `/api/insights/leads-view`
  already exist for verification.
- `src/analytics/non_article_scan.py` — the suspected-homepage/section-capture detector
  (count-only today).
- `src/catalog/provenance.py` — `provenance_of` (web / wikipedia / newsletter / statistics /
  cited / law) — the clean internal-channel identifier for exemptions.
- Language capability: `analytics/managed.py` (`language_status`, `UNSEGMENTED`), the
  script-guard precedent in the subjectivity engine (S5.2: a method that cannot measure a
  language returns an honest GAP, never a fabricated result).

---

## §2 The slices (commit-per-slice; each ships with its regression tests)

### S1 — Shared noise substrate (rows 1–4, 7, 10, 15)
1. **Laundering origins:** add `is_infrastructure_domain` to the `:45` noise predicate;
   group candidate origins by `registrable_domain` and emit AT MOST one card per origin
   domain (row 2). State the exclusion in the card's Method line (the disclosure rule:
   an exclusion is part of the method).
2. **Generic-term gate for keyword producers** (`flooded_topic`, `story_propagation`):
   a term is not a candidate when its corpus document-frequency is ubiquitous (measure per
   language over the producer's own window — e.g. carried by ≥ a high share of active
   sources; calibrate on the export: *data/media/social/vir/lani* must gate out, a real
   event term must not). This is DETECTION-side gating with a stated threshold — the
   trusted keyword index itself is untouched (the anti-capping ruling stands: this gates
   which terms may become CARDS, it never deletes or hides a keyword anywhere else).
3. **Internal-channel exemption:** behavioral producers about *publisher conduct*
   (`capacity_implausible`, `flooded_topic`) skip sources whose `provenance_of` class is
   not `web` (newsletter import, law.*.local, wiki editions) — the .eml channel is the
   user's own import, not a publisher (row 7). The exemption is DISCLOSED in the method
   string. `diet_self_audit` keeps internal channels (the reading diet honestly includes
   them) — no change there beyond S4.4.
4. **Non-article member exclusion seam:** a shared helper exposes the
   `non_article_scan` suspicion so cluster-building producers (convergence, weather,
   recycled) can exclude suspected homepage/section captures from MEMBERS (row 10),
   with the count of excluded members disclosed (`excluded_non_articles: n`) — never
   silently. (The retroactive QUARANTINE stays the separate parked fix-session slice.)

### S2 — Statistical hygiene (rows 5, 13, 14)
1. **Ripple homograph:** commodity→keyword resolution matches the exact LABEL or exact
   SYMBOL term only — never "significant words of the label" (`supply_chain_ripple.py:110`).
   A commodity whose only match is a common-word homograph (*lead*, possibly *corn*-adjacent
   terms in other languages) resolves to NOTHING and produces no card — an honest gap.
2. **Ripple volume confound:** correlate daily SHARES (term count ÷ total corpus articles
   that day), not raw counts — two series that only track total collection volume must not
   co-move after normalization. Skeptic acceptance: synthesize a corpus where two unrelated
   terms both scale with daily volume → NO card; a genuinely co-moving pair → card.
   Update the method string to say shares.
3. **Count floors for proportion tests:** `flooded_topic` requires the keyword count
   itself ≥ 5 (not just the source's article count) or uses an exact test — z=5.85 on
   3 articles (row 5) must not fire.
4. **Null results are not Leads:** `price_narrative` emits a card only when the
   correlation is significant at a stated level AND |r| clears a stated floor; the
   non-significant pairs remain visible in the markets exploration surface (nothing is
   hidden — they just don't claim a Lead slot). Same principle for any producer that can
   compute a null.

### S3 — Language capability gates (rows 11, 12)
1. **headline_body:** surface-form lexical divergence is only meaningful where forms
   match across headline/body. Gate per language: run where the language is
   segmentation/inflection-compatible (start: the languages where the current method was
   validated; at minimum EXCLUDE highly-inflected languages until a lemma/stem-aware
   comparison exists) and return an honest per-language gap otherwise — the S5.2
   script-guard precedent. A divergence of exactly 1.0 with a non-empty body is treated
   as a method-failure signal, not a finding.
2. **ownership_change:** the `:1033` verb regex is English — gate candidates on
   `language == "en"` (or add per-language verb lists as DATA, dated, only with native
   review). The Romanian election article (row 11) must produce nothing.

### S4 — Scale-relative selection (rows 6, 8, 9, 16, 17)
1. **lonely_signal:** at most one card per source per refresh; and at large corpus scale
   (state the threshold, e.g. ≥ 50k articles) a single-source cluster is only a Lead when
   it intersects something the user watches or a currently-trending term — otherwise it
   remains available in exploration. "Single-source is the norm at this scale" joins the
   caveat.
2. **convergence:** canonicalize places to country CODE for identity + display
   (`Usa` → US display name via the shared region-name path; Allemagne ≡ Deutschland,
   row 9 — same key in weather corroboration); surprise is measured against the place's
   OWN baseline share of the corpus (a hub country converging is the base rate — fire on
   the deviation, not the absolute source count); prefer city-level clusters over
   country-level when both fire.
3. **weather corroboration:** one card per (event-vocabulary family, country code,
   window) — the France/Paris/UK/DE heatwave quartet collapses to the distinct
   country-level facts, Paris kept only if city-level adds precision beyond France.
4. **diet_self_audit:** wording must follow the number — with top-3 share ≤ a stated
   diversity threshold the card either doesn't fire or says the diet is broad (row 16:
   14% over 2,117 sources is diverse; the current headline asserts the opposite).
5. **severity_alert:** suppress the info-tier meta-card when its only content re-counts
   convergence cards already present in the same feed (row 17); provider-declared alerts
   (the ruled urgent/watch boundary) are untouched.

### S5 — Cross-card dedup + wire the Leads-2.0 core
1. Producer-level dedup keys (laundering: registrable origin domain; convergence/weather:
   country code + window; ripple: commodity; lonely: source) — S1–S4 individually add
   these; this slice adds the belt: `run_all`/`refresh_briefing` drops exact
   (producer, key) duplicates loudly (logged count).
2. **Wire `sort_leads` + `is_major` + `cluster_by_article_ids`** into the briefing
   assembly: disclosed ordering (the order-key is facts, never a score — `explain_order`
   goes into the card hover), the major-floor gates which cards claim the top slots,
   clustering collapses same-story cards into one entry with members. **This visibly
   reorders Home** — ship it conservative + flagged per the standing fork-3/Q6a
   convention (node-check + invariant tests + defensive fallback to the current order
   if the module errors), and verify against the existing Settings→Leads preview panel.
   The maintainer's export IS the mandate for this wiring; a browser click-through
   remains owed and stated in the PR.

### S6 — The measurement loop (so improvement is measured, not asserted)
1. A `leads_quality` diagnostic: export the CURRENT feed as JSONL (producer, key facts,
   the card's n/threshold values) — the maintainer re-runs it on the live corpus and
   sends it back, exactly like the keyword-log loop. Ride the all-diagnostics bundle
   (the membership ratchet will enforce it).
2. Encode §0's rows as the regression suite: every fixed defect gets a fixture test
   asserting the artifact input produces NO card AND a neighboring legitimate input
   still does (the negative-space discipline both ways).
3. Before/after on the export: the PR body states, for each §0 row, what the same
   input now produces.

---

## §3 Binding honesty rules (unchanged, restated for this territory)

No composite scores (the no-score key-walkers run on every changed payload). Every
exclusion/gate/floor is DISCLOSED in the producer's method string — an exemption the
user can't see is a hidden editorial hand. Degrade loudly: a language the method can't
measure is a stated gap, never a silent skip and never a fabricated zero. Nothing is
deleted from exploration surfaces — selection discipline applies to LEAD SLOTS only
(cross-time recall and the anti-capping rulings stand). Thresholds are stated numbers in
the method line, never buried constants. "Absence of a flag ≠ absence of manipulation"
stays on every producer.

## §4 Out of scope

New producers; the bury-half of flood; LLM anything; the event-timed-op card; reworking
the keyword engine (the generic-term gate CONSUMES the existing measure); the non-article
QUARANTINE action (parked fix-session slice — S1.4 only excludes suspects from card
membership); Home visual redesign beyond the S5.2 wiring.

## §5 Definition of done

All §0 rows pinned as tests and green; skeptic passes (negative-space both directions)
recorded per statistical slice; full local suite green; ledger + shipped.csv rows; one
draft PR onto `main` with the before/after table; the leads_quality diagnostic in the
bundle. The maintainer's next live export is the field acceptance: the feed should lead
with the convergences, law changes, and genuine floods — not cookie-policy URLs.
