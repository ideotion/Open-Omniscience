# SESSION 6 of 6 — TIER 5: the feature backlog (highest-value codeable subset)

**Mission:** Tier 5 is months of designed work — you ship the subset with the highest value
per unit of risk for the app's purpose: helping journalists and citizens see information
honestly. Priority order below is BINDING (it ranks data-safety completeness, then the
sense-making surfaces, then comfort). **EXCLUDED by maintainer ruling 2026-07-11 #3: the
Wikipedia+laws versioned-sources revamp stays gated on the P0 live validation — do not
build it, not even foundations.** Read `SESSIONS_2026-07-11_CONVENTIONS.md` §0 first, then
**absorb S5's carry-overs**.

## Queue (top-down — get as deep as verification-quality allows)

**FIRST ACT: re-derive this queue against the tree** (the conventions' staleness guard).
The verification pass already found the 2026-07-02/03 wave shipped several rows this tier's
board still showed open — assume more of the same and verify EVERY item before building.

### S6.1 — Content-provenance class: VERIFY-AND-MARK (found already shipped end-to-end)
Tree evidence: ingestion stamps `source_type` per channel (`src/api/ingestion.py:178–197`,
incl. the newsletter backfill), the facet endpoint exists (`insights_source_types`,
`src/api/insights.py`), and reading-diet-by-channel is in `analytics/concentration.py`.
Your job: verify S1→S3 against the design doc's acceptance (incl. the additive-restore
carries-`source_type` check), mark the board + ledger per the already-built precedent, and
ship ONLY genuine residue found on inspection.

### S6.1b — Secondary-source `cited` provenance: the remaining slices (if S5 didn't take it)
The half-shipped sibling of S6.1 (slice 1 landed): the background job that resolves citing
relationships at corpus scale, denormalize `citing_source_id`, surface the citing trail in
the reader/analysis ("the sources' sources"), and wire the dormant `external_sources`
resolution. Deterministic, never fuzzy; the anti-false-triangulation framing (shared origin
≠ independent confirmation) travels on every surface.

### S6.2 — Backup completeness: FILE members in the SIGNED VOLUME ARTIFACT + a survivable legacy path
Scope precision (the folder engine ALREADY exists — `src/backup/folder_backup.py` carries
wiki/OSM/models with checksum dedup, additive never-overwrite restore, per-category opt-in;
do NOT duplicate it): **the genuinely-open delta is file members inside the signed encrypted
VOLUME artifact's manifest**, so ONE portable artifact can carry the blobs.
- Additive-restore FILE placement from the volume manifest into `wiki_dumps/`/`osm_regions/`/
  the model store — bit-identical dedup by checksum, NEVER overwrite a differing local file,
  skip non-`done` downloads by construction, opt-in per category. The ZETA name→path
  traversal enumeration applies to every NEW manifest field, on BOTH verify and restore.
- **Legacy single-file restore — a READER must survive.** The volumes/folder paths can never
  DECODE an old-format artifact, so removing the legacy path outright would strand any user
  whose only backup is old-format — permanent data loss of exactly the kind this program
  exists to prevent. You may consolidate/hide the legacy UI surface behind the unified
  Import dialog, but the old-format → additive-merge READER stays; final retirement is
  GATED on the maintainer's explicit "format fully retired in the field" confirmation —
  a condition no offline session can verify. Data-safety-critical: full skeptic matrix
  before push.

### S6.3 — Collector write-batching: VERIFY-AND-MARK (found already shipped as P1.8)
Tree evidence: `src/ingest/batch.py` implements exactly the `COLLECTOR_WRITER_BATCHING.md`
design (its docstring cites the same 847,351 s figure; `commit=False`, redo-per-article
fallback, gate-never-across-fetch; `tests/test_collect_batching.py`). Your job: verify the
no-loss battery is complete, verify composition with whatever S2's A9 reproducer pass
concluded about F13, mark the board + ledger, and fix the stale ROADMAP §4 "write-batching
🎨" row.

### S6.4 — Convergence & attention: the TWO missing producers + a capped alert extension
Tree evidence trims this: `space_time_convergence` and `watch_matches` producers ALREADY
exist and register ("Converging now" / "watch-rules fired" ≈ shipped), and the
severity-tiered alert layer is SHIPPED (`src/analytics/alerts.py` + the Home strip +
`tests/test_alert_layer.py`). The real work:
- Build the TWO genuinely-missing producers: **"On the horizon"** (agenda events ∩ the
  user's watched/trending keywords) and **"Through time"** (anniversary lens: today vs the
  corpus's past years). Real producers with `_trigger`, no scores, fail-safe registration,
  honest empty states.
- Alert layer: EXTEND-only, and the shipped invariant is BINDING — **"urgent" is ONLY a
  provider-declared red hazard alert; a count/spike is NEVER promoted into it** (the ruled
  no-escalation boundary: watch matches and tag-family spikes cap at watch/info). Any change
  to that boundary is a maintainer ruling, not yours.

### S6.5 — The LLM-perception EVAL HARNESS (the gate for the whole perception track)
Build the harness BEFORE any extraction feature (the ruled eval-first order): a
difficulty-tiered, phenomenon-tagged synthetic gold set ×12 languages (ar/zh/ja/hi/bn
flagged needs-native-review) for who/where/when extraction; scores precision/recall/
**hallucination-rate** per language/tier/phenomenon vs the RULE-BASED baseline;
deterministic; LLM place-string vs gazetteer-coordinate scored separately; de-US-centring
measured per stratum. Reuses the `ir_eval` reporting discipline (per-stratum with n, never
one pooled average, no composite). The extraction feature itself waits for the harness to
exist and a model to clear it — do NOT ship extraction this session.

### S6.6 — Agenda depth (the offline-codeable set)
The ONE recurrence model (RULE + dated INSTANCES + `since:` origin year — fixes the
year-pinned-import class) · **deduced events as FIRST-CLASS agenda entries** with keyword
links (the backend `/api/events/deduced` exists; parity with the moon/season treatment;
"deduced · never confirmed" pill stays visible) · month-span events ("Dry January" banners)
· EXTEND the existing VEVENT/uid import (`src/events/feeds.py` already parses + dedups per
source,uid — the new parts are RRULE recurrence expansion, month-spans, `since:` origins;
don't rebuild the parser) · saved-filter smart calendars (subscribe to a tag query) · i18n
for the NEW agenda surfaces this session builds (S4 keys the pre-existing tail). The eclipse canon + world religious calendars need SOURCED data →
operator list (never fabricate a date; the Meeus-computed moons/seasons pattern is the bar).

### S6.7 — Maps & task-manager comfort (small, real)
Temporal linear/log time-scale toggle (labelled ticks, no hidden warp) + feed the map's
mention layer with EVENT-places · OSM/dump downloads gain an HONEST owner-measured rate/ETA
(the manager measures its own bytes-over-time — the deliberate omission was about
client-side guessing, which stays forbidden).

### S6.8 — Onboarding tour (first-run guidance)
Dismissible Home-card tour + contextual "why" notes per tab (the designed autonomous
onboarding track's first slice): teaches airplane/consent/corpus concepts in the app's
honest voice; ×12; never blocks; never auto-fires network.

### S6.9 — (stretch) Scenario cards with honest local triggers
Disputed-chronology, story-propagation AND supply-chain-ripple already shipped (2026-07-03,
`tests/test_scenario_cards.py`) — do not rebuild. If, and only if, everything above is
verified: pick from the genuinely-remaining set — **silent-disasters** / **law-takes-effect
watch** (both computable from existing hazard/law/date substrate with honest
innocent-explanations). Skip news-desert-atlas and election-window-desk (external baselines
/ roster data — operator-gated).

## Explicitly NOT yours — name these in the program closeout's next-cycle list
Versioned sources (gated — ruling #3) · elections roster/calendar data, eclipse data,
lexicons, any fetch (networked/operator) · Tor/Stem integration, oo-netcut, self-update,
portability, voice, the Mirror (each needs its own design session or maintainer step) ·
and the CONSCIOUSLY-PARKED partials no session takes this program: the Open-Meteo remainder
(anomaly baselines / signal-keywords / reader row / map overlay), the lunar-effects
framework remainder, the hand-rolled offline vector map, the OSM bandwidth-cap + country
sub-extracts + consented exact-size refresh, the "which country next & why" schedule panel,
the evidence-tier card remainder (what's-missing inversions · BH-FDR · dismiss-with-reason
· card-diagnostics export — fold the cheap ones into S6.4 only if trivially adjacent).
Parking them HERE is what keeps the closeout honest — they must appear on the next-cycle
list, not silently vanish.

## Closeout — the PROGRAM closeout
Ledger rows + ROADMAP flips + a final **program summary**: what the six sessions shipped
end-to-end, the consolidated OPERATOR list (live validation → tag; the networked fetches;
click-throughs; gold-set grading; keyword-log export), and the recommended next cycle's
top three. Leave the board honest — that is the deliverable the program is judged on.
