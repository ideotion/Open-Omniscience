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

## 1. The trust core (data integrity + crypto + safety)

| Item | Status | Gate | Acceptance check |
|---|---|---|---|
| Backup carries EVERYTHING (oo-backup-2 artifact, signed manifest) | ✅ | RC-BLOCKING | torture suite T5/T6; manifest lists exclusions |
| Merge-only restore (preview=commit code path, FK remap, conflicts reported, atomic swap) | ✅ | RC-BLOCKING | torture suite 10/10 green (is, today) |
| Custody chains verified-not-trusted, never spliced | ✅ | RC-BLOCKING | T9 |
| Cross-version restore floor + staged upgrade | ✅ | RC-BLOCKING | T4 |
| **SQLCipher at-rest encryption ON by default + passphrase unlock UX + doctor attestation + one-way encrypt tool (PR-E)** | ✅ 2026-06-12 | **RC-BLOCKING** | shipped in one PR per the honesty gate; 8-test suite incl. subprocess boot states + the crown (encrypted corpus stays ciphertext through backup/merge); doctor reads real headers; remaining riders: key re-wrap in the tool, launcher prompt wiring |
| State-into-DB migrations (settings/annotations/events → tables, D1/D4) | ⬜ | SHOULD | legacy JSONs imported once; artifact v3 member list updated; suite green |
| Settings → Data & backup UI on the v2 endpoints (restore preview table, encrypted-default, ×12 locales) | ✅ 2026-06-12 (T6) | RC-BLOCKING | shipped: signed-archive backup + preview→merge flow primary in Settings; plan table (new/duplicate/conflict-kept-local + samples); Apply disabled on failed verification; legacy tools demoted to a collapsed block (never silently lost); i18n 100% ×12; UI contract pinned in tests/test_restore_ui.py |
| Network kill switch: airplane-mode semantics + online-consent popup (local IPs) + immediate repaint | ⬜ | RC-BLOCKING (ethics-facing) | every online transition consented; state never lies (scrape-start repaint) |
| oo-netcut opt-in OS layer (interface-agnostic; netsh/networksetup parity) | ⬜ | POST (document app-level scope honestly in RC) | manual + sudoers doc; per-OS smoke |
| Single guarded socket factory + build-failing test (no module opens its own) | ⬜ | SHOULD | grep-test in suite |
| Newsletter scraper | ⬜ | POST (by standing ruling: only after the above is solid; no-recovery premise must be revisited first) | — |

## 2. Release engineering & portability

| Item | Status | Gate | Acceptance check |
|---|---|---|---|
| 3-OS CI matrix (the *definition* of supported) | 🔶 added 2026-06-11 | **RC-BLOCKING** | win/mac lanes graduate from observation (`continue-on-error`) to required-and-green |
| SQLCipher wheel smoke on 3 OSes (blocking job) | ✅ added | RC-BLOCKING | green on all three runners |
| Windows/macOS INSTALL path (installer logic into the package; sh/ps1 bootstraps) | ⬜ | RC-BLOCKING | a fresh win/mac machine reaches the Console via documented steps; CI installs prove the package half |
| Release artifacts from one tag + checksums documented | ⬜ | RC-BLOCKING | release action emits all artifacts; SHA256SUMS in release notes |
| Signing/notarization decision | ⬜ | POST (deferred by ruling; checksums regardless) | decision recorded |
| Version/branding sweep (0.0.9→0.1; FOOS suffix stays until the rename ruling) | ⬜ | RC-BLOCKING | pyproject single-source; grep gate |
| CHANGES.md 0.0.9→0.1 section + release notes | ⬜ | RC-BLOCKING | docs build; claims match code (see §5) |

## 3. The ruled feature queue (maintainer field reports, 0.09 cycle)

| Item | Status | Gate | Notes |
|---|---|---|---|
| Agenda: data-first restructure + month-grid default + tab fully i18n'd | ✅ 2026-06-11 | — | invariant #13 enforces |
| Agenda content: recurrence schema (+origin years, month-spans), worldwide bank holidays, religious calendars (computed/moon ±1d caveat; sourced tables), astronomy layer (Meeus moons tested vs almanac + eclipse canon), article-extracted dated events layer | ⬜ | RC-BLOCKING (the maintainer's "all and everything accessible") | every entry carries method+accuracy; zero-network boot kept |
| Agenda: remaining views (week/trimester/semester/year/decade) | ⬜ | SHOULD | month+list shipped |
| Task manager window (repeat ×2; acceptance: reorder fr-before-en wiki dumps; per-country scrape priority) + download arbitration (queue/prioritize/cancel) | 🔶 2026-06-12 (T9 slice 1: visible jobs view, REAL reorderable dump queue — fr-before-en works end-to-end and is tested; arbitration ask on collect) | RC-BLOCKING (twice-repeated ask) | REMAINING: per-country scrape priority; arbitration ask on remaining starters; richer pass-time estimates |
| Reader TABS (mindmap/related/source/keywords/sentiment) | ⬜ | RC-BLOCKING (twice-repeated ask) | bar: sleek, data-rich, scientifically driven |
| The ONE corpora system (6 entries: hand/tag-selection/tag-click/commodity-click/keyword-click/date-keyword-click; keyword windows = same sub-tabs + events sub-tab + TIME-SCOPE control) | ⬜ | RC-BLOCKING (the flagship analysis object) | one window architecture, n=1..N |
| Interactive charts (zoom/pan/X-Y readout/legends; kill the 5-point cap; real curves) | 🔶 2026-06-12 (T8 slice 1: ooChart toolkit + markets symbol + insights trend; invariant #16) | RC-BLOCKING (live-test complaint) | >6mo scales render full series; REMAINING: commodity-card enlarge + indices board detail onto the toolkit |
| Commodity → keyword-family pivot (price curve + article-timeline overlay; symbol→family seed table) | ⬜ | SHOULD | co-occurrence framing, never causation |
| Continuous collection (per-country round-robin + first-run approval + onboarding country/language picker; explainable schedule) | ⬜ | SHOULD | consent design shared with network popup |
| When×Where×Who extraction at ingest + backfill (confirmed GO) | ⬜ | SHOULD (substrate for convergence) | reader stops recomputing; map gains event-places |
| Convergence detection + watch rules (the 0.0.9 flagship, layers 3+4) | ⬜ | POST (honest: too large to rush into an RC; ships in 0.1.x with its own design) | maintainer veto point |
| Permanent top-bar language switcher (flag + native name) | ✅ 2026-06-12 (T7) | RC-BLOCKING (reputation ×12 languages) | shipped: 12-language menu (flag = cue, native name = identifier), one click through OOI18N.setLang (DOM re-walk + t() for dynamic strings), Settings sync, invariant #15 |
| i18n long tail → ~0 (audit-chrome per tab) + Home-card title translation design | ⬜ | RC-BLOCKING | `i18n_report.py --audit-chrome` ≈ 0 per tab |
| French easter eggs (transnational, translatable) | ⬜ | SHOULD | personality.yml |
| Tor transport-awareness in per-host verdicts + "running over Tor" manual chapter (logs pending from maintainer) | ⬜ | SHOULD | verdicts distinguish robots/Tor-refused/down |
| Global search rework (omnibar absorbs Search tab — only after parity) | ⬜ | POST | the Desk lesson: never lose a tool |
| Indices/commodities reclassification + #commodities alias; more feeds (rare earths, LNG, cereals…) | ⬜ | SHOULD | per-index verdicts in UI |
| Home cards → per-type investigate views | ⬜ | SHOULD | every card clickable |
| Evidence-tiered cards remaining slices; corpus tier header | ⬜ | SHOULD | plain sentence + math, translated |
| Custody tab UX (rename/explain/guided) | ⬜ | SHOULD | non-expert comprehension test |
| De-US-centring remainder: Wikidata gap run (maintainer's machine) + raise located share (49% unlocated) | 🔶 | SHOULD | coverage report metric moves |
| Trans-language equivalence rings → LIVE analytics merging | 🔶 groundwork | SHOULD | fr:élections+en:elections = one concept, per-language counts visible |
| Offline LLM kit (RM-08); translated-docs drafting run (needs a machine with a model) | ⬜ | POST | — |
| Wikipedia-as-a-source; smart calendars; event-family merge/split UI; offline vector map; onboarding track | ⬜ | POST | recorded designs |

## 4. Security & ethics gate (the "impeccable" clause, honestly framed)

Security is a process, not a state — the RC claim is: *every known finding
closed or consciously accepted, and the closure verifiable.*

| Item | Status | Gate |
|---|---|---|
| 0.0.9 full-audit remediation queue (`docs/audit/06_FULL_AUDIT_0_0_9.md`) — top: "stays on this machine" wording ×12 (AWAITS MAINTAINER RULING), caveats-visible-vs-calm (AWAITS RULING), reliability_score=5 + language="en" defaults removal, inline-onclick retirement, a11y batch, ETHICS.md tense rewrite | 🔶 several fixed in-audit | RC-BLOCKING (each row closed or accepted-with-reason in the report) |
| bandit/pip-audit: blocking in CI + weekly | ✅ | stays green |
| Threat-model statements shipped wherever crypto/network claims appear (seized-machine vs compromised-session; which layer the kill switch controls) | 🔶 backup/design done; UI pending PR-E + network batch | RC-BLOCKING |
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
