> **Status update (2026-07-22, docs-audit remediation pass):** verified against live `main` by a subagent fan-out audit of the whole `docs/design/` tree — Slice 3's remainder (laws stored full-text per-revision, ingested via `index_article` as first-class corpus Articles) is now confirmed SHIPPED — see `src/law/corpus.py`, which mirrors `src/wiki/corpus.py` deliberately. Two carry-overs remain genuinely open: Slice 2 (a first-launch external-drive data-location chooser) and Slice 4a's remainder (a reversible retroactive quarantine ACTION — `src/analytics/quarantine_job.py` is still explicitly build-only, no singleton wired). See [`ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md`](./ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md) for the full remediation plan.

# Fix-session prompt — 2026-07-14 (data-safety first)

**What this is.** A ready-to-paste kickoff prompt for a Claude Code CLI session (Opus 4.8,
max effort) that fixes a set of confirmed, live defects on `origin/0.2`. Written by the
Fable-5 planning instance per the standing workflow ruling (web = planning/design; CLI =
coding). Every claim below was verified against `origin/0.2` at the time of writing
(tip `8e51103`, 2026-07-13). **It leads with a data-safety corpus-backup bug the maintainer
hit in the field.**

**Read the STALENESS GUARD first — a lot shipped on 2026-07-13 and this prompt must not
re-do it.**

---

## STALENESS GUARD (do this before touching anything)

The tree moves fast; briefs lag merged work. Before each slice below, `git fetch origin 0.2`
and confirm the defect is still present with the exact `file:line` grep given in the slice.
If a slice is already fixed, mark it VERIFIED-PRESENT in your closeout and skip it — do NOT
rebuild.

**Already shipped on 2026-07-13 (do NOT redo — verify-and-mark only if a slice touches
them):**

- **Non-article ingest filter** (#659) — a high-precision ingest-time classifier now stops
  nav/index/tag/tool/wall pages at the door. So the *forward* half of "~42% of stored items
  are non-articles" is done. Only the **retroactive cleanup** of already-stored non-articles
  remains (Slice 4a).
- **Source-quality diagnostic v2** (#656) + the **standing source AUDITOR** (#663, FLAG-ONLY,
  auto-demote machinery built but DEFAULT-OFF) + two sources disabled (#657). So the
  source-quality recalibration is substantially addressed; do NOT re-prompt a p90→p99
  recalibration without first reading `src/analytics/source_quality.py` on the tip — the
  auditor may already carry the direction-aware thresholds.
- **Optimization-program cores S1–S8** (#643–#653, all draft PRs) — Conjunction Lens, Leads
  2.0, keyword fingerprints, search-timing, power profiles, Tor throughput, LLM keyword
  triage, recursive-loop diagnostics. Out of scope here.
- **Subjectivity engine surfaced in the reader** (#664, Part-3A). Out of scope here.
- **Cumulative integrity audit** (#639–#642) — found and fixed only BUG-1 (columnar
  bare-except). It did **not** look at the field-diagnostic-zip findings or the law vertical;
  those are this session's job.

**Rollup-serve note:** `src/analytics/rollup_serve.py` is now AUTO-ON whenever the `[columnar]`
duckdb extra is installed (no flag). So the field "trending rollup not landing (280 s)" is
most likely a **deployment** gap (duckdb not installed on the field box), not a code bug —
do not "fix" it in code; note it as operator (`pip install -e ".[columnar]"`) unless you find
a genuine code path that fails with duckdb present.

---

## WORKING MODE (binding)

- One PR per slice, small + additive, **draft** onto `0.2`, branches `claude/fix-*`, stacked
  (rebase on a freshly-fetched `0.2` tip as bottoms merge). Nothing self-merges — the
  maintainer reviews every PR.
- **Skeptics-before-push with the mandatory negative-space lens** on every honesty- or
  data-safety-critical slice (Slices 0, 1, 3). A parser/guard skeptic must generate
  should-be-empty / should-fail inputs and assert them, not only the positive path.
- Verify with the in-repo `.venv` (py3.13): full `pytest -q` stays green; `ruff` F/B clean;
  `mypy` ratchet ≤ baseline (per-file `mypy <file>` shows 0 new); `node --check` every
  `<script>` block after UI edits; `python scripts/i18n_report.py --min 100` when adding
  chrome strings (12 locales, Arabic RTL).
- Frontend that can't be browser-verified here ships CONSERVATIVE + FLAGGED (node-check +
  extend `tests/test_repo_invariants.py` / `test_ui_invariants` + defensive states; "browser
  unverified, needs click-through" per fork-3).
- Honesty non-negotiables carry into every slice: no composite scores (field NAMES, not
  `repr()`), caveats visible by default, three provenance classes never blended
  (asserted / deduced / AI-derived·unreliable), degrade loudly, zero fabricated
  data/checksums/dates, airplane socket guarantee + the ONE consent popup, reversible
  (disable/quarantine, never silent delete).

---

## ORCHESTRATION & CONTEXT DISCIPLINE (binding — the main context is the scarce resource)

This session WILL outlive its context window. Run the main agent as a thin ORCHESTRATOR
whose context holds only plans, verdicts, and diffs-in-review — never raw file contents —
and push everything durable into files/git immediately. Concretely:

**1. The main agent never reads big files.** `src/static/app.js` is ~14k lines; this repo's
`CLAUDE.md` alone has overflowed recon agents before (recorded lesson, S3.3). All recon,
verification, and code-reading goes through subagents (Explore/general-purpose) with a hard
RETURN CONTRACT: verdict first, ≤40 lines, `file:line` evidence, NO file dumps. An agent
that needs context gets it fed INLINE in its prompt (the exact snippet + surrounding facts)
— never "go read CLAUDE.md" or "open app.js".

**2. Phase 0 = one parallel staleness fan-out (before any build).** Launch ONE read-only
agent PER SLICE (0, 1, 2, 3, 4a–4d) concurrently, each given the slice's exact grep/`file:line`
anchors from this doc, returning `LIVE | SHIPPED | CHANGED (new evidence)` + a ≤10-line
justification. The orchestrator only integrates verdicts. Do not sequentially re-derive what
the fan-out already established.

**3. Durable session state, compression-proof.** Immediately create a state file at a fixed
path (`docs/ledger/.fix-session-2026-07-14-state.md` in the working tree, or the session
scratchpad — pick ONE and never move it) holding, per slice: verdict, branch name, PR #,
tests status, NEXT ACTION — under 80 lines total, updated the moment anything changes.
**After any context compaction, re-read this file FIRST and trust it over recollection.**
Git is the other half of durable memory: commit early and per-logical-step on each slice
branch, push as soon as a slice is reviewable, write the `shipped.csv` row in the same PR —
so nothing load-bearing lives only in context.

**4. Parallel builds in isolated worktrees (the slices are file-disjoint by design).**
Slice 0 (`app.js` + a JS test), Slice 1 (`write.py`/`batch.py` tests), Slice 2
(`unlock.html` + a small endpoint + `install.sh` seam), Slice 3 (`src/law/` + models +
migration), and Slice 4b (`extract.py`/selftest) touch disjoint files. After Phase 0, launch
their implementation agents IN PARALLEL, each with `isolation: worktree`, each prompt
carrying: the full slice text from this doc, the honesty rules that bind it, and the return
contract (branch name + `git diff --numstat` + test names added + a ≤30-line summary).
Exceptions to parallelism:
- **Shared append-targets stay sequential in the orchestrator**: `docs/ledger/shipped.csv`,
  CLAUDE.md-adjacent ledger edits, and `tests/test_repo_invariants.py` if two slices touch
  it — additive merges only, orchestrator applies them one at a time.
- **Full-suite runs are serialized.** Worktree agents run TARGETED tests only; the
  orchestrator runs the FULL `pytest -q` once per branch, one branch at a time, in the
  primary checkout (never switch branches while a suite is running — recorded lesson,
  2026-07-09).
- Slice 4a (quarantine) depends on the #659 classifier — build it after Phase 0 confirms
  the classifier's tip-state, not in the first wave.

**5. Skeptics: parallel, lens-diverse, inline-fed.** For Slices 0, 1, 3 (honesty/data-safety
critical) launch the skeptic panel CONCURRENTLY (distinct lenses: data-loss ·
negative-space/should-be-empty · concurrency · regression), each fed the DIFF INLINE plus
only the facts it needs. Skeptics must COMPLETE before push (the #542→#544 rule). Their
verdicts go into the state file, not just the conversation.

**6. Orchestrator review discipline.** The main agent reviews each slice as: the agent's
summary + `git diff --numstat` + reading ONLY the hunks it needs to judge (via targeted
`git diff` on specific files). It hand-re-verifies any skeptic HIGH before accepting a fix
(the 06-audit false-positive lesson). It never pulls a whole changed file into context.

**7. When context compression hits mid-slice** (it will): the state file + the slice branch's
commit log ARE the resume point. Re-read the state file, `git log --oneline` the active
branch, and continue — do not re-run Phase 0 for slices already marked, and do not rebuild
anything a pushed commit already contains.

---

## SLICE 0 — DATA-SAFETY, TOP PRIORITY: the "large data" backup silently skips the corpus

**Field report (verbatim intent):** the maintainer ran the unified Export with *everything*
selected (a few models, many wiki dumps, almost all maps, ~350K articles). The export folder
finished — but **the corpus (articles) was not backed up**. Blobs (wiki/maps/models) were
present; the UI said "Backup complete." The maintainer is re-running a corpus-only export as
the workaround (which is correct — the volumes+parity path IS the real corpus backup).

**Confirmed root cause (regression from `2a10cd3` "fix(backup-ux): job-state-as-truth", B5,
2026-07-10).** The backend is NOT at fault: `write_stream_backup` unconditionally emits the
corpus member (`src/backup/stream_backup.py:922-926`,
`_emit_member(st, MemberFile(src.member_name, "corpus", src.path))`), and
`volume_job._run_backup` sets `state="error"` on any exception
(`src/backup/volume_job.py:139-142`). So a volumes job that reaches `state:"done"` genuinely
wrote the corpus. The hole is in the **frontend `_uxRun` volumes→folder sequencing**:

- `_uxStartThenPoll` (`src/static/app.js:5061-5074`) masks a start error by accepting **any**
  live job — line 5071 `if (!(s === "running" || s === "paused")) throw e;` — it never checks
  the live job's `mode` or `dest`. `api()` throws on every non-2xx, so a **409** from
  `_reap_or_reject` ("A volume backup/restore is already running", `volume_job.py:57`) lands
  in this catch. All of `start_backup`/`start_restore`/`start_verify` share **one**
  `VolumeBackupManager` singleton and **one** `/v2/volumes/status` that reports the mode/dest
  of whatever that manager is doing (`volume_job.py:290-292`).
- `_uxRun` (`src/static/app.js:5097-5098`) only special-cases the **paused** result
  (`if (s1 && s1.state === "paused") { … return; }`) and treats everything else — including a
  `done` that belongs to a **different** job — as a completed corpus backup, then proceeds to
  `folder/start` (blobs) and prints "Backup complete → &lt;dest&gt;" (`app.js:5107`). There is
  **no `s1.state === "done"` / `mode === "backup"` / dest-match assertion.**

**Reproduction (entirely in-app, matches the report):** a prior/concurrent volume op is live
— e.g. a Verify launched from the Import dialog, a first export into another drive still
streaming the 350K-article corpus, or a double-clicked Export. New `/v2/volumes/start` →
`_reap_or_reject` 409 → `api()` throws → catch consults `/status` → sees the OTHER job
`running` → line 5071 passes → polls it → it reaches `done` → `s1.state==="done"` (not
"paused") → `_uxRun` runs `folder/start` → blobs copied → "Backup complete." **The corpus for
the chosen drive was never written.** Pre-`2a10cd3` the code was strict (any start throw
propagated to `_uxRun`'s catch → "Backup failed" → folder phase unreachable); B5 loosened
exactly this abort path.

**THE FIX — restore the invariant "the folder (blobs) phase is unreachable, and 'Backup
complete' is never shown, unless the volumes phase provably completed as a `backup` of the
corpus into THIS `dest`."**

- **(A) Gate the folder phase (load-bearing, surgical) — in `_uxRun` right after the paused
  guard (`app.js:~5097`):**
  ```js
  if (s1 && s1.state === "paused") { _uxShowPaused(prog, bar, pauseBtn, t); btn.disabled = false; return; }
  if (!s1 || s1.state !== "done" || s1.mode !== "backup"
      || (s1.dest && !_uxSamePath(s1.dest, dest))) {
    throw new Error(t("The corpus backup could not be confirmed — aborting before the "
      + "large-data files so you never get a partial backup that looks complete."));
  }
  ```
  This throws into `_uxRun`'s existing catch (`app.js:~5108`) → "Backup failed:" → `folder/start`
  is never called. Add `_uxSamePath` (normalize trailing slashes; `s1.dest` is the
  backend-normalized `str(destp)` from `volume_job.py:87`). If reliable path comparison is
  awkward, keep at minimum the `state==="done" && mode==="backup"` checks — those alone kill
  the verify/restore attach.
- **(B) Stop the masking attaching to an unrelated job — `_uxStartThenPoll` (`app.js:5071`):**
  thread an `expect = {mode:"backup", dest}` and re-throw when the live job doesn't match:
  ```js
  if (!(s === "running" || s === "paused")) throw e;
  if (expect && expect.mode && st.mode && st.mode !== expect.mode) throw e;   // NEW
  ```
  So a 409 from an unrelated verify/restore/other-dest backup re-throws → "Backup failed: A
  volume backup/restore is already running" → the user waits, never a false success. A
  genuinely lost *response of this backup* (the legitimate B5 case: `mode==="backup"`, dest
  matches) still masks correctly. Pass the same `expect` on the folder-phase call for symmetry
  where `mode` applies.
- **(C, optional, cheap defense-in-depth):** `/v2/volumes/start`'s 409 payload can include the
  live `mode`/`dest` so the UI can message precisely ("a Verify is still running"). No schema
  migration; no backend behavior change required — the client already receives `mode`/`dest`
  in `status()`.

**Regression test (node/DOM harness stubbing `api()` and driving `_uxRun`) — must assert:**
1. **Core data-safety:** with `/v2/volumes/start` rejecting (409) and `/v2/volumes/status`
   reporting a live job that is NOT this backup (`{state:"running", mode:"verify"}`, or
   `mode:"backup"` with a *different* `dest`) which later reaches `{state:"done"}` — `_uxRun`
   **never calls `/api/backup/folder/start`** and renders "Backup failed", not "Backup
   complete".
2. Any volumes resolution with `state !== "done"` (or `mode !== "backup"`, or mismatched dest)
   does not start the folder phase nor report success.
3. **Positive path:** a clean volumes job reaching `{state:"done", mode:"backup", dest:<this
   dest>}` DOES proceed to the folder phase and reports success (proves the fix keeps the legit
   flow, including the intended lost-response masking of *this* backup).
4. **Backend contract (Python):** `write_stream_backup` always includes a `role=="corpus"`
   member in its manifest/summary (pins the "done ⇒ corpus present" invariant the fix relies
   on), so a future refactor can't silently drop it.

**Ruled out (checked — do not chase):** the folder phase does not clobber `volumes.json`
(`folder_backup.py` writes its own `oo-folder-backup.json` + category subfolders); the
reuse-pool never skips the corpus member (a passphrase/format mismatch re-emits everything);
`ux-c-corpus` is never read by `_uxRun`, so the corpus phase is always attempted — it's the
mask/attach that diverts it.

**New chrome string** ("The corpus backup could not be confirmed…") needs keying ×12 (English
fallback via `t()` is fine to ship; key it in the same PR if quick).

---

## SLICE 1 — DATA-INTEGRITY: the "database is locked" retry net is dead on encrypted stores

**Confirmed live** (`src/database/write.py:46-55`):
```py
def is_locked_error(exc: BaseException) -> bool:
    if not isinstance(exc, OperationalError):   # line 52
        return False
    ...
```
On an **encrypted (sqlcipher3) store**, a "database is locked" surfaces as a raw
`sqlite3`/`sqlcipher3` exception that SQLAlchemy does **not** wrap as
`sqlalchemy.exc.OperationalError` (the engine is a plain sqlite dialect with a sqlcipher3
creator — `src/database/session.py:60-78`). So `is_locked_error` returns `False`, the
`run_write_with_retry` backoff never engages, and the `src/ingest/batch.py` rollback-then-redo
path (which calls `is_locked_error`, batch.py:~286) never fires. Field evidence: 297 fetched
articles left **unindexed** (data discarded after a successful fetch — the exact loss this
module exists to prevent, per its own docstring `write.py:9-11`).

**THE FIX:** make `is_locked_error` recognise the locked/busy condition **regardless of
exception class** on encrypted stores — match on the message across `OperationalError` AND the
raw sqlite3/sqlcipher3 error types. Do it precisely:
- Keep the `OperationalError` fast path.
- Add: if the exc (or its `__cause__`/`__context__`) is a `sqlite3.OperationalError` /
  `sqlcipher3.dbapi2.OperationalError` (import lazily; sqlcipher3 may be absent in a core
  install → guard), match `"database is locked"` / `"database is busy"` in `str(exc)`.
- Do NOT broaden to *all* exceptions (a genuine `IntegrityError` must still take the
  dedup/redo-per-row path, not the backoff). Only the locked/busy **message** qualifies.

**Skeptic (negative-space) must assert:** a non-locked sqlcipher3 error (e.g. a real
`IntegrityError` / a syntax error) is NOT treated as locked (no infinite backoff on a
permanent failure); a plaintext `OperationalError: database is locked` still matches (no
regression); a wrapped-cause case (`raise X from sqlite3.OperationalError("database is
locked")`) matches. **Test the encrypted path** — the field failure only reproduces with the
real sqlcipher3 error class, so a plaintext-only test would pass while the bug survives (this
is a CI-only test; prove the message-matching logic here with a standalone repro over the pure
`is_locked_error` function fed a fabricated sqlcipher3-shaped error).

Then confirm the `batch.py` redo path re-arms once `is_locked_error` is fixed (the 297-article
loss condition): a batched collect commit that hits a locked error must roll back and redo
per-article with zero loss (extend `tests/test_write_gate_dataloss.py` / the batch tests).

---

## SLICE 2 — FEATURE: first-launch external-drive data-location chooser

**Maintainer request:** at first launch, after choosing language and accepting the legal
conditions (and before/at the passphrase step), let the user pick where the app stores its
database: **default** (the app data folder) or **choose a folder** — in which an **"OOS data"**
subfolder is created and used as the data dir. This is the on-ramp for putting a 100 GB+
corpus on an external drive.

**Reuse the shipped A11 persistence mechanism, do not invent one:** `install.sh`
`persist_data_dir()` already writes `export OO_DATA_DIR=<path>` to `<install>/oo.env` (mode
0600, atomic tmp+mv, `%q`-quoted) and `scripts/launch.sh` sources it. The whole data layer
keys off `data_dir()`. So the chooser's job is: (1) let the user pick a folder, (2) create
`<picked>/OOS data/` (create-if-absent, must be writable, honest free-disk preflight),
(3) persist it as `OO_DATA_DIR` via the same `oo.env` seam, (4) proceed to passphrase against
that dir.

**Where it lives:** the fresh-store flow in `unlock.html` is already
language → legal-accept → create-passphrase, all **pre-DB** (the correct seam). Insert a
**data-location step between legal-accept and create-passphrase**. It needs a tiny backend
endpoint (pre-DB, loopback) to (a) validate a server-side path is a writable directory with
enough free space, (b) create `OOS data/`, (c) write `OO_DATA_DIR` to `oo.env` and re-point
the process's `data_dir()` before the passphrase/init runs. Honest states: unwritable path,
insufficient space (show needed-vs-free), tmpfs/ephemeral warning (reuse the A11 honest
tmpfs/Qubes-disposable detection — never "stop using DispVMs").

**Honesty/safety:**
- Default stays "app data folder" (one click). The external choice is explicit + reversible
  (changing it later is a Settings action + a move, out of scope for first-launch; at minimum
  document the manual move).
- At-rest encryption still applies to the corpus wherever it lands; the external-drive threat
  model (seized/off drive) is the same stated model — surface it.
- Zero network at boot preserved; this is a local filesystem action only.
- Key the new step ×12.

**Test:** `tests/test_repo_invariants.py` — the step exists in `unlock.html` between
legal-accept and passphrase; the endpoint validates writability + creates `OOS data/` +
persists `OO_DATA_DIR`; the default path is unchanged when the user picks default.

---

## SLICE 3 — LAW VERTICAL: laws are not scraped/ingested/tracked like Wikipedia

**Maintainer report + confirmed state:** government laws are NOT first-class corpus citizens
the way Wikipedia articles are. On `origin/0.2`:
- `src/law/` is only `__init__.py`, `catalog.py`, `track.py` — no corpus-ingestion module.
- `track.py` is a thin HTML-diff watcher: `page_text` (BS4 strip, :37), `_diff` (lossy, capped
  `_MAX_DIFF_LINES=4000` :33, diffs against a frozen baseline :146), no PDF/JS handling.
- `LawDocument`/`LawRevision` (`models.py:1846`, `:1890`) have **no `full_text`/`latest_text`**
  (those columns at `models.py:1768/1822` belong to WikiPage/WikiRevision) — so the app can
  neither show the *current* law text nor reconstruct a past version.
- Law does NOT flow through `index_article`, so laws are absent from keyword analytics, When×
  Where×Who, search, and the Leads.
- `configs/legal_sources.yml` is a tiny static catalog (~51 sources, ~17 tracked docs); tests
  are fixture-only.

**The ruling of record (CLAUDE.md "Versioned sources as first-class Articles"):** a versioned
source = **an Article + a linked revision/audit trail**. Wikipedia already does this
(`src/wiki/corpus.py` → `index_article`; `WikiRevision` is the linked layer). Laws get the
identical treatment: `LawDocument` becomes a first-class `Article` (keyworded, searchable,
When×Where×Who) with `LawRevision` as its linked audit layer.

**IMPORTANT scoping ruling (record + honor):** the *full* versioned-sources revamp
(auto-ingesting whole Wikipedia editions from dumps) is **P0-scale-gated and EXCLUDED**. The
law vertical is **much smaller** (tens–hundreds of tracked documents, not millions of
articles), so it is **not** gated by the 5 TB scale work — build the law half now, mirroring
`src/wiki/corpus.py`, without touching the excluded dump-ingestion path.

**Build (slice into PRs; each fully tested):**
1. **Store the full text per revision + a materialized latest.** Add `LawDocument.latest_text`
   (+ `latest_text_revid`) and `LawRevision.full_text` (both `CompressedText`, nullable,
   additive migration + boot self-heal like the wiki columns). `track.py` stores the full
   fetched text (not just a capped diff) so the current law is always shown and any past
   version is reconstructable. Keep the diff as a *derived* convenience, not the source of
   truth. Fetch stays through the ONE `EthicalFetcher` (robots fail-closed, kill switch, Tor,
   airplane-gated). Honest handling for PDF/JS-rendered pages (a `pypdf` text extraction for
   PDF law sources is the recommended dependency; a JS-only page that can't be extracted
   stores nothing + a stated reason, never a fabricated body).
2. **Ingest laws into the corpus via `index_article`** (mirror `src/wiki/corpus.py`): one
   `Article` per law document (canonical law URL; a dedicated per-jurisdiction source domain so
   laws stay a FILTERABLE provenance class forever — like per-edition wiki sources), synced to
   the latest text, idempotent on content hash, through the ONE `index_article` hook so
   keywords + When×Where×Who + sentiment follow the latest version automatically. Failures
   never block tracking.
3. **Search + reader.** Laws now appear in `/api/search/omni` (content, not just title) and in
   the reader with a **tracked-changes view** (the wiki pattern): current text default, the
   `LawRevision` history beneath, honest "raw extracted text" caveat + the storage-choice
   disclosure ×12.
4. **Grow the catalog** honestly (more jurisdictions, movable/uncertain fields marked; never a
   fabricated effective date). Keep sourced.

**Skeptic (negative-space):** a law page that fails to extract stores NO body + a reason, never
an empty-but-present article; a re-fetch of unchanged text does NOT create a duplicate Article
(hash dedup) but DOES record the revision check; a PDF with garbled extraction is flagged, not
silently indexed; the law source is a distinct filterable class (never blended into web-news
provenance).

---

## SLICE 4 — REMAINING FIELD-DIAGNOSTIC ITEMS (verify-then-fix; several may be partly done)

Re-verify each against the tip before building; note VERIFIED-PRESENT/SHIPPED honestly.

- **4a. Retroactive non-article cleanup.** The forward filter shipped (#659); already-stored
  non-articles (crawler-ingested section/index/tag/tool pages — field bundle estimated ~42% of
  stored items) remain. Build a **reversible QUARANTINE** pass (never a silent delete):
  reuse/extend the #659 classifier over the existing corpus, move flagged items to a quarantined
  state (excluded from analytics/search but restorable), report counts, let the operator review
  before purge. Honest: the classifier is high-precision but not perfect → quarantine + review,
  not auto-delete.
- **4b. Keyword extraction junk.** `tracking` ≈ 889k mentions (~1.2% of tokens) traces to
  **tracker-URL tokenization** (URLs bleeding into the keyword stream); repeated-token n-grams;
  accented-UPPERCASE call-to-action strings mis-tagged as entities (the acronym rule from #283
  is ASCII-oriented). Fix at extraction: strip/never-tokenize URL residue into keywords; drop
  repeated-token n-grams; extend the acronym/entity guard so accented all-caps CTAs
  ("PARTAGEZ", "S'ABONNER") are treated as terms/noise, not entities. Each fix lands in the
  keyword self-test (`src/analytics/selftest.py`) the SAME commit + a diagnostics-log
  before/after so the maintainer can measure it. Honor the stoplist-architecture lesson
  (scoped vs global channel; collision-check any global addition).
- **4c. Diagnostics endpoint freezes (verify-first — likely partly addressed by S2).** The
  field bundle showed multi-hour synchronous diagnostics GETs (home-cards 2.47 h) starving the
  single-worker threadpool. S2's guard-coverage sweep added admission caps + deadlines to
  insights endpoints and converted `/api/articles` async→def. **Re-check** which diagnostics
  GETs are still `async def` doing heavy synchronous DB+codec work on the event loop; convert
  the offenders to plain `def` (threadpool) or `run_in_threadpool` the body, and bound any
  whole-table materialization with the existing deadline/admission guard. Grep the TEST tree
  for the old `async def <name>(` signature before any conversion (the #283 stale-source-anchor
  family). Do NOT re-do what S2 already fixed.
- **4d. Segmenter (operator, not code).** zh/ja/th are unsegmented because the `[segmentation]`
  extra isn't installed on the field box. Note it as an operator step (`pip install -e
  ".[segmentation]"`), not a code fix — the seam is already `None`-fallback safe.

---

## DEFINITION OF DONE

- Slices 0 and 1 are the non-negotiable **data-safety** deliverables — ship them first, each
  its own draft PR, skeptic-verified, with the exact regression tests above.
- Every slice: draft PR onto a freshly-fetched `0.2`, full suite green in the `.venv`, ruff/
  mypy/node-check/i18n gates green, honesty non-negotiables intact, a `docs/ledger/shipped.csv`
  row, and a carry-over note for anything deferred (browser click-throughs per fork-3; the law
  catalog growth; the retroactive quarantine review is operator-run).
- Nothing auto-merges. The maintainer's PR review is the gate.
- The session state file (§Orchestration item 3) is deleted (or left in the scratchpad) at
  closeout — its content must by then be fully reflected in the PRs + `shipped.csv`; it is
  working memory, not a record.
