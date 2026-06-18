# V0.1 alpha — official release-candidate gate

> **Maintainer mandate (2026-06-11):** "absolutely everything" from
> `CLAUDE.md` + `FUTURE_DEVELOPMENTS.md` built and bundled into the 0.09
> cycle before V0.1 alpha goes live; Windows and macOS installations tested;
> app ↔ documentation reciprocity; ethics reflected in the software;
> security impeccable; UX guaranteed.
>
> **This document is the gate.** It is the honest inventory — what is DONE
> (verified), what is OPEN (with size), and what "done" means per item. An
> item leaves this list only when its acceptance check passes. The answer to
> "is everything implemented?" is **NO until every BLOCKING row is checked**
> — and this file is where that claim becomes checkable instead of taken on
> faith. (Estimates are estimates, not promises; they reflect the measured
> pace of the 0.08–0.09 sessions.)

Status legend: ✅ shipped+verified · 🔶 partially shipped · ⬜ open.
Gate column: **RC-BLOCKING** (V0.1 does not ship without it) / SHOULD
(strongly recommended in RC) / POST (honest to ship after, stated in notes).

> **Reconciled 2026-06-15 (solo session, OO-D14-010).** This snapshot had drifted
> behind the code: several rows below were ⬜/🔶 while shipped at HEAD (verified in
> `index.html` / `src/`). Only **code-spot-checked** rows were advanced (under-claim is
> safe, over-claim is not — the audit ethic). **`CLAUDE.md` is the live ledger**; this
> gate is a periodic snapshot and may still lag it between reconciliations.

> **Reconciled 2026-06-16 (autonomous 'everything' batch — CLAUDE.md is authoritative).**
> Scope is now the full V0.1 mandate + promotions. Rows advanced this pass: both honesty
> bugs ✅ (airplane-paused #245; back-button); Reader TABS → 🔶 slice 1 (#246, standalone);
> Item Y (n<10→bars) ✅. Newly ACTIVE (were design-only/POST): the UI rethink (centerpiece),
> the in-app Ollama installer, GUI self-update (mechanics only), + two new verticals (geo /
> offline map; official-statistics ingestion). The convergence WATCH engine is greenlit as
> "Watches view + history".

> **Reconciled 2026-06-17 (release-eng pivot, the 13 batch rulings).** Rows advanced this
> pass against shipped code: **release.yml** (tag→sdist/wheel/SHA256SUMS/verify-version, 🔶 —
> needs a real tag); **version single-source** (`importlib.metadata`, guarded by
> `test_version_single_sourced_from_pyproject`, 🔶 — the 0.0.9→0.1 flip HELD per ruling #2);
> **watch engine** ✅ ON BY DEFAULT (ruling #3); **live mailbox pull** ✅ (ruling #11, closed a
> kill-switch gap); **scheduled stat-vintage auto-refresh** ✅ (ruling #12); two
> **manipulation-pattern Leads** shipped (source-laundering + recycled-claim, ruling #13 — both
> citation-graph/near-dup, no score, innocent-explanation-beside-pattern). De-scoped per
> ruling #5: win/mac CI-graduation + install path → POST (Debian is the V0.1 target).

## 1. The trust core (data integrity + crypto + safety)

| Item | Status | Gate | Acceptance check |
|---|---|---|---|
| Backup carries EVERYTHING (oo-backup-2 artifact, signed manifest) | ✅ | RC-BLOCKING | torture suite T5/T6; manifest lists exclusions |
| Merge-only restore (preview=commit code path, FK remap, conflicts reported, atomic swap) | ✅ | RC-BLOCKING | torture suite 10/10 green (is, today) |
| Restore is ADDITIVE-ONLY: the destructive replace paths removed entirely (ruled 2026-06-13) | ✅ 2026-06-13 | RC-BLOCKING | `/api/database/restore` + `/api/safety/restore/encrypted` + `restore_from_bytes`/`restore_encrypted_backup` gone; merge is the only restore; `tests/test_additive_restore_only.py` guards regression; torture 10/10 |
| Custody chains verified-not-trusted, never spliced | ✅ | RC-BLOCKING | T9 |
| Cross-version restore floor + staged upgrade | ✅ | RC-BLOCKING | T4 |
| Single-writer gate (no fetched data lost to writer contention; keystone #1) | ✅ 2026-06-13 | RC-BLOCKING | `src/database/writer.py` serialises every write via session events; `tests/test_write_gate.py`: 6 concurrent writers never "database is locked", reads never gated, safety-net release on close. END-TO-END + ISOLATION proof `tests/test_write_gate_dataloss.py` (2026-06-14): real `SessionLocal`+`import_points` racing a scrape store lose 0 rows; control without the gate reproduces the field-log lock (47) while the gate yields 0 |
| **SQLCipher at-rest encryption ON by default + passphrase unlock UX + doctor attestation + one-way encrypt tool (PR-E)** | ✅ 2026-06-12 | **RC-BLOCKING** | shipped in one PR per the honesty gate; 8-test suite incl. subprocess boot states + the crown (encrypted corpus stays ciphertext through backup/merge); doctor reads real headers; remaining riders: key re-wrap in the tool, launcher prompt wiring |
| State-into-DB migrations (settings/annotations/events → tables, D1/D4) | ⬜ | SHOULD | legacy JSONs imported once; artifact v3 member list updated; suite green |
| Settings → Data & backup UI on the v2 endpoints (restore preview table, encrypted-default, ×12 locales) | ✅ 2026-06-12 (T6) | RC-BLOCKING | shipped: signed-archive backup + preview→merge flow primary in Settings; plan table (new/duplicate/conflict-kept-local + samples); Apply disabled on failed verification; legacy tools demoted to a collapsed block (never silently lost); i18n 100% ×12; UI contract pinned in tests/test_restore_ui.py |
| Network kill switch: airplane-mode semantics + online-consent popup (local IPs) + immediate repaint | ✅ | RC-BLOCKING (ethics-facing) | SHIPPED (T2, invariant #14 + tests/test_network_consent.py): every online transition consented; state never lies (scrape-start repaint) |
| oo-netcut opt-in OS layer (interface-agnostic; netsh/networksetup parity) | ⬜ | POST (document app-level scope honestly in RC) | manual + sudoers doc; per-OS smoke |
| Single guarded socket factory + build-failing test (no module opens its own) | 🔶 2026-06-13 | SHOULD | `guarded_session` routes dumps/wiki/ores/DDG through the kill switch + proxy + honest UA; the socket-importer RATCHET test pins the allowlist (6→3). REMAINING: refactor the remaining allowed importers onto the ONE factory |
| Newsletter ingestion (local `.eml` import + live mailbox pull) | ✅ 2026-06-17 (ruling #11) | POST | local `.eml` import shipped (Settings → Newsletters, anonymise-at-ingest, zero-network). **LIVE MAILBOX PULL shipped 2026-06-17 (ruling #11 reverses the IMAP block — maintainer wants to test):** closed a pre-existing `fetch_imap` SECURITY GAP (no kill-switch gate) → `src/ingest/email.py` `fetch_imap`/`fetch_pop3`/`fetch_mailbox` are airplane-gated (refuse up front → NO socket offline) + logout in `finally`; `POST /api/newsletters/mailbox` stores under a dedicated disabled `mailbox.import.local` source (409 offline / 502 transport, anonymise tally + TLS/IP/not-Tor/creds-not-stored disclosure); reuses `ingest_emails` (recipient never stored, no raw retention, tracking-link detox). `imaplib`/`poplib` stdlib → socket-importer ratchet intact. `tests/test_mailbox_ingest.py` (6, incl. airplane-opens-no-socket). REMAINING: a visible task-manager job over a long pull; stored creds for repeat pulls |

## 2. Release engineering & portability

| Item | Status | Gate | Acceptance check |
|---|---|---|---|
| 3-OS CI matrix (the *definition* of supported) | 🔶 added 2026-06-11 | POST (de-scoped 2026-06-17, ruling #5) | **ruling #5: win/mac install is NOT blocking — Debian is the V0.1 target.** The matrix stays for observation; win/mac lanes graduate to required-and-green POST-V0.1 |
| SQLCipher wheel smoke on 3 OSes (blocking job) | ✅ added | RC-BLOCKING | green on all three runners |
| Windows/macOS INSTALL path (installer logic into the package; sh/ps1 bootstraps) | 🔶 de-scoped 2026-06-17 | POST (ruling #5) | **ruling #5: focus DEBIAN for V0.1** — a fresh Debian machine reaches the Console via documented steps; win/mac install graduates later |
| Release artifacts from one tag + checksums documented | 🔶 2026-06-17 | RC-BLOCKING | **`.github/workflows/release.yml` SHIPPED**: a `v*` tag builds sdist+wheel, **verifies the tag matches the pyproject version**, emits `SHA256SUMS`, and creates the GitHub release (one job; only SHA-pinned checkout/setup-python). REMAINING: prove end-to-end on a real tag (held until the version flip, ruling #2) |
| Signing/notarization decision | ⬜ | POST (deferred by ruling; checksums regardless) | decision recorded |
| Version/branding sweep (0.0.9→0.1; FOOS suffix stays until the rename ruling) | 🔶 2026-06-17 | RC-BLOCKING | **single-source SHIPPED**: `src/__init__.py` `__version__` reads `importlib.metadata.version("open-omniscience")` (pyproject is the one source); `tests/test_repo_invariants.py::test_version_single_sourced_from_pyproject` guards it. The 0.0.9→0.1 FLIP is **HELD** until every RC-BLOCKING row is ✅ (ruling #2); FOOS suffix stays |
| CHANGES.md 0.0.9→0.1 section + release notes | 🔶 2026-06-17 | RC-BLOCKING | 0.09 user-facing entries kept current (statistics+vintages, Watches, mailbox live-pull, manipulation Leads); the 0.1 rename section lands with the version flip (ruling #2) |

## 3. The ruled feature queue (maintainer field reports, 0.09 cycle)

| Item | Status | Gate | Notes |
|---|---|---|---|
| Agenda: data-first restructure + month-grid default + tab fully i18n'd | ✅ 2026-06-11 | — | invariant #13 enforces |
| Agenda content: recurrence schema (+origin years, month-spans), worldwide bank holidays, religious calendars (computed/moon ±1d caveat; sourced tables), astronomy layer (Meeus moons tested vs almanac + eclipse canon), article-extracted dated events layer | 🔶 | RC-BLOCKING (the maintainer's "all and everything accessible") | every entry carries method+accuracy; zero-network boot kept. **Article-extracted layer BACKEND shipped 2026-06-16:** `datestore.upcoming_deduced` + `GET /api/events/deduced` group future MENTIONED dates (distinct articles + sources, ≥-articles gate, article-id set), "deduced from text, never confirmed", no score (`tests/test_deduced_dates.py`). **Article-extracted FRONTEND shipped 2026-06-16:** `mapDeducedToAgenda` routes `/api/events/deduced` through the `AG.events` pipeline (renders in every view as a distinct filterable "deduced" category; visible never-confirmed pill+note; title opens the exact article set via `openAnalysisForIds`; +4 i18n ×12; `test_ui_invariants` #13b). **Date-extractor wiring fixed 2026-06-16:** `store_for_article` now passes the article's publication date (`anchor`) + `language` to `extract_dates` at ingest, so the extractor's anchored/relative/no-year/numeric-disambiguated forms are captured corpus-wide (were silently explicit-only); the deduced-events layer inherits it (test_store_uses_article_anchor_and_language). **Recurrence SCHEMA shipped 2026-06-17:** `src/events/catalog.py` now honours `origin_year`/`until_year` (active year range — "since 1950" / an ended observance, out-of-range occurrences suppressed) + `end_month`/`end_day` (month-spans like "Dry January", year-wrap-aware), exposed as a per-event `span {start,end,active}` and origin; pure logic, honest (a span is built only from explicit start+end), `tests/test_event_recurrence.py`. REMAINING: deduced events as first-class agenda events with keyword links; world-calendars (Islamic/Hindu — verification-bound, like the Meeus moons); eclipse-canon astronomy slice |
| Agenda: remaining views (week/trimester/semester/year/decade) | ✅ 2026-06-14 (PR #206) | SHOULD | all shipped — Month/Week/Trimester/Semester/Year/Decade/List view buttons present in the agenda tab (`index.html` agenda view bar) |
| Task manager window (repeat ×2; acceptance: reorder fr-before-en wiki dumps; per-country scrape priority) + download arbitration (queue/prioritize/cancel) | 🔶 2026-06-12 (T9 slice 1: visible jobs view, REAL reorderable dump queue — fr-before-en works end-to-end and is tested; arbitration ask on collect); per-job controls extended to OSM + Resume for paused/failed downloads (Item 2, 2026-06-16, invariant #20d) | RC-BLOCKING (twice-repeated ask) | REMAINING: per-country scrape priority; arbitration ask on remaining starters; richer pass-time estimates; per-job rate/ETA + bandwidth cap (needs owner-measured bytes-over-time, never a client-side guess) |
| Reader TABS (mindmap/related/source/keywords/sentiment) | ✅ 2026-06-16 (PR1: Read·Keywords·Sentiment·Related·Links; PR1b: **Mindmap** via `/api/insights/graph?article_ids=` + `queries.article_graph` radial + **Source** profile pane (catalogue provenance + corpus footprint, no score); reader is standalone; tests/test_reader_tabs.py) | RC-BLOCKING (twice-repeated ask) | fork-1: reader stays STANDALONE. Full tab set Read·Keywords·Mindmap·Sentiment·Related·Source·Links; When/Where/Who in the Read pane |
| The ONE corpora system (6 entries: hand/tag-selection/tag-click/commodity-click/keyword-click/date-keyword-click; keyword windows = same sub-tabs + events sub-tab + TIME-SCOPE control) | 🔶 advanced 2026-06-15 | RC-BLOCKING (the flagship analysis object) | sub-tab set built out on the `#corpus` modal (Mindmap/Sentiment/Keywords/Sources/Competitive, PRs #214–218) AND the Group F `#analyze` window (invariant #22); TIME-SCOPE shipped as `ooTimeScope` (PRs #197–201). REMAINING: the **two-windows consolidation** (known debt, CLAUDE.md) + the remaining entry points |
| Interactive charts (zoom/pan/X-Y readout/legends; kill the 5-point cap; real curves) | 🔶 advanced 2026-06-15 | RC-BLOCKING (live-test complaint) | full series at all scales; **indices board detail rolled onto `ooChart`** (PR #205; invariant #16 asserts `ooChart($("idx-chart-oo")`). **Trends sparkline → click-to-enlarge `ooChart`** via the reusable `chart-enlarge` dialog (Item 1; invariant #21b++). REMAINING: commodity-card enlarge → `ooChart` (the n<10→bar rule, Item Y, SHIPPED app-wide 2026-06-15 in both renderers) |
| Commodity → keyword-family pivot (price curve + article-timeline overlay; symbol→family seed table) | ✅ 2026-06-16 (Item 3) | SHOULD | category subtabs (`ooSubtabs`) + title/Analyse → `openAnalysisFor` + a commodity-gated **Price** subtab: `commodityOverlaySvg` draws a time-aligned DUAL-AXIS overlay (price line + corpus-coverage bars, each its OWN labelled axis — no magnitude conflation), seed map = `COMMODITY_QUERY`; co-occurrence framing never causation (visible); reuses existing endpoints; invariant #22b. Browser-unverified |
| Continuous collection (per-country round-robin + first-run approval + onboarding country/language picker; explainable schedule) | 🔶 2026-06-13 (slice 1: boot-in-airplane-mode + continuous loop + per-country round-robin ordering, tested) | SHOULD | consent design shared with network popup; REMAINING: onboarding picker, explainable cycle detail, demote arbitration modal, parallel fetch |
| When×Where×Who extraction at ingest + backfill (confirmed GO) | 🔶 advanced 2026-06-15 | SHOULD (substrate for convergence) | reader now reads STORED rows (PR #202, `datestore.for_article`); WHO+WHERE corpus aggregates shipped (`/api/insights/who` + `/where`); temporal-map mention layer (PR #200). REMAINING: map gains EVENT-places too |
| Convergence detection + watch rules (the 0.0.9 flagship, layers 3+4) | ✅ 2026-06-17 (watch engine, ruling #3) | POST | READ-ONLY space-time co-occurrence shipped (`src/analytics/convergence.py` + briefing producer; distinct-sources metric, no score). Read-only Convergence subtab over `GET /api/insights/convergences` (PR 2026-06-16; `test_ui_invariants` #21c). **WATCH ENGINE SHIPPED 2026-06-17, ON BY DEFAULT (ruling #3):** `Watch`+`WatchMatch` models (migration b8c9d0e1f2a3) + `src/analytics/watches.py` (CRUD + `evaluate_watches` fires a `watch` Lead when the corpus gains enough NEW articles matching a saved FTS condition over the user's threshold+window; `last_seen_ids` prevents re-alarming) + `watch_matches` producer wired into `refresh_briefing` (runs after every pass) + `src/api/watches.py` CRUD/history/evaluate + a Watches Insights subtab. LOCAL-only, no notifications/network/telemetry, no escalation tiers (the ruling). `tests/test_watch_engine.py` (7) + `tests/test_watches_api.py` + `test_ui_invariants` #21d. REMAINING: i18n-key the Watches panel; richer condition types (place/convergence) |
| Permanent top-bar language switcher (flag + native name) | ✅ 2026-06-12 (T7) | RC-BLOCKING (reputation ×12 languages) | shipped: 12-language menu (flag = cue, native name = identifier), one click through OOI18N.setLang (DOM re-walk + t() for dynamic strings), Settings sync, invariant #15 |
| i18n long tail → ~0 (audit-chrome per tab) + Home-card title translation design | 🔶 ruling #8 (PROCEED) | RC-BLOCKING | keyed strings stay **100% ×12** (`--min 100` green); `--audit-chrome` measures **431 untranslatable chrome strings as of 2026-06-17** (recently-shipped Settings panels — Models/Offline-map/Newsletters/mailbox/Statistics/Watches — are the largest cohort). Mechanism confirmed: a chrome string becomes translatable by adding its `English → translation` entry to the 12 `src/static/locales/*.json` (the engine keys on the English string + auto-walks DOM text/attrs). Burn down in native-reviewable slices (AI-drafted non-en, flagged) |
| French easter eggs (transnational, translatable) | ⬜ | SHOULD | personality.yml |
| Tor transport-awareness in per-host verdicts + "running over Tor" manual chapter (logs pending from maintainer) | ⬜ | SHOULD | verdicts distinguish robots/Tor-refused/down |
| Global search rework (omnibar absorbs Search tab — only after parity) | ⬜ | POST | the Desk lesson: never lose a tool |
| Audit-07 arbitration (B0) + disclosure sweep (B1: VADER EN-only, LLM labels, lexical limits, modality, CJK honesty) | 🔶 | BLOCKING-proposed | plans: `V01_ALPHA_ACTION_PLANS.md`; findings: `docs/audit/07_TRANSVERSAL_AUDIT_V01.md`. VADER EN-only + LLM labels already disclosed; **CJK honesty shipped 2026-06-17** — `queries.unsegmented_note` surfaces "keyword extraction does not segment zh/ja" in the user-facing keyword analytics (`corpus_keywords` + `article_graph`), not only in the diagnostics export (`tests/test_unsegmented_disclosure.py`). REMAINING: B0 arbitration, lexical/modality wording |
| Local fixity audit tool (B2 — reliable-memory turned inward) | ⬜ | SHOULD-proposed | re-hash corpus vs stored hashes, loud report |
| 100k-article scale proof + consented-archiving design (B3) | ⬜ | SHOULD-proposed | perf-harness profile; measure first. PERF WORKSTREAM (field report 2026-06-18, in flight): insights TTL cache + warm; framing/supergroups bounded; **denormalised `Keyword.mention_count`/`article_count` maintained at index time — slice 1 (columns + incremental maintenance + backfill + self-heal + migration a2b3c4d5e6f7) SHIPPED, slice 2 rewrites top_terms/_supergroup_totals onto the counters** |
| "Your lens" dashboard v1 + corpus passport (B4/A3/A2) | ⬜ | SHOULD-proposed | plural declared baselines; descriptive never corrective |
| Indices/commodities reclassification + #commodities alias; more feeds (rare earths, LNG, cereals…) | ⬜ | SHOULD | per-index verdicts in UI |
| Home cards → per-type investigate views | ⬜ | SHOULD | every card clickable |
| Evidence-tiered cards remaining slices; corpus tier header | ⬜ | SHOULD | plain sentence + math, translated |
| Custody tab UX (rename/explain/guided) | ⬜ | SHOULD | non-expert comprehension test |
| De-US-centring remainder: Wikidata gap run (maintainer's machine) + raise located share (49% unlocated) | 🔶 2026-06-16 (title-evident gap CLOSED: seeder now reads the `Name (Country)` convention + a hand-reviewed demonym/name pass; 129 additive `country:` entries, sources.yml located 40.4%→44.4%, all non-US, topic/edition/international titles kept NULL by design; regression-guarded) | SHOULD | REMAINING: the Wikidata gap run (maintainer's machine) for the deeper unlocated share; coverage report metric moves |
| Trans-language equivalence rings → LIVE analytics merging | ✅ 2026-06-16 (slice 1) | SHOULD | wired into top/trending/associations/graph via src/analytics/equivalence.py; fr:élection+en:election+de:wahl = one concept, per-language counts visible (language_breakdown), signature-supported join honours fr:main≠en:main, user can split, OO_KEYWORD_EQUIV=0 off. REMAINING: cross-country split, map view, frontend breakdown |
| Offline LLM kit (RM-08); translated-docs drafting run (needs a machine with a model) | ⬜ | POST | — |
| Wikipedia-as-a-source; smart calendars; event-family merge/split UI; offline vector map; onboarding track | ⬜ | POST | recorded designs |

## 4. Security & ethics gate (the "impeccable" clause, honestly framed)

Security is a process, not a state — the RC claim is: *every known finding
closed or consciously accepted, and the closure verifiable.*

| Item | Status | Gate |
|---|---|---|
| 0.0.9 full-audit remediation queue (`docs/audit/06_FULL_AUDIT_0_0_9.md`) — top: "stays on this machine" wording ×12 (qualified default applied 2026-06-15), caveats-visible-vs-calm (✅ RULED visible-by-default + ENFORCED for briefing cards, audit PR A 2026-06-15, invariant #23), reliability_score=5 + language="en" defaults removal, inline-onclick retirement, a11y batch, ETHICS.md tense rewrite | 🔶 several fixed in-audit | RC-BLOCKING (each row closed or accepted-with-reason in the report) |
| bandit/pip-audit: blocking in CI + weekly | ✅ | stays green |
| Threat-model statements shipped wherever crypto/network claims appear (seized-machine vs compromised-session; which layer the kill switch controls) | 🔶 at-rest done (unlock.html ×2 + Settings encryption panel: "protects a seized/copied file, not a compromised running session" + no-recovery); network WHICH-LAYER done 2026-06-16 (the consent popup states airplane mode controls only THIS app's network, never device/OS/hardware — `test_ui_invariants` #14e) | RC-BLOCKING |
| External-link guard, robots fail-closed, kill switch, no-composite-scores (CardSchemaError), provenance columns | ✅ | invariant-tested |
| Fresh full review pass over the RC diff (the 06-audit method: agents + hand-verification of every critical) | ⬜ | RC-BLOCKING — scheduled as the LAST batch before tagging |

## 5. Documentation ↔ app reciprocity

| Item | Status | Gate |
|---|---|---|
| USER_MANUAL: backup/restore+encryption chapter; running-over-Tor chapter; task-manager/agenda updates; FOOS naming note | ⬜ | RC-BLOCKING |
| Claim sweep: every feature sentence in README/USER_MANUAL/QUICKSTART/ETHICS resolves to a working surface, and every shipped surface is documented (two-direction diff, the 06-audit method) | ⬜ | RC-BLOCKING |
| Translated docs: FR hand-seeded ✅; other 11 machine-drafted via local model | 🔶 | SHOULD (banner says English is authoritative) |
| ARCHITECTURE/DESIGN refreshed for backup v2 + SQLCipher | ⬜ | SHOULD |

## 6. Recommended order (maintainer veto applies)

1. **PR-E SQLCipher** (the standing next batch; smoke job already proves the
   driver on 3 OSes) → closes §1's biggest open row.
2. Backup/restore **Settings UI** + state-into-DB + USER_MANUAL chapter →
   closes the reliability story end-to-end.
3. **Network toggle + consent popup** (small, ethics-facing).
4. **Task manager + download arbitration** (twice-repeated).
5. **Reader tabs + corpora system** (the flagship surface; includes keyword
   windows + time-scope + commodity/date pivots).
6. **Agenda content batch** (recurrence, world calendars, astronomy,
   article-dates layer).
7. **Interactive charts** + indices/commodities reclassification.
8. **Continuous collection + onboarding picker** + language switcher +
   i18n long tail to ~0.
9. Win/mac lanes to REQUIRED + installer bootstraps + release action.
10. **Final audit pass + docs reciprocity sweep + CHANGES** → tag V0.1 RC.

Estimated honestly from the demonstrated pace: **8–12 further dedicated
sessions** to check every RC-BLOCKING row. "Absolutely everything" including
every POST row is materially more. The gate file is updated every session;
the day every RC-BLOCKING row reads ✅, the tag is earned — not before.
