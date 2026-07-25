# 09 — Transversal audit, 0.3 delta edition (2026-07-25)

> Commissioned as a general "full transversal / functional / bug-bounty / documentation-claims-vs-code-reality
> audit." Per this project's own C8 discipline ("re-audit delta for the next cycle... check this document's own
> C1-C7 against the ledger before writing edition 09, rather than re-deriving from first principles"), this is
> **not a from-scratch re-derivation** of [`07_TRANSVERSAL_AUDIT_V01.md`](07_TRANSVERSAL_AUDIT_V01.md) (2026-06-12)
> or [`08_TRANSVERSAL_AUDIT_0.3.md`](08_TRANSVERSAL_AUDIT_0.3.md) (2026-07-21) — it is scoped as the "edition 09"
> those documents anticipated: (a) disposition of 08's own Action Plan C (C1-C8), (b) a fresh disposition pass on
> [`GUI_TEST_REPORT_2026-07-22.md`](GUI_TEST_REPORT_2026-07-22.md)'s 5 P0 + a P1 sample, (c) an independent
> transversal audit of every surface shipped **since** those two documents (2026-07-21 → 2026-07-25 — the LLM/vLLM
> stack, the throughput-scaling brief, and the 2026-07-20 source-management program named in the 0.3 close gate's
> own row 1), and (d) a genuine bug-bounty pass (static security sweep + a live adversarial attempt to defeat the
> airplane-mode socket guard) — the parts of the commissioning brief 07/08 did not cover, since neither was written
> as a security audit.

## 0. Methodology & honest scope

A 23-agent orchestrated workflow (10 generation agents across three phases + 13 independent adversarial skeptic
re-verifications of every candidate defect the generation agents surfaced) ran against the live `origin/main` tip
(`2aa8dc3`, fetched fresh at session start). 786 tool calls, ~9M tokens, ~66 minutes wall-clock. Every finding below
that carries a severity passed through a **skeptic agent with no access to the original claimant's reasoning**,
instructed to default to refutation and re-derive the evidence itself — 12 of 13 candidate defects survived as
real (one refuted, §10.6). Beyond that in-workflow skeptic layer, I (the orchestrating session) additionally
**hand-verified the single most consequential finding myself** — the airplane-mode SOCKS/Tor bypass (§2) — by
installing the real PySocks library and reading its actual `socksocket.connect()` source against the actual
`src/ingest/airplane.py` guard code, before trusting it enough to write into this document.

**What this is not:** not a live penetration test (no running server instance was attacked — this sandbox has no
running app to point Burp/ZAP/Nuclei at, and the brief's dynamic-testing tooling list assumes one); not an
exhaustive re-run of 07/08's own tool-by-tool ethics tables (§1 there is far broader than security/functional
correctness, and re-deriving all 17 rows from scratch was judged lower value than the delta + security work this
edition adds); not a fuzzing/dependency-graph-wide audit (bandit + pip-audit + targeted manual review, not
AFL/Semgrep/Checkmarx, which are unavailable in this sandbox).

## 1. Executive summary — top findings

| # | Severity | Finding | One-line impact |
|---|---|---|---|
| 1 | **P0** | The airplane-mode **socket-level backstop is fully blind to the real destination host** when a SOCKS proxy (Tor — the app's own recommended "protected mode" transport) is configured. Live-reproduced. | The guard's own claim ("no packet can reach the network, whatever the code path") is false for exactly the transport at-risk users are told to use. Not actively leaking in shipped code today (every known entry point checks the kill switch first) — but the last line of defense provides zero protection for proxied traffic. |
| 2 | **P0** | The brand-new (2026-07-24) **B6 eval-gated who/where/when LLM extraction is completely non-functional**: `gate_languages_from_report()` reads the wrong nesting level of its own input, so every language is permanently gated "never evaluated" no matter how many times the eval harness runs or how clean its results are. | A shipped, user-facing feature silently does nothing, forever, with no error anywhere. |
| 3 | **P1** | A **path-traversal-via-symlink** bug in the folder-backup **restore** path (`restore_folder_backup`) — the sibling `verify_folder_backup` function correctly guards the identical untrusted-input threat model; the write path does not. Live-reproduced. | A hostile/compromised backup source (e.g. a shared external drive) can have an arbitrary locally-readable file's content silently copied into the live app data directory. |
| 4 | **P1** | The committed, CI-validated `requirements.lock` pins **Pillow 12.2.0**, with real vulnerabilities fixed in 12.3.0, reachable via `POST /api/verify/image-metadata` — a journalist-facing "analyze this suspicious image" endpoint that feeds fully untrusted bytes straight to `Image.open()+.load()`. | Real, but narrower than first read: only 2 of 13 distinct CVEs are actually reachable through this app's exact (narrow) Pillow usage, both DoS-class, not memory-corruption. |
| 5 | **P1** | A missing `session.rollback()` in the new archive-backfill and housekeeping-lane loops (throughput brief C1/C2/C15) lets one dirty-session DB exception **cascade into silently, permanently marking unrelated URLs/ride-alongs as "failed"** even though they were never actually attempted — the exact bug class ("mid-batch handler discards sibling work") this project has independently rediscovered and fixed multiple times before. | Silent, non-transient loss of archive-backfill coverage and false "housekeeping lane failed" logs. |
| 6 | **P1** | The **Tor-exit-resolve (SOCKS RESOLVE) path is design-only**, not implemented, despite the 0.3 close-gate's own row 1 explicitly listing it as a required, already-"implemented" component. Downgraded to P2 by the skeptic pass (a self-consistency/gate-documentation defect, not a functional one — nothing in the running app is broken). | The gate's own checklist would over-report readiness if closed without reconciling this. |
| 7 | **P1** | The **USER_MANUAL has zero mentions of "qualification" anywhere**, even though `Source.status` now gates whether a source is ever scraped at all — despite the 0.3 close-gate's own row 1 explicitly requiring this docs↔app reciprocity. | A user has no way to learn, from the manual, why a newly-added source sits unscraped for up to ~6 months under the re-qualification backoff ladder. |
| 8 | positive | **All 5 P0 findings from the 2026-07-22 GUI test report are now fixed** on current `main`, across 4 distinct fix commits (`506a22b`, `8b74c8e`, `f534938`, `19f68eb`). Independently re-verified by reading the current source, not by trusting the test report or any pinning test's own assertions. | The flagship-UI blockers found by the 100-agent GUI test are closed. |
| 9 | positive | The **airplane-mode zero-egress guarantee holds for every direct (non-proxied) code path** — stdlib sockets, asyncio, TLS, the mailbox protocols, no stray DNS libraries, no raw `urllib.request`. This is the *non*-proxied half of finding #1; only the proxied/Tor half is defeated. | The core safety mechanism is sound outside the one gap named above. |

Full detail for every item, including several lower-severity/info findings not in this table, follows below.

## 2. Headline finding — airplane-mode socket guard is blind to proxied (SOCKS/Tor) traffic

`src/ingest/airplane.py`'s `install_airplane_socket_guard()` patches exactly four functions —
`socket.getaddrinfo`, `socket.create_connection`, `socket.socket.connect`, `socket.socket.connect_ex` — and its
own module docstring states the resulting guarantee in absolute terms: *"with airplane mode engaged, no packet
can reach the network from this process, whatever the code path."*

That claim is false for the app's own documented, recommended "protected mode" transport (a SOCKS proxy — Tor at
`socks5h://127.0.0.1:9050`, per `src/safety/settings.py`/`docs/SECURITY.md`, including the brand-new 2026-07-24
operator SOCKS-proxy-pool feature). **Hand-verified directly against the real PySocks source** (installed and
read this session, not taken from the workflow's own claim):

```python
# PySocks socks.py, socksocket.connect() — the real installed library
super(socksocket, self).connect(proxy_addr)   # loopback → the guard correctly allows this
...
negotiate(self, dest_addr, dest_port)          # the REAL destination, sent via sendall()/recv()
                                                 # at the SOCKS application-protocol layer —
                                                 # NEVER through socket.socket.connect() again
```

`urllib3.contrib.socks.SOCKSConnection._new_conn()` — the exact class `requests` instantiates whenever a
`socks*://` proxy is configured — calls precisely this path (`socks.create_connection()` →
`socksocket.connect()`). So `install_airplane_socket_guard()`'s four patched functions see the connection to the
**proxy** (loopback, correctly allowed) and never see the **real destination** at all — it is negotiated at an
application-protocol layer the socket-level guard cannot observe.

**Live reproduction** (in the original 23-agent workflow, using a local non-forwarding stub SOCKS5 server): with
the real guard installed and the real kill switch engaged, a real PySocks connection to a real external IP
(`93.184.216.34:80`) completed successfully with **zero** `AirplaneModeError`; the guard's own internal check was
invoked only with `'127.0.0.1'`; the stub server decoded a genuine SOCKS `CONNECT` request naming the real
external host — exactly what a live Tor daemon would receive and relay onto the real internet.

**Honest caveat, verified by hand:** this is *not* demonstrated as an actively-exploitable leak in shipped code
today. Every known entry point that could reach a proxy-capable session checks `kill_switch_active()` as
literally its first action, *before* any proxy/session use — confirmed by direct grep: `src/ingest/__init__.py:620`
(`EthicalFetcher.fetch()`), `src/ingest/__init__.py:502` (`declared_sitemaps()`), `src/safety/fetcher.py:59`
(`GuardedSession.request()`). So the app-level per-call convention (the "friendly, explanatory layer" the guard's
own docstring says it sits *beneath*) currently covers every real code path.

What this finding actually falsifies is the guard's own claim to be *unconditional* backstop, "whatever the code
path." A future code path, refactor, or third-party dependency that constructs and uses a proxy-configured
session **without** first checking the kill switch — the exact scenario the socket-level guard exists to catch,
per its own docstring ("a per-call convention is only as airtight as our memory") — would leak real traffic to
the real internet while the operator believes airplane mode makes that structurally impossible. This is precisely
the population (at-risk journalists using Tor) the guarantee is built to protect most, and the guard provides
**zero** defense-in-depth for them specifically. `tests/test_airplane_socket_guard.py` (6 tests) exercises only
direct, unproxied socket calls and does not cover this case.

**Recommended fix shape** (not built this session, per this project's report-first-for-audits convention, §13):
the guard cannot patch PySocks generically (a third-party library, version-fragile). The more robust fix is at
the point of proxy construction: gate `EthicalFetcher`/`GuardedSession`'s session-building code so that
constructing a proxy-configured `requests.Session` itself checks `kill_switch_active()` and raises before the
session object is ever returned — closing the gap architecturally rather than per-call. A secondary, cheaper
mitigation: extend `tests/test_airplane_socket_guard.py` with a SOCKS-proxy-path regression test (using the same
local-stub-server technique) so this specific defeat is pinned and any future fix is provably closed.

## 3. Headline finding — B6 who/where/when extraction gate is completely inert

`src/ai_layer/perception_extract.py::gate_languages_from_report()` — the mechanism that is supposed to enforce
this project's standing "LLM perception must pass the eval harness before extraction runs" ruling — reads
`(report or {}).get("by_language")` at the **top level** of whatever it is handed. But the real, persisted
artifact this function is actually fed (`last_perception_eval_live_report()`, `src/ai_layer/perception_job.py`)
nests the harness output one level deeper, under a `"report"` key, alongside `status`/`model`/`backend`/
`prompt_version`/`schema`/`run_at`. `by_language` therefore only ever exists at `artifact["report"]["by_language"]`
— never at the top level `gate_languages_from_report()` actually reads.

Both real production call sites feed it the full enveloped artifact, not the unwrapped harness dict:
`run_progressive_perception_extract_job` (`perception_extract_job.py:136-140`) and `current_language_gate()`
(`perception_extract_job.py:361-368`, backing `GET /api/diagnostics/perception-extract/gate`). The result:
`gate_languages_from_report()` always returns `{}`, and `language_gate("en", gate)` always returns
`(False, "never evaluated")` — for every language, regardless of how the harness actually scored it.

Live-reproduced end-to-end using the real production functions (no mocks): a clean, hallucination-free English
harness run, persisted and re-read through the real path, still yields an empty gate. Reading the SAME artifact's
`["report"]["by_language"]` (the correct nesting) shows all 13 evaluated languages present and populated — the
bug is exactly and only the missing one-level unwrap. Every unit test of `gate_languages_from_report()` constructs
its mock report as `{"by_language": {...}}` directly at the top level — the shape the bug expects, not the shape
`last_perception_eval_live_report()` actually produces — which is why this shipped fully green.

**Impact:** an operator can run `POST /api/diagnostics/perception-eval-live` (get a clean report), then
`POST /api/diagnostics/perception-extract/run` (the actual extraction toggle) — the sweep walks the entire
corpus, reports every article "gated / never evaluated," extracts nothing, and the job reports `done`/
`complete: true` with zero errors. The `/perception-extract/gate` UI panel likewise always reads "no active
languages" immediately after a harness run that just reported real gold-case scores. There is no error, exception,
or log line anywhere pointing at the cause — this is a shipped, user-facing feature that silently does nothing,
permanently, no matter how many times its own gating mechanism is (correctly) exercised.

**Fail-safe note:** the bug fails in the *safe* direction — it gates too much (extracts nothing) rather than too
little (extracting ungated garbage into the AI layer). No fabrication risk exists; this is a completely-broken
feature, not a data-integrity issue. It is rated P0 because it defeats the *entire point* of the eval-gating
ruling this project explicitly requires before any LLM extraction ships, not because it risks bad data.

## 4. Disposition of 08's Action Plan C (C1-C8)

| Item | 08's ask | Status this session | Note |
|---|---|---|---|
| C1 | Close out the B1 disclosure sweep (LLM-artifact label, "record begins" stamp, Wikipedia-bias note, VADER-EN reach) | **Mostly already shipped, and mostly already shipped *before 08 was even drafted*.** The "AI-derived · unreliable" label, the manual's "record begins" and "Wikipedia carries its own systemic biases" paragraphs all pre-date 08's own authoring commit by 3+ days (PR #705, 2026-07-18). The one genuinely new-since-08 piece is the *runtime* `recording_began_at` stamp on snapshot metrics (shipped 2026-07-23). VADER-EN disclosure is extensive across reader.js, the competitive panel, tone chips, Home cards. | 08's own §7/§9 text incorrectly claimed "no evidence found" for two of these sub-items — see §11 below (info-level correction to 08 itself). |
| C2 | Fold the local fixity audit into the all-diagnostics bundle | **Still open** — `audit_fixity`/`GET /api/integrity/fixity` are real, correct, and have a UI button, but zero references to "fixity" exist in `src/api/diagnostics.py`. **Compounding structural finding:** the completeness ratchet meant to prevent exactly this (`test_all_diagnostics_bundle_covers_every_get_diagnostic` + its runtime twin) only scans `src/api/diagnostics.py` itself — it is structurally blind to the sibling `src/api/integrity.py` router (4 routes, incl. `/fixity`), so the bundle can report itself "complete" while an entire diagnostic router is invisible to both coverage and the documented exclusion list. Confirmed real by skeptic re-verification, severity corrected P1→P2 (a completeness/honesty-mechanism gap, not a functional break — fixity is independently reachable via its own button). |
| C3 | Surface the segmentation capability matrix in-app | **Still open**, exactly as 08 described. `language_status()`/`keyword_engine_report`'s per-language functional/unsegmented/no_stoplist data exists and rides the all-diagnostics bundle, but no in-app panel renders it; the one adjacent UI element (unmanaged-language disabling) is scoped to a different question. |
| C4 | Extend `perf_harness.py` toward the 5M-article gate with 100k/1M checkpoints | **08's own framing was stale.** `scripts/perf_harness.py` was in fact extended in direct response to audit-07's B3 — five weeks *before* 08 was drafted (2026-06-15, a documented "100k SCALE PROFILE" command + new endpoint timings, all commented "audit-07 B3" in the file itself). The *substantive* gap 08 is chasing is still real, though: defaults are unchanged, no 1M value/`--checkpoint` flag exists, and no larger-than-6.4k run has ever produced a committed result artifact. Separately: the DB-10 pagesize-bench (a *different* tool) HAS since run at real 474,556-article/22.2 GB scale, and the resulting `page_size=16384`+`auto_vacuum=INCREMENTAL` pragma seam has fully shipped (`src/database/connect.py`) — 08's "still pending a large-corpus run" framing for that item was already stale when written; its own sibling `RELEASE_0.3_GATE.md`, drafted the same day, got this right. |
| C5 | Name "conservative-default bias" as a taxonomy addition in the next edition | Confirmed not-yet-added anywhere outside 08 itself — expected, since 08 explicitly proposed it for edition 09 (this document). **Recorded here per the ask** (see §4a below). |
| C6 | Get a general maintainer ruling on "reviewed by eye" as an acceptable evidentiary bar for future default-on display-layer changes | **Still open.** The maintainer *did* rule on the specific lemmatization instance (2026-07-18, predating 08), but no general policy precedent exists anywhere in the repo. |
| C7 | Build "Your lens" v1 (plural-baseline representation + single-origin + wire-dependence share) | **Still genuinely unbuilt** — only design-doc aspirational references exist. The underlying computational substrate has grown since 08 (`reading_diet_by_type`, `laundering.py`, `convergence.py`, `source_trail.py`, `skeleton.py`) but nothing unifies them behind a dashboard. |
| C8 | Re-audit delta discipline for edition 09 | This document. |

### 4a. Conservative-default bias — added to the taxonomy (per C5)

08's §8.1 proposed naming a bias pattern discovered in the law vertical's S2 fix: a safety-motivated default
(`flagged_only=True` on a large-change heuristic tuned for other document types) silently **hid true signal**
rather than fabricating false signal — a routine, real law change read as "the tracker looks broken" purely
because a conservative default suppressed it. **This edition confirms and records the addition:** "conservative-
default bias" is a distinct failure mode from every other item in 08's §6 taxonomy — those describe biases that
*over-claim* (recency, popularity, permissive-host survivorship); this one *under-claims*. Recommended standing
check for future audits: any heuristic default that suppresses/flags/hides output by default (rate limits,
change-detection thresholds, admission gates) should be spot-checked for whether it silently swallows a routine,
correct signal rather than merely gating a genuinely risky one. No new instance of this pattern was found this
session beyond the one 08 already named.

## 5. GUI test report (2026-07-22) — disposition (the good news first)

**All 5 P0 findings are now fixed on current `main`.** Each was independently re-verified by reading the actual
current source — not by trusting the report or any pinning test's own assertions — with a throwaway script
hand-executing the same string checks the repo-invariant tests use, against the live files:

| P0 | Status | Fix commit |
|---|---|---|
| Reader "Related in your corpus" + dup-badge queried the dead `article_keyword_association` table | Fixed — now reads `KeywordMention` | `506a22b` |
| `#net-coach` coachmark pointer-blocked the airplane toggle/lang-switch/task-manager/shutdown buttons | Fixed — coach now places itself below a union bounding rect over all four protected buttons | `8b74c8e` |
| A rejected first-launch passphrase left the whole form hidden (blank white screen) | Fixed — the catch handler now re-shows the correct prior view | `19f68eb` |
| 375px width pushed 4 top-bar controls off-screen with no overflow affordance | Fixed — `.topbar` now `flex-wrap: wrap` | `8b74c8e` |
| The text-size slider had no accessible label | Fixed — `<label for="dr-font">` now wraps it | `f534938` |

**P1/P2 sample — mixed:**

- **`theme-select` lossy overwrite (was P1)** — **now fixed** (`de4b32d`): `saveSettings()` now guards the
  destructive theme re-apply, so saving unrelated Settings no longer collapses a named theme (e.g. Midnight) to
  Ink unless the user actually changed the theme select.
- **`llm-triage-airplane-mode-off-required` (was P2, "mixed signal")** — the **functional** gate was fixed
  `ceeb718` (2026-07-21), which actually *predates* the GUI report's own test-run commit by ~32h — so the report's
  own "live symptom does not reproduce" sub-observation was already correct at test time. But the **residual UX
  copy is still broken today**: `src/static/app.js:13076`, `4918`, `17941-17943` and `src/api/ai.py:246-251,554`
  all still tell the user airplane mode can cause local-AI unavailability for paths that are now loopback-safe —
  including a comment inside code shipped by the *same* 2026-07-24 session CLAUDE.md credits with resolving this
  item. Real, currently-reproducible, still P2 (copy-only, no functional block — no `ensureOnline()` gate wraps
  any generate/translate/summarize call).
- **Governments/law tab still defaults to Countries, not Law** — confirmed **still broken** (P2, per the
  report's own rating; standing known-open item, independently rediscovered by 4 test groups in the original run).
  `src/static/app.js:4033-4039`: `ooSubtabs(nav, showGovView, {initial: "countries"})` is hardcoded.
- **Home boot fires duplicate `/api/database/stats` (×3-4) and `/api/scheduler/status` (×2-3)** — confirmed
  **still present** (P2, OPT-rated in the original report). Three independent code paths (`loadHome`,
  `refreshHomeLive`'s immediate tick, `checkEmptyCorpus`) each fire their own request with no path-keyed
  de-duplication in the shared `api()` helper.

## 6. New-surface audit — LLM/vLLM stack (B1-B7, shipped 2026-07-24)

This body of work shipped one day before this audit and had never been reviewed by anyone but its own author.

**Sound (verified by direct source read):**
- Never writes the trusted rule-based index tables — `record_keywords()` is the sole write path, only ever
  constructs `AiKeyword` rows; grep across `src/ai_layer/*.py` for the trusted-table model names returns zero hits.
- Garbage/malformed model output is never invented — missing fields default to `[]`, empty-content articles are
  honestly gated before ever calling the model.
- torch/vLLM stay fully out of the core dependency tree (`pyproject.toml` has zero `vllm`/`torch` entries); vLLM
  installs into its own venv (`data_dir()/vllm_venv`), never the app's own interpreter.
- No `shell=True`/injection risk anywhere in the vLLM subprocess management; all argv lists are fixed or
  regex-validated (`_MODEL_RE`) before reaching a subprocess call.
- `run_concurrent` (the B3 concurrency helper) is genuinely order-preserving, isolates per-item failures without
  aborting the batch, and defaults to a byte-identical serial for-loop for Ollama (`max_workers<=1` → no
  `ThreadPoolExecutor` constructed at all). No SQLAlchemy `Session` is shared across concurrent workers at any of
  the three real call sites (bulk translate/summarize, continuous langdetect, perception extraction).

**Defects (§3 above for the P0; two more, both minor):**
- The B6 gate defect (§3) — **P0**.
- A benign TOCTOU race in `get_client_with_name()`'s per-backend client cache (`src/llm/backend.py:192-204`, no
  lock on a check-then-act dict write) — confirmed real, but the skeptic pass downgraded it from the claimed P2
  to **P3/info**: `httpx.Client()` opens no socket at construction (lazy connection), has no `__del__`, and the
  losing instance is never even bound to a local before being superseded — CPython reclaims it near-instantly via
  refcounting. Real, fixable in one line (`threading.Lock` or `dict.setdefault`), essentially zero practical impact.

## 7. New-surface audit — throughput brief (C1-C17, shipped 2026-07-24)

Checked against this project's own extensively-documented, historically-recurring bug classes for exactly this
kind of change (savepoint-vs-whole-rollback, delete-then-reinsert double-counting, autoflush-hands-gate-to-a-read,
mid-batch-handler-discards-siblings, single-writer-gate-coverage-of-bulk-DML).

**Sound:** the bulk `KeywordMention` insert (C13) correctly uses the single-writer gate's `do_orm_execute` path
(not a raw connection bypass) and is protected by a real SAVEPOINT (`begin_nested()`) for mid-batch collisions;
the in-memory dedup front (C12) never produces a false negative (a miss always falls through to the real DB
check) and today's one bulk-delete path (newsletter removal) doesn't even touch the front, so its documented
"self-healing" claim is currently unreachable-but-true; the C15 archive-backfill cursor is written **after** the
fetch attempt completes (not before — the audit's own hypothesized failure direction was backwards from what the
code does — a crash mid-tick causes redundant re-attempts, never a silent skip); robots.txt is still enforced
fail-closed for the new sitemap-discovery and crawl-by-default code paths, through the same `EthicalFetcher`.

**Defect (P1, confirmed real, corrected severity unchanged):** `src/ingest/archive_backfill.py`'s per-URL loop
and `src/scheduler/runner.py`'s `run_housekeeping_lane` per-kind loop (both new/consolidated by C1+C2+C15) catch
broad exceptions but **never call `session.rollback()`**. `store_fetched` only catches `IntegrityError`; any other
DB exception (an `OperationalError` variant, a raw sqlcipher3 driver error — this project's own documented
`is_locked_error` class of bug) propagates uncaught, leaving the shared session in a `PendingRollbackError` state
for the rest of that tick. Since `archive_backfill.py` advances its cursor **unconditionally** and persists it via
a plain JSON write fully decoupled from the SQLAlchemy transaction lifecycle, every subsequent URL in that tick's
slice gets permanently, silently marked "attempted/error" even though it was never actually fetched — a genuine,
non-transient loss of archive coverage. The skeptic pass independently reproduced the mechanism with a standalone
SQLAlchemy repro and traced one step further than the original claim: `qualification.py`'s `trial_fetch` has the
identical pattern and can poison the *same* shared session, cascading the false-failure to every other ride-along
in that tick (world_discovery, markets, country_data, …) — directly contradicting `run_housekeeping_lane`'s own
docstring claim that "one kind's failure never skips the rest."

## 8. New-surface audit — 0.3 close-gate row 1 (source-management program)

Six of seven named components are genuinely wired end-to-end (not merely designed), independently confirmed by
reading imports/router registration/ingest-time call sites — not by trusting the ledger's own narrative:

| Component | Status |
|---|---|
| Qualification admission gate (`select_sources` filters on `status=QUALIFIED`) | ✅ wired |
| Source model gains `status`/`qualified_at`/`qualification_criteria_version` | ✅ wired |
| Background qualification job + endpoints | ✅ wired (`src/catalog/qualify_job.py`, `/api/sources/qualify-bulk*`) |
| Re-qualification backoff ladder (1→2→4→6 months) | ✅ wired (`backoff_months()`, append-only attempt history) |
| Newsletter/.eml links → `ArticleLink` rows | ✅ wired |
| Airplane/Ollama gate split (loopback allowed, `pull`/`remove` still gated) | ✅ wired |
| Per-article/per-source IP surfacing | ✅ wired |
| Discovery trail + citations tally/drills | ✅ wired |
| Nav-soup prose gate at ingest time (not just diagnostic) | ✅ wired, default ON |
| Post-import delta screen + LLM triage/tag runs | ✅ wired |
| **Tor-exit-resolve (SOCKS RESOLVE / 0xF0) path** | ❌ **design-only** — zero code exists; CLAUDE.md's own text admits "assessed, design of record pending the go" |
| **USER_MANUAL docs↔app reciprocity** (qualification / source management / post-import screen chapters) | ❌ **missing** — zero occurrences of "qualif" anywhere in the manual |

Both ❌ items are checked against gate row 1's *own explicit text*, which requires the program to be "implemented
AND DOUBLE-CHECKED... field-confirmed, not merely merged," and separately states "'double-checked' INCLUDES
docs↔app reciprocity." The Tor-exit-resolve gap was downgraded by the skeptic pass from P1 to **P2** (a
gate-self-consistency/documentation defect — nothing in the running app is broken by its absence, and the gate
itself has not yet been closed). The USER_MANUAL gap stayed **P1** (a real, user-facing discoverability problem:
a newly-added source can sit unscraped for up to ~6 months under the ladder with no explanation anywhere a user
would find it).

## 9. Fresh non-negotiables spot-check

Five concrete, checkable claims from CLAUDE.md's own "Non-negotiables" section, hand-verified against current
code (distinct from 07/08's scope, which focused on tool-by-tool method/truth/gap rather than these specific
safety claims):

| Claim | Status |
|---|---|
| App boot makes zero network calls | ✅ holds — both the plaintext and encrypted-unlock boot paths install the socket guard + engage the kill switch synchronously before the ASGI app is ready to serve |
| robots.txt fail-closed | ✅ holds — a fetch failure or 401/403 refuses the fetch (`RobotsUnavailable`); `respect_robots=False` is never set anywhere in `src/` or `tests/` |
| Single fetch path (EthicalFetcher/guarded_session) | ✅ holds — independently re-ran the ratchet test's own regex over every file in `src/`; exactly the 4 documented allowlisted importers, zero new offenders |
| No bundling of Ollama/models; core deps free of torch/vllm/transformers | ✅ holds — zero committed model weights (`find . -size +5M` empty); zero torch/vllm/transformers in any `pyproject.toml` dependency block |
| No composite trust/quality scores anywhere in the 2026-07-17→24 work | ✅ holds — the `_BANNED_FIELD_FRAGMENTS`/`CardSchemaError` denylist is intact; every new qualification/triage/tags module uses only categorical stamps (`unqualified`/`qualified`/`disqualified`), never a score field |

No P0 ethics violations found in this pass.

## 10. Security sweep

`bandit -r src -ll -q` (the project's own documented house command) reproduces its claimed clean result — 0
medium/high findings. Going beyond the house command: all 117 suppressed low-severity findings were manually
reviewed (all cache/best-effort bookkeeping, no swallowed security checks); all 55 `# nosec B608` dynamic-SQL
annotations across 12 files were individually traced and confirmed to genuinely have their claimed safety
property (constant identifiers, or an allowlist-regex + identifier-quoting two-layer defense for the one
genuinely-untrusted-input case, backup manifest table names); zero hardcoded secrets/credentials/private keys
anywhere in `src/`, `configs/`, or tracked files; zero `eval`/`exec`/`pickle.loads`/unsafe `yaml.load`/
`os.system`/`shell=True` anywhere in `src/`.

**10.1 — Symlink-follow path traversal in folder-backup restore (P1, confirmed, live-reproduced).** See the
executive summary (§1 #3). `restore_folder_backup()` walks an untrusted source folder with `Path.rglob("*")` and
copies each entry via `open(src, "rb")`, which follows symlinks — no `is_symlink()` check, no `Path.resolve()`+
containment guard. The sibling `verify_folder_backup()` in the *same file* correctly defends the identical
threat model (its own docstring: *"a folder backup on an external drive can be edited: every name→path field is
traversal-guarded before we stat/hash it"*). Reproduced live: a symlink inside a fake backup's `wiki_dumps/`
pointing at an out-of-tree secret file has its **content** silently copied into the live data directory as a
plain (non-symlink) file. This is a recurrence, in a sibling backup module, of a defect *class* this exact
project has previously found and fixed as serious in the same subsystem (the 2026-07-10 ledger entry on
traversal-guarding every manifest/config path field). Precision correction from the skeptic pass: this is
symlink-following information disclosure (CWE-61/CWE-59), not classic directory-escape — the destination path
stays correctly bounded inside the live data directory (derived structurally via `relative_to()`, not from
attacker-supplied strings), so there is no arbitrary-write-location primitive, only arbitrary-*content*-under-a-
chosen-filename-inside-the-target-directory.

**10.2 — Outdated Pillow in the committed lockfile (P2, confirmed, downgraded from claimed P1).**
`requirements.lock` pins `pillow==12.2.0`; `pip-audit` (installed and run against PyPI's real advisory data)
reports 13 distinct real CVEs, all fixed in 12.3.0. `src/verification/metadata.py:extract_image_metadata()`
(`Image.open()+.load()` on fully untrusted upload bytes, zero pre-validation) is reachable via
`POST /api/verify/image-metadata`, whose entire purpose is analyzing suspicious images a journalist encountered
in the wild — precisely the threat model these CVEs target. CI's `lockfile-resolve` job only hash-validates the
lock file (`--dry-run --require-hashes`); the actual blocking `pip-audit` step audits a separate,
pyproject-floor-driven install that would resolve to whatever Pillow is newest at CI run time — explaining why
this slipped through. **Severity correction (why P2 not P1):** the skeptic pass installed 12.2.0 and read the
actual vulnerable source to check reachability through this app's *exact* narrow usage — only `Image.open()` /
`.load()` / `.getexif()` are ever called, never `.paste()`/`.crop()`/`.save()`/`ImageCms.*`/any font loader. Of
13 CVEs, only 2 are actually reachable (a JPEG2000 tile-width memory-exhaustion bug and an EPS negative-byte-count
loop), both DoS-class (OOM/hang), not the heap-corruption/OOB-write bugs the raw advisory list implies. Fix is
trivial: bump the pin to `>=12.3.0` and regenerate the lockfile.

**10.3 — requests CVE (refuted).** A candidate finding claimed `requests==2.32.5` (pinned in `requirements.lock`)
carries `PYSEC-2026-2275`. **Refuted by the skeptic pass**: the actually-pinned version is `requests==2.34.2`
(newer than the advisory's own fix version, 2.33.0) — the original claim misread the lockfile. Recorded here only
as a worked example of the adversarial-verification layer catching a real false positive.

**10.4 — Bare `assert` in six diagnostic self-tests' own no-score-fabrication check (info).** Six modules
(`conjunction.py`, `skeleton.py`, `source_audit.py`, `leads.py`, `tor_throughput.py`, `search_timing.py`) each
implement their own `_walk_no_score()` self-test helper via a bare `assert`, which `python -O`/`PYTHONOPTIMIZE`
would silently strip — meaning that self-test's own "no fabricated score" honesty check would false-pass under
that (currently unused-anywhere-in-this-project) interpreter flag. Does **not** affect the live production
enforcement (`src/briefing/card.py`'s `CardSchemaError`, which correctly `raise`s, not `assert`s) — only these
six modules' own diagnostic self-reports about themselves. Confirmed the project sets no `-O`/`PYTHONOPTIMIZE`
anywhere in its own launch/CI tooling today, so this is currently inert; worth a one-line fix per module
(`if ...: raise AssertionError(...)`) given how much weight this project's own documented culture places on
exactly this failure mode.

## 11. Corrections to 08 itself (info-level, not code defects)

Two places where 08's own text made a claim its own author's search evidently missed, confirmed by checking out
the exact commit preceding 08's authoring commit (`fff575b^`):

- **08's B1/C1 rows state "no evidence found" for the LLM-artifact label and the Wikipedia-bias manual note.**
  Both already existed at `fff575b^` — `src/api/main.py` already rendered "AI-derived — unreliable" in the
  reader view, and `docs/USER_MANUAL.md` already carried both the "record begins" and "Wikipedia carries its own
  systemic biases" paragraphs (added 3 days earlier, PR #705). 08 likely searched for a specific literal phrasing
  ("model-artifact — verify") the codebase never actually used, and appears to have grepped `src/` only, not
  `docs/`. Interesting precedent: 08's *own document* already self-corrected an analogous mistake on its B2/fixity
  finding via a follow-up commit (`53eafa8`, same root cause: "grep-without-opening-the-file") — this B1/C1
  instance was never given the same correction.
- **08's C4 framing** ("no evidence found this session that `perf_harness.py` was extended past T1's 6.4k
  profile") — the extension happened 5 weeks before 08 was drafted, commented "audit-07 B3" in the file itself
  (§4 above).

Neither correction changes any substantive conclusion 08 reached about *remaining* gaps — in both cases the
underlying gap 08 was chasing (a dashboard/checkpoint/artifact that still doesn't exist) remains real; only the
"was anything done since 07" framing was inaccurate for these two sub-items.

## 12. Action Plan D — 0.3 delta edition, ranked

1. **Fix the airplane-mode SOCKS/Tor blind spot** (§2) — the highest-consequence finding, given the population
   this guarantee exists to protect most. Recommended shape: gate proxy-session construction itself on
   `kill_switch_active()`, not just per-fetch-call sites; add a SOCKS-path regression test.
2. **Fix the B6 perception-extraction gate** (§3) — a one-line unwrap (`report["report"]`) restores the entire
   feature; fix the tests' mock shape to match the real envelope so this class of bug can't recur silently.
3. **Fix the folder-backup restore symlink-follow gap** (§10.1) — apply `verify_folder_backup`'s existing
   `_safe_member_path()` guard (or equivalent) to `restore_folder_backup`'s copy loop.
4. **Bump Pillow to >=12.3.0 and regenerate `requirements.lock`** (§10.2) — trivial, closes two live DoS vectors
   on a journalist-facing endpoint.
5. **Add `session.rollback()` to `archive_backfill.py`'s and `run_housekeeping_lane`'s except handlers** (§7) —
   this project's own established fix pattern elsewhere in `pipeline.py` (`_maybe_index_keywords`/
   `_maybe_index_links`) is directly reusable.
6. **Extend the all-diagnostics completeness ratchet to scan every diagnostic-shaped router, not just
   `diagnostics.py`** (§4, C2) — then fold fixity in as originally asked.
7. **Reconcile gate row 1's own text** — either build the Tor-exit-resolve path or explicitly mark it
   maintainer-ruling-gated rather than "implemented," and write the missing USER_MANUAL chapters
   (qualification / source management / post-import screen) before closing row 1.
8. **One-line fix on the 6 bare-`assert` self-test honesty checks** (§10.4) and the `get_client_with_name()`
   TOCTOU (§6) — both cheap, low-priority.
9. **Add "conservative-default bias" to the standing bias taxonomy** (§4a) — done inline in this document; carry
   forward into future audits as a named check.
10. **Re-audit delta discipline for edition 10** — check this document's own Action Plan D items against the
    ledger before writing the next edition, per the same C8 discipline this edition itself followed.

## 13. Scope honesty, restated

This edition is **report-first**, matching the established convention for audit/test-pass documents in this
repo (the GUI test report's own explicit "not built this pass"). No fixes were applied in this session — every
finding above is a verified observation, not yet a shipped remediation. Every severity claim in §1-§10 passed
through an independent adversarial skeptic that actively tried to refute it (12/13 candidates survived, 1
refuted — §10.3); the single highest-stakes finding (§2) was additionally hand-verified by the orchestrating
session directly against the real installed PySocks library source, not taken on the workflow's word alone.
Sections not marked "delta" restate 07/08 without independent re-verification this session — they are not
re-confirmed, only carried forward with attribution, per those documents' own stated discipline.

— Audit drafted 2026-07-25, authored by a 23-agent orchestrated workflow + hand-verification of the headline
finding by the orchestrating session; no prior draft of this file existed anywhere in the repo or origin/main at
session start.
