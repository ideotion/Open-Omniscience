# SESSION 6 of 6 — TIER 5: the feature backlog (highest-value codeable subset)

**Mission:** Tier 5 is months of designed work — you ship the subset with the highest value
per unit of risk for the app's purpose: helping journalists and citizens see information
honestly. Priority order below is BINDING (it ranks data-safety completeness, then the
sense-making surfaces, then comfort). **EXCLUDED by maintainer ruling 2026-07-11 #3: the
Wikipedia+laws versioned-sources revamp stays gated on the P0 live validation — do not
build it, not even foundations.** Read `SESSIONS_2026-07-11_CONVENTIONS.md` §0 first, then
**absorb S5's carry-overs**.

## Queue (top-down — get as deep as verification-quality allows)

### S6.1 — Content-provenance class S1→S3 (if S5 didn't take S1)
The cleanest metadata the app can add — an ASSERTED channel fact, no classifier: the
`source_type` controlled vocabulary + per-ingest-path population + deterministic backfill
(fixes newsletters mislabeled "news"), → the facet surface, → reading-diet-BY-TYPE
(extend `analytics/concentration.py`). Descriptive, never a credibility score. The design
doc's backward-compat verification (additive-restore carries `source_type`; staged-upgrade
migrates before merge) is binding.

### S6.2 — Backup completeness: FILE members (wiki dumps / OSM / models) + retire the legacy restore
The long-ruled reversal of design D3: backups may carry the big public blobs so a restore
never re-downloads tens of GB over Tor.
- Additive-restore FILE placement: manifest-listed file members placed into
  `wiki_dumps/`/`osm_regions/`/the model store — bit-identical dedup by checksum, NEVER
  overwrite a differing local file, skip non-`done` downloads by construction, opt-in per
  category (small backups stay small), traversal-guarded per the ZETA lessons.
- Then remove the LEGACY single-file RESTORE path (endpoints + `_MAX_RESTORE_BYTES` + the
  UI remnant), absorption-test-gated — the volumes/folder paths must demonstrably cover
  every restore need first. Data-safety-critical: full skeptic matrix before push.

### S6.3 — Collector write-batching (the keystone refactor, live-justified)
Per `COLLECTOR_WRITER_BATCHING.md` + the field's 847,351 s cumulative gate-wait: restructure
the collector's store path onto `index_article(commit=False)` batches with the proven
rollback-then-redo-per-article fallback. NO-LOSS is the bar: the batched==per-article parity
test, the contention race test, and the gate-hold probe all mandatory. S2's F13 fix
(extract-outside-gate) composes with this — verify both together.

### S6.4 — Convergence & attention: the new Home producers + the local alert layer
Pure local analytics, high daily value:
- Producers: **"Converging now"** (fresh space-time convergences) · **"On the horizon"**
  (agenda events ∩ the user's watched/trending keywords) · **"Through time"** (anniversary
  lens: today vs the corpus's past years) · **"Your watch-rules fired"** (the watch engine
  already runs — surface it). Each a real producer with `_trigger`, no scores, fail-safe
  registration, honest empty states.
- The severity-tiered LOCAL alert layer: info/watch/urgent from hazard severity + tag-family
  spikes + watch matches; urgent = a Home banner; thresholds user-owned + explained;
  local-only, no notifications/network/telemetry (the ruled boundary).

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
year-pinned-import class) · month-span events ("Dry January" banners) · full iCal import
(idempotent per source,uid) · saved-filter smart calendars (subscribe to a tag query) ·
agenda i18n. The eclipse canon + world religious calendars need SOURCED data → operator
list (never fabricate a date; the Meeus-computed moons/seasons pattern is the bar).

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
If, and only if, everything above is verified: pick from disputed-chronology detector /
story-propagation tracer (both computable from existing lineage/date substrate with honest
innocent-explanations). Skip the ones needing external baselines.

## Explicitly NOT yours
Versioned sources (gated — ruling #3) · elections roster/calendar data, eclipse data,
lexicons, any fetch (networked/operator) · Tor/Stem integration, oo-netcut, self-update,
portability, voice, the Mirror (each needs its own design session or maintainer step).

## Closeout — the PROGRAM closeout
Ledger rows + ROADMAP flips + a final **program summary**: what the six sessions shipped
end-to-end, the consolidated OPERATOR list (live validation → tag; the networked fetches;
click-throughs; gold-set grading; keyword-log export), and the recommended next cycle's
top three. Leave the board honest — that is the deliverable the program is judged on.
