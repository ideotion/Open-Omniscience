# Autonomous-session build brief — resolve the open items from the 2026-06-20/21 field test

**How to use this file:** paste it verbatim as the first message of a fresh autonomous
session, OR keep it in the repo and tell the session "read
`docs/archive/session-briefs/AUTONOMOUS_SESSION_BRIEF_2026-06-21.md` and execute it." Everything the
session needs is below; it should still read `CLAUDE.md` in full first (the ledger is the
source of truth and overrides any conflict here).

This brief covers the **remaining / not-yet-built** work from the 2026-06-20→21 field-test
session (PR #420, merged; PR #421 legal docs, merged). Items already shipped in those PRs
are NOT repeated — only what is left.

---

## §0 — Operating contract (read before touching code)

1. **Read `CLAUDE.md` in full first, every session.** Record every new maintainer ruling
   in `CLAUDE.md` IN THE SAME TURN it is given (shipped → invariants/shipped-log; pending →
   the open queue). If a critical UI behaviour is added, extend
   `tests/test_repo_invariants.py` (and `test_ui_invariants` for chrome).

2. **Branching.** Develop each slice on a fresh branch cut from a **freshly-fetched**
   `0.09` (`git fetch origin 0.09 && git checkout -B <branch> origin/0.09` — `origin/0.09`
   goes stale within minutes given fast merges). One PR per slice, **small + additive**,
   opened as a **draft** onto `0.09`. The maintainer merges everything — nothing
   self-merges; every PR stays a draft. Stack branches as bottoms merge; rebase on a fresh
   `0.09`. After `git push`, if it says `[new branch]` the previous PR was merged → open a
   new PR onto `0.09`.

3. **Verification reality.** The container is **Python 3.11** and is missing some deps
   (`bleach`, the Rust `cryptography` build, a few test extras), so the **full pytest suite
   needs py3.13 → runs in CI**. Locally verify with: `python3 -m py_compile`,
   `node --check` (every `<script>`/static JS edit), `bash -n` (shell), the targeted tests
   you can run, and `python3 scripts/i18n_report.py --min 100`. Build a py3.13 venv if you
   can; otherwise lean on CI and say so honestly in the PR.

4. **Non-negotiables (honesty/ethics by construction):** local-first, loopback-only; the
   ONLY sanctioned external call is gated DuckDuckGo discovery. **Airplane mode is a
   socket-level hard guarantee** (`src/ingest/airplane.py`) + the global kill switch — every
   new network action must be gated and must open NO socket while engaged. **No composite
   trust/quality scores** (`CardSchemaError`/`assert_no_score_fields` enforce); every signal
   carries method + caveat + n. **Caveats are visible by default** (never hidden behind a
   toggle); long form goes in the `#oo-tip` hover. **Never fabricate data** (no invented
   sizes/dates/checksums/IPs — if you can't verify offline, flag "verify on a networked
   box" and fail loudly). **Never silently downgrade transport** (no Tor→clearnet fallback
   without explicit consent). **Encryption-by-default stays.**

5. **i18n.** Every user-facing chrome string ships ×12 locales (`src/static/locales/*.json`,
   flat `{"English string": "translation"}`; Arabic is RTL). The engine keys on the English
   string and auto-walks DOM text + translated attrs (`title`/`placeholder`/`aria-label`),
   so a clean single-text-node string is keyable by adding locale entries only.
   Interpolated JS strings need `t()`. New non-en translations are AI-drafted → **flag for
   native review** in the PR. Keep the `--min 100` gate green.

6. **Browser-unverified convention (fork-3):** UI you can't click-test here ships
   CONSERVATIVE + FLAGGED — `node --check`, extend `test_repo_invariants`, add defensive
   empty/error states, and write "browser-unverified, needs click-through" in the PR. No
   headless browser, no dark feature-flags.

7. **The Desk lesson:** never silently remove a tool/capability. When a surface is replaced,
   the old one is made unreachable (not deleted) and an absorption test proves nothing was
   lost.

8. **Autonomy — this session asks NOTHING.** Maintainer ruling 2026-06-21 (verbatim "Change
   the ruling, I don't want to be asked anything. … This session should be completely
   autonomous"). Make EVERY decision yourself — choose the most honest, conservative default
   and proceed; record each non-trivial choice in `CLAUDE.md`. There are **no open questions**
   (the three that earlier drafts flagged are answered in §1). Do **not** call
   `AskUserQuestion` for anything in this brief. (The only exception is a genuinely NEW
   ethics/irreversible/outward-facing surface that this brief does not cover — then default to
   the conservative, reversible choice and note it; don't block.)

---

## §1 — All decisions resolved (do NOT ask — these were open, now answered 2026-06-21)

There are **no open questions**. The three the earlier draft flagged are now decided by the
maintainer (2026-06-21):

1. **Unifying NAME for "articles + newsletters" → KEEP "Article" for now.** No rename. The
   naming slice of item B is **dropped** (do not change `HOME_STAT_LABELS` / the Database
   label). Revisit only if the maintainer asks later.

2. **Large-data backup destination → SERVER-SIDE PATH, confirmed.** The user picks/types a
   server-side filesystem path (validate: exists + writable + enough free space). Never the
   browser.

3. **Models in the large-data backup → SAME folder backup.** One "large data" backup carries
   wiki dumps + maps + models together (not the separate `.oomodels`). Keep the old
   `.oomodels` endpoints working (Desk lesson) but fold the UI into the one flow.

(Auto-promoting cited discovery origins remains a genuine ethics ruling and is **out of scope**
for this brief — don't touch it.)

---

## §2 — Build queue (features), sequenced

### A. Large-data "Copy to a folder/drive" backup + restore  ⭐ flagship, decided

**Why.** The current `oo-backup-2` is in-memory, **2 GiB-capped, and browser-delivered**
(restore does `await file.read()` → `decrypt_bytes` → `zipfile.ZipFile(io.BytesIO(...))`
with `_MAX_RESTORE_BYTES = 2 GiB`; encrypted create does
`encrypt_bytes(zip_path.read_bytes())` — whole archive in RAM). So it **physically cannot**
carry Wikipedia dumps (enwiki ≈ 20 GB), OSM maps (planet ≈ 72 GB) or model blobs. The
maintainer chose **server-side "Copy to a folder/drive."** This single build resolves the
long-standing rulings: *backups must include wiki dumps*, *backups should optionally include
LLM models*, and *maps in backups*.

**Decision (binding).** A **server-side** backup that STREAMS files (never the browser) into
a **user-chosen destination directory** (e.g. an external drive mounted on the machine):
- Members: `data_dir()/wiki_dumps/`, `data_dir()/osm_regions/`, and the Ollama model store
  (`src/backup/ollama_models.py::default_store()` → `OLLAMA_MODELS` or `~/.ollama/models`).
- Copy file-by-file with `shutil.copyfileobj` (bounded buffer) + a **manifest** + **sha256
  dedup** (skip an unchanged blob across runs).
- These blobs are **public + re-downloadable** ⇒ copied **as-is, NOT whole-file encrypted**
  (that is what makes 100 GB feasible). The encrypted CORPUS backup (`oo-backup-2`) is
  **unchanged** and remains the private-data path.
- **Skip non-`done` downloads** (the "ongoing downloads never backed up" principle — a
  partial file must never ride into a backup).
- **Restore** copies them back **additively**: skip-if-present, **never overwrite a
  differing local file** (content-addressed blobs make this inherent for models; for
  dumps/maps compare by name + sha256).
- A **visible, pausable task-manager job** over the long copy (mirror
  `src/wiki/dumps.py::DumpDownloadManager` / `src/geo/osm_downloads.py::OsmDownloadManager`:
  persisted state under `data_dir`, worker thread, pause via stop-event + persisted cursor,
  resume via re-start, progress done/total, surfaced in `/api/jobs`).
- **Free-disk preflight** before starting; refuse honestly if the destination lacks room.
- **No network** (local disk I/O) ⇒ no airplane gate, BUT it IS a DB-reader of state; it
  does not write the corpus DB.

**Acceptance.**
- A folder backup writes wiki_dumps + osm_regions + models to the chosen dir with a manifest
  listing every file + sha256; a second run re-copies nothing unchanged (dedup proven).
- A partial (`status != done`) download is excluded (test it).
- Restore into a fresh data_dir places the files; restore over an existing data_dir skips
  present files and never clobbers a differing local file.
- The corpus `oo-backup-2` path is untouched (its tests stay green).
- The job appears in `/api/jobs`, can pause/resume.
- Settings "What to back up" tickboxes (Wikipedia dumps / Offline maps / Models) flip from
  the current DISABLED "coming soon" to live, wired to this folder backup. Fold the separate
  `.oomodels` export/restore into this flow (keep the old endpoints working — Desk lesson).
- "What to restore" gains the symmetric maps/wiki/models toggles.

**Files.** New `src/backup/folder_backup.py` (the streamer + manifest + dedup + job),
`src/api/backup_v2.py` (endpoints: start/status/restore for the folder backup; validate the
path), `src/api/jobs.py` (surface + pause/resume the new job kind), `src/static/index.html`
+ `app.js` (the path picker + tickboxes + progress). Reuse `src/backup/ollama_models.py`
(`default_store`, `list_models`), `src/backup/artifact.py::_excluded_inventory` (already
lists `wiki_dumps` + `osm_regions` as excluded/re-downloadable — the manifest should now say
"carried by the folder backup" when that's enabled).

**Honesty.** Manifest lists what IS and ISN'T carried; the UI states the corpus stays in the
encrypted `oo-backup-2` and these large public blobs go to the folder unencrypted +
re-downloadable; preflight + skip-non-done are visible.

---

### B. Newsletter batch-import overhaul (server-side folder job)  ⭐ decided (name in §1.1)

**Why (six maintainer asks, 2026-06-20).** The `.eml` importer must scale to a **folder of
20 GB+**. Current gaps:
1. The file picker can't select a folder.
2. **HTTP 400 at ~1300 files** — ROOT CAUSE: Starlette's `MultiPartParser` default
   `max_files=1000` (600 works, 1300 → "Too many files" 400). No override exists
   (`src/api/ingestion.py::import_newsletters` takes `files: list[UploadFile]`; confirmed no
   `max_files`/`MultiPartParser` override in the tree).
3. No progress bar / ETA.
4. Not in the task manager, not pausable.
5. **Slow while hardware idles** — ROOT CAUSE: `ingest_emails` commits PER MESSAGE
   (fsync/SQLCipher-codec-bound, serialized — not CPU-bound).
6. **Naming** — the DB "article count" is articles AND newsletters; coin a unifying term
   (display-only; §1.1).

**Decision (binding).** A **server-side folder-path import** run as a **pausable background
JOB**, mirroring `DumpDownloadManager` (persisted state under `data_dir`, worker thread,
pause via stop-event + persisted cursor, resume via re-start, progress done/total, surfaced
in `/api/jobs` + pause/resume in `src/api/jobs.py`). The backend ALREADY has
`src/ingest/email.py::ingest_eml_directory()` / `ingest_eml_files()` (currently unused) —
build on them. **Zero network** (local disk read, no airplane gate); it IS a DB-WRITER job
(`kind="import"`, already in the `/api/jobs` arbitration set — it must take the single-writer
gate and arbitrate with collect).

Also: **keep the small-file upload path** (Desk lesson) and **fix its 400 honestly** —
raise the limit by parsing with an explicit `await request.form(max_files=…, max_fields=…)`
(or document the folder path as the route for big sets and cap the upload path with a clear
message). **Perf fix:** batch commits (every N rows, not per-row) in the directory ingest
path; optionally a bounded parse worker pool feeding the single writer.

**Naming: KEEP "Article"** (maintainer 2026-06-21, §1.1). Do NOT rename the display label;
the naming slice is dropped.

**Added — a LIVE "remove imported newsletters" action (closes the "replace the faulty ones"
loop).** The maintainer curated a corpus with faulty `.eml` imports and wants the NEXT clean
import to **replace** them. Restore is additive-only, and the shipped selective-backup
tickbox only excludes newsletters from a *backup* — it does not purge the *live* corpus. So
add a guarded Settings action that runs the SAME logic as
`src/backup/artifact.py::_drop_newsletter_articles` (delete the `newsletters.import.local` +
`mailbox.import.local` source articles AND every dependent row, leave the empty source rows
for re-attach) but on the **live DB** (single-writer gate; a "back up first?" nudge like the
uninstall flow; reversible only via a prior backup — say so). Then the workflow is: remove
faulty → re-import clean (the cleaner `_strip_html` body hashes differently, so it won't
dedup against the junk). Add a test that it deletes only newsletter articles + dependents and
leaves the source rows + non-newsletter articles intact (mirror
`test_backup_newsletter_filter`, on a live session).

**Acceptance.**
- A server-side folder path imports all `.eml` recursively as a background job with
  done/total progress + a rule-of-three ETA, visible in the task manager, pausable/resumable.
- 1300+ files import without a 400 (folder path) and the small-upload path no longer 400s at
  1000 (raised/handled).
- Commits are batched (prove via a timing/commit-count test or a structural assertion).
- All the existing anonymise-at-ingest guarantees hold (recipient never stored, no raw
  retention, tracker-link detox, **N files ⇒ 0 sockets** — keep that invariant test).
- The live "remove imported newsletters" action purges only newsletter articles + dependents
  (source rows kept); a re-import then re-attaches. (No rename — "Article" stays, §1.1.)

**Files.** `src/ingest/email.py` (batch-commit the directory path), new
`src/ingest/import_job.py` (the pausable job manager) or fold into an existing manager
pattern, `src/api/ingestion.py` (folder-path endpoint + fix the upload 400),
`src/api/jobs.py` (surface + pause/resume), frontend (folder-path input + progress + task
manager). Reuse the `newsletters.import.local` source. Cross-link the CONTENT-QUALITY fix
already shipped (`_strip_html` hardening 2026-06-20) — note that already-imported junky
newsletters need a re-import to clean (the cleaner body hashes differently, so it won't
dedup against the junk; this is the maintainer's "replace the faulty ones" path combined
with the §2.A "back up without newsletters" tickbox already shipped).

---

### C. LLM model-download QUEUE + AI-tab models UI rework  (decided, 2026-06-20)

**Why.** Pulling several models at once **overlaps visually + starts them all at once**;
and the Settings → AI model LIST is **poorly displayed**. Two cohesive parts — build
together.

**C1 — Download queue.** Make model pulls a **queued, task-manager-visible job** like wiki
dumps: **one at a time**, the rest queue, with a **CANCEL** action (ollama `/api/pull` is
**not resumable**, so cancel — not pause). The user can queue several and manage them from
the task manager. (Pull already streams real progress via `/api/llm/pull`; wrap it in a job
+ a single-active queue.)

**C2 — AI-tab models UI.** Settings → AI (`data-tab="models"` / `#set-models`,
`index.html:868/999`; the catalog comes from `MODEL_CATALOG` via `/api/llm/models` — the
frontend has no hardcoded list). Make the list **COMPACT**; clicking Pull gives **immediate
visual feedback**; and a pulled model is lifted OUT of the catalog list INTO a **TOP
section** showing per-model **STATUS (Pulling · Queued · Available · Active)** + a progress
bar.

**Acceptance.** Queuing 3 pulls runs them sequentially, each cancellable from the task
manager; the AI tab shows a compact catalog + a top "your models" section with live status +
progress; Pull feedback is instant (button disables + "Queued…/Pulling…"). Honesty: real
bytes/percent only (no fabricated ETA/rate — same rule as dumps); pulls egress over CLEARNET
via the ollama process (disclosed; airplane refuses). `node --check` + a `test_repo_invariants`
test pinning the queue + status section.

**Files.** `src/api/llm.py` (job-wrap the pull; a small single-active queue or reuse the
background-task registry `src/monitoring/tasks.py`), `src/api/jobs.py` (surface model-pull
jobs + cancel), `app.js` (`#set-models` render: compact list + status section + queue),
`index.html`.

---

### D. Advanced-search SORT + FILTER by metadata + a "filtered" indicator  (maintainer: "important")

**Why.** Enables thinner corpus creation: sort/filter articles per language · per date · per
source · alphabetically · broadly per-metadata; and when ANY filter is active show a
**"filtered" indicator on ALL tabs** (same convention as the active search-terms indicator)
so the corpus scope is always visible.

**Decision/scope.** Extend the existing search filter path
(`src/api/main.py:437+` already has `start_date`/`end_date`; the list endpoint orders by
recency). Add: `sort_by` (date | source | title/alphabetical | language) + `sort_dir`;
`language`, `source`/`source_tag` filters (date already present). Surface in the
Advanced-search UI. Add a global "filtered" chip mirroring the search-terms indicator,
driven by whether any filter is active.

**Acceptance.** Each sort/filter returns the correct subset/order (backend tests on an
in-memory corpus); the "filtered" indicator shows on every tab when a filter is active and
clears when reset. No score; ordering is honest metadata, not relevance-magic. Browser-
unverified UI flagged.

**Files.** `src/api/main.py` (search/list params), `src/database/queries.py` (sort/filter),
`app.js` + `index.html` (Advanced-search controls + the filtered indicator),
`test_repo_invariants`.

---

## §3 — Performance & data-quality (from the 8 diagnostic logs, 29k-article / 2.4M-mention / 1 GB corpus)

### E. `trending-windows` per-day mention rollup  ⭐ #1 perf hotspot

**Why.** `/api/insights/trending-windows` is the slowest endpoint at **~20 s idle / ~98 s
under load** and it's POLLED from Home. It is **observed_on-WINDOWED**, so the denormalised
corpus-wide keyword counters (`Keyword.mention_count`/`article_count`) **do NOT apply** —
it GROUP BYs the full mention table per call. The TTL cache helps re-opens but not the cold
cost or the live-scraping case.

**Decision.** Build a **per-day mention rollup** table (e.g. `keyword_day_counts(keyword_id,
day, mention_count, article_count)`) maintained incrementally at index time (the same
delta discipline as the corpus counters in `src/analytics/store.py`), so windowed trending
sums a small indexed per-day table instead of scanning 2.4M mention rows. Migration + boot
self-heal + one-pass backfill (mirror the counter slice in CLAUDE.md). Rewrite
`queries.trending` / `trending_windows` (`src/analytics/queries.py:962/1126`) to read the
rollup; keep byte-identical output for a consistent corpus (a test that compares rollup-based
output to the live GROUP BY, like `test_keyword_counter_queries`). If a full rollup is too
big a slice, a strong interim is a **stale-while-revalidate** guarantee on the Home poll +
`warm_cache` pre-compute (already partly there) — but the rollup is the real fix.

**Acceptance.** trending-windows drops from tens of seconds to sub-second on a large corpus;
output byte-identical to the join for a consistent corpus; counters/rollup proven to match
the live aggregation; no score.

### F. Strip HTML/CSS before keyword extraction (drain the 36.5k `?` unknown-lang bucket)  ⭐ root cause

**Why.** The keyword log's `?` (unknown-language) bucket holds **36,519 keywords** that are
CSS/HTML tokens (`div`, `span`, `max-width`, `font-size`, `font-family`…). The 2026-06-21
stopword batch only **mitigates**; the real root is an **HTML-stripping gap before
extraction**. `.eml` has `_strip_html` (`src/ingest/email.py:76`, hardened 2026-06-20), but
**web-scraped** article content (and/or the extractor input) is leaking markup.

**Decision.** TRACE where the CSS tokens enter: sample `?`-bucket-bearing articles, find
their source (web scrape vs `.eml` vs wiki). Then strip HTML/CSS at the right chokepoint —
most likely ensure the scrape pipeline stores clean text, and/or have
`BaselineExtractor.extract` (`src/analytics/extract.py:534`) drop `<style>`/`<script>`
blocks + tags + unescape entities before tokenising (reuse the `_strip_html` approach). This
shrinks the corpus, speeds every aggregation (they all pay for the inflated 245k/829k…2.4M
counts), and cleans analytics. Apply at index time so a re-index cleans existing rows.

**Acceptance.** New ingests of an HTML/CSS-laden body produce zero CSS-token keywords; a
re-index of a junky article drops them; a test feeds markup and asserts no `div/span/
max-width` keyword survives. No silent content loss (the stored article body is what changes;
keep provenance).

### G. Grow stoplists for `no_stoplist` languages (+ zh/ja note)

**Why.** `no_stoplist` langs (uk/tr/ro/ur/th/cs/ca/fi/hi/et/vi/sk…) leak function-word junk;
zh/ja are unsegmented. The 2026-06-21 batch added conservative high-confidence words +
Greek/Slovenian month vocab. The loop is: read the keyword log's `stopword_candidates`
digest, propose per-language stoplist additions → those languages become "managed" → their
sources can be re-enabled (`src/analytics/managed.py`).

**Decision.** Use `scripts/analyze_keyword_log.py` over the maintainer's exported log
(`?format=zip&per_lang=1000000` now exports the WHOLE corpus). Add the high-confidence
function words per language to `src/analytics/extract.py::_EXTRA_STOPWORD_TEXT` (accented /
unambiguous-grammar rule; **never** content words/homographs). Add native month vocab for
remaining non-European UI locales to `src/timemap/dateextract.py::_MONTHS` where the
date-diagnostics log shows `in_month_vocab=false` low-coverage langs. zh/ja segmentation is a
larger, separate effort — note it, don't fake it.

**Acceptance.** Each added word is filtered (extend `test_dateextract` / the stopword
self-test); content words/homographs proven NOT filtered; the keyword self-test stays green.

### H. translation_coverage + tag_coverage backfill

**Why.** The engine report showed `translation_coverage ≈ 11.8%` and `tag_coverage = 0%` on
the live corpus. Two cheap wins:
- **Tags:** the backfill exists (`POST /api/insights/keyword-tags/backfill`,
  `src/analytics/store.py:118`; UI button at `app.js:6333`) — make sure it's discoverable /
  runs on this corpus (it's forward-only at ingest, so a pre-existing corpus needs the
  backfill). Consider a one-time auto-backfill when the Keywords explorer opens (like
  auto-index #21), honest + bounded.
- **Translation:** run the gap-targeted generator
  (`scripts/generate_wikidata_rings.py --from-log LOG.json`) on a **networked machine**
  (Wikidata is 403 in-sandbox) over the keyword log's `ring_candidates.by_language` digest →
  new rings into `configs/keyword_rings_generated.yml` (VET before commit — first-search-hit
  resolution is ~6% wrong; the guard test `test_shipped_generated_file_is_clean_and_vetted`
  enforces shape). This is a networked-machine step → flag it for the maintainer to run, OR
  hand-curate a small high-confidence expansion of `configs/keyword_equivalents.yml` in the
  meantime (the established pattern).

**Acceptance.** Re-running the engine report after a tag backfill shows tag_coverage > 0; the
ring generator's output passes the vetting guard; no fabricated rings.

### I. Polling-storm sanity check

**Why.** The debug log showed activity+vitals polled ~1281× in 26 min. Adaptive backoff
(`_adaptivePoll`, 5 s→20 s when idle, pause on hidden tab) shipped earlier — **verify it's
actually engaged** on both chrome polls and the standalone `/tasks` page; tighten if a poll
slipped through. Low effort; mostly verification.

### J. Other diagnostic findings (lower priority / known gates — don't lose them)

- **`/api/insights/associations` cold ~6 s** (busiest keyword "important" ≈ 42k mentions) and
  **supergroups cold ~15 s.** Both already have the TTL cache for re-opens; the cold cost is
  inherent whole-corpus co-occurrence. The real lever is the **persisted columnar store** —
  which is **gated on the per-OS httpfs/OpenSSL crypto-extension PACKAGING DECISION** (until
  then the DuckDB engine runs **in-memory**, so it gives no cross-restart gain and the hot
  endpoints lean on the counters). If you can bundle the per-OS httpfs crypto extension
  locally (verified offline, never auto-downloaded — that's the blocker), persisted-encrypted
  columnar becomes available and these accelerate; otherwise leave them on the counters/cache
  and note it. See the DATA-ARCHITECTURE entry in `CLAUDE.md` for the full state.
- **Network preflight: the 50-source sample was all `unreachable`.** This is almost certainly
  the **Tor/airplane population**, not a bug (premium news 403s over Tor are expected, and the
  app boots in airplane mode). Re-check ONLINE before treating it as a regression; surface it
  honestly via the existing transport-aware verdicts; do not "fix" by weakening robots/Tor.
- **HTML-strip ties into §3.F:** the same CSS-leak inflates the corpus the perf items pay for,
  so shipping F first makes E/J cheaper.

---

## §4 — i18n + polish tail (small REMAINING items from shipped slices)

These are the "REMAINING" notes attached to features shipped in PR #420. Each is low-risk;
batch them.

- **Key ×12 the English-fallback strings added this session:** the synthesis WINDOW chrome
  (`#synth-window`), the bulk-QUEUE panel (`.bulk-queue`), the offline-map merged-list
  strings, the backup/restore "What to back up / restore" fieldset labels, the new
  "Download ALL keywords (.zip)" button. (Shutdown/terminal-overlay strings are already ×12.)
  Use the de-tagging convention for any paragraph with inline `<b>/<em>` (drop the cosmetic
  tags so each `<p>` is one text node, then key). Keep `--min 100` green.
- **Offline-map list:** add per-row reorder ↑/↓ (the task manager already has it); the
  monolithic-planet code path is now UI-unreachable (harmless).
- **Bulk QUEUE:** surface the client-side translate/summarize queue in the BACKEND task
  manager too (only the ACTIVE run is in `/api/jobs` today; reuse `src/monitoring/tasks.py`).
- **Unified search:** add **full-text search over downloaded wiki DUMPS** (the standing gap —
  search currently covers FTS-indexed wiki CORPUS articles + watched-page titles, not the
  offline dump files).
- **AI-tab Ollama BINARY installer:** still blocked offline on per-OS installer checksums
  (fabricating them is forbidden). Note as a networked-machine step; the pull/remove/active
  half already works.
- **Launcher / autostart:** optional login-autostart (opt-in, airplane-safe — the maintainer
  expected auto-launch on boot; don't add silently). Make the protected systemd Ollama store
  exportable via a sudo-helper (out of scope for the models-export fix already shipped, but a
  real follow-up).
- **Consolidate the guided-wizard language step** (now partly redundant with the
  language-first first-launch shipped in #420).
- **Synthesis (low priority):** an optional persisted/saveable synthesis "document" (today
  Copy / Export .md / Open-as-page is the save path); full multi-paragraph prompt-BODY
  localization only if the native-language directive proves insufficient (the output-language
  pin already works — don't translate the tuned English prompt bodies unless evidence says a
  weak model needs it).
- **Bulk queue:** key the queue panel strings ×12 (it ships English-fallback today).

---

## §5 — Verification & PR hygiene checklist (run for every slice)

- [ ] `python3 -m py_compile` on every changed `.py`; `node --check` on every changed JS;
      `bash -n` on shell.
- [ ] `python3 scripts/i18n_report.py --min 100` green; new non-en flagged for native review.
- [ ] Extend `tests/test_repo_invariants.py` (and `test_ui_invariants` for chrome behaviour)
      — a NEW test per slice, proven to FAIL before the change.
- [ ] Honesty audit: no new `*score*` field on any card/signal; caveats visible ×12; airplane
      gating on any network action (no socket while engaged); no fabricated data.
- [ ] CLAUDE.md updated IN THE SAME COMMIT (shipped-log or queue entry).
- [ ] Draft PR onto a freshly-fetched `0.09`; "browser-unverified, needs click-through" where
      applicable; subscribe to PR activity / watch CI.
- [ ] If any external/dated artifact is added, register it in
      `configs/external_artifacts.yml` (the freshness protocol guard fails otherwise).

---

## Appendix — verified code anchors (as of 0.09 @ 237df57)

| Concern | File:symbol |
|---|---|
| Download-job pattern to mirror (pause/resume/queue/persist) | `src/wiki/dumps.py::DumpDownloadManager`, `src/geo/osm_downloads.py::OsmDownloadManager` |
| Jobs aggregation + pause/resume/reorder | `src/api/jobs.py` (`_dump_jobs`:61, `_osm_jobs`:95, `_task_jobs`:188, `/dumps/reorder`:275, `/osm/reorder`:283, `/{job_id}/resume`:329) |
| Background task registry (for AI/bulk visibility) | `src/monitoring/tasks.py` |
| Models backup (.oomodels) to fold into folder backup | `src/backup/ollama_models.py` (`default_store`:79, `list_models`:105, `build_models_archive`:219) |
| Corpus backup (unchanged; in-memory/2 GiB-capped) | `src/backup/artifact.py` (`_WIKI_DUMPS_DIR`:69, `_OSM_DIR`:70, `_excluded_inventory`:171), `src/api/backup_v2.py` |
| `.eml` directory ingest (unused — build the job on it) | `src/ingest/email.py` (`ingest_emails`:318, `ingest_eml_files`:378, `ingest_eml_directory`:403, `_strip_html`:76) |
| Newsletter upload endpoint (the 400-at-1300 path) | `src/api/ingestion.py::import_newsletters`:182 (`files: list[UploadFile]`; no `max_files` override) |
| Trending (windowed; counters don't apply) | `src/analytics/queries.py` (`trending`:962, `trending_windows`:1126); seam `src/analytics/readmodel.py:51/56` |
| Keyword extraction (HTML/CSS strip point) | `src/analytics/extract.py::BaselineExtractor.extract`:534; `_EXTRA_STOPWORD_TEXT` |
| Index-time counter delta discipline (rollup pattern) | `src/analytics/store.py::index_article`:180 |
| Baseline tag backfill | `src/analytics/store.py::backfill_baseline_tags`:118, `POST /api/insights/keyword-tags/backfill` (`src/api/insights.py:1313`) |
| AI / models Settings subtab | `src/static/index.html`:868 (`<button data-tab="models">AI</button>`), :999 (`#set-models`); `app.js`:2863 (`/api/llm/models`), :2932 (`/api/llm/pull`) |
| Search filter/sort path | `src/api/main.py`:437 (`start_date`/`end_date`), search list endpoint |
| Managed-language classification | `src/analytics/managed.py`; `scripts/analyze_keyword_log.py`; `src/timemap/dateextract.py::_MONTHS` |
| Keyword log export (whole corpus) | `src/api/diagnostics.py::keyword_log` (`?format=zip&per_lang=1000000&page=N`) |
| Ring generator (networked-machine) | `scripts/generate_wikidata_rings.py --from-log`, `configs/keyword_rings_generated.yml` |

---

### Suggested order
A (flagship, unblocks the maintainer's curated-DB backup) → B (newsletter folder import, the
20 GB pain) → E + F (the two biggest perf/quality wins, log-proven) → C → D → G/H/I → §4 tail.
Adjust freely; one PR per slice; record every ruling in CLAUDE.md.
