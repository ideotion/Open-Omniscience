# 10 — Transversal audit (2026-09-08)

> Commissioned as a general "transversal, functional, comprehensive audit covering the visual aspects
> of the app, its translation throughout the UI, its code structure, its function, tools and claims,
> its documentation, and its code structure, health, simplicity, efficiency and safety... report,
> don't fix." Per this project's own C8 discipline, this is **not** a from-scratch re-derivation of
> [`07_TRANSVERSAL_AUDIT_V01.md`](07_TRANSVERSAL_AUDIT_V01.md) (2026-06-12),
> [`08_TRANSVERSAL_AUDIT_0.3.md`](08_TRANSVERSAL_AUDIT_0.3.md) (2026-07-21), or
> [`09_TRANSVERSAL_AUDIT_0.3_DELTA.md`](09_TRANSVERSAL_AUDIT_0.3_DELTA.md) (2026-07-25) — §2 disposes of
> 09's own findings first, and everything after that is scoped as new coverage of the ~6 weeks of work
> that shipped since (roughly PRs #7xx through #1042 — the tree grew from 09's base commit `2aa8dc3` to
> today's `faff1fc4`, including the 2026-09-06/07 self-analysis effort at
> [`docs/plans/2026-09-06-repo-analysis/`](../plans/2026-09-06-repo-analysis/00_INDEX.md), which this
> audit treats as a peer document to check against, not a substitute for independent verification).
> **This report is intentionally report-only, per the commissioning instruction: no finding below was
> fixed as part of writing it.**

## 0. Methodology & honest scope

A 68-agent orchestrated workflow ran against the live `main` tip (`faff1fc4bc08b028a54ed76fc1b20c35a53d1f91`,
fetched fresh at session start): **20 generation agents**, each scoped to a disjoint slice of the
~1,482-file, ~46-module tree (frontend shell, the 8-skin GUI gallery, i18n, network safety, the
scheduler, the database/ORM layer, the API surface, crypto/backup/custody, the AI/LLM layer, the
statistics/analytics primitives, each of the five content verticals split two ways, the shared
utilities, docs-vs-code claims, the ledger's own self-discipline, the test suite itself, dependency
security, dead-code/duplication, and efficiency), followed by **48 independent adversarial skeptic
re-verifications** — one per P0/P1/P2 candidate finding, each told to default to refutation and
re-derive the cited evidence itself from the real files, with no access to the original claimant's
reasoning. ~6.9M subagent tokens, 1,884 tool calls, ~93 minutes wall-clock, zero agent failures.

**112 of 115 raw findings survived a title-level dedup pass unchanged** (three exact-title duplicates
were merged). Of the 48 adversarially verified candidates, **47 were confirmed as factually accurate**
(most with the claimed severity, several with the skeptic revising the severity up or down — see the
tables below, which report the **adjusted, post-verification severity**, not the original claim) and
**1 was refuted** (§6.3, a process-discipline finding whose central claim was accurate but whose
conclusion was contradicted by text the claimant hadn't read far enough to see). Beyond the in-workflow
skeptic layer, I (the orchestrating session) additionally **hand-verified a further, independent set of
facts myself** directly against the tree — real tool runs, not agent claims — covering: `mypy` (0 errors
across 514 files, matching the pinned `2.3.1` via the correct Python 3.13 interpreter), `ruff` (450/450
against the exact CI-pinned `0.16.6`, zero slack), both i18n ratchets (554/554 and 295/295, zero slack),
`bandit` (0 medium/high-severity findings; 191 low, spot-checked), `pip-audit` against the pinned
`requirements.lock` (one live, previously-unreported CVE — §5.6), a duplicate-key scan and conflict-marker
grep across every ledger file, and the CLAUDE.md line ratchet (616/616, exact). These are folded into the
relevant sections below and marked **[hand-verified]**.

**What this is not:** not a live penetration test (no running server instance exists in this sandbox to
attack); not a browser-driven UI walk (no Chromium session was launched — the visual-core and
guis-gallery findings are static-source-level, like the 2026-07-28 GUI audit); not a full-suite `pytest`
run (this sandbox ships Python 3.11 by default with no project dependencies installed; `python3.13` is
present and was used for every static tool that matters, but installing the full `[analysis,dev]` extra
tree to run the real suite was judged out of scope for a report-only session); not a fuzzing or
dependency-graph-wide audit (`bandit` + `pip-audit` + targeted manual review, not Semgrep/CodeQL/AFL).

## 1. Executive summary — top findings

| # | Severity | Finding | One-line impact |
|---|---|---|---|
| 1 | **P0** | A **live, reachable stored-XSS** in the article-evidence link handler: `esc()`'s HTML-entity-escaping of `'` does not stop an attacker-controlled URL from breaking out of a hand-written inner JS string literal inside an inline `onclick`, because the browser HTML-decodes the attribute *before* compiling it as the handler's JS body. | Ingesting an ordinary hostile site and clicking its evidence link on the Home feed executes attacker JavaScript in the app's own page context. |
| 2 | **P0** | The **anti-hallucination grounding check** behind the whole Layer-B bulletin-narration honesty story (`src/bulletin/grounding.py`) uses **substring containment, not exact matching** — a fabricated number or name that happens to be a substring of a real one in the evidence (`"40"` vs real `"1,240"`; `"The Continental Bank"` vs real `"The Intercontinental Bank"`) is verdicted as grounded/supported. | The one mechanical guarantee behind "every figure and name in this LLM-generated sentence appears in the evidence" is false for exactly the near-miss failure mode real LLMs actually produce. |
| 3 | **P1** | **OpenTimestamps chain-of-custody anchoring** — found independently from three different angles (the ingest pipeline, the API endpoint, and the manual UI button) — performs real, privacy-sensitive network egress (IP + timing to three public Bitcoin-calendar servers) with **no `ensureOnline` consent gate anywhere on the reachable path**, contrary to both the code's own docstring ("real egress under explicit consent") and CLAUDE.md invariant #14/#14e. | An operator who has enabled OTS anchoring (opt-in, but only a static warning, never a per-action popup) silently phones three third-party servers on every ingested article and on every manual "Anchor root" click. |
| 4 | **P1** | The **i18n completeness CI gate is structurally blind to the `t9()`/`t9m()` alias family** used throughout the newer UI modules — the regex only matches literal `t(`. At least 10 live, production strings (including the top-bar Collection on/off toggle and the invariant-#4 rate-toggle knob) have **no locale key in any of the 12 languages** and render in English forever, while the gate reports itself exactly saturated and green. | A maintainer-mandated "locale files must stay 100%" ritual is currently false for at least 10 real, user-facing strings, with no mechanism able to catch a new one. |
| 5 | **P1** | **Six numbered UI invariants (#9–#13, #22) are still mechanically enforced by `test_ui_invariants()` but have vanished from CLAUDE.md's own numbered list** — including a dangling self-reference to the missing #13. This is exactly the "work regressed between sessions" failure mode rule (4) exists to prevent, now happening to the rule-(4) mechanism itself. | A future session that reads CLAUDE.md "in full" per its own mandatory-reading rule will never learn what invariants #9–#13/#22 (evidence-tiered cards, bundled fonts, themed widgets, the Typeface picker, the agenda's data-not-plumbing rule, the analysis window) actually require. |
| 6 | **P1** | **Settings → Source qualification's two scope checkboxes silently fail to save and then visibly revert**, right after a false "Saved." toast — the API's Pydantic model doesn't declare the two fields, so Pydantic v2 quietly drops them before they reach the settings dataclass that does support them. | A maintainer-facing control that looks like it works does nothing, with zero test coverage of the actual HTTP round trip. |
| 7 | **P1** | The **source qualification → collection promotion frontier is still fully unbuilt** (re-verified fresh against today's tree, not trusted from the 2026-09-06/07 inventory): a qualified verdict never sets `Source.enabled`, so real Tor bandwidth is spent trial-fetching tens of thousands of disabled candidates whose positive verdict can have zero effect on what ever gets collected. | Ongoing, silent, unbounded waste of exactly the "bounded, consented, respectful network use" the project states as a non-negotiable design center. |
| 8 | **P1** | A **Mann-Whitney U effect-size formula is mathematically wrong** (`src/analysis/statistical_tests.py`) — verified by independent scipy execution to report 0.43 instead of a true 1.0, and 0.14 instead of a true 0.33 — on an API module whose own docstring advertises "the real statistic... never a fabricated number," with zero test asserting the actual value. | A silently wrong number shipped as fact on a credibility-branded "no fabrication" endpoint. |
| 9 | **P1** | The **watched-Wikipedia-page `wiki` code is never validated** before being f-string-interpolated into a live outbound fetch URL (unlike the sibling dump-download path, which already has the exact guard). A crafted code (e.g. `attacker.example#`) hijacks the request's real destination — **reproduced live** with `urlparse`. Triggered automatically by every scheduled collection pass once such a page exists. | A URL-injection primitive in a normal, unauthenticated, scheduler-driven code path, of the exact class the project's own SSRF-guard non-negotiable exists to prevent. |
| 10 | **P1** | `GET /api/sources/` (the Settings page's own source list, called with `limit=1000`) computes each row's article count via `len(s.articles)`, forcing a **full decrypt-and-materialize of every article body of every source** just to produce an integer — the identical bug already fixed for the sibling `source_io.py` endpoint via a maintained counter column, never applied here. | An uncapped, reachable N+1 that can turn a routine Settings page load into a full-corpus SQLCipher decrypt on a prolific corpus. |
| 11 | **positive** | The **prior audit's (2026-07-25) P0 finding — the SOCKS/Tor airplane-mode bypass — is genuinely fixed and further hardened**, and a second, independent connect-time SSRF guard closes an additional DNS-rebinding gap in the same patch layer. Also fixed: the B6 who/where/when LLM-extraction gating bug (2026-07-25 P0), the folder-backup symlink-follow bug (2026-07-25 P1), the Pillow CVE (2026-07-25 P1), and the USER_MANUAL qualification-documentation gap (2026-07-25 P1). | Every P0/P1 the prior full audit found has either been fixed and confirmed fixed, or (in the SOCKS case) fixed and further hardened with an independent second gate. |

Full detail for all 115 raw findings (2 P0 · 13 P1 · 25 P2 · 26 P3 · 32 positive · 16 info, after
adversarial re-severity-adjustment; one candidate refuted) follows below, organized by severity, then
by the dimension it came from.

## 2. Disposition of the 2026-07-25 audit's findings

Every P0/P1 from `09_TRANSVERSAL_AUDIT_0.3_DELTA.md` was independently re-checked against today's tree,
not trusted from the ledger's own "shipped" claims:

| 09's finding | Verdict today | Evidence |
|---|---|---|
| §2 P0 — airplane-mode socket guard blind to SOCKS/Tor traffic | **FIXED, and hardened further.** | `airplane.py` now also patches `http.client.HTTPConnection._tunnel` and PySocks' `socksocket.connect`, checking the real destination on both paths. A *second*, independent connect-time SSRF guard (`ssrf_guard.py`, added 2026-09-07 as NET-01) closes a further DNS-rebinding gap in the same patch layer, so a call site cannot satisfy one gate and miss the other. — **New gap found in the fix itself:** the three regression tests that specifically exercise the SOCKS patch (`test_airplane_socket_guard.py:212,224,237`) all call `pytest.importorskip("socks")`, and PySocks is installed in **no** CI lane (not declared anywhere in `pyproject.toml`, no workflow installs it) — so the safety net for the exact code that closed this P0 silently skips in every CI run today (§4.2). |
| §item 2 P0 — B6 `gate_languages_from_report()` reads the wrong nesting level, permanently gating every language | **FIXED, genuinely.** | The function now correctly unwraps `report["report"]["by_language"]`, both real production call sites feed it the full enveloped artifact, and the regression test exercises the *real* harness envelope end-to-end rather than a hand-typed mock — exactly the guard needed against this class of bug recurring. |
| §item 3 P1 — path-traversal-via-symlink in `restore_folder_backup` | **FIXED, genuinely, and the pattern is now applied defense-in-depth in the newer file-placement code too.** | `restore_folder_backup` now checks `p.is_symlink()` before any `open()`, mirroring `verify_folder_backup`'s pre-existing guard; the 2026-09-07 `place_artifact_file_members` independently re-derives the same containment check even though its manifest is already validated upstream. |
| §item 4 P1 — Pillow 12.2.0 pinned with reachable DoS CVEs, fixed in 12.3.0 | **FIXED.** | Both `pyproject.toml`'s floor and `requirements.lock`'s resolved pin now read `12.3.0`, with no ceiling permitting a downgrade. |
| §item 5 P1 — missing `session.rollback()` cascading false failures in archive-backfill/housekeeping loops | **Not re-examined this session** (out of the 20 dimensions' explicit scope; no finder happened to hit this specific code path). Carries forward as unverified-since-09. | — |
| §item 6 P1 — Tor-exit-resolve (SOCKS RESOLVE) design-only vs. claimed-implemented in the 0.3 gate | **Not re-examined this session.** Carries forward as unverified-since-09. | — |
| §item 7 P1 — USER_MANUAL has zero mentions of "qualification" | **FIXED.** [hand-verified] | `docs/USER_MANUAL.md` now has a full "Source qualification — the admission gate" section (37 matches for "qualif", confirmed via direct grep). |

Two of 09's seven P0/P1 items (the rollback bug and the Tor-RESOLVE gate mismatch) simply weren't inside
any of this session's 20 dimension scopes and should not be read as "still open" or "closed" — they are
untouched. Everything else disposed of above was independently re-derived from the current tree, not
copied from a ledger claim.

## 3. Critical findings (P0)

### 3.1 Stored XSS via `esc()`'s incomplete defense against inner-JS-string breakout in `onclick` handlers

**Area:** visual-core · **Files:** `src/static/app-home.js`, `src/static/app-core.js`, `src/api/main.py`, `src/briefing/producers.py`

`esc()` (`app-core.js:26-27`) HTML-entity-escapes `'` to `&#39;` specifically to stop attribute breakout,
per its own comment ("data reaches single-quoted attributes (onclick='…')... audit 0.0.9"). That defense
closes the *outer* HTML-attribute delimiter, but several call sites additionally wrap the escaped value in
a **hand-written, inner single-quoted JS string literal** inside the `onclick` text itself — e.g.
`extLink()` (`app-home.js:1494-1495`):
```
onclick="event.preventDefault();openLinkPreview('${esc(u)}')"
```
The browser's HTML parser decodes character references in an attribute value **before** the decoded
string is compiled as the event handler's JS body — so `&#39;` round-trips back to a literal `'` by the
time the JS engine parses `openLinkPreview('...')`, and that restored quote closes the inner string
literal early. A URL such as `http://evil.example/'-alert(document.cookie)-'` passes `safeUrl()`
unmodified (it only checks the scheme and strips control characters — apostrophes, parens and operators
are untouched, and an apostrophe is legal, unescaped, in a URL path per RFC 3986), so the emitted markup
decodes to `openLinkPreview('http://evil.example/' - alert(document.cookie) - '')` — the
`alert(document.cookie)` call executes as a side effect of evaluating the (nonsensical, NaN-valued)
arithmetic expression the moment the user clicks. `script-src 'self' 'unsafe-inline'`
(`src/api/main.py:555`) does not block inline handlers, so there is no CSP backstop. The reachable,
attacker-controlled data is the article's own URL: `src/briefing/producers.py:391` builds card evidence
directly from the stored article's URL — the address of a page the adversary's own site served, which
they fully control.

**Skeptic verification:** every cited line re-read verbatim at HEAD; the core mechanism (HTML entity
decode happens before inline-handler JS compilation) is standard, well-documented browser behavior; no
sanitizer, CSP nonce, or URL normalization anywhere in the codebase strips the character that matters.
**Confirmed, not refuted.**

This is a **different** bug from the one the 0.0.9 audit's G1 closed (breaking out of the *outer*
attribute — correctly fixed by entity-escaping `'`), and it **refines and contradicts** that audit's own
G2 assessment of the same interpolation *shape* elsewhere as "safe today, fragile forever" — at this
specific site, it was never actually safe. The codebase's own established safe idiom,
`esc(JSON.stringify(x))` (present at 25+ other call sites — `app-corpus.js`, `app-insights.js`,
`app-map.js`, `app-ai-tools.js`), correctly backslash-escapes the JS string delimiter before HTML-escaping,
closing exactly this gap. §4.1 documents ~13 further sites carrying the same *shape*, downgraded to P3
on verification because their interpolated values are traceable to app-generated (not scraped) strings.

### 3.2 Bulletin narration's anti-hallucination check uses substring containment, not exact matching

**Area:** catalog-sources-pipeline · **Files:** `src/bulletin/grounding.py`, `src/bulletin/narration.py`, `src/bulletin/introduction.py`, `tests/test_bulletin_grounding.py`

`src/bulletin/grounding.py` is the mechanism the entire Layer-B narration honesty story rests on: every
generated sentence is checked with `check_sentence()` and dropped unless every number/name in it "appears
in the evidence" — the shipped, user-facing caveat text (in all 12 locales) tells the reader narration
sentences are "kept only because every figure and name in them appears in the articles it was shown. That
check catches invented facts." In fact the containment test is a **plain Python substring check**
(`n not in <folded evidence string>` for numbers at line 168, `_fold(r) not in ev` for names at line 201)
rather than exact token/number membership. Since number normalization strips grouping separators, any
digit run that occurs *inside* a longer real number in the evidence is reported "found" even though the
evidence never asserts that number. **Reproduced live** by the skeptic, independently, with real code
execution:

```
check_sentence('Coverage reached 40 articles this week.',
                'The corpus holds 1,240 articles about the European Commission this week.',
                language='en')
→ {'supported': True, ..., 'missing': []}   # same for 12, 24, 124, 240 — any substring of "1240"
```

The same containment flaw affects the capitalized-name check: evidence naming "The Intercontinental Bank"
grounds a fabricated sentence about "The Continental Bank" (a literal substring). This is exactly the bug
class this codebase's own `LESSONS.md` repeatedly calls out ("a substring proves only that a token appears
somewhere") — recurring, unnoticed, in the newest and most safety-critical instance of the pattern.
`tests/test_bulletin_grounding.py` never exercises this because every invented-figure test case is
digit-disjoint from the real figure by construction, so the suite is green while the check silently
under-protects against exactly the near-miss LLM failure modes (a transposed/truncated digit, a
slightly-renamed entity) that are common in practice, not contrived.

**Skeptic verification:** independently re-derived both hand-checked cases with live scipy/Python
execution rather than trusting the claimant's arithmetic; confirmed `check_sentence` is the sole gate
before a generated sentence is kept (`narration.py:194`, `introduction.py:217`); confirmed the exact
caveat wording is shipped verbatim across all 12 locale files. **Confirmed, not refuted.**

## 4. High-severity findings (P1)

Thirteen findings hold at P1 after adversarial re-verification (three raw P1 candidates were downgraded
to P2/P3 on verification and are covered in §5/§6; one raw P0 candidate was downgraded to P1 and is
folded into §4.3 below).

### 4.1 The i18n completeness gate is structurally blind to `t9()`/`t9m()` aliases

**Area:** i18n-translation · **Files:** `scripts/i18n_report.py`, `src/static/app-sources.js`, `src/static/app-corpus.js`, `.github/workflows/ci.yml`

`unkeyed_t_calls()` (backing the CI-blocking `--max-unkeyed-t-calls 295` gate) matches only literal
`\bt\(...` call sites. Many modules locally alias `OOI18N.t` to `t9`/`t9m` (`const t9 = (window.OOI18N &&
OOI18N.t) ? OOI18N.t : ((s) => s);`) and then call `t9("literal")` — a shape the regex structurally
cannot see (the digit sits between `t` and `(`). At least 10 confirmed production strings have no key in
*any* of the 12 locale files, including the top-bar **Collection is ON/OFF** toggle label
(`app-sources.js:876-877`) and the 2026-07-23-ruled rate-toggle knob's hover title and toast confirmations
(`app-sources.js:833-855`), plus the corpus chart's scale-mode labels (`app-corpus.js:1372-1398`). Because
`i18n.js`'s `t()` falls back to the raw English string on a miss, all of these render in English for every
one of the 11 non-English locales, forever, while the CI gate — which today sits exactly at its ceiling of
295 — has zero visibility into the `t9` family and will never flag a new one. §5.1 lists two more
concretely-identified untranslated `t9()` strings on the same mechanism.

**Skeptic verification:** ran the actual tool (295, exact ceiling match); confirmed programmatically that
none of the `t9(` sites in `app-sources.js` match the audit's own regex; confirmed 10/11 cited strings are
absent from `en.json` (the 11th happens to have an unrelated existing key). **Confirmed at P1.**

### 4.2 PySocks regression tests for the fixed SOCKS P0 skip in every CI lane

**Area:** network-safety · **Files:** `tests/test_airplane_socket_guard.py`, `pyproject.toml`, `.github/workflows/ci.yml`

*(Originally rated P0 by its finder as a live re-opening of §2's fixed bypass; the skeptic downgraded it
to P2 — see §5.2 — after confirming the actual runtime guarantee is unaffected. It is placed here in the
narrative because it's the direct sequel to §2's disposition, not because of its final severity.)*

### 4.3 OpenTimestamps custody anchoring bypasses the app's consent gate on three independent paths

**Areas:** crypto-backup-custody, api-surface *(three raw findings — one from each of the ingest,
API, and frontend angles — converged on the same underlying gap and are merged here)* ·
**Files:** `src/ingest/pipeline.py`, `src/custody/log.py`, `src/custody/timestamp.py`, `src/custody/anchor.py`, `src/api/custody.py`, `src/static/app-ai-tools.js`, `src/static/index.html`, `tests/test_network_consent.py`

Once an operator opts into `anchoring_mode="opentimestamps"` in Settings (off by default, one checkbox,
static warning text), **three separate reachable paths** perform real, synchronous outbound submissions
to three public OpenTimestamps calendar hosts (`a.pool`, `b.pool`, `alice.btc.calendar.opentimestamps.org`)
with **no `ensureOnline` consent gate anywhere in the chain**:

1. **Every ingested article, automatically.** `src/ingest/pipeline.py:237` calls `_maybe_record_custody()`
   unconditionally on the per-article store path; `CustodyLog.record()` → `_default_timestamp()` →
   `ots_stamp()` loops **sequentially** over the three calendars (10s timeout each — up to ~30s of
   ingest-blocking if calendars are slow), with zero kill-switch/consent check anywhere in the call chain
   (`kill_switch_active` appears at 27 sites in `src/`, none of them in `custody.py`/`anchor.py`/`timestamp.py`).
2. **`POST /api/custody/anchor`.** The endpoint calls straight into `OpenTimestampsAnchorProvider.anchor()`
   → `ots_stamp()` with no check of its own, even though `timestamp.py`'s own docstring says "submitting to
   a calendar is real egress under explicit consent, so a capability probe must never perform it."
3. **The Settings "Anchor root" button.** `anchorRoot()` (`app-ai-tools.js:1734-1743`) calls the API
   directly — no `ensureOnline`/`ensureAiEgress` wrapper, unlike every comparable network-triggering
   button in the codebase (`installVllm`, `qualifyBulkStart`, collection start).

If the kill switch is engaged, the process-wide airplane socket guard (§2) still blocks the raw connect
(fail-closed, not a security hole) — but while the app is online, all three paths fire with only a static
hover tooltip and caveat line, never the transactional "this is about to leave the machine, continue?"
popup invariant #14/#14e requires. The socket-importer ratchet (`test_network_consent.py`) is structurally
blind to this because it only greps for `import requests`/`import httpx`; `timestamp.py` imports `from
opentimestamps.calendar import RemoteCalendar`.

**Skeptic verification (all three, independently):** every cited line, function, and call chain re-read
verbatim at HEAD; confirmed the docstring's own "explicit consent" language is directly contradicted by
the actual code; confirmed the app's own established `ensureOnline` pattern is present at the analogous
sibling call site (`app-backup.js:1963`) and absent here. The path-1 finding was originally rated P0;
the skeptic downgraded it to P1, noting it is opt-in, fails open safely (never breaks ingestion, honest
fallback), ships an unusually forthright privacy warning, and is an *extension* of an existing gap (the
DuckDuckGo discovery toggle has the identical missing-`ensureOnline`-on-save pattern) rather than a novel
class of failure. Paths 2 and 3 confirmed at P1 as independently rated. **Net: confirmed P1**, not
refuted on any of the three angles.

### 4.4 Six numbered UI invariants have vanished from CLAUDE.md's own list, though the test suite still enforces them

**Area:** ledger-protocol-discipline · **Files:** `CLAUDE.md`, `tests/test_repo_invariants.py`

`test_ui_invariants()` still enforces invariant paragraphs **#9** (evidence-tiered cards / "Why am I
seeing this?"), **#10** (bundled open-source fonts), **#11** (themed form widgets), **#12** (the Typeface
picker), **#13** (the agenda shows data, never plumbing), and **#22** (the analysis window) — six live,
asserting blocks at `test_repo_invariants.py:2125,2129,2143,2148,2152,2623`. But CLAUDE.md's numbered
invariant section jumps straight from "7. External links..." to "14. Network toggle...", and separately
from "21. INSIGHTS auto-indexes..." to "23. BRIEFING CAVEATS...". CLAUDE.md even still contains a
**dangling cross-reference** to the missing content: its own trailing "8." bullet reads "First applied:
Agenda (invariant #13 in `test_ui_invariants`)" — proving this isn't an intentional renumbering. This
directly violates the file's own rule (4) ("Critical invariants are ALSO enforced by
`test_ui_invariants`... extend that test whenever one is added here... It exists because work regressed
between sessions... and the maintainer had to repeat earlier rulings") and rule (5c)'s explicit warning
that the size ratchet must never be satisfied "to make room for something rules (5)/(5a) would have sent
to `docs/ledger/`" — UI invariants are constitution content, never shipped-work to compress away. No note
in `LESSONS.md`/`OPEN_QUEUE.md`/`SHIPPED_LOG.md` explains or authorizes the removal; the most plausible
mechanism is the 2026-09-07 rule-A3 restructuring that brought the file down to its 616-line ceiling.

**Skeptic verification:** reproduced the full invariant-number sequence via grep (1,2,3,4,5,6,7,14,...23,
30,31,8 — 9/10/11/12/13/22 genuinely absent as paragraphs); confirmed all six test blocks are live and
asserting, not dead code; confirmed no ledger note authorizes the removal. **Confirmed at P1** — a
correctness/process defect in the project's own designated source of truth, silently enforced by tests
but unreadable by any future session, with no counter-evidence of a deliberate, documented removal.

### 4.5 Two more genuine, independently-confirmed functional bugs

- **Qualification-scope checkboxes silently fail to save, then revert, after a false "Saved." toast**
  (scheduler-jobs; `src/api/scheduler.py`, `src/static/app-ai-tools.js`, `src/scheduler/settings.py`).
  `SchedulerConfigUpdate` doesn't declare `scrape_unqualified`/`scrape_app_provided_only` (nor
  `auto_track_signals`/`archive_backfill_per_pass`), so Pydantic v2's `extra='ignore'` silently drops them
  before `save_settings()` ever sees them; the frontend re-GETs and resets the checkbox to its unchanged
  value right after toasting success. The sibling field `qualification_recheck_per_pass` was fixed for
  exactly this trap (its own code comment says so); these two were not. Zero test coverage of the actual
  HTTP round trip. **Confirmed at P1.**
- **The scheduler-wired auto-on-ingest custom AI extractors hardcode `OllamaClient()`**, bypassing
  `src/llm/backend.py`'s documented single Ollama-vs-vLLM resolution seam (ai-llm-briefing;
  `src/ai_layer/auto.py:101`, `src/scheduler/runner.py:2088`). The regression test that pins the seam's
  three known consumers never mentions this fourth one. On a vLLM-only host (an explicitly supported
  configuration), `OllamaClient.is_available()` deterministically returns `False`, so `run_auto_on_ingest`
  silently no-ops forever — the identical "shipped feature silently does nothing forever" shape as the
  already-fixed B6 bug (§2). **Confirmed at P1.**

### 4.6 A wrong statistical formula on a "never fabricated" endpoint

**Area:** analysis-analytics-stats · **Files:** `src/analysis/statistical_tests.py`, `src/api/analysis.py`, `tests/test_statistical_tests.py`, `tests/test_analysis_api.py`

`mann_whitney_u()`'s reported "effect size" is `1 - (2 * min(r1, r2) / (n1 + n2 + 1))` using mean ranks —
not the rank-biserial correlation (the correct closed form is `1 - 2*U/(n1*n2)`), nor any recognized
Mann-Whitney effect-size formula. The skeptic independently re-derived both of the finder's hand-checked
cases with live scipy execution: perfect separation (`[1,2,3]` vs `[4,5,6]`) should read 1.0 and the code
returns 0.4286; a case with true rank-biserial 0.333 returns 0.143 instead. The bug is reachable via
`POST /api/analysis/mann-whitney`, in a module whose docstring explicitly advertises "the real statistic,
p-value, sample size, effect size and method... never a fabricated number." Neither test asserting this
endpoint checks the actual `effect_size` value — only that it's present. **Confirmed at P1**, not because
it crashes anything (the U-statistic and p-value, which come straight from scipy, are correct — only the
derived effect size is wrong), but because it is a silently wrong number shipped as fact by a
credibility-branded, explicitly no-fabrication API. Notably, every other statistical primitive checked in
the newer `src/signals`/`src/stats` layer (Wilson/Katz intervals, BH-FDR, MinHash/Jaccard, robust-z) was
independently hand-verified mathematically correct — this defect is isolated to the older, more
generically-translated `src/analysis` "Pillar 2" module (§8, info).

### 4.7 Elections' three-tier date-confidence system is computed but never rendered

**Area:** verticals-markets-civic · **Files:** `src/civic/elections.py`, `src/events/catalog.py`, `src/static/app-agenda.js`

`src/civic/elections.py` implements a carefully-designed three-tier confidence system (scheduled / window
/ projected) with four distinct, maintainer-ruled caveat strings, including a "projected date passed —
status unknown" investigative-lead case. `events/catalog.py`'s `agenda()` calls `annotate_election()` on
every event, so the served JSON genuinely carries `date_confidence`/`date_caveat`/`projection` — but a
repo-wide grep of every static JS/HTML file for those keys returns **zero hits**. The only rendering
function (`agRow()`) branches solely on the pre-existing generic `e.confirmed` boolean, so a window-tier
election, a projected-tier election, and a passed-projection election all render with the identical
generic "approx · check source" pill. **Confirmed at P1** by the skeptic (all cited lines/functions
verified live and reachable, not dead code) — real backend investment, invisible at the UI, on a
maintainer ruling (V1_PATHWAY §4.5) specifically about a domain the project cares about getting right.

### 4.8 Watched-Wikipedia-page code is never validated before reaching a live fetch URL

**Area:** verticals-law-wiki-geo · **Files:** `src/api/wiki.py`, `src/wiki/track.py`, `src/wiki/mediawiki.py`, `src/wiki/dumps.py`, `src/scheduler/runner.py`

`POST /api/wiki/pages` (`add_page`) accepts an arbitrary `wiki` string and only checks it's non-empty —
never through `validate_wiki_code`, the exact guard `src/wiki/dumps.py` already uses **because**, per its
own docstring, the code "flows into a filesystem path AND into `dump_url`'s path." `ensure_page` stores it
with only `.strip().lower()`. That stored value is later handed unvalidated to
`api_endpoint()`: `f"https://{code}.wikipedia.org/w/api.php"`. The skeptic **independently reproduced the
exploit primitive** with Python's own `urlparse`: a code of `attacker.example#` turns the f-string into a
URL whose parsed `netloc` is `attacker.example` — a real host hijack, not theoretical. `guarded_session`
(the shared fetch wrapper) only handles the kill switch, Tor routing, and User-Agent — it has **no
destination-host restriction of any kind**. `src/scheduler/runner.py:702` calls this path on every normal
scheduled collection pass once such a page exists. **Confirmed at P1** — a real URL-injection primitive on
a documented, unauthenticated-by-design local API endpoint, exercised automatically and repeatedly by the
scheduler, of exactly the class the SSRF-guard non-negotiable exists to prevent — the fix pattern already
exists in the same codebase and simply wasn't applied to this older, more heavily-used path.

### 4.9 The source-qualification → collection promotion frontier is still fully unbuilt

**Area:** catalog-sources-pipeline · **Files:** `src/catalog/qualification.py`, `src/scheduler/runner.py`, `src/api/source_management.py`

Re-verified fresh against today's tree rather than trusted from the 2026-09-06/07 inventory (which had
already flagged this as SRC-01/SRC-02): `select_unqualified` filters only on `Source.status ==
'unqualified'`, with **no `enabled` check** — so disabled candidates are trial-fetched exactly like
enabled ones. `evaluate_and_stamp` sets `status`/`qualified_at`/`criteria_version` but **never touches
`enabled`**. The scheduler's own collection query independently requires *both* `enabled=True` and
`status==qualified` — so a disabled candidate that earns a genuine "qualified" verdict from its Tor trial
fetch is discarded with **no path to ever collecting from it**; the operator would have to separately
notice and manually enable it. The unrelated `SourceCandidate` promote/dismiss model has the same shape of
gap on its own side (`promote_source_candidate` always creates `enabled=False`, with a comment
acknowledging "the operator's deliberate act stays required"). At the inventory's own count (~42,000
disabled candidates), this is ongoing, silent, unbounded Tor-routed network use whose positive verdicts
can never translate into value. **Confirmed at P1** — the skeptic traced the full caller chain and found
no `enabled=True` assignment anywhere in the promotion path.

### 4.10 A core (non-`[analysis]`) install silently loses working pure-Python API endpoints

**Area:** shared-utils-services · **Files:** `src/services/article_intelligence.py`, `src/api/_wiring.py`, `src/api/keyword_analysis.py`, `src/services/keyword_extractor.py`

`article_intelligence.py` hard-imports `numpy`/`scikit-learn` at module top level, even though most of its
methods never touch either. `keyword_analysis.py` imports it at its own top level, and `_wiring.py` wraps
*both* `keyword_analysis_router` and `keyword_management_router` in **one shared** `try/except
ImportError` block. Since numpy/sklearn are declared only under the optional `[analysis]` extra ("kept out
of core so the spine stays light"), a plain core install's `ImportError` on `article_intelligence.py`
propagates up and silently disables `keyword_management_router` too — whose own code (`keyword_extractor.py`,
`text_processor.py`) is **pure stdlib** and has no ML dependency at all. `/api/keywords/process`,
`/frequencies`, `/statistics`, `/extract`, `/categorize`, `/top`, `/phrases` all vanish on a core install
for a reason unrelated to their own code. **Confirmed at P1** — an avoidable, unrelated-dependency
coupling exactly opposite to the `[analysis]` split's stated purpose.

### 4.11 `list_sources`/`get_source` fully materialize and decrypt every article just to count them

**Area:** efficiency-performance · **Files:** `src/api/source_management.py`, `src/database/models.py`, `src/api/source_io.py`, `src/static/app-sources.js`

`GET /api/sources/` — the endpoint the Settings source-management UI actually calls, with `limit=1000`
and no server-side upper bound — computes `article_count` via `len(s.articles)`. `Source.articles` is a
plain lazy relationship (no `lazy="dynamic"`, unlike the `groups` relationship two lines below it in the
same model), so `len()` triggers a full `SELECT *` that materializes every `Article` ORM object for that
source — including the `content`/`compressed_content` columns, decrypted through SQLCipher — purely to
produce an integer, repeated for every source on the page. **The identical problem was already fixed** for
the sibling `GET /api/source_io/sources` via a maintained `Source.article_count` counter column
(migration `d2f8a9df7168`); `source_management.py` was never migrated onto it, and its own `/facets`
docstring even self-documents awareness of "the N+1 article/group loads `list_sources` does" without
fixing `list_sources` itself. **Confirmed at P1** — a real, uncapped, reachable performance bug on the
app's own primary settings surface for exactly the prolific-corpus scale this project is designed around.

## 5. Moderate findings (P2)

Twenty-five findings hold at P2 after verification (grouped by theme; two were downgrades from raw P1
candidates, noted inline).

### 5.1 Visual / i18n / GUI gallery

- **Inline `on*=` handler count and CSP `unsafe-inline` re-confirmed still accurate and unchanged**
  (592 vs. the inventory's ~590; `script-src 'self' 'unsafe-inline'` unchanged) — not new, but confirms
  UI-03/NET-04 has neither regressed nor been addressed.
- **The dead temporal-map cluster is confirmed still present, unchanged** — self-documented "UNREACHABLE
  dead code... left in place pending a browser-verified deletion cleanup" (`app-map.js:1680-1688`);
  independently confirmed zero live callers and no `#tmap-*` DOM targets remain.
- **The i18n coverage tooling is structurally blind to `src/static/guis/`** — the exact I-1 failure mode
  (2026-07-28) in a location the fix never covered. `i18n_report.py`'s module-discovery regex only matches
  `/static/(app...)\.js`; `boot.js`/`gallery.js` (loaded via identically-shaped `<script>` tags) and
  `ui-command.js`/`ui-canvas.js` (loaded dynamically, so not even reachable by a tag-scanning regex) are
  never scanned by `audit_chrome()`, `unkeyed_t_calls()`, or `test_i18n_audit_scope.py`. Today's strings
  there happen to already be fully translated (spot-checked), so this is a live blind spot, not a live
  regression — yet.
- **The gallery's Alpine-engine badge tooltip is untranslated in all 12 locales, including `en.json`**
  (`gallery.js:89-91`) — a direct, concrete symptom of the blind spot above; picked up by the universal
  hover-tip mechanism (invariant #17) but with no matching key anywhere, so it silently renders raw
  English in all 11 non-English locales forever. *(Originally rated P2, downgraded to P3 on verification —
  listed here for thematic grouping with its cause.)*
- **Two more `t9()` strings are unkeyed and untranslated everywhere**: the rate-toggle-knob toast
  confirmations ("Collection speed set to Maximum/500 KiB/s — applies from the next pass.") and the
  corpus chart's "Absolute"/"Indexed (=100)" scale labels — same root cause as §4.1.
- **`GET /api/wiki/dumps/probe` silently drops the just-ruled kill-switch reason** (invariant #14e, ruled
  the day before this audit): the sibling batch endpoint correctly returns a named `reason: "airplane"`;
  this older single-edition route discards everything but `size_bytes`, and a test pins the lossy
  behavior as intended. No current frontend caller — a regression-in-waiting, not yet user-visible.

### 5.2 Network / process-discipline

- **The regression tests for the fixed SOCKS/Tor P0 (§2) skip in every CI lane.** *(Originally rated P0 —
  see §4.2.)* PySocks is installed nowhere (not in `pyproject.toml`, no workflow installs it, and
  `docs/SECURITY.md` itself says "there is no packaged extra for it"), so `pytest.importorskip("socks")`
  silently skips the three tests that actually exercise `_guarded_socks_connect` in every environment
  that mirrors CI. **The runtime guarantee itself is unaffected today** (`airplane.py`'s own docstring
  frames PySocks-absent as "nothing to patch since no SOCKS proxying is even possible") — but a future
  refactor of the SOCKS-patching branch would get **zero red signal** from CI if it silently broke.
- **`docs/SECURITY.md`'s "for completeness, the full set of endpoints" list is not complete, and
  CLAUDE.md's absolute "the ONLY external service call" wording is false.** *(Originally rated P1,
  downgraded on verification.)* Both omit the real, live, airplane-gated IMAP/POP3 newsletter mailbox pull
  (`POST /api/newsletters/mailbox` → real `imaplib.IMAP4_SSL`/`poplib.POP3_SSL` connections to a
  user-configured, non-Tor-routed mail server). Mitigated by the fact that the channel *is* disclosed in
  its own endpoint docstring, the in-app UI, and README's feature list elsewhere — this is a completeness
  defect in a specific "exhaustive" claim, not an undisclosed or unguarded feature, but it sits in exactly
  the class of document (security posture, for at-risk journalists) where overclaiming completeness
  matters more than an ordinary doc bug.
- **CLAUDE.md's "the ONLY external service call is DuckDuckGo" non-negotiable is separately stale** given
  the shipped, scheduler-default-**on** USGS/GDACS hazard feeds and the click-gated Open-Meteo weather
  API — two more named, structured third-party API integrations analogous in kind to the one exception
  the non-negotiable names, with the hazards one being default-ON (the opposite of "off-by-default"). The
  underlying safety mechanisms (robots.txt, kill switch, airplane guard) are unaffected; this is a
  documentation/ledger-accuracy gap in the constitution's own stated purpose of preventing exactly this
  drift.

### 5.3 Database / API surface

- **`sqlcipher_export()`'s alias is f-string-interpolated into SQL with no escaping or `nosec`
  annotation**, unlike its sibling `_quote_key()` and two other files' documented-safe concatenations in
  the same codebase. *(Downgraded from P2 to P3 on verification — every current call site is a hardcoded
  literal, and bandit itself reports zero findings on the line.)* Listed here as a consistency gap worth
  closing before a future caller derives the alias from external input.
- **`PUT /api/sources/{id}` mass-assigns arbitrary attributes onto the ORM instance, including the primary
  key** — an untyped `dict` body forwarded via `**kwargs` into `if hasattr(source, key): setattr(...)`,
  with `id` includable. Tempered by the app's loopback-only, no-auth-by-design architecture (an attacker
  already has significant local access to reach this endpoint at all), but a real, reachable,
  zero-validation code-quality/robustness gap with no test guarding it.

### 5.4 Crypto / backup / custody

- **The zip-artifact extractor's containment check uses a string-prefix test the codebase itself names as
  unsafe elsewhere** (`str(target).startswith(str(root))` instead of `is_relative_to`, contradicted by an
  explicit docstring warning three files over). *(Downgraded to P3 on verification — the surrounding
  `..`/leading-`/` filters already fully close the traversal this specifically guards against in this call
  site.)* A real consistency/defense-in-depth gap, not a currently-exploitable bypass.
- **`src/crypto/provenance.py`/`signatures.py` are orphaned dead code, re-exported in a public `__all__`
  with a misleading "ensures legal admissibility" docstring**, while the app's actual, live
  admissibility mechanism (`src/custody/log.py`) is entirely separate. `signatures.py`'s `GPGSigner` has
  **zero** test coverage of any kind, not even isolated. *(A related, independent finding from the
  test-suite-health dimension additionally flagged `provenance.py` for opening a **plain, unencrypted**
  `sqlite3.connect()` — which would violate the at-rest-encryption non-negotiable if this dead code were
  ever wired into a live path; that finding was downgraded to P3 on verification since the module is
  completely unreachable today, but the encryption detail is worth carrying forward if the module is ever
  revived rather than deleted.)*

### 5.5 Analytics, verticals, mind-map

- **`story_lineage` can assert "traces earliest to X" with no date ordering at all** when every document
  in a near-duplicate cluster lacks `published_at` — `primary` becomes an arbitrary pick from an
  undated-only list, rendered with no caveat distinguishing it from a genuinely date-ordered result.
- **Timemap's hazard-empty-state message points users to a Settings control that does not exist**
  ("refresh it in Settings to see hazards here" — no such control anywhere; the snapshot is populated only
  by the scheduler's automatic pass or a direct API call).
- **GDACS parser defaults an unrecognized/missing alert level to `"info"` instead of an honest
  `"unknown"`**, inconsistent with the sibling USGS parser in the same file and the module's own
  documented "never guessed" ethos — a malformed/renamed provider field would silently downgrade what
  could be an orange/red alert to the lowest tier.
- **Mind-map "family"/"super-group" zoom levels can visibly cross-tangle**, unlike the keyword level —
  node position is assigned purely by weight-rank into rings, independently of which edge is later drawn
  by pure weight comparison, so a drawn edge can join geometrically distant nodes. A real, live, purely
  cosmetic violation of the app-wide "no cross-tangle" mind-map non-negotiable at the two deeper,
  secondary zoom levels.

### 5.6 Dependency security & supply chain

- **`cryptography==49.0.0` (pinned in `requirements.lock`) carries a live, currently-unaddressed CVE
  (PYSEC-2026-3552 — a PKCS7-decryption timing/length side-channel), fixed in 50.0.0.** [hand-verified,
  not raised by any of the 20 agents] Found via `pip-audit -r requirements.lock`. `grep -rn "pkcs7"
  src/` returns nothing, so the app's own code does not call the vulnerable functions directly;
  reachability through a transitive dependency's own PKCS7/S-MIME usage was not fully ruled out in the
  time available. CI's `pip-audit --skip-editable` step runs weekly against whatever is actually
  installed, not explicitly against `requirements.lock`'s pin — this may simply not have run again since
  the advisory was published, which is exactly the "freshly published CVE worth seeing" scenario that
  step's own code comment anticipates.
- **`requirements.lock`'s hash-pinned, audited versions are never actually installed by any real install
  path** — `install.sh` (both online and offline), `scripts/build_offline_bundle.sh`, all resolve from
  `pyproject.toml`'s loose `>=` floors against live PyPI/local wheels; CI's `lockfile-resolve` job only
  runs `--dry-run`. The lock file's supply-chain-integrity guarantee (reproducible, audited, hash-verified
  versions) provides no actual protection for a user running the shipped installer.
- **`offline-bundle.yml` interpolates a `workflow_dispatch` free-text input directly into shell via
  `${{ }}` templating**, a classic GitHub Actions script-injection pattern the same repo correctly avoids
  elsewhere (`release.yml` uses an `env:` variable). *(Rated P3 by its finder — listed here for topical
  grouping.)* Exploitation requires pre-existing repo write access (the ability to trigger the workflow),
  so it's a self-inflicted escalation path, not an external attack surface.

### 5.7 Ledger discipline & dead code

- **`docs/ledger/shipped.csv` carries 3 byte-for-byte identical duplicate row-pairs** (all dated
  2026-08-04, the trend-chart brush-selection feature) that do **not** fit the documented "brief vs. later
  PR-number" merge pattern the ledger's own L8 entry explains for the other 6 of its 9 known duplicate
  keys — a plain accidental double-append nobody has cleaned up, and not analyzed anywhere in the ledger's
  own duplicate-tracking prose.
- **The ledger's own twice-documented "duplicate-key scan over `shipped.csv`" recommendation has never
  been turned into a test**, unlike the parallel CLAUDE.md line-ratchet mechanized the same day for an
  analogous self-diagnosed risk. A recurrence would silently re-corrupt the shipped-work record with no
  grep or marker catching it.
- **CLAUDE.md's "Shipped batch log" section still states "125 entries as of 2026-06-25."** [hand-verified,
  not raised by any of the 20 agents] `shipped.csv` today has **858 rows** — a stale, trivially-fixable
  factual claim in the file's own summary of itself.
- **Six more `pyproject.toml` dependencies are orphaned exactly like the `structlog` case the maintainer
  fixed on 2026-09-07** with a dedicated regression test — `jinja2`, `pydantic-settings`, `tenacity`,
  `cachetools`, `orjson` (all core, downloaded on every install) and `networkx`/`python-gnupg` (declared
  optional extras with zero `src/` callers). None are covered by `test_dependency_hygiene.py`, which is
  scoped entirely to `structlog`.
- **`load_progress_state`/`_save_progress_state` (the atomic checkpoint read/write for resumable sweeps)
  is byte-for-byte copy-pasted, docstrings included, across three modules**, with a fourth
  (`narration_job.py`) carrying independently-added hardening (a `.mkdir()` and a `finally:
  tmp.unlink()`) the other three lack — a live, already-materialized example of the drift risk copy-paste
  invites, not a hypothetical one.
- **~450 lines of dead code** in `src/utils/cache.py` (`LRUCache`, `lru_cached`, and three named
  singletons implying they cache real corpus data — never imported anywhere outside their own tests) and
  `src/utils/compression.py` (`ChunkedCompressor`/`StreamingCompressor`, less tested than the cache dead
  code — not referenced even in their own test file).
- **`get_security_headers()`/`SECURITY_HEADERS` in `src/utils/security.py` are dead code, disjoint from
  and stale relative to the actual production headers** set independently in `src/api/main.py` — wiring
  the "helper" in later, as its docstring implies is intended, would actively regress (a stale
  `Referrer-Policy` value, deprecated `X-XSS-Protection`, a no-op `Strict-Transport-Security` over plain
  HTTP loopback).
- **`text_processor.process_text()` mislabels bigram/trigram keys as `"nngrams"`/`"nnngrams"`** — an
  `f"{'n'*n}grams"` typo, reachable via `GET /api/keywords/process`, contradicting the same function's own
  empty-input branch (which correctly promises `bigrams`/`trigrams`) and covered by zero tests.

### 5.8 Efficiency

- **`find_flooded_topics` issues up to 360 sequential per-source queries** (3 per source × up to 120
  candidates) on a documented "heaviest" (27–111s), uncached analytics path, where the sibling
  `find_buried_topics` in the same file already shows the batched, grouped-query alternative.
- **`find_buried_topics` re-derives an already-known list index via `list.index()`** per surfaced hit
  (up to 4,800-entry linear scans, discarding an index it already had for free from `enumerate()`), on the
  same uncached heavy path.
- **`backfill_corpus`'s sort column (`Article.keyword_indexed_at`) has no index**, and its candidate
  filter is a `NOT IN (DISTINCT ...)` anti-join against the corpus's largest table — reachable and
  re-executed roughly every 6 seconds while the Insights tab is open and a backlog exists (the exact
  PRH-01 large-backlog scenario), forcing an unindexed filesort every time.

## 6. Minor findings (P3)

Twenty-six findings, condensed (full evidence available in the finder agents' original transcripts if a
future session wants to act on any of these):

1. **~13 more sites carry the same unsafe `onclick`-interpolation shape as §3.1**, but every one traced
   concretely resolves to an app-generated (never scraped) value, so none is demonstrated exploitable
   today — still worth migrating to `data-*` + delegated listeners as the 0.0.9 audit's G2 item already
   recommended and was never done.
2. The **task-manager window has an undocumented fifth "Coverage" subtab** not in CLAUDE.md invariant
   #20's Active/Queue/System/Schedule roster, with no ledger trace of when it was added.
3. The **Command/Canvas GUI skins push invariant #19's "at-a-glance strip"** below their own injected Home
   content via `insertBefore(sec, home.firstChild)` — plausibly an accepted sandbox trade-off, but not
   called out as deliberate in either skin's own design rationale.
4. `boot.js`'s comments still describe a single "app.js" that hasn't existed since the 2026-08-20
   decomposition into 20 modules — comment-only drift, functionally harmless.
5. The Alpine-engine gallery badge tooltip is untranslated (§5.1's cause; the string itself, listed here
   for completeness).
6. Dead legacy locale keys `"▶ Online"`/`"⏸ Offline"` survive, untranslated, in all 12 locales from the
   pre-2026-06-12 toggle redesign — nothing renders them; pure locale-file inflation.
7. A stale code comment claims a packaged `[safety]` extra for PySocks that `docs/SECURITY.md` was
   already corrected to say doesn't exist.
8. Segmented (checksum-verified) dump downloads bypass PERF-09 rate measurement entirely — degrades
   honestly to "not measured," never fabricated; the feature is dormant/rarely configured.
9. `docs/plans/2026-09-06-repo-analysis/00_INDEX.md`'s top-level summary line for the 56-handler item
   wasn't updated alongside `INVENTORY.md`'s correctly-updated detail row — a stale rollup, not a stale
   fact.
10. `response_model=` is used in only 4 of ~55 `src/api` modules — consistent with the project's
    dict-first design, not itself a bug, but means response-shape drift is caught only by hand-written
    tests, not a schema contract.
11. The composite-score honesty guard's banned-name list doesn't include `"confidence"`/`"probability"`/
    `"likelihood"` — an unenforced gap in the mechanism, not a currently-exploited one (no producer uses
    those key names today).
12. `detect_coordination` can misattribute documents/hosts to an actor if `min_shared_stories > 1` is ever
    used — currently masked because production always calls it with the default value of 1.
13. `PARKED.md`'s `ConfidenceInterval.sample_size` (Haldane-Anscombe) open question is unchanged and
    accurately documented, but the affected methods (everything except `mean_ci`) are unreachable dead
    code today.
14. The blocking "zero mypy errors / no implicit Optional" gate is silently defeated for
    `pd.Series`-typed parameters, because `pandas` ships with no `py.typed` marker and the project's own
    `ignore_missing_imports = true` setting resolves it to `Any`.
15. The methods-appendix Markdown table escapes `|` in the title column but not the URL column — a URL
    containing a literal pipe would break table alignment in rendered Markdown (rare; data isn't lost).
16. `DOMAIN_ALIASES` carries a self-referential no-op entry for `washingtonpost.com` (maps to itself) —
    entirely inert, likely a leftover from a dropped intended alias.
17. `log_audit_trail()` in `logging_config.py` is unused dead code that could silently create files under
    `repo-root/audit/` if anyone starts calling it without review — the same shape of unused audit-log
    machinery CLAUDE.md already records removing once elsewhere (OO-D5-002).
18. `USER_MANUAL.md`'s seed-catalog domain count has drifted ~7% low (states ~3,180; actual union is
    3,395) — README's separate "~3,400" figure is accurate by comparison; the same recurring class of
    drift `docs/HISTORY.md` already records once before (F-007).
19. `src/api/diagnostics.py` (already tracked, STR-01/ROADMAP S-1, maintainer-answered "yes, split it" but
    "NOT attempted") **grew again the very next day** after being flagged as deferred-and-growing (6,291→
    6,312 lines, 128→129 routes) — confirming the ROADMAP's own "grew while recorded as deferred"
    observation is an ongoing trend.
20. A leftover, self-aware commented-out network-calling demo block sits in a `src/` library module's
    `__main__` block (`source_manager.py`) rather than a script/example file — harmless, never executed.
21. `sqlcipher_export()`'s unescaped f-string interpolation (§5.3's downgrade, listed here for the record).
22. The zip-artifact extractor's string-prefix containment check (§5.4's downgrade, listed here for the
    record).
23. `DuckDuckGoSearch.discover_rss_feeds`'s "Method 2" (RSS_PATTERNS regex scan) is a **silent no-op** —
    none of its 14 regexes has a capturing group, so `if "http" in match` can never be true; masked
    because Methods 1 and 3 still work.
24. `ArticleIntelligenceAnalyzer.group_by_similarity`/`extract_terms_with_metadata` are unreachable dead
    code implementing an O(n²)-plus clustering pass that has never run against real data.
25. `src/crypto/provenance.py`'s only exerciser test uses a nonstandard bare `import crypto.provenance`
    (via a manual `sys.path` hack) rather than the project's `from src.X import Y` convention — real, but
    the specific "this uniquely marks it as noticed-and-orphaned" inference in the original finding was
    itself refuted by the skeptic (the same pattern exists in 8 other, mostly-live test files).
26. GitHub Actions `offline-bundle.yml`'s script-injection pattern (§5.6, listed here for the record).

*(One raw P2 candidate — a claim that the ledger's "add a test for the shipped.csv `PR pending` sweep"
recommendation was an unaddressed process lapse — was independently investigated by its skeptic and
**refuted**: the source text the claimant quoted is immediately followed, within the same cited line
range, by "Not taken unilaterally: it changes the sequence every session follows," making this a
correctly-recorded pending-maintainer-ruling, exactly as CLAUDE.md's own protocol rule (2) requires, not a
lapse. Excluded from the counts above.)*

## 7. Positive findings — what's working well

The audit surfaced 32 positive findings; the load-bearing ones, by area:

- **The Observatory** (`oosky.js`/`app-observatory.js`) faithfully implements all five of invariant #31's
  non-negotiable rules in the actual code, not just the comments — including the two refusal behaviors
  (log-scale below a full decade, zero-value outer band) and deterministic, `Math.random`-free geometry.
- **Core UI invariants #1, #3, #4, #5, #14/#14e, #15, #16, #18, #19, #21, #23** were each spot-verified
  against live implementation, not names or comments, and hold as documented — including confirmation that
  the previously-recorded #14e dump-size-read consent-gate fix has actually landed (`app-map.js:1814`).
- **The 8-skin GUI gallery's scoping, caveat/consent preservation, and no-inline-handler discipline are
  genuinely clean**, verified independently rather than trusted from the existing test file; the vendored
  Alpine.js checksum matches exactly, and the two Alpine skins automatically pick up new nav tabs (e.g.
  Observatory) with zero code changes, a real instance of the "reuses the core" design claim holding up.
- **Locale key parity is exact — 3,134/3,134 — across all 12 languages**, with no lazy/machine-translated
  leftover English found by a targeted heuristic sweep, and the Observatory's newest strings are genuinely,
  distinctly translated in every sampled language.
- **The prior audit's P0 (SOCKS/Tor bypass) is fixed and further hardened** with an independent second
  gate (§2); the gated DuckDuckGo discovery channel is correctly routed through the one guarded session.
- **PERF-09's per-job rate/ETA measurement is genuinely honest and correctly wired on both download
  managers** — absence over fabrication, correct reset-on-resume, no persisted-across-restart state.
- **The 56-async-handler-on-the-event-loop item is genuinely fixed**, not merely claimed fixed: an
  independent AST scan found the real current count is 4, each off the event loop by design, with a real
  regression guard (`test_handlers_off_the_event_loop.py`) closing the exact evasion the original
  inventory worried about.
- **The Alembic migration chain is a single, clean, linear history** (58 revisions, one root, one head,
  zero duplicates or mismatches), with real `alembic check`-based drift enforcement and a carefully-reasoned
  "safe-advance floor" for data-only migrations.
- **No composite/blended trust or quality score was found anywhere in the API surface examined** — the
  one score-shaped field (`reliability_score`) is explicitly operator-set, never computed, and documented
  as a deliberate exemption; a real near-miss (an emotion category literally named "trust") was already
  caught by the mechanical banned-key scanner and fixed in-line, evidence the enforcement is not decorative.
- **The B6 who/where/when gating bug (prior audit's P0) is genuinely fixed**, with a real end-to-end
  regression test using the actual harness envelope rather than a hand-typed mock.
- **The local-only-LLM claim holds structurally**: zero direct `httpx`/`requests` imports anywhere in
  `src/ai_layer`, `src/briefing`, or `src/personality`; every LLM call funnels through `OllamaClient`/
  `VllmClient`, both of which enforce loopback-only construction and a kill-switch check on every network
  method, with `clearnet=True` correctly and honestly disclosed for the two methods (`pull`/`remove`) that
  necessarily reach the separate Ollama process's own clearnet path.
- **The markets/commodity/hazards vertical code is exceptionally rigorous** — extraction, unit conversion,
  and correlation code refuse to fabricate at every checked site, and the ~110-source markets catalog is
  genuinely seeded, not a stub.
- **The Wikipedia dump reader is genuinely tested end-to-end** against a real multi-stream bz2 fixture at
  real byte offsets, not a mock.
- **Bulletin completion (D1–D4) is real, correctly implemented, and matches its shipped-log claim** —
  resumable narration as a genuine `BackgroundJob`, tri-state export-privacy accounting, per-card period
  measurement.
- **Annotations, evidence-bundle signing, and fixity/metadata verification are all clean and correctly
  wired end-to-end**, with no dead code, no bare excepts swallowing failures, and zero TODOs in scope.
- **The external-artifact registry discipline holds**, and `link_preview.py` correctly implements the
  local-only preview invariant, reusing the same URL normalizer at ingest and preview time so citation
  counts cannot drift.
- **A broad set of the most safety-sensitive documentation claims verified accurate** against current
  code — hybrid PQC custody signing, the GitHub-attested Ollama installer checksum, the genuinely-removed
  destructive restore endpoint, honest per-job rate/ETA, the CSV importer's error accounting — with no
  broken internal documentation cross-links found anywhere.
- **The CLAUDE.md size ratchet and conflict-marker hygiene currently hold at zero slack** [hand-verified]:
  616/616 lines exactly, no unresolved conflict markers in any of the 8 scoped ledger files, and zero
  literal `"PR pending"` placeholders remaining in `shipped.csv`.
- **Zero import/module drift between the 851 test files and current `src/`** — an AST-based check of
  every import statement (5,618 from-imports) found zero cases of a test referencing a module path or
  name that no longer exists.
- **The three named safety-regression test files are substantive, real end-to-end drivers**, not stubs —
  they drive the actual production socket-patching code, a real threaded loopback server simulating
  DNS-rebinding, and include explicit anti-vacuity assertions proving the *connect-time* gate (not just
  the pre-fetch gate) is what's actually under test.
- **The TODO/FIXME/XXX/HACK sweep of all of `src/` is genuinely clean** — exactly two hits in ~196k lines,
  both false positives (test fixture bytes and a comment explicitly denying it's a TODO) — real evidence
  the ledger-first discipline (pending work lives in `OPEN_QUEUE.md`, not code comments) is actually
  followed, not just stated.
- **Heavy analytics reads are protected by a well-built three-layer defense** (TTL cache + single-flight
  concurrency cap + statement deadline) directly targeting the documented 2026-07-08 "poll pile-up death
  spiral," consistently reused across the manipulation-detection endpoints.

## 8. Measured facts (info)

Sixteen findings recorded real numbers or confirmed/updated a specific ledger claim, without themselves
being defects:

- `src/static/app.js` no longer exists as one file — decomposed into 20 ordered modules
  (2026-08-20); this audit's coverage treated them collectively, matching the test suite's own convention.
- Single-fetch-path / no-new-socket-importer claim re-verified true: still exactly 4 allowlisted modules
  import `requests`/`httpx` directly.
- `field_test.py` is genuinely single-call-site, env-gated, never auto-enabled.
- `PARKED.md`'s 490/490/9 model-column count is stale but the underlying invariant still holds exactly:
  495/495/9 today (normal growth since 2026-08-20), with all 9 `Column()` calls still confined to the two
  `Table()` association constructs.
- Loopback binding is a documented default with a warning, not a hard-enforced bind-layer guarantee — the
  real enforcement is the separate Host-header/CORS/CSRF middleware stack, independently confirmed present
  and correctly wired.
- The DuckDB crypto-extension floor/pyproject coupling claim is accurate and genuinely test-enforced.
- **The newer `src/signals`/`src/stats` statistical primitive layer is markedly higher quality than the
  legacy `src/analysis` module** — every primitive hand-checked in the former was mathematically correct;
  the one confirmed defect (§4.6) lives specifically in the latter.
- Hazards ingestion, the local snapshot cache, and the elections coverage-floor math were read in full and
  found free of fabrication or honesty-convention violations.
- **PRH-05 (the location-extractor's O(patterns×text) scan) is already fixed** (commit `1b3ff01`,
  2026-09-07) — the 2026-09-06 inventory's "UNBUILT" status for this item is one day stale.
- The law vertical's structured (CLML/XML) adapter half is real but has **zero integration into the live
  tracking pipeline** — confirmed accurate against the ledger's own LAW-01/02 characterization, plus one
  additional, previously-undocumented fully-dead module (`adapters/diff.py`) referenced from nowhere,
  not even the adapter's own self-test.
- LAW-08's "39 figures across 32 countries" denominator claim is numerically exact.
- `shipped.csv`'s duplicate-key count (9) matches the historical baseline `LESSONS.md` already cites as
  correct to compare against — this audit's only new information is that 3 of those 9 are full-row
  duplicates rather than the documented brief/PR-number pattern (§5.7).
- **Test-suite scale**: 514 `src/*.py` files vs. 843 `test_*.py` files (~1.64:1), ~201k lines of test code
  against ~196k lines of source; all 851 test files compile cleanly; the blocking correctness lint lane
  passes at zero findings; 155 conditional skips (all genuinely gated on optional extras/platform, none
  unexplained); zero `xfail` markers anywhere.
- No hardcoded secrets found anywhere in `src/`, `configs/`, or `.env.example`.
- `src/backup/merge.py` (5,669 lines) and `src/llm/vllm_lifecycle.py` (3,908 lines) — the two largest files
  after `diagnostics.py` — reflect genuinely large domains (per-table merge handlers; one process's full
  lifecycle), not unmanaged sprawl, unlike `diagnostics.py` (§6.19).
- Near-duplicate detection genuinely uses LSH/MinHash banding, not brute-force O(n²) comparison, with
  every call site bounding its input pool.

**Additional facts from this session's own direct tool runs** [hand-verified, not raised by the
20-agent workflow]:

- `mypy src/` (the correctly-pinned `2.3.1`, run under Python 3.13): **0 errors across 514 source files.**
- `ruff check src/ tests/` (the correctly-pinned `0.16.6`): **450 findings**, exactly matching the
  CI ratchet's ceiling — zero slack.
- Both i18n ratchets (`--max-untranslatable`, `--max-unkeyed-t-calls`) sit at **exactly** 554 and 295 —
  zero slack on either.
- `bandit -r src/` (the CI-pinned `1.9.4`): **0 medium/high-severity findings**; 191 low-severity, of
  which the 5 `B105` ("hardcoded password string") hits were all spot-checked and confirmed **false
  positives** (a separator constant, cache-token dict keys, a variable-name-only match on
  `_passphrase = ""` — which is itself the *correct* security practice of clearing a key after use, not a
  hardcoded secret); the 133 `B110` (try/except/pass) hits cluster heavily in `src/backup/merge.py`
  (5,669 lines — the codebase's second-largest file) and were spot-checked as benign best-effort
  diagnostic/telemetry guards, not swallowed real errors.
- `pip-audit -r requirements.lock`: **1 finding** — `cryptography==49.0.0` / PYSEC-2026-3552 (§5.6); this
  is a genuinely new result this session's own tool run produced that no dimension agent's search surfaced.
- CLAUDE.md's own line-ratchet: **exactly** 616/616 — zero slack, matching §7's positive finding.

## 9. What this audit did not cover

Per the project's own methodology convention, named here rather than silently omitted: no live browser
session was launched (all visual/i18n findings are static-source-level); the two 09-audit items not
re-examined this session (§2, rollback bug and Tor-RESOLVE mismatch) were simply outside this session's 20
dimension scopes, not re-verified either way; the full `pytest` suite was not executed (Python-version and
dependency-installation constraints in this sandbox — `mypy`/`ruff`/`bandit`/`pip-audit` were run for real,
but the actual behavioral test suite was not); and the `cryptography` CVE's reachability through any
transitive dependency's own PKCS7/S-MIME code path was not fully traced beyond confirming the app's own
`src/` code never calls the vulnerable functions directly.

---
**Verification stamp:** static/source-level audit, 68 agents (20 finders + 48 adversarial skeptics) plus
independent hand-verified tool runs by the orchestrating session; no live browser session; no fixes
applied (report-only, per the commissioning instruction).
