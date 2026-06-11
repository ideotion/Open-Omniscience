# Full audit — 0.0.9 cycle (2026-06-11)

> Maintainer-commissioned ("be thorough, critical about your thinking patterns,
> self-contradictory about your choices, and always remember the ethical and
> scientific standards"). Five domains, swept by five independent passes with
> every critical claim re-verified by hand before being recorded here: the
> Python code, the documentation, the UI's user-facing text, all 12 translations,
> and GUI bugs/optimisations. A sixth section audits the auditor: this session's
> own decisions, challenged.
>
> Severity scale: **critical** (violates a §0.5 invariant or is exploitable) ·
> **high** (factually false claim or real defect users hit) · **medium**
> (honesty/UX erosion) · **low** (polish). Items marked **FIXED(this PR)** were
> repaired in the same change that adds this report; everything else is the
> remediation queue, ranked.

---

## 1. Code (Python)

**Verdict: strong discipline at the core; the defects found were at the edges
(dead code, never-called helpers, one leftover default).** Verified clean:
no composite scores anywhere (CardSchemaError holds); briefing producers carry
method+caveat+n; no boot-time network; sessions/files context-managed; SQL
parameterized throughout; the ingest race on duplicate hashes is handled;
broad `except` blocks are documented as auxiliary-never-fatal by design.

| # | Finding | Severity | Status |
|---|---|---|---|
| C1 | `src/database/async_db.py` — dead module (never imported) from an aborted async refactor, still carrying `country default="US"` (the exact fabrication removed from models.py) and a parallel schema that WILL drift. | high | **FIXED(this PR)**: moved to `quarantine/dead_src/` |
| C2 | `src/utils/url_utils.py:resolve_redirects()` — raw `requests.head()` outside the single fetch path; exported but never called. An attractive nuisance: the first caller would have bypassed robots/politeness silently. | high | **FIXED(this PR)**: removed (+ export), honest tombstone comment |
| C3 | `ExternalSource.credibility_score default=50.0` — every unknown source asserted "medium-credible". Mitigated (the link-analysis API is counts-only and never exposes it) but it is stored fabricated data. | medium | **FIXED(this PR)**: default removed; migration phase D NULLs stored 50.0s |
| C4 | `Source.reliability_score default=5` and `language default="en"`, `region default="global"` — same shape as the US default. Judgement: `reliability_score=5` is the same defect class as C3 (asserts "medium" for unrated) — queue its removal with a sweep of any consumer; `language="en"` is WRONG for the same reason (an anglophone assumption — the de-anglicising lesson from the keyword cap applies); `region="global"` is arguably config not fact. | medium | queued (needs consumer sweep + migration like the country one) |
| C5 | `/api/database/coverage` polled every ~16 s does a full `GROUP BY` + per-row tag Counter over all sources; fine at 3k sources, wasteful at the 50k catalog target. | low | queued (cache with a sources-table version stamp) |

## 2. Documentation

**Verdict: the code is more honest than its docs.** The biggest finding of the
whole audit was here:

| # | Finding | Severity | Status |
|---|---|---|---|
| D1 | `docs/ETHICS.md` opened with "**SOFTWARE NOT FUNCTIONAL / completely unusable / does not work**" (×3 banners) — factually false for many cycles. The project's honesty-over-hype stance must also bind UNDER-claims: a reader deciding whether to trust the tool was being told a falsehood in the ethics document itself. | **critical** | **FIXED(this PR)**: honest status banner; banners removed |
| D2 | `docs/ETHICS.md` asserted present-tense HTTrack fork provenance (×3). DESIGN.md itself calls the lineage "vestigial; drop the framing"; no HTTrack code remains. | high | **FIXED(this PR)**: historical note, claim corrected |
| D3 | `scripts/README.md` documented a non-existent `debug_install.sh` at length, including a `curl \| bash` from the retired `0.03` branch. | high | **FIXED(this PR)**: rewritten as an honest index of the 17 real scripts |
| D4 | Source-count drift: QUICKSTART "~1,900 outlets / ~1,780 unique", USER_MANUAL "~2,100+", seed docstrings "~1900" — reality: ~3,200 entries, ~3,180 unique domains. | high | **FIXED(this PR)**: all three updated to measured numbers |
| D5 | ETHICS.md body still carries future-tense framing ("when it becomes functional", "intended to") in many sections beyond the banners. | medium | queued: full-tense rewrite, deserves its own careful pass |
| D6 | `docs/i18n/fr/` holds only QUICKSTART while ARCHITECTURE implies a mirrored tree. | medium | queued (run `scripts/translate_docs.py` on a machine with a model — already a standing TODO) |
| D7 | ARCHITECTURE.md links a non-existent "Performance Tips" anchor; audit-archive docs (01_ARCHITECTURE) list `desk.html` sizes — point-in-time records, left as history but worth a "frozen snapshot" banner. | low | queued |
| D8 | USER_MANUAL doesn't document the crawl-depth parameter range, or the offline reader endpoint as a concept. | low | queued |

## 3. UI text / user notices

**Verdict: the caveat culture is real and often exemplary** (the /investigate
recipes' caveats, the temporal-map empty state, panic-wipe's two-factor confirm)
— but caveat *delivery* has holes: several load-bearing caveats render only if
the API happens to send them, and one headline claim overreaches.

| # | Finding | Severity | Status |
|---|---|---|---|
| U1 | "Everything stays on this machine — no cloud, no telemetry" (Home + Settings) is unqualified while Proxy/Tor fetch modes exist; in proxy mode traffic demonstrably leaves the machine. The claim is true for *the app's own behaviour* (no telemetry/cloud) but reads broader. | high | queued — wording change touches locale keys ×12, do as one keyed batch: add "; fetching follows your Network mode" or equivalent |
| U2 | Caveats rendered conditionally from API fields with NO fallback (mind-map `g.caveat`, framing `d.caveat`, temporal map `TMAP.caveat`): an empty field silently deletes the honesty layer. | high | tmap **FIXED(this PR)** (fallback text); mind-map + framing fallbacks queued (same one-line pattern) |
| U3 | "Show method & caveat" toggle defaults OFF on Home cards — defensible calm-UI choice, but it conflicts with the evidence-tiered-cards ruling (plain-English trigger sentence LEADS). Tension flagged for a maintainer ruling rather than silently "fixed": recommend caveat-on-by-default for analytic cards, or the trigger.plain line always visible (already shipped for 7 producers). | medium | maintainer decision requested |
| U4 | VADER tone numbers shown bare (e.g. `0.42`) without the −1…+1 range or "lexicon heuristic" label at the point of display (the intro paragraph has it; the table cells don't). | medium | queued (one formatter + locale keys) |
| U5 | "Fixed civic dates are confirmed" (Agenda) — "confirmed" overstates bundled iCal data; "fixed-date" is the honest word. Same family: the `unconfirmed / scheduled` pill conflates two different uncertainties. | medium | queued |
| U6 | Destructive confirms: panic-wipe/uninstall are exemplary (type-WIPE second factor); "Delete source" (removes all its articles) and "Clear draft" are single-confirm. | medium | queued (second factor or undo-toast) |
| U7 | Commodities intro omits the publication-lag note that Indices carries ("EOD, not real-time") — inconsistent caveat placement. | low | queued |
| U8 | Terminology drift: Library tab vs "Database" panel heading vs "corpus" in body text; "Collect" tab vs "Ingest" section headers. | low | queued (one-pass rename with locale keys) |

## 4. Translations (12 locales)

**Verdict: genuinely strong — and the audit pass itself produced false
positives worth recording as a lesson.** The automated sweep flagged 26
"untranslated" keys across fr/de/es/pt; hand-verification showed essentially
all are correct cognates or accepted loanwords ("Actions", "Accent", "Pages",
"Documentation" ARE French; "Region", "System", "Passphrase", "Online/Offline"
ARE German usage). Lesson: a string-equality heuristic is not a translation
audit; verify before filing.

| # | Finding | Severity | Status |
|---|---|---|---|
| T1 | Key parity 12/12 at 100% (`scripts/i18n_report.py`), `_meta` blocks correct, Arabic RTL correct, caveat/notice strings fully keyed and translated. | — | clean |
| T2 | Structural gap: composite strings with interpolated values (`"${n} source(s)"`, "page X of Y", the regional-balance pills with numbers) can never match the exact-match engine — ~5% of chrome, including some caveat-adjacent text. | medium | queued: format-string support in OOI18N (design note, not a quick patch) |
| T3 | Translation provenance isn't tracked per key (which were human-reviewed vs machine-drafted) — the docs pipeline has a provenance banner; the locale files have nothing equivalent. | low | queued (a `_meta.provenance` note + review marks) |
| T4 | The chrome long tail (untranslatable/unkeyed fragments) remains tracked by `--audit-chrome`; Agenda tab is still the priority per the standing queue. | — | already queued (standing item) |

## 5. GUI bugs / optimisations

**Verdict: one real security class found and closed; architecture is sound.**
Verified clean: NO duplicate top-level function names (the 2026-06-11 lesson —
re-checked exhaustively), no duplicate element IDs, `safeUrl()` blocks
`javascript:`/`data:` schemes, poller start/stop discipline is correct,
listeners are init-time only.

| # | Finding | Severity | Status |
|---|---|---|---|
| G1 | `esc()` did not escape `'` while three handlers embedded scraped-content keyword terms in SINGLE-quoted `onclick` attributes (`onclick='pickTerm(${JSON.stringify(t.term)})'`). An apostrophe-bearing term (real in fr corpora) breaks the attribute; a crafted term shaped like `x' onmouseover='…` becomes attribute injection → script execution. Exploitability depends on the keyword extractor's tokenization surviving quotes — one regex away from changing, so treated as real. | **critical** (defense-in-depth) | **FIXED(this PR)**: `esc()` now escapes `'` app-wide (investigate.html already did) + the three sites wrapped |
| G2 | The same *pattern* — data interpolated into inline `onclick` strings — exists at ~12 more sites, all currently fed by server-constant or esc()-wrapped values. Safe today, fragile forever. | medium | queued: migrate to `data-*` attributes + delegated listeners (one mechanical pass) |
| G3 | i18n MutationObserver re-walks the ENTIRE document on every mutation burst (debounced 120 ms): O(page) work on each toast/poll repaint. | medium | queued: apply() per added subtree |
| G4 | Coverage/library poll rebuilds the whole table innerHTML each refresh; mitigated this cycle by the change-detection stamp (skips identical payloads) — residual cost only when data actually changes. | low | acceptable; revisit at 50k sources with C5 |
| G5 | Accessibility: palette and vitals popover don't return focus on close; vitals popover lacks `aria-modal`; Sepia theme `--muted` on panel ≈2.8:1 contrast (below AA). | medium | queued (small, user-visible, do as one a11y batch) |
| G6 | `visibilitychange` resumes the live poller without an immediate tick (worst case ~6 s stale on tab return). | low | queued |
| G7 | `_covStamp` stale-error bug (the error note could outlive recovery) — found by self-review during this audit. | low | **FIXED(this PR)** (earlier commit) |

## 6. The auditor audited — this session's own choices, challenged

Per the maintainer's instruction, the contradictions I can build against my own
0.09 batch, recorded so they are decided consciously rather than by inertia:

1. **Migration phase B clears CSV-asserted `us` values.** I argued cost
   asymmetry (thousands fabricated vs rare explicit CSV-US on gTLD domains).
   The counter-argument stands: it deletes a *user assertion* the user never
   gets told about. Mitigation shipped (the trade-off is now STATED in the
   migration docstring + log line); the alternative (skip rows whose source has
   no `via:` tag) was rejected because CSV imports carry no provenance tag
   either — **the real fix is adding `via:csv` provenance at import, queued.**
2. **I chose lowercase ISO-2 after first telling the maintainer uppercase.**
   Reversed on evidence (every live consumer is lowercase). The residue:
   exports now show lowercase codes where ISO convention is uppercase —
   accepted, codes are uppercased at render. Recorded as a deliberate
   convention, not an accident.
3. **`configs/catalog_targets.yml` floors are MY numbers.** Drafted from
   actuals (+method note), but no maintainer has ratified them; the report
   brands them "working targets". They need an owner — flagged.
4. **The coverage live-poll replaced the Refresh button** on a 16 s cadence
   for data that changes rarely; arguably the wrong trade (steady background
   cost vs a click). Kept because the maintainer's ruling said "drop the button
   if data is live", and change-detection makes repaints free — but
   refresh-on-mutation would be cleaner; queued with C5.
5. **I machine-drafted 11 locales' new keys myself** without marking
   provenance (T3) — the same standard I praised the docs pipeline for. Queued.
6. **The audit agents themselves over-claimed** (translation false positives;
   an "XSS" rated critical whose exploitability is honestly *uncertain*). Every
   critical above was hand-re-verified; severities were adjusted down where the
   evidence only supported "fragile", and up where the honesty stakes (D1)
   exceeded the technical ones.

## Remediation queue (ranked)

1. **U1** — qualify the "stays on this machine" claim (keyed, ×12 locales).
2. **U2 remainder** — caveat fallbacks for mind-map + framing surfaces.
3. **C4** — remove `reliability_score=5` + `language="en"` defaults (migration, consumer sweep).
4. **G2** — retire inline-onclick data interpolation (mechanical, one pass).
5. **G5** — a11y batch (focus return, aria-modal, Sepia contrast).
6. **D5** — ETHICS.md full tense rewrite.
7. **U3** — maintainer ruling: caveats visible by default vs calm UI.
8. **U4–U8, T2–T3, G3, G6, C5, D6–D8** — as batched above.
9. **via:csv provenance** on CSV imports (the self-critique #1 fix).
