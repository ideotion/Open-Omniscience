# Lessons — reusable findings from shipped work

> **Moved verbatim out of `CLAUDE.md` on 2026-09-07** (maintainer ruling A3(1); proposal
> `docs/design/LEDGER_RESTRUCTURE_PROPOSAL_2026-08-04.md` §4.1, extended by the ruling to
> cover this subsection too). **The move was byte-exact:** everything from the opening
> "Lessons harvested from the shipped log" bullet down to the *A SESSION CLONE IS SHALLOW UNTIL
> PROVEN OTHERWISE* entry is identical to the Session-rituals "Lessons" subsection it came from
> — nothing was summarised, reworded, reordered or dropped. Entries appended AFTER the split
> sit below that block, starting with *A DRIVER IS NOT A TOOLKIT*.
>
> **This file is MANDATORY READING every session**, together with
> [`../../CLAUDE.md`](../../CLAUDE.md) (the non-negotiables, the UI invariants and the
> rituals). Together they are the constitution. Most of what is recorded here was found the
> expensive way, and several entries are about the exact class of change a session is likely
> to be asked to make.
>
> **Appending:** a new reusable lesson or empirical fact is appended HERE per `CLAUDE.md`
> THE PROTOCOL rule (5a)(b), alongside its verbatim entry in
> [`SHIPPED_LOG.md`](SHIPPED_LOG.md) and its row in [`shipped.csv`](shipped.csv).
>
> **Eight more lessons are NOT here yet.** They were recorded in the Open queue by the
> sessions that earned them and could not be moved verbatim on 2026-09-07 without editing
> cross-references into an entry that must stay — the finding, the eight titles and the
> options are the last entry in [`OPEN_QUEUE.md`](OPEN_QUEUE.md), awaiting a ruling. Until
> that ruling lands, read them there: they are lessons, and this file is otherwise the
> complete set.

- **Lessons harvested from the shipped log (the reusable ones; full context in
  `docs/ledger/SHIPPED_LOG.md` + git history):**
  - **GitHub release assets carry an ATTESTED `digest: sha256:…` field:** to verify a
    downloaded installer/binary WITHOUT fabricating a checksum (a §0.5 non-negotiable),
    fetch the `releases/latest` JSON, read the asset's own `digest`, and verify the
    downloaded bytes against it; refuse on mismatch OR when no digest is attested. This
    resolved the long-standing "we can't fabricate per-OS Ollama checksums" blocker
    (the in-app Ollama binary installer, `src/llm/installer.py`, 2026-06-30).
  - **SQLCipher codec column-order PERF TRAP:** a SQL join from `keyword_mentions`
    to `articles` for ONE small column drags whole ~35 KB article rows through the
    SQLCipher codec (column order puts `content` before `language`) — measured ~26 s
    of a 32 s wall. Read small denormalisable facts via a COVERING INDEX or a
    one-pass Python map, never that join. Corollary: MEASURE (EXPLAIN QUERY PLAN +
    time on the real encrypted DB) BEFORE adding a drift surface like a per-day
    rollup — a covering index is zero-drift and was the right call for trending.
  - **No-score tests check field NAMES, not `repr()`:** a caveat that legitimately
    says "never a score" trips a naive `repr(out).lower()` substring check. Walk the
    dict KEYS recursively for `score`/`ranking`/etc. (grep `repr(.*).lower()`+score
    before shipping). Cost: a red `test` + `Core-only` lane.
  - **Run mypy in the sandbox:** `pip install mypy==2.1.0` works on py3.11 and
    type-checks CHANGED FILES via their real import closure even without project
    deps. The ratchet is a BLOCKING gate; `py_compile` + `ruff F,B` do NOT catch
    type errors. Run `python3 -m mypy <changed.py>` on every Python change.
    **USE THE PINNED VERSION, AND CHECK THAT IT ACTUALLY CHECKED (2026-08-03, the
    #853 ratchet breach):** the ambient `/root/.local/bin/mypy` is 1.19, which hits
    `src/database/write.py:147: Expected '('` on this tree's py3.13 syntax and then
    prints **"errors prevented further checking"** — it reports 3 stub/syntax errors,
    says nothing about your files, and exits. That reads exactly like a clean run of a
    file with no type errors, so a pre-push check can pass while checking NOTHING; two
    real errors in a brand-new module reached `main` that way, and because the
    maintainer fast-merges, they breached the ratchet on the default branch and
    reddened the next PR rather than their own. Install the pyproject-pinned
    `mypy==2.3.0` into the project venv (`TMPDIR=<repo>/.tmp-pip .venv/bin/python3.13
    -m pip install mypy==2.3.0 types-PyYAML` — TMPDIR per the recorded pip lesson) and
    reproduce the CI command verbatim: `python -m mypy src/`.
    **AMENDED 2026-08-23: THE RATCHET IS GONE — the 2026-08-20 paydown took the
    remaining 127 to 0 and `ci.yml` now runs the plain blocking `python -m mypy src/`,
    so the pass condition is EXIT 0, not a count under a baseline.** Any earlier
    ledger text naming 127 (or the local-reads-126 adjustment) is a record of how the
    number fell, not of what to check. THE TELL survives the change and is now the
    FILE COUNT in `Success: no issues found in N source files` — N is ~482; a run that
    aborted reports 3 stub errors and no success line at all, which still reads like a
    clean check of a file with nothing wrong in it. And when an error IS reported,
    diff against a worktree at the merge-base rather than assuming it is yours; at
    zero, a newer mypy's new diagnostic reddens every PR through no code change, which
    is why the pin is load-bearing.
  - **CI-only tests + the standalone-repro pattern** — **but MEASURE the claim before
    accepting it: on 2026-08-23 `pip install -e .` into the py3.13 `.venv` (TMPDIR in
    the repo) turned 18 "pre-existing" reds across the whole restore/merge family into
    81/81 + 124/124 GREEN, and `cryptography` 50.0.0 installed and imported without the
    pyo3 panic this entry had recorded as a fact.** That matters more than the
    convenience: a baseline diff is blind wherever the baseline is already red, and 13
    of those 18 were in `test_restore_timing_instrumentation.py`, i.e. the file most
    likely to catch a regression in the very function being changed — so "they fail on
    both sides" was worth nothing until they RAN. The dependency chase is six installs
    deep (`bleach` → `cryptography` → `fastapi`/`python-multipart` → `slowapi` →
    `feedparser` → `trafilatura`), which is the tell to stop chasing and install the
    project. Historically: the guarded fetch factory pulls
    in `cryptography` and the ORM pulls `bleach` (often absent) — so endpoint/ORM/fetch
    tests were treated as CI-only. Prove the ALGORITHM
    here with a standalone py3.11 repro against the PURE module (e.g. `parse_csv` /
    `_parse_period`), then let CI run the real test. (`pip install bleach sqlalchemy
    pytest` lets the ORM/store tests run locally; `cryptography` won't.)
  - **A wiring/route test must COMPOSE the actual route** (router prefix + decorator
    path) and match it against the caller — never assert the two strings side by
    side (that passed while a `/api/backup/...` vs `/api/backup/v2/...` mismatch
    404'd in the field).
  - **Literal BOM in source `lstrip`:** use the `"\ufeff"` escape, never a pasted BOM
    char (Edit can't distinguish it; it recurred in `sdmx.py`/`bulk.py`/`fetch.py`).
  - **Tests + timestamps/async writers:** never compare a hardcoded timestamp against
    a real-`now` marker (it flaked by time-of-day); an autouse gate-leak assertion
    must WAIT/drain for the app's own legitimate background writers (the briefing
    refresh daemon) before failing. The macOS "Portability observation" lane is
    observation-only but catches these timing/portability flakes FIRST — investigate
    it before the blocking lane hits the same thing.
  - **`merged ≠ green`:** the maintainer fast-merges PRs even with a red `test` lane,
    so a real failure can persist into the next PR on `0.09` — don't assume a merged
    base is green; a webhook CI-failure on a *merged* SHA may be a stale/out-of-order
    delivery (check the HeadSHA against your branch tip).
  - **DERIVED-ROLLUP SCALING lessons (5A-bis, 2026-07-01, D2/D3/serve):** (a) THE
    DELETE-THEN-REINSERT EPOCH TRAP — `index_article` deletes-then-reinserts an article's
    mentions, so an id-watermark INCREMENTAL rollup (tail = `id > watermark`) DOUBLE-COUNTS
    across ANY re-index/prune (the old contribution stays in the rollup AND the re-inserted
    higher-id rows re-add); guard every derived-append rollup with a CORPUS EPOCH bumped by
    exactly the non-append mutators (re-index/prune/restore), a changed epoch forcing a FULL
    rebuild — never an incremental merge. (b) IN-MEMORY COLUMNAR **DOES** WIN FOR *WINDOWED*
    QUERIES in a long-running process (build-once-serve-many): the earlier "in-memory gives
    no gain over the counters" finding was specific to the corpus-wide `keyword_agg` (the
    Slice-2 counters already win there), NOT the windowed `keyword_daily` rollup the counters
    CAN'T serve — so the persisted store (D1/httpfs) is a DURABILITY win (survive restart / no
    per-process rebuild), not the only path to the windowed speedup. (c) the rollup's summed
    `articles_on_day` is an UPPER BOUND on distinct articles BY STRUCTURE but EXACT today under
    the unique `(keyword_id, article_id)` index (gap 0, parity-tested) — disclose the bound the
    structure guarantees, not the value it happens to yield. (d) new dynamic SQL in
    `columnar.py` trips the BLOCKING bandit B608 gate even with constant fragments + bound
    params — add `# nosec B608 - <reason>` per the merge.py/diagnostics.py convention (ruff
    selects no `S`, so no `# noqa: S608` needed; verify with `pip install bandit==1.9.4` then
    `bandit -r src -ll -q` → exit 0). (e) comparing rollup-served vs live top-N is FLAKY at the
    LIMIT cutoff when mentions TIE (DuckDB vs SQLite order ties differently) — test parity
    ORDER-INSENSITIVELY or with a limit large enough to include every term (no cutoff).
  - **FastAPI streamed JSON** must use compact separators `(",",":")` for byte-parity
    with `JSONResponse`. **Install:** pip unpacks big wheels in `TMPDIR` (=/tmp =
    tmpfs on Qubes) → `Errno 28` even with disk free; point `TMPDIR` at the install
    volume + classify disk-full vs network failures honestly.
  - **A FastAPI `async def` handler runs ON the event loop; only a plain `def`
    handler gets the threadpool (2026-07-02, field report "stuck on Previewing… for
    an hour").** So heavy SYNCHRONOUS work inside an `async def` (decrypt a GB, copy
    the live corpus, run the merge) freezes the ENTIRE single-worker server for its
    whole duration — every other request (task manager, polls, the UI) stalls, and the
    app looks hung. The restore preview/commit were exactly this (`restore_preview` did
    a full corpus-copy + dry-run merge on the loop). FIX = `run_in_threadpool(...)` the
    blocking body (extract a `_*_sync` helper), or make the handler `def`. This is the
    SAME single-worker-freeze family as the unlock-blocking + task-manager-never-loads
    bugs: never do multi-second synchronous work on the event loop.
  - **STOPLIST ARCHITECTURE — the safe mental model for adding stopwords (2026-07-01,
    #525/#528/#530):** two channels with OPPOSITE collision behaviour. (a) `global_stopwords()`
    (`src/analytics/extract.py`) = `_EXTRA_STOPWORDS` ∪ English `default_stopwords` ∪
    `get_stopwords(en)` ∪ `get_stopwords(fr)` = LANGUAGE-AGNOSTIC → collision-PRONE: a word
    here hides the same spelling in EVERY corpus language, so it needs cross-language review
    (NEVER globalise a word that is content elsewhere — e.g. English "content" = French
    "happy"; use the plural "comments" not fr "comment"=how). Latin additions want
    length≥4/accented-only. (b) the SCOPED channel (`StopwordsManager.scoped_stopwords` =
    the vendored `configs/stopwords_iso/*.txt` + the in-code `CURATED_SCOPED_STOPWORDS`
    [temporal] + `PUBLISHING_BOILERPLATE_SCOPED` in `src/services/stopwords.py`) is
    LANGUAGE-SCOPED → collision-FREE by construction, so a FULL per-language list drops in
    freely. GOTCHA: en/fr take the `language_stopwords` branch in `get_stopwords`, so the
    scoped channel does NOT reach en/fr — an English addition MUST go in `language_stopwords`
    (= globalised, collision-checked). So: distinct-script or non-en/fr → scoped (free);
    en/fr, or anything you deliberately want global → `language_stopwords`. `build_stopwords.py`
    regenerates the `.txt` (offline; `stopwordsiso` bundles the data) — hand edits there are
    overwritten, so curated words live in the in-code dicts. sr/bs share BCS (bs aliased to hr).
  - **OPEN-CLASS keyword garbage has NO safe blanket rule (2026-07-01, #530):** function-word
    garbage is solved by stopword lists, but adjectives/common nouns are DUAL-USE (health/policy/
    state are topics AND noise) and there is no POS tagger — a category sweep deletes real topics.
    The honest levers are corpus-statistical DF-ubiquity DETECTION (`analyze_keyword_log.py
    --generic-terms` — propose, human judges, never auto-apply) + a TIGHT English-precedented
    platform/closed-class batch (podcast/newsletter/cookies + indefinite pronouns). Inflected
    generic VERBS (zeigen/voir/finden) are lemmatization territory (P4.3, gated on the eval
    harness), not a surface stoplist. **MEASURE-FIRST:** filter an exported keyword log through
    the CURRENT stoplist before analysing — a log exported before a stoplist change OVERSTATES
    garbage (nearly re-targeted German function words already fixed by #525); the user's real
    exported logs sit in the session scratchpad (`fixed_log.zip`) and are the way to measure a
    batch's true impact (e.g. #530 = 43 rows / 20,747 mentions).
  - **VERIFY-BEFORE-PUSH under fast-merge (2026-07-02, #542→#544):** the maintainer merged a
    date-extractor PR while adversarial verification was still RUNNING — six real defects landed
    on 0.09 and needed a follow-up. Rule: parallel skeptic agents (distinct lenses) must COMPLETE
    and their reproducers must be pinned as tests BEFORE `git push` — "draft PR" is not a review
    gate here. Applied to #545, where two pre-push skeptic rounds each refuted the first cut.
  - **CJK REGEX BOUNDARY FACT (2026-07-02, #545):** ideographs are `\w` in Python `re`, so `\b`
    NEVER fires between an ideograph and an ASCII digit — glued dates ("报道于2024-06-11发布")
    were invisible to the extractor AND the diagnostics probe (field coverage undercounted).
    Fix = explicit digit-safe lookarounds (`(?<!\d)(?<![A-Za-z_])`) that block the same ASCII
    neighbours `\b` blocked; keep the digit rule for ALL scripts (never carve a date out of a
    longer numeral). COROLLARY lockstep rule: every extractor vocabulary/pattern gain lands in
    `datediag.py` the SAME commit, or the probe reports phantom gaps.
  - **SQLite EXPLAIN QUERY PLAN scan classification (2026-07-02, PR #567, recursive-log #3):**
    SQLite marks BOTH a bare table scan AND an index-only scan with the word `SCAN` — a
    `SCAN <table> USING [COVERING] INDEX …` is HEALTHY (index-only), and the only scaling
    smell is a bare `SCAN <table>` with no `USING`. A slow-query/EXPLAIN diagnostic that
    flags every `SCAN` cries wolf on covering-index scans; classify on the presence of
    `USING`. (`src/monitoring/slowquery.py`.)
  - **A diagnostic log must degrade, never 500 (2026-07-02, PR #567):** the recursive-
    augmentation logs run raw SQL over the live store; a genuinely missing/corrupt table
    (or a non-SQLite backend) must return a structured `{error/skipped}` field, not a
    traceback — wrap each risky query and mark it degraded (StatementTimeout re-raised so
    the deadline still bites). The debug-bundle `_safe()` wrapper does the same at the
    aggregator level so one failing log never aborts the bundle.
  - **ENDPOINT TESTS MUST OVERRIDE get_db, NEVER SEED SessionLocal (2026-07-06, PR #577):**
    an endpoint test that needs seeded data must seed its ISOLATED fixture engine and route
    the handler to it via `app.dependency_overrides[get_db] = lambda: session` (cleaned up in
    a `finally`). NEVER open a raw `SessionLocal()` (the shared process/data_dir DB) and commit
    rows into it — that DB persists across the WHOLE pytest session (conftest binds one
    `OO_DATA_DIR`), so the rows pollute every later test that reads it. A wave-2 test did exactly
    this (committed a `flood` keyword + recent mentions to SessionLocal), reddening 7
    order-dependent trending/translation tests that pass alone. Same merged≠green /
    order-dependent-pollution family as the rollup-serve fix (#572) — **run a FULL-suite health
    check after every fast-merged parallel wave; per-PR CI misses cross-test pollution** because
    the polluter and victim only collide in the combined run.
  - **NO-FABRICATION SKEPTICS MUST ATTACK THE NEGATIVE SPACE (2026-07-09, the #590 Jalali
    fix-forward):** #590's pre-push verification ran 5 skeptic lenses and STILL shipped 3
    fabrication repros, because every lens verified the POSITIVE space (goldens convert exactly,
    gates hold) and none generated SHOULD-BE-EMPTY inputs. For an extractor, a skeptic must
    enumerate per pattern: every alternation member as a WORD-TAIL/fragment (Persian دی ends
    عادی/اقتصادی — month names are substrings of prose), every router FAILURE path (an invalid
    date falling through a claim-on-success router gets re-read by the generic loops under
    another calendar — the fix is CLAIM-ON-ROUTE: consume the span the moment the year says
    Jalali, add only on success), and every order-ambiguous form (day-first digits with a
    Jalali-range year: skip, never convert on an assumed field order). Each must assert `[]`.
    Corollary: `_MIN_YEAR=1000` means ANY 4-digit year that leaks past a calendar router is
    stored as a plausible medieval CE date — routers over shared numeric shapes are
    fabrication-critical, not recall tweaks.
  - **dbstat is a PER-BUILD SQLite capability — probe it, never assume it (2026-07-09, THETA
    R2 + the #606 macOS fix-forward):** SQLITE_ENABLE_DBSTAT_VTAB is a compile flag: the
    bundled sqlcipher3 NEVER has it ("no such table: dbstat"), Linux stdlib sqlite3 has it,
    and the macOS CI runner's Python build does NOT (the observation lane caught two
    `available is True` assertions red at #606's head SHA — merged≠green). So dbstat-based
    introspection (the P1.5 storage-composition diagnostic) DEGRADES on the encrypted live
    store AND on some plaintext platforms: design it with an honest `{available:false,
    reason}` block + the PRAGMA-level facts (page_size/page_count/freelist_count work
    everywhere), TEST the degrade path as a production path, and gate any
    full-split test on a runtime `_dbstat_available()` probe, not on platform guesses.
  - **NEVER key a cache on `id()` of a per-request object (2026-07-09, THETA R2):** CPython
    recycles addresses — within a TTL window a later request's Session can land on the same
    `id(db)` and hit an entry computed for a DIFFERENT engine (wrong corpus) or a pre-write
    snapshot. A "per-call" key must be a monotonic nonce (can never recur) qualified by the
    BIND; a bounded cache absorbs the one-shot entries. COROLLARY (change-gating rollups): read
    the corpus epoch with a COLUMN query, never `session.get` — the identity map hides another
    connection's bump inside a long-lived session; and gate on the epoch AND an append id tail,
    since ordinary ingest appends without bumping the epoch (a pure epoch gate freezes the
    rollup during collection).
  - **AUTOFLUSH CAN HAND THE WRITE GATE TO A READ — never enter a fetch loop on a DIRTY
    session (2026-07-09, ETA P1.8):** the single-writer gate acquires on FLUSH, and
    SQLAlchemy AUTOFLUSHES dirty state on the next QUERY — so feed bookkeeping written
    BEFORE the collector's article loop meant the loop's first dedup SELECT acquired the
    gate and held it ACROSS the article fetch (a slow Tor fetch + politeness while holding
    the gate = the field's 438 s max single write-wait; a batched loop would hold it across
    the WHOLE feed). Probe empirically — a fake session asserting
    `write_gate.stats()["held"] is False` inside `get()` — and the rule: on gate-wired
    sessions, write bookkeeping AFTER the network loop and COMMIT it before returning so the
    session leaves clean (tests/test_collect_batching.py pins both collector paths + the
    sequential shared-session case).
  - **A "STREAMING" PIPELINE IS ONLY AS BOUNDED AS ITS WORST STAGE + INCREMENTAL-IN-PLACE IS A
    DATA-LOSS FOOTGUN (2026-07-09, the P0.1 backup rework):** (a) the "already streaming"
    volumes+parity path OOMed anyway because `write_parity` loaded EVERY volume into RAM at once
    (N×512 MiB = the whole archive — 11.7 GB on the 10 GB field VM); when a path claims
    bounded-RAM, grep every stage INCLUDING the resilience/erasure/checksum layers for whole-set
    materialization (now banded, bytewise-identical, test-pinned). (b) changed-volume re-emit
    under deterministic per-slice file names would have OVERWRITTEN files the previous complete
    manifest references — an interrupted refresh degrades the last good backup (the rsync
    --inplace hazard); the safe shape is run-unique names for emissions + atomic manifest swap +
    garbage-collection only AFTER finalize. Corollary: file names in a manifest anyone can
    self-sign are traversal-guarded before verify/restore touches the filesystem (a signature
    proves consistency with the EMBEDDED key, never trust). Full entries in SHIPPED_LOG 2026-07-09.
  - **TRAVERSAL-GUARD EVERY NAME→PATH FIELD, ATOMIC-SWAP THE CANONICAL ARTIFACT, AND TEST THE REAL
    PATH (2026-07-10, the post-merge audit of the Round-2 backup wave):** the same backup engine's
    hardening pass (draft PR `claude/zeta-hardening-audit`) shipped WITH a traversal guard on
    `members[].name`/`volumes[].name` — but MISSED the top-level `corpus_member`/`wal_member` and the
    per-member `members[].volumes[]` refs, which restore turned into `staging/<name>` + `unlink` = an
    arbitrary-file DELETE of the LIVE corpus from a self-signed hostile backup. RULE: enumerate EVERY
    manifest/config field that becomes a filesystem path (not just the ones literally named "name")
    and run them ALL through the one guard, on BOTH the verify and restore paths. (b) the crash-safe
    corollary above was stated but the code still wrote the NEW unsigned/parity-less manifest OVER the
    canonical `dest/volumes.json` before signing+parity — a crash/kill/parity-failure in that window
    left an unsigned-complete manifest that `cleanup_cancelled_build` (unsigned⇒disposable) then
    DELETED, previous backup included. Build the fully-signed(+parity) manifest in memory and swap the
    canonical path in ONE atomic `os.replace`; the prior signed manifest must survive until that single
    commit point (an uncaught erasure-code ceiling — GF(2⁸) N+M<256 ≈ 128 GB corpus — must not be able
    to destroy the last good backup). (c) a TEST DOUBLE injected via a parameter (here `corpus_source`)
    BYPASSES the production code path — a fix in the real path (`_live_corpus_source`'s gate check) needs
    a test that drives the real path (monkeypatch `live_db_path`), or the test passes while the fix is
    unexercised. Also: `# nosec`/bandit runs in CI only (not the sandbox venv); the mypy ratchet counts
    import-closure errors, so verify NEW errors are in YOUR files (per-file `mypy <file>` shows 0) before
    trusting a red count. Full entry in SHIPPED_LOG 2026-07-10.
  - **OFFLINE WORD SEGMENTATION IS AN OPTIONAL SEAM, NOT A CORE CHANGE (2026-07-10, B1 segmenter):**
    to add a capability that only some installs have (zh/ja/th segmentation via jieba/janome/pythainlp),
    make it a pip EXTRA with a `segment()->[(word,offset)]|None` seam and a segmenter-aware
    `language_status()`; the whole point is that a core install stays BYTE-IDENTICAL (the `None`
    fallback runs the old tokenizer) — pin BOTH sides: the segmenter-present tests skip when the extra
    is absent, and tests that hardcoded "zh is unsegmented" must be rewritten to assert against the
    source-of-truth (`segmenter_available(lang)`), not a constant, or they flake between environments
    (installed vs not). Three empirical facts worth keeping: (a) CJK words are 2 chars (中国/政策/経済),
    so a segmented path needs `min_len=2` — the Latin 3-char floor drops real words; (b) a segmenter's
    surface tokens CONCATENATE to the input, so janome/pythainlp offsets reconstruct exactly with a
    forward-cursor `text.find(s, cursor)` (jieba yields offsets directly) — and the offset feeds a
    provenance sentence-slice, so validate `text[off:off+len(w)]==w`; (c) a status/gating check must use
    a LIGHTWEIGHT importability probe (`__import__` only), NEVER the heavy loader, or a mere
    `language_status()` call triggers jieba's prefix-dict build. The corpus-level win is that real words
    RECUR across articles (Heaps β drops from ~0.95), which is what makes aggregations meaningful — the
    per-article count is a red herring. Full entry in SHIPPED_LOG 2026-07-10.
  - **A VERDICT MUST MAP TO THE BAR IT ACTUALLY TESTED — a "pass" on a proxy is a fabricated pass
    (2026-07-12, S1 P0-validation kit):** the honesty non-negotiable "never a fabricated pass" applies
    to the VERDICT MAPPING, not only to fabricated numbers. The P0.1 bar IS bounded-RAM-at-scale, so a
    backup that merely COMPLETES at sub-2 GB (where bounded-RAM can't be measured) must report
    `not-measurable-here`, NEVER `pass` — a completion-pass over-reads as "the scale bar was met." Three
    corollaries from the same kit: (a) **AND-gating two thresholds can HIDE a real signal** — a collector
    climb heuristic `ratio>1.5 AND abs>512 MB` misses the OOM signature at a HIGH baseline (a +1.9 GB
    climb on a 4 GB base is only 1.48× → not flagged, and the reason literally said "stayed flat" while
    the numbers rose); use the absolute-rise signal that holds at any baseline and never assert "flat"
    against climbing numbers. (b) **a "scrub"/guard named for a safety property must ENFORCE it** — a
    pass-through `_scrub` no-op gives false assurance; make it a real recursive redaction so the
    endpoint's secret-safety is a PROPERTY, not a convention every future report author must remember.
    (c) **a read-only diagnostic is only as good as its retention** — reading `recent_samples()` over a
    ~2 h-trimmed log can't see a multi-day leak; state the window limit honestly and point at the durable
    signal (memory-guard state + a clean previous-session end), never let the how-to promise more than
    the mechanism delivers. Full entry in SHIPPED_LOG 2026-07-12.
  - **A BACKUP-PATH PROBE THAT STAGES ON THE OPERATOR'S EXTERNAL DRIVE ESCAPES THE data_dir JANITOR —
    give it a swept prefix (2026-07-12, S1 P0.2 restore probe):** a staged-restore probe needs the disk
    room a 100 GB plaintext conversion + working copy demands, so it stages under the operator's DEST
    drive, NOT `data_dir()`. But the boot janitor (`sweep_stale_backup_temps(data_dir)`) and the forensic
    inventory only scan `data_dir`, so on a hard-kill mid-probe the leftover — which for an ENCRYPTED live
    corpus contains a PLAINTEXT staged copy (an at-rest-encryption concern) — is orphaned, unseen, on the
    external drive. Fix: name the probe dir with the engine's swept `.restore-` prefix (so a subsequent
    `write_stream_backup(dest)`'s own sweep reclaims it after the 24 h age guard) + sweep the dest at run
    start + document the manual `.restore-*`-delete recovery. Verify a diagnostic's temp against BOTH
    reclaim paths (janitor scope AND drive), not just its own finally. Full entry in SHIPPED_LOG 2026-07-12.
  - **THE `TestClient(app)` LIFESPAN IS A HEAVYWEIGHT, GLOBAL-STATE FIXTURE — a suspect in subset-order
    pollution (2026-07-12, S1.1 health check):** `with TestClient(app)` runs the app's REAL startup+shutdown
    (engine init/dispose, the airplane socket guard, source seeding), all process-global. A pre-existing
    latent order-dependency exists on 0.2: running `test_a2_job_endpoints.py` before
    `test_diagnostics.py::test_doctor_healthy_returns_zero` (in a subset with a few others) leaves
    `run_doctor()`'s `session_scope().query().count()` failing → rc 1; it REPRODUCES on clean origin/0.2
    and is GREEN in full-suite order, so per-PR CI and the full run never hit it (the #577 family, but
    surfacing only under a non-default subset order). Lesson: when a health check goes red in a SUBSET,
    check clean-base + full-suite order before assuming it's your wave; a lifespan-driven client fixture
    that mutates global state is the first suspect. (Flagged, not fixed — a test-hygiene carry-over.)
  - **REPRODUCER-FIRST FOR GATE-HOLD RIDERS — a REAL hold is not a reason to fix it (2026-07-12, S2.1):**
    a write-gate hold being present is not sufficient to fix it. MEASURE the throughput ceiling
    (GIL-bound Python work gets NO gate-split gain beyond the amortised-fsync overlap — batching already
    collapses N per-article extractions onto ONE commit, so the writes are the small part of the window;
    F13's ~13 ms/article extraction-in-gate is real but splitting `index_article` is high-risk + GIL-marginal)
    and weigh the hot-path risk. And a gate held across a scan can be MANDATORY: the streaming backup's
    `_corpus_facts` MUST run inside the `freeze()` gate because the tamper-evidence article-hash commitment
    has to MATCH the streamed at-rest bytes — moving it out breaks correctness, not just risk (and it is a
    rounding error beside the multi-hour corpus byte stream). F14's autoflush mechanism cannot fire under
    `SessionLocal(autoflush=False)` (a read never flushes a dirty session → the gate is never acquired
    across a fetch). Close a DECLINED rider with the reproducer AS the evidence (a test that pins the
    property or refutes the mechanism), never a hand-wave (tests/test_write_gate_riders.py).
  - **`async def` IS A WHOLE-SERVER FREEZE; THE FIX IS `def` OR `run_in_threadpool` — AND SLOWAPI WORKS ON
    SYNC `def` (2026-07-12, S2.5):** a FastAPI `async def` handler runs ON the single event loop, so heavy
    SYNCHRONOUS DB+SQLCipher-codec work inside it freezes the WHOLE worker for its duration (the
    unlock/restore/task-manager freeze family — /api/articles was async def, measured p95 25 s). Make the
    handler a plain `def` (Starlette runs a `def` route in the threadpool) or `run_in_threadpool` the body;
    `@limiter.limit` (slowapi) DOES work on a sync `def` (verified via the suite: `Depends(get_db)` lifecycle
    + exception handling intact). For FTS search NEVER materialize the whole match to sort+paginate: resolve
    the surviving ids (fts ∩ filters) in the FINAL order via an id-only (+ sort-column) query, then load FULL
    rows for the PAGE only — content is decrypted for ≤limit rows, not the ~20k-match whole set (GAMMA-measured
    50 ms→11 ms warm at 1,776 matches; the win grows with match count). COROLLARY (caught by the S2 full-suite
    run AFTER push, fixed forward): renaming `async def view_article` → `def view_article` broke a SOURCE-INSPECTING
    test that sliced the body via the literal anchor `"async def view_article("` (IndexError). Before any
    `async def`→`def` conversion, grep the TEST tree for the old signature (this is the #283 stale-source-anchor
    family); the durable fix is an async-agnostic anchor (`re.split(r"\n(?:async )?def ", …)`), never a literal
    `async def`. And the local full suite is not optional after a push — it caught this before CI reddened.
  - **`src/api/insights._cached` IS DICT-ONLY — A SCALAR HANDED TO IT IS A SILENT NO-OP (2026-07-12, S2.5
    skeptic):** `_cached` persists + returns ONLY dict payloads (a non-dict `out` falls straight through with
    NO `.set`; a hit is recognised only `if isinstance(hit, dict)`). Handing it a scalar (an int count) makes
    the cache a SILENT no-op — correctness holds (always live/exact, so a freshness-only test passes green) but
    the optimisation does NOTHING. Wrap the scalar in a dict (`{"count": n}`) and pin a HIT with a test that
    asserts the STORE, not just freshness. (Corollary: guarding an endpoint in `guarded_read`/`_deadlined`
    bounds even a whole-table `.distinct().all()` OOM — the statement deadline's SQLite progress handler
    interrupts a runaway scan mid-query, so a full Python materialization can never complete past the deadline;
    the omnibar is the exception — it must never blank, so its guard DEGRADES to an honest empty-with-note
    payload instead of a 429/503.)

  - **A STORE HELPER THAT COMMITS INTERNALLY BREAKS ANY CALLER-OWNED SAVEPOINT (2026-07-17, the
    #691 fix-forward):** #691 wrapped index_article's when/where/who pass in `session.begin_nested()`,
    but `datestore.store_for_article`'s tail `db.commit()` CLOSES the caller's nested-transaction
    context — the NEXT statement raises "Can't operate on closed transaction inside context manager",
    which the pass swallows BY DESIGN → every article WITH a newly-extracted date silently lost its
    places/entities (main red since #691; only ONE suite test has a dated fixture = the misleading
    1-failed/3967-passed signature; a re-index restores the lost field rows). RULE: before wrapping an
    existing helper in `begin_nested`, grep it (and everything it calls) for commit/rollback; a store
    helper must be savepoint-aware (`db.in_nested_transaction()` → flush, else commit) or never own
    the commit at all. COROLLARY: a swallowed-exception design hides exactly this class of failure —
    the standalone repro calling index_article DIRECTLY (tests/test_article_dates.py savepoint test +
    the scratchpad repro) is what surfaced the real exception the production path eats.
  - **A PERSISTED DuckDB store opened via `ATTACH` REJECTS a second in-process handle to the same
    file (2026-07-12, S3.2):** `Binder Error: Unique file handle conflict`. So the in-memory
    rollup-serve model (build a fresh con, swap it in, close the old) CANNOT apply to a persisted
    file — hold ONE connection refreshed IN PLACE under the serve lock (incremental via
    `refresh_keyword_daily`; full rebuild only on an epoch change). The concurrency/incremental/
    durability logic is crypto-independent, so test it with an UNENCRYPTED file-backed duckdb; only
    the encryption is CI/operator-only. (Two plain `connect(file)` handles DO share the in-process
    instance — but the store uses ATTACH.)
  - **Adaptive backup-volume sizing must count PER-MEMBER slices, not `ceil(total/size)`
    (2026-07-12, S3.3; a pre-push skeptic caught it):** the backup slices EACH member independently
    (`_emit_member`), so the real volume count is the SUM of per-member ceils + the manifest/WAL
    members emitted after sizing — `ceil(total/vsize)` undercounts by up to one volume per member
    and could push the real N+M over the GF(2⁸) 255 ceiling → `write_parity` ABORTS (not data-loss
    — the crash-safe finalize survives — but the fix is defeated at scale). Model N exactly the way
    the emit loop emits it. The mandatory skeptic (fed the DIFF + surrounding facts INLINE so it
    never opened the 1382-line file → no context overflow, unlike the recon agents that choked on
    this repo's CLAUDE.md) is what found it.
  - **CI-installs-the-extension is the honest trust path for an offline-verified binary (2026-07-12,
    S3.1):** verify a bundled binary against a SHA-256 pin before `LOAD`; prove the MECHANISM against
    a FIXTURE binary (no real binary/network); ship the registry pins BLANK (empty-pin-stays-in-
    memory, pinned); let a CI lane install the real extension, checksum it IN-LANE, and run the real
    round trip — NEVER promoting the in-lane checksum into `external_artifacts.yml`. DuckDB gotchas
    verified empirically before writing the loader: `allow_unsigned_extensions` is a CONNECT-config
    setting (post-connect `SET` raises); `enable_external_access=False` blocks a file ATTACH
    (Permission Error), so the persisted path omits it (network safety = autoload-off + absolute-path
    LOAD + the airplane guard).
  - **DuckDB derives an extension's INIT SYMBOL from the LOADed file BASENAME split on the FIRST DOT
    (2026-07-13, columnar CI-red fix):** `LOAD '<path>'` computes the C init symbol `<name>_init` where
    `<name>` = `FileSystem::ExtractBaseName(path)` = the basename split on `.` taking `[0]`. So the
    version-dotted bundled name `httpfs-<plat>-v1.5.4.duckdb_extension` derives the BOGUS
    `httpfs-<plat>-v1` -> DuckDB looks for a nonexistent `httpfs-<plat>-v1_init` -> the LOAD fails and
    the persisted-ENCRYPTED store SILENTLY degrades to in-memory (was the "Columnar store" CI lane's red
    on the real-httpfs round-trip `test_ci_encrypted_persisted_round_trip`). FIX = LOAD the already-SHA-
    verified bytes through a per-process temp COPY whose basename is the canonical `httpfs.duckdb_extension`
    (`_canonical_httpfs_path`), so DuckDB derives `httpfs` -> `httpfs_init`. Keep the SHA pin + version
    coupling + traversal guard ON THE REAL FILE (`_verified_httpfs`) BEFORE the copy. SKEPTIC LESSON: a
    cache that verifies the SOURCE each call but hands `LOAD` an un-re-checked cached COPY makes the
    "verify-before-LOAD every call" claim FALSE for the loaded artifact — so key the cache on the verified
    DIGEST (a re-pin to different bytes at the same path invalidates) AND re-hash the COPY against that
    digest before reuse (an in-place tamper is caught, the stale copy never served). Real round-trip is
    CI-ONLY (`extensions.duckdb.org` is egress-blocked in the sandbox), so the "Columnar store" lane is the
    confirmation; the fix removes only the symbol-mangling blocker — D1/D2/D3 persisted-store still need the
    operator to bundle + pin the per-OS binaries (the registry pins ship blank).
  - **A VALUE-BEARING STRING IS ONLY TRANSLATABLE IF ITS KEY IS A FIXED TEMPLATE (2026-07-12, S4.5):**
    a flat `t()` lookup can never translate "3 of 10 articles" — the numbers vary, so it never matches
    a static key. The fix is a COMPOSITE lookup (`OOI18N.tf(template, vars)`): the KEY is a fixed
    `"{done} of {total} articles"` template (keyable ×12), the VALUES are DATA interpolated after
    translation — so the FRAME translates and the DATA does not (the same discipline as translating
    chrome but never data). Server-emitted titles ride the same seam: `Card.title_i18n` (template) +
    `title_vars` (JSON-scalar data), with the English `title` kept as the additive fallback. TWO gotchas:
    (a) a `{placeholder}` with no matching var renders a literal `{x}` — VALIDATE at construction (fail
    loud), never ship a broken frame; (b) adding a new template key to `en.json` ALONE reddens
    `--min 100` (en.json is the canonical 2020-key set; every locale must carry every key) — add the key
    to ALL 12 locale files (translations keep `{term}` verbatim). `t()`-with-an-English-string still needs
    no key (it falls back), but a `tf()` template you WANT translated must exist in the maps.
  - **AN ONBOARDING "PICK YOUR THEMES/COUNTRIES" MUST DEFAULT TO EVERYTHING, AND EMPHASIS ≠ EXCLUSION
    (2026-07-12, S4.7):** the cover-everything ruling ("scraping must cover EACH AND EVERY source;
    ordering ≠ exclusion") means a first-launch theme picker can NOT silently narrow the corpus. Two
    honesty rules: (a) `select_tags` is a FILTER (`Source.tags ILIKE`), so DEFAULT all-selected and treat
    all-or-none as `[]` (no filter = everything); a partial pick is the user's EXPLICIT, reversible focus,
    stated in the UI — never an app-chosen narrowing. (b) for a country/language EMPHASIS use the levers
    that ORDER, never exclude — `country_priority` (a `sort` key in the runner, explicitly "orders first,
    never excludes") and `language_equilibrium` (a cadence weight), NOT `select_languages` (which filters).
    And before calling a settings-write endpoint from a surface that promises "never posts the network,"
    VERIFY the handler has no egress side effect: `PUT /api/scheduler/config` is `save_settings` only (no
    kill-switch clear, no `run_now`), and `exclude_unset=True` means only the fields you send are touched.
  - **ABSORB-THEN-HIDE, BUT AN INTERLEAVED SHARED COMPONENT BLOCKS THE BLIND HIDE (2026-07-12, S4.4):**
    the Desk lesson ("never lose a tool") says retire a surface only once its replacement absorbs every
    capability. When a capability is genuinely missing, PORT it first + add a REGRESSION GUARD on the
    absorption — but the HIDE can still be unsafe: `#ins-explore` interleaves the search bar (retirable)
    with a NON-searchable overview (`#ins-landscape`, must stay) AND a RELOCATABLE shared component
    (`#mm-kit`, moved into the corpus window and back — writing to `#ins-term`/`pickTerm`). A blind
    display:none/removal browser-unverified is the interleaved-shared-helper hazard (passes `node --check`,
    breaks at runtime). So: port the missing piece, guard the absorption, and GATE the actual hide on a
    browser-verified untangle — recorded as a carry-over, not shipped on faith.
  - **A MULTILINGUAL LEXICON MEASURE MUST VERIFY THE TEXT'S SCRIPT — else a mislabelled language yields a
    FABRICATED NEUTRAL, not an honest gap (2026-07-12, S5.2 skeptic):** the whole honesty of a rule-based
    subjectivity/loaded-language scorer rests on "density 0.0 is a REAL measurement (no loaded terms),
    DISTINCT from the unmeasured gap of an unsupported language." That distinction SILENTLY COLLAPSES when
    the scorer trusts the source-asserted `language` (which the project itself treats as unreliable) and
    scans, say, a Cyrillic body against the English lexicon: 0 matches → `density:0.0` reads as "measured,
    clean" when the truth is "wrong lexicon, unmeasurable." Same for unsegmented CJK against a Latin list
    (one giant token, 0 matches). FIX = a cheap SCRIPT GUARD: compute the text's dominant script and the
    lexicon's script; on a mismatch return an honest GAP, never a fabricated 0. The negative-space lens
    (should-be-a-gap inputs) is what surfaces this — a positive-only test suite passes right over it.
  - **A SUPPLY/PHYSICAL PARSER'S "NEVER A PRICE" MUST BE AN ALLOWLIST GUARANTEE, AND GROUPED THOUSANDS ARE A
    FABRICATION TRAP (2026-07-12, S5.1 skeptic):** "this parser never emits a price" cannot rest on a
    unit-string check (it misses €/£/¥/cents/non-USD codes, and trade/consumption measures are reported in
    MONETARY terms) — narrow the MEASURE allowlist to the always-physical measures so a value-denominated
    figure can't enter at all. Two more traps a negative-space pass caught: (a) `float("350,000")` raises →
    a REAL published figure silently becomes a fabricated `value=None` GAP (USGS/OWID print thousands
    separators) — strip US grouping before parsing; (b) a substring currency check false-POSITIVES on
    physical units ("euro"⊂"europium" drops legit Europium supply) — match currency codes/words on a WORD
    BOUNDARY, symbols anywhere. A currency in the value cell REFUSES the row (never a fabricated gap).
  - **"A SINGLE DOWNSTREAM VALIDATOR" IS A LIE IF THE BUILDER PRE-COERCES (2026-07-12, S5.3 skeptic):** a
    write-then-validate file builder that claims `load_X` is the one loud validator is wrong the moment the
    build step coerces or drops before the validator sees the value: `int(2.9)==2` and `int(True)==1` land a
    fat-fingered grade as a clean valid one, and a silent `except: continue` DROPS a judgement the human
    made (the opposite of the "never silently drop" comment beside it). Validate STRICTLY at the build layer
    — reject float/bool/non-numeric LOUDLY, detect a duplicate-key collision (`{2:2, "2":0}` clobbers via
    `str()`), and clean the temp on an `os.replace` failure so a validated `.tmp` is never orphaned.
  - **A CATEGORICAL STATUS THAT CONTAINS A BANNED SCORE-SUBSTRING TRIPS THE NO-SCORE KEY-WALKERS — KEEP IT A
    VALUE, NEVER A KEY (2026-07-13, omnibus source auditor):** the project's recursive no-score guards ban
    `score`/`ranking`/`rating`/`grade` as SUBSTRINGS of dict KEYS (`tests/test_source_quality.py:333`,
    `test_conjunction.py:181`, `test_scale_bench.py:46`), and the status value **`"degraded"` contains
    `"grade"`**. So a `status_counts={"degraded": n}` or a per-region `{...,"degraded":n}` map fails the
    walker even though a categorical status is not a score. Fix: never make such a status a KEY — represent
    per-status tallies as `[{"status": s, "n": n}]` objects (status as a VALUE, safe). NB the CANONICAL
    `assert_no_score_fields` (`src/briefing/card.py`) matches dataclass FIELD names against a specific
    fragment list that does NOT include `grade`, so it wouldn't catch this — but the per-module test-walkers
    DO, so align new diagnostic output to the stricter substring convention (walk your own payload before
    pushing).
  - **A COHORT-RELATIVE `value > p90` TAIL GOES BLIND WHEN MANY MEMBERS ARE BAD — GIVE THE HIGH-CONFIDENCE
    SIGNAL AN ABSOLUTE FLOOR (2026-07-13, omnibus source-auditor skeptic, a HIGH found + hand-verified):**
    `source_quality.robust_stats` p90 is NEAREST-RANK, so with a cohort of 8 where 2 members are bad, p90
    lands at index `round(0.9·7)=6` = a BAD value → `v > p90` is false for the bad members → they escape
    flagging entirely. A cohort-relative auditor therefore reads `healthy` PRECISELY when a whole cohort
    degrades (a scraper regression hitting many same-language sources, or a tiny non-EN cohort mostly of
    consent-walls) — an inversion of its own headline property. Fix: give the HIGH-CONFIDENCE
    extraction-failure signal (an absolute, article-level pathology rate) an ABSOLUTE floor that fires
    independent of the source cohort — but ONLY that signal, NEVER the style-ambiguous soft criteria (an
    absolute short/outlier floor would flag legitimate terse/atypical prose, breaking the extraction-validity
    reframe). And TEST THE MALIGN DIRECTION: a zero-spread/flat-cohort test only proves the benign side; add
    a "genuinely-worst source in a degraded/absent cohort still flags" assertion or the escape ships unseen.
  - **A HAND-PICKED ALEMBIC REVISION ID COLLIDES SILENTLY AND SURFACES AS "CYCLE DETECTED", AND THE SCRIPT
    HEAD IS NOT WHAT A REGEX SCAN SAYS (2026-07-14, omnibus discovery Q4a migration):** the repo's formulaic
    revision ids (`a1b2c3d4e5f6` / `b1c2d3e4f5a6` / …) are effectively EXHAUSTED, so a hand-picked "next"
    id very likely DUPLICATES an existing revision. Alembic then reports a confusing **`Cycle is detected in
    revisions (…)`** (NOT "duplicate id"), and `test_no_model_drift` (which runs `alembic upgrade head`) goes
    red. Two rules: (a) pick a genuinely-RANDOM 12-hex revision id and `grep` the versions dir to confirm it's
    free before writing the file; (b) get the real head from **`python3 -m alembic heads`** (the CLI), NEVER a
    regex scan of `migrations/versions/` — a `revision: str = "…"` typed form + `ScriptDirectory.get_heads()`
    returning the DB STAMP (`5ea842778603`) rather than the script head fooled a manual scan into naming the
    wrong head. The model-column + migration + boot self-heal trio is still the pattern; `test_no_model_drift`
    is the gate that catches a mismatch (run it locally — alembic works in the sandbox even when the full ORM
    doesn't).
  - **A SEAMLESS-ON-TAILS/DEBIAN AUTO-INSTALL IS AUTO-INSTALL-THEN-HONEST-FALLBACK, NEVER A BLIND `sudo apt`
    (2026-07-14, #677 venv fix):** the stdlib `venv`/`ensurepip` ships in a SEPARATE apt package Tails and
    minimal Debian don't preinstall, so `python3 -m venv` fails. The seamless fix installs it automatically —
    but three properties are load-bearing and easy to get wrong: (a) NEVER hang on an unanswerable prompt —
    probe passwordless `sudo -n true` FIRST and only allow a password prompt in an interactive, non-scripted
    session (`--appvm`/`--unattended` both set `UNATTENDED=1`; CI has no TTY), else fall back; (b) REFUSE to
    claim success unless the capability is actually present afterwards (`"$PY" -c 'import ensurepip'` as the
    function's return, so an apt-ran-but-still-missing case falls back, never a false "installed"); (c)
    provide an opt-out (`OO_NO_APT=1`) and degrade to honest guidance when apt is absent (macOS) or elevation
    fails. `set -e` note: call the installer function from an `if` CONDITION so set -e is suspended inside it
    (intermediate `apt`/`sudo` failures return cleanly instead of aborting the whole installer). TEST IT with
    the extract-the-function bash harness (stub `apt-get`/`sudo`/`id`/`$PY`) — the same pattern as
    `test_ollama_store_access_guards_are_noops`. TAILS GROUND-TRUTH (web-verified, never fabricate a Tails
    claim): Tails 6.x = Debian 12 = **Python 3.11** (so a 3.13 interpreter + `python3.13-venv` are NOT in the
    default repos — a versioned-Python install closes the package gap, not the interpreter gap); `sudo`/apt
    need an **administration password** set at the Welcome Screen (OFF by default); apt runs over **Tor**; apt
    packages are **amnesic** unless added via Persistent Storage → Additional Software.
  - **SQLCipher CANNOT DISCOVER `cipher_page_size` FROM THE FILE — a store built at a non-default
    size reads as WRONG-PASSPHRASE unless the opener declares the SAME size right after `PRAGMA
    key` (2026-07-19, the pagesize-bench field failure "the passphrase does not open
    .pagesize-bench-16384.db"):** the maintainer's passphrase was CORRECT — `connect()` just never
    set the page size, so the 4096 target opened (the default) and the 16384 target HMAC-failed.
    `connect()` now takes `cipher_page_size=` for exactly this case. TWO SIBLING TRAPS fixed in the
    same pass, both live-reproduced (sqlcipher3-wheels installs in the sandbox — the encrypted
    paths are NO LONGER unrunnable here): (a) some sqlcipher3 builds return PRAGMA read-backs as
    TEXT (`'16384'`), false-failing an `==` self-verify on a perfect rebuild — always `int()` the
    read-back; (b) a function that ACCEPTS an explicit `passphrase` but opens some of its
    connections via the ambient process key is half-wired — thread the key through EVERY open
    (source + verify + workload), or the explicit-key path fails in ways the in-app path hides.
    And the meta-lesson: "the encrypted path shares the code shape and self-verifies at runtime"
    was the test docstring's exact excuse — the untested branch is where all three bugs lived;
    skip-guarded encrypted tests now pin it (they RUN in CI and in any sandbox via the wheels).
  - **A `session.rollback()` inside a mid-batch failure handler discards EVERY pending
    (uncommitted) object in the transaction, not just the one that raised (2026-07-19, the
    restore-merge re-index perf fix):** a batching loop's failure path must redo the
    ACCUMULATED SURVIVORS one at a time, committed — never just mark the triggering item
    failed and move on (that silently drops every already-staged batch-mate accumulated
    before it). `reindex_all_batch` already encoded this correctly; a sibling rewrite
    (`reindex_articles`) initially missed it — cross-check a new batching implementation
    against the PROVEN reference shape, don't assume a simpler-looking version is
    equivalent. Also: a progress callback wired into only ONE stage of a multi-stage
    pipeline (here, the 14-step table-merge) reads as a HANG once the work moves to the
    next, unreported stage (the post-merge per-article re-index ran silently, single-core,
    for however long it took) — "the UI is frozen on the last number it saw" is a prompt to
    grep for what runs AFTER that last callback, not proof of a stall.
  - **A crash-recovery journal must survive ITS OWN write failures:** the DIAGNOSE-THE-
    DIAGNOSTICS journal (`_write_all_diagnostics_zip`, 2026-07-20) exists to diagnose a
    hard-killed run, but its first cut let an `OSError` on the journal's own
    `write`/`flush` propagate uncaught, aborting the whole bundle — the exact crash
    scenario the journal was built to survive. Any sidecar/telemetry write path added
    for resilience must itself degrade (log + disable, never raise) on failure, or it
    becomes a second single point of failure layered on top of the one it was meant to
    catch. Caught in code review, not by a test. Also: a "the sandbox's own /tmp is
    full" error is a HOST-level condition (confirmed independently outside the
    subagent that hit it first) — never respond to it with an unscoped `rm -rf`
    (flagged as a policy violation this session); it doesn't fix a full disk anyway
    if the culprit is a different filesystem/partition (here: Python site-packages on
    the root volume, not `/tmp` itself), and it can destroy other parallel sessions'
    files sharing the same path.
  - **AN AGGREGATION THAT OMITS ZERO-EVIDENCE ENTRIES MAKES "ABSENT" READ AS "PASSED"
    (2026-07-23, the qualification zero-evidence fix):** `source_audit.per_source_metrics`
    only ever produces a dict entry for a source with >=1 stored article — a source with
    literally NO evidence (a totally-failed trial fetch, or no feed and no prior
    articles) is simply MISSING from the metrics dict, not present with an empty/zero
    value. Downstream code that reads `fails_by_source.get(id, [])` then sees an empty
    list — indistinguishable from "examined and found clean" — and an admission gate
    (`run_qualification_pass`) silently promoted the source to `qualified` on zero
    verification. The fix: explicitly test dict MEMBERSHIP (`id in per`) to separate
    "no evidence to judge" from "judged, nothing bad found", and never let the absent
    case fall through to the same code path as a genuine pass. The general form: any
    aggregation keyed by a `.setdefault`/groupby loop over real observations will have
    this exact trap for any entity that produced ZERO observations — audit every
    `.get(id, [])`/`.get(id, {})` downstream of one for whether "missing" and "present
    but empty" are meant to mean the same thing (they usually aren't).
  - **FIXING A FREE-PASS BUG CAN CREATE A LIVELOCK IF THE SELECTION QUERY HAS NO
    FAIRNESS/ROTATION MECHANISM (2026-07-23, the SAME qualification fix, found by
    adversarial review + reproduced live BEFORE trusting the claim):** a pure
    `ORDER BY id ASC LIMIT n` selection query (`select_unqualified`) silently assumed
    every candidate would EVENTUALLY leave the queue (get stamped one way or the other).
    Once "never silently qualify with zero evidence" was correctly enforced, any
    candidate that can STRUCTURALLY never produce evidence (here: bulk-generated
    sources with no feed at all, confirmed by grepping the generator script) stays
    `unqualified` forever and — because it is still the oldest untouched row — gets
    RE-SELECTED identically on every future call. Once enough such candidates occupy an
    entire batch window, nothing behind them in id order is EVER reached again, no
    matter how many times the job runs. The fix pattern: log the inconclusive attempt
    (a NEW verdict distinct from the real judged states, never touching the actual
    status) and change the selection ORDER to least-recently-attempted (NULLS FIRST for
    never-tried) instead of pure insertion order — a stuck row rotates out of the way
    after one try instead of permanently occupying the front of the queue. General
    form: whenever a bug fix changes "always removed from a FIFO/id-ordered queue" into
    "sometimes stays in the queue", check whether the queue has ANY rotation/fairness
    mechanism — a fix that is locally correct can convert a working-by-luck queue into
    one that starves on its very first permanently-unresolvable entry. Reproduce the
    EXACT adversarial scenario live (not just reason about it) before trusting a
    claimed defect OR a claimed fix.
  - **A PER-ROW `IntegrityError` HANDLER INSIDE A MULTI-INSERT LOOP MUST ROLL BACK TO A
    SAVEPOINT, NEVER THE WHOLE TRANSACTION (2026-07-23, S2 Library-snapshot recorder,
    caught by re-reading my own code against this exact lesson list before pushing —
    not by an external skeptic this time):** the hourly snapshot recorder loops over
    several metrics, `session.add()`-ing one row per metric inside ONE open
    transaction. A bare `session.flush()` + `except IntegrityError: session.rollback()`
    on a concurrent-writer collision would have discarded EVERY prior metric's
    already-flushed-but-uncommitted insert in the SAME loop iteration, not just the
    colliding one — the identical class of defect the "delete-then-reinsert" and
    "restore-merge re-index" lessons above already name for OTHER call sites. FIX: wrap
    each row's insert in its own SAVEPOINT (`with session.begin_nested(): session.add(...)`)
    so a rollback on that one IntegrityError rolls back only to the savepoint, leaving
    sibling inserts in the same call untouched. PROVE it, don't just assert it: seed a
    pre-existing colliding row for ONE metric and assert every OTHER metric still gets
    recorded in the same call (`test_a_mid_batch_collision_never_discards_sibling_inserts`)
    — a test that merely checks "the function doesn't raise" would pass even with the
    unsafe bare-rollback version.
  - **`scripts/generate_wikidata_rings.py` OVERWRITES its `-o` TARGET — CONFIRMED ON A REAL RUN,
    NOT JUST READ FROM SOURCE (2026-07-23, the 2nd Wikidata ring batch, 168 seeds):** `main()`
    does `args.out.write_text(emit_yaml(rings, ...))` — a full overwrite, never a merge. A run
    must ALWAYS target a fresh file, never the live `configs/keyword_rings_generated.yml`; the
    merge into the live file is a SEPARATE, deliberate append-only TEXT SPLICE (never a full YAML
    round-trip re-serialization, which reformats/reorders the untouched existing rings and buries
    the real diff). A REPEAT-OFFENDER QID can resurface under a DIFFERENT seed string across
    batches (this batch's "translation" independently re-hit the SAME "version, edition or
    translation" bibliographic meta-class the 2026-06-20 batch already dropped under a different
    seed) — the regression-guard test's `dropped` blocklist is what caught it LIVE on the first
    full pytest run, not the manual eyeball; run the test before trusting a hand-vetted merge, not
    just after. Mis-resolution correlates with PROPER-NOUN NAMESPACE COLLISION (a band/journal/
    video-game sharing the concept's name) and TARGET-SPECIFICITY DRIFT (the search API's top hit
    being a real but far narrower related item) — NOT with seed word-count (this batch's 12 drops
    split evenly 6 single-word / 6 multi-word, refuting that naive predictor).
  - **A RESUMABLE JOB'S EXECUTION MODE MUST BE EXPLICITLY RE-SUPPLIED ON RESUME, NEVER LEFT TO A
    DEFAULT (2026-07-23, S3.2 quarantine write step):** `QuarantineJobManager.start()` originally
    only set `self._write` when `_cursor<=0` ("only a fresh run decides the mode"), but `resume()`
    calls `start()` WITHOUT passing `write=` — so a legitimately-paused WRITE-mode run with
    `_cursor==0` (paused before its first batch committed) would have silently resumed in
    DRY-RUN mode, an invisible flip on a data-safety control. Caught by design review, not a
    failing test, BEFORE it shipped. Fix: `start()` always sets the mode unconditionally from its
    own parameter; `resume()` explicitly captures the paused run's mode and re-passes it. General
    rule: any resumable job with more than a cursor (a mode, a scope, a target) needs an explicit
    mode-preservation test — "just re-call start()" is exactly where that extra state quietly drops.
  - **A CACHING BRANCH KEYED ON "IS THE FILTER LIST EMPTY" IS SILENTLY DEFEATED BY AN UNCONDITIONAL
    ADDITION TO THAT SAME LIST (2026-07-23, S3.2 quarantine write step):** `_query_articles`'s
    browse path picks a cheap CACHED total when `filters` (a plain list) is empty, else a live
    `.count()`. Appending an always-on exclusion (the new quarantine condition) directly into
    `filters` would make it never empty again, permanently defeating the cache for the common
    no-other-filter case. Fix: model "always-on" conditions SEPARATELY from the optional filter
    list, and make the cached path itself aware of the always-on condition. Before adding a WHERE
    clause to an existing query builder, check whether it branches its OWN behaviour (caching,
    plan shape) on the filter collection being empty.
  - **A "CAPTURE THE BASELINE FRESH EVERY CALL" DESIGN IS WRONG FOR A RESUMABLE JOB —
    THE BASELINE MUST BE CAPTURED ONCE AND PERSISTED ACROSS EVERY RESUME (2026-07-23,
    S3.3/S3.5 import-time quarantine + report hooks):** the first cut of the
    newsletter-import quarantine hook captured the "before" article-id baseline FRESH
    at the top of every `_run()` invocation, reasoning that a resume's baseline should
    reflect reality at the resume point. This silently DROPPED coverage: a run that
    gets PAUSED before reaching its own success branch never screens the articles it
    already stored, and — because the LATER resume's fresh baseline sits ABOVE those
    already-stored ids — the eventual completion's "new since baseline" scan skips
    them FOREVER, not just for that one resume. The general form: for any per-run
    "what's new since X" computation on a job that can be paused mid-way and resumed
    as a SEPARATE invocation, X must be captured ONCE at the TRUE start of the whole
    logical run and PERSISTED (alongside the cursor) across every resume — never
    recomputed per invocation, or a paused invocation's own contribution becomes
    permanently invisible to the very check meant to cover it. COROLLARY: when a
    baseline capture can FAIL, never fall back to a "safe-looking" default like `0` —
    an unscoped `id > 0` matches every PRE-EXISTING row, not just this run's; use an
    explicit two-state flag ("not yet attempted" vs "attempted and failed, skip this
    run's hook entirely") instead of guessing a numeric fallback. Caught by re-tracing
    the pause/resume interleaving BEFORE push (no external skeptic this slice — same
    scrutiny, done by hand); the fix was STASH-VERIFIED (the old behavior reproduced
    live, the new regression test failed exactly as predicted, then the fix was
    restored and the test passed) rather than merely asserted.
  - **A "the old pattern must be GONE" regression guard checked against the WHOLE
    FILE can produce a FALSE PASS when the new code legitimately reuses the same
    trailing text at a different nesting depth (2026-07-23, S4.1 duty-cycle fix):**
    the first invariant-test draft asserted `"refresh_briefing(session)\n
    except Exception" not in runner` to prove the old synchronous call site was
    removed — but the NEW background-thread version also calls
    `refresh_briefing(session)` immediately followed by an `except Exception:` line
    at the SAME indent (Python's own indentation conventions make the two
    structurally identical once you look only at where a line ends and what the
    very next line starts with, regardless of how deeply the intervening code is
    nested). The assertion therefore passed against BOTH the code it meant to
    reject and the code it meant to accept. Fixed by scoping each "must be gone" /
    "must be present" assertion to the SPECIFIC method body it claims to guard via
    a source split on that method's own `def` line, never a bare whole-file
    substring search when the two things being distinguished can share literal
    text. General form: a regression guard proving something was REMOVED is only
    as strong as the scope it searches.
  - **AN HONEST "resolver error → not-measurable-here" DEGRADE PATH CAN SILENTLY MASK A GENUINE
    BUG IN THE RESOLVER ITSELF (2026-07-23, S5 item 2, the KPI K2 fix):** the K2 resolver read
    `latency.summary()["snappy_bar"]` as a plain float, but the module's REAL, current shape
    nests it as a dict — `float(dict)` raised `TypeError` on EVERY real call. `kpi_snapshot()`'s
    own try/except is exactly the "never a fabricated pass" honesty mechanism (a resolver fault
    degrades to `"not-measurable-here"` rather than crashing the snapshot) — but that same
    mechanism meant the crash was NEVER visible: every call silently read as "no data yet"
    instead of "this metric is broken," and no test caught it because the suite only checked the
    SHAPE of a not-measurable entry, never distinguished "genuinely no data" from "the resolver
    itself is broken." General form: a resolver/adapter reading another module's payload by KEY
    must be tested against that module's REAL, CURRENT shape (a live call, or a fixture that
    matches the actual nesting) — not an assumed/historical shape — and a graceful-degrade
    fallback needs its OWN regression test proving the HAPPY PATH still produces a real value, not
    just that the sad path degrades honestly; otherwise the fallback becomes a permanent hiding
    place for the very bug it was built to survive.
  - **AN "EXCLUSIVE OPERATION" PAUSE MUST GATE EVERY ENTRY POINT THAT CAN START EQUIVALENT WORK,
    NOT JUST THE PRIMARY LOOP (2026-07-24, Session A §4 "import owns the machine" restore
    instrumentation — a mandatory-skeptic-matrix HIGH finding):** a large restore paused
    background collection for its duration via `BackgroundScheduler.stop()`/`.start()` around the
    CONTINUOUS loop, and on that premise claimed "the machine" (an enlarged SQLite cache, all CPU
    cores for the post-merge re-index) — but `run_now()` (wired to a manual "Run now"
    button/endpoint) spawns its own worker thread gated ONLY on `self._active`, with ZERO
    awareness of the pause; a single manual click during the restore silently ran a full
    concurrent collection pass, defeating the isolation the pause existed to provide (not a
    data-loss bug — the single-writer gate still serialised any real write — but a real,
    trivially-triggerable hole in the exact guarantee the surrounding comments claimed). FIX: a
    DEDICATED hold flag (`hold_exclusive()`/`release_exclusive()`) set UNCONDITIONALLY
    (independent of whether the primary loop was even running) and checked by EVERY entry point
    that starts equivalent work, released in a `finally` so a manual trigger works again the
    instant the exclusive operation ends. GENERAL FORM: before trusting "I paused the background
    work" for an exclusivity claim, enumerate every OTHER way that same category of work can be
    triggered (a manual button, a second endpoint, a scheduled-vs-immediate variant) and gate ALL
    of them on the SAME hold — a pause that only stops the primary loop is honest-sounding but
    incomplete, and code built ON TOP of it inherits that incompleteness silently. Found by a
    DEDICATED adversarial concurrency-lens skeptic pass (not by an earlier data-loss/crash-safety
    pass, exactly why the brief mandated a separate lens) — the same pass also caught a related
    MEDIUM (the "own the machine" resource-tuning knobs applied UNCONDITIONALLY regardless of
    whether the pause actually confirmed exclusivity; fixed by gating them on the pause's own
    success) and a data-loss-lens pass caught a third MEDIUM (the all-cores worker count had NO
    upper bound, unlike the everyday default's cap; fixed with a separate, higher-but-still-finite
    ceiling for the exclusive path).
  - **A CLASS METHOD NAMED `list` SHADOWS THE BUILTIN `list` FOR EVERY LATER-DECLARED ANNOTATION
    IN THE SAME CLASS BODY (2026-07-24, C11 throughput-brief slice, wiring segmented downloads
    into the wiki-dump/OSM managers):** `DumpDownloadManager`/`OsmDownloadManager` each already
    define a method named `list(self) -> list[dict]:`; adding a NEW keyword param typed
    `mirrors: list[str] | None = None` to a method declared FURTHER DOWN the same class raised a
    genuinely confusing mypy error ("Function ... .list is not valid as a type") — confirmed via
    a minimal repro (`class Foo: def list(self)->list[dict]: ...; def bar(self, x:
    list[str]|None=None): ...`). Python class-body scoping means the method's own NAME becomes
    the nearest binding for that identifier for every annotation textually AFTER it in the class,
    shadowing the builtin. FIX = use `collections.abc.Sequence[str]` for the new parameter instead
    of `list[str]` — the general lesson: when a class defines a method whose name collides with a
    builtin type name (`list`/`dict`/`set`/`type`/…), NEVER trust `list[...]`/`dict[...]`
    annotations declared later in that same class; reach for the `collections.abc` equivalent, or
    rename one of the two.
  - **A QUALITY GATE THAT ONLY CATCHES INVENTION LICENSES SILENCE — every floor needs its
    negative-space twin, applied ONLY where the evidence exists (2026-07-29, the perception
    eval gate):** `perception_extract.gate_languages_from_report` failed a language only on
    `hallucination_rate > MAX`, and `hallucination_rate = fp/(tp+fp) if (tp+fp) else None` —
    so an extractor returning NOTHING scored `tp+fp==0` → rate `None` → never failed → was
    **licensed for every language**. Verified live against the real harness: a null extractor
    cleared all 13 gold languages before the fix and fails all 13 after. THE SYMMETRIC TRAP the
    obvious fix walks into: adding a blanket recall floor would fail the NINE `where`-only gold
    languages on `who`/`when` — fields they were never tested on — and **a fabricated FAIL is
    exactly as dishonest as the fabricated pass**. So gate each floor on its own denominator:
    apply the recall floor only where `recall is not None` (⟺ `n_gold > 0`) and the
    hallucination floor only where `rate is not None` (⟺ `n_pred > 0`). Corollary found in the
    same pass: a report row with NO field metrics at all returned `{"active": True, "reason":
    "cleared the S6.5 harness"}` — a fabricated pass on literally zero evidence; that needs a
    THIRD state (`None` = unmeasured), and the third state must stay **epistemic, not
    permissive** — it explains the absence of a measurement, the run decision still refuses.
    General form: for any pass/fail gate over a metric that can be `None`, ask separately what
    `None` means for EACH direction — "nothing to judge" is not "nothing wrong".
  - **A LANGUAGE-BLIND LEXICON MEASUREMENT PUBLISHES A FABRICATED NEUTRAL — and when two modules
    score the same quantity, the honest one is the spec (2026-07-29, `awareness/framing.py`):**
    VADER returns compound **0.0** for text it cannot read, which is *indistinguishable* from a
    genuinely neutral English sentence (verified live: fr/ru/zh news bodies all score exactly
    0.0). `compare_framing` ran it ungated across every language, so EVERY non-English outlet
    published `tone_label: "neutral"` as a measured value — while its sibling
    `analytics/sentiment.py:55` had refused exactly this for months with the reason written in a
    comment. TWO PROCESS POINTS worth more than the fix: (a) **the design doc's cited line was
    unreachable dead code** (`avg = ... if tones else 0.0`, guarded by an earlier `if not
    articles: continue`) — patching the cited line would have shipped a "fix" that changed
    nothing, so re-derive a defect's mechanism from the code before patching the line a report
    names; (b) turning a fabricated value into an honest `None` is never a one-file change —
    grep every consumer, because `producers.framing_split`'s `sorted(key=lambda f:
    f["avg_tone"])` would have raised `TypeError` on the first `None` and silently blanked the
    producer. Ship the gap WITH its denominator (`tone_articles`/`tone_unmeasured` per outlet)
    so "no tone" reads as *unmeasured*, never as *neutral*.
  - **A FIX RECORDED IN THE LEDGER DOES NOT PROPAGATE ITSELF TO A NEWER SIBLING MODULE
    (2026-07-29, the vLLM install TMPDIR recurrence):** CLAUDE.md:519-520 already carried "pip
    unpacks big wheels in TMPDIR (=/tmp = tmpfs on Qubes) → Errno 28 even with disk free; point
    TMPDIR at the install volume", fixed in `install.sh:pip_install` — but `vllm_lifecycle.py`
    was written later, ran `pip install vllm` through a bare `Popen` with **no `env=`**, and
    pulls wheels an order of magnitude larger. So when adding a NEW subprocess/install path,
    grep the Lessons list for the operation class (pip, subprocess, SQLite writes) rather than
    trusting that a past fix is structural. Two design points the recurrence clarified: derive
    the temp dir from the **install target** (`venv_dir().parent`), not `data_dir()` — an env
    override can put the venv on an unrelated volume, and same-volume is the property that makes
    a measured free-disk figure real; and the ledger entry's *second* half ("classify disk-full
    vs network failures honestly") is as load-bearing as the first — a bare "exit code 1" sends
    the operator hunting the wrong thing. Diverging from the precedent is fine when the
    divergence is verified: `install.sh` KEEPS its build dir, this one deletes it, safe because
    pip's resumable cache is `$XDG_CACHE_HOME/pip` (checked with `pip cache dir`), not TMPDIR.
  - **THE SINGLE-WRITER GATE ALREADY COVERS BULK `session.execute(insert()/update()/delete())` —
    NOT JUST ORM `session.add()` (2026-07-24, C13 throughput-brief slice, batching keyword-mention
    inserts):** before restructuring `index_article`'s per-term loop from N `session.add(KeywordMention(...))`
    calls into ONE `session.execute(insert(KeywordMention), rows)` SQLAlchemy 2.0 "ORM Bulk INSERT"
    call, the write gate's own coverage needed re-confirming — a bulk `insert()`/`update()`/`delete()`
    statement does NOT flow through the ORM unit-of-work's `before_flush` hook the gate's
    `_on_before_flush` listener attaches to. `src/database/writer.py`'s OWN docstring already
    documents the answer: it ALSO attaches a `do_orm_execute` listener specifically to catch this
    class of bulk DML, so no additional gate-wiring was needed. General form: before assuming a new
    write pattern needs its own gate wiring, read the gate module's own docstring/listener list
    FIRST — a project this write-safety-conscious usually already anticipated the bulk-DML case.
  - **A SHARED ERROR/RENDER PATH FIXED FOR ONE PAYLOAD SHAPE IS RE-BROKEN BY THE NEXT SIBLING
    SHAPE — AND THE SAME COMMIT CAN DO IT (2026-07-29, the vLLM-install 409):**
    `app.js:_apiErrorMessage` was written to abolish `"[object Object]"` from a Pydantic 422
    `detail` ARRAY, and its own comment says the fix "must not be scoped narrowly to one
    endpoint". A later change then introduced the FIRST dict-valued `detail=` in the whole API
    (a 409 carrying machine-readable preflight warnings) — which is truthy, so it fell past the
    `Array.isArray` branch, was returned AS AN OBJECT, and `new Error(obj).message` rendered the
    exact string the helper existed to prevent. GENERAL FORM: when a helper branches on a type
    to normalise a payload, enumerate EVERY type that field can now hold (string · array ·
    object · null), not just the one that motivated it — and when you ADD a new shape to a
    field a shared helper consumes, the helper is part of your change. COROLLARY, and the more
    expensive half here: the endpoint's structured refusal was reachable ONLY through that
    helper, so the frontend had no way to read `acknowledgeable` and always POSTed `{}` — a
    machine-readable refusal with no caller that reads it is a DEAD END, not a feature. Before
    shipping an endpoint that answers "here is why, and here is how to proceed", grep for the
    caller that actually sends the proceed flag; the endpoint tests passed because they
    constructed the request body directly, which is the standing "a test double injected via a
    parameter bypasses the production path" lesson wearing a different hat.
  - **NORMALISE A LANGUAGE CODE BEFORE GATING ON IT — REFUSING TO MEASURE IS NOT THE SAFE
    DIRECTION (2026-07-29, the framing tone gate):** closing a fabricated-neutral hole,
    `_scorable` compared `Article.language` to a bare `"en"`. But `language` is stored RAW from
    trafilatura's `<html lang>` read (`pipeline.py:167`, no normalisation on write) and
    `models.py:307` documents the value space as *e.g. "en", "fr", "en-US"* — so most major
    outlets arrive as `en-US`/`en-GB` and the new gate silently DESTROYED a correct, measurable
    tone, on the very surface the fix was meant to make honest. The repo already had
    `analytics.managed.normalize_lang` at 24 call sites (store-raw / normalise-on-read), and a
    sibling module even documents "Mirrors managed.normalize_lang" — the convention existed and
    was simply not reached for. TWO GENERAL RULES: (1) a fix that turns a fabricated value into
    an honest gap needs a NEGATIVE-SPACE TWIN in the same commit — one test that the gap is
    produced, one that a genuinely measurable input still produces a REAL number — because an
    over-tight gate reads as "conservative" while quietly deleting data, and only the second
    test catches it; (2) when two modules publish the same quantity and one falls back to the
    other (here the framing table falls back to `Article.sentiment_score`), they must agree on
    the gate, or the fallback prints a number computed over a different denominator.
  - **AN OPERATION THAT BECOMES SLOW BECAUSE YOU FIXED IT NEEDS ITS CANCEL PATH RE-EXAMINED
    (2026-07-29, the vLLM install):** `run_install_job` checked `ctx.stopping` once per YIELDED
    LINE while `_default_runner` sat in `for line in proc.stdout`, so a silent child was never
    interrupted and nothing ever killed it — live-reproduced (worker still blocked 3 s after
    cancel; returned only when the child finished on its own). Pre-existing, and harmless while
    the install died fast on ENOSPC; the TMPDIR fix turned it into a multi-GB download over
    Tor, i.e. hours of silence, and the wedged job also made the endpoint refuse every retry
    (`if job.status().get("running")`). The job advertised `cancellable=True`, which
    `BackgroundJob`'s own docstring reserves for workers that genuinely stop early — so the fix
    made it true rather than dropping the claim: a pump thread + an idle HEARTBEAT so the stop
    check runs on a schedule + SIGTERM-then-SIGKILL teardown (the module's own `stop()` already
    had that shape). TESTING NOTE that is the whole reason this survived: all 21 existing runner
    doubles were generators yielding lines instantly, so the per-line check always fired; only a
    test driving a REAL subprocess that goes SILENT reproduces it. COROLLARY: a `finally` is not
    a cleanup guarantee — the worker runs on a DAEMON thread, so SIGKILL, OOM and the app's own
    SIGTERM shutdown all skip it; moving a multi-GB scratch area off the OS-cleared `/tmp` onto
    permanent disk therefore needs a sweep-at-start and a forensics entry, or it becomes
    invisible orphaned storage (the recorded P0.2 swept-prefix lesson, in a new subsystem).
  - **A BASELINE DIFF IS BLIND WHERE THE BASELINE IS ALREADY RED — AN ENVIRONMENTALLY-FAILING
    TEST MASKS A GENUINE NEW FAILURE IN THE SAME TEST (2026-07-29, the option-(a) merge change):**
    the established discipline (run the suite against clean `main`, diff the failure SETS, ship
    only on "zero introduced") reported byte-identical 435/435 — and CI then failed on three real
    regressions. The diff compares NAMES, so a test that is already failing locally for an
    environmental reason cannot ever appear as "introduced", no matter how badly the change breaks
    it: `test_merge_symmetry` was red in both runs (for different reasons each side) and
    `test_t5_round_trips_preserve_content` errored on a fixture that needs a full env. THE FIX IS
    CHEAP AND WAS AVAILABLE ALL ALONG: the whole `test_db_reliability_torture.py` suite runs here
    with `PYTHONPATH=<repo>` (its `_run` helper shells out to `tests/torture_helper.py`, which
    needs `src` importable — nothing else was missing; 11/11 pass). So: before trusting a
    zero-introduced diff, LIST the already-red tests that touch the code you changed and try to
    make them runnable — a name-diff is evidence only about tests that actually execute. Corollary
    when a genuinely-red-everywhere assertion blocks a new test: verify the count against CLEAN src
    (stash `src/`, keep the test) and assert only the portable property — here "every imported
    article reaches the re-index", never `failed == 0`, which pins the environment rather than the
    behaviour.
  - **SQLite SPILLS DIRTY PAGES AS THE CACHE FILLS — an open transaction does NOT pin them,
    so `cache_size` bounds merge memory and transaction length does not (2026-08-03, the
    import cache regression):** the 2026-07-30 "scale the import cache to RAM" rule was built
    on the opposite belief, written into its own comment ("pages dirtied early cannot be
    evicted until the final COMMIT … closer to a floor on residency than a ceiling"), and that
    belief is FALSE. Measured directly (encrypted, WAL, page_size 16384, the merge's own
    INSERT..SELECT-with-NOT-EXISTS shape, 1 GB incoming): cache 2048/989/512/256/64/32 MiB →
    RSS held 2042/2026/1545/1286/1093/1060 MiB, with the balance spilled to the file DURING the
    open transaction (96 MB spilled at 989 MiB of cache, 984 MB at 32 MiB). So the cache is a
    RESIDENCY DIAL, not a throughput lever — and the old rule turned it UP on exactly the
    machines least able to pay. FIELD COST: a ~35-42 GB corpus merging into a 2.49 GB one on an
    8.3 GB box was handed a 989 MiB cache, drove RSS to 6.4 GB, pinned all 1 GB of swap 55
    minutes in, and spent **15.9 hours inside merge step 3 of 19** without finishing; the same
    code merged 20k-45k-article backups in 17-91 SECONDS. WHY A BIGGER CACHE CANNOT HELP THIS
    SHAPE: the dominant step streams the whole incoming corpus exactly once, so its working set
    is always far larger than any cache and the hit rate is ~0 at every size — cache exists to
    serve re-reads and there are none. TWO COROLLARIES worth as much as the fix: (a) an RSS
    trace that CLIMBS then PLATEAUS and stays flat for hours while writing continues is itself
    proof of a bounded-and-recycling structure, not an accumulator — read the plateau before
    blaming transaction size; (b) the codec is arithmetically NOT the cost here — 35 GB at
    AES-NI speed is ~35 CPU-seconds against 33,925 CPU-seconds observed, so "N GB through the
    SQLCipher codec" is a framing to check with a division before repeating it (I stated it
    myself before doing the arithmetic).
  - **`sqlcipher3.Error` IS NOT A SUBCLASS OF `sqlite3.Error` — every driver-class catch on a
    merge/restore connection is dead code on the encrypted store, i.e. on every real corpus
    (2026-08-03; verified with `issubclass`, and the third recurrence of this family after the
    2026-07-14 `is_locked_error` fix):** `merge_corpus`'s cleanup did
    `with suppress(sqlite3.Error): con.execute("ROLLBACK")`, and that connection comes from the
    raw `connect()` factory — so on an encrypted corpus a failing ROLLBACK was NOT suppressed
    and PROPAGATED FROM INSIDE THE `except` BLOCK, replacing the real failure the operator
    needed to see. It fails routinely: an interrupted statement leaves SQLite having already
    rolled back, so the cleanup ROLLBACK raises "cannot rollback - no transaction is active".
    RULE: in the backup/merge chain, a cleanup path suppresses `Exception`, never a driver
    class; and where an outcome must be recognised across drivers, key on YOUR OWN flag set
    before the call, never on the exception type (`_step_watch`'s `stopped[0]`).
  - **A SINGLE SQL STATEMENT IS A BLIND SPOT FOR BOTH PROGRESS AND STOP — the VDBE progress
    handler is the way in (2026-08-03):** the merge checked `should_stop` only BETWEEN its 14
    steps, so during the step that actually takes the time (15.9 h in the field) the Stop button
    was inert, ruling 2026-07-29 item 15 notwithstanding, and the run journal's counter could not
    move because step 3 published nothing internally. `con.set_progress_handler(fn, n_ops)` fires
    inside a running statement and **returning non-zero ABORTS it** — measured: at n_ops=1000,
    ~38 callbacks/s on the merge's own INSERT shape (n_ops=100 → ~536/s, too many); the abort
    raises the driver's "interrupted" and the transaction is ALREADY rolled back when it lands.
    Rate-limit the REPORTING but never the stop check (an `Event.is_set()` costs nothing and
    rate-limiting it just adds latency to the one control the operator is waiting on). The tick
    is a LIVENESS signal — elapsed seconds — and must NOT be turned into a percentage or an ETA:
    it counts VM operations, which bear no honest relation to rows remaining.
  - **A MEASUREMENT THAT NEVER TOUCHES DISK WHILE THE RUN IS IN FLIGHT CANNOT DIAGNOSE A RUN
    THAT NEVER FINISHES — the gap is a SINK, not instrumentation (2026-07-31, the import/export
    run journal):** the import path was already well instrumented and every number it produced
    was correct — `StageTimings` accumulates in a call frame, `VolumeBackupManager._progress` is
    a bare in-memory dict, `reindex_rates` is filled by one `stats.update()` *after* the article
    loop exits, and `persist_import_report` is called from exactly one site on the success path.
    So a 686,896-article import that sat on one progress line for seven hours and was then killed
    left **no report at all**, and "stuck or slow?" took manual `ps` sampling over several rounds
    (with the first verdict wrong). Before building more instruments, check whether the existing
    ones ever reach durable storage DURING the operation; if they do not, the fix is a streaming
    sink over what already exists, not new measurements. FOUR SPECIFICS worth keeping: (a) **a
    healthy process pool makes the PARENT near-idle**, indistinguishable from the deadlocked
    case — only the CHILDREN's cumulative CPU (`psutil.Process.cpu_times()` per child, a
    measurement absent repo-wide until now; every existing reading was instantaneous
    `cpu_percent`) separates them, so any "is it working?" signal over pooled work must sample
    children. (b) **a progress-delta rule fabricates a stall on any phase that publishes no
    counter** — `prepare_staged` is 54% of a large import and reports a phase and nothing else,
    so `d_done == 0 ⇒ not moving` would print `moving:false` for ninety minutes of healthy work;
    emit the verdict ONLY when the active phase owns a real counter and two samples both read
    it, and name the counter keys the app ACTUALLY publishes (`reindex_done`/`merge_step` — there
    is no generic `done`/`total` anywhere in the tree, and assuming one blinds every path
    forever). (c) **the absence of a terminal marker IS the evidence, so never write one to mark
    the journal handled** — a boot-time promotion that appends `run_end` makes every crashed run
    read as finished from the first restart; use a distinct event. And do not call it a crash: a
    journal muted mid-run by ENOSPC leaves the identical signature, and the two are not
    distinguishable from the file. (d) **an aborted run still carries a `plan`** (it is computed
    before the commit point), so a renderer that headlines it prints "**686,896 new articles**"
    at the top of a run that committed nothing — branch on outcome FIRST, and surface outcome in
    any listing, because a filename `kind` cannot carry it (`restore-partial-…` splits to kind
    `restore`, identical to a committed one). SAFETY COROLLARY: the journal's own fork discipline
    is load-bearing — `os.register_at_fork` plus a PID guard checked BEFORE the lock, because a
    child blocking on an inherited lock with no owner alive to release it is precisely the
    deadlock the journal exists to diagnose.
  - **AN OPTIONAL-EXTRA REFEREE HAS TWO ABSENCES, AND THEY MUST NOT SHARE A SENTINEL
    (2026-08-11, the translation task on the Core-only lane):** the new translation
    bench judges the output's language with `analytics.langdetect`, whose
    `detect_language()` returns `None` for four different reasons — library absent,
    text too short, low confidence, unsupported language. That conflation is CORRECT
    for a caller that only wants the language, and wrong for one that REPORTS the
    absence: on a core install (py3langid lives in `[analysis]`) every answer landed
    in `unmeasurable`, which reads as "the model's output could not be read" when the
    truth is "this install cannot read anything". Two facts about two different
    things — the text, and the machine — behind one number. Fixed with a public
    `detector_available()` plus a `referee: {available, reason}` block that places the
    blame, and by noting that SPEED is unaffected because it needs no referee: a
    degrade should surrender only what actually depended on the missing thing.
    **THE TEST HALF IS A RECURRENCE**, and the ledger already carried it: the 2026-07-10
    segmenter lesson says to assert against the availability probe, never against an
    assumed environment. I asserted "French answers read as French" and the Core-only
    lane failed it against perfectly correct code. When a check depends on an optional
    extra, the guard skips on the SOURCE OF TRUTH (`detector_available()`), and a
    second guard — which must still RUN without the extra — asserts the honest
    degrade. Reproduce the lane locally before pushing: blocking the import in a
    `builtins.__import__` shim and resetting the module's memoised probe takes two
    minutes and is the difference between finding this and having CI find it.
  - **A DEGRADE SENTINEL MUST NOT SHARE A KEY WITH A REAL MEASUREMENT (2026-07-29,
    `ai_diagnostics._safe`):** the bundle's per-section guard returned
    `{"available": False, "error": ...}` on a crashed probe — and `resolve_backend()`
    legitimately returns `available: False` to mean "the selected backend is unreachable",
    which was the operator's actual state. One key, two meanings: "we measured, it's down" and
    "we never measured" became indistinguishable in `ai.json`, so a hung `nvidia-smi` on one
    machine read as a capability claim about another. Renamed to `section_ok`. GENERAL FORM:
    when adding a field to a payload that is ALSO wrapped by a try/except degrade helper, check
    the sentinel's key set first — this is the K2 lesson (a graceful fallback becoming the
    hiding place for the bug it was built to survive) at the schema level rather than the
    resolver level, and the test that pins it must assert BOTH directions (the happy path still
    publishes a real value; the sad path publishes the sentinel and NOT the measurement key).
  - **THE SAME "LOCAL WINS DEFENDS AN ABSENCE" DEFECT EXISTS PER-COLUMN, AND THE SPLIT
    RUNS ALONG TABLES-VS-COLUMNS (2026-08-10, metadata on duplicate articles):** asked
    whether a redundant article's richer metadata is discarded on import, the measured
    answer was HALF. `temp.map_articles` joins on HASH, so it maps duplicates onto their
    local twin and every per-article CHILD table already attaches — AI summaries and
    translations (`article_analyses`), AI-derived metadata (`ai_keyword`), extracted
    dates, links. What was dropped is the article's own COLUMNS, because a duplicate
    takes the `WHERE NOT EXISTS` path and nothing updated the local row: AI enrichment
    survived and better EXTRACTION did not. Two columns make that more than cosmetic —
    `server_ip`/`ip_observed_at` is a SOCKET-TIME observation no re-index rebuilds and no
    re-fetch recovers (a later fetch reaches a different CDN edge), and `published_at` is
    the better-extractor case exactly, since the date extractor gained CJK/Jalali/relative
    recall over time. FOUR THINGS WORTH KEEPING. (a) The rule is the qualification rule
    one level down: fill a local NULL ("never measured here"), never overwrite a local
    value. (b) **A per-column `COALESCE` is WRONG for columns that are only meaningful
    together** — it adopts an incoming sentiment LABEL onto a local SCORE whenever the
    local label happens to be absent, publishing "negative" beside +0.9, a reading no run
    produced; group such columns under an ANCHOR whose NULL-ness decides the whole group.
    (c) The UPDATE needs a guard naming the same anchors, or every duplicate is rewritten
    to store what it already had — at a ~90% duplicate rate that is a full row write per
    duplicate. (d) **MY OWN PAIR-ATOMICITY TESTS WERE VACUOUS and the mutation check is
    what said so**: with only sentiment set in the fixture, no anchor fired, the guard
    skipped the row entirely, and the assertion passed for a reason unrelated to
    atomicity — a per-column-COALESCE mutant passed all nine tests. The fixture needs an
    UNRELATED adoptable column (an author) purely to make the row eligible, and an
    assertion that it really was updated. COST, measured rather than assumed: +27.8 µs
    per duplicate at field-realistic 22 KB rows (+11.7 µs at 1.8 KB — row size dominates),
    so ~17 s plaintext over the field's ~617k duplicates, ~41 s applying this machine's
    measured 2.4× codec ratio. Note the percentage is the misleading unit here: the same
    measurement reads "+100% of the merge" on a small plaintext fixture whose baseline is
    unrepresentative, and "+31.6%" at realistic row size — the per-duplicate RATE is what
    extrapolates.
  - **A "LOCAL WINS" POLICY MUST NOT DEFEND A NON-JUDGEMENT — and a fixture with an EMPTY
    local side cannot tell the two apart (2026-08-10, qualification across a multi-instance
    import):** the 2026-07-24 fix below made the merge carry the qualification stamp, and it
    was still true a year of field use later that importing a fully-qualified instance's
    backup added ZERO qualified sources. The stamp rides the sources INSERT, guarded by
    `WHERE NOT EXISTS (... m.domain = i.domain)` — and every instance is seeded from the SAME
    catalog, so essentially every incoming domain ALREADY EXISTS locally, takes the
    duplicate path, and keeps its `server_default='unqualified'`. Local-wins was defending a
    row that had never been judged: `status='unqualified'` means NO verdict was reached here,
    so there is nothing to overwrite and adopting is pure information gain. THE FIX is an
    UPDATE gated on `m.status = 'unqualified'` — which is also precisely what keeps the
    dangerous direction closed, since a local `disqualified` can then never be laundered to
    `qualified` by an incoming corpus. TWO THINGS WORTH MORE THAN THE FIX. (a) **Twelve tests
    covered this table and none could see it**, because every one either started from an
    EMPTY local corpus (so all sources take the INSERT path and arrive stamped) or seeded the
    local row as ALREADY JUDGED (so local-wins is the correct answer). The uncovered cell —
    local present but unjudged — is the only one the field actually produces, and it is the
    "a probe's data distribution is part of the lookalike" trap with the FIXTURE'S LOCAL SIDE
    as the varying axis. (b) **Measure every "what did this import contribute" figure against
    the PRE-MERGE state.** A first draft counted "local verdicts kept" after the INSERT, so a
    source the merge had just introduced read as a pre-existing local verdict; caught by the
    tally test, not by review. Same ordering hazard the adopted-set capture was already
    written to avoid — getting it right once in a function does not get it right twice.
  - **AN EXPLICIT COLUMN ALLOWLIST SILENTLY DROPS EVERY COLUMN ADDED AFTER IT — AND A
    `server_default` MAKES THE LOSS INVISIBLE (2026-07-24, source qualification through the
    restore-merge):** `_merge_sources` copies a hardcoded 14-column list, so the three
    qualification-stamp columns added in 2026-07 were never carried. The dangerous part is not
    the omission, it is that `Source.status` has `server_default='unqualified'`: the merged row
    arrives POPULATED with a plausible, legal value, so nothing looks missing — no NULL, no
    error, no empty column in a spot check. A dropped column with a NOT NULL default is
    indistinguishable from genuine data at every layer above the INSERT. GENERAL FORM: when you
    add a column to a model, grep for explicit column lists that copy that table (merge/export/
    ETL/`INSERT ... SELECT`), because they fail OPEN and silently; and when auditing one, compare
    it against the model rather than reading it for plausibility — a 14-column list looks
    complete on its own. COROLLARY, the same bug's second half: a table in NEITHER the
    handled-registry NOR the deliberately-ignored registry lands in a
    "reported-but-not-merged" middle state that READS as intentional in the restore report —
    `source_qualification_attempts` was counted on every restore and copied on none. Any
    handled/ignored pair needs a completeness check that a new table must join one set or the
    other, or the gap presents itself as a feature. DIRECTIONAL LESSON worth more than either:
    the loss inverted a SAFETY property — a `disqualified` source arrived as `unqualified`,
    which is byte-identical to never-judged, so the merge laundered known-bad sources back into
    the trial queue with their backoff ladder reset. When a dropped field encodes a NEGATIVE
    verdict, ask what the default means, not just what was lost; and note that this direction
    was found only by the adversarial pass — both initial readers correctly identified the
    dropped columns and neither noticed the inversion.
  - **ELEMENT `opacity` MAKES A CONTRAST PAIR LIE — score the COMPOSITED colour, not the
    declared one (2026-07-31, the `.ag-cal` calendar-chip field report):** a rule reading
    `background:var(--panel); color:var(--muted); opacity:.6` looks like a muted-on-panel
    pair, and muted-on-panel passes AA on every theme. It is not that pair. Element opacity
    composites the WHOLE element over what is BEHIND it, so the real text pixel is
    `0.6*--muted + 0.4*--panel` while the background pixel stays `--panel` — the dimming eats
    40% of an already-soft pair and contributes nothing to the background it is measured
    against. Measured across all 17 themes: **16 FAILED WCAG AA 4.5:1** (worst 2.25 on Paper);
    only `contrast` passed, which is exactly why the maintainer reported it as broken in light
    AND dark rather than as a light-theme bug like the earlier `--caveat`/`--warn` failures.
    THREE RULES: (a) any contrast check over a rule that sets `opacity` (or sits inside an
    opacity-carrying ancestor) must compute `α*fg + (1-α)*parent_bg` vs `parent_bg`, or it
    scores a pair that never appears on screen; (b) do not fix it by nudging the token — plain
    `--muted` passes once the opacity is gone, but only just (worst 4.56), so prefer a
    dedicated theme-DERIVED token (`--chip-off:color-mix(in srgb, var(--fg) 50%, var(--muted)
    50%)`, worst 5.70) for the same reason `--caveat` exists: a hardcoded hue failed 8/17
    themes; (c) dimming was never the right way to say "off" anyway — the ON state here was
    already carried by an accent background + border, so removing the opacity cost no
    legibility of STATE, and the toggle additionally gained `aria-pressed` so state is not
    colour-only. Corollary for the guard: assert the opacity is ABSENT from the rule (a
    re-added `opacity` silently restores the bug while every declared colour still looks fine).
  - **A BASELINE DIFF MUST PROVE THE HEAD SIDE RAN THE CHANGED TREE — a clean diff from a
    harness that tested the baseline TWICE is indistinguishable from a real pass
    (2026-07-31, the PR-6 verification):** the runner script was
    `cd "$SP/base-wt" && pytest > base.txt` followed by `pytest > head.txt` — and the `cd`
    PERSISTS into the second command, so both sides ran the BASELINE worktree. The diff came
    back "zero introduced, zero gone" and was worthless. THE TELL, and the cheap permanent
    fix: a PR that ADDS tests must show a PASS-COUNT DELTA equal to the tests it adds (here
    4493 -> 4510, exactly the 15 ladder + 2 invariant tests); identical counts on both sides
    of such a PR is proof the head side never ran the change. A failure-NAME diff cannot show
    this — it compares only names, so "no new names" reads the same whether the change is
    clean or was never executed. So assert THREE things, not one: (a) the head run's actual
    cwd (echo it into the log), (b) the pass-count delta matches the tests added, (c) the
    name-diff is empty. This is the same family as the recorded "a baseline diff is blind
    where the baseline is already red" lesson — both are ways a green diff can certify
    nothing — and the same family as "a verdict must map to the bar it actually tested".
    GENERAL FORM: in any two-run comparison harness, the run that is supposed to be
    DIFFERENT must carry a positive, independently-predictable signature of its difference;
    without one, a harness bug that silently makes the two runs identical presents as the
    best possible result. **THIRD WAY THE SAME HARNESS LIES, hit on the very next PR
    (2026-07-31, PR-8): pytest ABORTS the whole run on collection errors**, and this sandbox
    is py3.11 against a py3.13 repo, so ~46 files fail to import. Both sides then finish in
    ~20 s having executed ZERO tests, and the name-diff comes back empty — a perfect-looking
    result from a run that never happened. `--continue-on-collection-errors` is mandatory
    here, and the tell is the same one as the cwd bug: **the totals line has no `passed` in
    it at all**. So the harness must print BOTH sides' full summary lines and the delta, not
    just the diff — a diff over two empty sets is empty.
  - **A "MUST BE GONE" SOURCE GUARD FAILS ON THE COMMENT THAT RECORDS THE REMOVAL
    (2026-07-31, PR-8's AI-subtab guards):** every assertion of the form "this string no
    longer appears in function X" is written next to a comment explaining WHY it was
    removed — and that comment necessarily QUOTES the removed string. The first draft of
    three such guards failed against correct code, on their own explanations. The repo
    already knew this in one place (the hardware-damage guard is deliberately BEHAVIOURAL,
    with a docstring saying a source grep "would also forbid the comments that EXPLAIN why
    the claim is absent") — the generalisation is: a negative source guard must read
    COMMENT-STRIPPED source (drop whole-line `//`, which leaves a `https://` inside a string
    literal untouched), or be behavioural. Do not solve it by rewording the comment: the
    comment is the thing a future session reads before deciding the removal was a mistake.
  - **A SOURCE-EXTRACTING TEST MUST START BRACE-MATCHING AT THE *BODY* BRACE, OR ITS GUARDS
    PASS VACUOUSLY (2026-08-01, Session D S1):** the house pattern for testing `app.js` logic
    is to EXTRACT the function from the real file by name (a re-typed copy would pass while the
    shipped code was broken). The naive extractor takes the first `{` after the function name —
    but `function ooChart(el, seriesList, opts = {})` carries a `{}` in a DEFAULT PARAMETER, so
    depth goes 1→0 immediately and the "body" is the signature alone. Every source-level
    assertion over that empty slice then passes for free. Scan forward until the PARENTHESES
    balance, then take the next `{`. Two sibling forms of the same trap appeared in the same
    session: a slice that runs from a function to the next top-level declaration sweeps in
    unrelated code (an Overview guard asserting "never calls the LLM" was reading 150 lines of
    other functions), and — the expensive one — **`test_commodities_category_subtabs` was
    passing by ACCIDENT for months**: its whole-file `'{initial: "__all"}'` assertion matched
    the HOME families call site, while the commodities code it names passes the shorthand
    `{initial}`. GENERAL FORM: a whole-file substring assertion is only as meaningful as that
    string's UNIQUENESS; a test scoped to one surface must slice to that surface, and when a
    guard fails against code you believe is correct, check whether it was ever testing what it
    claimed before "fixing" the code.
  - **EXTENDING A SERVER-EMITTED STRING THAT IS ITSELF AN i18n KEY SILENTLY UN-TRANSLATES IT
    (2026-08-01, Session D S2):** `ALERT_CAVEAT` is injected into the DOM and translated by the
    i18n walker's EXACT-key lookup, so appending two sentences to it changed the key and every
    non-English locale fell back to English — caught only because a dedicated test pins that key
    across all 12 files. The fix is a RE-KEY, not a new key: pop the old entry, append the
    translated new sentences to each locale's EXISTING (already-reviewed) translation, and write
    it under the new key. Adding the new key while leaving the old one orphans a translation and
    leaves the gate green. Before editing any long server-side constant, grep the locale files
    for its opening words.
  - **`re.split` CONSUMES ITS SEPARATOR — only an EXACT-COVERAGE assertion catches what that
    loses (2026-08-02, Session E S4):** the never-truncate chunker for user-asked summarize/
    translate split sentences on `(?<=[.!?。！？])\s+`. The lookbehind keeps the punctuation, but
    the `\s+` is consumed, so every inter-sentence space vanished and a translation reassembled
    from the parts came back subtly wrong — plausible text, quietly damaged, and invisible to any
    test that checks the parts "look right". Split at `m.end()` (the separator stays with the
    piece before it) and assert the PROPERTY: `"".join(chunk_text(t, n)) == t`, over several
    shapes (paragraphs, punctuation-dense, punctuation-free, CJK, mixed) × several budgets. The
    general form: for any splitter whose output is meant to be reassembled, the test is exact
    reconstruction, never per-piece plausibility.
  - **A FastAPI DEFAULT IS A SENTINEL OBJECT WHEN THE FUNCTION IS CALLED DIRECTLY — AND
    `Query(False)` IS TRUTHY (2026-08-02, Session E S4, caught by CI not by the local run):**
    `Depends(...)`/`Query(...)` defaults are resolved by FASTAPI, so any other caller gets the
    sentinel itself. `_all_diagnostics_members` builds `ai.json` by calling the route
    DIRECTLY, so adding `measure_corpus: bool = Query(False), db: Session = Depends(get_db)`
    to it meant the bundle took the `if measure_corpus:` branch (a `Query` object is truthy!)
    and handed a `Depends` object to a function expecting a Session. The bundle's own
    `_safe()` would have swallowed that into `{"section_ok": False}`, so EVERY bundle would
    have shipped a degraded `ai.json` and nothing would have said so — the degrade wrapper
    becoming the hiding place for the bug, the K2 lesson again. THE RULE: a route that is also
    called directly must have its arguments passed EXPLICITLY at every such call site (the
    file's own `leads_quality(download=False, db=db)` convention), and the guard must be
    BEHAVIOURAL — drive the real member generator and assert the payload is a real report, not
    a sentinel section. A source-level check of the route signature would have passed.
  - **PARSE A VALUE-BEARING PROVENANCE STRING DEFENSIVELY BEFORE EXTENDING IT (2026-08-02,
    Session E S4):** `ArticleAnalysis.prompt_version` is `String(50)` and is NOT just a version —
    the translation TARGET LANGUAGE lives inside it after a colon (`translate-v2:French`), read
    back by `_parse_target_language`. Appending a method suffix (`+chunked-3`) to record that a
    run was chunked would have made the displayed target "French+chunked-3", and a 50-character
    truncation could have cut into the language itself. TWO fixes, both needed: the parser strips
    the suffix, and the WRITER refuses to append when the result would overflow — losing a method
    note is strictly better than corrupting a value. Same family as the i18n-key lesson above:
    before extending any string, find out what already reads it and what else it carries.
  - **A BACKSTOP MAY BE THE ONLY THING GUARDING A PATH — "every real path checks the gate
    itself" IS AN ENUMERATION, AND ENUMERATIONS ARE WRONG (2026-08-01, the AI-install egress
    window):** relaxing the socket-level airplane backstop process-wide was justified in
    writing by "every real fetch path still refuses itself at its own gate — both gates are
    chokepoints the whole app funnels through." Two modules were absent from both:
    `src/monitoring/preflight.py` and `feed_preflight.py` call `EthicalFetcher._guard_target`
    / `_guarded_redirect_get` **directly** instead of `fetch()` (so they never meet the
    `_KILL` check, which lives only in `fetch`/`sitemaps_for`) and use the fetcher's plain
    `requests.Session` rather than a `GuardedSession` (so they never meet that one either).
    The backstop had been their sole protection since it was built — which is precisely what
    a backstop is FOR, and precisely why its removal read as safe. Live-reproduced: an open
    window let a preflight sweep DNS-resolve and HTTP-fetch scraped-source hosts. THREE
    RULES. (a) Before relaxing a catch-all, do not audit the paths you can name — grep for
    callers of the guarded thing's INTERNAL helpers, because a caller that reached past the
    front door is exactly the one your enumeration omits. (b) Scope the relaxation to the
    narrowest axis that still works: here THREAD + single request (`threading.local` entered
    by `GuardedSession.request`), which left the backstop in force for every other thread —
    verified by driving a bare `getaddrinfo` on a second thread. The narrow version was no
    harder to write than the broad one; it was only harder to THINK of. (c) Bind the two
    gates in ONE place — the exemption is entered by the same method that performs the
    app-level check, so a call site cannot opt into one and forget the other. COROLLARY on
    fixing it: also give the bypassed path its own gate (`_KILL` in the two side doors), so
    the docstring's claim becomes true rather than merely re-enforced from above; a DNS
    resolve is itself egress (it hands the resolver the list of sources the operator reads),
    so a test must assert zero RESOLUTIONS, not merely zero HTTP requests. And the sibling
    lesson the same review produced: **a self-closing resource whose only reaper is an HTTP
    status endpoint closes when a browser happens to poll it** — `reap_idle` had exactly one
    caller, so "it closes on its own once the install finishes" (a sentence in the consent
    dialog) held only while a tab was open. If a UI string promises a lifecycle, the
    lifecycle needs a driver the UI does not own.
  - **TWO COMPONENTS THAT EACH HARDCODE A DEFAULT PORT WILL EVENTUALLY WANT THE SAME ONE —
    and the health probe then reports the WRONG DIAGNOSIS (2026-08-02, "installing vLLM on a
    new machine fails"):** `vllm_lifecycle.DEFAULT_PORT = 8000` and `main.py`'s
    `os.getenv("OO_PORT", "8000")` were written years apart and never read together, so
    `vllm serve` could never bind on any machine that finished an install — `OSError(98)
    Address already in use`, reproduced live. THE PART WORTH REMEMBERING IS THE MISREPORT:
    `is_running()` probed `GET /v1/models` on that port, reached THE APP, got a 404 (the app
    has no such route) and concluded "vLLM is down" — 270 of those 404s in one field session,
    logged by the app's own error log as if an external service were flaky. A boolean
    up/down probe cannot distinguish *not started* from *something else is here*, and it will
    confidently answer the wrong one; give it a `port_occupant()`-style third state and let
    `start()` refuse a doomed launch BY NAME instead of spawning a process that cannot bind.
    Two corollaries: DERIVE the second port from the first (`OO_PORT` + 1) rather than
    hardcoding the new value — a hardcoded 8001 re-collides the moment the operator moves the
    app — and make a malformed override fall back to the DERIVATION, never to the old flat
    constant, which would restore the exact bug through the error path. The test reads the
    app's own default out of `main.py` by regex rather than duplicating it, so moving
    `OO_PORT` reddens the test instead of silently passing. **PROCESS NOTE, the reason this
    was diagnosable at all:** the fix that shipped days earlier (the install journal's
    `resolver`/`fallback_fired`/`duration_s`/`package_present`) is what proved the install had
    SUCCEEDED — without it the report "the install fails" would have been investigated as an
    install bug. Instrumentation earns its keep on the first field report that contradicts its
    own headline.
  - **A SELECTION FUNCTION ANSWERS THE QUESTION IT WAS WRITTEN FOR — reading its
    answer for a DIFFERENT question is where the fabrication enters (2026-08-02,
    "the model does not download"):** `resolve_backend()` answers ROUTING — who can
    serve a request right now — so an unreachable backend is correctly disqualified
    and Ollama is the ruled fallback. The default-model plan read that answer as a
    DOWNLOAD target, and on a GPU machine with vLLM installed-but-stopped and Ollama
    absent it named an Ollama tag and queued a pull into a daemon that does not
    exist — while the panel directly above said "This machine will use vLLM",
    because the frontend picked its target from the hardware. The resolver was not
    wrong; the *reuse* was. PROVISIONING asks what the machine will serve with ONCE
    SET UP, where not-running-yet is the normal state, so it must decide from what
    is INSTALLED and fall back to the same hardware rule the other consumer already
    uses — otherwise two notions of "which backend" meet inside one chain and
    disagree. When you reach for an existing decision function, name the question it
    was built to answer and check it is yours; if it is not, derive the second answer
    from the same facts rather than adding a second probe. **SECOND DEFECT, and the
    reason the first was silent:** the endpoint and its ONLY consumer never agreed
    where the answer lives. `_followJob` returns when it sees a top-level `state` that
    is not `"running"`; `/default-model/status` published none on EITHER branch (one
    nested a job under `job`, the other returned a raw queue with no state at all), so
    it polled every three seconds forever and the chain hung — and a poller with no
    terminal condition is indistinguishable from slow work. When a payload feeds a
    follower, the terminal condition is part of the contract; keep a third state
    (`idle` = nothing was ever asked) distinct from success, or a never-started job
    reads as a finished one. **THIRD, cheap and recurring:** a hand-written test
    double of a payload drifts — a two-key resolver stub passed for months while
    omitting every field a caller might read, then failed against *correct* code the
    moment a new field was consulted. Build the double with the payload's own builder
    (`backend._result` here), so a double can never describe a machine that could not
    exist.
  - **A TEST THAT STARTS A REAL WORKER AND NEVER JOINS IT POISONS THE WHOLE PYTEST
    PROCESS — and the bill arrives in a different file thousands of tests later
    (2026-08-02, the Core-only egress-window flake):**
    `test_start_seeds_mirrors_and_checksum_only_on_a_new_entry` was the only test in
    its file that called `start()` — every sibling drives `_download` directly, which
    launches nothing — so it alone needed injected seams, and it had none. It fetched
    for real and left `oo-dump-en:pages-articles` running as a DAEMON for the rest of
    the run (live-reproduced: still alive when the test body ends). The
    egress-window `guard` fixture clears the kill switch during setup, so whenever
    that worker's retry landed in the window it reached a real `socket.connect` —
    and the fixture records into a **process-global** spy and asserts an exact list
    against it. FOUR general rules. (a) Before trusting "the sibling tests are safe,"
    check which API actually LAUNCHES something: `start()` and `_download` are not
    interchangeable, and only one of them needs joining. (b) A test asserting an
    exact list against a process-global patch point is making a claim about the whole
    PROCESS, not about itself — thread-scope the record, but keep foreign calls in a
    `.foreign` list that prints on failure, or a guarded path that genuinely moved a
    fetch onto a worker thread vanishes from the negative-space assertion that exists
    to catch it. (c) When a lane fails intermittently, look for a second workflow run
    on the SAME sha — this repo runs push and pull_request lanes concurrently, which
    is a free A/B that separates a flake from a regression in one lookup (here: one
    pass, one fail, identical commit). (d) READ THE CAPTURED TEARDOWN before
    theorizing: the failing test's own stderr carried a `src.wiki.dumps _default_get`
    traceback — a completely different subsystem naming the culprit outright, while
    every plausible mechanism I could reason out from the failing file was wrong.
  - **A LINE DRAWN ACROSS A HOLE IS A FABRICATED MEASUREMENT — AND THE OBVIOUS GUARD
    AGAINST IT IS INVERTED BY `isFinite(null)` (2026-08-02, honest gaps in the chart
    toolkit):** both renderers in the ONE toolkit bridged holes — `dashChartSvg`
    emitted a single `<polyline>` over every point, `ooChart` coerced `+p.v` and
    lineTo'd unconditionally — which the project's own committed chart framework
    rejects outright ("Render gaps as gaps; mark 'no data' distinctly"), and which
    `ooviz.pathWithGaps` had existed to prevent since it was written, with no caller.
    THE TRAP, found by the test and not by reading: **`isFinite(null)` is `true` and
    `+null` is `0`**, so the natural "keep the finite values" filter keeps a published
    gap as a plotted **zero** — a fabricated measurement, strictly worse than the
    bridged line it hides inside. `ooViz.isMissing` already encoded the right rule.
    THREE general rules. (a) The opposite failure is equally dishonest — a fabricated
    gap invents an outage — so every "it breaks here" test needs an "and it does NOT
    break there" beside it, or an over-eager splitter ships looking conservative.
    (b) Key the gap rule to the series' OWN median cadence rather than a fixed
    duration (one rule then serves hourly counters and annual indicators alike),
    refuse to guess a cadence from fewer than three intervals, and apply it ONLY
    where the axis is a real time axis — on an INDEX axis the spacing claims
    observation order, not elapsed time, so bridging fabricates nothing and the
    output stays byte-identical, which is what bounds the blast radius of a change
    that touches every chart. (c) Write a test's expectation with its OWN explicit
    predicate, never by borrowing the implementation's helper: the first draft of the
    exact-coverage assertion here wrote `isFinite(pts[i].v)` and failed against
    correct code — the trap catching the test written to catch it — and comparing an
    implementation against itself would have proved nothing either way.
  - **A NAMESPACE'S CASING CAN MAKE A WHOLE SUBSYSTEM LOOK DEAD (2026-08-02, the same
    pass):** the 2026-07-28 GUI audit recorded that `ooviz.js`'s primitives were
    "BUILT + TESTED with ZERO call sites", and a first grep here agreed. Both were
    wrong: the namespace is **`ooViz`**, not `ooviz`, and six primitives are wired,
    with `slopeChartSvg`, `smallMultiplesSvg` and `ringDumbbellSvg` already shipping
    on them. A case-sensitive grep for a name you did not read out of the file is not
    evidence of absence — read the export site first. (Same pass: `ooDonut` DOES have
    a slice-count guard, falling back to theme-derived share bars past five, so that
    half of audit finding V-4 is spent too. Recorded so neither is "fixed" twice.)
  - **AN INSTRUMENT ON A HOT PATH IS A LOAD SOURCE — and "durable=False" meant
    "skip the fsync", not "cheap" (2026-08-06, the import that left the app
    unbootable):** PR #878 added a per-statement breadcrumb to diagnose a merge
    step and sent it through `runlog.milestone(durable=False)`. That flag controls
    ONLY whether `fsync` is called; the FILE is chosen by `beat=`, which
    `milestone()` hardcodes to False — so every breadcrumb was appended and
    flushed to the milestone stream, the one the module's own docstring calls
    "never trimmed". The beat file has a 5,760-line ring; the milestone file had
    no ceiling at all. MEASURED, from the operator's two bundles: `run_logs` went
    **11 MB / 76 files → 1,615 MB / 78 files** across one 24 h merge. THE SECOND
    HALF IS WHERE IT BECAME UNRECOVERABLE: `_read_jsonl` loaded a whole journal
    into a list of dicts with no cap, and `promote_incomplete_runs` calls it at
    BOOT, before the unlock screen, over up to 50 files. Parsed JSON costs several
    times its on-disk size, so on a 12.5 GB box with 1 GB of swap the app was
    OOM-killed at startup on every attempt — and an OOM is a SIGKILL, so the
    `except Exception` wrapped around that call could not catch it, and a
    reinstall could not fix it because a reinstall does not touch `data/`. FOUR
    GENERAL RULES. (a) Before putting an event on a per-call path, ask what
    *writes* it, not just what computes it; a flush under a lock per SQL statement
    is a throughput change, not instrumentation. (b) An in-flight breadcrumb wants
    to be a STORE the existing sampler reads (`runlog.statement` → the beat), not
    a write — the beat is already capped, already periodic, and a statement that
    finishes in milliseconds needed no record at all; only one still running at
    the next sample did. (c) "Not trimmed" is a promise about ORDER, never about
    SIZE: any append-only stream whose safety rests on "these events are rare"
    needs that premise ENFORCED (a byte cap, with the forensic-contract events
    exempt so a capped journal never reads as a killed run), because the next
    person to violate it will be as sure as I was. (d) Every reader of an
    on-disk artifact needs a ceiling **independently** of the writer, since the
    oversized file already exists by the time you find out; and a bounded read
    keeps BOTH ends and states the gap, because which end matters depends on the
    question (`run_begin` identifies the run, `run_end` says how it ended) — then
    anything derived by PAIRING events across the gap, like an unmatched
    `stage_begin`, must be published with its basis rather than as a measurement.
    MY OWN PR TEXT CARRIED THE REFUTATION: it claimed "no per-row cost — these are
    bulk statements, a handful per step, not one per article", which is true of
    the six statements in the step I was looking at and false across all 19. I
    wrote a quantitative claim without counting, in the comment right above the
    code that depended on it.
  - **A CONSERVATIVE CONSTANT DESCRIBES A POPULATION — once the population is one, it
    is just a wrong number (2026-08-13, "This model's maximum context length is 2048
    tokens"):** the operator read that as a claim about the model; it was OUR OWN
    `--max-model-len`. `compute_server_args` divides a post-weights budget by
    `_KV_MB_PER_TOKEN = 0.5`, and its own comment said what that is — "a 7B-class fp16
    multi-head figure" — and, in the next breath, that "a grouped-query model (what we
    actually ship) costs ~4x less, so this errs toward a SHORTER context". Erring short
    was CORRECT while eight models of unknown shape could be loaded and a wrong guess
    meant an OOM at startup. It became a defect the day the roster collapsed to one
    model whose `config.json` is on the disk: an assumption about a class you can no
    longer be wrong about is not caution, it is a stale number with a good excuse. The
    same applies to the sibling `weight_footprint_gb`, whose one-way "apply a measured
    footprint only when LARGER" rule was justified as refusing "context nobody asked
    for" — a premise a maintainer can revoke by asking for it. **THE FIX IS TO REPLACE
    THE CLASS WITH THE INSTANCE, NOT THE CONSTANT WITH A BETTER CONSTANT**: KV bytes per
    token is exact arithmetic over published config (`2 × layers × kv_heads × head_dim ×
    dtype bytes`), so there is nothing left to guess. **THE CHECK THAT MAKES THAT
    TRUSTWORTHY COSTS NOTHING AND SHOULD ALWAYS BE WRITTEN**: feed the new derivation the
    shape the OLD constant was hand-computed for and assert it rederives that constant
    exactly — 0.5000 MB/token for 32 layers × 32 heads × 128 dim at fp16. If it does not,
    one of the two is wrong, and you learn which without a GPU. THREE RIDERS. A quantised
    checkpoint quantises the WEIGHTS; its KV cache still runs at the compute dtype, so
    reading "fp8" off a repo NAME under-reserves the cache — the direction that fails at
    startup. `head_dim` is published precisely because it is not always
    `hidden_size // num_attention_heads`; deriving it when it is stated is wrong for
    exactly the models that state it. And the checkpoint's `max_position_embeddings` must
    cap the result and is allowed to bind BELOW your own floor: vLLM refuses to start
    above it, so a floor that overrides it converts a working start into a failed one.
    **THE MAINTAINER THEN DOUBTED THE NUMBER AND WAS RIGHT TO — verifying it against
    the publisher found two defects the arithmetic could not (2026-08-13, same day):**
    the figure I published (0.1016 MB/token) came from a shape I had GUESSED, and the
    live config matched it on all three fields that enter the formula. A lucky guess,
    not a sound one, and the luck hid two real things. (a) **transformers renamed
    `torch_dtype` to `dtype`**, and the shipped checkpoint carries only the new name —
    so the reader fell through to its 2-byte FALLBACK on exactly the model it was
    written for, which is bfloat16's size, so the output was correct and the mechanism
    was dead. A `"dtype": "float32"` checkpoint would have been under-reserved by half.
    That also makes the guard's fixture load-bearing: a bfloat16 config cannot
    discriminate a reader that read the field from one that read nothing, and my first
    test used bfloat16 and duly passed against the broken reader — **only a dtype whose
    size differs from the fallback tests anything**. (b) The reserve `gpu_memory_
    utilization` holds back was NOT subtracted from the KV budget, so the two
    derivations disagreed by 1.5 GB — vLLM's pool is `free − reserve` and the cache
    lives inside it. Fixing that had its own twin: applied to the UNMEASURED fallback
    it drops an 8 GB card 5120 → 2048, and 5120 is a number the field has served, so
    the subtraction is gated on the KV figure being measured. THE PUBLISHED CONFIG,
    recorded so it is never re-derived: 26 layers · 32 attention heads · **8 KV heads**
    · **head_dim 128** (`hidden_size` 3072 ÷ 32 = 96, so deriving it under-counts by
    25%) · bfloat16 · `max_position_embeddings` 262144 ⇒ **0.1015625 MiB/token**, ~5×
    cheaper than the class constant. TWO SMALLER RIDERS. Those figures are exact dyadic
    fractions (bytes ÷ 2²⁰), so **any** fixed decimal rounding truncates some of them —
    I picked a precision twice and was wrong twice (5 places lost 0.015625, 6 lost
    0.1015625) before noticing the value is divided, never displayed, and needs no
    rounding at all. And a clamp that was unreachable can be made LIVE by a change
    elsewhere: `max(0.5, free − weights)` needed `free < weights`, which an upstream
    guard already refuses by name, but subtracting the reserve made it fire for the
    ordinary state of a card holding a display server — publishing half a gigabyte of
    KV that the utilization had already declined to claim. When you add a term to a
    subtraction, re-ask what its floor now means. **THE FIXTURE WAS THEN MADE FAITHFUL
    TO THE REAL FILE, AND THAT FOUND MORE THAN THE NUMBERS DID:** the published config
    is MULTIMODAL — the transformer shape sits under `text_config` while the dtype stays
    at the TOP level, and `vision_config` carries its OWN `num_hidden_layers` (24). A
    flat fixture exercises none of that, so it cannot catch a reader that merges the
    wrong block and sizes the KV cache from the vision tower; a mutation doing exactly
    that passes every flat test and fails four faithful ones. Transcribe the real file
    rather than the fields you think matter — the STRUCTURE is part of the test. Three
    further facts from the same verification, recorded so they are not re-derived:
    `sliding_window` is explicitly **null**, which is what makes the linear formula
    correct here (a checkpoint declaring a window has its cache CAPPED at that width,
    so the formula would over-state — the safe direction, but a real limit); the 262144
    ceiling is **YaRN-extended from a trained 16384**, factor 16, with no quality claim
    at the top of the range; and the checkpoint is fp8 with `modules_to_not_convert`
    keeping the vision tower and `lm_head` in bf16, so weights are NOT a clean
    params×1 byte — while the KV cache stays 2 bytes because `--kv-cache-dtype`
    defaults to the model's own dtype. The independent verdict — "realistic on 8 GB:
    16384 at default settings" — sits just above what this code now computes (12288 on
    an idle card), and the gap has a NAMED reason rather than being unexplained
    conservatism: the vision tower profiles at image_size 1540 and is the largest
    transient on a small card, and nothing in the budget accounts for it.
  - **AN EQUATION THAT SHOWS ITS WORK MUST SHOW THE WORK IT DID — and the terms drift
    apart silently because they live in different places (2026-08-13, the same fix):**
    `compute_server_args` publishes a `method` string naming every term it subtracts,
    which is the right instinct and is why the defect above was findable at all. It was
    built as one f-string at the TOP of the function while the derivation happens 130
    lines DOWN, so the moment the reserve and the checkpoint ceiling entered the
    arithmetic the published equation stopped reproducing its own number — a reader
    doing the division got a different answer, which is worse than publishing no
    equation. The fix is structural, not editorial: compose the clause WHERE the
    numbers are known, so a term cannot enter the code without entering the sentence.
    Pin it with an assertion that hand-computes from the printed terms and equals the
    printed result, plus the negative-space twin that the fallback path does NOT name a
    subtraction it never made — a method that claims extra conservatism is a fabricated
    caveat, the same defect pointing the other way.
  - **A DETERMINISTIC REFUSAL CAUGHT BY AN OUTAGE HANDLER COSTS THE WHOLE RUN
    (2026-08-13, same report):** the four sweep loops catch `LLMError` and treat every
    instance as a backend that might come back — sleep, back off, retry the SAME batch up
    to ten times. A 400 naming the context length cannot succeed on retry, because
    nothing about the batch changes; the field run spent ten minutes proving that and
    then ended the sweep at `state=error`. Worse, the comment in `source_tags_job`
    already NAMED this case as the likely cause ("plausibly a context-length overflow
    given the uncapped, verbatim, corpus-wide tag vocabulary embedded in the prompt") and
    still paid for it at 60s a try — a suspicion recorded next to the code that ignores
    it. Classify on the SERVER'S WORDS, not the status code: a 400 is also how a backend
    reports a malformed request, and Ollama reports the same overflow as a 500. The
    answer is to make the request smaller — the cursor is untouched on failure, so
    halving the batch re-selects the same items in a smaller chunk, is bounded at ~log2
    halvings, and costs no outage budget because nothing about the backend is wrong. THE
    TWIN IS THE ONE THAT MATTERS: misreading a connection failure as an overflow would
    shrink the batch against a backend that is simply down AND skip the retry that is
    correct there, so both directions need a test. GENERAL FORM: before adding a failure
    to a retry loop, ask whether re-sending the identical request could ever produce a
    different answer; if not, retrying is not resilience, it is a delay before the same
    failure.
  - **A LOG TAIL IS THE WRONG HALF WHEN THE ROOT CAUSE COMES FROM A CHILD PROCESS
    (2026-08-02, the vLLM start failure):** `server_log_tail` kept the last 8000 bytes
    on the written assumption that "a CUDA OOM puts the actionable numbers at the END".
    That is true when a RUNNING server dies and exactly false at STARTUP: vLLM's
    EngineCore is a child, so it prints its traceback FIRST and the parent then dumps
    ~20 KB of its own stack ending in the words **"See root cause above."** — the log
    literally telling you the instrument is pointed the wrong way. The field bundle was
    29,855 bytes with the last 8,000 kept, every one of them the parent's stack. GENERAL
    FORM: before bounding a captured log, ask which PROCESS prints the reason and in what
    order; a parent that re-raises a child's failure inverts the usual "the end is the
    interesting part" rule. Keeping both ends is cheap; keeping only one is a bet on the
    failure shape. And state the gap (`elided_bytes`) so two retained halves can never be
    read as contiguous.
  - **WHEN A COMPUTED VALUE IS CLAMPED, CHECK WHETHER THE CLAMP IS DOING ALL THE WORK —
    and a test asserting `large >= small` passes for a constant (2026-08-02, same
    session):** `compute_server_args` published `max_model_len` with a method string
    saying it "scales with the remaining VRAM", and returned **32768 for every card from
    6 GB to 80 GB**. A unit error (0.5 MB treated as the cost of a THOUSAND context
    tokens when it is the cost of ONE for a 7B-class fp16 model, then multiplied by a
    further 1000) put the estimate three orders of magnitude high, so the cap decided
    every machine while the disclosure claimed a derivation — a fabricated method, which
    is the honesty defect even before any crash. Its guard,
    `test_compute_server_args_scales_with_vram`, asserted `large >= small` and had been
    passing for years against a function that did not scale at all; the mutation check
    prints the tell as `assert 32768 > 32768`. TWO RULES: a monotonicity assertion over a
    clamped value must be STRICT, or it is satisfied by the constant it exists to catch;
    and when correcting a wrong constant, prefer fixing its UNIT over inventing a new
    number — the 0.5 MB figure was right, only its denominator was wrong, so the fix
    needed no new estimate to defend.
  - **A THICK MEASUREMENT WINDOW IS THE SIGNATURE OF A POLLER, SO SELECTING ON IT SELECTS
    AWAY EVERY INTERACTIVE ROUTE (2026-08-02, the snappy bar):** `all_interactive_pass`
    and K2 judged only routes with `window_n >= 20` and reported GREEN at 31.2 ms while
    `GET /api/articles` sat at a measured p95 of **68,137 ms** in the same reservoir. The
    three routes that qualified were all 2-second pollers — and that is structural, not
    bad luck: the UI polls `/api/system/network` 275 times a session while a person opens
    the article list twice, so an n-threshold is a near-perfect *anti*-filter for the
    thing being measured. The deeper error was reading `low-n` as "no measurement exists"
    when it means "the measurement's TYPICALITY is unproven" — 68 seconds was really
    observed. Report the breach with its n rather than dropping it, and never let a
    confidence label double as an existence label. NEGATIVE-SPACE TWIN, mandatory here: a
    thin-but-FAST route must NOT break the pass, or the fix trades a fabricated green for
    a fabricated red that fires on every freshly-booted process.
  - **A HEALTH PROBE CANNOT TELL "GONE" FROM "MOMENTARILY UNREACHABLE" — so it may
    enrich a message but must never decide a retry (2026-08-02, the AI-sweep outage
    reason):** the sweeps' "local model hiccup (1/10) — retrying in 5s" was wrong in
    every part (`resolve_backend()` already knew `no_backend: true` with a precise
    reason), and the obvious fix — have the probe classify the outage as terminal and
    short-circuit the retry budget — was WRONG in a way the repo's own progressive-sweep
    tests caught within one run: a model reload, a restart and a busy server all answer a
    health probe identically, so that would end a multi-hour sweep on the first blip,
    destroying the exact guarantee the backoff exists to provide. Split the two concerns:
    the probe supplies WORDS (beside, never instead of, the raw error), the caller keeps
    the CONTROL FLOW. Pin it with a test that the helper exposes no verdict at all, since
    the tempting version is one refactor away. Same family as the port-collision lesson —
    a boolean up/down probe will confidently answer a question it cannot see.
  - **AN ABSOLUTE FLOOR FIXES THE BLIND DIRECTION AND LEAVES THE NOISY ONE OPEN — a
    zero-spread cohort makes `v > p90` mean `v > 0` (2026-08-02, source-audit):** the
    recorded tail-blindness lesson added `PATHOLOGY_ABS_FLOOR` so a DEGRADED cohort could
    not hide a broken source. The mirror case went unexamined: on a PERFECTLY CLEAN cohort
    the robust p90 and MAD are both exactly 0.0, so the tail test degenerates to
    "greater than zero" and ONE pathological article out of 1,992 became an
    extraction-failure verdict — all 63 sources the field called "failing" were this, each
    100–1000× below its own floor, Al Jazeera and Le Dépêche among them. A RATE cannot
    carry this weight (1-in-1,992 and 600-in-1,200 are the same number to a threshold), so
    guard the high-confidence criterion on the raw COUNT — which `per_source_metrics`
    already computed and discarded. GENERAL FORM: whenever a robust-statistic outlier test
    can meet a degenerate distribution, ask what the test *reduces to* there; and when a
    fix adds a floor for one failure direction, write the twin test for the other before
    assuming the criterion is now sound.
  - **A BOOT-ONLY JANITOR IS A JANITOR THAT NEVER RUNS, ON EXACTLY THE INSTANCE THAT NEEDS
    IT (2026-08-02, the orphaned restore staging):** `cleanup_stale_staging` reclaims
    `.restore-*` dirs at boot, guarded at 24 h so a live job is never swept. Both halves
    are correct and they compose into a hole: a dir orphaned in hour 1 is too YOUNG at the
    next boot check and is never looked at again, so it survives the entire uptime — and
    the longer the instance runs, the more certain that is, on the very machines the
    14-day-continuous KPI is asking for. Its sibling (the pre-restore snapshot sweep)
    already ran both at boot AND off-peak, which is the shape to copy. The cost is not the
    bytes: for an encrypted corpus a staging tree holds a PLAINTEXT copy, so an unswept
    one is an at-rest-encryption hole for as long as the app stays up. GENERAL FORM: any
    cleanup with an AGE GUARD needs a RECURRING trigger, because the guard guarantees the
    first look will be too early.
  - **A MUTATION TEST MUST REVERT EVERY MECHANISM THE FIX SHIPPED — reverting one of two
    proves nothing and reads as "the guard is dead" (2026-08-02, the WAL-starvation
    recalibration):** checking that `test_wal_reader_starvation`'s discriminating
    assertion still bites, I removed PR-D's between-producer `session.commit()` and the
    test still PASSED. The tempting conclusion — that the guard had silently stopped
    discriminating, which the file's own comments warn is a thing that happened before —
    was WRONG. PR-D shipped TWO independent WAL-releasing mechanisms
    (`_release_transaction` *and* `_WalGuardResult.fetchmany`'s periodic in-scan close),
    and either alone lets a checkpoint through, so a single-mechanism mutation changes
    nothing. Reverting both fails loudly and by name. RULE: before concluding a guard is
    vacuous, grep the fix for every path that satisfies it and neuter ALL of them —
    otherwise the mutation is testing your model of the fix, not the fix. Corollary worth
    keeping about the RECALIBRATION itself: the test was tuned so tightly (macOS measured
    2,006,504 bytes against a 2,097,152 bar — 96% of the way) that ordinary platform
    variance tipped it, and the honest lever was the one the file's own failure messages
    already named (`_TARGET_WRITES`, which raises WAL PRESSURE) rather than the assertion
    threshold. Raising the input a guard is fed strengthens a reproduction; lowering the
    bar it must clear weakens it, and only one of those is a legitimate response to a red
    lane. Calibrate against the WEAKEST platform observed, not the strongest, and record
    the per-platform measurement beside the constant so the next session does not
    re-derive it.
  - **A TEST THAT COMPRESSES TIME MUST COMPRESS THE THROTTLES TOO, OR IT SILENTLY MODELS A
    CASE THAT CANNOT OCCUR (2026-08-04, the same WAL soak test going red on CI two days
    later):** `test_wal_starvation_soak` shrinks a "scan that can run for MINUTES" — the
    production case its own comment cites — down to 0.8 s, but left
    `_WAL_GUARD_MIN_RELEASE_INTERVAL_S` at its production **30 s**. So every release after
    the unconditional first one was throttled out and the scan offered the checkpointer
    exactly **ONE** window, measured at **t=0.009 s**, before the checkpointer had finished
    its first 50 ms sleep. The whole assertion turned on whether a thread happened to fire
    inside nine milliseconds — luck that held locally (a deterministic 9 attempts, byte-identical
    4,902,832-byte WAL, run after run) and stopped holding on a cold shared runner. THE TELL
    THAT IT WAS NEVER ABOUT LOAD: CPU contention (12 spinners on 4 cores) reproduced nothing,
    8/8 green; and my first reproducer — widening the checkpointer's *inter-attempt* sleep —
    also reproduced nothing (6/6 at every width, even at fewer attempts than CI's failing
    round), because it never delayed the FIRST attempt, which is the only one that can catch a
    9 ms window. Delaying the first attempt by 0.15 / 0.30 / 0.60 s reproduces it exactly:
    1/6, 0/6, 0/6. **BOTH assertions rested on that one accident** — the WAL bound moved with
    it, 82% of ceiling → 110% → 132% → 158%, so "fixing" the checkpoint assertion by any
    route that lengthened the window would have traded it for the other one. Compressing the
    throttle to match the compressed scan fixes both (6/6 at every delay; WAL 4–13% of
    ceiling) and CANNOT weaken discrimination, because an unpatched build releases ZERO times
    at ANY interval — pinned by re-running the mutation matrix above at the new setting:
    in-scan release removed → **0/5**, between-producer commit removed → 5/5 (the recorded
    trap, reproduced), both removed → 0/5. GENERAL FORM: when a test scales one dimension of
    a mechanism down for runtime, list every *other* constant that dimension is compared
    against; any left at production scale silently converts the test into a different, usually
    degenerate, case. And add the anti-vacuity assertion one level below the property — here,
    that the scan actually OFFERED several windows (`wal_releases >= 4`; it is 2 without the
    compression) — because the fix is one deleted monkeypatch away from reverting to
    coin-flip, and it would revert as an intermittent CI red that reproduces nowhere.
    **IT RECURRED IN THE SIBLING ROUND (found independently by two sessions, 2026-09-03 and
    2026-09-04), and the recurrence is worth more than the fix:** the compression was applied
    to `test_wal_starvation_soak.py` and never to `test_wal_reader_starvation.py`, which runs
    the same shape against `run_all()` and whose scan is also sub-second. At the production
    30 s that scan offered the checkpointer exactly ONE window, so the whole assertion turned
    on whether a 50 ms-timeout attempt happened to land inside it. So the general form is not
    about throttles at all: **a lesson recorded against one assertion does not propagate itself
    to the one beside it** — when a timing fix lands, grep the tree for every sibling round
    driving the same mechanism (here `registry.run_all`) and check each one carries it, because
    the one you did not touch will fail months later as an intermittent red that reproduces
    nowhere. **THE CI SIGNATURE OF THIS CLASS IS WORTH RECOGNISING ON SIGHT: the same SHA
    passing in one lane and failing in another** — `2d12708` passed the PR run's own `test`
    lane AND the push run's Core-only job while failing the PR run's Core-only job; three
    lanes, identical code, so a code regression is ruled out by construction in one lookup
    (the recorded free A/B). **REPRODUCING IT NEEDS LOAD, NOT A DELAY**, and two sessions
    measured it separately on 4-core boxes under 3x CPU oversubscription — what a shared
    runner executing two full suites concurrently looks like: **4 pass / 6 fail** and
    **6 pass / 4 fail** in ten at the production 30 s; with the compression, **12/0** and
    **10/10**. Idle it passed either way, which is exactly why it only ever appeared on CI.
    **THE TWO SESSIONS ALSO APPEARED TO DISAGREE ON THE FLOOR — 3 releases versus 1 window —
    AND DID NOT: they measured different quantities**, which is the useful half. Re-measured
    on the merge, 3 runs per condition, deterministic every time — in-scan releases (total in
    brackets): compressed **6 (8)**; compression dropped **1 (3)**; the production in-scan
    release removed from `registry` **0 (2)**. So a floor on TOTAL releases and a floor on
    IN-SCAN releases are both discriminating, and the in-scan one is the right quantity
    (a release outside the producer's window offers the checkpointer nothing) — which is the
    version kept. Note the last two rows: **the floor cannot tell those two causes apart**, so
    its message must name BOTH — a missing production mechanism or a missing compression —
    because a floor that guesses one accuses the wrong party, and blaming the test's own
    throttle when `_WalGuardResult.fetchmany` is what regressed would send a reader hunting
    the wrong defect. One more rider: I first wrote "releases exactly ONCE" from reasoning and
    the measurement said 3, so calibrate an anti-vacuity floor against BOTH populations rather
    than deriving it from how you think the mechanism behaves.
  - **AGREEING ON THE GATE IS NOT ENOUGH — TWO MODULES PUBLISHING ONE QUANTITY MUST AGREE
    ON THE BUCKET KEY (2026-08-03, the language-equilibrium lever):** the recorded framing-tone
    lesson says modules publishing the same quantity must agree on the *gate*. A weaker
    disagreement is just as costly and much harder to see: `corpus_language_shares` bucketed
    languages on `.strip().lower()` while the house `normalize_lang` strips the region subtag,
    and `Article.language` is stored RAW from `<html lang>` — so `en` / `en-US` / `en_us` were
    three languages to the lever, which then compared ONE SPELLING'S share against the whole
    target. Measured: English deferred on 14.3% of passes where 50.0% is correct, a 3.5x
    under-correction that grows with how region-tagged the corpus is, and the bundled PRESETS
    (keyed on bare codes) could never match at all. FOUR modules in the tree hand-roll a
    per-language bucket key at THREE different normalisation depths, so this is a family, not an
    instance. TWO RULES: normalise on BOTH sides of any comparison — normalising only the corpus
    leaves an operator who writes `en-US` targeting a bucket that cannot exist; and when a fix
    turns a wrong bucket into a right one, write the NEGATIVE-SPACE TWIN (genuinely distinct
    languages must never merge), because an over-eager key is the same defect pointing the other
    way and is INVISIBLE — the shares still sum to 1.
  - **A TOOLKIT-WIDE FIX MUST ENUMERATE EVERY RENDERER, INCLUDING THE ONE WHOSE SIBLING GOT IT
    RIGHT (2026-08-03, smallMultiplesSvg):** the 2026-08-02 honest-gaps pass fixed `dashChartSvg`
    and `ooChart` and missed `smallMultiplesSvg` — which sits thirty lines BELOW `slopeChartSvg`
    in the same file, was written in the same batch, and whose sibling already carried the
    comment "break at gaps, never bridge". Proximity to a correct implementation is not
    coverage. The miss was also the worse half of the defect: a bridged line invents a
    CONNECTION, but `Y(null)` = `padT+(h-padT-padB)*(1-null/maxV)` lands on the zero BASELINE, so
    a published gap became an invented OBSERVATION. (An earlier draft of this entry ALSO blamed the
    scale scan's `isFinite(pt.count)`; an adversarial pass refuted it — `isFinite(null)` is true, but
    the guard was `isFinite(pt.count) && pt.count > maxV` and `null > maxV` coerces to `0 > maxV`,
    which cannot raise a scale starting at 0. Corrected here because a fabricated claim inside an
    honesty fix is the same defect the fix is about.) GENERAL FORM: when fixing a property across a "toolkit", grep for
    every function that emits the primitive (here `<polyline`/`<rect`), not for the renderers you
    can name; and check the ones whose neighbours already comply, since a reviewer's eye reads
    the correct sibling and moves on. COROLLARY worth reusing: geometry must span every SLOT
    while the sparse threshold and the displayed `n` count only real OBSERVATIONS — one number
    keeps the hole's width, the other refuses to claim evidence that was never collected.
    THIRD COROLLARY, from the same review: A CAVEAT MAY CLAIM ONLY WHAT THE DATA CAN EXHIBIT. The
    fixed renderer's one live caller feeds `_window_daily_series`, which OMITS zero-count days
    instead of publishing them as null — so no gap can ever reach it, while the caveat advertising
    gap handling rendered unconditionally. The handling is real and tested; it is simply not
    exercised there, so the sentence is now emitted only when a gap is actually present. A promise
    the shipped data cannot keep is a fabricated assurance even when the code behind it is correct.
    (The omission itself compresses the index axis — day 1 and day 5 render adjacent — which is a
    separate, pre-existing defect affecting the trending sparklines too; recorded, not fixed here,
    because for keyword mentions an absent day is a REAL zero and zero-filling is the right repair,
    not null-filling, and it changes a second shipped surface.)
  - **A MECHANISM THAT QUIETLY RECORDS A DECISION SUPPRESSES THE SAFETY DEFAULT THAT
    DECISION OVERRIDES (2026-08-02, the boot-airplane race, PR #846 merged RED then
    #847):** a field report — "on a new instance the app sometimes stays in airplane
    mode with no explanation" — was a real race: `_run_startup_upkeep` engages airplane
    at its tail, on the unlock path in a BACKGROUND THREAD, and a new instance's upkeep
    is slow enough that the wizard sits on screen throughout it, so an operator who
    crosses online mid-upkeep has the thread's `activate_kill_switch()` land after their
    `clear_kill_switch()`. The FIX was right; where it was recorded was not. Setting the
    crossed-online flag INSIDE `clear_kill_switch()` looked equivalent — clearing the
    switch *is* going online, surely — but that primitive is ALSO how a caller reaches a
    KNOWN STATE: `conftest` calls it around every test, and `test_app_boots_in_airplane_
    mode` calls it itself immediately before booting, precisely to start clean. The boot
    then declined to engage, and the whole test lane went red. **THE DIRECTION IS THE
    LESSON:** a mechanism that quietly counts as a decision SUPPRESSES the boot airplane
    engage — it weakens zero-network boot, the non-negotiable the feature was written to
    leave untouched — so the tempting repair (reset the flag in `conftest`) would have
    kept the weakening and hidden the evidence. Separate the two instead:
    `clear_kill_switch()` records nothing; `note_operator_crossed_online()` records the
    decision, called from the three surfaces where that is what happened (go-online
    endpoint, scheduler start, run-now), which were already its only production callers.
    GENERAL FORM: before folding a state-recording side effect into a primitive, list
    every caller and ask which of them is making a DECISION and which is merely reaching
    a STATE; if both exist, the primitive is the wrong home. COROLLARY that is a separate
    trap: a process-global "has an operator ever done X" flag is correct per-process in
    production (one boot, one operator) and wrong across a shared test session, where
    many tests legitimately act as the operator — it needs a per-test reset beside
    whatever other process-global state the suite already resets.
  - **`os.environ.pop` IN A TEST IS A SESSION-WIDE EDIT, AND ITS FAILURE SURFACES FAR
    FROM ITS CAUSE (2026-08-02, the same fix-forward):** `conftest` sets
    `OO_NO_SCHEDULER=1` once for the whole session; a test that needs production
    behaviour must borrow it with `monkeypatch.delenv(..., raising=False)`. A bare
    `os.environ.pop` deletes it for every LATER test too, so every subsequent
    `TestClient` lifespan takes the production branch — engaging airplane and starting
    the background scheduler. It presented as EIGHT unrelated "the network kill switch is
    active" failures in `csv_feeds`, `jobs`, `llm_ollama` and `markets`, none of which
    had anything to do with the change. WORSE, AND THE PART WORTH KEEPING: the leak had
    shipped one PR earlier and was INVISIBLE, because the very defect above (the flag set
    by `clear_kill_switch`) made the boot engage skip anyway — fixing one bug UNMASKED
    the other, so CI got worse before it got better and the second failure looked like a
    regression from the fix. When a fix makes a lane fail differently rather than less,
    suspect an unmasked pre-existing bug before assuming the fix is wrong. A `conftest`
    guard to fail whichever test leaks the variable was written and DELETED: its teardown
    races `monkeypatch`'s, so it fired on correct code — a gate that reddens on correct
    usage is worse than the leak it catches.
  - **A SELF-LIMITING INSTRUMENT MUST SELF-RECOVER, AND MUST BE CHARGED FOR ITS OWN COST
    (2026-08-02, the run journal's child-CPU walk):** the beat's per-child CPU sample is
    the ONLY thing that separates a healthy process pool (parent near-idle) from a wedged
    one — the module's own docstring says so, and the standing lesson above says it too.
    It was OFF for the entire phase it exists for. Two independent defects, both in the
    shape of a reasonable-looking guard: (a) the cost budget was charged against the
    WHOLE beat, which also reads `/proc/meminfo`, stats the destination filesystem and
    sizes the WAL — so a slow disk stat retired the child walk for a reason that had
    nothing to do with it; (b) the stand-down was a ONE-WAY LATCH. In a 19 h field import
    the walk died at beat 24, during `merging`, because one beat measured 25.9 ms against
    a 25 ms budget — 0.9 ms over — and all 1,561 following `reindexing` beats carried no
    child data at all. The constant's own docstring already said "sampled at a reduced
    cadence"; the code implemented "never again", and nobody had read the two together.
    RULES: time the expensive part ITSELF and report that time (so the cost is measured,
    never assumed), and make the stand-down bounded and recovering. Corollary that held
    up: a backed-off beat must still OMIT the field rather than zero it — `kids_n: 0`
    reads as "no worker processes", the inverse of what it stands in for.
  - **`.get(key, 0)` ON A DELIBERATELY-OMITTED FIELD FABRICATES THE MEASUREMENT THE
    OMISSION EXISTS TO PREVENT (2026-08-02, same investigation, caught before it reached
    the user):** reading the field bundle, I reported that the process pool had "never
    spawned a single worker — 0 children across 5,531 beats" and was one step from
    filing it as the root cause of a 19-hour import. It was my own bug: `kids_n` is
    ABSENT in those beats and my `.get("kids_n", 0)` invented the zero. The instrument
    was honest by construction (it omits with a reason rather than zeroing, exactly as
    its docstring promises) and my reader defeated that honesty in one keystroke. GENERAL
    FORM: when a payload's contract is "an unmeasurable field is omitted", every consumer
    must distinguish missing from zero — count key MEMBERSHIP before aggregating, and be
    suspicious of a striking result that rests on a default argument. The tell here was
    the strength of the finding: 0 children in 5,531 consecutive samples is too clean for
    a real system, and that implausibility is what prompted the re-check.
  - **A BACKSTOP ON ONE PATH IS NOT A BACKSTOP IF THAT PATH HANDS OFF TO AN UNBOUNDED ONE
    (2026-08-02, the re-index precompute stall):** `precompute_batch`'s fallback comment
    calls `_POOL_TIMEOUT_S` "the only thing standing between a deadlocked worker and an
    import that never finishes" — and then, on timeout, hands the whole window to
    `_serial`, a bare dict comprehension with no bound of any kind, which is also the
    deliberate small-batch path. Two field imports each stopped advancing at an exact
    window boundary (9.8 h before recovering; 6 h until killed), burning ~0.75 of a core
    with the WAL byte-frozen and the write gate free — all three facts saying in-process
    pure-CPU work — and nothing in 19 h of journal said WHICH ARTICLE, so there was
    nothing to reproduce from. Python cannot preempt a running C-level regex, so the
    honest fix is not a timeout it could not honour but a NAME: a watchdog thread that
    reports the article id, size and position WHILE IT IS STILL RUNNING, plus an
    after-the-fact line for the recovered case — the two are separate because a killed
    run never reaches the second and a recovered run is invisible to anything else.
    GENERAL FORM: when a guarded path degrades to an unguarded one, the guard's stated
    guarantee is false for the degraded case; check what the fallback inherits.
  - **A WINDOW'S ORDER CAN BE LOAD-BEARING FOR A RESUME CURSOR THAT COUNTS (2026-08-02,
    batching the re-index window load):** replacing a per-article `session.get` loop with
    one `IN (...)` per chunk is a pure perf change — same rows, same bytes through the
    codec — EXCEPT that an `IN (...)` result set has no guaranteed order, and the caller
    turns a COUNT back into an id by POSITION: `merge.py`'s `_tracked` stamps
    `ids[done - 1]` as the last finalised article, and the resume then keeps only
    `i > watermark`. A window staged in any other order would stamp a watermark ABOVE
    articles that were never re-indexed, and the ascending resume would skip them
    permanently — the unbounded invisibility the durable cursor exists to prevent.
    Nothing pinned it: reversing the load order left all 67 tests in the re-index suites
    green. GENERAL FORM: before changing how a collection is fetched, find out whether
    anything downstream indexes into it by position rather than by key — a count-to-id
    mapping is the signature.
  - **A STANDALONE SQL PROBE IS A LOOKALIKE, AND EXPLAIN QUERY PLAN CAN NAME AN INDEX
    THAT NO LONGER EXISTS (2026-08-04, the per-language feed's covering index):** two
    ways a plan assertion certifies nothing, both hit in one slice. (a) I confirmed the
    new composite index covered both of the feed's queries by running the SQL by hand in
    a scratch database — it did, there. Driving the REAL function showed SQLite serving
    the second query from a NARROWER index instead (`language IS NULL` is an equality
    seek; the composite's leading column is a range), then reading the heap for
    `detected_language` — index-only for the series, straight back into the codec for
    the tally, on exactly the rows that are most numerous when a corpus is under-tagged.
    A hand-written lookalike differs from the shipped query in table stats, in ANALYZE
    state, and in which other indexes exist, and all three move the planner. Capture the
    statements the production path actually emits (a `before_cursor_execute` listener)
    and EXPLAIN those. The FIX generalises past this case: when two queries want
    different indexes, fold the second into the first as an extra GROUP BY dimension —
    grouping on the predicate at most doubles the row count and leaves the planner no
    escape. (b) The negative half — "with the index dropped the plan must change" — is
    where it gets dangerous: **pysqlite caches compiled statements per connection and
    the pool hands the same one back, so EXPLAIN keeps reporting the DROPPED index by
    name** (verified: `sqlite_master` empty while the plan still cited it). Without
    `engine.dispose()` that assertion passes whatever the planner would really do — a
    guard that cannot fail, attached to the one claim that makes the positive half
    meaningful. COROLLARY, cheap and recurring: an index over a column a legacy store
    may lack collides with any fixture that simulates the missing column via
    `DROP COLUMN` (SQLite refuses while an index references it). Drop the referencing
    indexes BY REFLECTION rather than by name — the next index over that column then
    cannot silently break a guard that is about something else entirely, and it is also
    more faithful, since a store old enough to lack the column never had an index on it.
  - **A SOURCE GUARD OVER A DISCLOSURE SURVIVES THE MUTATION THAT DELETES THE DISCLOSURE
    (2026-08-04, same slice):** the tile's honesty rests on stating what it does NOT
    draw — the ranked-out tail, the articles with no asserted language. Guarding that
    with `assert "d.other" in body` felt like the house pattern and was worthless:
    neutering `if (other.languages)` to `if (false)` left the identifier sitting in its
    `const other = d.other || {}` binding, so the guard stayed green while the sentence
    vanished. The identifier is not the sentence. Extract the disclosure builder as a
    PURE function and test what it SAYS, in node, with the negative-space twin beside
    each claim (an over-eager disclosure invents missing data as dishonestly as an
    omission hides it) — four mutations that all passed the substring version all fail
    the behavioural one. Same family as the recorded "a whole-file substring assertion
    is only as meaningful as that string's uniqueness", one level sharper: even a
    correctly-SCOPED substring proves only that a token appears somewhere in the slice.
    And check the ratchet — `test_every_node_suite_has_a_driver` exists precisely
    because an unrun node suite already cost a shipped defect.
  - **NEVER RE-SERIALISE A CURATED FILE TO EDIT ONE ENTRY (2026-08-02):** adding a single
    key to the 12 locale files rewrote all 12 — 27,000 lines changed to carry 12 lines of
    real content — because they were written back with `json.dump(sort_keys=True)`. The
    order is not incidental: the files are grouped BY UI SECTION (nav, then home, then
    settings), which is how they are navigated and reviewed, so the sort destroyed that
    grouping permanently, buried the one real change, and guaranteed a conflict with any
    parallel locale work. The maintainer spotted it as "27K lines of code... this seems
    awkward" before review did. Edit in place (textual insert next to the sibling entry),
    and when a rewrite has already happened, verify EQUIVALENCE before restoring — parse
    both sides and assert same keys, same values, only the ordering differs — rather than
    reverting on faith. No repository script does this, so there was nothing in the tree
    to fix; the fix is the habit.
  - **A GUARD CAN PASS FOR A REASON THAT HAS NOTHING TO DO WITH ITS CLAIM — and the ratchet
    meant to catch that class had the same defect (2026-08-04, PR #861, the ruling-7c audit
    of every source-reading test file):** a 14-agent sweep with an adversarial verifier on
    each finding reported examining 8,204 assertions and produced 41 distinct guards that
    could not fail for the reason they were named — 47 confirmed of 58 raw, 11 refuted, each
    hand-re-verified before any edit. FIVE SHAPES, all of which really shipped here. (a) **The
    tautology.** `assert 'ensureOnline("Download an offline map region")' not in osm or
    "ensureOnline" in osm` — the second needle is a SUBSTRING of the first, so the disjunction
    is true for every possible input; it could not have failed with the consent gate deleted
    outright. A three-way disjunction whose third arm is guaranteed by an `assert` four lines
    above is the same thing wearing more clothes, and so is a loop that re-asserts the exact
    regex it just derived its ids from. (b) **The wrong operand.** `assert "score" not in
    "renderAnTrend drawAnTrend"` compares against a Python string LITERAL holding two function
    NAMES — a compile-time constant that never opened app.js, in a file whose every other
    assertion does. (c) **The comment-satisfied positive.** Invariant #16's `"never
    downsampled"`: all three occurrences are on `//` comment lines, and the assertion's own
    message said the toolkit must "state AND implement" the rule. Delete the implementation,
    keep the comment, stay green. (d) **The non-unique needle.** `confirm(` 30 matches,
    `card-caveat` 41, `ensureOnline` 47, `d.caveat` 58 — each asserted about ONE surface and
    satisfied by any of dozens. Its special case: a ZERO-ARGUMENT function's own declaration
    contains `name()`, so `assert "loadFamilyCuration()" in app, "showSetCat must WIRE it"` was
    satisfied by the definition and could not tell wired from defined. (e) **The mis-slice.**
    `split(DELIM)` where DELIM does not occur is a no-op and the "body" becomes the whole
    remainder: `split("\ndef test_")` against `src/api/main.py` — a source file with no tests in
    it — made the slice 108,272 characters, and the guard was then satisfied by `main()`, the
    exact call path its own docstring said must not count. Ten JS slices split on
    `"\n    function "`, which cannot match the `async function` that follows, over-running by
    up to 3.2x; one bounded a CSS rule by "the next selector I could think of" and took 820
    lines for a 20-line block. **THE PART WORTH MOST:** `test_source_slicing_discipline`'s own
    budget read 0 — not because the tree was clean but because its detector was a regex over
    five hardcoded helper NAMES, blind to the inline `html[a:b]` and `src.split(...)` forms
    nearly every slice actually uses; and its sibling "the budget is not left above the real
    count" AGREED, because both sides came from the same blind detector. The real count was
    276. A ratchet is only as good as its detector, and a detector keyed to NAMES is defeated
    by a rename — test the PROPERTY (an AST walk for `.index/.find/.split` taking a code-anchor
    literal, f-strings INCLUDED, since `src.split(f"def {name}(")` is the common parametrised
    form and reading only `ast.Constant` misses every one). GENERAL FORM: for any
    read-the-source guard ask what ELSE in the file satisfies the needle, and whether the slice
    is bounded by something that provably occurs; the correct bound comes from a parser (`ast`
    for Python, brace-matching from the BODY brace for JS and CSS, BRACKET-matching for a JS
    array literal — `tests/js_source_helper.py` now carries all four, each with its failure mode
    pinned), never from a guessed delimiter. The `array_literal` shape is here because the
    ratchet built by this very sweep caught its author reintroducing the class three days later:
    two guards over `_FIG_STYLES` sliced it as `index("const _FIG_STYLES = [")` to
    `index("];")`, which is correct only while no element contains that pair before the array's
    own close — and the elements are themselves arrays. It reddened all three lanes rather than
    shipping a fragment every assertion would have passed against, which is the ratchet earning
    its keep: prefer being stopped by it over lowering its budget.
    And when you fix one, check whether its own failure MESSAGE claims more than the new check
    tests: "state and implement" needed splitting into two guards, one per half. COROLLARY on
    tightening: only ONE assertion in the sweep changed truth value, and that IS the finding —
    `test_honest_empty_and_bounded_states` sliced four functions and three of its four claims
    belonged to siblings. Three scopes would have been wrong without opening the file first
    (a loader that had MOVED to `_ADV_LOADERS`, a caveat in `drawAnTrend` not `renderAnTrend`,
    and a byte window that swept into `UNRESOLVED_CANDIDATES` — exactly where the unverified
    model tag is SUPPOSED to live).
  - **AN LLM TRANSLATION PASS NEEDS A SECOND PASS THAT ONLY CHECKS THE CLAIM, BECAUSE THE
    FAILURE MECHANICAL VALIDATION CANNOT SEE IS AN OFF-BY-ONE (2026-08-04, PR #861, the 127
    honesty/data-safety strings ×12):** eleven translators, then eleven reviewers briefed
    ONLY to catch a changed claim — a dropped negation, a softened "cannot be undone", an
    uncertainty qualifier presented as fact, a mangled identifier. Both halves earned it. The
    **zh** draft SKIPPED index 68 and shifted every later entry up by one, so 59 English keys
    would have carried the NEXT string's translation; its reviewer found the shift and
    renumbered all 58 affected slots. NO mechanical check can catch that: every slot was
    non-empty, in the right script, and a plausible translation OF SOMETHING. The **ru** draft
    rendered "tamper-evident" (alteration is DETECTABLE) as "protected against tampering" —
    claiming a security guarantee the English deliberately does not make, which is exactly the
    line this project draws between honest and fabricated security. Keep the mechanical layer
    too (gaps, English echoes, per-locale script, identifiers/paths preserved) but know what it
    is for. AND WATCH THE CHECKER ITSELF: a path regex captured the sentence's full stop with
    the filename, so three CORRECT translations ending in their own terminator (Bengali "।",
    CJK "。") read as dropped paths — a good translation must never present as a defect, so fix
    the checker rather than counting it.
  - **`cmd | tail` MAKES `$?` THE EXIT CODE OF `tail` — a pre-push gate checked that way
    always reads green (2026-08-04, the #858 bandit red):** the local check was
    `bandit -r src/ -ll -q 2>&1 | tail -5; echo "exit: $?"`, which printed 0 while bandit
    was exiting 1 the whole time, so a real B608 shipped and reddened the `test` lane.
    This is the same family as the recorded cwd-persistence and collection-error harness
    bugs — a verification that reports success without testing what it claims — and it is
    the cheapest of the three to avoid: redirect to a FILE, capture `$?` on its own line,
    THEN read the file (`cmd > out 2>&1; rc=$?`), or set `pipefail`. The tell is that a
    gate you expect to be interesting never says anything interesting.
    **BANDIT-SPECIFIC, and the reason the first two fix attempts failed:** `# nosec` must
    sit on the line bandit REPORTS, which for B608 over a concatenation is the first line
    of the STRING EXPRESSION — not the enclosing `text(...)`/`execute(...)` call, and not
    the `sql = (` assignment. A marker one line off is silently inert; the run then prints
    `nosec encountered (B608), but no failed test` for the misplaced one while still
    failing on the real one, which is the signal to move it rather than add another.
  - **AN EXPLICIT COLUMN ALLOWLIST FAILS ONE GRANULARITY BELOW THE TABLE-LEVEL GUARD YOU
    JUST BUILT (2026-08-03, the fourteen dropped merge columns):** the 2026-07-24 lesson
    named the defect for a whole TABLE and the completeness registry closed that; the same
    `INSERT INTO t (cols) SELECT` allowlist drops every COLUMN added to the model after the
    INSERT was written, and that is the worse half — a missing table is at least COUNTED in
    the restore report, whereas a dropped column produces a row that arrives, a column that
    is nullable, and a value that is a plausible NULL. Fourteen had gone that way. THE TOOL:
    parse the INSERTs with the **AST**, never a grep — inline `# nosec` comments sit between
    the adjacent string literals the parser folds, so a line-oriented scan reports columns as
    missing that are present. THREE SCOPING TRAPS the guard hit, each of which would have made
    it cry wolf or pass vacuously: (a) not every INSERT is a merge-copy — `merge_batches` gets
    the app's OWN record via `INSERT..VALUES` and its `counts_json`/`report_json` are filled by
    later UPDATEs, so scope the guard to the tables that are actually copied (`_MERGE_HANDLED`);
    (b) a column can be carried ELSEWHERE — `keyword_categories.parent_id` is a self-FK
    remapped by a dedicated UPDATE, so it must be declared as handled or the next reader
    "fixes" what already works; (c) an f-string table name is INVISIBLE to the parser, so
    enumerate those blind spots explicitly, pin the set so it cannot grow silently, and cover
    the ones carrying data behaviourally instead. DIRECTIONAL POINT, as with the qualification
    stamp: ask what the dropped value MEANS, not just that it is gone —
    `keyword_supergroup_members.ring_id` is not data about a member but WHICH KIND of member
    it is, and its own migration records NULL as "a plain family member", so it arrived as a
    different, entirely legal kind and the super-group silently stopped spanning languages.
  - **A "THIS WOULD FLAG NOTHING" REJECTION IS WORTH MEASURING, BECAUSE THE MECHANISM MAY BE
    STRONGER THAN THE OBSERVATION (2026-08-03, the furniture detector):** the brief offered
    (a) retire a DF-ubiquity detector that had never fired, or (b) require corroboration from
    the closed-class publishing-boilerplate stoplist, and predicted (b) "may flag nothing
    either". Measuring it produced a better reason to reject it: every term in
    `PLATFORM_STOPWORDS` / `PUBLISHING_BOILERPLATE_SCOPED` is ALREADY a stopword, so none can
    ever be extracted as a keyword, so none can ever reach a per-source top-12 fingerprint —
    (b) flags nothing **by construction**, not merely in practice. That distinction decides the
    ruling: an empirically-quiet detector might wake up on another corpus, whereas an inert one
    that still LOOKS like a working detector is worse than no detector at all. GENERAL FORM:
    when a design option is expected to be useless, check whether it is *structurally* useless
    — the answer changes whether you ship it as a dormant safeguard or refuse it outright. And
    when you retire a signal, retire the VERDICT and keep the numbers: the DF counts are real
    evidence an analyst can read, and the honest artifact says which of the two it is publishing.
  - **A "MUST BE ABSENT" GUARD ALSO TRIPS ON ITS OWN EXPLANATION IN JS, AND THE FIX IS TO
    STRIP COMMENTS, NEVER TO REWORD THEM (2026-08-03, re-hit while adding the settings panel):**
    the recorded 2026-07-31 lesson says this for `app.js` source guards, and it recurred
    immediately: a guard asserting `ensureOnline` is absent from a loopback settings write
    failed on the comment saying *why* it is absent. Rewording the comment is the wrong repair
    — that comment is exactly what a future session reads before deciding the absence was a
    mistake. Strip whole-line `//` before asserting (which leaves a `https://` inside a string
    literal untouched), or make the guard behavioural. Worth re-recording because the lesson
    existed and was still not reached for until the test went red.
  - **THE REPO'S OWN INVARIANTS CATCH FRONTEND BUGS A NON-BROWSER SESSION CANNOT (2026-08-03):**
    two real defects in one panel, neither visible to `node --check`. `t()` was called in four
    new `app.js` functions without binding a local `t` — it is not a global, so opening the
    panel would have thrown "t is not defined" — caught by
    `test_no_app_function_calls_i18n_t_without_binding_it`. And a live-count read `total` from
    an endpoint whose payload calls it `matched`, which fails silently to an empty string; that
    one was caught by reading the endpoint rather than assuming its shape. So on a
    browser-unverified slice, run the FULL invariant suite rather than the tests you wrote, and
    read every endpoint payload you consume — those two guards are most of what stands between a
    conservative frontend slice and a broken one.
  - **A LAZY `.*?` LOOKING FOR A CLOSER THAT MAY NOT EXIST IS QUADRATIC, AND THE UNROLLED-LOOP
    REWRITE DOES NOT FIX IT (2026-08-05, the 412 KB article that wedged a field re-index):**
    `<(style|script)\b[^>]*>.*?</\1\s*>` is the textbook way to strip a block, and it is fine
    until an opener has no closer — then `.*?` expands to end-of-document, fails, and the engine
    RESTARTS that scan from the next opener, so K openers cost K·N. MEASURED at 412,351 chars:
    138.3 s worst case, 25.7 s on realistic unclosed-`<script>` spam, against **0.004 s for the
    same volume of well-formed markup** — a ~350× cliff that turns only on whether the closers
    happen to be there, i.e. reached by ordinary broken HTML rather than by a crafted input. THE
    TRAP WORTH REMEMBERING: the obvious fix — possessive quantifiers and an unrolled loop
    (`[^<]*+(?:<(?!/\1\s*>)[^<]*+)*+`) — removes the BACKTRACKING and bought only **2×** (138 s →
    66 s), because the K restarts are not backtracking; they are K separate linear scans. Only
    leaving the regex engine fixes it: walk openers with two cursors and RETIRE a tag once no
    closer remains after it (if there is no `</style>` after p there is none after any q > p), →
    0.030 s (4,648×). Two further rules: the replacement's copy cursor and scan cursor must be
    SEPARATE — advancing the copy cursor past a skipped opener silently swallows the text before
    it, a bug every one of 19 hand-written cases missed and a randomised differential against the
    old pattern caught in 2,479 of 6,000; and state the LOSS as well as the win — the linear
    version is ~10 ms SLOWER per 412 KB of well-formed style-heavy markup, because it pays two
    Python-level searches per block instead of one C-level `re.sub`. GENERAL FORM: any
    `OPEN.*?CLOSE` over untrusted markup is a K·N bomb; grep for the shape rather than waiting
    for the article that finds it.
  - **AN INSTRUMENT'S OUTPUT NAMES A SUSPECT, NOT A CAUSE — AND TWO STALLS CAN RUN AT ONCE
    (2026-08-05, the same import):** the console line (`serial precompute still on article 26324
    after 17536 s`) and the run journal disagreed: the journal said the run died in `merge` at
    step 3 of 19, having never reached the re-index at all. Both were true — the autonomous
    re-index job was draining an EARLIER batch concurrently, which the `reindex_resume`
    milestones prove. Reading either signal alone produces a confident wrong story. THE
    NEAR-MISS: the journal contains `step_elapsed_s: 26324.0`, so grepping the raw file for the
    article id "26324" returns a coincidental hit — a number matching across two payloads is not
    corroboration, and the units have to be checked before it is treated as such. SECOND HALF:
    that concurrency was itself the 2026-07-24 exclusive-hold lesson recurring one module over —
    the import recorded `owns_the_machine: true` and `hold_exclusive()` still gated only
    `run_now()`, because `reindex_job.py` never consulted `holds_exclusive()`. When a lesson says
    "gate EVERY entry point", the entry points added AFTER it are the ones that will be missing.
  - **NAME THE QUESTION A DECISION FUNCTION ANSWERS, THEN COUNT THE COPIES (2026-08-04, "AI
    backend won't start … local model hiccup"):** the recorded K2/routing lesson says a
    selection function answers the question it was written for. The sequel is that the
    question you need may have NO owner while looking answered. Here THREE existed —
    `resolve_backend` (routing: who serves this request), `provisioning_backend` (setup: what
    will this machine serve with), and a fourth hand-rolled copy in the browser's AI pill —
    and the one nobody owned was ACTIVATION: which backend do I *start*. Both
    `*_lifecycle.start()` functions existed and worked; no caller chose between them, so the
    sweep probed a backend nothing had started and burned its whole retry budget on a
    condition retrying cannot change. TWO COROLLARIES. (a) When a fourth copy lives in the
    frontend, it will have drifted: this one silently fell through to Ollama on a GPU machine
    whose vLLM was installed but whose model id was unset — a decision no other surface would
    have made. (b) **MOVING A DECISION SERVER-SIDE CAN SILENTLY DROP A FALLBACK THE OLD COPY
    HAD**, and that is the expensive half: consolidating the pill's logic lost its
    "preferred backend blocked → try the other one", turning "starts Ollama" into "refuses and
    starts nothing" on a real machine class. Honest and useless. Its own source-anchored test
    caught it, which is the argument for keeping such tests and *following the anchor* rather
    than relaxing them. Carry the preferred backend's blocker through the fallback (else the
    operator never learns why their GPU is idle), and never fall back under an EXPLICIT
    choice — being second-guessed is the one thing an explicit choice must not be.
  - **AN ENV VAR REACHES ONLY THE PROCESSES YOU SPAWN — say so, and make every consumer of the
    derived path agree (2026-08-04, moving model weights into the app folder):** `OLLAMA_MODELS`
    and `HF_HOME` are the whole mechanism for relocating local model weights, which makes the
    change look trivial. It is not, for two reasons. (a) A systemd/launchd-managed daemon has
    its own environment, so the setting cannot reach it; reporting the CONFIGURED path as
    though it were the live one is the fabrication here — an operator whose models are still in
    `~/.ollama` would have no way to tell the setting from a failure. Report configured AND
    detected as separate facts. (b) **COUNT THE CALL SITES THAT DERIVE THE SAME PATH.** Three
    had to agree — the cache PROBE, the weights DOWNLOAD, and the server SPAWN — and pointing
    only the spawn at the new directory would make the probe report "not downloaded" for
    weights that are present, so a guard built on that probe refuses a start that would have
    worked. Nothing about that failure looks like a path bug from outside. Route all of them
    through one resolver and make the agreement a test. And an operator-set value is used
    untouched: relocating several GB because an app preferred its own folder is a surprise,
    not a default.
  - **A JOIN KEY THAT IS ALSO THE PAYLOAD'S ONLY IDENTITY MUST FAIL LOUDLY WHEN IT DANGLES
    (2026-08-04, the dual-backend model catalogue):** composing a view over a dated catalogue
    is the right way to avoid re-typing identifiers that a freshness test governs — but the
    rows had no identity except their tag, so the join is BY tag, so a rename upstream
    (`granite4.1:3b` → `granite4.2:3b`) leaves the reference dangling. The first cut returned
    an empty row, and the model then rendered unavailable **with no reason at all** — a silent
    disappearance from the operator's list, which is strictly worse than the rename. Report a
    missed join by name as catalogue drift: honest, and the fastest possible signal that two
    catalogues have diverged. GENERAL FORM: when you join on a value rather than a surrogate
    key, the miss case is not "empty", it is "these two sources no longer agree".
  - **A DIAGNOSTIC STATE WITH NO CALLER IN THE DECISION PATH IS A DEAD END — and a comment
    naming it is not a caller (2026-08-04, "vLLM doesn't seem to start"):**
    `vllm_lifecycle.start_outcome()` was built two days earlier precisely to separate a vLLM
    that is still loading from one that has already died, after a field report of ten retries
    against a dead server. It had exactly one caller: the status payload. `ensure_running`,
    the one place whose decision depends on the difference, carried the comment *"its own
    start_outcome() is the tri-state that tells ready from still-loading from already-dead;
    do not guess here"* — and then guessed on the next line, taking `Popen` succeeding as the
    start succeeding. A child that died during engine init reported `started: True`, the
    coordinator's gate accepted it, and the sweep burned its whole retry budget. RULE: after
    building a state that exists to expose a failure, grep for its consumers before calling
    the fix shipped; if the only reader is a status endpoint, the failure is still invisible
    where it matters. Same family as the machine-readable 409 whose `acknowledgeable` flag no
    caller ever sent. COROLLARY on the fix: a watch window must be bounded by what the failure
    ACTUALLY costs — the startup deaths that matter (port collision, CUDA init, gated repo,
    import error) all land within a second or two, so six seconds separates them from a
    genuine tens-of-seconds model load without making a button wait for one.
  - **WHEN A NARROW HELPER CORRECTLY RETURNS None, LOOK AT WHAT THE CALLER PUTS IN ITS PLACE
    (2026-08-04, the same report):** `outage_reason()` answers backend REACHABILITY and
    returns None whenever a backend can be reached — which is right, and which is the COMMON
    case for the failures that actually reach a sweep loop: a reachable Ollama with no model
    pulled, a 500 from a context overflow, a vLLM whose port opened before its engine died.
    All four loops then fell through to the words "local model hiccup", naming the symptom
    while discarding the exception they were holding one variable away. So the enrichment
    layer built to explain outages became the hiding place for the outages it could not
    explain — the K2 shape again, one level up: not a crashing resolver, a *correct* one whose
    silence was filled with a worse answer. The langdetect loop was the purest case, already
    holding the aborting event's own reason and printing over it. RULE: a fallback branch is
    part of the helper's contract; when the caller has real evidence, the evidence wins, and
    the generic phrase is what you use when there is genuinely nothing else.
  - **REDIRECTING WHERE NEW DATA LANDS MAKES EXISTING DATA INVISIBLE UNLESS THE PROBE LEARNS
    BOTH LOCATIONS (2026-08-04, a regression from that same day's model-store move):** the
    recorded env-var lesson said "count the call sites that DERIVE the same path", and all
    three were made to agree. The half not thought through is that the OLD path had several GB
    of real data behind it: pointing `HF_HOME` at the app folder made `model_cache_state()`
    read one directory and answer "not downloaded" about the other, so the activation guard
    refused a start for a model that was on the disk and told the operator they had never
    downloaded it. The fix is not to silently prefer whichever location has content (a mixed
    state that flips the moment one model lands in the new one) but to probe BOTH and say
    WHICH answered — a legacy-only copy is still refused, because the server is spawned
    pointed at the new path and would re-fetch the same weights over the clear internet, but
    for the true reason and with the way out. RULE: any change to where an app looks for data
    it did not create must enumerate what is already at the old location, and the honest
    output of that enumeration is a NAMED difference, never a silent preference. Corollary on
    not over-building: an HF cache symlinks into its own `blobs/`, so a copy that is not
    symlink-aware doubles the size or breaks the links — naming the folder is honest, and a
    move this app has not built and tested would not be.
  - **⚠ THIS SANDBOX HAS A BROWSER AND PYTHON 3.13 — the standing "browser-unverified per
    fork-3/Q6a" caveat is a HABIT, not a limit (2026-08-04, the GUI-visualization build):**
    Chromium ships at `/opt/pw-browsers/chromium-1194/chrome-linux/chrome` with
    `PLAYWRIGHT_BROWSERS_PATH` already set, and `/usr/bin/python3.13` exists even though the
    default `python3` is 3.11. So a frontend slice CAN be driven and screenshotted in-session:
    `python3.13 -m venv .venv` → `pip install -e ".[analysis]" pytest playwright` (with
    `TMPDIR` inside the repo, per the recorded pip lesson) → seed a SYNTHETIC corpus through
    the real `index_article` → `uvicorn` on a loopback port with `OO_DATA_DIR` +
    `OO_DB_PLAINTEXT=1` + `OO_NO_SCHEDULER=1` → `pw.chromium.launch(executable_path=…)`. The
    full suite runs too (no `--timeout` flag: pytest-timeout is absent). FOUR DEFECTS in this
    slice were invisible to source reading and obvious in a screenshot: a flex container
    DISCARDS the whitespace between its items (so `${label} <span>n=…</span>` rendered
    "series 1n=40" — use `gap`), separate series' bars drawn at the same x read as a STACKED
    total nobody computed, a clamp meant to stop an edge group being clipped instead collapsed
    two members onto one pixel and hid a real measurement, and Arabic showed English method
    text under translated caveats. Also: apply greyscale as a BROWSER filter
    (`documentElement.style.filter = 'grayscale(1)'`) so what is judged is rendered pixels, and
    hand the images to adversarial subagents — three critics reading PNGs found things numbers
    could not, including one that correctly REFUSED to certify the gap-rendering path because
    the test data contained no gaps ("an untested code path, not a pass").
  - **THE i18n DOM WALKER MATCHES A TEXT NODE EXACTLY, so a label and its sentence must be
    SEPARATE ELEMENTS — and a sentence the server COMPOSES can never be translated at all
    (2026-08-04, the same slice, caught only in Arabic):** `figMeta` emitted
    `` `${t("Method")}: ${env.method}` `` as one text node, so the node was
    "Method: Articles grouped by…", which is not a key, and eleven locales showed English
    honesty text under correctly-translated Arabic caveats. Two elements, two exact matches.
    The sibling half is worse: `source_concentration` appended a basis-dependent clause to its
    method, making the string DIFFERENT on every corpus, so no key could ever match — the
    varying part must travel as a FIELD the frontend composes from its own keyed template (the
    `OOI18N.tf` discipline). THIRD, and the reason it survived one round of fixing: a Library
    view renders ONCE (`_libViewLoaded` is a `Set`), and an already-INTERPOLATED `tf()` string
    is no longer a key, so it stays frozen in whatever locale first rendered it — the recorded
    `home-lead-title-frozen-locale` bug class, which the `oo:langchange` handler exists to fix
    and which every new render-once surface must register with. THE DURABLE FIX IS A GUARD, not
    memory: a test drives every figure and fails if any `method`/`caveat` is absent from any of
    the twelve locale files, naming the figure, the field and the locale. Mutation-checked.
  - **COLOUR-ONLY SERIES IDENTITY IS REFUTABLE BY ARITHMETIC, AND THE REPLACEMENT CHANNELS MUST
    DIFFER BY FAMILY (2026-08-04):** `ooChart` distinguished series by a 4-colour cycle and
    nothing else. The decisive number is not the background contrast (though three of those
    four were below the WCAG 1.4.11 3:1 non-text bar on `--panel2`, the background the canvas
    actually paints) — it is that the worst MUTUAL contrast between two theme-derived series
    colours is **1.00:1, luminance-identical**, because pulling each hue toward `--fg` to clear
    the background bar necessarily converges them. That is a proof, not a preference: colour
    cannot carry identity, so dash and marker are load-bearing. TWO WAYS THE REPLACEMENT
    CHANNELS COLLIDE ANYWAY, both shipped for one iteration and both caught by a critic reading
    pixels: distinct dash NUMBERS are not distinct dash PATTERNS (`[2,3]` vs `[1,3]` both read
    as "the dotted one"; `[3,7]` is another pattern's rhythm at half the frequency — scaling
    does not make a new one, so compare the ordered sequence of mark-length CLASSES), and a
    marker must not be another marker ROTATED (a diamond IS a square at 45°, and at ~6px they
    are a coin flip). Also: the legend swatch must show the pattern it teaches — a marker
    centred on a 30px swatch covered exactly the stretch where a dash-dot cycle distinguishes
    itself, so that key rendered as a solid line.
  - **A FIX FOR A CLIPPED GROUP MEMBER MUST CLAMP THE GROUP, NOT EACH MEMBER (2026-08-04):**
    grouped bars at the first/last time slot fell half outside the plot, so each series' own
    left edge was clamped into the plot area. At the first slot that put series 0 and series 1
    on the IDENTICAL pixel, the later drew over the earlier, and a real measurement became
    invisible and un-hatched — the very failure the clamp was added to prevent, reached by
    another route. Clamp the group's left edge once and offset members within it; then no two
    sub-slots can coincide by construction. GENERAL FORM: when a fix bounds a POSITION, ask
    what happens when two things are bounded to the same bound.
  - **REUSING A MAINTAINED COUNTER MEANS INHERITING ITS DOCUMENTED FALLBACK (2026-08-04):**
    a new figure filtered `Source.article_count > 0`. That column is NULLABLE and is NULL on any
    corpus the bounded background reconcile has never touched, so the figure returned n=0
    against 180 real articles across 10 sources — not a missing caveat but a false statement,
    "no source holds any article". The fallback already existed at `src/api/source_io.py:163-177`
    (counter when set, live `COUNT` otherwise) with its three-state basis vocabulary
    `live`/`exact`/`estimated`, and was simply not reached for. COROLLARY on aggregating a
    basis: ONE estimated or live member makes the WHOLE aggregate that basis — reporting
    "exact" because most members were exact is the fabricated pass this project names
    elsewhere. And a `None` that means UNDEFINED must never render as 0 when 0 is a real value
    with the opposite meaning: `gini()` returns `None` below n=2, and a Gini of 0 is perfect
    EQUALITY.
  - **TWO SURFACES CAN DISAGREE ABOUT WHAT "JUNE" MEANS, AND NEITHER IS WRONG — SO THE FIX IS
    A DISCLOSURE, NOT A COLUMN CHANGE (2026-08-04, found while scoping the chart brush):**
    `KeywordMention.observed_on` is `(published_at or created_at).date()` (`store.py:284`) —
    a coalesce, and the x-axis of every keyword trend chart — while the date filter behind
    Advanced search and `_resolve_corpus` is `Article.published_at` alone
    (`main.py:818-821`). So an article whose publish date could not be extracted is PLOTTED
    at its ingest date and EXCLUDED by a filter over that same day; live-reproduced, two
    articles on one chart day, one returned. The reflex is to coalesce the filter, and that
    is the MIRROR DEFECT: an article ingested in June with no publish date may have been
    published in 2019, so folding `created_at` into a filter labelled "published between X
    and Y" fabricates an INCLUSION exactly as the present behaviour fabricates an ABSENCE.
    Both directions are dishonest and the conservative column is the defensible one, which
    means the repair is (a) disclose the count dropped for want of a publish date — derivable
    with no new storage — and (b) make the two surfaces agree about which window is on
    screen. GENERAL FORM: when two surfaces compute the same-sounding quantity by different
    rules, check whether EITHER rule is defensible before changing one to match the other;
    if both are, the disagreement is a labelling and disclosure problem, and "make them the
    same" silently picks a side. COROLLARY that decided a design: anything that turns a chart
    selection into a corpus must carry the ids of the buckets the chart actually drew rather
    than re-resolving the range through a filter — then it inherits the chart's own
    definition of time by construction and the disagreement cannot reach it. Same pass: a
    trend bar is a MENTION total, not an article count (`trend()` sums
    `KeywordMention.count`), so such a readout owes both numbers.
  - **A PROBE'S DATA DISTRIBUTION IS PART OF THE LOOKALIKE — and "fold the predicate into the
    GROUP BY" only works when the predicate column is IN the index (2026-08-04, scoping the
    duplicate-group figure):** the recorded lesson says a hand-written SQL probe differs from
    the shipped query in table stats, ANALYZE state and which other indexes exist. A fourth
    axis: the ROW DISTRIBUTION. Measuring a two-step design (a covering aggregate to find
    canonical-URL collisions, then a bounded `IN (…)` to apply the quarantine filter to just
    the colliders) produced a **bare `SCAN articles`** — which reads as a damning result until
    you look at the fixture: 32 collision groups out of 40, so the planner correctly scanned
    rather than index-seek 112 of 120 rows. At a realistic collision rate it may plan the
    opposite way. So a plan measured over a fixture whose DENSITY is unrepresentative is
    evidence about the fixture, not about production — state which questions the probe
    settles and which it does not, rather than reporting every line of its output with equal
    confidence. SECOND HALF, a genuine limit on a recorded trick: the 2026-08-04 per-language
    fix folded a predicate into the GROUP BY so the planner had no escape, and that does NOT
    transfer here — it changed nothing and added a temp B-tree, because the problem was never
    index CHOICE but that `quarantined` is absent from every candidate index, so any reference
    to it costs a row fetch (a decrypt per row under SQLCipher). When a predicate column is
    not in the index, the only real options are a composite covering index (a migration) or
    not referencing the column in that query at all; grouping on it is a non-fix that looks
    like one.
  - **A GUESS ABOUT *WHERE* THE REASON IS WILL BE WRONG TWICE BEFORE IT IS RIGHT — SEARCH
    INSTEAD (2026-08-04, the vLLM server log):** this repo fixed the same instrument twice
    on reasoning rather than evidence. First it kept the log's TAIL; then it kept both
    ends, on the correct observation that "EngineCore is a CHILD process, so a startup
    failure prints its traceback FIRST". In the operator's real 46,455-byte log the cause
    — `CUDA error: out of memory` — sat at byte 26,914: past the 8,000-byte head, before
    the 8,000-byte tail. The head was vLLM's banner and a config dump; the tail was the
    sentence "See root cause above." Both fixes reasoned about WHERE a reason lives in a
    file whose shape belongs to someone else's program. The fix is to SEARCH for known
    fatal signatures, MOST SPECIFIC FIRST — the wrapper that says "see the root cause
    above" matches too, and matching it first hands back the sentence whose entire content
    is that the answer is elsewhere — and to fall back to the head only when nothing
    matches, since a fabricated diagnosis is worse than an honest excerpt.
  - **A HEADROOM EXPRESSED AS A FRACTION OF A RESOURCE GIVES THE LEAST TO WHOEVER HAS THE
    LEAST (2026-08-04, the vLLM CUDA OOM):** `compute_server_args` derived
    `gpu_memory_utilization` from weights + KV, adding the fixed weight reserve back at
    full value while discounting only the remainder. The algebra came out as
    `0.85 + 0.75/vram`, i.e. utilization RISING as the card shrank — 0.95 on a 6 GiB card,
    0.86 on an 80 GiB one, and 0.94 on the 8 GiB card the app is designed around, leaving
    0.48 GiB free. CUDA-graph capture then died at 86% of 51 graphs. THE RULE: a reserve
    for something whose cost does NOT scale with the resource (a graph pool scales with
    the model and the graph count; fragmentation scales with neither) must be ABSOLUTE,
    with the fraction as a floor above it, and capped at the upstream default — being
    bolder than upstream on the smallest hardware is the wrong direction to be bold in.
    TWO COROLLARIES. Pin it as a MONOTONICITY, strictly, and additionally assert the
    series actually VARIES: the recorded lesson that a clamped value satisfies `>=` with a
    constant applies here too. And a first mutation attempt PASSED — because the mutant I
    wrote was not the old formula, only something else that happened to stay monotone; a
    mutation test is only evidence when the mutant genuinely reproduces the defect, so
    derive it from the real prior code rather than from memory of its shape.
  - **DO NOT REGRESS A NUMBER THE MEASUREMENT SAYS WORKS, EVEN TOWARD SAFETY (same fix):**
    the obvious tidy-up was to re-derive `max_model_len` from the new, lower utilization so
    both values came from one budget. That would have dropped it 5120 → 2048 on the field
    card — and the field run had served 5120 with 24,960 tokens of KV (4.88x concurrency),
    so that value was demonstrably not what failed. Internal consistency is a reason to
    rewrite a METHOD STRING, never a reason to tighten a figure the evidence exonerates;
    conservatism applied where the measurement already answered is just a worse answer with
    a better motive.
  - **WHEN TWO FUNCTIONS ANSWER ONE QUESTION FROM DIFFERENT SOURCES, THE MISMATCH SHIPS AS
    A CONFIDENT WRONG SENTENCE (2026-08-04, "Model 'mistralai/Ministral-3-3B-Instruct-2512'
    is not installed. Run: ollama pull mistralai/Ministral-3-3B-Instruct-2512"):** that is
    an HF repo id handed to OLLAMA, on a machine where the Ollama model was installed all
    along — and Ollama's message was perfectly correct about the question it was asked.
    `active_model()` resolved the backend from the STORED `llm_backend` setting; the sweeps
    called `get_client_with_name()` with no argument, and `resolve_backend()` read only
    `OO_LLM_BACKEND`. With the setting on "vllm" and its server not running, the MODEL came
    from one answer and the CLIENT from the other. THE FIX IS NOT TO BRIDGE THE CALL SITES
    — that is an enumeration, and the recorded backstop lesson says enumerations are wrong.
    Read the setting in the ONE place the decision is made, so the operator's choice is
    authoritative by construction; and where a caller ALREADY knows the answer (the
    coordinator knows which backend `ensure_running` actually brought up), let it pass that
    in rather than re-resolving, because the two calls can also disagree across a race or a
    fallback. GENERAL FORM: a value that is only meaningful beside another value (a model
    id beside its backend, a unit beside its number) must travel WITH it, never be looked
    up twice.
  - **A CAPABILITY ON A SURFACE WITH NO CALLERS IS A GUARD THAT PASSES WHILE PROVING
    NOTHING — and three more ways a locally-correct UI change claims something false
    (2026-08-04, the chart brush):** four defects from one slice, none visible in a diff.
    (a) **THE SHARPEST.** I wired brush-to-select onto `#corpus-chart` because it is a
    single-keyword article-time chart and qualified on every stated criterion — but
    `corpusTab` has **no callers** (the retired `#corpus-win` modal), so the capability was
    unreachable, and my own guard asserting both wired charts passed while half of it
    described something no reader can do. Before wiring a feature onto a surface, grep for
    the surface's CALLERS, not just its correctness; and a guard that enumerates surfaces
    must be checked against reachability or it certifies dead code. (b) **A CONTROL'S
    PREVIEW AND ITS ACTION MUST SHARE ONE FORMATTER.** The live brush readout used `fmtT`,
    which picks granularity from the whole axis span, so it rendered "2026-05" while the
    brush selected `2026-05-10` — the reader was shown a month and handed a span starting
    mid-month, with no way to tell before releasing. Two formatters for one quantity drift
    by construction; hoist one and both agree. (c) **A COLOUR TOKEN CARRIES MEANING, so
    reusing it for the opposite meaning gives one signal two readings** — the selection band
    was painted with `--fig-gap`, the ABSENCE token, so a selection and a hole were the same
    grey and a reader who had learned "grey means nothing recorded here" would read a
    selection as missing data. Selection is an ACTIVE state and belongs to the accent.
    (d) **A VISUAL CHECK CAPTURED AT THE WRONG MOMENT TESTS NOTHING** — greyscale was applied
    after the click navigated away, so "the band is visible without colour" had never been
    tested at all despite a greyscale screenshot existing. Captured mid-drag it does hold,
    but through the explicit EDGES; the translucent fill is faint once desaturated, which
    means the edges were load-bearing rather than decorative. Mid-interaction states need
    mid-interaction capture, and an existing screenshot is not evidence that the thing you
    care about was in it.
  - **APPLYING HALF A RECORDED LESSON IS HOW A DEFECT SURVIVES REVIEW — and a fixture that
    differs from production in the one dimension the lesson is about turns the guard into
    an accomplice (2026-08-04, the brush bucket snap):** the note I had just written said a
    chart selection must inherit the chart's OWN definition of time, and I got the column
    right (resolve on `observed_on`, never through the `published_at` filter) and the
    GRANULARITY wrong (resolve by day against a chart drawn in weeks). A week bar is drawn
    at its Monday, so a day-precise span cuts one in half or misses it while it still looks
    inside the band: four visible bars summing to 65 mentions were reported as 50, because a
    bar drawn at 2026-06-22 whose every mention fell on 06-28 sat inside a span ending 06-26.
    **THE PROCESS FAILURE IS WORTH MORE THAN THE FIX.** An adversarial critic read the
    screenshot, estimated ~65 against the reported 50 and suspected an off-by-one; I
    re-measured, got 50, and told the user its arithmetic was refuted — having measured with
    `bucket=day` while the shipped chart uses `bucket=week`. The critic was reading the bars
    actually on screen and was closer to right than my measurement. So: when a
    pixel-reading critic's arithmetic disagrees with your query, the first suspect is the
    PARAMETERS of your query, not their eyes. And SIXTEEN tests over the resolver passed,
    including one that pins exactly this property — every fixture used the default `day`
    bucket, so the invariant was held and the defect was invisible. This is the recorded "a
    probe's data distribution is part of the lookalike" lesson one level up: it is not only
    row density that makes a fixture a lookalike, it is any parameter the production caller
    sets and the fixture leaves at its default. Parametrise the guard over every value the
    shipped call sites actually pass (`day`/`week`/`month` here), and check what the call
    site passes rather than what the function defaults to. The fix's own shape generalises:
    a selection over a bucketed axis can only honestly return whole buckets, the bucket
    travels with the request, the response reports the EFFECTIVE span rather than the raw
    input, and the client preview snaps through the same widening — a preview that shows the
    raw gesture while the result reports a widened one is two answers to one action, the
    same divergence the shared day formatter had already fixed once in this very component.
  - **A MESSAGE CAN BE ENTIRELY TRUE AND STILL NOT BE THE ANSWER — and the third read of
    the same tri-state is where that finally showed (2026-08-04, "explicit override
    (vllm), but its server is NOT running — Ollama IS reachable; clear the override to
    use it"):** every clause was accurate. The engine had nonetheless been STARTED and had
    EXITED about a minute later — a vLLM reaches CUDA-graph capture around t+67s, far past
    any click-time confirm window — and `start_outcome()` had recorded exactly that while
    `outage_reason()` reported REACHABILITY instead. This is the "local model hiccup"
    defect one level deeper: not a missing fact, a correct-but-wrong-question fact
    published where a cause belonged. `start_outcome()` has now needed reading in THREE
    places (the start itself, the plan on every poll, and the sweep's retry line); after
    building a state that exposes a failure, the consumers are not one call site but every
    surface an operator can see the failure ON. THE TWIN IS LOAD-BEARING: only `exited`
    may be called a death — a still-loading engine keeps the generic wording, because the
    backoff exists to wait a model load out and naming that a failure is the
    fabricated-failure mirror of the fabricated-success being fixed. SECOND HALF, a
    separate class: the advice had gone stale. "clear the override to use it" was the only
    thing on offer when nothing in the app could start a backend; once `activation` could,
    it was telling operators to abandon the choice they had deliberately made. When a
    capability lands, grep the strings that were written around its ABSENCE — and pin the
    fix by ORDER, not presence, since both options should still be offered.
  - **AN ADVICE STRING IS A CALLER TOO — "start it from Settings" is a dead end when the
    app is the only thing that can press the button (2026-08-04, the fourth read of the
    same tri-state):** the recorded lesson says a diagnostic state with no caller in the
    decision path is a dead end, and names a status endpoint as the tell. This is the same
    defect wearing a sentence: `ensure_running()` had exactly two callers and BOTH are a
    human clicking — the coordinator's run endpoint and Settings → AI's start button — so
    on a machine whose operator had chosen vLLM and left the app running, four sweeps spent
    their whole retry budget while the message correctly, and forever, told them to go and
    do the one thing the app was in a position to do. The earlier fix gave the coordinator's
    ENTRY an activation call; nothing gave the RECOVERY path one, and a run that is already
    going is exactly where a backend goes down. TWO RULES. (a) After building an action,
    grep for the paths that DETECT the condition it answers, not just the ones that start
    the work — an entry-point fix does not reach a loop that has already entered. (b) The
    recovery must return WORDS and never a verdict (a reload, a restart and a busy server
    answer a probe identically), so the budget and control flow stay exactly where they
    were; and the words must SUPERSEDE the resolver's advice when the app has acted, because
    "start it yourself" was written for a world where nothing could — the stale-advice
    lesson, one surface over. TWO DEFECTS THE BUILD ITSELF SURFACED, both worth more than
    the feature: `ensure_running` read `start()`'s word **"already running"** as `ready`,
    but that word means `process_alive()` and the branch is only reached AFTER the health
    probe said the backend does not answer — so a loading engine reported as SERVING, and
    the recovery path would have hit it on its very first retry (live-reproduced; a word
    about a process is not a probe of the port). And `_recovery_last_at = 0.0` made the
    FIRST attempt of every process read as "attempted moments ago", because
    `time.monotonic()`'s reference point is undefined and small on a fresh boot — a
    sentinel that is also a legal value, the `.get(key, 0)` family again, caught by an
    EXISTING ride-along test rather than by any of the eight I wrote for the change.
    THIRD, and the one that would have escaped this box entirely: **adding an ACTION to
    a production failure path makes it a side effect of every test that drives that
    path.** Neither backend is installed in this sandbox, so the recovery is inert here
    and the suite stayed green — proving nothing. A throwaway pytest plugin that faked
    "both installed" and recorded every `start()` call found one real
    `ollama_lifecycle.start()`, i.e. a suite run on any developer machine that HAS
    Ollama would have left a daemon behind. The fix is not to patch the tests that
    happen to reach it (the enumeration again) but a real operator opt-out
    (`OO_LLM_AUTOSTART=0`) that `conftest` sets session-wide, exactly as it already does
    for `OO_NO_SCHEDULER` and `OO_AUTOSEED` — and the tests that are ABOUT the start
    turn it back on. GENERAL FORM: when a change makes a code path DO something rather
    than merely report, ask what the test suite now does on a machine unlike this one,
    and measure it with a plugin rather than reasoning about it.
  - **A METRIC KEY CAN BE A MISNOMER THAT MUST NOT BE "FIXED" BY REDEFINING IT — and a fix
    that makes two texts agree can do it by DELETING one (2026-08-04, the Library
    qualification tile):** `_count_sources_never_judged` counts `status == 'unqualified'`,
    while `log_no_evidence_attempts` writes a `no_evidence` attempt row and DELIBERATELY
    leaves status alone (its whole reason for existing, the 2026-07-23 livelock fix) — so an
    ENABLED source with no feed is tried on every rotation of the queue and was counted, and
    labelled, "Never judged". The tempting repair is to make the key mean its name; that is
    wrong, because the snapshot store has INFINITE retention and redefining an existing key
    makes its own history incomparable with its future, a silent break in a time series
    layered on top of the first defect. Freeze the definition, fix the LABEL, add a new key
    for the honest count. GENERAL FORM: when a name and a measurement disagree and the
    measurement has history, the name is the part you are allowed to change. SECOND HALF, in
    the same tile: an earlier fix had cured a real staleness bug (a per-mode caveat
    contradicting the scale hint above it) by writing `note.textContent = HINTS[mode] ||
    caveat` — and `HINTS[mode]` is non-empty for all three modes, so `|| caveat` was DEAD
    CODE and every `{scales: true}` caller silently lost its caveat, two of them
    mode-INDEPENDENT statements with nothing to do with the toggle. Two statements of
    different KINDS need two slots; through one slot the volatile one always wins. Found by
    opening the modal and reading its last line, which was the hint where the caveat should
    have been. COROLLARY on recurrence: the frozen-locale class (an interpolated `tf()`
    string is not a key the DOM walker can match, and a Library view renders once) recurred
    the moment a new interpolated string was added to a render-once surface — even though
    `oo:langchange` already registered a SIBLING view for exactly this reason with the reason
    written above it. A recorded lesson does not propagate itself to the next surface; only a
    guard does.
  - **CLAMPING log(0) FABRICATES AN AXIS, AND REFUSING A MODE MEANS NOT OFFERING IT
    (2026-08-04, ooChart's logY):** `vt(v) = log10(Math.max(v, 1e-9))` reads as defensive
    coding, and the guard pinning it even said "never crash on a zero/negative". Measured on
    four integer series in 0..6 with zeros at the start: the axis spanned log-space
    **−9..0.78**, so the real differences occupied about **5% of the plot**, `honestTicks`
    labelled log-space ticks back through `vtInv` and printed **`0.003` and TWO `0`
    gridlines** — none of them values a count can take — and every true zero was drawn as a
    plotted point on the floor with a line through it. Invisible for months because `logY`
    shipped for the markets boards, where an index value is never 0; the caller whose values
    legitimately start at zero is what exposes it. Refuse the mode when the data cannot
    support it, fall back to the axis the data deserves (zero-based, integer ticks for
    counts), and SAY so. THEN THE FOLLOW-ON, which is the part that generalises: leaving the
    control enabled put two statements on screen at once — a hint claiming "equal ratios are
    equal distances" above a chart that had drawn linear and said so underneath. The
    renderer-level refusal is the load-bearing guard because it cannot be bypassed; disabling
    the control is what makes the contradiction unreachable. And TEST THE OTHER DIRECTION in
    a browser: a positive-only series must still get a working log mode, or a fabricated-axis
    fix has quietly removed a real capability.
  - **A SENTENCE WITH AN INTERPOLATED COUNT CANNOT CONJUGATE, AND AN LTR-SHAPED VALUE NEEDS
    A BIDI ISOLATE (2026-08-04, the same tile; both caught by adversarial critics reading
    screenshots, neither visible to any mechanical check):** the note read "**1 have** never
    been attempted", and the French carried the identical error — which is the tell that it
    is the TEMPLATE, not the translation. Per-form keys are not the answer either: Russian
    has three plural forms and Arabic six, and this app has no CLDR plural rules. Phrase a
    value-bearing string as **label:value** and nothing conjugates, so every locale is
    correct by construction (the participles in the fr/es/pt renderings agree with the
    CATEGORY, not the number, which is why they survive). No mechanical check could see the
    original: every locale was present, non-empty, in the right script, and a plausible
    translation. SECOND: interpolating an ISO timestamp into a translated sentence renders in
    visual order **`.07T18:00:00-07-2026`** in Arabic — the year at the wrong end, a MISREAD
    date rather than an ugly one (measured by reading each character's rendered x position in
    the real page, not assumed). `U+2068` FIRST STRONG ISOLATE … `U+2069` POP DIRECTIONAL
    ISOLATE around the value fixes it; they are plain characters so they survive `esc()`, and
    they are inert in LTR locales. It is PUNCTUATION-JOINED runs that need it — dates,
    versions, IDs, URLs, ranges — never a bare number, so a lone count does not get one.
  - **BRACE-MATCHING A LITERAL IS NOT ENOUGH — a `}` INSIDE A STRING TRUNCATES IT
    (2026-08-04, the fifth slicer shape):** the slicing ratchet rejected three hand-rolled
    slices in a new test file (the class it exists to stop, written by someone who had read
    it), and writing the shared shape it asked for immediately exposed that the obvious
    implementation is wrong: `const L = {a: "x}y", …}` truncates at the brace inside the
    string, so the slice ends after one key and every assertion over the fragment passes for
    free — the same failure the module is about, one level down. `object_literal` therefore
    landed with a string-, template-literal- and comment-aware scanner that `array_literal`
    now shares (template literals additionally nest through `${…}`; a JS regex literal
    containing an unbalanced delimiter is an honest, stated limit that raises rather than
    truncating). The test that proves it is the one that failed against my own first
    implementation. And prefer being stopped by a ratchet over lowering its budget: 233
    unchanged.
  - **A PROBE WHOSE WINDOW IS SHORTER THAN THE FAILURE CANNOT TELL A CRASH LOOP FROM
    PROGRESS — and the log that would say so is overwritten by the next attempt
    (2026-08-05, the fifth round of "vLLM won't start"):** three instruments each held
    part of the answer and none held it long enough. `start_outcome()` is process-local
    and keeps only the LAST spawn, so a restart erases every death; `server.log` is
    opened `"wb"` per start, so each attempt DESTROYS the evidence of the one before
    it — the file whose entire job is explaining a failure is deleted by the next
    failure; and the recovery re-attempts every 30 s while a load takes 60–90 s, so a
    server dying at t+40 is respawned at t+60 and reports "starting" forever. The
    operator read steady progress off a crash loop, and every word of it was
    individually true. THE FIX IS A JOURNAL, and the reason to reach for one is that
    the artifact which finally cracked this chain was `install_attempts.jsonl` — a
    bounded append-only record already in the same module, whose value was proven the
    round before. GENERAL FORM: when a diagnosis needs *what happened over time* rather
    than *what is true now*, no amount of improving the point-in-time probe will do it;
    and any per-attempt log opened for truncation is a point-in-time probe wearing a
    file's clothes. TWO DESIGN POINTS worth reusing: recording a TRANSITION inside a
    read-only probe (`start_outcome`) is a journal rather than a side effect — it is the
    only place an exit is reliably observed — provided it is idempotent per pid, so a
    status endpoint polled a hundred times writes one line. And the verdict threshold
    is TWO exits, not one: an operator who has just FIXED the cause must get a fair
    start rather than a verdict inherited from the attempt they repaired, which is the
    fabricated-failure twin of the fabricated-progress being fixed.
  - **"EVERYTHING LIVES IN THE APP FOLDER" IS A CLAIM ABOUT EVERY PROCESS YOU SPAWN, AND
    ONE REDIRECTED CACHE DOES NOT MAKE IT TRUE (2026-08-05, from an operator's own
    provisioning scripts):** the model-store move pointed `HF_HOME` at the app's data
    folder and every test agreed the WEIGHTS landed there — while torch's Inductor cache,
    Triton's kernel cache, the CUDA JIT cache and vLLM's own cache/config roots all still
    wrote into `$HOME` on first run, GB-capable and invisible. The scripts said it in one
    line: *"Without these, torch / Triton / Inductor / NVIDIA / uv all write into $HOME and
    your self-contained app folder is a fiction."* GENERAL FORM: when you relocate one
    thing a subprocess writes, enumerate the OTHERS by asking what the whole dependency
    stack caches, not what your feature downloads. THREE THINGS THE FIX TURNED ON: the
    redirect is SERVE-only, because `XDG_CACHE_HOME` also governs pip's wheel cache and
    moving that would make the next reinstall re-download several GB it already has —
    which is exactly why the operator's reinstall took seconds, so the split has a
    measurement behind it, and it needs its own twin test or a later tidy-up will
    "simplify" it into the install path. An operator-set value must win, since someone who
    put Triton's cache on a big disk did that deliberately. And **the guard belongs on the
    RESOLVER, not only on the operation** — `data_dir()` CREATES the directory it returns,
    so guarding each `target.mkdir` while calling `_cache_root()` unguarded put the failure
    one call *earlier* than the guard, and on a read-only volume the whole start died for
    want of a cache. An existing test about something else entirely (losing the log must
    never block a start) is what caught it, which is the argument for running the
    neighbouring suites rather than only the ones you wrote.
  - **A BUDGET DERIVED FROM A RESOURCE'S *TOTAL* DESCRIBES A MACHINE THAT MAY NOT EXIST —
    and the operator's "it was never saturated" is what identified the mechanism
    (2026-08-05, five vLLM starts exiting 1 in ten minutes):** `detect_gpu()` read
    `memory.total`, so `compute_server_args` sized vLLM's budget for the whole 8 GB card
    while Ollama sat on several of those gigabytes serving the very sweeps that were
    waiting for vLLM. Nothing sequenced them: `ollama_lifecycle` deliberately has no
    `stop()` (the daemon is usually a system service the app does not own), and that
    correct constraint had silently become "no arbitration at all". THE DETAIL THAT
    CRACKED IT was the one that looked like a refutation — the operator noted ~900 MB
    still free at the peak, which rules out a plain OOM and points instead at vLLM's own
    startup check: `gpu_memory_utilization` is a fraction of the TOTAL, so a request for
    0.81 of a card with 3.6 GB free is refused *before* anything fills, and that refusal
    reaches the caller as exit code 1. When a reported detail seems to weaken your
    hypothesis, ask which mechanism it is *consistent* with rather than discarding it.
    FOUR RULES FROM THE FIX. (a) Size from what is FREE, but keep the fraction in the
    consumer's own unit (`(free − reserve) / total`) — mixing the two is how a budget
    that looks conservative asks for memory nobody has. (b) A MISSING reading is not a
    reading of zero: `vram_free_mb=None` must leave the old total-derived answer
    byte-identical, or every machine whose driver omits the field gets refused. (c) The
    floor that protects an *unmeasured* guess must NOT be applied to a *measured* one —
    flooring a real 0.26 back up to 0.50 reinstates the exact request being fixed; let
    the small number become a named refusal upstream instead. (d) The release goes in
    `start()`, not in the activation orchestrator, because `POST /api/llm/vllm/start`
    reaches `start()` directly — the standing "gate EVERY entry point" lesson, and the
    reason the fix is one chokepoint rather than two call sites. COROLLARY on shape: with
    `stop()` off the table, the release had to be a request the daemon already exposes
    (`keep_alive: 0` drops residency, Ollama reloads on its next call), so the worst case
    is one model-load latency and nothing the operator started is ever killed. And an
    unload is ASYNCHRONOUS — poll until the free reading stops improving rather than
    measuring immediately or sleeping a fixed worst case.
  - **A LEAD MEASURED IN LINES AGAINST A BUDGET MEASURED IN CHARACTERS SPENDS THE
    WHOLE BUDGET ON CONTEXT (2026-08-06, the sixth round of "vLLM won't start"):**
    the start journal was built precisely because `server.log` is truncated on the
    next start, and it recorded ten consecutive failures without once recording a
    reason. `failure_excerpt` searched correctly, anchored correctly, and then built
    its window as "six lead lines, then everything after, truncated to `limit`" —
    but vLLM prefixes every line with `(EngineCore pid=NNNNNN) INFO MM-DD HH:MM:SS
    [file.py:NNN]`, so six lead lines cost **662 characters against the 400 the
    journal passed**. Live-reproduced: at 400 the excerpt provably never reaches the
    matched line, so every persisted record held the six lines BEFORE the error and
    never the error. The instrument built to survive the log being overwritten could
    only preserve the part that was not evidence — the K2 shape (a degrade becoming
    the hiding place for the bug it was built to survive) at the level of a window's
    arithmetic. RULE: when a bounded window must contain a specific thing, give that
    thing the budget FIRST and buy context with the remainder; and when two bounds
    are expressed in different units, convert one before trusting the pair. THE
    DISCRIMINATING TEST is the tight budget, not the generous one: raising the limit
    400→1200 also "fixes" today's log, and would break again on a longer prefix, a
    deeper stack or a smaller limit — so assert that a 200-character budget still
    reaches the failure and drops the context instead. TWO SIBLINGS from the same
    pass. **An instrument that lives inside the thing it diagnoses is destroyed by
    the first fix anyone tries**: the journal sat in `venv_dir()`, and "reinstall
    vLLM" — which deletes the venv — is the first thing an operator does when a
    server will not start, so the record was erased by the response the failure
    provokes (moved to `data_dir()`, legacy file migrated once). And **a bounded
    excerpt cannot hold a traceback anyway**, so a FAILED start now keeps its whole
    log under a swept, capped `vllm_failed_starts/`, with the newest carried IN the
    diagnostics bundle — five rounds of this were each diagnosed from an export and
    every one ended in another request for a file the export did not contain.
  - **A RESILIENCE SETTING DOES NOT SURVIVE A TOOL SWITCH — and the tool may be
    naming its own fix in a message nobody reads (2026-08-06, the aborted vLLM
    installs):** `_PIP_NET_FLAGS` raises pip's timeout to 60 s because 5–10 GB of
    wheels are exposed to a dropped link for a long time. The big install then moved
    to **uv**, which reads none of pip's flags — it takes `UV_HTTP_TIMEOUT` from the
    environment, defaults to **30 s**, and nothing set it. Two field installs aborted
    after 22 and 76 minutes, one on a 187 MiB wheel and one on a 43 MiB one, and the
    install journal had captured uv saying *"Failed to download distribution due to
    network timeout. Try increasing UV_HTTP_TIMEOUT (current value: 30s)"* — verbatim,
    both times. The operator's report was "aborted for unknown reasons", so the
    second defect is that a captured cause which never reaches a surface is not a
    captured cause. This is the recorded "a fix in the ledger does not propagate
    itself to a newer sibling module" lesson with a twist worth naming separately:
    the sibling here is not a new module but a REPLACEMENT for the hardened one, and
    a replacement inherits the requirement, not the implementation. When swapping a
    tool, enumerate what the old one was configured with and find each setting's
    equivalent — an unset knob is invisible in a diff that only shows the swap.
  - **A GUARDED CALL TO A MISREMEMBERED METHOD NAME IS INDISTINGUISHABLE FROM A JOB
    WITH NOTHING TO REPORT — and the double that was written beside it asserts the bug
    (2026-08-10, the AI check's progress line):** the worker called
    `ctx.progress(done, total, detail)` behind `if hasattr(ctx, "progress")`, and
    `JobContext`'s actual API is a keyword-only `set_progress`. The guard was doing its
    job perfectly: it saw no such method and did nothing, for every step of every run,
    so a button that runs for minutes reported no progress at all — which looks exactly
    like a slow first step. It survived review because the test's own `_Ctx` double
    carried the method I had invented, so the test PASSED while asserting a class that
    does not exist. TWO RULES. (a) A `hasattr` guard around a call you wrote is
    self-fulfilling; when the attribute is part of a class YOU control, call it
    directly and let a wrong name raise. (b) Pin a hand-written double to the real class
    with `inspect.signature` — same parameter names AND kinds — because "the double
    drifted" and "the code is wrong" produce the identical green. Same family as the
    recorded resolver-stub lesson, one level up: there the double omitted a field, here
    it invented a method. **SIBLING, from the same slice: a test that drives the LIVE
    steps of a composition is a test that pollutes whatever runs next.** Asking "does
    the one check include the perception harness?" by calling `run_ai_check(steps=None)`
    ran real inference and real DB paths, and reddened `test_doctor_healthy_returns_zero`
    in a subset — a failure in a different file, about a different subsystem, with
    nothing in it pointing back. The order of a plan is a PURE fact; give it a seam
    (`default_step_names`) so it can be asserted without executing.
  - **READING "WHAT IS SERVING" AS "WHAT IS INSTALLED" — and the hazard the correct
    answer creates (2026-08-10, the vLLM half of the bench):** `GET /v1/models` reports
    the ONE model a vLLM server was started with, because that is how vLLM works; the
    bench read it as the installed set, so an operator who had downloaded four models
    was told all four were "not-installed" while the weights sat on the disk. The fix is
    to ask the question that was meant — is it DOWNLOADED — of the weights cache. THE
    PART WORTH REMEMBERING IS WHAT THAT COSTS: once several models count as available on
    a backend that serves one at a time, benching the second without restarting the
    server sends its prompts to the first and files the answers under the second's name.
    That is a fabricated measurement no reader could later detect, so it is REFUSED by
    name rather than run — a correctness fix that widens a set owes an audit of what the
    consumers assumed about that set's size. COROLLARY on where the guard looks: the
    first cut opened its own client to ask which model was serving, which let it
    disagree with the run itself and broke a test that had injected one; ask the object
    that will actually do the work, never a second connection to the same thing.
  - **A RULING IS PINNED BY GUARDS THAT DO NOT SHARE ITS VOCABULARY — grep the test
    tree for the MODULE, never for a plausible filename (2026-08-10, adding a narrowed
    `stop()` to `ollama_lifecycle`):** the no-stop ruling was enforced by
    `test_backend_launch.py` and `test_gpu_arbitration.py`, neither of which I ran,
    because I had listed candidate suites by NAME (`test_ollama_*`, `test_vllm_*`) and
    those two are named for what they test rather than for the module they test it
    through. `grep -rln ollama_lifecycle tests/` finds them instantly. The full suite
    caught it, which is the argument for running the full suite before pushing rather
    than the files you can think of. **THE HALF WORTH MORE:** both guards were RIGHT,
    and one of them had written down what to do — *"if a stop() is ever added, it must
    only ever kill a process this app itself spawned — update this test deliberately,
    never by reflex."* A guard that anticipates its own supersession is worth writing;
    it turns a red test from an obstacle into an instruction. Both were then rewritten
    from asserting an ABSENCE (`not hasattr(mod, "stop")`, which says nothing about
    behaviour) to proving the PROPERTY — patch `os.kill`, drive the real refusal,
    assert no signal reaches a daemon the app did not spawn — which is strictly
    stronger and survives the feature existing. Prefer that shape from the start: a
    ruling about what the code must NOT DO is testable as behaviour, and expressing it
    as the absence of a function guarantees a false red the day the function is
    legitimately added.
  - **THE THREE i18n GATES ARE THREE SEPARATE CI COMMANDS — running the combined form
    locally exercises a DIFFERENT computation (2026-08-10, PR #910's first red):**
    `ci.yml` runs `--min 100`, then `--max-untranslatable N`, then
    `--max-unkeyed-t-calls N`, as three invocations. I ran
    `--audit-chrome --max-untranslatable 572 --max-unkeyed-t-calls 301` in one call, it
    printed only the unkeyed line and exited 0, and I read that as both ratchets green.
    The untranslatable count was 578 against a 572 ratchet the whole time — six new
    `title=` attributes and paragraphs, which are UI strings the DOM walker can
    translate but only once they have keys. This is the recorded `cmd | tail` lesson in
    a new costume: a gate that never says anything interesting is the one to distrust,
    and the fix is the same — reproduce each CI command VERBATIM, separately, and read
    each one's own output. COROLLARY worth keeping: a ratchet is not only a floor to
    stay under, it is a floor to LOWER. Keying the nine strings took the count 578 →
    569, three BELOW the old bar, and the script prints the new floor when it can drop
    — the step's own comment says "lower it in the same PR that adds the keys". Leaving
    the slack invites the next drift to land unseen.
    **RECURRED 2026-08-12 (PR #945), which says the entry above was missing its
    MECHANISM: gate 1 passing is not weak evidence about gate 2 — it is NO evidence,
    by construction.** `--min 100` compares the eleven locale files against `en.json`,
    so it can only ever see a key that already EXISTS; a brand-new `title=`/label/hint
    with no key at all is invisible to it and always will be. That is precisely the
    string gate 2 counts. So the two gates cannot substitute for each other in either
    direction, and "i18n was green" means nothing unless it names WHICH gate — I added
    three strings to a panel, watched `--min 100` report 100% across twelve locales,
    and pushed a tree that was three over the ratchet. The habit that actually works is
    to run gate 2 whenever a diff touches `index.html`, before the push rather than
    after CI says so. COROLLARY on the fix: keying the three brought the count back to
    exactly the bar, so there was no slack to reclaim and the ratchet stayed at 567 —
    "lower it when it can drop" is not a licence to lower it when it cannot, which
    would hand the next drift a free slot.

  - **A TERM WHOSE COUNT EQUALS THE ARTICLE COUNT IS A FACT ABOUT THE CHANNEL, NOT ABOUT
    THE CORPUS — and the argument FOR keeping it will already be written into the code
    and a passing test (2026-08-20, official-statistics series as Articles):** ruling
    5/30/31 makes each series an ordinary Article, so ~9,800 templated documents enter
    the shared keyword index. The body carried `{agency} · {series_id}`, two facts a
    reader might plausibly search for, once each; the module docstring said the
    producer's name "is exactly what ruling 30 asks for" and that the code had to stay
    because "dropping it from the body would remove it from FTS too". Measured over 1,298
    real series with the real extractor, that line was **a THIRD of the channel's entire
    term volume** (30,358 -> 20,372) and held ranks #1/#2/#3 — `world`, `bank`,
    `world bank` at 1,298 each, i.e. exactly one per article. Both halves of the argument
    were wrong differently: a per-article constant ranks by how much of ONE THING you
    have, and the code was never searchable in the keyword index at all, because the
    tokenizer splits `SP.DYN.LE00.IN` on its dots and indexes `dyn`/`le00`/`totl` — the
    DEBRIS of an identifier. **THE TELL IS THE ARITHMETIC: when a term's mention count
    equals the article count to the unit, it is scaffolding, whatever it says.** Two
    riders. (a) **Re-measure AFTER the change, not only before:** removing the line also
    collapsed the near-dup clustering that had motivated the audit — 9 clusters with a
    biggest of 36 down to 7 with a biggest of 3 — so the boilerplate was MANUFACTURING
    the similarity, not riding it, which no amount of reasoning predicted. (b) State the
    loss and CHECK the replacement: FTS covers `title, content` only, so `?query=World
    Bank` and `?query=SP.DYN.LE00.IN` now return 0, and `?source=…` / `?tags=statistics`
    were each verified to return all 1,298 rather than assumed to.

  - **A GUARD CAN BE READING THE PRODUCER'S OWN TEXT AND CALLING IT YOURS (2026-08-20,
    the same slice):** stripping the metadata line left a body of bare numbers — a value
    without its unit — so `({unit})` was appended and guarded with `"(years)" in body`.
    The mutation that DELETES the unit **passed**, because the World Bank's own label is
    "Life expectancy at birth (years)" (26 of the catalog's 36 read that way), so the
    shipped code would have printed "(years) (years)" while the test read the producer's
    parenthetical and reported success. GENERAL FORM: when your output CONCATENATES your
    text with someone else's, a fixture in which the two are indistinguishable cannot
    test which one produced the result — split the assertions by which source is supposed
    to supply it. The repair also has to key on the OTHER party's convention rather than
    a similarity heuristic: a substring check was measured and rejected because labels
    spell units out in words while the unit field uses symbols ("current US$" vs "USD",
    "metric tons per capita" vs "t/capita"), so it missed four of ten and re-introduced
    the doubling on exactly those.

  - **AN IDENTITY FALLBACK FOR A TEMPLATE IS A BROKEN FRAME, AND A HARNESS THAT DOUBLES
    THE i18n HELPERS CANNOT SEE IT (2026-08-20, same slice):** a new handler opened with
    `const tf = (window.OOI18N && OOI18N.tf) ? OOI18N.tf : ((x) => x)`, so before i18n
    loads a `tf("{created} new · …", vars)` renders the literal `{created}` to the
    reader — the broken frame the composite-string rule forbids. `_govTf` did it
    correctly thirty lines up, and a grep afterwards found this was the ONLY `((x) => x)`
    template fallback in 20,000 lines, i.e. the file's own convention was already right
    and I had written past it. What caught it was that the node harness EXTRACTS the real
    helpers from `app.js` rather than stubbing them; an identity double would have agreed
    with the defect. Reach for the module's existing helper before writing a fallback,
    and extract rather than double whatever the code under test calls.

  - **A SCRIPTED CLICK IS NOT A CLICK, AND A FALSE NEGATIVE FROM ONE IS INDISTINGUISHABLE
    FROM A DEFECT (2026-08-20, verifying the publish-anyway override):** driving the
    control with `eval_on_selector_all("#gov-grp-body button", "els => els[0].click()")`
    produced no request, no re-render and six standing refusals — which reads exactly
    like "the override is broken", and the instinct on seeing it is to go and fix code
    that is already correct. A real `page.click()` on the same selector fired it
    immediately: `allow_incomplete=true` on the wire, all six strategies computed, and
    the panel labelled itself `PARTIAL — members computed: 2 of 42` with the missing
    members named. Use the framework's own click; and when a UI check fails, rule out the
    harness before believing the finding.

  - **AN ENUMERATOR THAT DOES NOT LIST THE APP'S OWN DEFAULT MAKES THE APP BLIND TO ITS
    OWN WRITES — and the damage lands somewhere else entirely (2026-08-11, the Ollama
    store):** the 2026-08-04 move pointed a spawned daemon at `data/models/ollama`, and
    `candidate_stores()` — the function answering "where are the models" — was never
    told. So `default_store()` returned `~/.ollama` even when the app folder was the
    only populated store on the machine. The operator noticed a split; the expensive
    half was that the same function feeds the model BACKUP, which enumerated the wrong
    directory and carried NONE of their models **while reporting success**. This is the
    recorded "redirecting where new data lands makes existing data invisible" lesson
    **pointing the other way** — there the probe learned the new location and forgot the
    old one; here it learned neither, and survived a year because `store_report()` printed
    a plausible split that read as the feature working. RULE: when you redirect where
    new data lands, the same commit must update every enumerator of where data LIVES, and
    the test for it must seed BOTH locations — with only the new one populated, a
    fallback satisfies the assertion and the guard passes whether or not the enumerator
    learned anything (two of my own tests did exactly that until a mutation exposed them).
    **THE MIRROR HAZARD IS CREATED BY THE FIX**: ranking the app store first turns a
    detection heuristic into a claim it cannot support — with both folders populated it
    names the app folder whatever the running daemon is doing, so a report trusting it
    would give a clean bill of health while every pull went elsewhere. The answer is a
    MEASUREMENT, not a better heuristic: ask the daemon what it has and see which store
    holds a model the other does not — conclusive when the stores differ, honestly
    inconclusive when they are identical, and publish the heuristic's own answer beside
    it so the disagreement is visible. COROLLARY, a second self-inflicted defect from
    the same change: a helper whose default source resolves through the function you
    just re-ranked can become a **silent no-op** — the consolidate button computed
    `source = default_store()` and now got the destination, answering "nothing to do" in
    the exact split it exists for. After re-ranking a resolver, grep for callers that
    derive a *second* value from it.
  - **A GUARD OVER A CACHED-STATE CHECK IS VACUOUS UNLESS THE FIXTURE MAKES THE CACHE HIT
    (2026-08-11, the refused-switch trap):** the specialisation harness must never record
    a refused model hand-over as success, because a run whose switches silently failed
    does less work, finishes sooner, and is the fastest-looking row in the table while
    having measured a model it never loaded. I wrote the guard, wrote the mutation
    (`current = want` regardless of the outcome) — and **all 21 tests still passed**. The
    fixture used the split assignment, where the two tasks want DIFFERENT models, so the
    cached "current backend" failed to match on every phase whether or not the refusal
    was recorded; 4 switches either way. A cache-suppression bug can only be discriminated
    by a scenario where the cache would HIT, i.e. the same target requested twice in a
    row — here the one-model shape, where the second phase must try again precisely
    because the first hand-over never took. GENERAL FORM: for any "don't record X as
    done" guard, ask what the recording would SUPPRESS, and build the fixture that
    reaches the suppressed path; a scenario in which the cache always misses tests the
    surrounding loop, not the guard.
  - **A BUDGET FOR A LOOP WRAPPED IN BLANKET EXCEPTION ISOLATION CANNOT *BE* AN
    EXCEPTION (2026-08-09, the 69-minute `leads-quality.json`):** an all-diagnostics run
    hung at member 53/55 on a ~1M-article corpus, and the member was **not** unguarded —
    it runs inline under a 300 s `statement_deadline`, which fired exactly as designed,
    raising `StatementTimeout` from the next SQL statement. What it met was `run_all`'s
    per-producer `except Exception`, which exists so one bad producer can never blank
    Home. The guard fired; the isolation ate it; the loop moved to the next producer and
    did it again, once per producer, and the caller never learned anything was wrong.
    Neither half is wrong on its own — that is what makes the pair hard to see. RULE:
    when a loop is wrapped in blanket isolation, its budget must be **control flow the
    isolation cannot intercept** (a `break` in the loop that owns the budget), never a
    raised exception; and the budget must expire **before** any enclosing
    exception-based deadline, or the swallowed path is reached first anyway. Pin it with
    a reproducer that drives the *defeated* design (a producer raising the very
    exception the deadline raises, and the pass carrying on), so the reason for the
    `break` cannot later rot into "someone preferred it". SIBLING, same fix: report
    truncation in the PAYLOAD, not only a log line — otherwise a reader diffing two
    exports cannot tell a shorter FEED from a shorter RUN.
  - **A SIGNATURE TABLE IS AN ENUMERATION, SO GIVE IT A STRUCTURAL FALLBACK — and the
    wrapper is never the answer (2026-08-09, seventh round of "the log keeps the wrong
    part"):** `failure_excerpt` searches known fatal signatures, which is already the
    fix for two earlier wrong guesses about *where* a reason lives. It still missed this
    one, because the cause was new: the nvcc `RuntimeError` sat at byte 26,370 of 45,782
    — outside the retained head AND tail — and with no matching signature the search
    fell through to the generic `Traceback (most recent call last)` entry, whose window
    is the TOP of a stack while the reason is 115 lines below it. The durable half of
    the fix is not the new signature, it is reading the shape every Python failure
    shares: the terminal `SomeError: message` line. Take the **first non-wrapper** one —
    first because a child process prints its traceback before the parent prints one that
    merely says the answer is above, and non-wrapper because that parent line
    ("Engine core initialization failed. See root cause above.") is always present,
    always last, and always useless. Prove the structural half is live by testing it with
    the specific signature REMOVED; a rule that only works once you already knew the
    answer is not a rule.
  - **A FORENSIC READER THAT MATERIALISES ITS FILE COSTS MOST EXACTLY WHEN IT IS
    NEEDED MOST (2026-08-06, the app SIGKILLed during startup):** `promote_incomplete_runs`
    runs in the LIFESPAN STARTUP, before unlock, on every boot — and read every journal
    into a list of dicts. A journal's size is proportional to how much there was to
    diagnose, so **the worse the incident, the more likely the app died trying to tell
    you about it**; the operator saw only `Waiting for application startup.` then
    `Killed`. Measured on a 28 MB journal: **+243 MB RSS, 9× the file**. `summarise` was
    worse — it uses the beat file for a COUNT, the FINAL beat and the LAST TEN, and
    materialised all of them (a 19-hour import writes thousands, each carrying a
    per-child CPU array). GENERAL FORM: for any reader, write down what it actually
    consumes before choosing how to read; a count, a tail and a few aggregates are all
    streamable, and a whole-file read in a *boot* path is a startup cost proportional to
    the last disaster. Also check the readers that bound their output — `raw_runs` read
    every beat and THEN sliced `[-max_beats:]`, so the bound it advertised never applied
    to the peak, and `list_runs` was not even capped at 50 files like the boot pass was.
    **TWO TEST LESSONS, both from getting it wrong first.** (a) A memory guard built on
    `ru_maxrss` is VACUOUS: peak RSS is a process high-water mark that never shrinks, so
    by the time the test runs the peak is already set by earlier tests and the delta is 0
    whatever the code does — reverting the fix left it green. `tracemalloc` measures
    allocations inside the window and resets, which is the actual claim. (b) The fixture
    must grow EVERY file the path reads: padding only the beat file left the milestone
    read undetectable, and padding it with 30,000 *distinct* stage names then failed
    against correct code, because that builds a genuinely large aggregate the summary is
    supposed to report — pad with records the code does not accumulate, or the test
    measures the wrong thing in both directions.
  - **A COMPILE-TIME DEFAULT CAN DIFFER BETWEEN THE ENGINE YOU BENCHMARK ON AND THE
    ONE YOU SHIP — and `PRAGMA temp_store` does not tell you which (2026-08-06, the
    merge's 5.9 GB):** the bundled **sqlcipher3 is compiled `SQLITE_TEMP_STORE=2`**,
    the stdlib `sqlite3` is `TEMP_STORE=1`. So every statement journal, temp table and
    transient index defaults to **RAM on the encrypted store and to DISK everywhere
    else** — and `connect.py` never set it. Measured on the real engine, one
    `INSERT..SELECT` with the FTS trigger live and a 256 MiB cache: **~5 KB of RAM per
    row inserted, linear, and `cache_size` does not bound it** (that lesson is about
    the page cache; this is a separate allocation) — 100k/200k/400k rows → +663/+377/
    +735 MB cumulative to 1,980 MB, against **+0 MB and no time penalty** under FILE.
    A field import of 1,358,765 articles in one statement held 5,937 MB on a 5.5 GB
    box. THREE THINGS WORTH KEEPING. (a) The tell is invisible from the pragma:
    `PRAGMA temp_store` returns **0 = "the compile default"**, which is not
    self-describing — you must read `compile_options` to learn what 0 means, and every
    plaintext probe in this repo's history therefore measured the opposite default
    while looking authoritative. This is the recorded "a probe's data distribution is
    part of the lookalike" trap with the ENGINE as the varying axis. (b) Fix the
    setting AND bound the work anyway: the pragma moves the allocation to disk, but a
    5 TB import would then size a temp FILE by the corpus, so the durable answer is a
    statement that only ever handles a bounded window. (c) Do not credit the fix to
    the wrong half — the pragma is what the measurement supports; windowing is what
    makes it corpus-independent, and the two need separate tests or one will be
    reported as evidence for the other.
  - **A BOUND MUST BE DENOMINATED IN THE UNIT THAT ACTUALLY COSTS — and an
    architectural-consistency question can find that faster than a measurement
    (2026-08-06, the merge window):** the windowed merge shipped with a bound of
    20,000 source IDS and a comment claiming that kept a window "in the low hundreds
    of MB". The maintainer then asked whether the batch size shouldn't relate to the
    600 MB the backup already slices volumes into. It cannot *directly* —
    `write_volume_set` cuts an opaque encrypted stream at byte offsets with no row
    alignment, and restore reassembles every volume into one staged file before
    `merge_corpus` opens it, so by merge time volumes do not exist. But the question
    was right about the UNIT, and that is what the ids bound got wrong: measured on
    the shipped engine, the SAME 20,000 rows cost **178 MB at a 2 KB body, 393 MB at
    8 KB and 947 MB at 32 KB** (9.1 / 20.1 / 48.5 KB per row) — so a row-count window
    means something different on every corpus, and on the field artifact (32.1 GB /
    ~1.43M articles ≈ 22 KB each) it would have carried **~800 MB, five times its own
    comment's claim**. A fabricated figure, sitting directly above the constant it
    justified. THE FIX is to size the window in BYTES from a sampled average row size
    and clamp both ends; the numbers differ from the volume size because they answer
    different constraints (a volume is sized by the GF(2⁸) parity ceiling and download
    granularity, a window by what one machine holds at once) but the unit is the same.
    FOUR THINGS WORTH KEEPING. (a) The general form: when you bound a loop, name what
    the loop COSTS and bound that — a count is only a proxy, and it is a bad one
    wherever the items vary (this corpus holds articles from 1 KB to 412 KB).
    (b) Sample from SEVERAL blocks of the id range, not one `LIMIT n`: the oldest rows
    of a corpus are not its typical ones, and a single block makes a systematic drift
    invisible. (c) `LENGTH()` on TEXT counts CHARACTERS — on a mostly non-Latin corpus
    that under-counts every multi-byte row, widening the window exactly where rows are
    biggest; `CAST(x AS BLOB)` is what makes it bytes. (d) A "is X consistent with Y?"
    question from someone holding the whole system in view is a real review instrument:
    it found this when the measurement (which used one row size) and the tests (which
    asserted bounded rows) both could not.
  - **A GUARD OVER AN INTERRUPTED RUN MUST FORCE THE INTERRUPTION TO BE REACHABLE
    (2026-08-06, same slice — the recorded anti-vacuity lesson recurring):** the new
    guard "a half-merged working copy is never stamped `merged`" PASSED against the
    mutation that reverts the fix. Its fixture had three articles and the production
    window is 20,000, so the merge took the single-shot path, never committed
    mid-way, and the failure's rollback wiped `merge_batches` — leaving
    `all(status != 'merged' for row in rows)` to range over an **empty list**. The
    guard could not see its own subject. Two changes, both needed: shrink the window
    so a mid-run commit actually happens, and assert the collection is NON-EMPTY
    before asserting anything about its contents. GENERAL FORM: any assertion of the
    shape "no element of X has property P" is satisfied for free by an empty X, so
    every such guard owes a companion assertion that X exists — and for a guard about
    a *partial* state, that the partial state was genuinely produced rather than
    rolled away.
  - **BATCHING A DEDUPING `INSERT..SELECT` CHANGES WHAT LANDS, because a `NOT EXISTS`
    against the target does NOT see rows the same statement is inserting (2026-08-07,
    B5):** given two incoming rows sharing a step's dedup key, the whole-corpus
    statement keeps **both** and a windowed one keeps **one** — the second window sees
    the first window's commit. Measured on both stdlib sqlite3 and sqlcipher3 before a
    line was written. Neither answer is wrong; they are different, and swapping one for
    the other under a *performance* change is a silent edit to the user's corpus that
    no fixture without internal duplicates can detect. So windowing needs a
    JUSTIFICATION, not just an id to slice on, and exactly three establish it: the
    incoming dedup column is UNIQUE (no second row can exist), a `rep` collapse leaves
    one candidate per identity group, or the target carries a real PK/UNIQUE behind an
    `INSERT OR IGNORE`. Enforce it on the REAL PATH (`_insert_tracked` raises on an
    unregistered step), not only in a test, and record the refusals too — `_NOT_WINDOWED`
    exists because "absent" and "considered and refused" read identically otherwise.
    TWO COROLLARIES. (a) This retroactively audited the articles windowing shipped a week
    earlier: it was safe, because `articles.hash` is `unique=True` — but that was true by
    LUCK, not by check, so the guard now reads it from the schema. When a past change
    turns out to have been safe, ask whether it was safe *by construction* or *by
    accident*; only the first survives the next edit. (b) An `INSERT OR IGNORE` is not
    itself evidence of a constraint: `ai_keyword` has one and its two indexes are both
    NON-unique, so the `OR IGNORE` reads as protection that is not there.
  - **A "MUST BE GONE" GUARD IN PYTHON TRIPS ON THE DOCSTRING THAT EXPLAINS THE REMOVAL —
    and the fix is `ast`, not rewording (2026-08-07, B5; the recorded JS lesson recurring
    one language over, hit while writing the fix it warns about):** the guard asserting the
    inline `MIN(id) AS rep_id` sub-query was gone failed against CORRECT code, on the
    `_materialise_rep` docstring that quotes the pattern to explain why it was removed.
    That docstring is exactly what a future session reads before deciding the removal was
    a mistake, so rewording it is the wrong repair. Parse instead of grep: `ast` gives an
    exact docstring test (first statement of a module/class/function body), so the guard
    can search only the string literals that could really BE SQL. SECOND HALF, and the more
    general point: scoped that way it then failed on `commodity_prices`, whose inline rep
    is CORRECT because that step is not windowed — a guard that fires on correct code gets
    relaxed, and a relaxed guard catches nothing. Scope to the windowed call sites (walk
    `ast.Call` for the `src=` keyword), and add the NEGATIVE-SPACE TWIN asserting an
    unwindowed inline rep still exists somewhere, or "correctly scoped" and "matches
    nothing anywhere" stay indistinguishable.
  - **TWO MECHANISMS THAT COVER FOR EACH OTHER BOTH FAIL WHEN ONE OF THEM MOVES
    (2026-08-10, the FTS trigger after a windowed merge):** the entry below records that a
    merge-level test of the trigger-restoring `finally` proves the ROLLBACK, not the
    `finally` — SQLite's transactional DDL rolls the DROP away, while the `finally`'s
    CREATE runs inside the still-open transaction and is undone moments later. That was
    read as "belt and braces". It was the opposite: ONE working mechanism and one inert
    one, and which was which depended on nothing committing in between. WINDOWING then
    committed in between — a windowed step COMMITs and reopens, so on any corpus large
    enough to window (every real field corpus) the DROP is durable by the time a later
    step fails, the rollback can no longer undo it, and it undoes the CREATE instead.
    Both mechanisms fail together and the working copy comes back unable to index.
    Probed rather than argued: force one id per window, fail a step, trigger gone.
    THE REASON IT STAYED HIDDEN IS ALSO THE REASON IT WAS CHEAP — it fails CLOSED
    (`verify_copy` refuses a trigger-less copy, and a failed merge's working copy is
    disposable), so it cost wasted work and a confusing refusal rather than data; a
    fail-closed bug has no symptom until someone measures for it. FIX: capture the DDL
    before the transaction opens and re-create AFTER the rollback, where
    `isolation_level = None` leaves the connection in autocommit so the CREATE is durable
    immediately; idempotent, so the small-corpus case where the rollback already restored
    it is a no-op, and best-effort, so it can never replace the failure that brought it
    there. GENERAL FORM: when a property is upheld by two mechanisms, find out which one
    actually holds it and under what precondition — "there are two" is not redundancy if
    both depend on the same thing, and a change elsewhere (here, committing mid-step for
    memory reasons) can retire both at once without touching either.
  - **SQLite DDL IS TRANSACTIONAL, so a merge-level test of a `finally` that restores a
    dropped trigger proves the ROLLBACK, not the `finally` (2026-08-07, B6):** the guard
    for "the FTS insert trigger is always restored" passed against the mutation that
    deletes the `finally` — because the merge's own ROLLBACK undoes a `DROP TRIGGER` by
    itself (verified directly: the trigger is absent mid-transaction and present again
    after the rollback). The test was vacuous in the precise way the anti-vacuity lesson
    above describes, but by a mechanism no fixture size could fix. THE SPLIT that makes it
    real: test the context manager's contract OUTSIDE a transaction, where only the
    `finally` can restore the trigger and where removing it genuinely fails; and rename
    the merge-level test to claim only the property it actually proves. GENERAL FORM:
    before trusting a cleanup test, ask what ELSE would restore the state if the cleanup
    were deleted — in SQLite that includes every DDL statement inside an open transaction,
    so a mutation run inside one is testing the database, not your code.
  - **A PROBE'S SCALE IS PART OF THE LOOKALIKE — a fixture small enough to sit in cache
    cannot reproduce a cache-pressure defect, and "refuted" then goes in the ledger
    (2026-08-07, B6; the recorded "a probe's data distribution is part of the lookalike"
    trap with SCALE as the varying axis):** I recorded FTS automerge as refuted at
    "1.25×/1.24×/1.50×, ~600× short". The measurement was real and the conclusion was
    wrong: on a small fixture the whole index fits in the page cache and few segment
    merges happen, which is the one regime where the problem cannot appear. Re-measured on
    a cache-constrained fixture, the same change is 1.36× overall and 23.7× on the insert
    itself. It cost three field imports. So when a probe REFUTES a hypothesis, state the
    regime it refuted it in, and check that regime is the one the field is in — a negative
    result is a claim about the fixture until it is shown to be a claim about the system.
    Corollary that saved the follow-up: the two OBVIOUS fixes were then genuinely refuted
    by measurement (deferring automerge alone 0.93–0.97×; `'rebuild'` 0.75×, because it
    re-indexes the half of the corpus already indexed), so record refutations WITH their
    numbers or the next session re-chases them.
  - **A FIX THAT RELOCATES A COST MUST BE ASKED WHAT THE REPLACEMENT SCALES WITH — the
    lesson directly above recurred ONE TURN LATER, inside its own fix (2026-08-08, C2):**
    B6 correctly found that FTS work was 98% of the merge and moved it off the article
    step; it then chose `'optimize'` as the tidy-up. `'optimize'` merges the WHOLE index
    into one b-tree, so its cost tracks the **corpus** while the insert beside it tracks
    the **import** — measured 2.05 / 3.00 / 9.31 / 13.81 s as the index grew 25k → 150k
    documents with the insert flat. On a fixture whose corpus is small that is invisible;
    on a queue of eighteen backups it is eighteen whole-index rewrites, each larger than
    the last. GENERAL FORM: when you replace a mechanism, name the dimension the
    REPLACEMENT's cost scales with and check it is the same dimension the original scaled
    with — a replacement that tracks a different axis looks fine at the fixture's scale
    and wrong at the field's, and no amount of re-running the same fixture reveals it.
    COROLLARY, and the reason this one was caught: **a change that removes a tidying pass
    owes a QUERY-side measurement**, or it is a transfer rather than a win. Here the
    measurement said the trade did not exist (74.5 vs 74.6 ms median over six terms from
    very common to rare, bm25 as `search_ids` runs it, on a reopened connection) — and it
    also killed a mechanism I had already written: a bounded incremental merge bought 2–3%
    on query, inside the noise, for 16% more build, so it was deleted rather than shipped
    "just in case".
  - **FTS5 `hashsize` IS THE BULK-LOAD LEVER NOBODY IN THIS REPO HAD SET, AND IT IS NOT
    MONOTONIC (2026-08-08, C2):** FTS5 holds pending index data in memory and flushes a
    **new level-0 segment** every time it exceeds `hashsize`, whose default is **1 MiB**.
    That is what decides how many segments a bulk load creates, and collapsing them is the
    crisis-merge cascade whose `fts5DataRemoveSegment` dominated the field beat. Measured
    60k docs into a 60k index, varying only that: 1 MiB → 19 segments / 12.33 s; 4 MiB →
    16 / 9.43 s; 64 MiB → 4 / **8.40 s**; 256 MiB → 4 / **8.69 s, worse than 64**. So "as
    much as we can get" is the wrong instinct and the default is a measured number. TWO
    THINGS THAT BITE: it is a REAL allocation, so it belongs beside the page cache in the
    merge's memory budget rather than on top of it; and it **PERSISTS to
    `article_fts_config`** (verified), so a load that forgets to restore it leaves the
    corpus holding that budget for every later ingest — which is why the guard asserts the
    persisted value rather than counting statements. MEASURED AND NOT THE ANSWER, recorded
    so nobody re-chases it: `auto_vacuum=INCREMENTAL` costs ~5% on this workload
    (30.43 vs 28.83 s, 15.91 vs 15.17 s) — real, small, and nowhere near the field's gap.
  - **A STEP REPORTED AGAINST A DENOMINATOR THAT EXCLUDES IT PUBLISHES A NUMBER THAT
    COLLIDES WITH ANOTHER STEP (2026-08-08, C3):** the search-index build called
    `_step_watch(con, total, total, …)` where `total = len(steps)` did not count it, and
    the tick publishes `done = index − 1` — so it published `18`, which is exactly what the
    LAST table step publishes on completion. "18/19" therefore meant either *watches
    finished* or *the search index has been running for fourteen hours*, and the run
    timeline duly reported `stuck_at: 18` with the reading *"workers were idle"*. Count
    every step you report, including one that is not in the steps tuple. SECOND HALF: that
    step's own row progress went through `runlog.statement` — the **same slot** the
    per-statement trace overwrites within milliseconds — so the one step that genuinely
    knows how far it has got (it walks a known list of ids) published nothing that
    survived. Before adding progress, check which slot already owns that field and who
    else writes it.
  - **`pgrep -f "<pattern>"` IN A WAIT LOOP MATCHES THE WAITING SCRIPT'S OWN COMMAND LINE
    (2026-08-08, harness):** a chain of `while pgrep -f "a.py"; do sleep 10; done` scripts
    deadlocked on itself — each script's own `bash -c` command line contains the pattern it
    is waiting on, so it waits for itself forever, silently, looking exactly like a
    long-running experiment. Cost ~20 minutes of wall clock and produced four empty logs.
    Run sequential work in ONE script, or match on something the waiter cannot contain.
  - **A PUBLISHED REASON SENTENCE IS AN API — NAME IT, AND ASSERT IDENTITY, NOT A
    SUBSTRING (2026-08-08, the `kb_per_row_unavailable` red lane):** rewording a gap
    reason from "did not grow" to "did not **measurably** grow" reddened a guard asserting
    `"did not grow" in reason`. I greped the source for readers of that string and not the
    TEST tree, which is the half that mattered — the recorded stale-anchor class, again.
    The repair is not to re-pick a substring but to hoist both reasons into module
    constants and have every guard assert `== RSS_GAP_CURRENT` / `== RSS_GAP_PEAK`.
    Identity is strictly **stronger** here, not merely more robust: a substring proves
    some words appear, whereas identity proves WHICH of the two readers went blind — which
    is the property those guards sit inside a branch to check, and the one a substring
    could never distinguish (both sentences are about an unobservable delta). Mutation-check
    both directions: swapping which constant each branch publishes must fail by name, and a
    pure rewording must now pass. COROLLARY that is the real fix: the branch CI hit was
    reachable locally only when the allocator happened to serve the probe from a warm arena
    — a CI-shaped accident — so it also got a stub test that reaches it on every platform.
    When a guard fails only on CI, ask whether its branch has any deterministic driver at
    all; if not, the fix is a second test, not a better assertion.
  - **A CLASS WITH NO RULE IS A LIE THE MARKUP KEEPS TELLING — grep the stylesheet for
    every hook you are reading, not just the ones you are writing (2026-08-11, "some
    inner parts of the sections appear bigger or brighter than section titles"):**
    `class="small"` appears 35 times in `index.html`, 32 of them in Settings, and had
    **no rule anywhere in the tree** — so every element an author marked small rendered
    at the full 15px body size, and the several that also carry `font-weight:600` as an
    ad-hoc sub-heading were therefore *louder* than the `.panel h2` above them (12.5px,
    `--muted`). Reading the markup told you the opposite of what the screen showed, which
    is why this survived every review of the HTML: the defect is not in any line you can
    point at, it is in a line that does not exist. Defining it is a bug fix rather than a
    restyle — a missing `font-size` can only ever have made text *bigger* than intended,
    so supplying one can only reduce visual weight and can never overflow a layout. THE
    GENERAL FORM: before trusting what a class name says an element looks like, confirm
    the class is defined; and when a report is about relative prominence, measure the
    computed scale rather than reading the intent off the attributes.
  - **ENCODING RANK AS LETTER CASE IS INVISIBLE IN FIVE OF THE TWELVE LOCALES (2026-08-11,
    the same pass):** `.panel h2` said "section title" with `text-transform:uppercase` +
    `letter-spacing` at 12.5px in `--muted` — a small-caps label, which reads as a heading
    in Latin script and as **nothing at all** in Arabic, Chinese, Japanese, Hindi and
    Bengali, where `uppercase` is a no-op. So in five of the twelve locales this ships in,
    the title degraded to small dim text while every heading below it kept its size and
    weight. A hierarchy that has to survive translation steps on SIZE and WEIGHT only;
    case is decoration, never structure. The guard asserts the ORDERING of the declared
    sizes (fold > section > sub-section > body > small > hint) rather than any particular
    number, so it fails for the reason it is named — something inside a section grew past
    the section's own title — and separately forbids a heading from leaning on case again.
    COROLLARY worth keeping: a bare `<h3>` inherits the browser's `1.17em`, so in any
    design whose own headings are *smaller* than body text, every unstyled sub-heading is
    automatically the loudest thing on the page.
  - **A PHASE THAT RUNS WHILE NO SUB-UNIT IS IN FLIGHT HAS NO HOST ELEMENT — and the
    producer's own comment explaining why it must not be silent is why that survives
    review (2026-08-11, "according to UI, the import is over, but the CPU is still
    firing 100% on one core"):** an import run does not end when its last item does.
    `_tune_after_run` then merges the search index — FTS5 `'optimize'`, single-threaded
    and index-scaled — inside the same exclusive window, so collection stays paused and
    a second import is refused while every item already reads "Done". The backend was
    publishing that phase and its comment said outright that without it the run "would
    sit at 'running' with no item in flight … which reads as a hang". The renderer
    emitted `st.live` only INSIDE a row whose item is `running`, and by then none is —
    the fix for the exact failure was written, and had nowhere to render. GENERAL FORM:
    when a renderer hangs a status off "the currently-running child", ask what publishes
    status when there is no child; a tail phase, a warm-up and a cleanup all live there.
    SECOND, INDEPENDENT REASON it could not have shown even given a row: a mirrored
    sub-job status nests its phase under `progress` while the run's own live dict is
    flat, so one reader silently served one shape — check both ends of a field two
    producers write. THIRD, the honest half of the same report: the row said "Importing"
    beside 100% of items, a job claiming to be finished and working at once. The count
    was a real measurement and stayed; it was the NAME that was wrong, and that is
    usually the cheaper thing to fix. FOURTH, from the operator's own question ("if it
    means pausing the reindex, it's OK"): the post-import re-index drain never consulted
    the exclusive hold — the third recurrence of "gate every entry point", because
    `ReindexJobManager` grew `_yield_to_exclusive` and this is a *different, later* entry
    point. It STOPS rather than parks, because a park can only happen between batches and
    a single import is a single batch of everything it merged — so parking would never
    fire on the one shape that matters, while stopping is free against a durable
    per-article watermark that the queue's own end-of-run drain restarts.
  - **A COUNT OF ITEMS IS NOT A COUNT OF THE RUN'S STAGES — and the tail stage is exactly
    where the two diverge (2026-08-11, the same report's second half):** both progress
    bars were drawn from `items_done/items_total`, which reaches 100% the moment the last
    item lands — while the search-index merge is still holding the machine. A full bar
    beside a run that has not finished is a fabricated completeness, so the DENOMINATOR
    has to count the work actually left: `stages_total = items + 1`, the +1 being a real
    final stage, complete once it has RUN (what it *achieved* stays a separate field), and
    skipped after a Stop so a stopped run correctly never reaches its own end. Publish the
    stage counts BESIDE the item counts rather than replacing them — the item count was
    never the wrong number, only the wrong thing to draw a bar from — and when a client
    finds no stage counts, draw NO bar rather than falling back to the number being
    corrected. COROLLARY found in the same pass: `_jobRow` formatted EVERY job's progress
    as bytes, though four producers publish counts (`items`/`files`/`articles`/`stages`),
    so a 700,000-article re-index read "700 kB / 1.4 MB". The unit was already travelling
    with the numbers and nothing read it — when a payload carries a unit, the renderer
    that ignores it will be wrong for every producer that is not the one it was written
    against.
  - **A SECOND STORE FOR THE SAME KIND OF THING IS A SECOND ENUMERATOR NOBODY WROTE —
    and its layout may be incompatible with a guard you already shipped (2026-08-11,
    "vLLM models were not saved, only ollama models"):** `collect_model_items` listed the
    Ollama store and nothing else, so on a machine serving with vLLM the large-data
    backup carried no weights and still said "Backup complete" — it had copied everything
    it knew about. That is the 2026-08-11 Ollama-store lesson one store over: when a
    second backend arrives, every enumerator phrased around the first is now wrong, and
    it fails by reporting SUCCESS. THE INTERESTING HALF IS THE LAYOUT. A Hugging Face
    repo keeps its bytes once in `blobs/<sha>` and reaches them by SYMLINK from
    `snapshots/<rev>/`, so both obvious designs fail: copying both trees stores every
    multi-GB weight TWICE (the copier opens its source, so it follows the link), and
    storing the links collides with `restore_folder_backup`'s flat refusal of symlinks —
    a 2026-07-25 fix for a live-reproduced arbitrary-file copy out of an editable backup
    folder. The way through is to copy the snapshot entries with the link RESOLVED and
    skip `blobs/`: one copy, no link anywhere in the artifact, and the restored tree is
    the layout `huggingface_hub` itself produces where symlinks are unavailable rather
    than one invented for the occasion. GENERAL FORM: before teaching a backup a new
    source, check whether that source's on-disk shape is compatible with the guards the
    restore side already enforces — a design that needs the guard relaxed is the wrong
    design, not a reason to relax it. And state the residual cost rather than hiding it:
    two revisions of one repo sharing a blob are stored once per revision.
  - **A PERCENTILE OVER A MOSTLY-EMPTY DERIVED TABLE DEGENERATES INTO AN EXISTENCE TEST,
    AND THE FLAG RATE THEN RESTATES COVERAGE (2026-08-11, the source-quality export):**
    only **28,639 of 991,686** audited articles (**2.89%**) carried a single keyword
    mention — 21 languages at exactly zero, en at 5.00%. Every Layer-A ratio is computed
    over the keyword tables, so each cohort's `mention_density` and `vocab_sparsity` p90
    were BOTH `0.0`, and the outlier rule `value > p90` became **"has any keyword at
    all"**. The tell was already in the report and unreadable: `pct_flagged` equalled the
    indexed share to two decimals in every assessed language **except `unknown`**, the one
    cohort whose p90 was non-zero — the single divergence proving the mechanism. So the
    whole bundle (517 pathological articles, the `observed` ranges, the S5 floor question)
    was calibrating on 2.9% of the corpus while reading as a corpus-wide measurement.
    GENERAL FORM: a diagnostic built on a DERIVED table must publish that table's COVERAGE
    beside every rate it derives, because a percentile cannot distinguish "the tail is
    empty" from "the column is empty" — and where coverage is the smaller number, every
    threshold in the report is uncalibratable rather than merely unreached. COROLLARY on
    collinearity: `mention_density` and `vocab_sparsity` share a denominator and are zero
    together, and selected the SAME 27,772 records (symmetric difference 656, 2.4%) —
    reporting them as two of four independent dimensions overstates the evidence by one.
  - **A GUARD'S OWN JUSTIFICATION CAN BE A CASE THE DATA NEVER EXHIBITS — count it before
    assuming the guard is load-bearing (2026-08-11, the same export):** the article gate
    keeps any body ≥100 words whatever its URL, so "a genuine article at `/business` or
    `/tag/gaza` is never dropped". Measured on an unbiased random control, **10.95%** of
    articles carry a URL the project's OWN rules call a non-article and **8.10%** sit
    above that guard; **36 of those were hand-read and 36/36 were listings** — section
    fronts, tag/author archives, homepages, a sitemap. Zero were the protected case. The
    guard was not defending real articles, it was admitting index pages, and the
    retroactive scan inherited the same veto and under-reported by ~74%. GENERAL FORM:
    when a guard exists to protect a scenario, sample the population it actually governs
    and count how often that scenario occurs; a guard whose protected case is absent is
    a hole with a rationale attached. **TWO CANDIDATE CORROBORATORS WERE MEASURED AND
    BOTH REFUTED**, recorded with their numbers: line structure (unterminated-line
    fraction + median line length) gave 20–43% recall at 10–21% collateral, and "the
    title reads as a section label" gave a **22.9% false-positive rate on normal URLs —
    backwards, because for a real article the slug IS the title**. The right answer was
    not a weaker signal but REVERSIBILITY: route the population to the existing
    quarantine STAMP rather than the drop. And any rate from a fixed vocabulary
    (`_SECTION_WORDS`) is a FLOOR — `/astrology` and `/obituaries` are invisible to it —
    which must be published as such rather than widening the vocabulary to chase them,
    since widening is the one move that can start condemning real articles.
  - **A THRESHOLD EXPRESSED AS A FRACTION OF A POPULATION LARGER THAN THE ONE THE
    STATISTIC CAN BE DRAWN FROM IS UNREACHABLE BY CONSTRUCTION (2026-08-11, the furniture
    cut):** `ubiquity_cut = 0.3 × len(per_source_top)` counts every AUDITED source (2,224,
    empty fingerprints included) while cross-source DF can only be drawn from sources that
    HAVE a top-12 (241) — so the cut sat at 667 against a maximum ATTAINABLE of 241, and
    `reachable: false` was a fact about the denominator rather than about the terms. The
    retirement verdict stands on its own independent reasoning; what was missing was that
    a reader could not tell "nothing is ubiquitous here" from "nothing could have been".
    Publish `max_attainable` beside any such threshold. AND THE FIX THAT WAS *NOT* MADE is
    the load-bearing half: re-basing the denominator would change `furniture_share`, which
    is a soft criterion that can escalate a source from `degraded` to `failing` — a live
    change to the qualification gate, arriving inside a disclosure-only slice. When a
    reporting fix and a behaviour change share one line, ship the disclosure and leave the
    behaviour for its own reviewed slice.
  - **A TEST THAT HAND-ROLLS A SUBSET OF A SHARED STUB HELPER DRIFTS THE DAY THE THING IT
    STUBS GROWS A NEW CHECK — and it then fails naming the MACHINE, not the code
    (2026-08-11, `test_vllm_install_starts_a_background_job`):** the test asserts WIRING
    (does the endpoint hand the job its `version`), and it set up `platform.system`,
    `detect_gpu` and `kill_switch_active` by hand while the file's own `_preflight_stub`
    sets those THREE PLUS `_total_ram_bytes` and `_free_disk_bytes`. When the install
    preflight later grew a 15 GB disk floor, the hand-rolled version silently began
    reading the REAL volume, so it passed or failed on how much scratch space the rest of
    the suite happened to be holding: green run-alone and green at 16 GB free, red at
    13.92 GB mid-suite, with a 409 quoting `df` — a failure that reads as an environment
    problem and is actually a test-hygiene one. It matters past the sandbox, because this
    fleet includes low-spec laptops that never clear the floor at all. THE DISCRIMINATION
    WORTH KEEPING, since three sibling tests read the real disk and are RIGHT to: a SHAPE
    assertion (schema string, key presence, `installed is False`) is indifferent to what
    the environment says, while a SUCCESS-PATH assertion can be BLOCKED by it — only the
    second must stub. Proved rather than argued, by making the real `_free_disk_bytes`
    raise and re-running the file: the fixed test is absent from the failures (it no
    longer touches the volume), the three shape tests appear (they do, harmlessly, since
    the real reader returns `None` on unreadable and never raises), and separately the
    disk floor's own dedicated test still fails by name when the floor is neutered — so
    stubbing here removed a false failure and no coverage. GENERAL FORM: when a helper
    exists for a fixture, call it rather than copying part of it; a partial copy is a
    silent bet that the thing being stubbed will never grow.
  - **A RESUMABLE JOB WHOSE ONLY RESUME CONTROL LIVES SOMEWHERE ELSE IS NOT RESUMABLE —
    and the entry point that defaults a cursor to 0 is what destroys the work
    (2026-08-13, "just lost 24h of reindexing"):** every piece of the resume worked.
    `ReindexJobManager` persisted its cursor every 300 articles, `_load_persisted()`
    restored an interrupted run as `paused`, and `/api/jobs` had a Resume that continued
    it. What the operator had was the Settings **button**, whose whole path
    (`cleanupKeywords` → `_startReindexJob` → `POST /reindex-job`) called `start()` with
    no cursor — and `start()`'s `_cursor: int = 0` default then wrote over a day of work
    with a silent `max(0, 0)`. I had told them resume worked, and it did; it was simply
    not reachable from the surface they were on. TWO RULES. (a) **The safe action is the
    DEFAULT, never a control to find**: `start()` now CONTINUES a compatible paused run
    unless `restart=True` is passed explicitly, so the destructive reading has to be
    asked for. (b) **Refusing beats guessing when the paused run is a DIFFERENT one** — a
    paused full-scope sweep and a requested keywords-only sweep are not the same work, so
    continuing would misreport what was done and starting over would discard it; the
    409 names the cursor, the scope and the way out. GENERAL FORM: for any job with a
    persisted cursor, find every caller of its start path and ask what each passes for
    that cursor — a default of 0 in one of them is indistinguishable from "start over"
    at every layer above it, and the loss surfaces only as a progress bar back at zero.
    COROLLARY on the rate that shipped beside it: publish a measured quantity or none —
    `keywords_per_hour` counts real `KeywordMention` rows written (banked only on a
    committed batch, zeroed on rollback) rather than scaling the article rate by an
    assumed keywords-per-article, and the guard asserts the tallied number equals the
    row count in the database, because `> 0` passes for any fabrication.
  - **A CAPABILITY WITH NO CALLER PLUS A FIELD THE ARTIFACT DOES NOT CARRY LEAVES A 24-HOUR
    RUN UNUSABLE — and neither half looks like a defect on its own (2026-08-13, the keyword
    triage proposal):** `propose_stoplist_additions` / `propose_kind_overrides` were written,
    tested, and called by nothing outside the test tree — the recorded dead-end shape. That
    alone reads as an unfinished feature. The second half is what made it expensive: the
    per-batch verdicts record carried `term -> {verdict, kind}` and NOT the term's LANGUAGE,
    which is the field the whole decision turns on, because a per-language scoped stoplist
    entry is collision-free by construction and a global one is not (English "content" is
    French *content* = happy). So an overnight GPU sweep produced 109,466 verdicts that no
    code path could turn into a safe proposal, and the missing field would have forced every
    one of them through the dangerous channel. GENERAL FORM: when a pipeline's last stage has
    no caller, also check whether its INPUT carries what that stage needs — a stage nobody
    runs is never told it is missing an argument. THREE RULES from the fix. (a) The join back
    to live rows is what rescues an existing log, but it is not equivalent: a language
    recorded IN the run is what the model judged, one read from the corpus now is today's
    state — publish which basis each entry came from rather than presenting them as one.
    (b) Anything the join cannot answer is HELD BACK, not guessed: a term existing under
    several languages, or no longer in the corpus at all. Picking one language would invent
    precisely the cross-language collision the scoping exists to prevent. (c) A fixture that
    rides every batch by design (here the canaries) appears thousands of times and is not a
    corpus judgement — exclude it by name and publish the count, because a silent drop reads
    as "the model never saw them".
  - **A MOVED PANEL TAKES ITS LOADER WITH IT, AND A RESULT RENDERED ONLY WHILE RUNNING IS
    ABSENT WHENEVER ANYONE LOOKS (2026-08-13, "can't find your keyword triage button"):**
    two stacked defects whose common tell is that the panel's own markup was innocent of
    both — it is static HTML and had been in the tree the whole time, so every source grep
    for the button, the href, or the panel id found them. (a) The three AI sweep panels
    moved to Settings → Advanced → AI; their `sync*Toggle()` calls stayed behind on the AI
    SUBTAB, so opening the section that CONTAINS them never asked whether a run existed.
    When markup moves between subtabs, grep for what LOADS it, not just for what renders
    it. (b) `_syncAiSweepToggle` called the renderer only when `state === "running"` — and
    the renderer is what emits the download links, so after an overnight run finished they
    did not exist in the DOM at the one moment they are wanted. This is the recorded "a
    job's in-memory result is not the artifact's existence" lesson at the RENDER layer: the
    log is on disk, `/last` reads it, and the panel should have too. THREE RULES FROM THE
    FIX. An absent run renders NOTHING, never a zeroed panel — 0 batches reads as a run
    that found nothing. The saved state gets its own words rather than being poured into
    `paused_reason`, which all three renderers turn into the word "paused" — that would
    relabel an errored run, a fabricated state worse than the empty panel. And the guard is
    BEHAVIOURAL, because the defect was an absence and no assertion over an href can tell
    "the string is in the file" from "the string is rendered when someone looks".
    **THE PROCESS POINT IS THE NEGATIVE-SPACE GUARD THAT WAS ITSELF VACUOUS:** the twin
    proving a LIVE run is not overwritten left `/last` unstubbed, reasoning that reading it
    would throw and thereby prove it was not read — but the throw is swallowed by the
    courtesy try/catch, so the panel stayed empty either way and the assertion passed for a
    reason unrelated to its claim. It passed the mutation that deletes the early return.
    A negative-space test must make the forbidden path actually AVAILABLE, or it is only
    testing that the code did not crash.
  - **A RESUMABLE RUN'S FOOTER DESCRIBES ONE INVOCATION; THE FILE DESCRIBES THE RUN — and
    reading the first as the second reports a week of work as nothing (2026-08-13, the
    triage log):** a sweep resumes by APPENDING to the same dated log, and the summary
    footer is written by whichever invocation ended. A field log carried **6,208 batch
    records under `batches_completed: 0, verdicts_out: 0`** — the last attempt found vLLM
    down and gave up before its first batch, and its counters are its own. Every reader of
    the footer alone rendered "0 batches, 0 verdicts", which is not a missing number but a
    WRONG one, and worse: it reads as a run that judged nothing while days of GPU time sit
    in the file. THE FIX is to sum the per-batch records the run itself wrote — the file's
    own account, exact, invocation-independent, and free because the reader already visits
    every line — and to publish it BESIDE the footer rather than reconciled into it, since
    the two measure different things and a reader still needs the last attempt's state and
    error. TWO GENERAL POINTS. (a) Zero is a LEGAL value, so `footer.count != null ?
    footer.count : file_count` keeps the wrong one — the same trap as defaulting an absent
    field to 0, wearing a different hat, and it needs a fixture where the footer is
    genuinely zero to catch. (b) When a state and a total disagree, say which one the
    sentence is about: "ended on an error" printed beside 6,208 kept batches reads as a
    contradiction, so an errored footer over a non-empty log names the failed ATTEMPT
    instead. PROCESS NOTE: this was found by reproducing the field log's exact shape and
    driving the real page in a browser — the panel's own numbers, not a re-read of the
    code, are what showed the recovery working.

  - **A SENTINEL DOCUMENTED AT THE SOURCE IS STILL A FABRICATION AT THE RENDER BOUNDARY —
    and a clamp that fires on 19 of 20 rows silently reorders the whole section
    (2026-08-11, the field bulletin's rising concepts):** `queries.trending` computes
    `growth = rc / expected if expected >= 1 else float(rc)` and its docstring says so, so
    nothing there is dishonest. The renderer printed that value as **"×5701.0 vs the prior
    period"** for a term whose prior was **4**. THREE things follow that the docstring did
    not. (a) The threshold is on `expected`, not on `prior`, so at a 7-day window over a
    30-day baseline ANY prior of 4 or fewer lands in the sentinel — "new terms (no prior)"
    understated its reach by a wide margin, and a docstring that understates a sentinel is
    how a consumer comes to trust it. (b) Because the sentinel equals the count, the sort
    key `-growth` degenerates to `-recent`, so a section titled "Rising concepts" ranks by
    raw volume and the ONE row with a measurable baseline sat **fourteenth, behind thirteen
    counts wearing a multiplication sign** — a clamp doing all the work does not merely
    inflate a number, it silently substitutes a different ordering. (c) The caveat under it
    warned about multiple comparisons, which is a real hazard and not this one, so the page
    read as disclosed. FIX: the flag travels WITH the value (`growth_is_ratio`, at every
    site that computes it — the solo path, the ring merge, and `keyword_hover_stats`, which
    had the same shape one screen away), and the presentation groups rows by what each can
    support. THREE buckets, not two: the reader predicate has three answers, and an old
    record carrying neither the flag nor `expected` may not be filed under "no baseline to
    divide by" — that is a finding, and a row that cannot prove it is a ratio does not get
    to claim one either way. Editions already on disk render honestly because `expected` is
    what the flag is computed from. NOTE the frontend prints the same value as `↑{growth}×`
    at six call sites (Home trend strip, Trends bars, the keyword hover, the supergroup
    rate) — the same defect, recorded, not fixed in the bulletin PR.
  - **A JOIN KEY EACH SIDE POPULATES DIFFERENTLY FAILS SILENTLY, AND AN EMPTY RESULT IS
    INDISTINGUISHABLE FROM "NOBODY TRIED" (2026-08-11, the bulletin's narration layer):**
    `narrate_story` keyed each paragraph on the EVIDENCE's article ids — only those whose
    text fit the char budget, 15 of a 115-article cluster in the field — while both
    consumers looked it up by the STORY's full cluster. So the join missed on every story
    big enough to be interesting, and because `story["narration"]` merely stayed absent,
    the failure looked exactly like a story nobody had narrated. THREE consequences, none
    of which surfaced as an error: the deterministic fallback sentence, which exists so the
    document is never left with a gap where a model should have been, never rendered though
    it was sitting in the record; the review screen's per-sentence verdicts came out empty,
    and those verdicts are that screen's entire stated purpose (design record §13, "a
    sentence the operator can see was checked is a different thing from a paragraph labelled
    validated"); and the edition still appended *"the sentences under each story were
    written by a local model"* on a run where Ollama refused every connection and 0 of 8
    stories were narrated. FOUR RULES. (a) When two lists could both plausibly be the key,
    the IDENTITY is the one every consumer joins on; the other keeps its own name
    (`grounded_in_article_ids` is real provenance — which articles the model could have
    drawn from — it is simply not the identity). (b) **Three code paths built that paragraph
    and they disagreed**, so whether the join worked depended on which failure had occurred;
    a shape assembled in more than one place needs its identity set in one. (c) A dangling
    join is REPORTED (`attach_gap`), because the whole reason this hid is that absence and
    failure looked the same. (d) A document's self-description must be built from what
    HAPPENED — `stories_narrated`, never `narrate=True`. AND THE TEST LESSON, from my own
    first draft: asserting `"115 articles" in md` to prove the paragraph rendered passed
    with the join still broken, because the story's own header line prints that count
    regardless — a "did it render" assertion must name text ONLY the thing under test emits.
  - **THE RENDERER CAN BE THE BOTTLENECK, AND A TRUNCATED HEAD READS AS THE WHOLE
    (2026-08-11, same edition):** Layer A computed 114 source countries, 34 languages, seven
    per-channel volumes and seven daily counts; the document printed 8, 8, none and none,
    with nothing to say the rest existed. That turns the masthead's own caveat — "a country
    absent here is a country this corpus did not collect from" — into a claim the page
    cannot support. A document has to be readable, so the LIST stays bounded; what must be
    exact and stated is the TOTAL and the remainder ("20 of 114 shown; the other 94 carried
    20,811"). THE LINE WORTH MOST was one nobody had ever printed: the per-channel split
    said **407 scientific articles of 72,225**, which explains at a glance why nineteen
    mitochondrial-fission terms owned the rising section — a fact already computed and
    thrown away. Two sections additionally carried caveats naming fields the render dropped
    (the promised untagged count — 17,080 of 12,468,182 mentions carry a topic tag — and the
    alert magnitudes, places and times), which is the recorded "a caveat may claim only what
    the data can exhibit" defect recurring in a new module. COROLLARY: the masthead was the
    one block the two renderers did NOT share, and it had drifted — the HTML page carried
    four bullet points and none of these lines; the sibling `_section_groups` says in its own
    docstring that it is shared "so the two can never drift", which is exactly the argument
    for sharing this one too.

  - **ONE KEY, TWO MEANINGS — THE COUNT AND THE THING COUNTED (2026-08-11, my own bug,
    caught by a stack trace rather than by any of the tests I had just written):**
    `story["articles"]` is the article COUNT and always was; the story header prints it.
    Attaching the newly-described article ROWS under that same key replaced an int with a
    list, so every story header rendered an em dash — and none of the fourteen tests
    written for the feature could see it, because they assert the deterministic sentence,
    which is composed BEFORE the overwrite. It surfaced only when a second consumer
    (`worklist`) tried to iterate the count. TWO RULES. (a) Before writing a new key into
    an existing payload, grep for that key: a name that already means a quantity cannot
    also mean the collection it quantifies (the fix is `article_rows` everywhere, with
    `corpus_articles` for the count, so one name means one thing across two new modules).
    (b) A feature's own tests cluster around the feature's own output and will happily
    step over damage to the payload it shares — the guard that catches this asserts the
    NEIGHBOURING field still renders, not the new one.
  - **A BARE DECIMAL AS A "MUST BE ABSENT" NEEDLE MATCHES THE GENERATION TIMESTAMP, WHICH
    LOOKS EXACTLY LIKE AN ORDER-DEPENDENCY (2026-08-11):** `assert "3.2" not in text` over
    a rendered document failed about one run in eight, because the footer carries
    `2026-08-11T09:08:53.267792` and `53.2` contains it. Under `pytest-randomly` that
    presents as a flaky order-dependent failure and sends you hunting for cross-test
    pollution; the cause is the CLOCK. This is the recorded "a whole-file substring
    assertion is only as meaningful as that string's uniqueness" trap meeting the recorded
    "never compare a hardcoded value against a real-`now` marker" one. Assert the property
    with a needle nothing else in the document can produce — here `"(×"`, which cannot
    occur in an ISO timestamp — or scope the assertion to the section.
  - **A NOTE THAT ONLY PRINTS WHEN THERE IS OUTPUT IS MISSING FROM THE ONE CASE IT EXISTS
    FOR (2026-08-11, the bulletin's card section):** the truncation note ("the budget
    stopped further producers, so this is a partial set") was rendered inside the branch
    that iterates the section's blocks — so a run whose budget stopped EVERY producer
    produced no blocks, printed "Nothing to report for this period", and the note never
    appeared. A budget reading as a quiet corpus is precisely the misreading the note was
    written to prevent. GENERAL FORM: a disclosure about why output is short must be
    keyed on the section EXISTING, never on it having produced anything — and the
    same applies to an empty state, which is why both renderers now dispatch on the
    section's own fields rather than on whether a block list came back non-empty.
  - **A FEATURE'S OWN TESTS SUPPLY THE INPUT ITS MISSING CALLER WAS SUPPOSED TO, SO A
    FULLY-TESTED CAPABILITY CAN BE UNREACHABLE (2026-08-11, the bulletin's phase-2
    worklist):** `ai_worklist` was pure, seventeen tests green, and the renderer read
    `edition["ai_worklist"]` — but nothing in `src/` ever WROTE that key. Every test
    set it itself, which is exactly what hid the gap: the tests were the caller. The
    maintainer's design says phase 2 is "an option appearing after phase 1 has been
    produced", and it could never appear. This is the recorded dead-end shape (a
    machine-readable refusal whose flag no caller sends; a tri-state nothing reads)
    with a new tell worth naming: **when a renderer reads a key, grep for what writes
    it, and count callers OUTSIDE the test tree.** The fix's own shape carries three
    rules — compute the derived view from the PERSISTED record rather than attaching
    it at generation (that is what "after phase 1" means, and it keeps a proposal out
    of a record of measurements); apply it AFTER the operator's exclusions, since a
    section they cut must not be offered as work; and do NOT let a
    measured-on-this-machine duration into an artifact that travels, because a
    recipient reads "about twelve minutes" as a property of the work rather than of
    somebody else's hardware — the exact call COUNT is hardware-independent and is
    what the document states.
  - **MUTATION-TESTING AN UNTRACKED FILE CANNOT BE UNDONE WITH `git checkout`, AND THE
    RESTORE FAILS SILENTLY (2026-08-11, same slice):** the house discipline is to
    neuter the fix and confirm the guard reddens. Doing that to a brand-new module —
    still `??` in `git status` — and then running `git checkout <path>` leaves the
    MUTANT in the tree: git errors on a path it has never tracked, and inside a `||`
    chain that error is swallowed. The two tests went red exactly as predicted, which
    is precisely what makes it feel finished; a later grep found `"needs": False` still
    sitting in the source. RULE: `cp` the file aside before mutating it, restore from
    the copy, and VERIFY the restore (`git status` / re-run the suite green) rather
    than trusting the revert command — for a tracked file too, since the same `||`
    swallow applies.
  - **`read_text()` NORMALISES LINE ENDINGS, SO APPENDING ONE ROW REWROTE SEVEN
    (2026-08-11, `shipped.csv`):** the recorded "never re-serialise a curated file to
    edit one entry" lesson has a quieter form than `sort_keys=True`. Python's
    `read_text()` opens in universal-newline mode, so a `read_text` → edit →
    `write_text` round-trip silently converts every `\r\n` to `\n` — and this CSV is
    mixed (643 LF, 9 CRLF, from years of different sessions). One appended row came
    out as **10 added / 9 deleted**, with seven rows nobody had touched sitting in the
    diff looking edited. The tell is a numstat whose deletions exceed what you changed;
    the fix is to edit in BINARY (`read_bytes`/`write_bytes`) so untouched lines stay
    byte-identical, and `git diff --ignore-cr-at-eol --numstat` is what proves it. A
    line ending is content in a file whose diff people read.
  - **A COVERAGE RATIO OVER A CATALOG MUST NOT COUNT ENTRIES COPIED FROM THE SOURCE
    LANGUAGE — and the filter that keeps a source's own braces out of a
    frame-hole check cannot be built from the output (2026-08-11, the bulletin's
    translation layer):** two fabricated passes, one in the feature and one in my
    own check for it. (a) A translation catalog keyed on the English sentence can
    contain `"Stories": "Stories"`, and some of those are legitimate (a proper
    noun, a unit, `{n} mentions` in French) — so counting them as coverage lets a
    catalog of pure copies report itself complete, which is the exact shape of a
    pass on work nobody did. Count them APART and publish the count; a mutation
    that folds them into coverage then fails by name. (b) The render-integrity
    check for "a frame hole reached the reader" needs the set of OUR hole names,
    and my first version built it as `{holes in the frames} | {holes in the
    output}` — a superset of everything in the output, so the filter could exclude
    nothing and a publisher who writes `{x}` in a headline would be reported as
    our bug. Derive the set from the FRAMES the render declared (the translator
    tracks them), never from the text you are inspecting. TWO MORE POINTS worth
    keeping. A refused translation must render in ENGLISH rather than raise: a
    lost `{days}` prints a literal brace to a reader, and a `KeyError` would abort
    a whole document over one sentence — so it degrades visibly and the integrity
    check is what catches it. And a REORDERED frame must be honoured, since word
    order is the entire reason to translate a frame rather than its fragments;
    compare the hole SETS, never the sequence, and pin both directions.
  - **A MIXED-LANGUAGE DOCUMENT OWES ITS READER THE REASON, AND NUMBER GROUPING IS
    A MISREADING RATHER THAN A STYLE NIT (2026-08-11, same slice):** a French
    bulletin whose caveats are still English is not broken — they are simply
    untranslated — but a reader cannot tell that from a deliberate quotation, so
    the document states its own coverage (translated of total) above the first
    figure, computed AFTER the body so it counts what the body actually asked for.
    Read the report BEFORE composing that line or a fully-translated document
    announces a shortfall of exactly one: itself. The number half is the sharper
    one: `f"{n:,}"` renders 72,225, which in French convention reads as 72.225 —
    so the document says the grouping is English rather than pretending
    otherwise. Locale-aware grouping is deliberately NOT done here, because
    guessing per locale (a dot for German, lakh grouping for Hindi) trades one
    misreading for another and the fix belongs to the app-wide shared formatter.
  - **MEASURING TRANSLATION COVERAGE BY RENDERING ALONE REPORTS A WORKLIST COMPLETE
    WHILE HALF THE SENTENCES HAVE NO ENTRY (2026-08-11, same slice):** a record with
    no alerts carries no alert caveat, one with no stories carries no story caveat —
    so the prose the computing modules WRITE INTO a record is a surface no single
    edition exhibits. Harvest it from source as well (string literals assigned to the
    record keys the renderer translates), and declare it a CANDIDATE set rather than a
    total: it misses a sentence composed at runtime from two halves, and it includes
    method strings that belong to a selftest payload and never reach a document.
    Corollary on where a hover essay belongs: a 700-character `title=` explaining how
    to use a report is text nobody reads at the moment they act on it — put it in the
    report's own payload, which also keeps twelve locales from owing a translation of
    it, and the i18n ratchet from going red over prose that had a better home.
  - **A CROSS-ARTIFACT REFERENCE IS ONLY AS GOOD AS THE ROUND TRIP, AND A FILE-COUNT
    ASSERTION CANNOT SEE THE HALF THAT BREAKS (2026-08-11, the bulletin's annexes):**
    a report that cites `[0007]` beside a ZIP holding `…_Article_0007.md` has a
    property no component owns — that the two are the same article — and a reader who
    follows a reference to the wrong one has no way to notice. TWO RULES. (a) The
    numbering lives in ONE deterministic function called by BOTH sides, never in each
    side's own loop: two numberers agree until the day one of them walks a surface the
    other does not. (b) The test iterates every reference the document actually PRINTS
    and asserts a file exists that names the same article — `len(namelist()) == 3`
    passes while the report cites two of them, which is exactly what happened here:
    the round trip is what surfaced that `story["article_rows"]`, added a slice
    earlier so "the document can name them", was printed by NEITHER renderer. A
    cluster of 115 articles arrived as a count with no way in, and the bundle held
    files nothing cited. GENERAL FORM: when two artifacts must agree, assert the
    correspondence in the direction a reader travels, not the cardinality of either
    end. COROLLARY on naming such a pair: derive the name from what the record SAYS
    it covers (the period), refuse when the record cannot say (never default to
    today — a bundle called `20260811_…` for a document about last month is a
    filename that lies), and make a repeat's ordinal a POSITION among siblings rather
    than a next-free counter, or re-downloading the same artifact renames it.
  - **A FIXTURE WHERE TWO DATES COINCIDE CANNOT TEST WHICH ONE A NAME USES
    (2026-08-11, the annexes date rules):** the rule was "an article file is named for
    its PUBLICATION date, never the day we collected it" — and the mutation that named
    files by the collection date **passed all 44 tests**, because the fixture published
    at 09:30 and collected at 10:00 on the same day. Same shape as the recorded
    bucket-granularity miss: the fixture matched production in every dimension except
    the one the rule is about. Published 2026-08-05 against collected 2026-08-09, plus
    one article published in a different YEAR driven through the real bundle, and the
    mutation fails eleven tests. GENERAL FORM: when a rule picks one of two fields,
    the fixture must make them DIFFER, and a distinguishing test asserts the loser
    appears NOWHERE (`not any("20260809" in n for n in names)`) rather than only that
    the winner appears. TWO COROLLARIES from the same change. (a) A derived name should
    come from the RECORD's own account of an event (`generated_at`), not from `now()`:
    a download-time date gives one document two names across two days, and it also
    breaks an ordinal computed per creation-day, since two editions made weeks apart
    but downloaded together would share a stem the ordinal cannot separate. (b) When a
    filename stops being derivable from an identifier the reader holds, the index that
    matches the two becomes load-bearing — say so in the citing document rather than
    leaving a reader to construct a name that no longer exists.
  - **THE TWO FACTS THAT MAKE AN AIR-GAPPED DEBIAN INSTALL POSSIBLE — and the one that
    breaks on the BETTER-equipped machine (2026-08-11, the offline installer, PR #931):**
    (a) Debian ships the stdlib `ensurepip` in a SEPARATE apt package, so an offline box
    cannot create a venv the normal way and `install.sh`'s existing fix (apt-install
    `python3.13-venv`) needs the network it does not have. `python -m venv --without-pip`
    never imports `ensurepip` at all, and a wheel is a zip with a runnable pip inside
    (`python /path/pip-X.whl/pip install …`), so pip installs itself from the bundle and
    the apt package stops mattering — verified by hiding `ensurepip` behind an
    ImportError-raising shim. (b) **Since Python 3.12, `python -m venv` installs pip and
    NOTHING ELSE — no setuptools.** An offline editable install must use
    `--no-build-isolation` (isolation would FETCH a build backend, the one thing that is
    impossible here), so the backend has to be present already; the online path gets it
    from its own `--upgrade pip setuptools wheel` step and the offline path has to do the
    same from the bundle. THE SHAPE WORTH REMEMBERING: this failed on the machine that
    HAD `ensurepip`, because the no-`ensurepip` fallback already installed setuptools
    correctly and the main path did not — when a feature has a fallback, the fallback is
    often the better-tested branch, so test the one you expect to be taken. Two more
    facts from the same build: `git clone --depth 1` implies `--single-branch`, so an
    orphan branch carrying a large payload does NOT reach `bootstrap.sh` users; and
    `pip download --only-binary=:all:` REFUSES a dependency that publishes no wheel
    (jieba, in `[segmentation]`) — `pip wheel` builds such an sdist into a wheel on the
    connected machine, so the air-gapped side only ever sees wheels and never needs a
    compiler.
  - **NEVER BUILD PROGRAM SOURCE BY INTERPOLATING SHELL VALUES — pass data as data
    (2026-08-11, the offline bundle's manifest generator):** an unquoted `<<PYEOF`
    heredoc with `"glibc": "$LIBC"` produced `SyntaxError: unterminated string literal`
    on a value that measured clean (`2.39`, no newline) in three separate reproductions,
    including under the same `set -euo pipefail`. I could not prove the trigger, and that
    is the point: the FIX is not to find which character escaped, it is to stop putting
    values into a grammar. Quoting the heredoc (`<<'PYEOF'`, no expansion at all) and
    reading the values from the ENVIRONMENT (`os.environ`) cannot break for any content —
    the same discipline as bound SQL parameters, one language over. GENERAL FORM: a
    generator that writes code is a place where data becomes syntax; keep the boundary.
  - **A GUARD OVER A FUNCTION THAT CONTAINS TWO SIMILAR CALLS IS SATISFIED BY THE WRONG
    ONE (2026-08-11, the offline no-network guard):** asserting `"--no-index" in body` for
    `_pip_install_offline` passed with the flag DELETED from the actual install command,
    because the same function has a second pip call (the build-tools step) that still
    carried it. This is the recorded non-unique-needle trap one level down — correctly
    SCOPED to a single function and still vacuous, since uniqueness has to hold WITHIN the
    slice too. Fold shell line-continuations, extract every invocation, and assert the
    property on EACH; and match the invocation (`python -m pip install`), not the words,
    or a `warn "…skipping pip install…"` message counts as a command. Mutation-checked in
    both directions afterwards.
  - **THE SINGLE-WRITER GATE IS TAKEN ON FLUSH, SO IT CANNOT PROTECT A FILE-LEVEL SWAP —
    the second half of the pair is a lease, not a wider use of the gate (2026-08-11, the
    restore's `os.replace`):** a restore commits with `dispose_engine(); os.replace(...)`,
    and a thread holding a checked-out connection across that keeps writing to the OLD,
    now-unlinked inode — silently lost, and worse than lost, because a job with a durable
    cursor has already advanced PAST those articles so nothing goes back for them.
    Reaching for the write gate is the obvious move and it does not work: a re-index batch
    holds a connection through its whole read-and-extract phase holding **no gate at all**,
    so a swap landing there sends the flush that follows to the orphaned inode with the
    gate dutifully held. The gate serialises WRITERS; a swap needs to know nobody is
    holding the FILE. THE PAIR THAT WORKS is two halves neither of which is sufficient:
    the exclusive window stops a new batch from STARTING, and a lease held across each
    batch proves none is IN FLIGHT — then the swap waits out whatever had begun and
    ABORTS on timeout, at the last point where aborting is free and the live corpus is
    byte-identical. Waiting forever trades a data-loss window for a hang; swapping anyway
    IS the data loss. TWO DESIGN POINTS worth reusing: a lease must be **observed and
    never waited on by its holder**, because a job that runs INSIDE the window its own run
    opened (a queue item) would otherwise deadlock against itself — that is also why the
    lease wraps the BATCH and not the run, so a parked worker holds nothing and cannot
    make a restore wait out a job that is deliberately idle. **AND THE GUARD FOR IT MUST
    CHECK SCOPE, NOT PRESENCE:** the first cut asserted `"from … import corpus_lease"`
    appeared somewhere in the file, a scripted edit duly placed it in a sibling function,
    and the guard passed while the use site raised `NameError` — only ruff's F821 caught
    it. Any "module X imports what it uses" assertion has to resolve the binding (ast,
    enclosing scope), or it is satisfied by an import that cannot be seen from the call.
  - **ADDING A WAIT PAST AN ABORT POINT MAKES THAT ABORT POINT STALE — and the guard that
    notices will be anchored on a PROXY for the real boundary (2026-08-11, the same
    change, both halves found after it merged):** the restore's last poll is
    `_abort_point("swap")`, and the quiescence barrier went in just below it, so the first
    cut turned a ~0 s inert-Stop window into one of up to **180 s** — on the one control
    the operator is watching, against a ruling that says a pre-swap Stop aborts NOW. The
    fix is two halves and the ORDER of the second is the honest part: the wait takes a
    `should_stop` and returns early (it REPORTS, it never decides), and the abort point is
    RE-CHECKED after the wait but BEFORE the still-held refusal — otherwise someone who
    pressed Stop is told "another job is writing to your corpus", naming the wrong cause
    and sending them hunting a job that is not the reason. Both directions need pinning,
    because "honour the stop" is one edit from "give up early". **THE SECOND HALF cost a
    red `main`:** `test_there_is_deliberately_NO_abort_point_after_the_swap` split the
    source at `with timings.stage("swap"):` — but its own docstring names the rule as
    "after the atomic **swap**", which is `os.replace`, and the stage entry was only ever a
    proxy for it. The proxy went wrong the instant the stage gained legitimate PRE-swap
    work, so a correct abort was reported as a violation. Re-anchoring on the commit point
    is STRICTLY STRONGER for the property named (it still catches the one unsound thing and
    no longer fires on the many sound ones) — but note the direction of the reasoning:
    relax a guard only when its DOCSTRING's property is preserved and you can still fail it
    on the real violation, which is the mutation to run before touching it. GENERAL FORM:
    when a guard forbids something "after X", check whether it splits on X or on a landmark
    that merely used to coincide with X.
  - **A VALUE-BEARING SENTENCE LEFT IN A COVERAGE DENOMINATOR IS A FABRICATED FAIL — and the
    obvious way to remove it fabricates a pass instead (2026-08-11, the bulletin's own
    translation coverage):** the layer keys every sentence on its English text, which is what
    made ~110 stored caveats translatable without touching nine producers. It also swept in two
    things no key can ever match: a card SUMMARY, which every real producer composes as an
    f-string around live values (`~3.2× the prior rate (18 recent vs 5 before)`), and the WHOLE
    composed `signal_line` (`distinct sources 3 · articles 9`). Both counted as *missing*, so
    coverage under-reported permanently and both landed in the catalog stub, inviting a
    translation that would match exactly one corpus **and read as working** — the worse half,
    since a wrong-corpus translation is invisible where a gap is merely low. TWO RULES. (a) Split
    what is determinate: a label welded to its number can never be keyed, so emit `[label,
    value]` pairs and translate the LABEL — the labels here had been untranslatable since the
    layer shipped, not because anyone declined to translate them but because the string they
    lived in could not exist twice. Add the pairs ALONGSIDE the composed form; editions already
    on disk carry only the latter and must still render. (b) For what is NOT determinate, exclude
    it at the CALL SITE, which knows what it is holding, and publish the count with its reason —
    never by a heuristic over the text. A digit-based filter was refused outright: it would have
    reported a HIGHER coverage than the truth, and "Phase 1" and a `{n}` frame both carry digits
    while being perfectly keyable. The mirror mutation is the one to write first — widening the
    exclusion until it swallows real chrome passes every test about the gap and fails only a test
    that says *chrome still counts*. NAME THE UPSTREAM FIX in the payload (a keyable frame plus
    values, which `Card.title_i18n`/`title_vars` already does for titles), or the exclusion reads
    as the end of the matter rather than as a deferral.
  - **THE STALE-BASE RULE APPLIES TO A VERIFICATION WORKTREE, NOT ONLY TO A BRANCH CUT
    (2026-08-11, and it cost a whole duplicate derivation):** the recorded rule says local
    `origin/main` goes stale within minutes under fast merges, so fetch immediately before
    `git checkout -B`. I obeyed it for the branch and not for the BASELINE: a CI failure sent me
    to `git worktree add --detach … origin/main`, which resolved the ref I already had, and the
    guard duly failed there. That is a correct-looking confirmation of the wrong proposition — it
    proved the bug existed at a commit that was no longer main, not that it was unfixed — and on
    that basis I re-derived a fix a parallel session had already landed (identically for the
    anchor, and strictly stronger for the twin). A stale baseline does not merely risk dropping
    someone's merge; it MANUFACTURES a "this is main's bug, and nobody has fixed it" verdict,
    which is exactly the licence needed to build a duplicate. So: fetch before the baseline run,
    and print the SHA the baseline actually resolved to beside the result — this is the "a
    baseline diff is blind where the baseline is already red" family with a new member, the
    baseline that is stale-red. Corollary worth the same weight: when a red lane on your PR turns
    out to be the base's, check whether it is STILL the base's before writing a line of fix.
  - **A FIXTURE MISSING A FIELD PRODUCTION ALWAYS STAMPS SENDS THE TEST DOWN A FALLBACK
    BRANCH, AND A HARDCODED EXPECTATION THEN PINS THE FALLBACK BY ACCIDENT (2026-08-12, the
    annexes empty-bundle test going red at UTC midnight):** the recorded rule "never compare a
    hardcoded timestamp against a real-`now` marker" already existed and this still shipped,
    because the timestamp was never written as a timestamp — it was written as a *filename*.
    `test_an_edition_naming_no_articles_produces_an_honest_empty_bundle` built the minimal
    record `{"period": …, "masthead": {}, "sections": []}` and asserted the stem
    `20260811_OOS_Bulletin_Weekly`. `persist_edition` ALWAYS stamps `generated_at`, so that
    record cannot occur in the field; without it `creation_date` correctly took its
    `datetime.now(UTC)` fallback, and the literal in the assertion silently became "today".
    Green on the day it was written, red every day after — and the sibling tests in the same
    file all passed, because they use a `_edition()` helper that DOES carry `generated_at`.
    THE RULE: when a test omits a field, ask which branch the omission selects, not merely
    whether the object still validates — an incomplete fixture is not a smaller version of a
    production object, it is a DIFFERENT one, and it exercises the code paths that exist for
    the cases production does not produce. Repair it by making the fixture faithful (add the
    field production supplies), never by re-deriving the expectation from the implementation's
    own clock: `assert creation_date(x) == datetime.now(UTC).date()` cannot fail whatever the
    fallback returns, so it certifies nothing. Cheap detector, worth running after any date
    work: `grep -rln "20[0-9]\{6\}" tests/` and, for each hit, check whether the literal is an
    input the test CREATES (safe) or an expectation compared against something clock-derived
    (rots). Two of three hits here were the safe kind, which is why the grep alone is not the
    answer — the question is which side of the assertion the literal sits on.
  - **A "MUST BE PRESENT" SOURCE GUARD IS SATISFIED BY THE COMMENT THAT EXPLAINS THE THING
    IT GUARDS — the recorded trap's mirror, and the worse half (2026-08-12, the import
    queue's `queued=True`):** the ledger records twice that a "must be GONE" guard trips on
    the comment recording the removal, and that the fix is to strip comments rather than
    reword them, because that comment is what a future session reads before undoing the
    removal. Both entries describe a false RED. The mirror fails the other way: I asserted
    `"queued=True" in body` over a call site whose own comment opens *"queued=True: this
    item runs INSIDE the exclusive window…"*, so deleting the argument left the guard
    GREEN. A guard that fails open is strictly worse than one that fails loudly — nothing
    ever draws attention to it — and only the mutation caught it; re-reading the test would
    not have, since the assertion looks exactly right. FIX: assert the CALL, not the text —
    walk `ast` for the `Call` and check its `keywords` for `arg == "queued"` with a
    `Constant` `True`. A parser cannot see a comment, so the class closes by construction
    instead of by remembering to strip. GENERAL FORM: for any guard asserting a token is
    PRESENT, ask what else in the slice contains that token; the explanation of why it is
    there is the likeliest answer and it sits directly above the guarded line. COROLLARY
    from the same hour, same shape one level out: `ruff check … | grep -E "^(src|tests)/"`
    matched nothing in EITHER direction (ruff's default output does not start lines with
    the path), so a "does my change add findings?" comparison silently compared empty to
    empty and read as clean — the false green in the verification harness rather than in a
    test. `--output-format=concise` makes it real, and the tell is the same one the
    recorded `cmd | tail` lesson names: a check you expect to be interesting never says
    anything interesting.
  - **A SENTINEL THAT MEANS "NOTHING TO MEASURE" AND "COULD NOT MEASURE" AT ONCE CAN MAKE
    THE EVIDENCE A GATE ASKS FOR UNREADABLE — and the how-to may be what produces it
    (2026-08-12, the P0.4 unlock check at >1M articles):** `wal_bytes_before_open()`
    returns `None` on any `OSError`, and `FileNotFoundError` is one, so an ABSENT `-wal`
    and an unreadable one shared a value. Absent is not an absence of data: **a clean
    SQLite WAL-mode close checkpoints and DELETES the `-wal`** (verified with a five-line
    repro, not assumed), so "no WAL" is the real, informative measurement *nothing to
    replay* — and it is the NORMAL state after the very cold boot the acceptance bar asks
    the operator to produce. THE PART WORTH MOST: the check's own how-to told them to
    "cleanly shut the app down", so following the instructions **guaranteed** the null the
    report then presented as missing evidence, and two consecutive field runs reported a
    passing unlock that nobody could bank. The bar compounded it by justifying the cold
    boot as testing "WAL recovery, the phase that grows with the corpus" — which a clean
    shutdown by construction never exercises, so the stated reason for the instruction was
    false about its own mechanism. THREE RULES. (a) For any `None` a report publishes, ask
    what it means in EACH direction before treating it as a gap — this is the recorded
    "gate each floor on its own denominator" lesson at the level of a single field, and the
    `.get(key, 0)` family's mirror (there a default invented a measurement; here a
    sentinel destroyed one). (b) When a check tells an operator how to produce evidence,
    trace the instruction to the value it yields — an instruction that reliably produces
    the unreadable case is worse than no instruction, because it costs a full re-run to
    learn nothing. (c) Fix it ADDITIVELY where a shipped surface reads the old field: the
    three-state record lands beside `wal_bytes_before_open`, whose two-state meaning is
    preserved exactly, so `app.js` and the existing guard stay byte-unchanged and the only
    thing that changes is what the report can SAY.
  - **A `::after` INHERITS EVERY PROPERTY IT DOES NOT DECLARE FROM A LOWER-SPECIFICITY
    RULE THAT ALSO MATCHES — and a shape can therefore be absent for months with nothing
    to point at (2026-08-12, the AI pill's diagonal bar):** `#llm.ai-off::after` declared
    `content`, `position`, `inset:0`, `pointer-events` and a gradient, which looks
    complete. But `.pill.oo-tip-target::after` is the hover convention's 4px corner dot,
    and EVERY titled element is given that class by the i18n/tip observer — so the pill
    always matched both rules. The cascade merges per PROPERTY, not per rule: the id
    selector won for what it declared and silently inherited `width:4px; height:4px;
    border-radius:50%; opacity:.55`. An absolutely positioned box with left, right AND
    width all set ignores `right`, so the maintainer's ruled "red WITH A DIAGONAL BAR"
    resolved to a 4×4 rounded dot in the top-left corner at 55% opacity, over which a
    50%-stop gradient is invisible. The bar had not rendered since the pill gained a
    title, and the state's whole no-colour-alone cue was gone. THREE RULES. (a) When
    adding a pseudo-element to a component that already has one from a shared
    convention, enumerate what the OTHER rule sets and restate all of it — `inset` covers
    four sides and nothing else. (b) Reasoning about this is how it shipped: the computed
    values settle it in one call (`getComputedStyle(el, '::after')`), and this sandbox has
    Chromium, so measure. (c) The same pass measured the marks' contrast from RENDERED
    PIXELS and found the semantic token is often the ceiling — `--ok` tops out at 2.69:1
    for a mark sitting on a pill already tinted in that hue, under the 3:1 WCAG 1.4.11
    non-text bar; mixing toward `--fg` (65%) lifts it to 4.65:1 while keeping the hue
    readable, the same repair `--caveat` and `.ag-cal` needed. A first probe that read
    `backgroundColor` instead of pixels reported garbage (the mark is a gradient, and
    `.pill` sets no background so the baseline fell back to white on a dark page) — the
    recorded lookalike trap, in a stylesheet.
  - **A "MUST BE PRESENT" SOURCE GUARD IS SATISFIED BY ITS OWN EXPLANATORY COMMENT
    (2026-08-12, same slice — the recorded trap in mirror image):** the ledger already
    warns that a "this string must be GONE" guard trips on the comment recording the
    removal. The positive direction is worse, because it fails silently: the guard added
    to stop the leak above asserted that each rule declares `width:`/`height:`/
    `border-radius:`/`opacity:`, and the comment beside the fix quotes
    `width:4px; height:4px; border-radius:50%; opacity:.55` verbatim to say what leaks —
    so deleting every real declaration left the guard GREEN. Caught only by mutation.
    Strip comments before asserting (`re.sub(r"/\*.*?\*/", "", css, flags=re.S)` for CSS,
    the existing `strip_comments` for JS); rewording the comment is the wrong repair,
    since it is exactly what a future session reads before deciding the resets are
    redundant. GENERAL FORM: any source guard — in either direction — must read
    comment-stripped source, because the explanation of a rule necessarily contains the
    rule's own vocabulary.
  - **A TIMING COMPARISON CAN BE UNSOUND IN BOTH DIRECTIONS AT ONCE — and raising the
    input only repairs the PROPORTIONAL case (2026-08-12, the llm-throughput concurrency
    check):** the check proving four workers really run in parallel asserted
    `parallel_wall < serial_wall`, and `run_concurrent` is a plain for loop at
    `max_workers <= 1` and a ThreadPoolExecutor above it — so the parallel side pays a
    pool-creation cost the serial side never pays: the noise is a FIXED term against a
    fixed signal, not jitter that shrinks as the work grows. Measured under 8x CPU
    oversubscription, pool creation reached **132 ms against the 120 ms signal**, and the
    shipped configuration failed **2/200** with a worst margin of **-500 ms**. **THE
    RECORDED WAL REPAIR DOES NOT TRANSFER HERE:** raising the input (50 ms calls, or 16
    calls) lifted the floor to 600 ms and it STILL failed **1/120**, because the stall
    tail is unbounded rather than proportional — so no fixed floor is safe, and shipping a
    bigger constant would have been an unmeasured fix to a defect that survives it. Raise
    the input when the noise scales with the work; change the CLAIM when it does not.
    **THE HALF NOBODY MEASURES IS THE FAIL DIRECTION:** against a genuinely serial pool
    both levels take the same time, so the comparison is near a coin flip and caught the
    defect it exists to catch only **29/40** times — the guard was worse at its job than
    at its false alarms, and only a mutation shows that. The replacement is the
    load-independent claim underneath (a rendezvous proving W calls were in flight AT
    ONCE: a stall can delay that moment but cannot make it false) — 60/60 under the same
    contention, and 100% detection of the serial pool. TWO DESIGN POINTS: a rendezvous
    must GIVE UP ONCE and then open permanently, or a genuinely broken pool pays the
    timeout per CALL instead of per run; and it must exclude the bench's warmup call
    explicitly, since that call arrives alone and would otherwise trip the give-up path
    before the measured level starts. NOTE the propagation failure — this file's own
    sibling test had already replaced a timing THRESHOLD with an exact identity for the
    RATE assertion, with a docstring saying "do not re-derive a discriminating threshold
    from timings", and the concurrency assertion three lines up was left as a timing
    comparison. A lesson recorded against one assertion does not propagate itself to the
    one beside it. **THE SOAK THEN FOUND THE THIRD ONE, in that same sibling:** its
    surviving anti-vacuity ratio (`measured < assumed / 2`) failed 1/12 at **0.522**.
    `call_wall_p50_s` is timed PER CALL and includes the queue wait, so `assumed =
    3600/p50 x workers` and `measured = n/wall x 3600` are not independent — as
    contention rises the queue inflates p50, `assumed` falls toward `measured`, and the
    ratio drifts UP toward whatever bar is set. **Two quantities that converge by
    construction cannot be separated by a threshold at all**, however it is calibrated;
    the repair is a structural cap (a `lanes`-lane backend cannot exceed `lanes/seconds`
    — an UPPER bound contention can only satisfy) plus a timing-free companion. **AND MY
    OWN FIRST REPAIR WAS TOO WEAK, caught only by mutation:** asserting the assumed rate
    falls OUTSIDE the identity's own rounding band sounds exact and proves almost
    nothing, because a *perfectly-scaling* fixture also differs by far more than a 37/h
    band — so it passed the `lanes=64` mutation that is precisely the vacuous case.
    GENERAL FORM: an anti-vacuity assertion needs its own mutation, and the mutation is
    to feed it the VACUOUS fixture — not the broken one.
  - **TWO HARVEST INSTRUMENTS, EACH BLIND WHERE THE OTHER SEES — so the durable answer is
    neither, it is a guard (2026-08-12, translating the annexes bundle):** collecting every
    sentence a module needs translated, I drove its branches and **missed five** (an
    empty-index paragraph, `No articles`, `(untitled)`, a lexicon-reads-English-only gap, a
    no-text-included paragraph) — branch-driving cannot reach a branch you did not think to
    drive. An AST scan of `T.t("literal")` found all five and would have missed the labels
    `_md_kv(T, label, value)` takes as a **parameter**, which are never literals at the call
    site. Neither is complete alone, and a union of two incomplete instruments is still a
    guess about the next string somebody adds. Ship a CI guard that walks the module's own
    AST and fails naming the string, the locale and the file. THREE SMALLER TRAPS from the
    same slice. (a) **A key is only reusable where the whole SENTENCE is** — reusing the
    already-keyed `"Period"` looked free and its French entry is the genitive fragment *"de
    la période"*, which reads as garbage as a table label; check the target-language value,
    not just that the key exists. (b) **Never hand a translator a row whose delimiters are
    load-bearing** — one long pipe-delimited Markdown header is a row a translation destroys
    by dropping a pipe; translate the words and keep the pipes ours. (c) The returned dict
    reported 54 chrome strings while its own page printed 53 — the count-drift class again,
    fixed by recording into an out-parameter BEFORE the line that composes its own count.
    GENERAL FORM for the headline: when a change's correctness depends on having enumerated
    a set, ask what each enumerating instrument is structurally unable to see, and prefer a
    mechanism that fails on the next addition over a list that was complete once.

  - **A CAPABILITY ADDED FOR ONE OF TWO FUNCTIONS THAT DO THE SAME JOB REACHES ONLY THAT
    CALLER — and the field report that motivates it will arrive a second time, from the
    other side (2026-08-12, "re-index + prune keywords is taking days … 1 cpu thread is
    too slow"):** `reindex_articles` and `reindex_all_batch` both force-re-index a set of
    articles through `index_article`. The parallel precompute went into the first on
    2026-07-19, in response to *"a large restore pinned one CPU core for hours while the
    other cores sat idle"* — and `reindex_all_batch`, which is what the Settings "Clean
    up keywords" job runs, never even grew a `workers` parameter. So an import used every
    core and the standalone re-index used one, for the same work, for as long as nobody
    ran both. THE FIX IS DELEGATION, NOT A SECOND COPY: the window now goes to
    `reindex_articles`, which also carries the pool-deadlock fix, the retry on a transient
    lock, the no-loss redo after a batch rollback and the load/precompute/apply split — a
    second implementation of those would drift, and the drift would be silent.
    **THREE THINGS THE DELEGATION HAD TO GET RIGHT.** (a) **Do not pass `should_stop`
    down.** `reindex_articles` can abandon a window part-way, but `reindex_all_batch`
    returns `last_id` as a RESUME WATERMARK — stamping `ids[-1]` for a window that stopped
    early skips every article after the stop point permanently. The job stops BETWEEN
    batches, where the watermark is honest; the guard is a signature assertion, because
    the tempting symmetry is one edit away. (b) **The parameter that exists on only one
    side is the silent loss.** `scope` ("keywords" = the fast keyword-only cleanup) had no
    equivalent on `reindex_articles`; dropping it on the hop passed the ENTIRE SUITE, and
    a keywords-only run would have quietly become a full one — slower, and rewriting the
    when/where/who the operator asked it to leave alone. The reason the suite was blind is
    worth more than the bug: the one test named for this asserts the status STRING the
    manager sets, never the effect, so *"the job threads scope through"* was true of the
    label and false of the work. (c) **Assert the PATH the pool reports, not that the call
    accepts an argument.** `precompute_batch` declines below `_MIN_PARALLEL_BATCH = 16`
    and for any extractor outside `_RECONSTRUCTIBLE_EXTRACTORS = ("baseline", "spacy")`,
    so a fix that plumbs `workers` into a window too small, or an extractor the pool
    refuses, stays single-core while passing every output-equality test. COROLLARY on the
    instrumentation added beside it: accumulate seconds as a FLOAT and round only on the
    way out — rounding each batch and summing floors every sub-second batch to zero, and
    over the thousands of batches a million-article run takes a real cost reports as none
    at all, which is worse than not measuring it. **AND THE GATE THAT CAUGHT WHAT THE
    SUITE COULD NOT:** the last edit of this slice (the scope-aware task shape) appended a
    5-tuple where an earlier branch appends a 6-tuple, so mypy inferred the element type
    from whichever branch it saw first and rejected the other — a real error, in my own
    new code, that CI found and I did not, because after that edit I re-ran the TESTS and
    not the TYPE GATE. Both are gates; finishing a change means re-running all of them,
    and the temptation to skip is strongest exactly where the edit "only" changes a tuple.
    (`tasks: list[Task] = []` fixes it — the alias is a bare `tuple`, so both shapes are
    valid, which is the point the annotation now documents.) COROLLARY WORTH KEEPING: this
    sandbox reports **one fewer** mypy error than CI does (48 files vs 49 — one module's
    import resolves there and not here), so the local number that corresponds to a GREEN
    ratchet is **126, not the 127 baseline**. Reading 127 locally as "at baseline" ships a
    red lane; the error itself reproduced here perfectly once the gate was actually run.

  - **A COST THAT SCALES WITH THE CORPUS RATHER THAN THE BATCH IS INVISIBLE IN THE KNOB
    THAT SIZES THE BATCH (2026-08-12, "source validation takes too much time"):**
    `qualification_per_pass` defaults to 5 and reads like a small, honest budget — judge
    five candidates a pass. The actual cost of a pass is `per_source_metrics` ->
    `collect_article_stats`, a `GROUP BY` over the **whole `keyword_mentions` table**
    plus a full `articles` scan, materialised in Python. That is paid ONCE PER BATCH and
    tracks the CORPUS, so at a million articles the five candidates are free and the scan
    is everything. The knob therefore misleads twice: raising it barely costs more, and
    lowering it barely saves — while the number an operator naturally reaches for to make
    a slow thing faster is exactly the one that cannot. The bulk job's own docstring had
    already measured the consequence (42.6k-66.7k candidates at 5/pass = 90+ days) and
    even named the mechanism in an aside about a concurrency risk, so the finding was
    sitting in the tree, correctly written down, one level away from the person reading
    the knob. GENERAL FORM: when a budget parameter does not visibly change the wall
    time, find what the loop body costs INDEPENDENTLY of the budget before tuning it — and
    when a per-item budget guards a per-batch fixed cost, say so where the knob is, or
    every future reader re-derives it. THE FIX SHAPE, recorded and NOT built here: hoist
    the cohort baselines out of the batch loop (compute once per run, then judge each
    batch's candidates against them, scoping the per-candidate metrics by `source_id`),
    which turns O(corpus) per batch into O(corpus) per RUN. It is deliberately unbuilt
    because it changes the verdict path, and shipping an unreviewed change to a
    data-safety-adjacent decision immediately before a ten-day unattended run is the
    wrong trade. COROLLARY worth as much: the same scan materialises ~1M stat objects and
    a ~1M-entry dict per call, and the memory guard polls only BETWEEN batches — so it
    cannot interrupt the scan it most needs to. A guard that runs between the expensive
    things is not a guard on the expensive thing.
  - **SQLite's LIKE OPTIMIZATION NEEDS A `COLLATE NOCASE` INDEX, AND A "SCAN … USING
    COVERING INDEX" IS WHAT ITS ABSENCE LOOKS LIKE (2026-08-20, the omnibar keyword
    group):** `x LIKE 'abc%'` is rewritten into a range scan only when the indexed
    column's collation matches the LIKE case-sensitivity — and since
    `case_sensitive_like` is OFF by default, that means the index must be NOCASE. The
    keywords table's index is BINARY, so the rewrite could never fire and every
    debounced omnibar keystroke traversed all ~5M keys, twice. Measured at 2M rows:
    126.7 ms → 0.02 ms (count) and 140.8 ms → 0.22 ms (top-3). **TWO THINGS I GOT WRONG
    BY RECALL AND FIXED BY MEASURING**, which is the transferable half: I "remembered"
    that an `ESCAPE` clause disqualifies the optimization — it does NOT, at least
    through SQLite 3.45; and my first bench omitted `idx_keyword_frequency`, so the
    planner picked a different pre-fix path and the before-number moved once the
    table's REAL index set was present. The recorded "a standalone SQL probe is a
    lookalike" lesson has a third axis beyond stats and ANALYZE state: **the rest of
    the table's indexes.** Reproduce the index set, then capture the statements the
    production path emits (`before_cursor_execute`) and EXPLAIN those. And note the
    plan vocabulary: the pre-fix count read `SCAN … USING COVERING INDEX`, which the
    repo's own classifier calls healthy — index-only is not the same as bounded, and a
    full traversal of a covering index over 5M rows is still a full traversal.
    **THE INDEX IS CHARACTERISED AND NOT SHIPPED, and the reason is the durable half:
    an entry in `HOT_INDEXES` is not optional-to-mirror on its model.** Wiring the
    self-heal alone flipped `alembic_stamp_align`'s verdict to `schema-behind`, because
    that check compares the LIVE schema against the MODELS and an index the boot
    self-heal creates but no model declares reads as drift — which is why every
    existing entry in that dict carries a "mirrored on the model + migration" comment.
    Mirroring it does not resolve it either: **`COLLATE NOCASE` makes it an EXPRESSION
    index, and alembic's autogenerate cannot compare those** — it warns "should either
    skip expression indexes or provide a custom implementation" and then reports a
    permanent spurious "changed index". So a NOCASE/expression index needs a
    migrations-layer decision (an `include_object` exclusion or equivalent), not just a
    DDL string. GENERAL FORM: before adding to a boot-self-heal index dict, check what
    ELSE compares the live schema to the models — the dict is not a free-standing
    performance knob, it is one of three places that must agree.
  - **THE "NEVER CAPPED FIGURES" SWEEP HAS MORE INSTANCES, AND THE ONE THAT BITES IS A
    `limit=` DEFAULT (2026-08-20, the omnibar articles total):** the 2026-07-18 ruling
    asked for a sweep for "any other displayed figure that is secretly a cap". Here it
    was `total: len(ids)` where `ids = search_ids(...)` and `search_ids` carries
    `limit=_MAX_CANDIDATES` (20000) — so on any corpus where a common term matches more,
    the omnibar published a flat 20000 as a count. The shape to grep for is not
    `.limit(n)` at the call site (which is visible) but a **helper whose own signature
    caps**, read by a caller that treats the returned length as a measurement. THE FIX
    IS FREE IN THE COMMON CASE: under the cap `len(ids)` IS exact, so only a list that
    actually FILLED the cap pays for a count — which is also the only list whose length
    was ever a lie. **AND STATE THE COST HONESTLY: this is not a speedup.** Measured on
    a 300k-doc FTS fixture, a broad term costs 438 ms against 415 ms, +5.6% for a right
    number instead of a wrong one — worth it, and not something to dress as performance
    work. **THE TEST TRAP, which cost a vacuous guard:** compressing the module CONSTANT
    is not enough to reach the branch, because the helper's `limit` is a DEFAULT
    ARGUMENT bound at definition time — the fetch still returned every row, `len(ids)`
    was still exact, and the first draft passed against the reverted fix. The list must
    genuinely be truncated.
  - **A FINDING CAN BE RETRACTED BY A LATER FIX — re-check a brief's PREMISE, not just
    whether its item is done (2026-08-20, the five 100%-outlier sources):** the
    2026-07-21 field brief named five sources at 100% `outlier_rate` and reasoned that
    "a 100% rate across a real sample is much more consistent with broken extraction",
    proposing they be hand-checked. That inference was made unsafe by the auditor's own
    arithmetic: `robust_stats` p90 is nearest-rank, so on a cohort with zero spread p90
    IS 0.0, the tail test `value > p90` degenerates to `value > 0`, and ONE pathological
    article in ~2,000 scores 100%. Root-caused and fixed 2026-08-02. Building the
    proposed tool would have been building on a withdrawn signal. GENERAL FORM: the
    staleness guard is usually run as "is this already built?" — run it also as "is the
    MEASUREMENT this item rests on still one the code would produce today?", because a
    fix to an instrument silently retracts every finding that instrument reported. Same
    pass, same brief: five of its seven items were already closed and its own
    three-week-old banner said "still fully unaddressed", so a status line ages faster
    than the finding it describes.
  - **A WALK'S INSTRUMENT PASSES OR FAILS FOR REASONS ABOUT THE INSTRUMENT — five
    lookalikes from one matrix run, and the axis-widening payoff that justified it
    (2026-08-20, gate row 8's stretch expansion):** (a) `querySelector(".pill.warn")`
    measured the AI PILL — an element that carries those classes for footprint styling
    while its STATE rules override the colour per state — and filed a P1 naming the
    `--warn-fg` token whose fix was intact (5.78:1 on the theme it accused); the first
    match of a class selector can be an element whose classes mean something else, so
    exclude it (`:not(#llm)`) and measure the state label as its OWN claim. (b) A
    surface anchored on a BY-CONSTRUCTION-EMPTY element (`#ux-imp-summary` before any
    import) reads not-visible and fails the reachability walk it was meant to serve —
    anchor reachability on the container, and let a dedicated fixture (state D's real
    import) claim the content. (c) A breakpoint walk that NAVIGATES at 375px tests
    navigation-at-375 — a different claim, and one the sidebar legitimately fails below
    600px per invariant #2's own floor — so the settings-gear click times out and three
    of five flagship surfaces read blocked; navigate at desktop width, then measure the
    OPENED surface at the target width. (d) A specimen-search that derives a CSS
    selector from tag/class hands the reader the DOCUMENT'S first `td`, not the
    specimen's — the recorded non-unique-needle trap as a selector; tag the found node
    with a probe attribute and address that. (e) A sidecar API probe shares 127.0.0.1
    with the harness's own browser, so the app's rate limiter (a feature under test)
    can 429 it past any polite backoff — read ids from the DOM the browser already
    rendered. PLUS the f-string continuation trap that produced two of the five: in a
    multi-line `page.evaluate(f"... {{ ..." "... }}")` the PLAIN-string continuation
    line's `}}` stays a literal `}}` (only f-strings collapse braces), a JS
    SyntaxError — and after fixing it in one evaluate it was found AGAIN in a sibling
    drill in the same file, the recorded fixing-a-property-in-one-place failure. THE
    PAYOFF THAT MAKES THE MATRIX WORTH ITS COST: widening the theme axis 5 → 17 found
    the AI pill's ai-off label at raw `var(--err)` below AA text contrast on 13 of 17
    themes (worst solar 2.41:1 against the pill's own 8%-err tint) — invisible to every
    earlier 5-theme run; the repair is the recorded mix-toward-`--fg` pattern (55% =
    the smallest 5-point step clearing 4.5:1 on every theme, worst 4.82:1), and the
    state was never colour-only (the diagonal bar + hover title carry it). And the
    deduced-events find is the same family app-side: `#agenda-subonly` defaults CHECKED
    and its bypass named only `imported`, so the corpus-DEDUCED category — whose
    synthetic calendar can never be subscribed — was invisible in every agenda view at
    default settings while the category filter still OFFERED "deduced" as an empty
    lens; a filter must never offer a category its default state structurally
    suppresses.
  - **A MAX-GATE RATCHET CANNOT DETECT ITS OWN INSTRUMENT GOING BLIND — check the count is
    UNCHANGED, never merely under the bar (2026-08-20, splitting the UI engine past the i18n
    scope):** the two JS i18n ratchets are maxima (`--max-untranslatable 561`,
    `--max-unkeyed-t-calls 298`), and finding I-1 already records this instrument once reading a
    green 100% while pointed at the wrong file. Splitting `app.js` into 17 modules pointed it at
    the wrong file AGAIN — and this time the failure would have passed more comfortably than
    success: fewer files scanned means fewer strings found means a LOWER count, under the bar,
    with the script printing *"the ratchet can now be lowered"*, which reads as progress. The
    direction of a max-gate is exactly backwards for detecting blindness. So the check that
    means anything is that the count is IDENTICAL — 561/298 at every wave, with every module
    present in the per-file breakdown — not that the gate is green. GENERAL FORM: for any
    ratchet expressed as a maximum over a measured population, a SHRINKING POPULATION and an
    IMPROVING CODEBASE produce the same movement, so a change that alters WHAT IS MEASURED owes
    a same-count check rather than a same-verdict one.
  - **SPLITTING A FILE THAT TESTS ASSERT AGAINST TURNS EVERY NEGATIVE ASSERTION VACUOUS, AT
    EVERY SITE AT ONCE (2026-08-20):** 80 test files now read the UI engine through the one helper, at 216
    call sites. After a split, a POSITIVE assertion (`"function X" in app`) fails
    loudly and gets fixed; a NEGATIVE one (`assert_absent`, `X not in app`) passes FOR FREE
    against a file that no longer contains the thing it checks — the exact vacuity failure
    `js_source_helper` exists to end, reintroduced at 151 sites in one commit and silently. The
    fix is a helper returning the CONCATENATION of the modules in load order, read from
    `index.html` so it cannot drift; because the split is a contiguous slice, that string is the
    semantic equivalent of the old file and every assertion keeps exactly its old meaning. THE
    QUIETER HALF: one reader wrapped its read in `if path.exists()` and SKIPPED the engine
    rather than failing — a guard that turns a missing file into a smaller scope is the same
    hazard wearing a safety belt, and only that file's POSITIVE assertions noticed.
  - **`T == "\n".join(lines)`, SO A NON-FINAL SLICE OWES EXACTLY ONE SEPARATOR — and adding it
    conditionally loses a newline whenever the slice ends on a BLANK line (2026-08-20):**
    splitting a file into contiguous slices looks like pure bookkeeping, and the obvious
    `if not text.endswith("\n"): text += "\n"` is wrong: when the slice's last line is empty the
    join ALREADY ends in a newline representing that blank line's own terminator, so the
    separator is never added and one byte vanishes at the seam. Caught on the FIRST run by a
    concatenation-must-be-byte-identical check, in seconds, with the exact byte offset. GENERAL
    FORM: when a change is supposed to move bytes without altering them, make the
    identity check the first thing that runs — it is total (nothing can hide from it), it
    localises (it names the offset), and it cannot be satisfied vacuously the way a test over
    the result can.
  - **A MIGRATION KEYED TO THE INSTRUMENT'S LANGUAGE MISSES EVERY READER IN ANOTHER ONE
    (2026-08-20, the fifteen node suites):** the brief named `tests/js_source_helper.py` as the
    thing to migrate source-asserting tests through, so I swept Python and reported the
    migration done. Fifteen `*_node_test.js` suites read the SAME file with their own
    `fs.readFileSync(path.join(__dirname, "..", "src", "static", "app.js"))`, were invisible to
    a Python-shaped search, and broke together the moment the file stopped existing. That they
    broke LOUDLY is the good case and not luck — each extracts a function BY NAME and asserts it
    was found, so an empty read is a failed assertion rather than a suite quietly testing
    nothing; the ratchet that every node suite has a driver is what made them run at all. TWO
    RULES. (a) When a change invalidates a way of READING something, enumerate the readers by
    what they READ (grep the path, the filename, the URL), never by the helper you intend them
    to use — the helper's language is your search's blind spot. (b) The fix is the same helper
    one language over, reading the module list out of `index.html` rather than hard-coding it,
    because fifteen hand-rolled copies of a path are precisely the debt the slicing ratchet
    exists to count.
  - **A TEST THAT ASSERTS A VERSION LITERAL PINS THE NUMBER, NOT THE PROPERTY — and it turns the
    CORRECT response to a change into a red lane (2026-08-20, `oo-shell-v1`):** the service
    worker's guard read `assert 'caches.delete(k)' in sw and 'oo-shell-v1' in sw` under the
    comment *"old cache versions are purged on activate"*. Changing the precached SHELL list
    REQUIRES bumping the cache name — without it a client that is already offline keeps serving
    the previous list, which is the one thing an offline shell must never do — so the first
    legitimate bump made the test red while the property it named held perfectly the whole time.
    Assert the mechanism instead: `caches.delete(k)`, the purge keyed on `k !== CACHE` (a purge
    naming specific old versions leaves the next one behind), and that the name carries a
    version at all. Both mutations fail; the literal caught neither. GENERAL FORM: when a guard
    quotes a value that is expected to CHANGE, it is anchored on a landmark that merely
    coincided with the property once — the same family as a guard splitting source on a landmark
    that used to coincide with the commit point.
  - **A CPU THROTTLE EMULATES A SLOW MAIN THREAD, NOT A SMALL MACHINE — and the difference is
    the whole result (2026-08-20, measuring what splitting the UI engine bought):** splitting
    `app.js` into seventeen modules measured **−38.8 %** main-thread script time under 6× CPU
    throttling, which is the number I would have reported. Three controls said the effect was
    real — an A/A run landed inside noise, swapping the order flipped the sign, a second server
    on a second worktree reproduced it — and two more said what it actually was. Removing the
    throttle **REVERSED** it (+21.6 %, 14.8 ms slower: sixteen extra requests and compile
    set-ups, which a fast main thread notices because it has no work worth moving). Pinning the
    browser to two cores cut it to −17.5 %. Both sides serve BYTE-IDENTICAL JavaScript — the
    split side ships 20,812 bytes MORE — so "less to parse" was never the mechanism: compile
    work relocates onto background threads that `Emulation.setCPUThrottlingRate` does not
    throttle, and the win is therefore proportional to the spare cores available to receive it.
    THREE RULES. (a) Name the mechanism before quoting the number: a packaging change that
    cannot reduce total bytes cannot be reducing parse cost, so a large "parse" win is evidence
    of RELOCATION and relocation depends on the machine. (b) A throttle knob and a core count
    are different axes, and a profile that throttles one while leaving the other generous is the
    most favourable case for anything that moves work sideways — the recorded "a probe's data
    distribution is part of the lookalike" trap with CORE COUNT as the varying axis. (c) An A/A
    control costs one extra run and is what separates "the harness has a position bias" from "the
    change did something"; it is the cheapest control available and the one that makes every
    other number readable.
  - **A WALKER WHOSE STEP COUNT VARIES CANNOT CARRY A SAME-STEP-COUNT CLAIM — find out before
    explaining it (2026-08-20):** the browser walk reported 52 steps at baseline and 59 from the
    next run onward, and I wrote a plausible sentence into the evidence section saying the count
    rose because the walker reaches more subtabs once the corpus is populated. It was invented.
    A control walk against the PRE-SPLIT tree produced **both numbers in a single run, from one
    server against one data directory** — so the seven flapping steps (all one tab's continent
    subtabs) are a race on whether that tab's fetch has populated the subtab strip when the
    walker reads it, and nothing to do with populated-versus-empty or with the code under test.
    GENERAL FORM: when a measurement moves and you can think of a reason, that reason is a
    hypothesis with a cheap test attached — run the old code again. And an instrument that varies
    run to run still supports the invariants it holds exactly (zero `pageerror`, the same 1393
    globals, in all fourteen state-runs); it just cannot support the one that varies, and saying
    which is which is what keeps the evidence section evidence.
  - **A WATCH WHOSE BASELINE IS THE SHIPPED VERSION FIRES FOREVER ON AN ARTIFACT THAT IS
    SUPPOSED TO LAG — and a gate that always fires is a gate nobody reads (2026-08-22,
    freshness issue #440, open two months):** `check_upstream_updates` compared the latest
    upstream release against `upstream_check.current`, which names the version we SHIP. For an
    `on-security` artifact lagging upstream is the CORRECT steady state — we re-vendor on a
    security fix, not on every release — so `vendored-alpine` flagged on every single Alpine
    release, the rolling issue could never close, and the whole watch decayed into background
    noise. That is the recorded "a gate you expect to be interesting never says anything
    interesting" lesson INVERTED, and the failure mode is worse: the one release that does
    carry a CVE arrives into an issue that has been red for months. FIX = keep the two facts
    apart rather than overloading one field (the standing one-key-two-meanings defect):
    `current` = what we ship, `reviewed_through` = the newest upstream release a human
    reviewed and CLEARED; the watch compares against the second when present. TWO GUARDS make
    it honest rather than a mute button — it is rejected on any policy but `on-security` (a
    `track-duckdb-version` entry must keep nagging until the coupling is really re-verified),
    and it may never sit BEHIND `current`. And the quiet branch must NOT reuse the "up to
    date" string: we still ship the older release, so it says "reviewed through X (upstream
    X)" — a mutation that reuses the old wording reddens by name. HONEST LIMIT recorded in the
    entry: this watch sees RELEASES, not ADVISORIES, so a CVE filed against a pinned version
    with no new release is invisible to it.
  - **READ THE TAGS, NOT THE ISSUE BODY — and ask whether the fix reaches what you SHIP
    (2026-08-22, the same issue):** the issue said Alpine v3.16.1; `git ls-remote --tags` said
    **v3.16.2** — an automated issue is a snapshot that ages, so re-derive the upstream state
    before reasoning about it (the same class as the stale-baseline trap, one input over). The
    review itself then turns on a question a version-diff cannot answer: of 190 commits in
    v3.14.1..v3.16.2 exactly one is genuinely XSS-shaped (#4770, escaping `&` and `"` before
    an `innerHTML` attribute write), and it lives in `packages/morph` — **our vendored bundle
    contains no morph at all** (four token probes, all 0). So the honest verdict is "no
    security fix applies to what we vendor", which is a stronger and more checkable claim than
    "no advisory exists" — and it needed the upstream GIT HISTORY, not the release-note prose,
    since Alpine publishes no CHANGELOG. Corollary on tooling: `git ls-remote` and a
    `--filter=blob:none --no-checkout` clone need no GitHub API access, which matters because
    `api.github.com` is repo-scoped in the sandbox and `github.com/advisories` + `api.osv.dev`
    are both egress-blocked (403) — state which kind of review you actually did.
  - **A PATCH BUMP INSIDE THE SAME MINOR CANNOT INVALIDATE A VERSION-COUPLED BUNDLE — check
    which component the coupling is on before doing the expensive checklist (2026-08-22):**
    duckdb v1.5.4 -> v1.5.5 reads like the trigger for the full per-platform httpfs rebuild
    the registry's `refresh` describes. It is not: `columnar._verified_httpfs` couples on
    MAJOR.MINOR, and `_duckdb_minor()` returns `"1.5"` at 1.5.5 (measured, not assumed), so
    any 1.5.x binary still matches and only a 1.5 -> 1.6 bump demands the rebuild. What WAS
    verifiable in-sandbox is the live half — pip resolves `duckdb>=1.4` to 1.5.5 today, the
    floor coupling holds, and the whole columnar lane is green at 1.5.5 (57 passed) — while
    the dormant half stays operator-gated because `extensions.duckdb.org` is egress-blocked
    and the binaries ship blank by design. Bumping `verified` is then honest ONLY with the
    split written down beside it; a bare "1.5.5" would imply the per-platform work happened.
  - **A "PIN AN OLDER VERSION" WORKAROUND IS ONLY AN OPTION IF SOME VERSION EVER CARRIED
    THE ARTIFACT — query every release, not the one pip resolved (2026-08-23, Windows on
    ARM):** an install died building `cryptography`, `statsmodels` and `httptools` from
    source on an ARM64 machine. Reading the resolved versions gave the obvious remedy —
    `cryptography` published `win_arm64` wheels for 46.0.0-46.0.3, so pin it — and the
    previous QUICKSTART had already recommended exactly that. Walking the FULL release
    history instead showed `statsmodels` and `httptools` have **never** published a
    `win_arm64` wheel, so there is nothing to pin the other two to and the whole route is
    dead: without a C and Rust toolchain the only thing that works is an x64 interpreter,
    which Windows on ARM runs natively and for which all three ship wheels. The check is
    four lines against the PyPI JSON API and it inverted the recommendation. GENERAL FORM:
    before proposing a downgrade, ask whether the thing being downgraded TO exists — for
    every blocker, not just the one you looked at first. **THE MECHANISM HALF is the trap
    that would have made the fix decide backwards:** what determines whether a wheel exists
    is the interpreter's own build platform (`sysconfig.get_platform()` -> `win-amd64` /
    `win-arm64`), NOT the machine — and `platform.machine()` on Windows reports the MACHINE,
    so an x64 python running under ARM64 emulation, which is precisely the configuration the
    fix installs, answers `ARM64` and every check built on it reads the opposite of the
    truth. THIRD, on defaults: a package manager asked to install without an explicit
    architecture picks the machine's own, so on ARM64 every install AND every retry path
    re-fetches the arch that cannot work — the architecture has to be named at each call
    site, and a guard that only checks the flag appears somewhere in the file passes while
    one retry quietly reinstalls the wrong build. And state a platform-gated precondition
    BEFORE the expensive step: the same warning printed after a twenty-minute source build
    arrives as the last line of a wall of Rust errors, where nobody reads it.
  - **⚠ THIS SANDBOX CAN RUN POWERSHELL — the standing "CI runs pytest and never
    executes install.ps1" caveat is a HABIT, not a limit (2026-08-23):** three
    consecutive Windows defects shipped because nothing ever ran the script. PowerShell
    publishes linux-x64 tarballs as GitHub release assets, and github.com is reachable
    here: `curl -sL .../releases/download/v7.4.6/powershell-7.4.6-linux-x64.tar.gz`,
    untar, `chmod +x pwsh`. That gives (a) a REAL parse — `[Parser]::ParseFile` — which
    is the `bash -n` equivalent the repo's own skipped test wanted all along, and (b)
    far more: pull the function definitions out of the real file with the AST
    (`FindAll` for `FunctionDefinitionAst`, dot-source each `Extent.Text` — never
    retype them) and EXERCISE them. Done here, that downloaded 14 MB from nuget.org,
    verified it against the publisher's attested SHA-512, unpacked it, and separately
    confirmed a tampered file fails the same comparison — the security-critical path
    proven live rather than asserted by a substring guard. Same shape as the recorded
    browser/py3.13 lesson: check what the box can actually do before writing
    "unverified" on a slice. **AND THE CATCH THAT PAYS FOR IT:** a pwsh-gated test
    SKIPS in the sandbox, so it is unverified until run with a real pwsh — mine was
    broken (`-Command` does not populate `$args`, so the script read a null path) and
    would have reddened the Windows lane. Run tool-gated tests with the tool, exactly
    as the Core-only-lane lesson says for optional extras; and pass a path to a
    PowerShell script as DATA in the environment, never spliced into the source.
  - **BEFORE PINNING A DEPENDENCY BACKWARDS TO SATISFY A PLATFORM, QUERY ITS ADVISORY
    RECORD — a pin that restores compatibility by reintroducing known vulnerabilities
    is not a fix (2026-08-23, Windows on ARM):** the obvious way to make a native ARM64
    install work was to pin `cryptography` to 46.0.0-46.0.3, the only series publishing
    `win_arm64` wheels. One call — PyPI's JSON carries a `vulnerabilities` key per
    version — says why not: **13 open advisory records at 46.0.3 against 0 at current**,
    including a statically-linked OpenSSL one fixed only at 48.0.1 and several
    certificate-chain bypasses. In an app whose value proposition includes tamper-
    evident signing, shipping that silently is the fabricated security this project
    forbids, so the compatibility pin was REFUSED as an automatic path and the honest
    fallback became a stop with the one-download fix (plus an explicit opt-in for a
    machine that really can compile). GENERAL FORM: a version constraint chosen for
    COMPATIBILITY is still a security decision, and the check is one HTTP call. THE
    SIBLING RULE, from the same fix: when the honest answer is "obtain the right
    artifact" rather than "downgrade", the acquisition needs a verifiable source — read
    the PUBLISHER's attested digest (nuget.org's catalog `packageHash` +
    `packageHashAlgorithm`, GitHub's release `digest`) and refuse on mismatch AND on a
    missing attestation, so "nobody published a hash" can never quietly become "install
    it anyway". Never write a digest into the repo for this: it would be fabricated (if
    you cannot reach the publisher to verify it) or rot into a false alarm that someone
    eventually deletes.
  - **RESOLVING A NEW INPUT DOES NOT RE-DERIVE WHAT WAS BUILT FROM THE OLD ONE — and the
    stale copy will be sitting right under the line that announces the new one
    (2026-08-23, the Windows venv):** the ARM64->x64 ladder worked exactly as designed in
    the field: detected the machine, tried winget twice, fetched the PSF's x64 CPython from
    nuget.org, verified it against the attested SHA-512, and printed
    `ok  Python 3.13 (win-amd64)`. Four lines later it printed `ok  Reusing the existing
    .venv` and pip went hunting `win_arm64` wheels. A `.venv` keeps the version and wheel
    platform of whichever interpreter built it, FOR LIFE, and the only check was
    `Test-Path` — so the entire architecture ladder was undone by derived state nobody
    re-derived, silently, with the correct answer printed immediately above the failure.
    GENERAL FORM: after changing how an input is chosen, list what is BUILT from that input
    and cached on disk (a venv, a lockfile, a compiled index, a generated config) and give
    each one a match check against the new value — existence is not a match. THREE RIDERS.
    (a) The check reuses the SAME probe the resolver uses (`Test-PythonCandidate` against
    the venv's own python), so the two can never disagree about what a match is; a second
    implementation would drift. (b) The negative-space twin is what makes it a guard rather
    than a rebuild: reusing a MATCHING venv untouched has to be asserted too, because a fix
    that rebuilds unconditionally passes every mismatch test and costs a full
    several-hundred-MB re-download on every run — both mutations redden the one behavioural
    test by name. (c) A replacement that FAILS (a locked folder) must stop, not fall through
    into the environment just judged wrong; and it is not prompted, because a `.venv` holds
    no user data and under `irm | iex` stdin is redirected, so a prompt would answer itself
    — say what is happening instead. Verified with pwsh in-sandbox that a venv reports its
    BASE interpreter's `sysconfig.get_platform()` (the premise the whole check rests on),
    and that the nuget package carries `venvlauncher.exe` + `ensurepip` with a bundled pip,
    so the vendored interpreter can build the venv it is now asked to.
  - **A RESOURCE WRITTEN INTO A DIRECTORY A LATER STEP REQUIRES TO BE EMPTY IS A
    DEADLOCK THAT DELETING THE DIRECTORY CANNOT FIX (2026-08-23, the Windows
    installer):** the nuget rung unpacked its interpreter into `$target\.python-x64`,
    and the step after it refuses when `$target` is non-empty and not a git checkout.
    So section 2 created the very condition section 3 rejects — reported from the field
    three consecutive runs, and it would have happened on every machine that needs that
    rung, forever. The operator deleting the folder does not help: the next run
    recreates it before looking. **THE PART WORTH REMEMBERING IS THAT RELAXING THE
    CHECK WOULD NOT HAVE FIXED IT** — `git clone` declines a non-empty directory on its
    own, so the emptiness check was not the obstacle, only the first thing to complain;
    the RESOURCE had to move. GENERAL FORM: when an early step writes into a path a
    later step constrains, the constraint is usually right and the placement is wrong;
    look for the step that owns that directory before assuming the guard is too strict.
    TWO RIDERS. (a) Ask what KIND of thing it is: an interpreter is a MACHINE resource,
    not a checkout resource, so outside the checkout it also survives the operator
    deleting the app folder — which matters because a venv whose base interpreter
    vanished is broken, not merely stale — and a second `-Path` checkout reuses it
    instead of re-downloading. (b) A copy left in the old place by the shipped version
    is MOVED, never deleted: deleting also clears the deadlock and costs every affected
    machine another download, so the twin test asserts the bytes SURVIVED, not just
    that the folder is empty. And moving a resource out of a tree means the uninstall
    no longer reclaims it by removing the tree — both sites must read ONE function, or
    the uninstall silently orphans it.
  - **A CACHE WHOSE KEY IS PER-CONNECTION HAS A 0% HIT RATE ON A POOLED ENGINE — and the
    tests around it will be witnesses rather than detectors (2026-09-03, S3.2):**
    `/api/database/stats` was guarded by a cache described in its own comment as VERIFIED:
    served only while `PRAGMA data_version` and `SELECT total_changes()` proved the database
    unchanged. The claim is true and the mechanism was dead. Both components are PER
    CONNECTION and diverge by OPPOSITE mechanisms — `total_changes()` counts only the writes
    THIS connection made since it opened (so two pooled connections disagree PERMANENTLY, not
    transiently), while `data_version` does NOT tick for the connection that wrote and DOES
    tick for every other. Measured through the production functions on a two-connection pool
    with ZERO writes: **six reads, six recomputes**. The default engine is `pool_size=5` + 10
    overflow, so on a live server the cache essentially never served and every 4 s poll paid a
    whole-table scan inline — 43 s for the mentions count on the field corpus. **THE THREE
    TESTS AROUND IT ALL PASSED, AND EACH WAS EVIDENCE OF THE DEFECT:** one had to
    `monkeypatch` the probe to a constant to observe a cache hit at all, with a comment
    blaming a "spurious" invalidation and a 2026-06-15 CI flake; two others passed only
    BECAUSE there were no hits (write a row, read the count on the next line). A test that
    freezes the mechanism it is testing is describing a lookalike, and a test that depends on
    a cache never serving will keep passing for as long as it never does. GENERAL FORM: a
    cache key must be a property of the DATABASE, not of the connection that happens to serve
    the request — and the way to find out is to drive the real `_cached` with two sessions and
    count computes, not to read the probe and reason about it. THE PROBE THAT WORKS was
    already in the tree: the write gate's `grants` counter, one process-global monotonic int
    bumped once per write transaction, measured against all four properties (pure reads do not
    bump it; it sees this connection's own write; it sees another connection's write from
    anywhere; it is comparable across connections by construction). **STATE ITS LIMITS RATHER
    THAN THE GUARANTEE YOU WISH IT HAD:** it is blind to a bare textual `session.execute(text(
    "INSERT ..."))` outside `write_lock()` (measured, unchanged) and to another PROCESS, so the
    corpus swap and VACUUM drop the entry BY NAME and every payload carries its real `as_of` —
    the offer is that the age is VISIBLE, never that it is zero. COROLLARY: the same broken
    cache existed as a VERBATIM COPY in `src/api/library.py`, which is how one copy gets fixed
    and the other quietly does not; and a namespacing wrapper added to prevent key collisions
    had a hole at the one call site that did not go through it, found by the test rather than
    by review.
  - **"SERVE STALE" AND "REFRESH WHEN CHANGED" ARE THE WRONG PAIR — the probe must gate the
    REBUILD, not the SERVE (2026-09-03, same slice):** the obvious design is "probe says
    changed → recompute", which is exactly the defect (during collection every poll pays the
    scan), and the obvious repair is "refresh at the TTL regardless", which on a corpus where
    the scan takes 43 s and the TTL is 60 s means a background rebuild running essentially
    continuously. Neither is right. The trigger is `age >= ttl AND the probe moved`: an idle
    app rebuilds NOTHING (the value is not merely fresh enough, it is still exactly correct),
    a collecting one rebuilds at most once per TTL, and the request thread never computes
    after the first cold call. TWO DETAILS THAT CARRY IT: keep `built_at` (the value's real
    age, which drives `as_of`) separate from `checked_at` (the refresh clock) — re-stamping
    `built_at` on an unchanged re-check restarts the age at zero and reports a value computed
    minutes ago as fresh; and single-flight the COLD path under a per-key lock with a
    double-check, or N simultaneous polls start N scans, which is the death-spiral shape the
    alert strip already hit.
  - **A MUTATION THAT SURVIVES IS A FINDING ABOUT THE TEST, AND THE USUAL FAULT IS THAT THE
    FIXTURE NEVER REACHED THE BRANCH (2026-09-03, same slice):** `test_an_unavailable_probe_
    is_never_read_as_nothing_changed` warmed the cache and THEN made the probe unavailable, so
    the stored probe was a real int against a `None` reading — unequal under both the fix and
    the mutant, and the mutation that reads `None` as "nothing changed" passed. The
    discriminating case is a probe that is `None` when the entry is BUILT as well as when it
    is read, i.e. the real case (an install whose write gate is off), where the mutant freezes
    the counts forever. Same shape as the recorded cache-suppression and bucket-granularity
    misses: ask what the mutant would SUPPRESS and build the fixture that reaches it.
  - **A GUARD THAT FIRES ON THE WRONG ASSERTION IS A GUARD WHOSE CLAIM IS UNTESTED
    (2026-09-03, S3.4):** the node harness for the poll backoff asserted both the SCHEDULE
    (the delay the chain asks for) and the SOURCE (that `startLive` reads the load factor).
    The source checks ran first, so the brief's own mutation — "schedules at exactly 15,000
    ms" — aborted the suite on a string before the delay was ever driven. It reddened, which
    is what makes it easy to miss: the suite failed, so the mutation looked caught. Order the
    BEHAVIOURAL assertion first, so the number the claim is about is the thing that fails
    (`got 15000`). And a rebuilt-from-source function must keep its SIGNATURE: extracting only
    the body and re-wrapping it as `function name()` silently drops the parameters, and the
    copy then throws `ReferenceError` on the very argument the real one is called with.
  - **A PER-SECTION DEGRADE EARNS ITS KEEP ON THE FIRST RUN, NOT IN THEORY (2026-09-03,
    S3.4):** the `server_load` composer wraps each of its three readings separately and reports
    `{"read": false, "reason": ...}` for one that raises, because "we could not read it" and
    "we read it and it is quiet" are opposite facts that must not share a key or a value. Its
    very first execution reported `TypeError: 'bool' object is not callable` — my own bug,
    `memguard.memory_guard.engaged` being a PROPERTY — where a naive `except: return
    {"engaged": False}` would have published a confident, wrong, permanent all-clear. When
    adding a composed diagnostic, write the honest-absence branch BEFORE trusting any of the
    sections, and give it a test that asserts a failed section does not also publish the value
    it failed to read.

  - **A CONTEXT MANAGER THAT CAPTURES A CONNECTION AT ENTRY AND RELEASES IT IN `finally`
    BREAKS THE MOMENT THE BLOCK LEGITIMATELY RECONNECTS — and the crash is the loud half
    (2026-08-23, the first field diagnostics bundle):** `statement_deadline` armed one raw
    DBAPI connection at entry and cleared its progress handler on that same object in
    `finally`, while the briefing registry's WAL guard closes its cursor and commits every
    30 s BY DESIGN — and on a NullPool bind returning the connection CLOSES the real handle.
    So the teardown raised `"Cannot operate on a closed database"` **from inside a
    `finally`**, replacing the member's return value: three bundle members (the only three
    that drive the producer registry, 400 s of a 713 s run) each finished their work and
    wrote 0 bytes. **A guard that can destroy the work it was guarding is worse than no
    guard.** THE QUIETER HALF IS THE ONE TO REMEMBER: a progress handler is
    PER-CONNECTION, so from the first reconnect onward the deadline was **not enforced at
    all**, with nothing raising to say so — measured on the unpatched code, a 1 s deadline
    let a runaway recursive CTE run 15.2 s to completion. Fixing only the crash would have
    left a guard that reports success and guards nothing. GENERAL FORM: for any resource a
    context manager acquires ONCE and releases at exit, ask whether the guarded block can
    legitimately re-acquire it — if it can, the manager must track every instance it armed
    (here a SESSION-scoped `after_begin` listener re-arms on reconnect; an engine-level one
    would arm other sessions' connections and interrupt their statements on your clock) and
    disarm each defensively, since releasing an already-released resource must never
    surface. And the mutation matrix has to revert EACH mechanism separately: dropping the
    re-arm fails only the enforcement test, un-guarding the disarm fails all three — which
    is how you learn both halves are load-bearing rather than one being decoration.
  - **A URL'S QUERY STRING CAN BE THE ARTICLE ADDRESS, AND `urlparse().path` THROWS IT AWAY
    (2026-08-23, the first criteria-calibration report):** the whole drop path proposed FOUR
    articles out of 5,010 and all four were false positives — `antiwar.com/news/?articleid=2504`
    and siblings, each recorded as *"section landing '/news'"*, each with a function-word
    density of 0.28–0.37 (prose; nav soup measures ~0.05). An older CMS puts the article id
    in the query and leaves the path a bare section; WordPress's own default permalink
    (`/?p=12345`) does the same to the homepage rule. Both rules exist on the premise that
    the URL names no item, which a query id falsifies — so the *reason* was untrue of the
    thing it was about, which is the defect even where the disposition is arguable. TWO
    RULES. (a) When a classifier keys on URL SHAPE, enumerate which components it reads and
    which it discards; a rule whose premise is "there is no item address here" must look at
    the query, not only the path. (b) Scope the repair to the rules whose premise actually
    fails — the taxonomy and utility rules key on an explicit path segment and must NOT be
    vetoed, or `/tag/gaza?id=9` stops being a listing. And keep the veto narrow in the
    direction that matters: the parameter name must read as a record id AND its value must
    contain a digit, so `?page=2` / `?tag=gaza` / `?s=query` rescue nothing, because the
    cost of a mistake here is a QUARANTINED REAL ARTICLE. PROCESS POINT: this is what the
    sign-off step in a clean-up gate is for. Proposing corpus-wide criteria from those four
    specimens would have quarantined four genuine articles and zero junk, and the report
    would have read like evidence.
  - **A STATISTIC'S PROSE IS A CLAIM, AND WHEN IT DISAGREES WITH THE CODE THE CODE IS
    PUBLISHING A VERDICT NOBODY ASKED FOR — plus: a whole-process sampler makes a
    diagnostic contaminate its own window (2026-08-23, the P0.3 collector `fail`):** the
    check computed `rise = max(numeric) - first` while the `climb_method` string it
    published beside the number promised *"a sustained absolute rise is the OOM signature
    at any baseline"*. `max()` cannot tell one excursion from a trend, so the two had never
    been the same measurement, and the field run duly reported *"the OOM signature"* over a
    series whose first, median and last passes were 1323 / 1371 / 1303 MB — **3 of 193
    passes (1.6 %)** above the floor, 71 *below* the first pass, opening-to-trailing fifth
    +176 MB against a 512 MB bar. A fabricated FAIL is exactly as dishonest as a fabricated
    pass, and it is more expensive here, because it points an operator at a leak that is not
    there. THE SECOND HALF IS THE ONE THAT GENERALISES FURTHEST: `collect_perf` samples
    `psutil.Process()` with **no argument** — whole-process RSS — so the app's own backup,
    restore and diagnostics work lands in the collector's samples, and the largest spike sat
    between two pre-restore snapshots the instance's own forensics timestamps. **Running the
    P0 validation contaminates the very window P0.3 reads.** RULES. (a) When a computation
    publishes a method string, assert that the string describes the arithmetic — the
    mismatch is invisible in review precisely because the sentence reads correctly. (b) For
    any "did this grow" verdict, take it from the SUSTAINED level (a trailing window against
    an opening one) and keep the peak as a *reported fact*: suppressing the excursion trades
    one dishonest reading for another, since a 2.4 GB spike is information even when it is
    not a leak. (c) Before reading a per-subsystem metric, ask whether the sampler can even
    see subsystems — a process-wide gauge attributes everything to whoever is being measured.
    (d) The twin is mandatory and cheap: a monotone climb AND a leak that saturates early
    must still fail, or the fix is just a detector that never fires.
  - **AN EXPENSIVE CALIBRATION ARM POINTED AT THE WRONG POPULATION MEASURES NOTHING THE
    DECISION NEEDS — and a resumable cursor pinned to 0 can never finish (2026-08-23, the
    row-5 criteria):** the clean-up decision is about the **451** index pages that clear the
    ≥100-word body guard — URL says listing, body length says article, so the corroborating
    prose measurement is the whole question. The report's prose arm instead walks the corpus
    by ascending id, and the bundle member pins `prose_gate_after_id=0` with `limit=500`, so
    every run re-measures the same lowest-id 500 articles, `done` can never become true on
    any corpus larger than 500, and two consecutive field reports both stopped at
    `last_id: 695` having flagged **0**. Nothing is mislabelled — the per-batch denominator
    is stated — but "resumable" reads as "will finish", and in the bundle it will not. So
    the proposal could only cover the 8-article drop path, against a 451-article problem.
    GENERAL FORM: when a report exists to calibrate a decision, name the population the
    decision is about and check the report's costly arm is pointed AT it; an arm that walks
    a natural key (id, date, alphabet) samples whatever that key happens to order first,
    which is almost never the population in question. And the honest move when the evidence
    is missing is to propose the tier you CAN corroborate and say plainly that the other one
    is unmeasured — quarantining 451 real-looking articles on a URL rule alone would be the
    lookalike trap wearing a clean-up's clothes.
  - **A TABLE BUILT TO DEMONSTRATE RIGOUR IS EXACTLY WHERE A CELL GETS BACK-FILLED
    (2026-08-23, correcting the gate's own evidence section):** two `origin/main` merges
    left gate §7.4 quoting `8423 passed` under the heading *"the tree that would be
    tagged"*, in the one section arguing that a pass count is load-bearing evidence. Fixing
    it, I widened the prose into a six-row table with a `skipped` column — and invented two
    cells doing it: a baseline of `40 skipped` (the ledger records **43**) and `+3 skipped`
    for a merge whose skip count provably did not move, since the runs bracketing it both
    read 43. A third cell, that merge's test count, came from a commit range spanning more
    PRs than the merge actually brought in. None of it was checkable from anything I had
    measured; all of it looked like diligence. THE MECHANISM IS THE FORMAT: prose states
    only the steps you have, while a table has a cell for every intersection and an empty
    one reads as an omission, so the shape itself asks to be completed. RULES: extend the
    prose rather than promote it to a grid unless every cell is measured; before writing a
    figure into an evidence section, name where it came from (a run you executed, or a line
    in the ledger) and drop it if the answer is "it follows"; and when a delta *can* be
    checked against the diff, check it — `+2 passed / +1 skipped` against three added test
    functions closes exactly, and that arithmetic is what the section is claiming to do.
    COROLLARY worth the same weight: a `skipped` count is not noise beside a pass count
    here — `pwsh`-gated installer tests correctly skip in this sandbox, so reading passed
    alone makes a merge look as though it under-delivered against its own diff.
  - **WINDOWS WILL NOT UNLINK A FILE SOMEBODY HAS OPEN, SO EVERY delete-then-replace
    PATH IS POSIX-ONLY-TESTED BY CONSTRUCTION — and the errno that looks like the
    signal is shared with the failure it must be told apart from (2026-08-23, a restore
    dying on `[WinError 32] ... open_omniscience.db-wal`):** the swap unlinks the live
    `-wal`/`-shm` before `os.replace`, which is load-bearing (a stale WAL beside the
    incoming database has SQLite replay the old log into the new file — corruption, not
    a failed import). POSIX unlinks an open file happily, so the step was correct by
    accident everywhere it had ever run. Compounding it, `engine.dispose()` closes only
    the pool's IDLE connections and leaves CHECKED-OUT ones to close as they are
    returned, so the swap legitimately meets a handle that is ABOUT TO GO AWAY — which
    is why waiting it out is the fix and not a workaround. FOUR THINGS WORTH KEEPING.
    (a) **`errno` cannot discriminate a lock on Windows**: ERROR_SHARING_VIOLATION (32)
    and ERROR_ACCESS_DENIED (5) both map onto `EACCES`, so an errno-based check reads a
    permissions failure as a busy file, burns the whole retry budget per file, and then
    tells the operator to close a program that was never the problem. `winerror` is the
    only signal that answers, and where it exists `errno` must not be consulted at all.
    Its sibling half was DEAD CODE: `isinstance(exc, PermissionError) and errno ==
    EBUSY` is unreachable, because Python raises a plain `OSError` for EBUSY and
    `PermissionError` only for EACCES/EPERM — measured, not assumed. Both were caught
    by the negative-space twin on its FIRST run, which is the whole argument for
    writing it. (b) **Never key on message text**: the field report arrived in French
    (*le fichier est utilise par un autre processus*), so any substring match would
    have missed the very report that produced the fix — and the test proves the CODE
    decided, by asserting that the identical message carrying no `winerror` is NOT
    recognised. (c) **Checkpoint before you unlink**: committed transactions live in
    the WAL until a checkpoint moves them into the database file, so unlinking a
    non-empty WAL and then failing the replace loses exactly those; checkpoint first
    and an abort at every later point is free. (d) **A checkpoint must be BOUNDED**:
    `checkpoint_wal` takes the single-writer gate and that gate's `acquire` has NO
    timeout, so calling it straight converts a restore that fails fast into one that
    hangs forever behind another writer — and a checkpoint that cannot finish MEANS a
    writer is active, which is the one condition the swap must not run under, so the
    caller aborts rather than proceeding. ORDERING IS ASSERTED FROM THE PARSE TREE, not
    as text: a comment explaining why the order matters necessarily names the same
    calls, so a substring search is satisfied by the explanation of the rule instead of
    the rule. **PROCESS NOTE, and the cheapest thing here to get wrong:** two mutations
    in the matrix ran `pytest -k order` against a guard whose name contains no "order",
    so they selected ZERO tests and printed nothing — which reads exactly like a pass.
    Same family as the recorded `cmd | tail` lesson: a check you expect to be
    interesting that says nothing interesting has usually not run. Assert the selector
    matches FIRST (`1 passed, N deselected`), then mutate.
  - **A SIGN-OFF NAMES A POPULATION; THE CODE PATH APPLIES A SET OF CRITERIA, AND THOSE
    ARE NOT THE SAME THING (2026-08-23, executing the row-5 clean-up):** the maintainer
    agreed *Tier A* — 8 articles, the URL-shape drop path. `POST /api/quarantine/start
    ?write=true` would have stamped those 8 **plus** every ≥100-word body the nav-soup
    PROSE GATE flags, because the write path applies three independent criteria and that
    one defaults ON while the manager never passed the flag at all. It is not a stricter
    reading of the URL rules — the URL rules fire only BELOW the ≥100-word guard and the
    prose gate only ABOVE it, so they are disjoint populations, and the second one's size
    was unmeasured *and unmeasurable* from the same report (its prose arm is the one pinned
    at `after_id=0, limit=500` that never advances). RULES. (a) Before executing an agreed
    scope, enumerate every criterion the code path applies and check each against what was
    agreed — an agreement about a COUNT is not an agreement about a PREDICATE, and the
    count is what gets quoted back. (b) The two-tier proposal was what made this findable:
    naming the blast radius up front is what turns "run the pass" into a checkable claim.
    (c) A criterion that changes WHICH rows are selected is run-lifetime MODE, not a call
    argument — `write` and `index_page_tiers` were already treated that way here, with the
    docstring citing the resume lesson, and the third dimension was simply missed; the same
    audit found `index_page_tiers` preserved by in-process `resume()` but NOT persisted, so
    an app restart silently NARROWED a tier run while a missing prose-gate flag would have
    WIDENED a Tier A one. Both file two different criteria under one run's name.
    **AND THE GUARD THAT WAS SUPPOSED TO CATCH THIS DIDN'T:** a parity test existed whose
    docstring promised "the next addition reddens HERE, by name" — and it compared against
    a HARDCODED `manager_passes = {...}` set, so it only ever recorded the additions someone
    remembered to add to it. It now derives the set by walking `_run`'s real `work(...)` call
    with `ast`. A guard that must be updated by hand to keep working is a guard that reports
    on the last person's memory. FIFTH mutation worth keeping: the endpoint silently dropping
    the operator's choice passed everything until a TestClient guard was added — and it had
    to be a TestClient, because a route called directly receives `Query(...)` sentinels,
    which are truthy, so a direct-call check would have passed on exactly that bug.
  - **FIXING A PROPERTY AT ONE OF ITS TWO CALL SITES IS NOT FIXING IT — and the second
    site was in the SAME function, four lines down (2026-08-23, the Windows restore
    failing a second time):** the first fix taught the swap that Windows will not UNLINK
    an open file: `_clear_stale_side_files` got a retry, `_file_is_locked` got a winerror
    check, `classify_restore_error` got a branch naming the remedy. It shipped, and the
    operator hit `[WinError 32]` again on the same `-wal`. The reason is that
    `os.replace(working, target)` is `MoveFileExW(..., MOVEFILE_REPLACE_EXISTING)`, which
    needs the DESTINATION to be closed for exactly the same reason unlink does — so the
    retry protected one of the two Windows operations in that block and the other was
    left bare. The ledger already carries this shape twice (`release_backend` reading
    `stopped` alone; the vLLM stop with two paths and the guarantee in one) and it
    recurred anyway, which says the tell is not "grep the module" but **"name the OS
    PROPERTY you are working around, then list every call in the block that depends on
    it"** — here: anything that unlinks, replaces or renames. THREE RIDERS. (a) One
    budget for the whole block, not one per call: two 20s retries read as 20s in the
    message and are 40s in the wall, so the deadline is computed once and each step gets
    what is left — and note that "one budget" is a claim about the INNER loop too: my
    own first cut computed the shared deadline at the CALL SITE and then handed each of
    `-wal`/`-shm` the full remainder, so the side-file step could spend 2x while the
    replace — the step that matters — was left with `max(0, ...)` = ZERO. **THE GUARD I
    WROTE FOR IT WAS VACUOUS TWICE.** The `ast` version asserted the call-site shape
    (`wait_s` passed, the deadline assigned once) and says nothing about what the callee
    does with it. The behavioural replacement locked BOTH files permanently — and that
    does not discriminate either, because the first file raises at its deadline and the
    second is never reached, so per-file and shared spend the same. The scenario has to
    RELEASE the first file partway, so the loop actually reaches the second and a fresh
    window shows up on the clock (measured: 1.50s against a 1.0s budget). General form:
    for a guard about a BUDGET SHARED ACROSS STEPS, the fixture must reach every step —
    a fixture that fails at step one tests the step, never the sharing. (b) A retry whose
    holder is OUR OWN pool must DO something between
    attempts — `engine.dispose()` closes only IDLE connections, so a re-dispose every few
    attempts is what converts waiting into progress; waiting alone is how a 20s budget
    expires against a handle that was never going to be released by time. (c) When the
    budget expires the message must say WHAT IT WAITED and, where it can, WHO held it:
    "close any other window" is unactionable advice if the operator has none open, and it
    is the sentence that sends a real bug back as user error.
  - **AN ERROR THAT NAMES THE FILE AND NEVER THE HOLDER IS A DIAGNOSTIC DEAD END — build
    the probe out of the SAME primitive the failing operation needs (2026-08-23, the
    Windows lock report):** two rounds of fixes produced no way to tell a bug in this app
    from a program the operator could simply close, because `[WinError 32]` names the
    path and nothing else. The answer is not to parse the error harder: Windows will hand
    you the fact directly if you ask for the same EXCLUSIVITY the swap needs —
    `CreateFileW(GENERIC_READ, dwShareMode=0, OPEN_EXISTING)` succeeds only when no other
    handle exists, and closing it immediately changes nothing. A probe built from the
    operation's own precondition cannot drift from it the way a heuristic would.
    **THE CTYPES TRAP THAT WOULD HAVE INVERTED THE WHOLE FINDING:** `INVALID_HANDLE_VALUE`
    is `(HANDLE)-1`, and a function declared `restype = wintypes.HANDLE` (a `c_void_p`)
    returns the UNSIGNED form — `18446744073709551615` on 64-bit — so `handle == -1` is
    **False on every failed call**, and a REFUSED open would have been reported as a
    success on precisely the case the module exists to detect. Compare against
    `ctypes.c_void_p(-1).value`, and note the sibling: `ctypes.get_last_error()` returns 0
    unless the library was opened `WinDLL(..., use_last_error=True)`, so a naive read can
    report a different call's error under this one's name. TWO HONESTY RULES the report
    needed. (a) NOT-MEASURED is a third state: reading a probe that did not run as "free"
    via `.get("exclusive_open", True)` prints an all-clear for an unanswered question —
    the `.get(key, 0)` family again, and here it would tell an operator to retry a restore
    that is still doomed. (b) An empty holder list is only a finding when the sweep was
    COMPLETE: enumerating another process's handles needs privileges this app does not
    ask for, so refused and unreached processes are counted and published, because
    "not visible" and "not there" are opposite answers. And the exclusion-path check is
    the recorded containment trap in a new place — `…\Open-Omniscience-old` starts with
    `…\Open-Omniscience`, and reporting that as excluded tells an operator they already
    applied a remedy they did not.
  - **A MUTATION THAT DOES NOT APPLY IS INDISTINGUISHABLE FROM A GUARD THAT DOES NOT
    BITE — assert the edit landed before reading the run (2026-09-02, the S1.3 locale
    mutation):** the mutation matrix's whole value is that a green run after a mutation
    is a FINDING. That inverts the moment the mutation silently fails to apply: a
    `str.replace` whose needle is absent is a no-op, the suite passes, and the result
    reads exactly like "this guard is vacuous". Here the French translation uses
    NON-BREAKING spaces (`{available}\xa0Mo`, correct typography that `json.dumps`
    preserved), so a plain-space search matched nothing and a perfectly good guard was
    about to be recorded as dead. RULE: every mutation asserts its own application
    (`assert new != old, "MUTATION DID NOT APPLY"`) before the test run, and where the
    edit is a value in a data file, take the needle FROM the parsed file rather than
    retyping it. Same family as the recorded `pytest -k` selector matching zero tests
    and the `cmd | tail` exit-code trap: a check that reports success without having run
    is the most expensive kind, and here it would have cost a real guard.
  - **A GUARD THAT PROVES THE SAFETY HALF AND NOT THE ACTION PASSES WITH THE ACTION
    DELETED (2026-09-02, the pool-dispose step):** `test_disposing_the_pool_closes_idle_
    connections_only` asserted that a checked-out connection SURVIVES — the property the
    step could most plausibly get wrong — and `ok is True`. Deleting `pool.dispose()`
    left both true, so the release ladder's largest step could have shipped as a no-op
    reporting success. The mirror case in the same file: `_shrink_sqlite` had a
    beautifully measured PREMISE test (a raw connection proving `shrink_memory` is what
    frees a warm page cache) and nothing asserting the SHIPPED function issues the
    PRAGMA, so replacing it with `pass` kept `ok: True` and every test green. GENERAL
    FORM: a step with a safety property and an effect needs an assertion for EACH, and a
    measurement of the MECHANISM is not a test of the CODE — drive the production
    function with a recording double and assert the statement reached it. Note the
    fixture order matters for the action half: a checkout REUSES an idle connection, so
    a test that takes its held connection after seeding the idle ones silently consumes
    one of them and the count it asserts is wrong.
  - **A NEW LOCAL THAT SHADOWS AN EXISTING ONE IN A LONG FUNCTION IS A REAL BUG THE TYPE
    GATE CATCHES AND REVIEW DOES NOT (2026-09-02, S1.3's `_floor`):** the fan-out cap
    bound `_floor` to the floor VERDICT (a dict) 130 lines above an existing `_floor`
    holding the mem-low permit floor (an int). Python rebinds happily; mypy rejected it
    by name. In a 200-line function the two uses are never on screen together, so the
    only thing standing between this and a later edit reading the wrong one is the type
    gate — which is the argument for running it rather than only the tests after an edit
    that "only" adds a variable. Rename with the reason in a comment, so the next reader
    does not tidy the distinction away.
  - **A COST YOU ARE ABOUT TO PUT ON A POLLED ENDPOINT IS ONE `timeit` AWAY — measure it
    instead of caching defensively (2026-09-02, the floor verdict on `/status`):** the
    memory-floor caveat has to ride every scheduler response for the same reason `online`
    does — a caveat behind a second poll the UI might never make is not visible by
    default. The reflex is a TTL cache, and it is the wrong instinct here twice over: the
    call is one `/proc/meminfo` read (measured at **107 µs**), and a STALE available
    reading is precisely the wrong thing on a machine whose memory is moving. Measuring
    took less time than writing the cache would have.
  - **A MEASUREMENT WHOSE INSTRUMENT IS PROCESS RSS IS ONLY VALID IN A PROCESS SMALL
    ENOUGH TO SEE IT — run it in a subprocess (2026-09-02, the shrink_memory premise
    test):** the release ladder rests on a measurement (a warm 64 MiB page cache is
    handed back by `PRAGMA shrink_memory` and NOT by ending the transaction), and
    re-running it as a test is right. Reading it through `/proc/self/status` is not: the
    test passed alone and failed in the full suite, where the interpreter already holds
    ~1.5 GB across the allocator's arenas and a 64 MiB free is invisible — so the failure
    read as "shrink_memory does nothing", the exact opposite of the truth. This is the
    recorded `ru_maxrss`-is-vacuous lesson with the sign flipped: there a
    high-water-mark instrument could not fail, here a whole-process instrument could not
    succeed. `tracemalloc` is no help either, because the allocation is SQLite's, in C.
    The fix is to measure where the docstring's own numbers were taken — a fresh
    interpreter — and to add the anti-vacuity assertion that the probe genuinely warmed
    a cache first, or a probe that allocated nothing would "prove" the same thing.
  - **PREFER BEING STOPPED BY THE SLICING RATCHET OVER LOWERING ITS BUDGET — and it
    fires on TESTS, which is where new hand-rolled slices are written (2026-09-02):**
    a new test file sliced `app-sources.js` with `src.index("function renderMachineFloor(")`
    and a hand-guessed `"\n    }\n"` terminator, and `test_adhoc_slicers_do_not_multiply`
    caught it at 233 against a budget of 232. Routing it through
    `js_source_helper.function_body` + `strip_comments` restored the budget WITHOUT
    lowering it, and the mutation matrix was re-run afterwards to confirm the re-sliced
    guard still discriminates — a refactor of a guard is not finished until its mutation
    reddens again. The ratchet's twin (`test_the_budget_is_not_left_above_the_real_count`)
    means the number cannot be quietly raised either: it fails if the budget sits above
    the real count, so the only ways out are to fix the slice or to argue the budget up
    deliberately.
  - **A BELT ADDED FOR SAFETY CAN MAKE THE THING IT BACKS UP UNTESTABLE — the second
    guard masks the first (2026-09-02, the `statement_deadline` pool poison):** the fix
    is four edits, and edit 4 (an owner-thread check, so an escaped handler can only
    interrupt the thread that armed it) is a deliberate belt under edit 1 (disarm on
    checkin). Together they are right; together they also mean the CROSS-THREAD test —
    the one that reproduces the field defect — passes with edit 1 **neutered**, because
    the belt makes a stale handler inert on a foreign thread anyway. Neutering the
    listener reddened nothing. The discriminating case is SAME-thread: a connection
    returned to the pool mid-deadline and checked out again by the same thread, where
    the belt is silent and only the listener can save it. GENERAL FORM: when a fix has a
    primary mechanism and a belt, ask which one each test is actually exercising — a
    belt that covers the primary path everywhere leaves the primary untested, and the
    mutation matrix is the only thing that says so.
  - **A TEST THAT ATTACHES THE PRODUCTION LISTENER TO ITS OWN ENGINE PROVES THE FUNCTION
    AND NOT THE WIRING (2026-09-02, same slice):** the fixture did
    `event.listen(eng, "reset", _disarm_progress_handler)` — right for exercising the
    real function on an isolated engine, and it means removing
    `@event.listens_for(engine, "reset")` from `session.py` reddens NOTHING. That is the
    recorded "a test double injected via a parameter bypasses the production path" trap
    wearing a fixture's clothes, and the fix is one assertion:
    `event.contains(engine, "reset", fn)` against the app's own engine.
  - **A "TWO SESSIONS MUST NOT INTERFERE" TEST NEEDS THEM TO SHARE THE RESOURCE, WHICH
    A ROOMY POOL PREVENTS (2026-09-02, same slice):** the foreign-disarm test ran on
    `pool_size=2`, so the two blocks never touched the same connection and restoring the
    old historical-list disarm changed nothing. `pool_size=1` FORCES the shape the hazard
    needs — X arms C and commits, Y picks C up and arms it on its own clock, X's block
    exits — and the mutation then fails by name. Same family as the anti-vacuity rule
    already recorded for the cross-thread case (with a larger pool the other thread gets
    a fresh connection and passes for free): for any interference test, assert or force
    that the two parties really share the thing.
  - **A NESTED-STATE TEST MUST PUT THE INTERESTING VALUE ON THE OUTER LEVEL, OR
    "RESTORED" AND "ERASED" READ THE SAME (2026-09-02, the deadline expiry):** the
    expiry is stashed in `session.info` and restored on exit so nesting works. Tested
    with a LONG outer and a SHORT inner, the post-exit assertion is
    `deadline_expired() is False` — which is equally true if the key was restored and if
    it was deleted outright, so replacing the restore with an unconditional `pop` passed.
    Making the OUTER the expired one turns the same assertion into a discriminating
    `True`. GENERAL FORM: for any save/restore, arrange the fixture so the restored value
    and the absent value produce DIFFERENT answers.
  - **A MUTEX WITH NO TIMEOUT IS A HANG WITH A GOOD REASON, AND THE WORK BELOW IT IS WHAT
    DISAPPEARS (2026-09-03, S2.5):** `WriterGate.acquire()` waited on a `Condition` with no
    bound, which is *correct* for a writer — a write that waits is right, a write that
    proceeds ungated is the data-loss bug the gate exists to prevent. It is wrong for the
    pass tail's WAL checkpoint, which takes the gate on the way past, and `record_run` sits
    BELOW it: so a long writer did not merely delay the checkpoint, it deleted the run
    record, and a stalled pass left no account of itself at all. THE RULE: when adding a
    bound to a shared primitive, ask what each caller does when it gives up — a caller that
    would proceed anyway must not get the bound (the default here stays unbounded, and the
    negative twin pins that), and a caller that can honestly SKIP gets it. THE SKIP IS ITS
    OWN OUTCOME: `checkpoint_wal` already returned `None` for "disabled / not due", so
    folding a gate-busy skip into `None` would have made "could not run" and "was never
    asked to run" indistinguishable in the run report — the recorded one-key-two-meanings
    defect, in a return value. RIDER that cost a rewrite: `except WriteGateBusy` is
    *evaluated* when an exception propagates, so binding that name with an import INSIDE the
    `try` turns any earlier failure into a `NameError` from the handler; the exception class
    has to be imported at module level even when the function it guards imports lazily.

  - **A PRESCRIBED REMEDY CAN BE A REVERT OF A RECORDED FIX — read the module's own
    docstring before implementing the plan item that names it (2026-09-03, S3.5):** the
    brief's first remedy for the rollup's per-batch full scan was "re-key the batch loop on
    the integer PK". `columnar.py`'s own docstring records why that key was ABANDONED:
    `KeywordMention.id` carries no `AUTOINCREMENT`, so a DELETEd rowid can be reused, and
    with `index_article`'s delete-then-bulk-insert idiom a rowid keyset was LIVE-REPRODUCED
    both double-counting and silently dropping rows (the PR-D / W2 correction). Bounding
    `id <= MAX(id)` closes the append direction and NOT the reuse one: a re-index that frees
    the top rowids and reinserts there lands at ids inside the bound, behind an advanced
    cursor. The plan's PERFORMANCE claim was exact and only its remedy was unsafe, which is
    the distinction worth carrying — verify the measurement, then check the fix against what
    the code already knows. GENERAL FORM: a plan written from measurements is trustworthy
    about the defect and not automatically about the repair, and the docstring beside the
    line you are about to change is where the previous repair's reasoning lives.
  - **AN EXPRESSION OVER AN INDEXED COLUMN MAKES THE INDEX UNREACHABLE, SO ADDING THE INDEX
    PROVES NOTHING — remove the expression (2026-09-03, S3.5):** the rollup's keyset was
    `WHERE COALESCE(created_at, :epoch) <= :bound AND (COALESCE(...) > :cursor OR ...)
    ORDER BY COALESCE(...), id`, and EXPLAIN over the statements the REAL build emits (a
    listener, not a hand-written lookalike — the recorded probe-is-a-lookalike lesson) said
    `SCAN keyword_mentions` **plus** `USE TEMP B-TREE FOR ORDER BY` per 50k batch, i.e. it
    sorted its whole match set every batch. Measured: adding `(created_at, id)` left that
    plan **byte-identical**, because an expression is not indexable. The fix is to make the
    predicate a plain range, which here means streaming the NULL rows as their own phase —
    and NOT an expression index, because alembic's autogenerate cannot compare those and one
    would leave permanent spurious drift plus an `alembic_stamp_align` schema-behind verdict
    (the recorded 2026-08-20 NOCASE case). Splitting a scan on nullability has its own
    correctness question: a rowid keyset is safe on the NULL phase *only* because nothing
    can ADD a row to it mid-scan, which is a claim about every insert path and was verified
    against both real idioms (a plain ORM `add` and the bulk `insert(Model), [rows]`) plus
    the absence of any raw `INSERT INTO` in `src/` — not assumed from the column default.
  - **A `busy_timeout` IS THE HOLD: against a pinned WAL the whole cost of
    `wal_checkpoint(TRUNCATE)` is the busy handler, and the pinned verdict is free
    (2026-09-03, S4.1):** measured on the real PRAGMAs with a reader holding an unexhausted
    cursor (4.1 MB WAL, 423 frames) — `TRUNCATE` at `busy_timeout=5000` cost **5012 ms**,
    returned `busy=1` and moved nothing; `PASSIVE` cost **0.0 ms** and backfilled 423/423;
    `TRUNCATE` at `busy_timeout=0` cost **0.0 ms** and returned the same `busy=1`; with the
    reader closed, `TRUNCATE` took 0.8 ms and left the WAL at 0. So waiting bought no
    information a later boundary would not get, while guaranteeing a multi-second hold of
    the write gate at every pass boundary. PASSIVE is what actually bounds growth while
    pinned (it backfills to the oldest reader mark; only the FILE reset needs the reader
    gone). **THE PLAN'S OWN GATE IS REFUTED AND PINNED AS REFUTED:** attempting TRUNCATE
    only when `log_frames == checkpointed_frames` after the passive step does NOT mean
    "nothing is pinned" — a reader whose snapshot sits at the current END of the WAL
    satisfies it exactly (423 == 423) while still pinning the file — and adopting it also
    breaks the UNPINNED path, since with no reader the frames also match and the TRUNCATE
    would be skipped, leaving the file unreclaimed. There is nothing to predict: not
    waiting is the fix.
  - **`fetchall()` OVER A `LIMIT` ALREADY COMPLETES THE STATEMENT, so an explicit
    `close()` there is belt and not the mechanism (2026-09-03, S4.2, caught by a mutation
    that SURVIVED):** the registry's close-never-merely-commit finding is about
    `fetchmany()` on a **partially drained** Result, where an un-reset prepared statement
    pins the read snapshot independently of BEGIN/COMMIT. I copied that comment onto a
    batch loop that fully drains each bounded query with `fetchall()`, and the mutation
    removing the `close()` reddened nothing — correctly, because the statement had already
    reached natural completion. A claim in a comment that the code does not depend on is a
    fabricated mechanism inside an honesty fix; state which of the two shapes you have.
  - **A FIXTURE WHOSE ENTITIES CARRY SLACK CANNOT SEE A LOST ROW (2026-09-03, S4.2):** a
    keyset mutation advancing the cursor one row too far (skipping a row per chunk) passed
    a chunk-size-agreement test twice. With one keyword and a lopsided majority, no output
    field moves; with 24 keywords at THREE mentions each, losing one still left every
    keyword above the floor and the tally unchanged. Only ONE mention per keyword makes a
    keyword's presence in the tally depend on a single row, and then the mutation fails
    immediately. GENERAL FORM: for a guard that a scan lost nothing, build the fixture so
    each counted entity depends on exactly one row — any redundancy per entity is slack the
    mutation hides in, and this is the same "a probe's data distribution is part of the
    lookalike" trap with REDUNDANCY as the varying axis. Corollary from the same matrix: a
    test of a HELPER is not a test of its WIRING — every assertion called `_wal_gauges()`
    directly and deleting its use from the sample dict reddened none of them, which is the
    recorded unguarded-wiring defect recurring one subsystem over.
  - **A TEST CAN BE POISONED BY ITS OWN BACKGROUND THREAD, AND PASS ALONE ONLY BECAUSE THAT
    THREAD DIES — remove the kick, never out-wait it (2026-09-03, the persisted-serve
    race):** `test_persisted_serve_matches_live_and_discloses_the_store` took its live
    baseline by calling `top_terms` with the rollup serve ON and `_STATE["con"]` None,
    which is precisely the condition `windowed_rows` answers with
    `_trigger_build_async()`. So the test raced a daemon in-memory build against its own
    four statements, and that build's swap sets `persisted=False`: landing before the
    test's `_STATE.update` is harmless, landing between the serve and the `basis()`
    composition is a red `assert 'memory' == 'persisted'`. **It was green for years
    because in ISOLATION the racing build reads the PROCESS store via `session_scope()`,
    and in a single-file run that store is unmigrated — it raises `no such table:
    keyword_mentions` before it can reach the swap.** A full suite migrates the store, the
    build completes, and the landing point is then decided by how long the build takes —
    which two extra round trips in an unrelated rollup change were enough to move. THREE
    GENERAL POINTS. (a) A test that passes alone and fails in a full run is not
    automatically pollution FROM another test: it can be its OWN worker, which only becomes
    capable of finishing once the shared fixtures other files set up exist — so ask what the
    thread READS, not only what the tests write. This is the mirror of the recorded
    "a test that starts a real worker and never joins it poisons the whole pytest process":
    there the victim is elsewhere, here it is the test itself. (b) Prefer removing the kick
    to draining it — taking the baseline with the serve explicitly OFF makes the race
    impossible by construction, and the `kicked == []` assertion then reddens
    DETERMINISTICALLY when the guard is removed, where an out-wait reddens only by luck.
    (c) Prove the two halves SEPARATELY and synchronously before touching either side (the
    serve kicks a build; the swap flips an installed state), or "I made the test
    deterministic" is indistinguishable from "I relaxed an assertion I had not understood" —
    and ship both halves as named guards, so the next reader can check the reason rather
    than re-derive it.
  - **A GUARD WRITTEN FOR THE DEFECT IS NOT A GUARD ON THE CODE — a mutation matrix over my
    OWN new tests found SEVEN gaps, and every one of them was a test that could not see the
    branch the shipped code takes (2026-09-03, S5.1/S5.2):** twenty-two mutations, seven
    survivors, all against tests written in the same hour as the fix. The shape recurs, so
    it is worth naming rather than listing: each guard was aimed at the CASE THE FIX WAS
    ABOUT and not at the CASE THE FUNCTION EXECUTES. (a) **A verdict-parity test cannot see
    a scoping change.** Deleting the `source_id IN` filter — the whole point of S5.1 —
    changed NO verdict: the extra sources land in `per`, the caller only ever reads
    `s.id in per`, and the baseline is the FROZEN cut either way, so every status and every
    reason stayed identical while the per-batch read went back to walking the corpus. A
    slice whose win is COST needs a guard on cost or shape; parity is blind to it by
    construction. (b) **A cross-source statistic needs a fixture that crosses sources.** The
    furniture ubiquity cut is `max(5, 0.3·n_sources)`, and the cohort fixture gives every
    source its own unique terms, so no document frequency ever reaches the cut, every share
    is 0.0, and the assertion `alone == together == frozen` held as `0.0 == 0.0 == 0.0` —
    passing for a reason unrelated to its claim. (c) **"consulted at least twice" is
    satisfied by one loop ticking twice**: count EXACTLY, and give the two loops DIFFERENT
    row counts (quarantine one article; the mention GROUP BY has no quarantine filter) so
    the total names which half went missing. (d) **One function, two branches, two guards** —
    the scoped path chunks its mention aggregate and the unscoped path does not, so a test
    driving one leaves the other's pause check unexercised. (e) **When two scans can both
    pause, the first one always wins**, so `should_pause=lambda: True` only ever exercises
    the freeze; supplying a frozen cohort is what moves the pause to the scoped read the
    gate actually runs per batch. (f) **A negative twin at production granularity over a
    tiny fixture proves nothing**: the check fires every 5,000 rows and the fixture walks
    76, so "a callback answering False completes the scan" was true whatever the code did —
    it needs the compressed threshold AND an assertion that the callback was consulted at
    all. (g) The `ValueError` refusing a cohort frozen at the wrong `min_articles` — added
    in the same slice precisely because the failure is invisible — had **no test whatsoever**.
    GENERAL FORM, and the cheap way to get it right the first time: for each new guard, name
    the branch it executes and ask what ELSE in the function could satisfy the assertion;
    then run the mutation before believing the answer. A mutation that reddens nothing is a
    finding about the test, and here it was the finding seven times out of twenty-four.
    **AND AN EIGHTH GAP THE MATRIX COULD NOT SEE, because it was in the SHIPPED code rather
    than the tests:** the memory guard was wired into the bulk job's scan and NOT into the
    per-pass ride-along, which calls the same whole-corpus freeze from the scheduler's
    housekeeping lane. That is "gate EVERY entry point" recurring for the Nth time, and the
    tell is the same every time — the fix was written while reading ONE caller. Before
    declaring an interruption, a hold or a pause wired, grep for every caller of the thing
    being guarded, not for the caller you happened to open.
  - **THE FOURTH RECURRENCE OF "GATE EVERY ENTRY POINT" HID IN THE PATHS KICKED BY A
    REQUEST — and the primitive the brief named would have shipped a worse bug than the
    one it fixed (2026-09-03, the all-diagnostics bundle's exclusive hold):** the bundle
    runs for tens of minutes and competed with a collection pass the whole time, so it
    takes the exclusive hold. Enumerating who else must respect that hold, the answer
    looked complete — `run_now` checks it, the re-index job checks it, the continuous
    loop is paused by the window. The two that did not check are the two ROLLUP BUILDS,
    and the reason they were absent from the enumeration is structural: they are kicked
    from a SERVE, i.e. by any HTTP read that happens to find the change gate open, so
    they never appear in a list of "background work" — nothing schedules them. A
    whole-corpus columnar rebuild is the heaviest thing this process does outside a pass.
    GENERAL FORM: when listing what competes for a machine, the request-kicked paths are
    the ones missing, because they do not look like background work; grep for what STARTS
    a thread, not for what is scheduled.
    **THE SECOND HALF IS SHARPER, AND IT WAS THE BRIEF'S OWN INSTRUCTION:** the slice was
    specified as "acquires the existing exclusive hold (`runner.hold_exclusive()`)", and
    doing exactly that would have been a defect. `_exclusive_hold` is a **BOOLEAN**, so a
    bundle started during a restore would clear the RESTORE's claim on its own release and
    put a manual "Run now" back on the machine mid-restore — reinstating precisely the
    concurrency defect the 2026-07-24 lesson records, from inside the fix for it. The
    codebase already had the answer: `exclusive_window()` is the RE-ENTRANT, imbalance-proof
    wrapper whose own docstring says it "restores the flag to what it FOUND", and it exists
    because this was learned once already. RULE: before calling a hold/release pair
    directly, read whether the flag is a boolean or an owned/counted one — a boolean pair
    is safe only for a single outermost owner, and a nested caller must use the wrapper.
    The test that pins it enters an OUTER window first and asserts the outer claim survives
    the inner block's exit; without the outer window every mutation passes.
    **THIRD, on the payload:** a hold whose pause is bounded and best-effort must not
    publish `exclusive: true`. `paused_collection` is the pause's OWN return value (was the
    loop running and did it get signalled), `nested` says an outer operation already owned
    the machine, and a caller that took no hold gets `held: false` with a reason — three
    facts instead of one claim the mechanism cannot support.
  - **A HIGH-WATER INSTRUMENT USED AS A PER-ITEM DELTA PUBLISHES A FABRICATED ZERO FOR
    EVERY ITEM AFTER THE LARGEST — and the first item's number looks right, which is what
    carries it past review (2026-09-03, the bundle's `rss_delta_kb`):** `ru_maxrss` never
    falls, so once the process peak is set, a member that really allocated 40 MB reports a
    delta of 0. The recorded 2026-08-06 lesson names this for a TEST that could not fail;
    the costlier form is a SHIPPED PAYLOAD, where ~58 of 59 members published 0 under a
    field named for their memory cost, and 0 reads as "this member allocated nothing"
    rather than as "we could not tell". Every field bundle collected since carries it.
    THREE THINGS THE FIX NEEDED. (a) The discriminating test FIXES a high peak and asserts
    the delta still moves — a test that merely checks the key exists, or that it is
    non-negative, passes against the defect. (b) The high-water rise is still worth
    publishing and must keep its OWN name: "did this member allocate 40 MB" and "did it
    push the process past its all-time peak" are different questions, and only one of them
    is answerable after the first big member. (c) An unreadable instrument OMITS the field
    and NAMES itself (`rss_basis`), because a `(after or 0) - (before or 0)` is the same
    fabricated zero by another route. RIDER, on reuse: the instruction "reuse it, don't
    write a second one" is testable BEHAVIOURALLY — monkeypatch the function that must be
    reused and assert the caller reflects it, so an inlined second copy fails where a
    source grep for the import would pass.
  - **A LOCK THAT GRANTS TO WHOEVER FINDS IT FREE MAKES ITS OWN WAIT COUNTER MEANINGLESS
    (2026-09-03, S2.6c):** the gate's `max_wait_s` was the field's headline number — 6,236
    seconds — and it could not be read as a long write, because `acquire()` had a fast path
    that took a free gate without queueing. A thread looping acquire/release re-takes it the
    instant it releases, while the waiter it just notified is still being scheduled, so the
    figure measures STARVATION and a hold indistinguishably. FIFO tickets fix the number as
    much as the fairness. TWO THINGS THE FIX TURNS ON: `notify()` becomes `notify_all()`,
    because under FIFO the one thread `notify()` wakes may not be the queue head, and it
    goes straight back to sleep while the head is never woken — a lost wakeup that a
    fairness change introduces rather than removes; and a timed-out waiter must REMOVE
    itself and wake whoever is now the head, or the abandoned entry sits at the head forever
    and blocks every later acquire (which also means `_reset_for_tests` must clear the queue,
    not just the owner). **AND THE OBVIOUS WAY TO SOLVE THE FIRST IS A 5.3x THROUGHPUT
    REGRESSION, which only a measurement finds:** one shared condition plus `notify_all()` is
    correct, reads as the textbook fix, and at 50 workers x 200 us holds took **2543 ms
    against the old 482 ms**, because every release woke all 49 waiters so that one could
    proceed — a thundering herd on the very collector throughput the field report is
    complaining about. Give each waiter its OWN `Condition` over the SHARED lock and wake the
    head alone: one wakeup per handoff, what the pre-FIFO `notify()` cost. Then state what
    fairness itself costs rather than implying it is free — 473 -> 550 ms wall (+16%) while
    the worst wait falls 458 -> 14.6 ms (31x), within noise when uncontended. GENERAL FORM:
    a fairness fix on a contended primitive changes a HOT PATH, so benchmark it against the
    algorithm it replaces before shipping; and when the honest version is slower, the
    question is whether the fix can be made cheaper, not whether the regression is
    acceptable. TESTING NOTE, and the reason the guard is trustworthy: a thread race cannot
    deterministically discriminate FIFO from the old `notify()`-based "FIFO-ish" order.
    The load-bearing half is the fast path's REFUSAL, and that is testable directly — queue
    a ticket, leave the gate FREE, assert a fresh acquire is not granted — which reddens
    exactly when the `and not self._queue` guard is removed.

  - **AN INSTRUMENT THAT KEEPS NAMING A THREAD AFTER IT LET GO ACCUSES THE INNOCENT
    (2026-09-03, S2.6b):** the write gate can name whoever is inside the WRITE window, and
    can never name the thread that actually pins the WAL — a long-lived READ transaction
    stops `wal_checkpoint(TRUNCATE)` reclaiming anything with the gate free the whole time,
    which is the shape the field's three-hour WAL growth had. A checkout/checkin pair names
    it, and the load-bearing property is the CHECKIN: an instrument that recorded checkouts
    and never forgot them would name whichever thread ran last on every reading, so it would
    be worse than no instrument. Its negative twin ("a returned connection is NOT listed") is
    therefore the test that matters, and the empty case has to be stated in the payload —
    "nothing is checked out at this instant" is not "nothing ever was". RIDER: a
    process-global register attached to the real app engine is order-dependent test
    pollution by construction, so it joins conftest's autouse reset list — clearing the
    RECORD and never the listeners, since detaching them would leave every later test
    measuring an instrument that is not running.

  - **TWO THINGS THAT EACH REFUSE TO OVERLAP THEMSELVES ARE NOT THEREBY SERIALISED — and
    SKIPPING on contention starves whichever one is kicked second (2026-09-03, S2.5b):** the
    housekeeping lane and the whole-corpus briefing recompute each had a non-overlapping
    lock, each documented as "occasionally skipped, never stacked", and nothing stopped both
    running at once on the two-core box the field report describes. The obvious fix — a
    shared lock taken with `blocking=False` — reads like the existing posture and is worse
    than the bug: the lane is always kicked FIRST in the tail, so the briefing refresh would
    have found the lock held on essentially every pass and a permanently stale Home would
    have replaced a slow one. It WAITS instead, bounded, and the bound is what keeps a wedged
    consumer from pinning the other's thread forever. GENERAL FORM: when serialising two
    background consumers, look at the ORDER they are kicked in before choosing skip-vs-wait —
    skip is only fair when arrival order is fair, and a fixed kick order makes it a permanent
    verdict against the later one.
  - **A DOCSTRING SAYING "NOT AT IMPORT" IS NOT A GUARANTEE — CHECK WHETHER THE
    FUNCTION IT NAMES IS ITSELF CALLED AT IMPORT (2026-09-03, the write-gate
    watchdog):** `start_write_gate_watchdog()` was called from
    `register_write_gate()`, and BOTH its docstring and the comment at the call
    site said, in almost those words, that this was "the production wiring,
    never at import, so a test that imports this module gets no thread". The
    property was false the moment it was written: `session.py` calls
    `register_write_gate(SessionLocal)` inside a module-level `if _IS_SQLITE:`,
    so merely `import src.database.models` spawned a monitoring thread. I wrote
    the correct rule down twice and then satisfied neither. GENERAL FORM: when a
    comment asserts "X does not happen at import", the check is not to re-read
    the comment but to grep for the CALLERS of the function it points at and ask
    what scope each of them runs in — a function is only as lazy as its most
    eager caller. THE GUARD THAT CAUGHT IT was `test_import_has_no_side_effects`,
    which asserts the property BEHAVIOURALLY in a subprocess (`n0 ==
    threading.active_count()` after importing the models) rather than by reading
    the source — the only shape that could have caught this, since every source
    grep for the honest string finds it. THREE RIDERS. (a) The trigger has to be
    the point where the watched thing can first EXIST: `watchdog_tick` reads the
    gate's holder and nothing else, and a hold cannot exist before an acquire, so
    arming on the first `acquire()` loses no coverage while a migration, a CLI or
    a test that only imports pays for no thread. (b) A "have we decided yet" flag
    is NOT the same as a "did we start" flag: `_WATCHDOG_STARTED` stays False
    forever when the watchdog is disabled, so keying the hot path on it re-reads
    the environment and re-takes a lock on every single write — the disabled case
    needs its own one-shot flag, and the mutation that swaps them reddens only a
    test written for that case. (c) **THE PRE-EXISTING TEST FOR THIS WAS PASSING
    VACUOUSLY**: `test_the_watchdog_is_started_by_the_production_wiring` asserted
    `_WATCHDOG_STARTED is True` after importing the session module, and passed
    because an EARLIER test in the same file had already taken the gate and armed
    it — so it held whatever the wiring did. It was re-anchored (deliberately,
    per the guard-that-anticipates-its-own-supersession rule) onto the real
    property in a subprocess: no thread on import, a thread after a real ORM
    write. Anything process-global ("has it started yet", "was this registered")
    is unprovable in-process once any sibling test can arm it.
  - **A `pgrep -f` / `pkill -f` PATTERN MATCHES THE WRAPPER RUNNING IT — twice in
    one session, in two different disguises (2026-09-03):** the recorded 2026-08-08
    lesson names `pgrep -f` in a wait loop; both recurrences here evaded it because
    neither looked like that example. (a) `until ! pgrep -f "[p]ytest -q --continue"`
    — the `[p]` bracket trick that defeats a self-match in `ps | grep` does NOTHING
    for `pgrep -f`, because the pattern is a REGEX matched against every command
    line INCLUDING the waiting shell's own, which contains the literal
    `pytest -q --continue-on-collection-errors` from the command it is about to
    run. The loop waited on itself forever, and a wait that never returns is
    indistinguishable from work that never finishes. (b) `pkill -f "python -m
    pytest"` killed the very shell that issued it (exit 144). RULE: never match a
    process by a string your own command line contains — match on an absolute
    argv[0] (`ps -eo args | grep "^/abs/path/.venv/bin/python -m pytest"`), or
    record the PID when you START the process and wait on that. And prefer the
    harness's own job control (a background task id) to any pattern at all.
    **RECURRED THREE TIMES IN ONE SESSION, 2026-09-05, BY AN AGENT THAT HAD READ THIS
    ENTRY — so the remedy above is stated too weakly to be reached under time pressure,
    and its last sentence has its own trap.** (a) `until ! pgrep -f "pytest tests/ -q"`
    as a background waiter: the waiter's own `bash -c` line contains the pattern, so the
    loop never exited and a 16-minute suite read as "still running" long after it had
    printed its summary. (b) `pkill -f "\.venv/bin/python -m pytest tests/ -q"` — escaping
    the dot does not help, because the problem was never the regex, it is WHICH command
    lines it is matched against; it killed its own shell (exit 144). (c) **The recommended
    fix then failed in a new way: `nohup bash -c 'until …; done' &` INSIDE a
    `run_in_background` task.** The harness reported that task "completed (exit code 0)"
    within seconds — truthfully, because what completed was the LAUNCHER; the detached
    loop was still waiting, with its stdout on `/dev/null`, so no notification could ever
    arrive. A completion notice describes the process the harness is watching, so
    backgrounding your wait INSIDE a backgrounded task hands you a confident "done" about
    something you did not ask about. Let the wait BE the task's command
    (`while kill -0 <pid> 2>/dev/null; do sleep 15; done`) and never `&` inside it.
    ORDER OF PREFERENCE, then: capture `$!` when you launch and poll or wait on that PID;
    hand the harness the waiting loop itself; or, if you must match, filter on a field the
    matcher's own line cannot occupy (`ps -eo pid,args | awk '$2 ~ /python/ && /pytest/'`
    reads argv[0] rather than the whole line). Do NOT reach for `-f` with a substring of
    the command you are about to run — that is the whole class, and it is not made safe by
    bracket tricks, escaping, or a more specific pattern.

  - **AN INSTRUMENT THAT FORKS CAN DESTROY THE EFFECT IT IS MEASURING — and the
    obvious portable substitute for `/proc` does exactly that (2026-09-03, the
    macOS portability lane on the shrink_memory measurement):** the probe behind
    the S1.2 release ladder read `/proc/self/status`, which does not exist on
    macOS, so the test died there with `CalledProcessError` — a real portability
    defect in a claim (about SQLite) that is not Linux-specific. The obvious
    dependency-free fix is `ps -o rss=`, which reports CURRENT resident size on
    both platforms and looks perfect. It is wrong, and only a repeated run says
    so: five runs of each candidate on the identical workload gave
    **`/proc` 31.9 MB freed 5/5 · psutil (one Process object, hoisted) 31.9 MB
    5/5 · `ps -o rss=` −0.1 MB 5/5**. Reading RSS by FORKING prevents the
    allocator returning the pages, so the instrument erases the release it was
    added to observe — and shipping it would have made macOS report
    "shrink_memory freed nothing" forever: a FABRICATED FAILURE, exactly as
    dishonest as a fabricated pass and much easier to believe, because it looks
    like the code under test failing on another platform. **THE SAME HAZARD HAS A
    SECOND, QUIETER FORM**: constructing a fresh `psutil.Process()` on every read
    perturbs it identically (0 MB freed), while hoisting ONE Process object out
    of the loop agrees with `/proc` to the hundredth of a MB. So a memory
    instrument must be resolved ONCE, before anything is measured, and each
    reading must allocate as close to nothing as possible. **PROCESS NOTE, and
    the reason this entry is trustworthy at all: I reached the right conclusion,
    then refuted it, then re-reached it.** Single runs of each configuration
    disagreed with each other (66 MB / 0 MB / 49 MB / 0 MB across four one-off
    probes), and from that noise I first concluded "the fork destroys it", then
    "no, it is run-to-run variance, my mechanism was wrong". Only running each
    configuration five times showed both readings were wrong about the noise: the
    results are perfectly deterministic PER CONFIGURATION (5/5 identical each) and
    it was the one-at-a-time comparison that was unreliable. When a measurement
    disagrees between runs, the answer is more runs of each arm, never a better
    story about the difference. `resource.getrusage`'s `ru_maxrss` was never a
    candidate: a high-water mark cannot measure a DECREASE and would report
    success for any implementation at all (the recorded 2026-08-06 lesson).
    GUARD: because Linux prefers `/proc` and would never exercise the fallback,
    a dedicated test drives the real probe with ONLY `/proc/self/status` blocked
    (psutil reads `statm`, so it survives — a blanket `/proc` blackout would
    disable the very fallback under test and prove nothing) and requires the
    portable path to see the same release. Three mutations redden it by name:
    fork per read, Process per read, and no fallback at all.
  - **AND THE GUARD I JUST DESCRIBED FABRICATED A DIAGNOSIS ON THE PLATFORM IT WAS
    WRITTEN FOR (2026-09-03, the macOS lane, one day later):** it COMPARES the psutil
    answer against a `/proc` reference, and its own docstring says so — "checked FROM
    Linux". It had no gate, so it also ran ON macOS, where the shim blocking
    `/proc/self/status` does nothing (the file never existed), psutil takes the Mach
    path, and macOS's allocator does not hand freed pages back to the OS at all. It
    then reported **"the instrument is perturbing the measurement"** about a platform
    where the instrument is fine and the PLATFORM is what freed nothing. A fabricated
    diagnosis is exactly as dishonest as a fabricated pass, and it is worse to debug,
    because it names a mechanism that is not there. **THE PART THAT MATTERS IS THAT
    THE FIX WAS ALREADY WRITTEN TWENTY LINES ABOVE IT**: the sibling premise test
    skips when `instrument != "proc"` and the platform freed nothing, with the reason
    "calling this a failure would report a platform we never measured as a broken
    shrink_memory" — I wrote that guard and the ungated test in the same pass, which
    is the recorded "a lesson recorded against one assertion does not propagate itself
    to the one beside it" trap at its shortest possible range. GENERAL FORM: a test
    that COMPARES two instruments needs its REFERENCE, so gate it on the reference
    being available — not on a `sys.platform` string, which is a proxy for the thing
    you actually need — and make the skip say what stays unchecked there.
  - **A BAR SET AT EXACTLY `signal + one noise quantum` HAS ZERO SLACK — and whether
    to raise the input or change the claim is decided by asking if the noise is FIXED
    or PROPORTIONAL (2026-09-03, the shared-budget test on macOS):**
    `test_both_side_files_share_ONE_budget_not_one_each` failed at 1.353s and 1.385s
    against a 1.25s bar on BOTH lanes of one commit — systematic, not a flake (the
    recorded push-vs-PR A/B), in code the branch never touched. The mechanism:
    `_retry_while_locked` checks the deadline BEFORE `time.sleep(0.25)`, so an
    iteration starting a hair inside the budget legitimately returns one whole quantum
    past it — the shared case is **bimodal** at `budget` or `budget + 0.25`. The bar
    was `budget + exactly one quantum`, i.e. it allowed the overshoot and left nothing
    for `sleep()` returning late; an idle Linux box measured 1.213–1.226 against it,
    **24 ms of headroom**, so it was about to bite the blocking lane too. THE
    CALIBRATION RULE, which refines the recorded WAL and llm-throughput entries with
    the case neither covers: that llm lesson says raise the input when the noise
    scales with the work and change the CLAIM when it does not — here the noise is
    FIXED (one quantum) while the SIGNAL scales with the budget, which is the third
    combination and the one where raising the input is strictly the strongest lever.
    1.0s → 2.0s doubles the gap and leaves the quantum where it was: measured across a
    full-quantum sweep, shared 2.002 flat (worst legal 2.25), per-file ≥ 3.00, bar
    2.60 — 0.35 s of slack above and 0.4 s below, where there had been 0.03. The
    per-file mutation reddens at 3.13. COROLLARY worth grepping for: **any loop that
    checks a deadline before sleeping overshoots by up to one sleep**, so every budget
    assertion over such a loop owes room for a quantum it cannot avoid.
  - **A GUARD THAT FINDS THE CALL IS NOT A GUARD THAT RESOLVES THE NAME — and I wrote
    both the guard and the defect in one pass (2026-09-03, the header-cache
    invalidation):** the ledger already says *"any 'module X imports what it uses'
    assertion has to resolve the binding (ast, enclosing scope), or it is satisfied by
    an import that cannot be seen from the call"* — and the first cut of this slice's
    guard asserted that `invalidate_header_cache` appeared as an `ast.Call` anywhere
    in the file. It did: in a function whose scope had no import for it, so the
    endpoint would have raised `NameError` in the `finally` on the very path the guard
    existed to protect. **Only ruff's F821 caught it.** So the recurrence is the
    finding, and what the entry was missing is the RECIPE: build a `child -> parent`
    map, walk up from the call collecting the scopes it can see (each enclosing
    function, the module; a `ClassDef` only when the call sits directly in it, since
    class names are not visible to nested functions), and for each scope scan its own
    body for a binding — an import alias, a `Store` `Name`, a `def`/`class` of that
    name, a parameter, a `global` — WITHOUT descending into nested scopes, which have
    their own. Three mutations: dropping the import reddens by file and line, deleting
    the call reddens (the enumeration half still holds), and **hoisting the import to
    module scope must PASS** — the negative twin, because a guard that demanded one
    import style would be a fabricated failure the day someone legitimately moved it.
  - **A VERIFICATION TABLE NAMING TESTS IS AN EVIDENCE TABLE, AND I FABRICATED 14 OF 24
    CELLS FROM MEMORY (2026-09-03, the brief's §7 contract):** the recorded 2026-08-23
    lesson says a table "has a cell for every intersection and an empty one reads as an
    omission, so the shape itself asks to be completed", and names back-filled FIGURES
    as the hazard. The same pull applies to IDENTIFIERS, and it is easier to miss
    because a plausible test name looks like a citation rather than a number: writing
    one row per slice from memory of work I had done myself produced 14 names out of 24
    that **do not exist in the tree** — every one grammatical, house-style, and
    describing the right property. A reviewer following such a table finds nothing and
    cannot tell an invented name from a renamed test. THE DETECTOR IS TWO LINES AND
    SHOULD RUN BEFORE ANY SUCH TABLE SHIPS: extract every backticked `test_*` from the
    document, list the real ones with `grep -rho "^def \(test_[a-zA-Z0-9_]*\)" tests/`,
    and `comm -23` the two — anything printed is fabricated. Re-derived from the files,
    the same table came to 57 names and all 57 resolve. GENERAL FORM: a claim is only
    citable if it was READ; when a document's job is to let someone else check the work,
    every identifier in it is a measurement, and memory is not a measurement.
  - **EDITING ONE FILE MID-RUN MANUFACTURED EIGHT FAILURES, AND "NEVER SWITCH BRANCHES"
    UNDERSTATES THE RULE (2026-09-03):** the recorded 2026-07-09 lesson says never switch
    git branches while a background suite runs. I did not switch anything — I reordered
    two import lines in `src/backup/merge.py`, semantically identical, while a full run
    was at ~55%. The run reported **8 failures** across four files, every one of which
    reads that module's source; all eight pass alone, all 68 pass together, and the clean
    re-run reconciles exactly (8596 + 8 = 8604). THE DIAGNOSTIC SIGNATURE is worth more
    than the count: `inspect.getsource(merge.run_restore)` returned
    `'    staged: StagedArtifact,\n'` — a single line of the SIGNATURE — so every source
    anchor failed with `ValueError: substring not found`. If you see a source-reading test
    fail that way, suspect the tree moved under the run before suspecting the code.
    **THE MECHANISM IS NOT ESTABLISHED, and saying so is the point.** Two hypotheses were
    tested and neither reproduced: a `co_firstlineno` line-shift self-corrects, because
    `inspect.findsource` walks BACKWARD to the nearest `def`; and a `linecache` poisoning
    from a read during `open(p,"w")`'s truncation window explains the spread across
    minutes but could not be reproduced either. So the rule stands on the reconciliation,
    not on a story: **any write to a tracked file during a run can invalidate it**, because
    a suite reads source from disk long after importing it, and the wording to remember is
    "do not mutate the tree", not "do not switch branches". Cost: one 18-minute run, plus
    the time spent believing eight real-looking failures.
  - **A COMMENT IS NOT A GUARD AGAINST A BOT — AND THE JUSTIFICATION ITSELF CAN CARRY A
    FABRICATED FACT (2026-09-03, `pqcrypto` re-widened 14 days after it was pinned):** the
    2026-08-20 lesson ends *"Put the reason in the constraint comment, or the next reader
    simply widens the bound."* The reason WAS in the comment, in capitals, naming the
    migration doc it required — and dependabot #996 widened `pqcrypto>=0.3.4,<1.0` to `<2.0`
    anyway, and it merged, because the next reader was not a reader. Prose addresses humans;
    only a CI-visible mechanism addresses a bot, and this bound had no test. **THE HALF WORTH
    MORE:** that same comment asserted 1.0.0 *"returns `PublicKey` / `SecretKey` objects
    rather than raw bytes"*, which measurement REFUTES — `keygen()` returns plain `bytes` and
    `PUBLIC_KEY_SIZE` is 1952 in both versions. The real second breakage was elsewhere and
    worse: `verify` returns `None` for a VALID signature (0.4.0 returns `True`) and raises for
    an invalid one, so a `bool(verify(...))` call site reports every valid signature as a
    verification FAILURE — silently, in a tamper-evidence path, and reached without ever
    calling the renamed function. An unverified elaboration inside a justification is not
    harmless decoration: it makes the bound easier to dismiss AND points whoever eventually
    does the migration at a key-format problem that does not exist. RULE: when you record WHY
    a bound exists, install both versions and write down what you MEASURED — here 1.0.0 → 16
    failed / 23 passed in this repo's own suite against 0.4.0 → 39 passed, which is checkable,
    where a changelog paraphrase arrives at the same confidence and is where the error will be.
    **THE BOUND HAS A TEST NOW (2026-09-07, PR #1016) — and writing it produced a finding the
    obvious version of the guard would have missed: THE NEGATIVE-SPACE TWIN IS LOAD-BEARING ON A
    VERSION CEILING, because over-narrowing SATISFIES the ceiling assertion.** `pqcrypto==0.3.4`
    and `<0.4` both exclude 1.0.0, so both make a lone "the ceiling refuses 1.0.0" guard GREEN
    while dropping the release a real install resolves to — i.e. the cheapest way to fix the
    guard would be to make the extra useless. Mutation-proven in both directions: widening to
    `<2.0` (dependabot's exact change) reddens ONLY the ceiling test, over-narrowing to
    `==0.3.4` reddens ONLY the twin **while the ceiling test still passes**, and deleting the
    requirement trips an anti-vacuity helper — an absent requirement parses as an EMPTY
    `SpecifierSet`, which admits everything, so a guard that tolerated it would pass hardest at
    exactly the moment the ceiling stopped existing. Two riders. (a) Assert CONTAINMENT via
    `packaging.SpecifierSet`, never the literal constraint string: a lower-bound bump is
    legitimate and must not redden, and `packaging` ships wherever pytest runs (pytest requires
    it), so it is safe on the Core-only lane. (b) The failure MESSAGE is the whole deliverable —
    it is what a reviewer of the widening PR reads — so it names the constraint that was set,
    the version it now admits, and the inverted predicate, not just "bound changed".
    **(c) A GUARD WHOSE SUBJECT IS THE ENVIRONMENT IS UNREACHABLE UNLESS THE LANE THAT BUILDS
    THAT ENVIRONMENT COLLECTS IT — found in my own test, before it shipped.** The third guard
    compares the DECLARED ceiling against what pip actually RESOLVED, and it could not run
    anywhere: every bare `pytest -q` lane collects the file with no `[pqc]` installed, so it can
    only reach its own skip, while `crypto` — the ONE lane that installs the extra — runs two
    explicitly-named files and never collected it. Green in every lane, executed in none,
    reading as coverage. Naming the file in that lane fixes it, and the fix is MEASURABLE: with
    the extra installed the file goes 2-passed/1-skipped → 3-passed, and with pqcrypto 1.0.0
    installed against the declared `<1.0` it fails ALONE (1 failed / 2 passed) — which is also
    what proves it is not redundant with the twin, since the twin can only ever check a
    `_SHIPPED` constant a human wrote down while this one checks what upstream actually
    published. GENERAL FORM: when a test's meaning depends on an OPTIONAL extra, find the lane
    that installs that extra and confirm it COLLECTS the file; a lane that names files
    explicitly is where an environment-gated guard goes to die. Same class as the node-suite
    driver ratchet, which exists because an unrun suite already cost a shipped defect — there
    the file had no runner, here it had a runner in the one environment where it means nothing.
  - **A RESERVE SIZED FOR A MECHANISM THAT IS SWITCHED OFF IS NOT CONSERVATISM — it is a
    permanently unclaimed resource, and a "conservative" default stops being conservative
    once it decides EVERY machine (2026-09-05, the field context window; maintainer-ruled
    on the measurement the constant's own docstring asked for):** the 8 GiB field card ran
    `--enforce-eager` with `gpu_memory_utilization: 0.77`, peaked at **6294 MiB of 8188 —
    76.9%**, and simultaneously refused every 4057-token prompt with *"maximum context
    length is 2048 tokens"*. ~1.9 GB sat behind `_GRAPH_POOL_RESERVE_GB`, which is sized
    for the **CUDA-graph capture pool** — a pool eager mode never allocates and vLLM's own
    log says so ("Cudagraph is disabled under eager mode"). The docstring had already
    written the condition for changing it — *"If context length on small cards ever needs
    the room, measure first"* — so when the measurement arrives, honouring it is the
    promise, not a relaxation. Scope the reclaim to the mode where the mechanism is off;
    the capture reserve is untouched, because nothing here measured capture succeeding.
    **THREE RIDERS.** (a) **A monotonicity guard across a mode boundary fires on a
    decision, not a defect** — an eager card now legitimately claims a greater fraction
    than a slightly larger capture card, so the guard asserts the property WITHIN each
    mode (twice) rather than being deleted; the class it was built to catch is unchanged.
    (b) **Never past upstream's own default**: 0.90 stays the cap, so the reclaim moves
    toward vLLM's number and never beyond it — being bolder than upstream on the smallest
    hardware is the wrong direction to be bold in. (c) The budget still tracks what is
    FREE, so a card holding a display server narrows itself instead of over-asking.
    **AND THE ARITHMETICALLY SUFFICIENT CAUSE WAS SOMEWHERE ELSE ENTIRELY, which is the
    part worth the most:** `measured_weight_gb`'s docstring said it over-counts "in the
    safe direction" because a repo shipping both a consolidated checkpoint and its sharded
    equivalent — *"(Mistral's do)"* — has both on disk while the loader reads ONE. That was
    true right up to the day the repo doing it became the **only repo we ship**: the doubled
    figure (~3.3 GB counted twice, plus the load margin) spent the whole post-weights budget
    and floored `max_model_len` at 2048 **whatever the KV cost per token was** — so the whole
    2026-08-13 KV-derivation fix was invisible behind it. GENERAL FORM: a known over-count
    documented as harmless is a finding waiting for its population to shrink to one; group
    the mutually-exclusive alternatives and take the MAX, which keeps the safe direction
    without paying for it twice. **THE FOURTH DEFECT IS WHY IT TOOK A ROUND TRIP:** the
    diagnostics context block called `compute_server_args` with neither the checkpoint's KV
    cost nor its measured footprint, so it always described the FALLBACK derivation — a
    start no machine performs — and reported *"this model's own shape could not be read"*
    about a machine whose shape had never been looked at. When a report publishes a
    DERIVATION, it must be handed the same inputs the production path uses, and publish
    those inputs beside the outputs; otherwise the export cannot distinguish a machine that
    failed to read its checkpoint from a reader that was never called.
  - **A SET-VALUED EXPECTATION IS AMBIGUOUS BETWEEN "ALL OF" AND "ANY OF", AND THE
    READER WILL PICK THE ONE THAT MAKES THE BAR UNWINNABLE (2026-09-05, the
    source-tags canary):** `CANARY_EXPECTED` maps a canary to
    `frozenset({"finance","economy","economics","business"})` — four spellings of ONE
    concept, i.e. an alternatives list. `check_source_canaries` read it as a
    CONJUNCTION (`applicable.issubset(got)`), so the model had to name all three that
    exist in the live vocabulary. Measured over the field run's 118 batches it never
    did — while answering `economy+finance` 23 times and
    `economy+finance+official-statistics` once, which are correct answers for a
    statistics agency — and was scored FAILED **118 of 118**. Before writing a
    membership test over a set someone else declared, ask whether they meant *all* or
    *any*; if the structure cannot say, the structure is the defect, and a future
    conjunction needs an EXPLICIT mode rather than a second re-reading. **THE HALF
    THE 2026-08-11 DENOMINATOR LESSON DOES NOT COVER:** the same boolean also folded
    in 82 canaries the model never answered — 39 of them in batches whose median
    missing-share was **1.00**, i.e. the model returned nothing parseable for ANY
    source. There the canary was a WITNESS to a dead batch, not its subject, and
    `pb.missing` already counted it. So a probe of JUDGEMENT needs a no-evidence state
    distinct from both pass and fail, or it reports on the transport instead of the
    thing; of 161 recorded "failures", **zero were a wrong topic**. TWO COERCION TRAPS
    once the verdict is a tri-state, and they fail in opposite directions, so both
    need a test: `bool(None)` is False, so any serialisation or run-level `and` that
    coerces it publishes a fabricated failure (three call sites did); and `ok: True`
    with `checked == 0` is the vacuous pass — an existing test asserted exactly that
    and had to be amended deliberately. **THE VOCABULARY HALF REFUTED MY OWN FRAMING,
    which is why it was measured first:** I proposed "dedupe the near-synonym pairs",
    and of 17 collision candidates in the live 204-tag vocabulary exactly ONE was
    provable (`case-law`/`case_law` — `_norm_term` folds case, accents and whitespace
    but not `_` against `-`), two were singular/plural JUDGEMENTS, and **fourteen were
    real hierarchies** (`africa`/`east-africa`, `official`/`official-statistics`,
    `lean-center`/`lean-center-left`) that a stem-based sweep would have destroyed. So
    fold only what is provable, REPORT the rest, and fold the PROMPT while parsing
    against the FULL set — a strictly non-narrowing change, so no answer that used to
    resolve becomes a rejection. RIDER worth its own line: `resolve_tag_vocabulary`
    takes every distinct `Source.tags` value, and this codebase uses that column for
    provenance (`via:*`), coverage state, political lean and file formats — so a
    "closed topical vocabulary" resolved live is not topical. Measured, it is latent
    rather than live (2 non-topical proposals in 921 assignments), and the fix is a
    reported finding rather than a silent filter, because deciding `independent` is
    not a topic is a taxonomy ruling a human makes.
  - **A RELEVANCE-RANKED ID LIST IS NOT A SAMPLE FRAME — and for this question its bias
    ran the way that would have decided the ruling (2026-09-05, the month-occupancy
    diagnostic):** the cheap way to find articles containing a month name is
    `search_ids`, and it is the wrong way, because it is `ORDER BY bm25(...)`: the
    top-ranked documents for `march OR mai OR …` are the ones where a month token is
    DENSEST, which is a near-definition of a dateline-heavy page. Sampling from it would
    have over-counted the consumed side and under-counted the free one, i.e. produced a
    number saying "the ban is nearly free" for a reason that is entirely an artifact of
    the ranking. Drawn uniformly over the id range instead, with the one bias that
    substitutes STATED (an article just after a large id gap is over-represented, because
    each draw takes the first article at or above it) — a stated bias is a different
    object from an unexamined one. GENERAL FORM: whenever a search API is the convenient
    way to enumerate candidates, read its ORDER BY before treating the result as a
    population, and ask which direction its ordering pushes the specific quantity being
    measured. Two riders. Scanning uniformly costs a decrypt per article, most of which
    contain nothing of interest — recovered by running the cheap regex FIRST and paying
    for the expensive extraction only on a hit, so the sample size is bounded by hits
    rather than by draws. And the draw is SEEDED, because a diagnostic a maintainer may
    run twice owes the same answer twice; the seed and a bounded list of the ids drawn
    both ride in the payload, which is also what makes the determinism assertable rather
    than inferred.
  - **WHEN A MUTATION OF AN ARGUMENT SURVIVES, MEASURE WHETHER THAT ARGUMENT CAN CHANGE
    THE ANSWER AT ALL BEFORE INVENTING A TEST FOR IT (2026-09-05, same slice):** dropping
    the article's `language` from the diagnostic's call reddened nothing, and there are
    two wrong responses — write a contrived fixture until something fails, or conclude the
    argument is dead and delete it. The measurement settles it: over the 82 banned month
    names crossed with 12 languages and 7 sentence templates, `language` changes the
    outcome in exactly one shape — Hungarian's year-first `2024. december`, which the
    extractor reads only under a `hu` hint. Every other banned token sits in the
    language-agnostic table, and NO banned token is in the gated map at all. So the
    argument is (a) genuinely load-bearing, for one real and realistic case, and (b)
    nearly unfalsifiable on any other fixture — which is precisely why the test has to
    use that case and say so, or the next person to read it will "simplify" the fixture
    and silently restore the gap. The general rule: a surviving mutant is a finding about
    the test, and the first step is to find out what the argument DOES on the live data,
    not to keep guessing at fixtures. A currently-inert argument may still be right to
    pass — the banned set can grow into the gated vocabulary tomorrow — but that is a
    claim to write down, not one to leave implied by an untestable line of code.
  - **THE MEASUREMENT YOU NEED MAY ALREADY BE COMPUTED INSIDE A FUNCTION AND DISCARDED AT
    ITS RETURN (2026-09-05, the claimed-span seam):** the standing lesson says to check
    whether an instrument exists before building one; a level below it, check whether the
    thing exists as a LOCAL. `extract_dates` resolves overlapping matches most-specific-
    first by claiming character ranges, so it has always known exactly which text it
    consumed as a date — and returned only the dates. The month question is a question
    about those ranges, and the honest answer was a seam (share the body, return the pair,
    keep the public wrapper byte-identical) rather than a re-implementation that would
    have drifted from the extractor the moment either changed. Two details worth keeping.
    The exposed spans are deliberately a SUPERSET of "a date was stored" — the Jalali
    router claims on route, so an ambiguous Persian date is claimed and then refused — and
    for "was this token read as part of a date?" the superset is the right answer, so the
    docstring states which direction it errs in rather than leaving a caller to assume
    equality. And the spans index the text the pass actually SCANNED, so a caller reading
    an offset past `_MAX_SCAN` as "not claimed" would fabricate an absence out of a bound;
    that is a property of the seam, so it belongs in the seam's contract and in a test,
    not in each caller's memory.
  - **BEFORE CALLING A HELPER FOR A SIDE VALUE, CHECK WHETHER IT IS ALREADY IN SCOPE — AND
    WHETHER THE HELPER'S CALL COUNT IS ITSELF AN INVARIANT (2026-09-05, `_articleQuery`):**
    the R1 notice needed to know whether the current view has a text query, and I wrote
    `_articleQuery(p).get("query")` three lines below `const q = _articleQuery(p)`, which
    already held it. Harmless as waste; not harmless as a guard breach, because
    `test_every_api_articles_caller_goes_through_the_translation` deliberately counts
    `_articleQuery(` uses against `/api/articles` URL sites rather than checking variable
    names — its own docstring says naming would pass for a caller that picked the same
    name without using the helper. A convenience call is indistinguishable from a caller
    that skipped the translation, so the count broke on correct code. The repair is not to
    relax the guard: it is the change that should have been written anyway. GENERAL FORM:
    a test that counts CALL SITES is asserting a coupling, so any extra call — however
    innocuous — is a claim about the code it will make on your behalf; read the failing
    guard's docstring before deciding whether it or the code is wrong.
  - **A LESSON DOES NOT APPLY ITSELF TO THE CODE YOU ARE WRITING — grep for the READERS of
    every field you just published, and know which kind of field it is (2026-09-05, the
    omnibar cross-language block):** slice 1 taught `search_omni` to publish a
    `cross_language` block, a per-row `via_ring` flag and a separate `cross_language_items`
    count, and its own commit message cites the standing "a machine-readable refusal whose
    flag no caller ever sends is a DEAD END" lesson — about a different subsystem. Nothing
    in the frontend read any of the three. The ledger already carries that shape at least
    five times (the 409's `acknowledgeable`, `start_outcome()`, `ai_worklist`, the tri-state
    read in four places, `propose_stoplist_additions`) and it recurred anyway, in the slice
    that quoted it, because the rule was being applied to the code being CALLED and never to
    the code being WRITTEN. The check is one grep of the CONSUMING surface for the FIELD
    NAME (not for the endpoint, which is called either way), and it belongs at the end of
    any slice that adds a field to a payload. **THE DISCRIMINATOR MATTERS AS MUCH AS THE
    GREP, or the rule turns into "delete every unread field":** running it over all fourteen
    keys of this payload found two more unread by both the frontend and the tests
    (`matched_language`, `normalized`) and they are NOT the same defect — the question is
    whether an unread field is the only route to a CAPABILITY or is EVIDENCE inside a
    payload whose summary is already rendered. The disclosure block was the former: unread,
    the reader lost the whole honesty layer on that surface. The two provenance fields are
    the latter, sitting beside a `method` and a `caveat` the house convention puts in every
    payload precisely so a number can be checked by a reader the UI does not know about.
    Kept, deliberately, and now measured rather than assumed. Same read found the display
    bug below, which is the argument for doing this as a step rather than as a habit: the
    consumers you go looking for are also where the consumers you already had went wrong.
  - **A "N MORE" DISCLOSURE COMPUTED FROM `len(items)` IS DELETED BY PADDING THE LIST FROM A
    DIFFERENT POPULATION (2026-09-05, the same read):** the omnibar states a group's true
    size with `g.total > (g.items || []).length`, which was exact while every row came from
    the same query. Slice 1 then APPENDED cross-language sibling rows to the keywords group
    while its `total` stayed deliberately the PREFIX total (two populations; one number
    would describe neither) — so the padded row count could exceed a total that was still
    larger than the rows the reader typed for, and the "N matches in total" note vanished
    exactly when siblings were present, i.e. exactly when the group was least
    self-explanatory. GENERAL FORM: a disclosure derived from a collection's LENGTH is a
    claim about the population that collection holds, so adding members from another
    population silently changes what the disclosure means — count the rows the total
    actually describes, not the rows on screen. Same family as the recorded "two surfaces
    computing the same-sounding quantity by different rules", one layer down: here the two
    rules met inside one expression.
  - **A SURVIVING MUTANT CAN BE A FINDING ABOUT THE CODE — measure for EQUIVALENCE before
    writing a test to kill it (2026-09-05, same slice):** the mutation matrix left three
    survivors. Two were the recorded "a test of a helper is not a test of its wiring" gap
    (the node suite drove the helpers and never the row builder, so blanking the header note
    and dropping the per-row label both passed) and were closed with a wiring test. The
    third was not a gap at all: dropping `!terms.length` from a two-clause guard is
    BYTE-IDENTICAL over 11 payload shapes, because an empty list adds nothing in the loop
    and the tail already returns `""` when nothing was pushed. The reflex — write a fixture
    until something fails — would have pinned a redundancy forever and read as coverage.
    Measure the two versions against each other first; when they agree, DELETE the redundant
    clause with the measurement in a comment (so the next reader does not restore it as a
    missing guard) and replace the mutation with one that can actually fail. The standing
    rule "a mutation that reddens nothing is a finding" is right about the finding and
    silent about its subject, which can be the test, the fixture, or the code.
    RIDER, a node-harness fact worth not re-deriving: `app-*.js` modules share ONE global
    scope, and a guard written `window.OOI18N && OOI18N.tf` reads BOTH the property and the
    bare global — so a sandbox defining only `window.OOI18N` raises `ReferenceError` on the
    second half. Define the alias, and put every function under test in ONE sandbox: two
    `runInNewContext` blocks each defining that global throw `Cannot redefine property`, and
    the near-miss version (both merely assigning it) is worse — last-one-wins leaves the
    earlier block silently reading the later block's state.
  - **A TREE-SCANNING GUARD IS NOT IN THE SUITE YOU RUN FOR YOUR OWN FILES (2026-09-05, the
    omnibar guard's unencoded locale read):** before pushing I ran the four suites the change
    touched — 290 passed — and the full run then failed one test I had not thought to run:
    `test_utf8_file_io`, which walks the WHOLE tree for a text read or write with no
    `encoding=`, and my new guard read `en.json` with the platform default. On Windows that
    is cp1252 and it CRASHES rather than failing an assertion, on this file in particular,
    because the keys being asserted carry curly quotes. The general point is about which
    tests a new FILE can break: not only the tests of that file, but every guard that reads
    the tree — and this repo has four
    (`test_utf8_file_io` · `test_source_slicing_discipline` · `test_repo_invariants` ·
    `test_import_conclusion::test_every_node_suite_has_a_driver`). I ran the one I remembered
    and got lucky on the other two that were live for this change (the commit added a node
    suite AND touched source slicing). Run them as a NAMED SET after adding or editing any
    file; they cost seven seconds together, against the sixteen minutes of the full suite
    that is the only other thing that would have caught it.
  - **A ROLLUP THAT IS CORRECT AT ITS OWN LEVEL IS THE HARDEST RENDER-BOUNDARY LOSS TO
    SEE — nothing in the payload is wrong, and the reading it produces is the opposite
    of the truth (2026-09-05, the one-button AI check's extraction gate):** the recorded
    lesson says a distinction dies at a render boundary unless the renderer is part of
    the change. Every earlier instance had something visibly missing or visibly wrong.
    Here `_gate_lines` read `v["active"]` — the language-level rollup, which is `True`
    when ANY field clears and is documented as meaning exactly that, so it was right —
    and published `cleared: 13, refused: 0, unmeasured: 0`. Running the same gate over
    the same report: **20 of 39 FIELD verdicts cleared, 2 refused, 17 never measured**,
    with `hi`'s `who` refused for INVENTION (hallucination 1.0 past the 0.5 floor) and
    `fr`'s `who` for SILENCE (recall 0.0) — the two different failures the two floors
    exist to tell apart — while eleven of the thirteen "cleared" languages cleared on
    `where` ALONE. The earlier 08-12 report in the same bundle is worse: `who` refused in
    **all 13 languages**, 30 of 39 verdicts refused, rendered as "cleared: 7". So the one
    surface that answers *does my local model invent things* said no while the gate it
    reads was refusing that exact field everywhere. FOUR RULES. (a) When a payload carries
    a ROLLUP, ask what it is a rollup OF and whether the renderer publishes that too — a
    correct summary is not evidence that the detail survived, and `active: True` meaning
    "worth a call" is not `active: True` meaning "cleared for everything". (b) Do NOT fix
    it by redefining the rollup: the key had readers and its own documented meaning, so the
    level BELOW is added beside it and the note is what stops `cleared` over-reading (the
    recorded "the name is the part you are allowed to change" rule). (c) **There were TWO
    boundaries, and publishing without rendering moves the silence one function along** —
    `ai_check._gate_lines` dropped it from the payload and `_renderAiCheck` would have
    dropped it from the panel, so the fix is only a fix when both are in the same change;
    the renderer half is guarded BEHAVIOURALLY, because asserting `refused_fields` appears
    in the slice passes with the loop that draws it neutered (the `d.other` shape).
    (d) The RUN was correct throughout — `field_gate` discarded both refused fields and
    the sweep tallies `field_gated` per field — which is what made this invisible: there
    was no failure to investigate, only a report that could not be read. **AND THE
    MUTATION-MATRIX HALF, worth as much: a mutant that survives may be a finding about the
    MUTANT.** My first "treat an old fields-less report as a measurement gap" mutation
    passed everything, and the survival was correct — the legacy branch skips those entries
    in both loops, so the field list is empty and the fabricated-gap outcome is unreachable
    BY CONSTRUCTION rather than by a guard. Nothing can produce it, so no test can catch it,
    and a test written for it would assert a property nothing can break. Re-target the
    mutant at a mechanism that CAN be removed (here the disclosure itself) and record WHY
    the first one was rejected, or the next session re-adds the vacuous test. Sibling trap
    from the same run: a shell-quoted `str.replace` mutation whose needle never matched
    reported 42-passed twelve times over, which reads exactly like twelve dead guards —
    every mutation must `assert new != old` before its run is allowed to mean anything.
  - **A MODEL'S "JUNK" VERDICT IS ABOUT A TOKEN; A STOPLIST ENTRY IS ABOUT A LANGUAGE —
    and the gap between the two is 90% (2026-09-05, the keyword-triage batch):** the
    proposal offered 20,611 terms the model called junk. Hand-classifying a seeded random
    sample of 60 across the three languages the reviewer reads well
    (`docs/audit/keyword-triage-2026-09-05-sample.csv`, reproducible from
    `random.Random(20260905)`): **10% site chrome · 40% inflected verbs and adjectives ·
    27% real content nouns and proper nouns · 20% phrase fragments · 3% genuine
    function-word gaps.** The verbs and adjectives are the recorded lemmatization
    territory, the content nouns are the recorded open-class trap (nl `spanje`, `wereld`,
    `brandweer` were all offered), and even inside the 10% only a third survived a second
    bar — **furniture in a LANGUAGE, not furniture on one SITE**: nl `lang gratis` and de
    `klick online` are one publisher's subscription copy, and stoplisting them per-language
    would hide those words for every other publisher that uses them meaningfully (that is
    the source-auditor's `furniture_share`, not the stoplist's job). Twenty words shipped
    of 20,611 offered. FOUR RIDERS, each measured rather than reasoned. (a) **The
    `setdefault` in the loader makes a NEW key a REPLACEMENT, not an addition**:
    `scoped_stopwords.setdefault(lang, set()).update(curated)` means a curated entry for a
    language with no vendored `configs/stopwords_iso/<lang>.txt` CREATES the key, and
    `get_stopwords` then stops falling back to the English default — one word for `sr` takes
    its stopset **128 → 1**. Invisible in every existing test, because every existing key
    has a file; now a guard that proves the hazard rather than asserting it. (b) **The
    channel a proposal NAMES is not the channel its caveat DESCRIBES**: the artifact is
    `kind: scoped_stoplist_additions` and its caveat says an entry "hides every existing
    mention at query time" — true of the global channel (`hidden_set` unions
    `global_stopwords()`) and FALSE of the scoped one, which never reaches it. A scoped
    entry is index-time only; the existing mentions go on the next re-index. Read what the
    consumer does, not what the producer's prose says. (c) **`en` and `fr` cannot use the
    scoped channel at all** — `get_stopwords` checks `language_stopwords` first and those
    are its only two keys, so an English or French addition is necessarily GLOBALISED and
    owes cross-language review; that is one structural reason, and it subsumes the separate
    worry about `Keyword.language` being first-write-wins. (d) **A stoplist entry derived
    from unsegmented text is pinned to the tokenizer's failure mode**: with the
    `[segmentation]` extra absent, `th` terms are 3-character MARK FRAGMENTS (median 3.0
    chars — `งหว`, `ทำให`) while `zh`/`ja` are whole unsegmented RUN-ONS (median 8 and 7.5 —
    `保證天天中獎 點我下載app`, `会員限定記事`). Both are genuinely junk and neither is a WORD, so
    an entry for either would be dead weight the day a segmenter is installed and the token
    shape changes. Two different artifacts, one exclusion. **AND THE LABEL ONLY SELECTS THE
    CANDIDATE**: `Keyword.language` is first-write-wins (`reconcile_keyword_language` is the
    documented repair and runs only in the re-index cleanup), so the language a term is
    filed under is a hint, not a finding — every word in the batch was assigned by READING
    it, which is the only step that makes a language-scoped entry safe.
  - **A NEAR-SYNONYM IS NOT A NEW TAG — check a proposal against the tags the ENTRY
    ALREADY CARRIES and against the catalog's DOMINANT FORM, never against the domain
    (2026-09-05, the source-tag batch; the mistake is mine, not the model's):** the same
    sweep proposed tags for 223 sources, and the 164 with ≥20 collected articles were
    hand-reviewed rather than merged. The model's systematic defect is easy to state — **a
    keyword-derived tag describes the SCRAPE WINDOW, not the source**, which is how
    nawaat.org (Tunisian) was offered `east-africa`, medievalists.net `ancient-history`,
    and Argentina's largest general daily `climate` as its ONLY tag. The interesting half
    is that the careful review then made the mirror mistake: four entries were dropped on a
    SECOND pass because each proposal had been judged against the DOMAIN, and against the
    entry's own tags they were synonyms — `finance` beside an existing `financial` (the
    catalog's dominant form, **178 uses against 9**), `health` beside `healthcare` (86),
    `academic` beside `education`, `academic` beside `philosophy`, which already named the
    beat exactly — **and then six more through the channel the guard cannot see**:
    `disinformation` offered to six fact-checkers that every one of them already answers with
    `fake-news`, the catalog's form for that subject at **210 uses against 14**. That last set
    was found by MEASURING the added tag's frequency and its co-occurrence with the tags the
    entry carries, which is the step the stem guard cannot perform for you. A synonym does not add a fact; **it splits one collection stratum in
    two**, which is the fragmentation the canary work addresses in the model's vocabulary,
    recurring one level over in the batch that was supposed to be the careful one. The
    apply step already dropped EXACT duplicates, so nothing loud ever fired. THREE RIDERS.
    (a) The guard that pins it must **state what it cannot see**: a stem check finds
    MORPHOLOGICAL variants (`finance`/`financial`) and is blind to the SEMANTIC pair
    (`academic`/`education`), which shares no stem — so the docstring says so, or the next
    reader takes a passing guard as coverage. (b) A guard that passes over four clean
    catalogs **cannot fail when its own predicate is neutered**, so it owes an anti-vacuity
    companion asserting the predicate discriminates (`finance`/`financial` collide;
    `politics`/`policy` and `law`/`case-law` must not) — that companion, not the guard, is
    what the mutation matrix catches. (c) **A domain-keyed proposal cannot be attributed
    where a domain has several entries**: `microsoft.com` carries two (Research Blog `[ai]`,
    Security Blog `[cybersecurity]`), which refused one tag on its own — and the same check
    found **54 duplicate domains, i.e. 227 of the 3,429 entries in `configs/sources.yml`
    unreachable by the create-only seeder**. Corollary when a worklist row is missing from
    the file you expect: it may live in a SIBLING catalog the seeder also reads, and the
    entry that matters is the one the seeding ORDER actually reaches — checking that turned
    six "absent" proposals into four already-satisfied and one worth taking.
  - **THE DEAD-END SHAPE HAS A VERSION WITH A READER INSTEAD OF A CALLER — a refusal that
    names the choice and offers no way to make it (2026-09-05, the several-senses pick):**
    the recorded rule is about a machine-readable answer whose flag no caller sends, and
    the grep it prescribes is "who READS this field". One layer out, the field is read, the
    sentence renders, a human sees it — and there is still nothing to do. R1's refusal told
    the reader that `Wahl` denotes three concepts and that the search had therefore not been
    widened, listed all three, and shipped no way to pick one; R2a had already ruled that
    *the reader picks the sense*. The same grep works with the question changed: not "who
    reads this" but "what can the reader DO with it". Worth separating from the recorded
    entry because the two feel different while shipping — a payload with no consumer looks
    unfinished, and a rendered sentence looks finished — and because the fix is sequenced
    differently: this one belonged with the refusal, not in the later slice its broader
    COVERAGE is gated on. Distinguish the mechanism from the population before deferring
    something: the pick works today over the 91 collisions the rings know, and only the
    inventory's reach waits on a dump.
  - **WHEN A NEW REASON MAKES A PAYLOAD ENTRY MATTER, REVISIT THE FILTER THAT DECIDES WHICH
    ENTRIES ARE EMITTED AT ALL (2026-09-05, same slice):** the disclosure kept
    `[e for e in expansions if e.expanded or e.declined]` — exactly right while those were
    the only two ways a term could be interesting. A rejected sense pin is a third, and on a
    term that touches no ring it is the ONLY one: nothing expanded, nothing declined, so the
    reader's rejected choice would have been dropped by a filter written before that choice
    existed. The general form is that an allowlist-shaped filter fails CLOSED and therefore
    silently — the new case does not error, it simply never appears — so any predicate of
    the form "emit when A or B" is part of the change that introduces C. Same family as the
    recorded explicit-column-allowlist lesson, at the level of a list comprehension rather
    than a SQL INSERT, and with the same tell: the omission is invisible in the diff,
    because the line you would have had to edit is one you did not touch.
    RIDER on the fix's own safety property, which is where a URL-borne selector differs from
    an internal argument: a pin arrives from a link and has exactly two failure modes,
    a typo and staleness (the ring file is regenerated). Neither may widen a search. So the
    pin selects among the candidates the term ALREADY has and can never introduce one, which
    makes both failures end in the same place — ordinary resolution, plus a sentence saying
    the choice was not applied. Validate a selector against the set it claims to select
    from, rather than trusting it and hoping the value is still real.
  - **A REFACTOR THAT PRESERVES *WHAT* IS FOUND NEEDS A DIFFERENTIAL, BECAUSE A NAME-LEVEL
    ASSERTION CANNOT SEE THE FIELD THAT BROKE (2026-09-07, the location extractor's
    dispatch):** splitting `extract_locations` from one-scan-per-pattern into a scan half
    plus an indexed half changes HOW candidates are found and must change nothing about
    WHAT is found, so old and new ran side by side over ~22,000 (text x source_country)
    pairs at both gazetteer scales. The first draft's NAMES were all correct and it was
    still wrong: the result dict's `snippet` still read the loop variable `m` from the scan
    half, so every indexed hit carried some other pattern's snippet, and with no scan match
    at all it raised `UnboundLocalError`. Every assertion I would plausibly have written —
    names, kinds, mention counts — passes against that; the differential compares the WHOLE
    structure, which is why it showed up on the first run. THREE MEASURED FACTS, each
    load-bearing: (a) `rx.match(text, pos)` DOES honour a leading `\b` against
    `text[pos-1]`, so an anchored candidate check is exact and the index needs no boundary
    logic of its own; (b) `re.IGNORECASE` and `str.lower()` DISAGREE on real input —
    `"İ".lower()` is `i` plus a combining dot while IGNORECASE matches `İSTANBUL` against
    `istanbul`, and `ſ` folds to `s` for the engine and to itself for `lower()` — so an
    exact-token index over case-INSENSITIVE patterns is a false-NEGATIVE hazard, which is
    why the ~140 case-insensitive patterns keep their scan and only the case-SENSITIVE half
    is indexed; (c) **the ratio is the wrong headline**: 2,173 -> 86 ms at 4,500 cities
    reads as "25x", but what describes the fix is that 86 ms at 4,500 cities is within noise
    of 82 ms at 21 — the cost stopped scaling with the gazetteer. A ratio is a claim about
    one fixture; a removed dimension is a claim about the next one. COROLLARY: two of four
    mutations SURVIVED and both were test gaps, not redundant code — the discriminating
    input is the one where the obvious simplification and the correct rule differ, and it is
    never the obvious example. Position-order and pattern-order replay AGREE on "Northern
    Ireland" (the longer name also starts first) and differ on "New Mexico City", where the
    shorter guard opens at 0, claims the span, and the city silently disappears; trusting the
    index without re-confirming with the pattern is harmless for every single-token name and
    FABRICATES a place for a multi-word one ("New arrivals were reported." yields New York).
    When a mutation survives, find the input on which the two versions actually differ before
    concluding the mechanism is redundant.
  - **A COMPLETENESS RATCHET WHOSE PARSER CANNOT READ A LOOP IS EXEMPTING WHOLE MIGRATIONS
    (2026-09-07, found when a new column tripped the guard meant to catch it):**
    `test_migration_self_heal_drift` exists so a migration adding a column without a boot
    self-heal fails in CI instead of breaking a user's store at upgrade. Its AST parser read
    `op.add_column` with literal or module-constant arguments and could not resolve a LOOP
    VARIABLE — and four real migrations add their columns from a loop over a module-level
    table, so those four resolved to ZERO columns and were silently exempt: 12 columns across
    four tables that a reader would have read the guard as covering. Nothing was broken (all
    four were genuinely self-healed; only the registry was blind), which is exactly why it
    survived — a detector blind spot has no symptom. The recorded "a ratchet is only as good
    as its detector" lesson with a new, one-grep tell: **compare what the parser resolves
    against a crude textual count of the construct it looks for** (34 `.add_column(` calls
    against 30 pairs resolved — the gap IS the blind spot). And when you extend such a
    detector, put the newly-seen form into its own anti-vacuity assertion, or it can go blind
    again while the guard it feeds keeps passing.
  - **A SESSION CLONE IS SHALLOW UNTIL PROVEN OTHERWISE, AND A BOUNDED HISTORY ANSWERS EVERY
    ARCHAEOLOGY QUESTION WITH ITS OWN BOUNDARY (2026-09-07, resolving twelve `PR pending`
    rows in `shipped.csv`):** the honest way to find which PR landed a ledger row is to
    binary-search `main`'s FIRST-PARENT history for the earliest commit whose `shipped.csv`
    contains it, then read the PR number out of that merge's subject. Run against this
    session's clone that method returned **`#944` for ten different rows spanning seven
    weeks** — because the clone was 56 commits deep and its oldest commit already contained
    all ten, so the search was reporting the truncation point, once per row, with no error
    and nothing to distinguish it from a real answer. Ten identical, wrong,
    authoritative-looking numbers, one commit away from the project's permanent shipped
    record. `git fetch --unshallow` (56 → 1,789 commits) then produced twelve DISTINCT
    numbers. THREE RULES. (a) `git rev-parse --is-shallow-repository` costs nothing and is
    the precondition for any claim about when something first appeared — check it BEFORE the
    search, not after a suspicious result. (b) **The cheap self-test is to ask whether the
    OLDEST reachable commit already satisfies the predicate**: if it does, the answer is a
    boundary artifact whatever the search returns, and that check generalises to every
    bisect-shaped question over a history you did not clone yourself. (c) CORROBORATE from a
    second, independent field — each resolved merge's BRANCH NAME had to match its row's
    subject (`#706 claude/lemma-default-on-brief` ↔ the lemmatization row; `#726
    claude/pagesize-evidence-db10` ↔ the DB-10 §1b row), which is what turned twelve
    plausible numbers into twelve checkable ones. AND THE OBVIOUS SHORTCUT IS NOT ONE: a
    `git log -S` pickaxe over the same needle reports the MERGE commit rather than the
    authoring one on this history, so it agreed with the wrong answer — an agreement between
    two methods that share a defect is not corroboration.
  - **A REPORT THAT RE-DERIVES WHAT A WRITE JUST DID DESCRIBES THE WORLD AFTER THE WRITE — and
    when the field is emitted only-when-non-empty, the wrongness is an ABSENCE (2026-09-07, the
    restore-merge's example rows):** three merge steps captured their `samples` by re-running the
    INSERT's own `WHERE NOT EXISTS` predicate AFTER `_insert_tracked`. The INSERT has just made
    that predicate false for exactly the rows it copied, so the list came back empty on every
    restore since the reports were written — and `DomainResult.as_dict` emits `samples` only when
    non-empty, so the report simply had no examples block, which reads as "this merge added
    nothing". The omitted-field-versus-a-zero rule at the level of a whole section, and no test
    covered `samples` at all. THE FIX GENERALISES PAST THE ORDERING BUG: read back from the
    provenance the write already records (`merged_rows`), which reports what LANDED rather than
    what was predicted to land and cannot drift from the statement — load-bearing here, because
    the `articles` INSERT additionally joins `temp.map_sources`, so the obvious repair (hoist the
    same query above the INSERT) keeps a second copy of the predicate that can name rows the
    INSERT then skips. TWO RIDERS: the sibling `conflicts` lists at four other sites are
    UNAFFECTED and worth checking rather than assuming (they query rows present on both sides,
    which an insert into the target cannot falsify); and the negative twin is what makes the guard
    real, since a repair that listed every INCOMING row satisfies every positive assertion while
    inventing rows that never landed.
  - **A RULED GUARANTEE THAT HOLDS AS A SIDE EFFECT OF AN UNRELATED MECHANISM IS UNTESTED, AND THE
    CHANGE THAT BREAKS IT WILL LOOK UNRELATED (2026-09-07, the disqualified-domain skip):** the
    plan recorded ruling clause (d) — never re-propose a domain this instance judged and refused —
    as "not wired". Driven live before building anything, it already held: both discovery funnels
    dedupe against every existing `Source` domain, disqualified ones included, so such a domain
    never reached the staging call, and `select_unqualified` filters exactly `status ==
    'unqualified'` so the ladder was already the only way back. The defect was not the behaviour;
    it was that the guarantee rested on a dedup set whose PURPOSE is something else, nothing said
    so, and no test would have noticed if that set were narrowed — precisely the shape the open
    `enabled`-versus-`qualified` question would take. GENERAL FORM: when you find a ruling already
    satisfied, ask WHAT satisfies it; if the answer is a mechanism that exists for another reason,
    make the property explicit at the chokepoint every caller passes through (so a caller added
    later inherits a check it never had to write) and pin it at BOTH levels, saying which is which
    — the end-to-end test passes today and its value is that it KEEPS passing, while only the
    chokepoint test is discriminating. The same slice's reporting half is the recorded
    one-key-two-meanings defect: "we already collect this" and "we judged this and refused it"
    shared one counter, and that is what hid the ruling.
  - **A CREATE-ONLY, KEY-DEDUPED LOADER HAS TWO SKIP REASONS THAT MEAN OPPOSITE THINGS — and the
    entries that look redundant may be the mission (2026-09-07, 227 unreachable catalogue
    entries):** `seed_sources` counted "already in the database" (an idempotent re-run working
    correctly) and "an earlier entry of this same input claims the domain" (a catalogue entry no
    install can ever register) in one `skipped` number, so 227 of 3,429 entries had never been
    registered anywhere, invisibly. THE PART THAT MATTERS IS THE REPAIR DIRECTION: the obvious
    reading is "54 duplicate domains, clean up the data", and measuring refutes it — 108 of the
    227 are in a DIFFERENT language than the surviving sibling; `bbc.com` carries 31 entries and
    the 30 that lose are BBC Arabic, Hausa, Swahili and Persian, `dw.com` shadows DW Arabic,
    Deutsch, Español and Brasil. Deleting them would delete precisely the multilingual breadth the
    language-equilibrium lever exists to balance. So count the loss, ratchet it, and raise the
    identity question (a domain, or a feed) as a ruling rather than taking it — the recovery
    reaches the alias-aware dedup, the restore-merge's domain joins, the qualification overlay and
    the citations tally. RIDER on the split itself, caught by the negative twin: shadowing is a
    property of the CATALOGUE, not of the run, so it must be decided by the input's own first-wins
    rule and never from database state — computed from database state, a re-seed reclassifies a
    permanently-unreachable entry as a healthy idempotent skip and the count silently reads zero on
    every install that has already seeded once.
  - **MEASURING A PROPOSED ITEM CAN TURN IT INTO A NON-ITEM, AND REVEAL THE REAL ONE BEHIND IT
    (2026-09-07):** "a NULL-only backfill migration so existing installs pick up the
    `country_from_title` source-country recoveries" was a plausible, well-scoped item. Run against
    the real catalogue it recovers **0** of the 1,599 entries carrying no explicit country — the
    2026-06-16 batch promoted all 68 `(Country)`-suffix entries into explicit fields and a
    regression guard keeps it that way — so the migration has no subject and building it would
    have been pure risk. The gap it stood in for is real, broader and unmeasured: the seeder is
    create-only, so NO catalogue metadata improvement (country, language, tags) ever reaches an
    existing install. GENERAL FORM: before writing a migration, run its own predicate over the real
    data and count the rows it would touch; a zero is a finding about the item, and asking what the
    item was a proxy for is usually worth more than the item.

  - **A NUMBER THAT DESCRIBES WHAT A FUNCTION DOES MUST BE CAPTURED FROM THAT FUNCTION, NEVER
    FROM A REBUILD OF ITS INPUTS (2026-09-07, the catalogue-collision figure):** the seeder's
    real loss is measured by `seed_default_sources`, which concatenates five catalogue files.
    I re-assembled that list from the same five paths and got **494**; a skeptic re-assembled
    it and got **475**; the truth is 475, because the shipped path loads the CURATED legal file
    while my reconstruction merged the GENERATED one — a 224-entry difference in an input list
    that looked identical at the level of "which files". Spying on the callee
    (`ss.seed_sources = capture`) and driving the real function settles it in four lines and
    cannot drift. This is the recorded "a standalone SQL probe is a lookalike" lesson one layer
    up from SQL: the lookalike axis here is not table stats or ANALYZE state, it is **which
    inputs the production path actually assembles**, and a reconstruction is wrong precisely
    where the function has a detail you did not read. Corollary for the guard: make the FIXTURE
    the capture, so the number can never be pinned against a rebuild again.
  - **A RATCHET SCOPED TO ONE INPUT FILE CANNOT SEE THE CLASS IT NAMES WHEN PRODUCTION READS
    FIVE (2026-09-07, same slice):** the budget pinned 54 domains / 227 entries measured on
    `configs/sources.yml`, and its own docstring named the general class — "adding a second
    entry for a domain the catalogue already claims is silently discarded". Production seeds
    five catalogues, so **248 cross-catalogue collisions sat outside the guard entirely**,
    including 220 that are the whole political-lean catalogue losing to the curated one: 192
    shadowed entries carry a `lean-*` tag the survivor lacks (`cnn.com` loses
    `lean-center-left`), so a vocabulary `src/catalog/taxonomy.py` defines barely reaches the
    database it was written for. The tell is the mismatch between a guard's DOCSTRING (which
    names a class) and its FIXTURE (which names one file); pin the number the production path
    produces, and where a narrower figure is also worth keeping, say which is which rather than
    letting the smaller one stand for the loss.
  - **LOWERCASING THE NEEDLE AGAINST A CASE-SENSITIVE COLUMN IS WORSE THAN NOT NORMALISING AT
    ALL (2026-09-07, `is_disqualified_domain`):** `Source.domain == domain.lower()` reads as
    defensive and is not. The column is compared with SQLite's BINARY collation and
    `POST /api/sources` stores the domain as typed, so a source added as `Example.COM` and later
    disqualified became unrefusable by **every** spelling **including its own** — the
    one-sided normalisation broke the exact-match caller that worked before it. And the failure
    direction is the bad one: a refusal that does not fire looks exactly like a domain nobody
    judged. Normalise both sides or neither; where the stored side cannot be normalised without
    a write-path change, seek the SPELLINGS the caller can legitimately supply (`in_()` over a
    unique index is still seeks, not a scan) and STATE the residual gap rather than implying it
    is closed. The negative twin is mandatory — widening the spellings must not start refusing
    a domain nobody judged.
  - **"IT ALREADY PASSES" AND "IT CANNOT FAIL" ARE DIFFERENT CLAIMS, AND ONLY A PER-TEST
    MUTATION TELLS YOU WHICH YOU WROTE (2026-09-07, same slice):** the new test file classified
    its own tests — the two end-to-end ones as non-discriminating ("their value is that they
    KEEP passing"), the chokepoint as "the only level where the refusal is discriminating".
    Mutating each refusal separately showed one of the two end-to-end tests **fails without the
    change**, because that funnel used to report a disqualified domain under the wrong reason
    and the base commit has no such counter at all. A taxonomy of one's own guards is a claim
    like any other; a mutation matrix is cheap and it is the only thing that measures it.
  - **AN EXACT-DICT ASSERTION ENCODES EVERY FIELD THAT HAPPENED TO BE ABSENT — AND N RED NAMES
    ARE NOT N CAUSES (2026-09-07, the torture suite):** filling in a report field that had
    always been empty broke `test_t6_divergent_merge_full`, which compared the whole plan dict
    and was therefore only ever satisfiable BECAUSE the field was dead — the test had encoded
    the defect. It then broke `test_t2_duplicate_flood_is_idempotent` too, which touches none of
    the changed code: t6 aborts at its assertion **before** its `--commit`, so t2's first
    re-merge became the initial merge and legitimately created rows. **One regression, two red
    names, in a module-scoped fixture chain.** Before triaging a suite diff, ask how many CAUSES
    the failures have — a shared fixture makes the first failure a cause of the rest — and check
    the baseline for each, because here the baseline was green on both and the temptation was to
    read the second as an unrelated flake. The repair belongs in the assertion, not the code:
    compare the fields the test is about, and pin the newly-live field by name.

  - **A REPORT WHOSE EVERY BLOCK DEGRADES HONESTLY HAS THE SAME SHAPE WHEN IT WAS HANDED
    NOTHING — so a shape assertion cannot tell a working member from a broken one
    (2026-09-07, the soak-window bundle member):** the recorded K2 lesson names a degrade
    wrapper becoming the hiding place for the bug it survives, and the FastAPI-sentinel
    lesson names `Query(False)` being truthy when a route is called directly. This is
    where the two meet: a composed report in which each block reports `{measured: false,
    reason}` on failure produces a payload with all the right KEYS whether it got a real
    Session or a `Depends` object, so `assert "window" in payload` passes on exactly the
    defect it was written for. Measured, not reasoned: the mutation that replaced
    `soak_window_report(db=db)` with `soak_window_report()` left the guard GREEN. The
    assertion has to be on a VALUE only the real path can produce — here a `wal_bytes` row
    the test itself inserted, read back out through the member. GENERAL FORM: the better
    your degrade discipline, the weaker a shape assertion is, and the two are related by
    construction rather than by accident.
  - **FILTERING A BUCKETED SERIES TO A SUB-BUCKET WINDOW IS A CHOICE OF WHICH WAY TO BE
    WRONG — pick the direction the hazard makes safe, and disclose it (2026-09-07, same
    slice):** `wal_bytes` is stamped with its HOUR BUCKET, so a snapshot genuinely taken at
    10:45 by a process that started at 10:30 carries the timestamp 10:00. A strict `t >=
    started_at` drops a reading that really is in the window and UNDER-reports the maximum;
    widening the boundary to the containing hour can include up to 59 minutes of a previous
    session. Neither is free. For a GROWTH hazard the under-report is the dangerous half —
    a hidden WAL spike is the thing the series exists to show — so widen, and publish the
    boundary plus the first point's timestamp so a reader can see exactly which reading is
    the borderline one. The general question to ask is not "which is correct" but "which
    error does this metric's failure mode punish".
  - **NOT EVERY CUMULATIVE SECOND MAY BE DIVIDED BY A WINDOW (2026-09-07, same slice):** the
    write gate publishes `total_held_s` and `total_wait_s` side by side and only ONE of them
    is a share of wall time. The gate is exclusive, so at most one holder exists at a time
    and held time is bounded by elapsed time; waiting is summed ACROSS waiters, so on a
    contended gate it exceeds the window and a "share" computed from it would exceed 1.
    Before dividing an accumulated duration by a window, ask whether the thing being
    accumulated can happen in parallel with itself — and pin it, because the symmetry of the
    two field names is exactly what invites the second division.
  - **A MODULE DOCSTRING CAN DESCRIBE A MECHANISM THAT DOES NOT EXIST — and the reader
    auditing the module takes the sentence for the thing (2026-09-07, KPI K6):**
    `src/monitoring/kpi.py` states its own contract in its header — an expensive
    instrument "reports its last persisted value with an `as_of`, or
    `not-measurable-here`" — and NO resolver read a persisted file anywhere. For K6,
    cross-language translation coverage, the channel could not exist at all, because
    `engine_report` is computed on demand, streamed to the caller and never written
    down; so the metric the ring-lifecycle ruling asks the board to WATCH was on the
    board and structurally unreadable, and "joins the KPI board" was satisfied by
    LISTING it. GENERAL FORM: a docstring describing a MECHANISM is a claim of exactly
    the kind the staleness guard distrusts in a status line — grep for the code that
    implements it. The tell sat one screen away: K3's spec says "needs a P0-validation
    report from the operator's live corpus run" while `last_p0_validation_report()` is
    in the tree ready to serve one. THREE RIDERS, each found by a SURVIVING mutation
    rather than by review. (a) **A second-precision clock makes a re-stamp invisible to
    a same-second fixture:** `_now()` is `isoformat(timespec="seconds")`, so recording
    and reading inside one second makes `as_of=measured_at` and `as_of=_now()` the same
    string, and the mutation that re-stamps a months-old measurement as fresh passed a
    test written to forbid exactly that — age the record deliberately (rewrite the file
    with a `measured_at` 30 days old). (b) **Do not overload a sentinel:** reporting a
    real figure under `not-measurable-here` because the bar is a pending ruling puts
    "could not be read" and "read, no bar to judge it against" in one word; an EXISTING
    guard caught it (`not-measurable ⇒ value is None and as_of is None`), a fourth state
    (`measured-no-bar`) makes both honest, and widening a verdict domain owes the twin
    that stops the new state parking a red — injecting BOTH abuses, since the
    single-injector version leaves alive the dangerous one (a figure against a REAL
    bar). (c) **A guard that iterates a condition it never creates is vacuous twice
    over:** "no metric misuses the new verdict" passed with no metric using it AND with
    the selftest's own check ranging over an empty list — create the condition, assert
    the check SAW it (its own `detail` count), then feed it the abuse. FOURTH, on the
    CONSUMER: two snapshots quoting ONE persisted measurement are not two agreeing
    measurements — `kpi_diff.classify` compared values only, so an unmeasured cycle read
    as `unchanged`, a fabricated stability finding on precisely the metrics a persisted
    value exists for; it keys on the `as_of` now (`same-measurement`), never on the
    value, because keying on the value would hide two genuine runs that agree.
    **AND THE SIBLING, same session:** `scripts/generate_wikidata_rings.py` said its
    output "augments" the live ring file; it has always REPLACED it and its default
    `-o` IS that file, so an ordinary seed run was one command from deleting 684
    hand-vetted rings with no error and no diff to notice (the refusal now fires BEFORE
    the network run, so a refused pass costs no Wikidata calls). Where a script's prose
    and its `write_text` disagree, the prose is what people act on. ONE MORE, from
    building `--refresh` on it: batching `wbgetentities` turns a 684-ring refresh from
    684 requests into 14 (measured offline against the real file), and it is only safe
    because a QID ABSENT from a batch response is re-fetched ALONE before classification
    — a truncated reply and a deleted item are opposite facts, and reading the first as
    the second manufactures upstream drift out of a short answer.
  - **A `git worktree` BASELINE RUN SILENTLY TESTS *HEAD* UNDER AN EDITABLE INSTALL — so the
    strongest possible excuse for a regression ("the base is red too") is available for free
    and is false (2026-09-07, the t6 torture failure):** the discipline is right — before
    calling a red test yours, run it on a clean base and diff. `git worktree add --detach
    $SP/base-wt <sha>` then `pytest` inside it duly reproduced the failure at the merge-base,
    which would have filed a real regression as pre-existing. It reproduced because
    `pip install -e .` leaves a PATH HOOK that resolves `src` back to the ORIGINAL repo, and
    this suite drives SUBPROCESSES (`tests/torture_helper.py`) that therefore imported the
    mutated tree no matter which directory pytest ran in. With `PYTHONPATH=$SP/base-wt` the
    base is GREEN and the failure is mine. TWO RULES. (a) Any baseline run in a worktree must
    set `PYTHONPATH` to that worktree and PRINT which tree it resolved — the recorded "a
    baseline diff must prove the head side ran the changed tree" lesson, pointing the other
    way: here it is the BASE side that must be proven. (b) The tell is a base that reproduces
    a failure whose mechanism you can trace to a line you just wrote; when the story and the
    baseline disagree, suspect the baseline's imports before believing it.
  - **A LOCAL THAT SHADOWS A FIXTURE VALUE THE TEST STILL NEEDS IS A `str(dict)` HANDED TO
    SOMETHING PATH-SHAPED — and a module-scoped fixture then reddens a LATER test for a
    reason that has nothing to do with it (2026-09-07, same failure):** `art` held the
    artifact PATH; an amendment reused it for the articles plan dict four lines above
    `_run(a, "merge", str(art), ...)`, so the helper was handed
    `"{'new': 2, 'duplicate': 1, 'conflict': 0, 'samples': [...]}"` as a filename. The
    recorded shadowing lesson is about a long `src/` function and mypy catching it; mypy does
    not check tests, and in a 20-line test the two uses ARE on screen together and it still
    happened. THE TELL IS THE ERROR TEXT: a `FileNotFoundError` whose path is a stringified
    dict names the shadowing directly — read the failure's own words before opening the
    module it seems to accuse. AND THE CASCADE IS THE EXPENSIVE HALF: the `corpora` fixture is
    `scope="module"`, so t6 dying before its `--commit` left a later idempotency test looking
    at an unmerged corpus and failing on its own terms. Two red tests, one cause; before
    diagnosing the second failure in a module-scoped file, check whether an earlier test
    aborted mid-setup.
  - **A ROOT-GUARDED SKIP CAN MAKE A REAL ASSERTION UNREACHABLE, AND ONLY A SURVIVING MUTANT
    SAYS SO (2026-09-07, the 0600 env file):** `test_the_env_file_is_owner_only` skipped under
    `os.geteuid() == 0` by analogy with a sibling that legitimately does — and the two are
    different claims. Root ignores mode bits when it WRITES (so "an unwritable folder is
    refused" really is untestable as root), while the mode a file CARRIES is set and read back
    exactly as for any user. In a root sandbox the guard therefore never ran, which is how a
    mutation removing the `chmod` came back green. GENERAL FORM: a skip guard is a claim about
    what the environment makes unobservable; check it against the specific assertion rather
    than the neighbouring test's. COROLLARY, and a case of the recorded "a surviving mutant may
    be a finding about the MUTANT or the CODE": once the skip was gone the mutation STILL
    survived, and measuring said why — `tempfile.mkstemp` already creates the file 0600, so a
    defensive `chmod` after it cannot change an outcome and cannot be killed by any fixture.
    Kept anyway, with the measurement written into the comment, because it states OUR
    requirement rather than inheriting the stdlib's; the comment is what stops the next matrix
    re-finding it and someone writing a vacuous test for it.
  - **`t\("..."\)` ALSO MATCHES THE TAIL OF `createElement("button")` (2026-09-07):** a guard
    harvesting a page's translatable literals to check them against all twelve locales failed
    on `button`, which is not chrome and is not translatable. Any regex for a one-or-two-letter
    function name needs an identifier boundary (`(?<![A-Za-z0-9_$.])t\(`), because short names
    are substrings of longer ones far more often than they look. Same family as the recorded
    non-unique-needle trap, at the level of the token rather than the string.
  - **AN AUDIT THAT COUNTS A PLACEHOLDER AS CHROME IS RIGHT — the fix is a FRAME, never an
    exemption (2026-09-07):** the untranslatable ratchet flagged `placeholder="/media/drive"`,
    an example path. Translating a path is meaningless, and adding a skip rule for it would
    have blinded the ratchet a little for everyone. Making it `For example: /media/drive` keys
    the SENTENCE while the path stays data inside it — the frame-translates-data-does-not
    discipline — and a locale that wants a Windows example can now supply one. The Arabic value
    wraps the path in `U+2068`/`U+2069`, because a punctuation-joined LTR run inside RTL text
    renders in visual order otherwise.
  - **A PUBLIC FUNCTION'S GUARDS CAN LIVE ENTIRELY IN ITS CALLER, AND THE DOCSTRING WILL SAY
    OTHERWISE (2026-09-07, the artifact file-member placement — found by reading my own diff
    adversarially, not by a failing test):** `place_artifact_file_members` documented the path
    guards it relies on, and every one of them was enforced upstream in
    `_require_safe_manifest_names` — correct for the restore path that reaches it, and false
    for the function itself, which is public and joins `name` onto the staging dir to FIND the
    bytes. An unguarded `name` is therefore an arbitrary READ copied into the live data
    directory under an innocuous destination name, reachable by any second caller and by any
    future one. RULE: a guard that has to be reached from somewhere else is not a guard on this
    function — re-check at the boundary you are documenting, and say in the docstring that it is
    a re-check rather than implying it is the only one. COROLLARY, and the reason it is here:
    the same pass reported `unknown category` for an entry whose category was fine and whose
    PATH was hostile — the wrong-actor mislabelling this very session had just fixed in the
    pre-swap barriers, written again three commits later, one subsystem over. Every refusal
    carries its own reason, and "a lesson recorded against one assertion does not propagate
    itself to the one beside it" applies to lessons you wrote yourself an hour ago.
  - **A GUARD ADDED EARLIER IN A CHAIN MAKES THE LATER GUARDS UNREACHABLE BY THEIR OWN TESTS —
    the test keeps passing and stops meaning anything (2026-09-07, same slice):** the
    containment belt (`is_relative_to`, never a string prefix) was covered by a fixture whose
    `rel` was `../live-old/x`. Adding the `rel` traversal guard in front of it made that fixture
    refuse one step EARLIER, so the belt was never executed and its test proved only that
    something refused. The only shape that still reaches a containment check once traversal is
    refused upstream is a SYMLINKED root — a `rel` with no `..` in it at all, resolving out of
    its category because the category directory is a link. GENERAL FORM: after inserting a
    guard, re-ask which fixtures still reach the guards BEHIND it; a defence-in-depth layer that
    nothing can reach is decoration, and the mutation matrix is what says so (removing the belt
    reddened exactly one test — the new one).
  - **`object()` IS NOT A WEAK TEST DOUBLE, IT IS ONE THAT CANNOT DESCRIBE ANY REAL VALUE — and
    the pressure it creates lands on production code (2026-09-07, same slice):** six tests built
    their staged-artifact double as a bare `object()`, so adding one field to the real
    `StagedArtifact` raised `AttributeError` in six places at once. The one-line fix is a
    `getattr(staged, "file_members", [])` in the production path — which reads as defensive and
    is a permanent hole, because every real object HAS the field and the only caller that could
    lack it is a fixture. Make the double real instead (one helper building the actual
    dataclass); the tests then also stop being able to describe an artifact the engine could
    never produce. Same family as the recorded resolver-stub lesson, one step further down: there
    the double omitted a field, here it could not have had one. **AND FIXING THE SIX I COULD SEE
    WAS NOT FIXING IT — I wrote this lesson and the full suite then found three more an hour
    later.** They live in `test_import_phase_progress.py`, a file about ETA counters that no
    search for "backup" reaches, and a tenth in a file I had written MYSELF that same day stayed
    green only because its own double raises before the job reads that far — so it would have
    bitten the NEXT field instead of this one. The enumeration to run is not "which backup tests
    are there" but a grep for the PATCH TARGET (`read_volume_backup`) across the whole test tree,
    and the durable close is a comment-stripped guard with an anti-vacuity floor (assert it finds
    the doubles at all), because the next such file will be about something else again.
  - **TWO SESSIONS CAN FIX ONE DEFECT TWO WAYS, AND GIT MERGES BOTH WITHOUT A CONFLICT
    MARKER ANYWHERE NEAR THE DAMAGE — the assignment operator is the only thing that
    hid it (2026-09-07, merging #1020 with main's #1018/#1019):** this branch and main
    independently found the same defect (the merge's `samples` were read AFTER their own
    INSERT, with the predicate that INSERT had just falsified, so the list was empty on
    every restore ever taken) and fixed it differently — this side moved the read BEFORE
    the INSERT, main's added `_new_row_samples`, reading back from `merged_rows`. Git
    reported three tiny conflicts, each with an EMPTY `HEAD` side, because the two fixes
    touch DIFFERENT LINES: my loops merged in as ordinary context and main's assignments
    merged in as additions, so the resolved file ran both. It was harmless ONLY because
    main's line is `r.samples = ...`; had it been `.extend(...)` — an equally natural way
    to write it — every sample would have been listed twice, in a report whose whole
    purpose is to say what an import added. GENERAL FORM: when a conflict hunk has an
    empty side, that is not "nothing to decide" — it means the other side ADDED something
    where you CHANGED something nearby, so read what your side already does in that
    function before taking theirs; a semantic double-fix leaves no marker at the place it
    hurts. THE TIE-BREAK, once both were on the table, was not seniority but which claim
    each could support: a restated predicate is a second copy of the INSERT (the
    `articles` INSERT additionally joins `temp.map_sources`, so a restatement could name
    a row the INSERT then skipped), while a provenance read reports what LANDED and
    cannot drift from the statement. Both sides' test files were kept — their fixtures
    differ (an empty local corpus and a re-merge, against shared-row discrimination) and
    both pass against the one surviving implementation — but the LOSING side's docstring
    had to be corrected in the same commit, because it described the mechanism that lost
    and would otherwise have read as a live claim about how the code works.
  - **A DRIVER IS NOT A TOOLKIT — a JIT path silently turns a runtime dependency into a
    BUILD dependency, and it fails at the END of initialisation with the expensive resource
    already committed (2026-08-09, ten dead vLLM starts; retired to `SHIPPED_LOG.md`
    2026-09-07):** vLLM 0.26 selects FlashInfer for top-k/top-p sampling, FlashInfer
    JIT-compiles that kernel on first use, and first use is `warmup_kernels` at the very end
    of engine init — so on a machine with the NVIDIA driver and **no CUDA toolkit** it died on
    `Could not find nvcc and default cuda_home='/usr/local/cuda' doesn't exist`, ~78 s in,
    with the weights already resident. That reads as "it loaded and then unloaded", never as
    "it never started", which is why the host-RAM hypothesis held for ten attempts and was
    wrong (`journalctl -k` was empty, 5.5 GB free, no OOM kill, and `enforce_eager` is on
    below 10 GB so no graph capture happens). Inference needs only the driver. GENERAL FORM:
    when a component is chosen at RUNTIME because a package is merely importable, ask what
    that component does on FIRST USE — the cost of a JIT path is paid late, after the
    allocation that makes the failure look like a regression somewhere else. Fixed by
    `_server_env()` setting `VLLM_USE_FLASHINFER_SAMPLER=0` whenever `cuda_toolkit_present()`
    is false (`src/llm/vllm_lifecycle.py`), an operator's explicit setting still winning.
  - **A ONE-LINE FLIP OWES A DISCLOSURE THAT IS TRUE ON BOTH SIDES OF IT — and nothing about
    flipping a boolean will tell you the wording did not follow (2026-09-07, the Bulletin's
    open question 4):** the ledger had recorded for months that answering it was "one constant
    with exactly one read … a one-line change, not an audit", and the code half was exactly
    that. The other half was not: the caveat beside the constant said the deterministic
    document "is withheld only because the feature is gated as a whole", which became FALSE the
    moment the flip landed — a refusal an operator never received, printed in the one place
    they would go to understand why. A guard counting the READS cannot see it, and neither can
    a passing suite, because both states are internally consistent. **THE MECHANISM THAT MAKES
    BOTH TRUE AND KEEPS THE GUARD MEANINGFUL:** read the constant ONCE into a local at the top
    of the function and derive the verdict, the reason AND the caveat from that local — a local
    is not a second place to flip, it is the same place read once — then pin BOTH states with
    tests that monkeypatch the constant, plus the twin asserting the shipped state does NOT
    claim the refusal. Three mutations redden: the caveat pinned to either state, and the
    unmeasured-probe path claiming a gate it never measured. **THE SECOND HALF IS SHARPER AND
    GENERALISES FURTHER: when one gate answers two questions, the verdict is two keys.**
    `available` had to become the DOCUMENT verdict with `narration_available` beside it, because
    below the bar those are opposite answers and a caller reading a single `available` would
    have to guess which one it got — the recorded one-key-two-meanings defect, in a policy
    flag. And the key that is a HARDWARE FACT must read the POLICY constant NOWHERE, or
    flipping the policy silently changes what the app claims about the machine; the mutation
    that makes the narration verdict read the constant reddens by name.
  - **A WORKER WHOSE PER-ITEM FUNCTION DEGRADES INSTEAD OF RAISING WILL FINISH `complete` ON A
    DEAD BACKEND — the abort-to-done defect wearing a graceful-degrade hat (2026-09-07, the
    Bulletin's narration job):** `narrate_story` never raises; a model failure resolves to the
    deterministic template with the reason recorded, which is right for the document and is
    precisely what makes a naive loop walk every story, write a template for each, advance its
    cursor and end `done`. Nothing in the run looks like a failure. The design record had
    warned against exactly this three fixes running, and the warning is not enough on its own
    because the defect arrives through the CORRECT behaviour of the callee. **THE FIX IS TO
    CLASSIFY THE FALLBACK REASON**, not to make the callee raise: an outage does not advance
    the cursor, is retried with backoff, and after N in a row the run RAISES so the job state
    is genuinely `error`. **THE NEGATIVE-SPACE TWIN IS MANDATORY AND IS WHERE THE FIX GOES
    WRONG:** not every fallback is the backend. A story whose articles carry no readable text
    fails for a reason retrying cannot change, so treating every fallback as an outage stalls
    the whole run on one empty item, for ever, having looked conservative. Both directions need
    a test, and the mutation for each reddens a different one.
  - **A MUTATION IS ONLY EVIDENCE ABOUT THE SUITE THAT COULD HAVE SEEN IT (2026-09-07):** a
    mutation deleting a per-card disclosure line from the renderer SURVIVED, run against the
    translation-coverage suite — and coverage genuinely cannot see it, because a line the
    renderer stopped emitting is a line the translator is never asked for, so the catalog stays
    100% complete while the sentence vanishes. Re-pointed at the suite that claims the property
    it reddened immediately. The recorded `pytest -k` lesson says a selector matching zero tests
    reads like a pass; this is the same family one level up, where the selector matches plenty
    of tests and none of them is about the thing. Before reading a survival as a finding, name
    the test that would have to fail. **AND THE FINDING UNDERNEATH IS WORTH ITS OWN LINE: a
    translation-completeness guard is blind to a deleted render line by construction**, which
    makes a behavioural render assertion the twin every new disclosure line needs — with its own
    negative-space half, since a record written before the field existed must get NO line rather
    than a fabricated answer.
  - **AN EXCLUSIVE PERIOD END DOES NOT MAP ONTO EVERY CONSUMER'S CLOCK, AND THE TWO ARE ONE DAY
    APART (2026-09-07, the card producers' period seam):** handing producers an `as_of` anchor,
    `on_the_horizon` looks FORWARD and takes `end` directly — the first instant after the period
    is exactly "what was on the horizon when this closed" — while `through_time` is an
    anniversary on a CALENDAR DATE and must take `end - 1 day`, the period's own last covered
    day. Anchoring it on `end` picks the day AFTER the edition's last, finds a different set,
    and every ordinary fixture still passes. A fixture whose articles sit on the last covered
    day discriminates them; nothing else does. GENERAL FORM: when one anchor is threaded through
    several consumers, ask each one what its own clock MEANS before passing the value, and write
    the fixture that separates the two readings — a shared parameter name is not a shared
    semantics.
  - **A SURVIVING MUTANT CAN SURVIVE FOR A REASON UNRELATED TO THE PROPERTY — check WHY the
    fixture failed before writing a better assertion (2026-09-07, the same seam):** the mutant
    that made a derived anchor override an explicit `today` survived a test written for exactly
    that precedence. It survived because the mutated code returned `[]` too — for want of a
    trending term inside the anchored window, not because the precedence held. The fixture had
    seeded its mentions two months before the period, so BOTH versions took an early return and
    the assertion could not tell them apart. Moving the mentions inside the window made the two
    diverge and the mutation reddens by name. The recorded rule that the discriminating input is
    never the obvious example has a corollary: when a mutant survives, run the mutated code and
    find out which branch it took, rather than assuming the assertion is too weak.

- **A TIMING HARNESS THAT DOES NOT ASSERT THE WORK HAPPENED CAN REPORT A PASS FROM A SERVER
  THAT DID NOTHING (2026-09-07, S3.6, caught before it could lie):** the concurrency
  reproducer for the event-loop freeze put a slow handler in flight and measured how long a
  second, trivial request took. Its FastAPI mini-app was built inside the test function, in a
  test file carrying `from __future__ import annotations` -- so every annotation was a STRING
  that FastAPI resolves against the MODULE globals, and `Request`/`Session` were imported
  inside the function. FastAPI could not resolve `Request`, silently demoted `request` to a
  QUERY PARAMETER, and answered **422 without ever calling the handler**. The measurement
  would then have been "the second request was fast" -- a green run produced by a server that
  never did any work at all, in the direction that confirms the fix. What caught it was an
  `entered.wait(timeout=5)` latch set INSIDE the handler and asserted BEFORE the clock
  started. **GENERAL FORM: a harness that measures the effect of some work must independently
  assert that the work RAN.** The failure mode of a silently-skipped body is indistinguishable
  from the success it is trying to demonstrate, and it fails toward "pass". The same shape as
  the recorded `str.replace`-with-an-absent-needle mutation (a no-op whose green run reads
  exactly like a dead guard) -- one layer up, in the fixture rather than the mutation.

- **51 OF 56 `async def` HANDLERS AWAITED NOTHING AT ALL (2026-09-07, S3.6):** the crash brief
  recorded 56 DB-touching `async def` handlers as a freeze risk. Parsing their bodies before
  converting them showed that 51 contained no `await`, no `async for` and no `async with` --
  they were not handlers that needed the loop and used it wrongly, they were handlers where
  `async def` is simply the shape people type. Of the 5 that did await, one
  (`import_pdf_folder`) awaited ONLY its own `run_in_threadpool` hop, i.e. it went to the loop
  purely to bounce straight off it. **GENERAL FORM: before designing a fix for a defect class,
  count what the instances actually ARE.** The remedy for "async by habit" is a census guard
  with a named allowlist (a new instance must argue for itself); the remedy for "needed async,
  used it wrongly" would have been code review. The measured shape chose the mechanism, and it
  is the cheaper one.

- **"IT IS ONLY ONE ROW" IS NOT A REASON TO TOUCH THE DATABASE ON THE EVENT LOOP (2026-09-07,
  S3.6):** `import_newsletters` was fixed on 2026-07-17 to run its heavy `ingest_emails` call
  through `run_in_threadpool`, and a test has asserted since then that it "runs off the event
  loop". It still called `_get_newsletter_source(db)` -- a get-or-create that **COMMITS** --
  and `db.rollback()` on its error path, both on the loop. A commit waits on the single-writer
  gate like any other commit, and the field measured gate waits of **6,236 s**; so a one-row
  insert can block every request in the process for as long as the gate is held. **GENERAL
  FORM: when a fix moves "the heavy part" off a contended resource, the leftovers inherit the
  same WORST case, not the same average one -- their size bounds their typical cost, never
  their blocking cost.** The rule a guard can actually hold the line on is "the session is
  never touched on the loop", not "the big ones are not"; the AST guard added here asserts
  exactly that, because a threshold nobody can state is a threshold nobody can test.

- **A HALF-SHIPPED NUMBERED SLICE IS INVISIBLE FROM BOTH DIRECTIONS (2026-09-07, found by the
  S3.6 staleness sweep):** crash-brief slice S3.6 had two halves -- the lock-state cache and
  the 56-handler conversion. PR-10 shipped the cache; its commit message describes the cache
  and nothing else, and **no `S3.6` row was ever written to `shipped.csv`**. The result read
  both ways at once: the shipped half looked unshipped (the prompt still asked for it, and it
  was already there with both belts), and the unshipped half looked done-by-association to
  anyone who found the cache and stopped. **GENERAL FORM: when a PR ships PART of a numbered
  slice, the CSV row must name WHICH part and what remains** -- the slice id alone asserts the
  whole thing. This is the inverse of the stale-PENDING-banner failure the 2026-09-06 analysis
  named: there a doc claimed less than the tree held; here a commit claimed a slice id and
  delivered half of it.
  - **A LIST BOUND THAT THE RULING'S OWN LOAD-BEARING ROW RIDES ALONG WITH IS SAFE ONLY BY
    ACCIDENT — and the ordering that saves it is a property of the data, not of the code
    (2026-09-07, the concept map's country cap):** `ring_country_split` ended with a bare
    `rows[:limit]` over a GROUP BY ordered by article count, `limit` defaulting to 40. The
    unlocated ("not mapped") bucket is one of those rows — and it is the row the 2026-07-18 §D
    ruling names BY HAND as "often the largest, and it must be investigable, never a dead end".
    It survived every field run because it HAPPENED to be the biggest; on any concept carried by
    more than 40 countries with a smaller unlocated share it falls outside the window and the
    ruled-clickable drill simply is not in the payload. The shipped catalog carries **189 distinct
    source countries**, so the bound is reachable rather than theoretical — which is the number
    that turned "could this happen" into "this happens". TWO GENERAL RULES. (a) When a ruling
    singles out one row as load-bearing, check whether it travels through the same bound as the
    ordinary rows; if it does, split it out BEFORE the bound so the guarantee is structural, and
    the fixture that proves it must make that row the SMALLEST — a fixture using the field's usual
    shape (largest) survives any limit and the guard passes for free. (b) The same call had the
    anti-capping defect in its purest form: no exact total was published, so the only figure a
    reader could count — the polygons, which the frontend announced as "N countries" — WAS the cap.
    The fix cost nothing, because a GROUP BY has already materialised every bucket: `len(located)`
    is exact and free, and only the LIST needed bounding. Before adding a `[:limit]` to a
    fully-materialised aggregate, ask what the caller will count, and publish the number beside the
    list rather than leaving the list to stand in for it.
  - **A MIN GATE EXPRESSED AS A ROUNDED PERCENTAGE GROWS SLACK AS ITS DENOMINATOR GROWS — at 3040
    keys, exactly one missing translation is invisible (2026-09-07, measured while adding one
    key):** `scripts/i18n_report.py --min 100` is one of the three blocking i18n gates and computes
    `pct = round(100 * covered / n, 1)`. At today's n = 3040, a locale missing ONE key scores
    99.967 → **100.0**, prints "complete 3039/3040 (100.0%)" and exits 0. Measured, not reasoned:
    deleting the newly-added key from `fr.json` alone left the gate green. This is the recorded
    "a gate you expect to be interesting never says anything interesting" family with a new
    mechanism — the gate is not blind, it is ROUNDED, and its blind spot WIDENS with every key the
    project adds, so a check that was exact at 500 keys silently stopped being exact. GENERAL FORM:
    any threshold applied to a rounded ratio has a tolerance equal to half the rounding step times
    the denominator, so state it in ITEMS ("this gate cannot see 1 missing key") rather than in
    percent, and prefer comparing the counts. Not fixed in the slice that found it, deliberately:
    it changes a shared blocking gate and belongs to its own reviewed change — but measure the
    cost of tightening before deferring it, because all 11 non-English locales are currently at the
    full count, so today it would redden nothing.
  - **`grep --include` IS A WHOLE-INVOCATION FILTER, NOT A POSITIONAL ONE — naming files of another
    type beside it searches NONE of them, and reports a confident nothing (2026-09-07):**
    `grep -rn "<needle>" src/static/*.js src/static/*.html src/ --include=*.py` looks like "search
    these JS and HTML files, plus the Python under src/". It is not: `--include` applies to every
    path in the call, so the JS and HTML files were filtered out and the command searched only
    `*.py`. It printed nothing, and I concluded from that silence that a translated honesty string
    was keyed in twelve locales and rendered NOWHERE — a finding about an orphaned translation,
    written up as such, when the sentence is sitting in `index.html` and guarded by a test. The
    tell was available and I walked past it: the same run reported the string missing from files I
    had just been told it was in. Same family as the recorded `cmd | tail` exit-code trap and the
    `pytest -k` selector matching zero tests — a check that reports success (or emptiness) without
    having examined what it claims to. RULE: put `--include`/`--exclude` only on a bare recursive
    search, and when a grep over explicitly-named files returns nothing, re-run it on ONE of those
    files alone before believing the absence.
  - **A GUARD ANCHORED ON A LITERAL OPERAND LIST REDDENS WHEN YOU ADD AN OPERAND BESIDE THE
    ONE IT IS ABOUT — and the tell is that it fails against code where its own named property
    is untouched (2026-09-07, the ring-map dumbbell):** `test_dumbbell_wired_into_ring_map_detail`
    asserted the string `"langs + langBd + unlocNote + dumb + tbl"`. Inserting a SIXTH,
    unrelated operand (a truncation disclosure) between two of them reddened it — while the
    dumbbell it is named for was wired exactly as before. That is the recorded
    "anchored on a landmark that merely coincided with the property" class, in the cheapest
    possible form: a concatenation's operand ORDER is not the claim, membership is. Re-anchor
    STRUCTURALLY — select the composed render assignment (not the `= ""` resets that clear the
    block) and assert the term is one of its operands — which is strictly stronger, since it
    still fails when the term is dropped and stops failing when a neighbour is added; pin BOTH
    directions, because a re-anchor that only relaxes is indistinguishable from deleting the
    guard. **THE ROOT CAUSE IS THE CHEAP HABIT I SKIPPED:** before changing any string in
    `src/static/`, grep the TEST tree for it. The ledger already carries that rule twice (the
    `async def view_article` rename, the `did not grow` reason string) and I paid for it again
    by running only the suites I had touched; the full run is what caught it, ~20 minutes after
    it could have been caught in seconds. The grep is not "which tests are about this file" —
    it is the literal string, because the file that anchors on it will be named for something
    else entirely (here: a dumbbell chart).

  - **A PREMISE COPIED THREE TIMES IS STILL UNVERIFIED, AND EACH COPY MAKES IT READ AS BETTER
    SOURCED (2026-09-07, the dump-size endpoint):** "the dump date's `dumpstatus.json` lists
    every edition at once, so it is ONE request, not N HEADs" was written into an
    assistant-authored docstring in `src/wiki/dump_sizes.py`, copied verbatim into the Open
    queue as the ruled REMAINING work, and copied again into the prompt derived from the
    queue. By the third copy it had the shape of a settled fact with three citations, and
    **nobody had read the endpoint** — the sentence has one origin and two echoes. The
    recorded lesson that "an agreement between two methods that share a defect is not
    corroboration" is the same shape one level up, in prose: agreement between two DOCUMENTS
    that share an origin is not corroboration either, and the tell is that none of them says
    who looked. Two cheap checks settle it without the network. **Ask what the codebase's own
    behaviour implies:** every `dumps.wikimedia.org` URL this repo builds is per-edition
    (`/<code>wiki/latest/…`), which is evidence AGAINST a single cross-edition document.
    **And probe the host before planning around it:** `curl -o /dev/null -w '%{http_code}'`
    returns `000` here against `200` for `pypi.org`, so the shape was not checkable in this
    sandbox at all. The honest outcome is to ship the part that does not depend on the
    premise (one CONSENTED, bounded, politeness-spaced read over the operator's actual
    selection), park the optimisation with the evidence, and correct all three copies —
    building on the premise would have shipped a fabricated endpoint, and a 404 degrading to
    "sizes unavailable" is the kind of failure nobody ever traces back to a docstring.
    GENERAL FORM: when a plan states a fact about a THIRD PARTY's endpoint, file format or
    API shape, find where the sentence was FIRST written and whether that author read it; a
    fact with no reader is a guess with a citation trail.
  - **A CONSENT GATE ON THE ACTION IS NOT A CONSENT GATE ON WHAT THE UI DOES TO HELP YOU
    DECIDE (2026-09-07, same slice):** UI invariant #14 lists "dump start" among the gated
    actions, and `startDump` duly passes `ensureOnline`. The button beside it — "Estimate
    size" — fired a live HEAD to the same host with no gate at all, because it reads as
    *looking*, not as *doing*. Every sibling action on that surface (watched-page add, OSM
    region download, statistics fetch) has the popup; the preview did not, and it is the one
    that runs FIRST. GENERAL FORM: after gating an action, enumerate what the surface does
    BEFORE it — a size estimate, a preview, a validation, a reachability check, an
    autocomplete — because those egress too and are exactly where a gate gets forgotten. THE
    SECOND HALF, found in the same read: the ungated probe swallowed every failure into one
    `"size check failed"`, so airplane mode (a fact about THIS machine, nothing sent) was
    indistinguishable from a dump host that would not answer — the standing
    one-key-two-meanings defect, and it points an operator at someone else's server for their
    own setting. A refusal by the kill switch must be named as such wherever it can surface.
    THIRD, cheap and worth the grep: the probe read `dumpSelected()[0] || "en"` from a
    MULTI-select picker, so it reported one edition's size as though it described the
    selection and silently invented a default when nothing was chosen. A control whose input
    is a collection and whose implementation indexes `[0]` is a shape to grep for.
  - **CHECK A PRESCRIBED COLUMN AGAINST THE FACT'S CARDINALITY, NOT ONLY AGAINST THE CODE
    (2026-09-07, "per-mention revid anchoring"):** the recorded rule says a plan written from
    measurements is trustworthy about the DEFECT and not automatically about the REPAIR, and
    names the module docstring as where the previous reasoning lives. There is a second,
    faster check that needs no archaeology: ask what the value's cardinality is against the
    grain of the table the plan names. Here the defect was exactly as recorded (the revid was
    received and dropped, recoverable for watched pages only by reading a DIFFERENT fact and
    not at all for dump ingests), and the remedy named `keyword_mentions` — but every mention
    of an article is produced by ONE indexing pass over ONE text, so each would have carried
    an identical value: millions of copies at field scale, on the largest table in the store,
    of a fact with one distinct reading per article. That is the recorded "a term whose count
    equals the article count is a fact about the channel" tell, applied to a schema rather
    than to a keyword index. The fact belonged one level up, on the article, written in the
    same transaction as the text it describes so the pair cannot drift. GENERAL FORM: before
    adding a column, count how many rows would hold the same value for one entity; if the
    answer is "all of them", the column is on the wrong table — and say so in the commit,
    because deviating from a recorded shorthand silently is how the next reader re-files it
    as unbuilt.
  - **AN INVERSE VERIFIED BY ROUND TRIP BEATS ONE VERIFIED BY A CHARACTER RULE, AND THE
    CHARACTER RULE FAILS TOWARD SILENCE (2026-09-07, `wiki_page_ref`):** turning a canonical
    URL back into the `(wiki, title)` it was minted from needs a guard, since a hostile
    `canonical_url` must never become a wiki lookup. My first version listed what a path may
    not contain — and refused every title containing a slash, which is a real and ordinary
    shape (`A/B testing`, `OS/2`, `AC/DC`), because the forward function's `quote` leaves the
    slash alone. Nothing would have failed: those articles would simply never have been
    offered their history link, an invented absence on a surface whose whole point is that an
    absence is honest. Re-minting the URL from the candidate pair and requiring it back
    byte-for-byte accepts EXACTLY what the forward function can produce, by construction —
    no hand-maintained list to keep in step with `quote`'s `safe` set, and nothing this app
    never minted can pass. TWO RIDERS. Test the shapes a character rule gets wrong
    (`A/B testing`, `100% renewable`, `C++`, non-Latin titles) rather than the ones it gets
    right, or the parametrisation proves the easy half. And a round trip legitimately accepts
    a page genuinely titled `../../etc`, which is correct where the result is a bound DB
    lookup key and a traversal the moment someone joins it onto a directory — so say in the
    docstring which of the two it is, rather than leaving the next caller to assume.
  - **A SOURCE GUARD CANNOT TELL A LIVE BRANCH FROM A DEAD ONE — the identifier it looks for
    lives INSIDE the branch (2026-09-07, the tracked-changes header):** the recorded traps
    cover a needle that is not unique, a needle satisfied by a comment, and a slice that
    over-runs. This one is none of those: the guard was correctly scoped to
    `loadWikiTC`, comment-stripped, and asserted `d.page.title` — the exact expression that
    fills the panel's header from the server's answer when a `?wikitc=` deep link supplies
    only a page id. Neutering the branch to `if (false)` left the assignment sitting inside
    dead code and the guard GREEN. The class is general and has no source-level fix: for ANY
    guard of the form "X is read from Y", X necessarily appears inside the conditional that
    reads it, so disabling the conditional cannot change what the file contains. Only
    behaviour discriminates. Driving the real function in node cost about forty lines of DOM
    shim (`$` returning recording objects, an `api` that yields a fixture) and paid for
    itself immediately, because the same harness then pinned the five things the view's
    honesty actually rests on — the "showing N of M" window disclosure, the visible caveat,
    the flag-aware empty state, a revision with no stored diff saying why, and a failed read
    replacing the loading placeholder rather than leaving it up — each of which redden under
    their own mutation. This is the recorded "a test of a HELPER is not a test of its WIRING"
    lesson in mirror image: there a behavioural test missed the wiring, here a source test
    could see the wiring and not whether it runs.
  - **THE RECORDED REGEX BOMB HAD A SECOND, LARGER DISGUISE IN THE SAME FUNCTION — and the
    test written for the first one is what found it (2026-09-07, `plain_from_wikitext`):** the
    2026-08-05 lesson names `OPEN.*?CLOSE` and asks for the shape to be grepped. Grepping for
    that literal shape found three patterns in the wiki strip and fixed them (13.4 s → 0.003 s
    per 400 KB of unclosed-`<ref>` spam). It also MISSED six more in the same function, because
    they are written `OPEN[^X]*CLOSE`: the character class consumes to end-of-document and then
    backtracks position by position, which is a different mechanism with the same N² cost.
    Measured, 100,000 → 400,000 chars: `[[File...]]` 1.749 s → **28.035 s**, `[[target]]`
    1.721 → 27.398 s, `[url label]` 1.420 → 22.525 s, `<[^>]+>` 0.154 → 2.381 s — the ones I
    had not touched were an order of magnitude worse than the ones I had. **What found them was
    a TEST FAILING AGAINST THE FIX**: a bound on the comment shape came back 62× and the
    tempting move was to widen the bar; measuring instead showed the comment BLOCK strip was
    already linear and the cost was `<[^>]+>` downstream. GENERAL FORM: grep for the COST, not
    for the syntax — "an opener that can scan to end-of-document when its closer is absent"
    covers `.*?`, `[^X]*`, `\S+` and any other greedy class, and the syntax you grepped for is
    the one you already knew about. And when a bound you wrote fails, measure what is actually
    slow before touching the bound: the recorded rule is to raise the INPUT when the noise
    scales and change the CLAIM when it does not, and there is a third case — the bar is fine
    and the measurement is about something else entirely. RIDER on the fix's shape: a
    scaling RATIO (4× the input must not cost ~16× the time) is the right assertion here, not an
    absolute second count, because the defect is that the two diverge by an order of magnitude
    while an absolute bar is a bet on the runner's speed.
  - **A MUTATION MATRIX THAT NAMES A TEST FILE THAT DOES NOT EXIST REDDENS ON EVERY MUTATION,
    AND READS AS A PERFECT RESULT (2026-09-07):** the recorded trap is `pytest -k` selecting
    ZERO tests and printing nothing. This is its louder twin and it is more convincing: naming a
    non-existent file makes pytest exit non-zero with a COLLECTION ERROR, so every mutation is
    reported RED, "reddened: (collection error)" scrolls past, and the matrix appears to have
    killed everything. The check that separates them is the one the recorded lesson already
    prescribes for `-k`, and it applies to a file list too: **run the selector ONCE unmutated
    first and read its pass count**, then mutate. Doing that here turned "9 of 9 killed" into
    "6 of 9 killed, 3 survivors" — and all three survivors were worth having.
  - **A DECLINE'S OWN PREMISE CAN BE THE ARGUMENT FOR REVERSING IT, AND THE STEP IT NAMED
    WAS 5% OF THE COST (2026-09-07, C16 / S-D — reversing the 2026-07-12 F13 decline):**
    F13 recorded that the batched collector flush holds the single-writer gate across
    per-article extraction, and DECLINED the fix as "GIL-bounded-marginal", reasoning that
    "batching already collapses ~8 extractions onto ONE commit, so **writes are the small
    part of the window**". That premise is exactly right and the conclusion is inverted: the
    writes being small is precisely why moving everything else out is worth ~16x rather than
    an amortised fsync overlap. MEASURED on the real ingest path (8 articles x ~22 KiB, five
    runs per arm, deterministic per arm while wall time is pure noise on this box): the gate
    window is **3626-3756 ms** before and **207-236 ms** after, with extraction accounting for
    **93.0-93.4%** of it before and **0.0%** after. TWO THINGS WORTH MORE THAN THE RATIO.
    (a) **The decline named the wrong step.** It says "keyword EXTRACTION", and the keyword
    extractor is the SMALLEST of the five pure steps (~185 ms of that batch) — `extract_dates`
    alone is ~1.93 s and `score_article` ~0.70 s. The material change since the decline is that
    when/where/who at ingest (T12) landed AFTER it and multiplied the in-gate CPU by roughly an
    order of magnitude, so a judgment that was correct when written became wrong without anyone
    editing it. The staleness guard's "is the MEASUREMENT this item rests on still one the code
    would produce today?" applies to a DECLINE as much as to a finding — and a decline is more
    dangerous, because nothing about it looks pending. (b) **The wall clock did not move and
    saying so is the finding**: five runs per arm both span ~6.6-9.5 s, so this relocates CPU
    rather than removing it and is a CONTENTION fix, not a throughput fix — the earlier
    three-run "before" trio happened to land at the low end and would have supported a
    fabricated regression story just as easily as a fabricated win.
    **THE INSTRUMENT WENT BLIND AT THE MOMENT OF SUCCESS, which is the part that would have
    shipped a silent data loss.** The timing probe patched `datestore.extract_dates` /
    `whostore.extract_locations` — the names as imported into the STORE modules — and the fix
    routes the same work through `reindex_parallel._extract_www`, which imports them from their
    DEFINING modules. So the three when/where/who steps vanished from the breakdown and the
    measured extraction total fell 3500 -> 840 ms, which is indistinguishable from "the WWW pass
    stopped running and every date, place and person is now silently dropped". A moved call site
    defeats a probe pinned to the old one, and the failure presents as a better number. The only
    thing that separates them is a WHOLE-STRUCTURE DIFFERENTIAL: dump every derived row on both
    trees and compare (54 articles, 1032 mentions, 68 dates, 24 places, 24 entities, keyword
    counters, sentiment, top-keyword and deduced language — byte-identical, same SHA-256 over
    158,390 bytes).
    **AND THE FIRST DIFFERENTIAL WAS A LOOKALIKE THAT ALSO CAME BACK IDENTICAL.** `pipeline.py`
    stores `language = doc.language or source.language`, so a fixture with one `language="en"`
    source made every article "en" whatever `<html lang>` said — and `extract_dates`' month and
    weekday tables are language-GATED, so the gated paths were never reached and a byte-identical
    result was worth nothing about the one argument the change threads. Fixed by giving each
    language its own SOURCE, with cs/hr over the same body as the discriminating pair: measured,
    "12 listopadu 2024" is **2024-11-12 under `cs` and 2024-10-12 under `hr`** — a different
    MONTH, not a recall difference. (A second lookalike hid behind the first: the bodies were
    identical across sources, and the content hash is global, so only the first source's articles
    were ever stored.) An unknown language REFUSES rather than guessing, so a wrong language
    costs recall and never fabricates — which is why the collector passes `article.language`
    (byte-identical to its own inline path) rather than the deduced language that would raise
    recall, and the recall gain is recorded as a separate item instead of smuggled into a
    hot-path move.
    **THE PROCESS-POOL HALF WAS REFUSED ON MEASUREMENT, NOT ON RISK:** the brief asked for
    `precompute_batch`'s cross-core precompute next, and `collect_batch_size()` defaults to 8
    against `_MIN_PARALLEL_BATCH = 16`, so it would take its serial path on every shipped
    configuration — a dormant mechanism that still looks wired. Above that default the collector
    runs up to 50 source workers concurrently, each spawning its own pool of up to 8 processes
    with nothing arbitrating between them; `reindex_parallel`'s pool is safe precisely because it
    has ONE caller at a time, holding the exclusive hold. The recoverable win is the gate window
    and running serially OUTSIDE it recovers all of it.
    **THE BASELINE COULD NOT BE A WORKTREE**, per the recorded trap: `pip install -e .` installs
    a META-PATH finder (`__editable___*_finder`), which runs before `sys.path`, so a worktree
    baseline silently imports the head tree. Reverting the two files in place — with copies taken
    first and the restore verified by checksum — is what made the base run a base run.
  - **A GUARD THAT COMPARES A WINDOW'S FIRST AND LAST SAMPLE CANNOT SEE A RESET IN
    THE MIDDLE — and the number it then publishes is positive, plausible and wrong
    (2026-09-07, PERF-09's download-rate sampler):** the owner-side rate refuses a
    negative delta, which reads as complete: a cumulative byte count that goes
    backwards means the transfer restarted, and a negative rate is not a slow
    download. It is complete only for a restart at the window's EDGE. With
    `reset(0)` at the head and a restart in the middle — 0 → 10,000 → 500 — first
    is still less than last, so the guard never fires and the rate comes out as
    500 B over 4 s: **a measured 125 B/s over a window in which 10,000 bytes
    arrived and were then discarded.** The check has to run on EVERY observation,
    not on the pair that happens to bound the window; a backwards count then opens
    a FRESH window, which is also better than refusing forever, because the bytes
    arriving after a restart are real progress at a real rate. GENERAL FORM: when a
    guard is written over an aggregate of a sequence (first vs last, min vs max,
    sum vs count), ask what it cannot see INSIDE the sequence — an invariant about
    a series is not testable from its endpoints. TWO RIDERS. **The mutation matrix
    then produced a survivor that was a finding about the MUTANT:** it added a key
    to `DownloadEntry.to_dict()` to test "nothing about the rate is persisted",
    and `_save()` serialises `asdict(entry)` — the dataclass FIELDS — so the
    mutation could never reach the state file the guard reads. Re-targeted at a
    real dataclass field it reddens by name; the recorded rule holds, and the
    first step on a survivor is to check the mutant reproduces the defect at all.
    **And my own "nothing is persisted" test was a non-unique needle:** it scanned
    the serialised JSON blob for the substring `"rate"`, and pytest names the tmp
    directory after the test, so the PATH contained it and the assertion failed
    against correct code. Walk the persisted KEYS.
  - **PRUNE A RATE WINDOW AT READ TIME, NOT ONLY AT WRITE — an instrument that
    freezes while still reporting is worse than one that stops (2026-09-07, same
    slice):** samples arrive only when bytes do, so a sampler that prunes its
    window on `observe` alone keeps a full window forever once a transfer stalls,
    and goes on publishing the last healthy figure for as long as nobody sends it
    another byte. Pruning against a FRESH clock reading at snapshot time makes the
    stall fall out by construction: everything ages out, the window empties, and
    the honest answer — "no bytes received in the last N s", with the idle time —
    is a measurement of a DIFFERENT quantity and the one an operator watching a
    stuck download actually wants. The distinction needs its own branch: an EMPTY
    window means aged-out, ONE sample means a window that just opened (a start, a
    resume, a restart), and folding them together would print an `idle_s` of ~0
    beside "no bytes received" for a transfer that is perfectly healthy and merely
    young.
  - **ADDING A CALL INSIDE A FUNCTION MAKES EVERY NODE SUITE THAT EXTRACTS THAT
    FUNCTION PART OF YOUR CHANGE — and the guard for it already existed; I pushed
    ahead of it (2026-09-07, PERF-09's rate line):** the house pattern for testing
    the UI engine is to EXTRACT a function from the real file by name and evaluate
    it in isolation, precisely so a re-typed copy cannot pass while the shipped
    code is broken. The cost of that isolation is that the extracted copy sees ONLY
    what its own suite extracted: adding `_rateNote(j, t)` inside `_jobRow` left
    `import_tail_phase_node_test.js` — a suite about IMPORT PHASES, which no search
    for "rate" or "download" would ever reach — throwing `ReferenceError: _rateNote
    is not defined`. I wrote my OWN node suite carefully (extracting `_fmtBytes`,
    `_fmtDur` and `_rateNote` together) and never asked who else extracts the
    function I had just added a call to. GENERAL FORM: before adding a call inside
    any function, `grep -l "<function>" tests/*_node_test.js` — the enumeration is
    by what the OTHER suites READ, never by what your change is about, because the
    suite that breaks is named for its own subject and not for yours.
    **THE PART THAT MATTERS MORE THAN THE FIX: the guard was not missing.** Every
    node suite has a pytest driver (the `test_every_node_suite_has_a_driver`
    ratchet exists because an unrun suite already cost a shipped defect), so the
    full suite catches this in the ordinary way — I pushed before my full run
    finished, at a stop-hook prompt, and CI found it 20 minutes later. When you
    cannot wait for the full suite, the substitute is not hope: `for f in
    tests/*_node_test.js; do node "$f" || echo "RED: $f"; done` runs all 28 in
    SECONDS and would have caught it. Add it to the named tree-guard set for any
    change that touches an `app-*.js` function other tests extract.
    RIDER on the repair: the tempting fix is a `typeof _rateNote === "function"`
    guard at the call site, and it is wrong for the reason the ledger already
    records — a `hasattr`-style guard around a call you wrote is self-fulfilling,
    and here it would make the PRODUCTION renderer paper over a broken harness.
    Extract the dependency in the suite that needs it, and never stub it, or the
    copy under test drifts from the shipped code, which is the one thing this
    whole harness exists to prevent.
  - **A GUARD'S OWN EXEMPTION SET CAN DEFEAT THE GUARD — exempt the QUESTION, never the
    ANSWER (2026-09-07, NET-01's resolution check):** the connect-time SSRF guard allowlists
    the configured proxy endpoint, because a Tor proxy is loopback and refusing it would
    refuse Tor itself. Its resolution half then skipped any RETURNED address that was in that
    allowlist — which reads as the same exemption and is the opposite of it. Resolving the
    proxy literal `127.0.0.1` answers `127.0.0.1` and must pass; a NAME that answers
    `127.0.0.1` **is the attack**. The exact reach is worth stating rather than rounding: the
    check went blind to any answer equal to a configured proxy's own ADDRESS, which on the
    documented Tor shape — and in any environment that names a loopback proxy, as this sandbox
    does — is `127.0.0.1`, the commonest SSRF target of all. `10.0.0.5` and `169.254.169.254`
    would still have been refused, which is precisely why it looked like it worked. It was also
    invisible because the LATER net (the connect check, keyed on the exact `(address, port)`
    pair) caught the reproduction anyway and the test went green. What found it was asking WHICH of two mechanisms fired, by reading the scope's
    own counters, rather than being satisfied that something refused. GENERAL FORM: when a
    guard carries an exemption, name which side of the comparison it belongs on — an exemption
    keyed to the thing being ASKED ABOUT is narrow, one keyed to the RESULT silently exempts
    everything that can produce that result. COROLLARY, and the reason the belt hid the
    defect: with two nets over one property, a test that only asserts "it was refused" cannot
    tell you which net is alive, so each mechanism needs a driver that reaches it alone (the
    recorded belt-masks-the-primary lesson, arriving from the other direction).
  - **A SECOND GUARD RIDING AN EXISTING PATCH LAYER MUST NOT INHERIT THE FIRST'S OFF SWITCH,
    AND ONE FLAG CANNOT CARRY TWO FACTS (2026-09-07, same slice):** the airplane backstop
    already patches `socket.getaddrinfo`/`create_connection`/`connect(_ex)`/`_tunnel`/
    `socksocket.connect`, and the right place for a connect-time SSRF check is those same
    functions — one layer, so a call site cannot meet one gate and miss the other. But
    `install_airplane_socket_guard()` reads `OO_AIRPLANE_SOCKET_GUARD` and, when it is `0`,
    installs NOTHING: riding that installer would have handed an unrelated flag a silent veto
    over a security control it was never about, and the installer itself only runs from
    `run_deferred_startup`, so a CLI, a script or a test would have had no guard at all.
    Installing the patches unconditionally instead re-arms airplane's refusal for the
    deployment that opted out of it. Both directions are wrong because `_installed` was being
    asked to mean two things: "the functions are patched" and "airplane is in force". Split
    them (`_installed` + `_airplane_armed`), give each guard its own env opt-out, and let each
    hook decide for itself. GENERAL FORM: before extending a shared mechanism with a second
    policy, list the flags that currently gate it and ask which policy each one is ABOUT; a
    flag that gates the mechanism gates every policy on it, whether or not that was ever
    intended.
  - **A PLAN'S REMEDY IS A HYPOTHESIS, AND THE TIE-BREAK IS WHICH WAY IT FAILS (2026-09-07,
    NET-01 "connect-time IP pinning"):** the recorded rule says a plan written from
    measurements is trustworthy about the DEFECT and not automatically about the REPAIR. The
    defect here was exact and live-reproducible — `_guard_target` validates one `getaddrinfo`
    answer, urllib3 connects on a second one, and a real fetch returned a loopback server's
    body as a clean 200. The prescribed repair, an adapter that PINS the validated IP, was
    refused after being costed: pinning means taking over urllib3's connection construction
    and then carrying the hostname separately for SNI, certificate matching and the `Host`
    header, i.e. version-fragile private API whose failure mode is a SILENTLY WEAKER TLS
    verification. Validating the address the connection ACTUALLY reaches gets the same
    security property — the threat is reaching an INTERNAL address, and a second, different
    PUBLIC answer is normal under CDN anycast, so pinning's extra strictness buys nothing
    here — touches no TLS state, and rides the stdlib socket chokepoint every HTTP client
    must pass through. The deciding argument is the direction of failure: a pinning adapter
    fails OPEN the day urllib3 moves its private API, and a socket-level check fails CLOSED.
    GENERAL FORM: when you diverge from a prescribed remedy, cost BOTH and pick on the failure
    mode, then write the comparison where the next reader will look for it — otherwise the
    divergence reads as a shortcut.
  - **A TRANSLATION SCOPED TO THE CALL YOU EXPECTED TO RAISE LEAKS THE ONE YOU DID NOT
    (2026-09-07, same slice, found by the negative-space pass and by nothing else):** the
    connect-time refusal is a private exception type, translated at the fetch boundary into
    the public `BlockedTarget` so callers keep the contract they already have. The first cut
    wrapped `session.get` — the call the refusal was expected to come from. But a redirect
    hop re-runs `_guard_target` INSIDE the same scope, and that resolves, so the refusal can
    arrive from there too: a redirect to an internal host escaped as a type no caller catches,
    on a path refused for exactly the same reason. Wrap the whole scope body, not the call you
    had in mind. GENERAL FORM: when a guard can raise from anywhere inside a region, the
    translation belongs at the region's edge; enumerate what else inside it touches the
    guarded resource, because the enumeration you write from the happy path will omit the
    re-entry.
  - **`session.proxies` IS NOT THE ANSWER TO "WHAT WILL requests CONNECT TO" (2026-09-07,
    empirical, and it decided a guard's correctness):** `Session.merge_environment_settings`
    folds `HTTP(S)_PROXY` from the environment in whenever `trust_env` is set, which is the
    default, and none of that appears in `session.proxies`. A guard that allowlists "the
    configured proxy" by reading the session alone therefore REFUSES the proxy connection of
    every operator whose proxy comes from their environment — a security control breaking a
    working configuration, which is the one thing it may not do. Two riders measured while
    fixing it: `requests.utils.get_environ_proxies` strips the `_proxy` suffix off every
    matching variable, so `NO_PROXY` arrives as the key **`no`** carrying a comma-separated
    host list (not a proxy endpoint) and `yarn_https_proxy` arrives as `yarn_https`; and
    PySocks 1.7.1's `socksocket._write_SOCKS5_address` takes its non-`rdns` branch through
    `socket.getaddrinfo(host, port, AF_UNSPEC, SOCK_STREAM, IPPROTO_TCP, AI_ADDRCONFIG)` and
    keeps `addresses[0]` — read out of the installed library rather than recalled, which is
    what makes it safe to claim that a local-resolving SOCKS destination lookup meets a
    `getaddrinfo` hook.
  - **MEASURE A SURVIVING MUTANT FOR EQUIVALENCE BEFORE WRITING A FIXTURE TO KILL IT — and
    when it IS equivalent, the honest repair is a direct test of the contract, not a deleted
    guard (2026-09-07, the DuckDuckGo redirect unwrap):** three of five mutations survived.
    One was a fixture gap (the missing-target fallback is equivalent on a scheme-less
    redirector and only discriminating on the absolute one, where returning the redirector
    registers `duckduckgo.com` as a discovered SOURCE). The other two were genuinely
    equivalent AT THE CALLER: `_clean_url`'s own `scheme`/`netloc` check and `safe_href`
    reach the same verdict for every relative, scheme-less and dangerous-scheme target, so no
    fixture through that path can ever tell the versions apart. Deleting them would have made
    a public classmethod answer dishonestly for any caller that is not `_clean_url` (the
    recorded "a public function's guards can live entirely in its caller" defect); keeping
    them untested would have shipped unexercised code in a security path. The third way is to
    test the helper's contract DIRECTLY and write the equivalence measurement into its
    docstring, so the next matrix does not re-find it and nobody writes a vacuous fixture for
    it. GENERAL FORM: a surviving mutant is a finding about the test, the fixture, or the
    code — and "which" is a measurement, not a judgement call.
  - **A CAPABILITY PROBE THAT RUNS THE LIBRARY'S HAPPY PATH CAN STILL BE WRONG ABOUT IT — and
    the FABRICATED-FAILURE half is the one no fixture catches (2026-09-07, D7's OTS probe):**
    replacing `OTS_AVAILABLE`'s bare-import check with an offline round trip is the correct
    fix, and the first version of that round trip reported OTS **unavailable on every install
    that has it**. `opentimestamps` refuses to serialize an EMPTY `Timestamp` — by name, "An
    empty timestamp can't be serialized" — and `anchor()` never meets that because it merges a
    calendar's attestations in BEFORE serializing. So the probe exercised a shape production
    never produces, and a fabricated FAIL is exactly as dishonest as the fabricated pass being
    fixed, and much easier to believe: it looks like the library being broken rather than the
    probe. THREE THINGS. (a) It was found by INSTALLING the optional extra and running the
    probe, not by reading it — the recorded "run tool-gated tests with the tool" rule, which
    on this repo means `pip install -e ".[pqc,timestamping]"` in the sandbox venv and takes a
    minute. (b) The guard that stops it recurring must be keyed on the LIBRARY being
    importable, never on the flag: a `skipif(not OTS_AVAILABLE)` keys a skip on the very thing
    under test, so a probe that wrongly reports unavailable SKIPS the tests written to catch
    that — mutation-proven, the mutation removing the attestation survived the first matrix and
    reddens the second. (c) A probe of an optional extra needs a LANE that installs it: the
    crypto lane installed `[pqc]` only, so the OTS positive half could not have run anywhere,
    which is the recorded "an environment-gated guard goes to die in a lane that names files
    explicitly" trap arriving before the guard was even written.
  - **WITH A WORKING LIBRARY INSTALLED, AN IMPORT PROBE AND A CAPABILITY PROBE AGREE — so the
    obvious assertion about the flag cannot fail (2026-09-07, same slice):** the natural guard
    for "the flag is derived from the round trip" is
    `assert PQC_AVAILABLE is _probe_mldsa(_mldsa)[0]`, and it SURVIVES the mutation that reverts
    the flag to `_mldsa is not None`, because on a machine whose pqcrypto works both answers are
    True. The discriminating case exists only if a library that IMPORTS and CANNOT WORK is
    injected — which is the shipped 2026-08-20 defect itself — and injecting it means reloading a
    module every custody test imports, so it belongs in a SUBPROCESS rather than in the shared
    process. GENERAL FORM: when a fix replaces predicate A with predicate B, ask on which inputs
    A and B DIFFER, and check the fixture reaches one; a fixture drawn from the healthy
    environment usually reaches none, and the guard then measures the environment.
  - **A "MUST BE WIRED" GUARD OVER A ZERO-ARGUMENT FUNCTION IS SATISFIED BY ITS OWN
    DECLARATION, AND `"POST"` IS NEVER A UNIQUE NEEDLE (2026-09-07, the reader's AI lens):**
    two source guards written in the same hour as the fix, both refuted by the mutation matrix
    in one run. `assert "loadAiLens()" in src` cannot tell WIRED from DEFINED, because
    `function loadAiLens() {` contains `loadAiLens()` — the recorded zero-argument trap,
    recurring in a file where nothing had yet used the shared slicer. And
    `assert '"POST"' in src` survived deleting the confirm request's method, because
    `reader.js` has ANOTHER POST (summarize/translate) thirty lines away. The replacement is a
    node suite that extracts the real functions and drives them: what is asserted is the markup
    a reader ends up with and the request that actually leaves the page, and both mutations then
    redden by name. Worth recording again because both traps are already in this file and were
    still walked into — the durable fix is to reach for the behavioural shape FIRST on any
    "is it called" claim, since that is the exact claim a substring cannot make.
  - **AN EVIDENCE COLUMN'S HONESTY IS ITS EMPTINESS (2026-09-07, `AiKeyword.evidence`):** the
    column is documented as "the snippet the model drew the term from" and had zero writers
    since it was added. The tempting writer is the model — ask it for the snippet — and that
    adds a SECOND unverifiable claim beside the first. A deterministic search of the article's
    own stored text says something checkable instead ("this term appears HERE in your copy"),
    and the case that carries the value is the one where it finds NOTHING: a term the model
    produced that is not in the text was inferred, translated or invented, and only storing
    nothing preserves that. So the mutation that matters is not "does it find the snippet" but
    "does it invent one" — filling a miss with the article's opening line passes every
    positive test. TWO MECHANICS worth keeping: search exact-first with `str.find` and fall
    back to an IGNORECASE regex over the ORIGINAL string, because `"İ".lower()` is `i` plus a
    combining dot and `"ß".casefold()` is `ss` — both change LENGTH, so lowering the text and
    indexing back into it slices at the wrong place; and the needle is `re.escape`d, so there
    is no pattern to backtrack (a literal search is linear, unlike the `OPEN.*?CLOSE` shape
    that cost a 412 KB article 138 seconds).
  - **A ROW-LEVEL VERIFICATION TIER SAYS NOTHING ABOUT THE ENDPOINTS INSIDE THE ROW — and
    trusting it fabricates a source rather than breaking a fetch (2026-09-07, the law
    catalog's gazette feeds):** four catalog rows carry a `gazette_feed`, all four are
    `verification.status: fetched`, and one of those feeds had never been asked for. The
    status is about the PORTAL — impo.com.uy's row records loading `/contenido/`, while the
    row's OWN notes call the feed URL the site's generic WordPress `/feed/` of news posts,
    "not confirmed to carry each day's Diario Oficial issue individually, so verify before
    relying on it for gazette monitoring". Promoting on the row status would have filed
    Uruguayan site news in the corpus **as that country's official gazette**: not a broken
    fetch, which announces itself, but a plausible wrong corpus, which does not. GENERAL
    FORM: a verification tier covers the thing the verifying session actually looked at, and
    every OTHER URL in that record is a claim nobody checked — so a field that will be
    fetched needs its own tier, and the vocabulary should be narrower than the row's where
    the middle tiers cannot mean anything (a search snippet can say a site exists, never
    that a URL serves a parseable feed). The same catalog has 107 `enumeration_url` values
    and a `structured.api`/`structured.bulk` pair in the identical position. COROLLARY on
    reading the evidence: the row-level `evidence` sentence is what settles it, and it did —
    three of the four record fetching the feed, one records fetching something else. Read
    the sentence, not the enum.
  - **A DENOMINATOR IN AN UNDECLARED UNIT IS NOT A DENOMINATOR, AND THE JOIN KEY IS THE
    SECOND TRAP (2026-09-07, law coverage):** 39 dated official counts sat in the law
    catalog as the completeness principle's missing denominators, and the obvious move —
    print `tracked / enumerated` — is a fabricated statistic: a tracked document is
    act/code-level while the recorded units run over codes, acts, volumes, gazette issues,
    treaties and cases, and a volume or a gazette issue holds many acts. Deciding
    commensurability from the unit STRING is the exact move ruling 47's extensive/intensive
    rail already forbids for aggregation, so the two numbers are published side by side with
    the reason attached and the declaration is raised as a ruling. SECOND HALF, and it would
    have been silent: the counts key on ISO-2 `country` while documents key on an "ISO-ish"
    `jurisdiction`, and `uk` documents state `gb` — so reading the jurisdiction code as a
    country BOTH misses that pair AND risks attaching some other country's enumeration to a
    code that collides with its ISO-2. The honest join runs only through the country a
    document itself states, and a document stating none gets its own third state rather than
    being reported as "no enumeration exists". GENERAL FORM: before dividing two numbers
    from different files, check the UNIT and the JOIN KEY separately — either one alone can
    make the quotient a number nobody measured.
  - **A MECHANISM BUILT TO SURFACE CAVEATS IS BLIND TO THE CAVEATS IT WAS NOT SHAPED FOR —
    carry the raw field too (2026-09-07, same slice):** a derived check (is the figure's
    `source_url` on the publisher's own domain?) correctly flags the Council of Europe's
    treaty count, which cites Wikipedia, and Mauritania's, which cites a news site. It
    STRUCTURALLY cannot flag the African Union's 80, whose `source_url` is perfectly
    on-domain and whose caveat lives in the row's `notes`: "a manual tally ... treat this as
    approximate, not authoritative". Extracting that with a prose heuristic is the move this
    project refuses, so the notes ride along verbatim beside the figure. GENERAL FORM: when
    you build an instrument to expose disclosures, ask what it is structurally unable to
    see, and keep the unprocessed field beside it — the same shape as the recorded
    two-harvest-instruments lesson, at the level of one payload.
  - **AN HONEST GAP RECORDED AS A COMMENT IS OUTSIDE THE SYSTEM, NOT A LESSER VERSION OF ONE
    (2026-09-07, the law catalog's two confirmed gaps):** the catalog has a deliberate shape
    for "we looked and there is no official portal" — a domain-less `lead` row, which the
    validator sees and the loader drops, so a gap can never become a `Source`. Yemen is one.
    North Korea's identically-reasoned, better-evidenced gap was a **YAML comment block**, so
    the validator could not count it, the vetting board could not list it, and nothing that
    reads the catalog as data knew it existed. Nobody was wrong at the time; the comment is
    the producing session's own words and is where a future reader looks. GENERAL FORM: when
    a project has a DATA shape for a deliberate absence, prose recording the same fact is not
    a weaker record, it is an invisible one — add the row and keep the prose beside it.

- **THE `shipped.csv` UNION-MERGE DUPLICATE HAS A THIRD SHAPE, AND ITS RECORDED TELL IS SILENT ON
  IT (2026-09-07, caught live on PR #1025 by the prescribed scan):** the ledger already records
  this defect twice, both times as *main edited a row your branch also carries*, with the tell
  being **"a numstat with DELETIONS on a merge you expect to be purely additive."** This time the
  direction was reversed: **THIS branch edited two rows and main merely carried the originals
  forward** (main's own commits touched the file, but not those rows). Union kept both sides'
  lines, so the merge produced **two duplicates while adding four lines and deleting NONE** —
  `4 added / 0 deleted`, exactly the "purely additive" numstat the recorded tell says is the
  healthy case. `git merge` reported success, and a conflict-marker grep is blind by
  construction (`.gitattributes` sets `merge=union`, so this file never produces a marker).
  **GENERAL FORM: the numstat tell detects only the direction where the OTHER side deleted
  something. When YOU are the editor, the duplicate arrives with a clean, additive numstat and no
  tell at all.** So the duplicate-key scan over `(date, area, item)` against the COMMON ANCESTOR
  is not a confirmation step to run when something looks off — it is the ONLY check that sees all
  three shapes, and it must be run on every merge that touches this file regardless of how the
  numstat reads. (Compared against the ancestor, never against zero: nine duplicates already
  exist there, so a bare "are there duplicates" test accuses every merge of nine things it did
  not do.) A corollary worth stating plainly: **editing an existing row is strictly more dangerous
  than appending one**, because only the edit can be duplicated by union — which is why rule (5b)
  is best obeyed in the same session that learns the PR number, when the row is still the newest
  thing in the file and no other branch carries a copy.
  - **THE PUBLISHER'S OWN CONFORMANCE VECTORS ARE EVIDENCE; MY HAND-WRITTEN CASES
    MEASURE MY UNDERSTANDING OF THE SPEC (2026-09-07, the vendored Public Suffix
    List):** implementing the PSL algorithm, I wrote ~20 cases from the spec, ran
    them, and they were all green. The upstream's own `tests/tests.txt` (CC0, 78
    vectors, fetchable from the same repo as the list) then found **two real
    defects on the first run**. (a) A LEADING DOT was stripped, so `.example.com`
    answered `example.com` where the spec says a malformed input has no
    registrable domain. (b) The list stores internationalised rules in UNICODE
    (`公司.cn`) while hosts arrive in PUNYCODE, so every `xn--` host fell through
    to the wrong suffix — **and that one has no positive-space symptom at all**:
    the answers were plausible domains, one label short, which no eyeball and no
    self-written case would flag. GENERAL FORM: when implementing a published
    algorithm over a published data file, look for the publisher's OWN conformance
    suite before writing a single expectation — a vector set authored by the
    people who define the format is a different KIND of artifact from cases
    authored by the implementer, and the difference is exactly the cases you did
    not think of. Vendor it beside the data (its digest pinned in the test, the
    registry coupling requiring both to be refreshed together: a newer list judged
    by older vectors proves nothing), and give the parse an anti-vacuity floor
    (`len(cases) >= 70`), because a truncated fixture makes the whole guard pass
    for free.
  - **A MUTATION CAN APPLY TEXTUALLY AND BE SEMANTICALLY INERT, AND `assert new !=
    old` CANNOT SEE IT (2026-09-07, the newsletter resolver's matrix):** the
    recorded rule is that a `str.replace` whose needle is absent is a silent no-op
    whose green run reads like a dead guard, and the prescribed check is to assert
    the edit landed. It did land here — `_INFRA_LABELS: frozenset[str] =
    frozenset(` became `... = frozenset() or frozenset(` — and **an empty frozenset
    is falsy**, so `X or Y` evaluated to the untouched real set and the "mutant"
    was the shipped code with extra characters. All 28 tests passed and I was one
    step from recording a guard as vacuous. So the edit landing is necessary and
    not sufficient: a mutant is only evidence once it REPRODUCES THE DEFECT, which
    for a data structure means asserting the structure is what you think (`assert
    not _INFRA_LABELS`) and for a branch means proving the branch changed. Re-run
    correctly (`if publication and publication not in _INFRA_LABELS:` ->
    `if publication:`) it reddened three tests by name. Same family as the
    recorded "a surviving mutant may be a finding about the MUTANT", with a
    sharper tell: a survivor whose mutation involved a boolean operator, a default
    argument or a falsy sentinel is a suspect mutant before it is a suspect test.
  - **A RESTORED SOURCE FILE IS NOT A RESTORED IMPORT — `__pycache__` CAN SERVE
    THE MUTANT'S BYTECODE FOR A WHOLE SECOND (2026-09-07, same matrix):** after a
    mutation run I restored the module with `cp`, verified the restore with a grep
    that could only match the ORIGINAL line, and re-measured — and got the
    mutant's numbers back, twice, for a file whose source was provably correct.
    CPython validates a `.pyc` by comparing the source mtime it recorded against
    the source's current mtime, and both have **one-second granularity**: a `cp`
    landing in the same second as the mutated run's cache write produces a
    matching pair, so the stale bytecode is served. It presents as "my fix did not
    take" or, worse, as a real measurement. RULE: clear `__pycache__` (and any
    scratch script's own) as part of every mutation restore, and remember that a
    source-level restore check proves what the next run will READ, never what it
    will EXECUTE.
  - **A MODULE THAT DEGRADES HONESTLY WHEN ITS DATA FILE IS ABSENT IS EXACTLY THE
    ONE WHOSE PACKAGING OMISSION IS SILENT (2026-09-07, `src/geo/data`):** adding
    `src/catalog/data` I checked `[tool.setuptools.package-data]` and found `"src"
    = ["static/**/*"]` — so the offline IP-to-country table under `src/geo/data`
    had been missing from every built wheel since the day it was added, and
    nothing said so, because `ip_geo` reports an honest unavailable-with-a-reason
    rather than raising. The wheel installs, the app boots, and a feature is
    simply absent with a plausible explanation — the same shape as a degrade
    wrapper hiding the bug it was built to survive, moved into the build. TWO
    RULES. Derive the requirement from the TREE, not from memory: the guard walks
    every `src/*/data` directory that exists and fails naming the file no pattern
    covers, so the next such tree cannot be forgotten. And prove it with a REAL
    BUILD (`python -m build --wheel`, then read the zip's namelist) rather than
    with the declaration — the existing packaging guard is config-shape only and
    was green throughout, which is what let the gap live.

- **A DECLARATION THAT NAMES AN UNDEFINED CUSTOM PROPERTY DOES NOT DEGRADE — IT DELETES
  ITSELF, AND NINE AUTHORS IN A ROW WILL NOT NOTICE (2026-09-07, PRH-32):** `var(--line)` is
  referenced 41 times fallback-lessly across ten files of the SPA bundle and defined in none
  of them — only in the two SERVER-RENDERED pages, which carry their own `:root`, so
  `reader.css` is correct and everything the SPA loads is not. CSS does not fall back here: a
  `var()` that resolves to nothing makes the whole declaration **invalid at computed-value
  time**, so it becomes `unset`, and for `border` that is `0px none`. Measured with
  `getComputedStyle`: all eleven `<dialog>` elements declared `border:1px solid var(--line)`
  and every one computed `border-top-style: none` — nine have declared a border that has never
  once rendered. THREE THINGS WORTH KEEPING. (a) This is the recorded `class="small"` lesson
  one level down — there a class with no rule, here a NAME with no definition — and the same
  tell applies: the defect is not in any line you can point at, it is in a line that does not
  exist, so reading the markup tells you the opposite of what the screen shows. (b) **The
  property's `unset` decides the severity**, so ask what it is before ranking one: `border`
  disappears (cosmetic) while `fill` INHERITS, and the inherited value is black — the
  diagnostics chart's two axis titles rendered `rgb(0,0,0)` on a `rgb(20,24,31)` panel,
  **1.09:1**, on all twelve dark themes. (c) **A census must NOT flag `var(--x, fallback)`** —
  that form is valid whether or not the token exists, and the first cut of this guard reported
  `--hover`, `--lead-h` and `--muted-bg` as defects when all three are deliberate defaults
  (`--lead-h` is set by JS at runtime). A fabricated FAIL is exactly as dishonest as a
  fabricated pass; anchor the pattern on the closing paren. Reconciling the two counts is what
  turned "53 broken references" into "41 broken and 12 fine" — the raw prefix grep overstated
  the defect by a quarter.
- **A ZERO-SPECIFICITY `:where()` DEFAULT IS WHAT LETS A GLOBAL SCALE COEXIST WITH DELIBERATE
  EXCEPTIONS (2026-09-07, PRH-32):** lifting the 2026-08-11 Settings type scale app-wide as a
  plain `.panel h3` rule would have carried (0,1,1) and beaten `.brief-bucket > h3` (12px, a
  family lens label), `.fig-title` (13px) and `.lib-sub` (13px) — blowing three
  deliberately-small labels up to 15.5px, i.e. trading the reported inversion for three new
  ones. Written as `:where(.panel, dialog) :where(h3)` the rule contributes ZERO specificity,
  so it is a DEFAULT any authored class overrides with no `!important` and no re-scoping war,
  while a bare `<h3>` nobody styled stops taking the browser's 1.17em. Pinned by a guard
  asserting BOTH `:where()` wrappers survive — the mutation that unwraps one reddens by name,
  which is how you learn the mechanism is load-bearing rather than decoration. GENERAL FORM:
  when a base rule must lose to every component that disagrees with it, express that as
  SPECIFICITY rather than as source order — order only decides ties, and a class selector beats
  an element-descendant one whatever the order.
- **A PROPERTY THAT LIVES AT THE CALL SITE REACHES THE CALL SITES SOMEBODY REMEMBERED
  (2026-09-07, PRH-32):** nine of eleven `<dialog>` elements carried
  `background:var(--panel);color:var(--fg)` in their own `style=` attribute and two did not —
  so those two alone fell back to the UA's `Canvas`/`CanvasText` and rendered IDENTICALLY on
  all 17 themes (ground `rgb(18,18,18)` on the twelve dark ones, `rgb(255,255,255)` on the five
  light ones). The palette reached nine dialogs and stopped at two, and nothing said so,
  because a per-call-site convention has no place to fail. This is "gate EVERY entry point" in
  a stylesheet: the repair is one `dialog { }` rule, so a twelfth dialog is themed by
  construction. RIDER, and why the guard has two halves: an inline `style=` beats every
  stylesheet rule, so the chokepoint is only a chokepoint while nothing re-inlines what it
  owns — the guard therefore forbids the inline re-declaration as well as requiring the rule,
  and both mutations redden separately.
- **ONE THEME CANNOT ANSWER FOR SEVENTEEN WHEN THE VALUE COMES FROM THE UA (2026-09-07):** the
  two off-palette dialogs measured 18.73:1 on ink and 21.00:1 on paper — *better* than the
  app's own pairs, so a contrast-only check on one or two themes reports them as the healthiest
  surfaces in the app. The finding is not the ratio, it is that the GROUND was the same two
  values for all 17 themes while every themed surface's ground differs per theme. When a check
  can be satisfied by a value the app did not choose, measure the GROUND as well as the ratio,
  and sweep the axis the app actually varies.
- **A HEADING PROBE SCOPED TO ONE CONTAINER CLASS REPORTS A CLEAN APP (2026-09-07, PRH-32):**
  the first cut of the inversion probe defined "a section" as `.panel` and assigned each
  heading by `closest('.panel')`. It found **zero** inner headings on six of fourteen surfaces
  and reported **0 inversions** — a perfect-looking result from an instrument that could not
  see its subject, because most of this app's content sits in `.an-panel` / `.card` /
  `.fig-block`. The tell was the count, not the verdict: an anti-vacuity line printing
  `sections / titled / inner_headings` per surface is what showed six zeros. Measure EVERY
  candidate and post-process, rather than pre-filtering by a container you happened to name;
  and for any "no violations found" result, print the population the check actually examined.

- **A TEST NAMED FOR A MODE IS NOT COVERAGE OF THAT MODE — CHECK THE FIXTURE AGAINST THE SHAPE
  THE MODE EMITS, NOT AGAINST THE CODE PATH YOU JUST CHANGED (2026-09-07, `parse_sdmx_json`
  and `dimensionAtObservation=AllDimensions`):** the 2026-08-13 session fixed the
  observation-level LOOKUP for that mode, wrote
  `test_ref_area_is_read_at_observation_level_too_for_dimensionAtObservation_all`, and recorded
  the lesson *"run the parser; do not reason about it."* It followed its own lesson — and the
  fixture it ran the parser against kept `dataSets[].series[""]`, a container `AllDimensions`
  never emits. So the test exercised the lookup, never the container, and stayed green for
  three weeks while the mode returned **nothing**: `AllDimensions` hangs its observations
  straight off the dataSet (`dataSets[].observations`, no `series` key at all), the parser read
  them only out of `dataSets[].series[<key>].observations`, and a well-formed message parsed to
  zero rows. **THE SHARP EDGE: "run the parser" bounds only as much as the INPUT is real.** A
  fixture written by the same reasoning that wrote the fix inherits the same blind spot, and a
  green test then certifies the blind spot. When a fixture stands in for someone else's wire
  format, the thing to verify is the fixture against the format's own documented shape — a
  fixture derived from your code's expectations tests your code against itself. The tell here
  was cheap and general: the fixture had a `series` container in the one mode whose defining
  property is that it has none.
- **`[]` WITH NO LOG IS THE IDENTITY-LESS ROW INVERTED, AND THE ALARM MUST BE SCOPED TO A
  MISSING CONTAINER RATHER THAN TO ZERO ROWS (same session, the honesty half):** the 2026-08-13
  fix stopped a real number being emitted with no country, indicator or year. The mirror defect
  survived it — an unreadable message returning an empty list without a word, so *"this parser
  could not read the message"* and *"the publisher has no data for this query"* reached the
  caller as the same fact. Both are a gap published as something else; only the direction
  differs, and the silent one is harder to find precisely because nothing looks wrong. **AND
  THE OBVIOUS GUARD IS THE WRONG ONE:** warning whenever a dataSet yields zero rows would fire
  on `"series": {}` — a publisher honestly answering "nothing matches" — so the alarm has to
  key on a container that is ABSENT, never on one that is present and empty. An over-eager
  alarm is its own dishonesty: it trains a reader to ignore the real one. Both directions are
  pinned by mutation-checked tests, because the guard that cries wolf and the guard that stays
  silent fail in opposite directions and one test cannot see both.
  - **A POLAR "IMPORTANCE" AXIS IS A LOG AXIS WAITING TO FABRICATE ITSELF, AND THE REAL CORPUS
    PICKS THE FALLBACK (2026-09-07, the Observatory / `ooSky`):** the design specified a
    log-scaled radius with labelled orbit rings, which is right for the measure it was
    imagined against and wrong for three of the four the picker offers. Measured on a
    440-article corpus through the real `index_article`: `mentions` tops out at 263 (2.4
    decades, log is honest) but `distinct_sources` tops out at **7**, `distinct_languages` at
    5 and `distinct_keywords` at 8 — under one decade each, so a log radius would spread five
    sixths of a decade across an entire sky and label orbits nothing can occupy. This is the
    recorded `logY` defect one geometry over, and the same repair applies: **choose the mode
    from the data, fall back to the axis the data deserves, and SAY on the surface which one
    was drawn** — a hint claiming "equal ratios are equal distances" above a linear render is
    two statements at once. THE SECOND HALF IS BIGGER AND WAS NOT IN THE DESIGN AT ALL: **52
    of 77 galaxies had a measure of ZERO.** `log10(0)` is `-Infinity`, and the natural guard
    (`Math.max(v, 1e-9)`) plants a fabricated observation on the outermost orbit — so a zero
    gets NO coordinate, and `r(v)` returns `null` rather than a number, which is what stops a
    caller that ignored `mode` from plotting anyway. The absent majority then needs its own
    labelled treatment outside the value scale, because on a young corpus the gap IS the
    common case rather than an edge case. GENERAL FORM: before specifying a log axis, get the
    real maximum AND the count of zeros for **every** measure the control can select; a scale
    that is honest for the measure you had in mind is not thereby honest for its siblings.
  - **A SIZE CHANNEL WITH A MINIMUM RADIUS HAS A CAP, AND THE LEGEND WILL QUIETLY TEACH A
    SCALE THE CANVAS DOES NOT USE (2026-09-07, same slice):** `sqrtAreaScale` is the honest
    way to size a mark by a value, but a renderer also needs a floor or small marks vanish —
    and the floor is a CAP on the channel: every value under it draws identically. Two things
    follow. (a) The legend must clamp to the SAME constant the canvas clamps to; the first cut
    computed reference stars from the raw scale and produced a 0.8px sample while nothing on
    screen was under 1.5px, i.e. a key for a scale that does not exist. (b) The value at which
    the channel saturates is a number the surface owes the reader, exactly like "N shown, M in
    the nebula" — so it is computed (`maxMentions * (MIN_STAR/maxStar)²`) and printed. A
    visual channel's cap is an anti-capping disclosure like any other.
  - **A SECOND `oo:langchange` LISTENER IS A SECOND ENUMERATOR, AND TWO EXISTING GUARDS FIND
    "THE" LISTENER BY FIRST OCCURRENCE (2026-09-07, same slice):** a new module added its own
    `document.addEventListener("oo:langchange", …)` — reasonable in isolation, and it reddened
    `test_live_language_switch_rerenders_cldr_name_surfaces` and
    `test_home_briefing_re_renders_on_language_switch`, both of which locate the app's ONE
    canonical listener with `app.split('addEventListener("oo:langchange"', 1)[1]`. The new
    module loads before `app-boot.js`, so it became the first occurrence and both guards
    started reading a listener that was never theirs. The tests were right and the code was
    wrong: "what must re-render when the language changes" is a question the app already
    answers in one place, and a second listener is the recorded second-enumerator shape.
    Register there. The needle being non-unique is the tell, not the bug.
  - **AN ORM COLUMN DEFAULT MAKES A `None` FIXTURE UNABLE TO TEST THE NULL BRANCH (2026-09-07,
    the article-length quarantine filter):** `Article.quarantined` is `Mapped[bool | None]`
    with `default=False`, so a fixture row built with `quarantined=None` is stored as `0` and
    not `NULL`. The test asserting that `isnot(True)` keeps never-judged rows therefore
    contained no such row, and the mutation swapping `isnot(True)` for `== False` **survived**
    — the one survivor in a sixteen-mutation matrix, and it was a finding about the fixture
    rather than about the code. A pre-migration row is genuinely NULL, so the fixture has to
    write that state the way the database holds it (`UPDATE … SET quarantined = NULL`) and
    then ASSERT the NULL is there, or the branch is untested while looking covered. Same
    family as the recorded fixture-missing-a-field-production-always-stamps entry, arriving
    from the opposite direction: here production stamps a default the fixture cannot refuse.
  - **A CODEC MULTIPLIER MEASURED IN THE PAGE CACHE OVER-STATES A DISK-BOUND WALK, AND
    THE RULED PAGE SIZE IS WHY (2026-09-07, the S5 measurement of the two whole-corpus
    PRAGMA checks):** `merge_diag.walk_probe` publishes a plaintext-versus-encrypted
    page-walk RATIO precisely because a probe small enough to sit in a bundle is small
    enough to sit in RAM, and its docstring's recipe is to take the field's own measured
    `prepare_staged:validate` rate and apply the multiplier. Measured independently at
    2 and 4 GiB on the real engine, n=3 per configuration, the multiplier reproduces
    **warm** — 2.34x/2.57x against the recorded 2.40/2.39/2.42 — and falls to
    **1.29x/1.39x cold**. THE MECHANISM IS THE RULING ITSELF: a staged corpus is
    exported plaintext and gets SQLite's 4096 default, while an encrypted store created
    under DB-10 §1b is **16384**, so the encrypted arm does a QUARTER as many reads,
    four times as large, and once I/O dominates that pays for most of the codec — and
    the field's `validate` rate (17 MB/s on a 32 GB artifact) is as disk-bound as a
    number gets. So the recipe over-states by about 1.8x on exactly the input it names.
    GENERAL FORM: a ratio survives a regime change only when BOTH arms stay in the same
    regime; before applying one measured in RAM to a rate measured on a disk, ask what
    ELSE differs between the arms — here a page size that a separate, correct ruling had
    already changed. TWO MORE FACTS FROM THE SAME RUN, recorded so they are not
    re-derived: both checks are **LINEAR in bytes** (encrypted `quick_check` 8.2 → 8.4
    s/GiB cold as the corpus doubles, `foreign_key_check` 3.1 → 2.8, flat to within the
    noise), and `foreign_key_check` is **CODEC-NEUTRAL** (0.84-0.98x per byte in both
    regimes) and costs about a THIRD of `quick_check` — it is index-driven and never
    walks the pages `quick_check` walks, so it is not the place to look first.
    **AND THE MEASUREMENT TOOK THREE PASSES, WHICH IS THE OTHER HALF OF THE LESSON.**
    Pass 1 ran ONE repetition per configuration while this session was also running
    pytest, mypy and a mutation matrix; its cold ratios came out 1.51x/1.08x/0.95x/1.58x
    — no trend — and a story was nearly written around the 0.95. Pass 2 fixed the
    repetitions and interleaved AT THE CONDITION LEVEL (all arms cold, then all arms
    warm), which spreads machine drift across arms and **destroys any condition that
    depends on what ran immediately before**: by the time the first arm's "warm" run
    happened, three later arms had each dropped the page cache and read gigabytes
    through it, so its 2 GiB warm `quick_check` measured 14.6 s against a
    genuinely-warm 5.2 s. Interleave one level OUT — a round visits every arm, and
    within an arm the dependent conditions run back to back — and both properties
    survive. The tell for both passes was the same: a per-configuration spread that made
    the differences unreadable, against 1.19x worst-case once it was measured properly.
  - **"DID IT COPY?" IS ANSWERED BY THE CONTENT, NEVER BY THE CLOCK — a timing
    assertion at fixture scale is the lookalike trap wearing a test's clothes
    (2026-09-07, the checkpoint's carried working copy):** the whole saving of the
    import checkpoint is that the second item of a group REUSES the working copy
    instead of re-snapshotting the corpus, so the obvious guard is that the second
    item's `snapshot_working_copy` stage is faster than the first's. The mutation that
    re-snapshots unconditionally **SURVIVED it**: on a fixture this small both numbers
    are noise, and a comparison between two noise samples passes about half the time in
    each direction. The exact, load-independent question is what a re-snapshot actually
    DOES — it throws the previous merge away and starts again from the live corpus — so
    the discriminator is `SELECT COUNT(*) FROM merge_batches` in the carried file: two
    after two held items, one after a re-snapshot. GENERAL FORM: when a change's win is
    that some work is SKIPPED, do not assert the duration; assert the state that only
    the skipped path can produce. Same family as the recorded "a probe's scale is part
    of the lookalike", with the fixture rather than the measurement as the subject.
    **SECOND SURVIVOR FROM THE SAME MATRIX, and it was a finding about the CODE:**
    deleting `self._checkpoint_k <= 1` from the hold decision changed nothing, because
    the group-full check beside it (`open_items + 1 >= k`) independently returns False
    for every item at K = 1. Neither deleting the clause nor writing a test for it is
    right: it is a belt on the shipped default (an off-by-one turning `>=` into `>`
    would let K = 1 hold an item), so it stays, the measurement goes in a comment beside
    it, and the mutation matrix reverts BOTH clauses together — the recorded 2026-08-02
    "revert every mechanism" lesson, met for the first time on a guard being written
    rather than one being audited.
  - **A STAGE LIST THAT SAYS WHERE A DRY RUN STOPS IS A CLAIM ABOUT AN EARLY RETURN,
    AND THE RETURN MOVED FIRST (2026-09-07, `restore_stage_plan`):** the plan's own
    docstring and its test both said "a dry run stops AFTER `corpus_delta_before`", and
    `_RESTORE_STAGES_ALWAYS` duly counted that stage — while `run_restore`'s
    `if not commit: return` sits directly ABOVE it, so a preview's published
    denominator was one larger than the number of stages a preview walks. The drift
    guard could not see it: it compares the declared list against the ORDER of
    `timings.stage(...)` calls in the source, which is a claim about sequence and says
    nothing about which of them a given flag reaches. GENERAL FORM: a guard over an
    ordered list checks order; the CONDITIONAL membership needs its own assertion, one
    per branch the function can return on.
  - **PUSH CI ON `main` HAS NOT COMPLETED ONCE IN 40 RUNS — "CI will catch it" is not an
    available guarantee on this repository, and the ledger leans on it repeatedly
    (2026-09-07, measured while trying to verify a merge):** the recorded lesson is
    `merged ≠ green`; this is the structural version underneath it, and it is worse.
    Of the **40 most recently COMPLETED `ci.yml` runs on `main`**: **34 `cancelled`,
    2 `failure`, 4 `success` — and all four successes are `event: schedule`.** Not one
    push-triggered run on the default branch reached a conclusion. Each merge's run dies
    when the next merge lands, and under this cadence that is minutes: run 4923
    (`c370d4f8`, my own merge) was created 17:36:09 and cancelled 17:39:52, the instant
    #1029 merged; 4929 died at 17:43:12 when #1026 landed. 4923 had **zero jobs
    allocated** when it was cancelled, so it never ran a line. THE CONSEQUENCE IS NOT
    ABOUT ANY ONE PR: several standing lessons resolve a local limitation with "let CI
    run the real test" (the CI-only/standalone-repro pattern, the columnar real-httpfs
    round trip, the pwsh-gated installer tests, the crypto lane). On the default branch
    that referee reports on a cron, against whatever `main` happens to be at 11:33 UTC —
    a moving target that is nobody's merge. So a session that defers a check to CI is
    deferring it to the nightly, and the honest move is to reproduce the lane locally
    whenever it can be reproduced at all: the **Core-only lane can** (a clean 3.13 venv,
    `pip install -e ".[dev]"` in a worktree, then that lane's own `pytest -q`; measured
    here 9170 passed / 150 skipped / 0 failed against 9303/128 with the extras, the extra
    22 skips being the analysis-gated tests doing exactly what the lane checks), and so
    can PowerShell and sqlcipher per their own recorded entries. **WHAT IS MEASURED AND
    WHAT IS NOT:** the 34/40 count and the cancellation timestamps are measured. The
    MECHANISM is not, and the reason to say so is that `ci.yml` already carries
    `cancel-in-progress: ${{ github.ref_name != github.event.repository.default_branch }}`
    — i.e. the repo *intends* to exempt `main` and the exemption is not taking effect.
    Whether that expression is mis-evaluating, or whether pending runs in a group are
    superseded regardless of the flag, needs a check the Actions API does not expose
    cleanly (a cancellation reason). Do not "fix" the workflow on the strength of the
    observation alone — the observation says the guarantee is absent, not why.
  - **A RULING CAN INVALIDATE THE PLAN THAT ASKED FOR IT, AND THE PLAN GOES ON READING AS
    CURRENT (2026-09-07, the storage refresh):** `STORAGE_5TB_PLAN.md`'s whole priority order
    rests on headline finding (3) -- "a default-page SQLCipher file caps at ~17.5 TB, so text
    offload (Phase C) is MANDATORY". That ceiling is `max_page_count x page_size`, and the plan
    itself is what asked for the DB-10 SS1b page-size measurement; when the ruling landed
    (16384, wired 2026-08-13) the ceiling quadrupled to **64.00 TiB** and the premise died --
    seven weeks before anyone read the plan again, with no line in it that looked stale. The 5 TB
    milestone went from 28% of one file to 7.1%, and the plan's own "50 TB is not reachable by
    any single-file design" became false. GENERAL FORM: the staleness guard is usually run as "is
    this already built?" and the recorded refinement is "is the MEASUREMENT this item rests on
    still one the code would produce today?"; this is the third form and the most expensive --
    **a ruling changes an INPUT, and every premise COMPUTED from that input is stale the moment
    it lands, including premises in the document that requested the ruling.** So when closing out
    a ruling, grep the requesting document for numbers DERIVED from the value that changed, not
    just for status lines about the ruling. The tell is a load-bearing figure with no citation to
    a run -- "~17.5 TB" had been carried as a constant since 2026-07-12 and nobody re-derived it
    because it did not look like a measurement.
  - **A MECHANISM THAT WORKS ONLY AT THE OLD DEFAULT IS A TRAP THE NEW DEFAULT ARMS -- and it
    fails toward SUCCESS (2026-09-07, `VACUUM INTO` under SQLCipher):** the plan and the
    2026-07-18 folder-copy-parity ruling both name `VACUUM INTO` with pragmas set as an
    alternative migration mechanism. MEASURED across the page-size ladder, it writes its product
    at the compiled `DEFAULT_PAGE_SIZE` (4096) **whatever the source is, and reports success**:
    usable at 4096, unopenable at 1024/2048/8192/16384/32768. So it worked on exactly the page
    size every corpus HAD before 2026-08-13 and no corpus created since HAS -- the coincidence is
    both why it was never noticed and why the ruling that removed it is what armed the trap.
    (Not a plaintext leak: no plaintext runs, no table name, 261,051 of 262,144 bytes differ. The
    source survives. No live call site, so it was a documented instruction rather than a shipped
    bug -- which is the only reason this is cheap.) THE OBVIOUS REPAIR IS ALSO A TRAP: setting
    `cipher_page_size` on a live keyed connection poisons the codec and the next statement fails
    `file is not a database` **naming the SOURCE**, i.e. reporting corpus corruption that has not
    happened; the stdlib spelling `PRAGMA page_size` is accepted SILENTLY and surfaces one
    statement later. GENERAL FORM: when a default changes, grep for the operations that were only
    ever exercised at the OLD value -- their correctness may have been a coincidence with that
    default, and an operation that silently produces a wrong artifact is worse than one that
    refuses. And scope the finding with its twin: on a PLAINTEXT store the same statement honours
    declared pragmas exactly, which is why the Open-queue's "EMPIRICALLY PROVEN in-sandbox for
    plaintext" was true and was never evidence about the encrypted path.
  - **I HIT THE COINCIDENT-FIXTURE TRAP TWICE IN ONE HOUR, IN OPPOSITE DIRECTIONS, AND THE GUARD
    CAUGHT THE PROBE (2026-09-07, same slice):** the recorded rule is that a fixture where two
    values coincide cannot test which one is used. (a) My first C5 probe asked whether an
    ATTACHed target INHERITS the source's pragmas, using a 4096 source against a compiled default
    of 4096 -- so "inherited" and "took the compile default" gave the same answer and the arm
    settled nothing. (b) Re-run from 16384 it discriminated, and I then read its result as
    "`VACUUM INTO`'s product never opens" -- when the real rule was "the product is ALWAYS 4096",
    which my 16384 fixture could not distinguish from "always broken". **What caught (b) was the
    regression test failing**, not the probe: the guard used a 4096 source, the product opened,
    and the contradiction is what produced the actual mechanism. GENERAL FORM: a probe and the
    guard written from it are two instruments; when they disagree, the disagreement IS the
    finding, and the answer is a matrix over the varying axis rather than a better story about
    either run. COROLLARY, from the mutation matrix on my own guard: rewriting the negative-space
    fixture back to the coincident 4096 made it pass again, so the fixture is what carries that
    test -- closed with an anti-vacuity assertion that the source differs from the compile
    default IN BOTH DIMENSIONS, because a comment saying so is exactly what the next edit will
    not read.
  - **VARYING ONE PARAMETER MOVES EVERYTHING THAT DEPENDS ON IT -- the sharding control inverted
    my own finding (2026-09-07, the hash-shard BM25 measurement):** measuring cross-shard ranking
    divergence at K = 2/8/32/128 over a FIXED 120,000-document corpus produced an alarming result
    (top-20 overlap down to 30% at K=128, the top result itself changing) which I was one edit
    from recording as "sharding degrades ranking". It is not: raising K over a fixed corpus also
    THINS each shard, to 940 documents at K=128, and BM25's IDF is computed from per-shard
    document frequency -- so the fixture had made shards statistically thin, which is not the
    regime the plan proposes (~1,000,000 docs/shard). Holding K=32 and fattening the shards
    instead, the divergence RECOVERS toward the proposed size: mid-frequency 60 -> 75 -> 90%,
    rare tail 40 -> 75 -> 95% at 2k / 8k / 32k documents per shard. The control cost twelve
    minutes and reversed the conclusion. GENERAL FORM: before recording a trend over a swept
    parameter, list every OTHER quantity that parameter moves and hold the suspicious one fixed
    -- this is the recorded "a probe that refutes a hypothesis is a claim about the fixture until
    it is shown to be a claim about the system" trap, with the CONFOUND rather than the scale as
    the varying axis. Two riders worth keeping. The RECALL half (100% of the matching set in all
    44 cells) is structural rather than statistical -- the fan-out visits every shard with no
    per-shard cutoff -- so it confirms the construction rather than discovering it, and saying
    which of your numbers is which is what keeps the evidence section evidence. And FTS5's
    `bm25()` takes column WEIGHTS and nothing else, so the plan's offer of "either maintain
    global term stats or disclose the approximation" is not a real choice: there is no way to
    hand FTS5 external statistics, and the options are fat shards, disclosure, or scoring
    outside FTS5.

  - **A "MUST BE GONE" GUARD OVER A MARKDOWN DOCUMENT TRIPS ON THE SENTENCE THAT RECORDS
    THE REMOVAL -- and the narrowing that works is FENCED CODE BLOCKS (2026-09-07, the
    J3 SQLite-only sweep):** the ledger records this trap three times for source
    (`//` comments in JS, docstrings in Python, `/* */` in CSS) and each time the fix is
    "strip comments, never reword the explanation, because that explanation is what a
    future session reads before deciding the removal was a mistake". Markdown has no
    comment syntax, so the same guard looks unfixable: my rewritten Full-Text Search
    section necessarily NAMES the `to_tsvector` recipe it deleted, and the store section
    has named the `tsvector` path as what parity would require since the v0.0.7 audit --
    so `assert "to_tsvector" not in doc` failed against correct prose. The distinction
    that saves it is not about comments at all, it is about the CLAIM: the page may NAME
    PostgreSQL and must not INSTRUCT anyone to run it, and **an instruction is a command
    in a code block**. Extract the ``` fences and assert over those. GENERAL FORM: when a
    negative source guard fires on the text explaining the absence, do not look for the
    document's comment syntax -- look for the syntactic form the FORBIDDEN THING takes,
    and scope to that. And give the extractor its own anti-vacuity assertion (a fence
    reader that returned `""` would pass against any document ever written).
  - **A MEMORY, TIMING OR RATIO ASSERTION TAKEN OVER A SHARED PATH IS A CLAIM ABOUT THE
    WHOLE PYTEST SESSION -- and the tell can be an UNUSED `tmp_path` (2026-09-07, S6):**
    the full suite on clean `main` was 1 failed / 9221 passed, and the failure --
    `test_the_boot_pass_costs_the_SAME_whatever_the_journal_size` -- passed alone AND as
    a whole file. It asserts a RATIO (the boot pass must allocate no more for a 20.8 MB
    journal than 3x what it allocates for a 1.7 MB one) and took that reading over the
    session-wide `run_logs_dir()`, which `promote_incomplete_runs` scans up to FIFTY
    journals of. So the measurement included whatever every other test had left there,
    and the ratio moved with them: 1.74 MB -> 6.05 MB and 20.8 MB -> 21.43 MB against an
    18.15 MB bar. Over a directory holding only its own two journals the peaks are 0.39
    and 0.40 MB and FLAT across the 12x difference -- i.e. the streaming property the
    test exists to prove was intact the whole time and what was broken was the
    measurement's environment. THE FIX IS ISOLATION, NOT A LOWER BAR (raising the input
    strengthens a guard; lowering the bar weakens it, and only one of those is a
    legitimate response to a red lane) -- and the test already TOOK `tmp_path` and never
    used it, which is a cheap thing to grep for. It still discriminates: reverting
    `_iter_jsonl` to the whole-file read reddens it by name at 1.30 MB and 15.46 MB.
    This is the third distinct shape in the order-dependent family, after the lifespan
    `TestClient` fixture and the test poisoned by its own background thread; the common
    factor is not "another test wrote something" but "this assertion is about a resource
    the session shares".
  - **AN "ADVISORY" LANE CANNOT REPORT THAT IT IS FAILING WORSE (2026-09-07, S7's ruff
    decision):** the recorded freshness-issue lesson says a gate that ALWAYS fires decays
    into noise. The inverse is quieter and costs more: a lane marked
    `continue-on-error` fails by design, so growth inside it is indistinguishable from
    the failure it is expected to have. PARKED.md recorded the ruff style lane at **344**
    findings on 2026-08-20, in the session that had just zeroed 164 of them; it measured
    **432** on 2026-09-07 -- 88 of drift in eighteen days, in a file whose own contract is
    "statuses are the file's contract: keep them truthful". Prose had already been tried
    on exactly this number. The answer is a NON-GROWTH ratchet beside the advisory lane:
    the verdict stays "advisory" (nobody is asked to fix the 432) while growth reddens a
    blocking step. TWO RIDERS. A count-over-a-TOOL ratchet needs the tool VERSION bounded,
    for the reason the `mypy==2.3.1` pin already states in its own comment, and the script
    should print that version in its failure message so a rule-set change presents as
    itself rather than as mystery debt. And unlike `_ADHOC_SLICER_BUDGET` this one must
    PERMIT SLACK -- the slicer budget's zero-slack twin is right for a number only this
    repo can move, and wrong here, where a legitimate tool bump would otherwise redden a
    tree nobody touched. It caught its own author on its first run (a new test file added
    a SIM102, 432 -> 433); the finding was fixed rather than the ceiling raised.
  - **A PARKED ITEM'S STATED BLOCKER IS A CLAIM LIKE ANY OTHER -- measure it before
    honouring it (2026-09-07, NET-02):** the entry had sat parked with a specific,
    plausible reason: narrowing `safe_href`'s broad except "changes behaviour for non-str
    inputs of an app-wide sanitizer, so it wants its own reviewed slice". The reviewed
    slice found the premise false in one reading: both functions run `re.sub` on the
    input BEFORE the `try`, so a truthy non-str already raised `TypeError` outside the
    block and the broad except never covered that case. The blocker had been protecting
    nothing for as long as it had been written down. GENERAL FORM: the staleness guard is
    usually run against an item's STATUS ("is this already built?") and against its
    MEASUREMENT ("would the code still produce that number?"); run it against the stated
    REASON FOR NOT DOING IT too, because a blocker is the one part of a parked entry that
    nobody re-checks -- it reads as the conclusion of work already done. Ship the
    refutation as a test, so the next reader sees it was measured rather than overruled.
    ATTRIBUTION, because the lesson outlived the code that occasioned it: the narrowing
    itself shipped in PR #1031, from a session that found NET-02 in parallel and merged
    first. This branch's implementation was dropped; the refutation was not, because
    #1031's own block does not carry it, and it now rides beside that block as
    `test_a_non_str_input_already_raised_BEFORE_the_narrowing` (mutation-checked against
    #1031's code: move the pre-`try` work inside a re-widened except and it reddens).
  - **A DOCUMENT CAN BE RIGHT AT THE TOP AND WRONG A HUNDRED LINES DOWN, AND THAT IS
    WORSE THAN BEING WRONG THROUGHOUT (2026-09-07, J3):** the ruling asked to "document
    SQLite-only and remove the implication of dual support", and `docs/ARCHITECTURE.md`
    ALREADY did -- correctly, in detail, with the three reasons and the sentence "until
    that lands, this page will not pretend". The same file then handed out a PostgreSQL
    `to_tsvector` recipe, `psql` monitoring commands, a troubleshooting section and
    `pg_dump` backup instructions as parallel supported choices. A reader who lands in
    the middle has no way to tell which half is current, and the honest-looking top is
    what makes the bottom credible. So a staleness sweep over a DOC must not stop at the
    section that answers the question -- grep the whole file for the thing being retired,
    and treat "documented" as a claim about the document rather than about a paragraph.
    COROLLARY, from the same sections: the SQLite half was stale too, telling the reader
    to hand-build a virtual table the app already ships under a DIFFERENT name, and to
    back up by copying a WAL-mode, by-default-ENCRYPTED database file. Wrong advice about
    the supported path hides behind a correct statement about the unsupported one.
  - **A "DEAD CODE" CLAIM IS A CLAIM ABOUT A LINE, AND THE FILE MAY NOT IMPORT AT ALL
    (2026-09-07, PRH-04):** the item read "`scripts/setup_llm.py::start_ollama` is dead
    code calling `self.model_manager.start_ollama()` on a module that no longer exists",
    which describes a live script with one rotten branch and invites a one-line repair.
    Running it takes four seconds and says something else: BOTH of its imports name
    modules that are gone, so it raises `ModuleNotFoundError` at line 48 and
    `start_ollama` was never reachable from anywhere. The whole script had been
    advertised in `scripts/README.md` as the way to provision the local model. The
    difference decides the fix -- a rotten branch is repaired, a script that cannot start
    and whose capability now lives in the app is deleted, because repairing it means a
    second untested provisioning path beside the one that runs. GENERAL FORM: before
    acting on an item that names a FUNCTION, execute the module; "dead" is a spectrum and
    the item's author may have read the line without running the file.

  - **TWO SESSIONS BUILT THE SAME PARKED ITEM ON THE SAME DAY, AND THE PAPERWORK THAT
    WOULD HAVE PREVENTED IT DOES NOT EXIST (2026-09-07, PRH-03 + NET-02, PR #1035 vs
    PR #1031):** both sessions read `PARKED.md`, found the same two items, built them in
    full -- implementation, tests, a mutation matrix each -- and one merged hours before
    the other. Roughly a session of work was duplicated and then thrown away. WHAT MAKES
    THIS A LESSON RATHER THAN BAD LUCK IS THAT THE COLLISION WAS VISIBLE IN ADVANCE AND
    STILL HAPPENED: `INVENTORY.md` filed both items under **P21** while `PROMPT_20` S5
    claimed them by name, `00_INDEX.md` sets no fence between the two prompts, and the
    losing PR flagged that disagreement in its own body as "one cross-reference
    disagreement, surfaced rather than silently resolved" -- and then built them anyway,
    because a flagged disagreement is not a lock. A parked item is CLAIMABLE and nothing
    in this repository lets a session claim one: no owner column, no in-flight marker, no
    convention of opening the PR first. GENERAL FORM, for a repo that runs several
    sessions in parallel: before starting a slice whose subject is a NAMED item in a
    shared backlog, read the open PRs and the last day of `main` for that item's name --
    `git log --oneline -20 origin/main` and a `search_pull_requests` for the item id cost
    a minute, against a session of rebuilt work. AND WHEN YOU LOSE THE RACE, YIELD: take
    the merged implementation whole rather than re-landing yours over it, then keep only
    what yours has that theirs does not, and mutation-check each survivor against THEIR
    code so "additive" is a measurement rather than a courtesy. Here that came to five
    tests out of forty-three -- four negative-space cases on the redirect host check
    (three of which are the sole failure under their own mutant, so #1031's thirty tests
    demonstrably do not reach them) and the blocker refutation above. The rest was
    deleted, which is the right outcome and takes about an hour to reach honestly.

  - **THE `merge=union` DUPLICATE-ROW TRAP FIRED ON THE SWEEP THAT WARNED ABOUT IT, AND
    ITS TELL WAS THE OPPOSITE OF THE RECORDED ONE (2026-09-07, `shipped.csv`, PR #1035):**
    this session swept six `PR pending` placeholders to real numbers, and wrote into
    `OPEN_QUEUE.md` that a sweep is itself a duplicate generator because any branch cut
    BEFORE it still carries the stale text. Four hours later its own second merge of
    `main` produced exactly that: **860 rows against an expected 856**, four exact pairs
    differing in ONE column — the swept `PR #1031` beside another branch's `PR pending`
    copy of the same row. WHAT MAKES THIS WORTH A SEPARATE ENTRY is that the recorded
    TELL did not fire. The ledger says to suspect "a numstat with DELETIONS on a merge you
    expect to be purely additive"; this merge's numstat was **6 added / 0 deleted**,
    purely additive, because both sides were APPENDING their own copy rather than one side
    editing a row the other kept. A reader who had memorised the tell instead of the check
    would have shipped four duplicate rows into the project's permanent record. GENERAL
    FORM: a heuristic that has caught a bug once is not the check — it is one signature of
    the check's subject, and the subject can present differently. Run the DUPLICATE-KEY
    SCAN over `(date, area, item)` against the COMMON ANCESTOR with multiplicity preserved
    on every merge, whatever the numstat says. COROLLARY, learned in the same pass:
    fixing duplicates means DELETING rows, which is how a real row vanishes — so assert
    both directions, `introduced == 0` AND `keys present on either side but absent from
    the merge == 0`, and refuse to delete a `PR pending` row that has no
    identical-except-refs swept twin, because then it is not a duplicate but somebody's
    real, unswept row.

  - **A STATUS RE-CHECK IS ITSELF A CLAIM, AND ONE DATED TODAY CAN BE WRONG ABOUT WORK THAT
    SHIPPED TWO MONTHS AGO — search for the CAPABILITY, never for the design's own vocabulary
    (2026-09-07, PROMPT 23's staleness guard):** `docs/FUTURE_DEVELOPMENTS.md` carried a
    "Status re-check 2026-09-07 (docs-hygiene + reality-check pass)" banner listing three
    manipulation-card items as "genuinely open". Two of the three were shipped, one of them
    since **PR #568** — so the banner was not merely stale, it was BORN wrong, on the same
    day, by a pass whose entire job was checking status. The recorded 2026-08-20 lesson
    ("a status line ages faster than the finding it describes") does not cover this case:
    nothing had aged. **THE MECHANISM IS THE SEARCH VOCABULARY.** The design said the bury
    half of card #4 "needs a real external trigger", so a re-check naturally greps for a
    trigger — and the shipped implementation had resolved that blocker by a substitution the
    design never anticipated: the REST OF THE CORPUS is the trigger (a two-proportion z-test
    of the source's topic share against the rest-of-corpus share, BH-FDR corrected). Nothing
    in the code says "external trigger", so every search phrased in the design's words came
    back empty and read as confirmation. The same pass called outrage-intensity open because
    it is SECONDARY — which is its spec ("annotates, never fires alone"), not a deferral;
    that is *designed-as-partial* misread as *not built*. GENERAL FORM: when checking whether
    a designed item exists, grep for the CAPABILITY a user would get (`buried_topic`, the
    producer registry, the endpoint) rather than for the blocker the design named, because an
    implementation that solved the blocker differently is invisible to the design's own
    vocabulary — and it is precisely the item whose blocker was *interesting* that someone
    was most likely to solve creatively. COROLLARY, cheap and worth doing every time: when a
    re-check concludes "still open", cost one `git log -S` on the obvious identifier before
    writing it down; here that single command dates the answer to PR #568 in seconds. And
    when correcting such a banner, KEEP the wrong one beside the correction — a status line
    that was wrong is itself the finding, and deleting it hides that the re-check mechanism
    can fail.
  - **A DECISION RECORDED AS URGENT CAN HAVE BEEN SPENT MONTHS EARLIER, AND URGENCY IS THE
    ATTRIBUTE NOBODY RE-CHECKS (2026-09-07, same session, ruling V1-7):** the plan listed the
    storage rulings as "urgent, because they are CREATE-time irreversible", and a prompt built
    from it repeated that verbatim. Both create-time seams had already shipped —
    `_FRESH_AUTO_VACUUM` and `_FRESH_PAGE_SIZE = 16384` are the defaults in
    `src/database/connect.py`, one ruled 2026-07-17 and one shipped on a measured evidence
    pair — so no window was closing and had not been for weeks. The staleness guard is
    normally run as "is this already BUILT?"; run it also as **"is the URGENCY still real?"**,
    because a deadline attribute is written once, is never revisited by the sessions that
    inherit it, and mis-sequences whole prompts: it had this one leading with a decision that
    turned out to need only ratification. **⚠ AND THE "ONLY RATIFICATION" HALF WAS ITSELF
    WRONG — see the entry directly below, which this sentence's original sibling clause
    caused.** That clause said: ~~`page_size=16384` had been shipping on a *"FIRM
    recommendation"* and never a ruling, which is the mirror defect — a decision everyone
    treats as made because the code assumes it. When you find one, get it ratified rather
    than leaving the default resting on a recommendation.~~ It had been ruled twice over. The
    part of this entry that SURVIVES is the part about urgency, which is independently true
    and was verified against the code: both create-time seams are shipped and defaulted, so
    the deadline attribute really was spent.
  - **A CODE COMMENT MAY STATE THE EVIDENCE FOR A DECISION; WHETHER THE DECISION WAS TAKEN IS
    THE LEDGER'S TO SAY (2026-09-07, same session, and it cost a maintainer decision):** I put
    "ratify `page_size=16384`" to the maintainer on the strength of
    `src/database/connect.py`'s own comment, which read *"FIRM recommendation … not yet a
    maintainer ruling"*. It had been ruled TWICE — implicitly by merging **PR #749** under the
    §4.1.5 self-labeling convention, and **explicitly on 2026-08-13** when the maintainer said
    *"Let's consider this as finished"* and 0.3 gate row 6 was closed in `OPEN_QUEUE.md`. The
    comment simply never followed, and three weeks later it was the only thing I read. **A
    scarce maintainer decision was spent re-ratifying a settled ruling** — the one cost this
    project's whole ledger protocol exists to prevent. Two things generalise. (a) **The
    ledger is the ONLY authority on whether a ruling exists** — `OPEN_QUEUE.md` and
    `shipped.csv` — and checking it is one `grep`, so there is no version of this that was
    expensive to avoid; a comment, a design doc's status line, and a plan's framing are all
    downstream copies that go stale silently, exactly as the two entries above this one
    describe for banners and ratchets. This is the same failure a THIRD time in one session,
    which is what makes it a rule rather than a slip. (b) **The tell is a comment that
    editorialises about PROCESS.** Evidence ages well ("the 4K point-lookup win at 3 GB
    inverts at 22 GB") and stays true wherever the decision goes; process status ("firm
    recommendation", "pending ruling", "provisional until X") is a claim about a conversation
    the code cannot observe, and it is stale from the moment the conversation moves. When you
    write the second kind, you are writing a fact with an expiry date into the artifact
    nobody re-reads. Prefer the evidence and a pointer to the ledger row.
  - **A RATCHET'S VALUE IN A DOC IS NOT THE RATCHET (2026-09-07, same session):** the working
    mode named the i18n ratchets as 560 and 297; `ci.yml` pins **558 and 296**, one step
    lower, because a previous PR correctly lowered them and the doc did not follow. A session
    trusting the doc believes it has two slots of slack against gates that in fact have ZERO,
    and the recorded "lower it in the same PR that adds the keys" habit is what closes that
    gap — so the stale copy invites exactly the drift the ratchet exists to catch. Read the
    number out of `ci.yml`, never out of prose, and reproduce each of the three i18n commands
    separately (gate 1 passing is no evidence at all about gate 2 — it compares locale files
    against `en.json` and is structurally blind to a brand-new string with no key).
    **RE-EARNED THE SAME DAY, ON A RATCHET THAT DID NOT EXIST WHEN THIS WAS WRITTEN
    (2026-09-07, merging #1035):** the new advisory-ruff non-growth ratchet arrived on `main`,
    and I ran it at **442** — the number in its PR's body and in its own design doc. `ci.yml`
    pins **450**, and says why in a comment right above the step: shipping the tighter number
    *"would redden main on the merge commit over findings that are not this PR's"*. So the doc
    was not stale, it was never the gate: **the author deliberately shipped a different number
    than the one they measured**, which is a case the "stale copy" framing does not even
    cover. At 442 my branch read RED and I was one step from either fixing eight findings I did
    not write or arguing a ceiling up; at the real 450 it is green. Same instruction, stronger
    reason: `ci.yml` is the gate, and everything else is commentary about it.
    **AND THE MEASUREMENT WORTH KEEPING: that ratchet has ZERO slack.** `main` alone measures
    exactly 450 against its ceiling of 450, verified like-for-like in a detached worktree — so
    ONE new style finding in any PR reddens it, and mine had one (a `SIM108` in
    `src/civic/elections.py`). Fixed rather than argued, per the ratchet's own rule and its
    author's precedent of fixing the finding their own first run caught. The general point:
    when a ratchet lands at zero slack, measure the BASE BRANCH before concluding the red is
    yours — the delta is the only number that says whose finding it is.
  - **THE `shipped.csv` UNION-MERGE DEFECT HAS A THIRD FORM, AND THE RECORDED TELL DOES NOT
    FIRE ON IT — only the duplicate-key scan does (2026-09-07, merging #1041 with main's
    #1021 sweep):** the ledger already records this collision twice, and both times the
    diagnostic offered was *"the tell in the diff is a numstat with DELETIONS on a merge you
    expect to be purely additive"*. **Here the numstat was 17 added / 0 deleted — flawless —
    and the file was still corrupt.** The mechanism is worth stating exactly, because it is
    the case both earlier entries describe from the other side: main had EDITED two rows
    (sweeping their `refs` to add `PR #1021` per rule 5b), my branch carried the ancestor's
    unedited copies, and `merge=union` **added main's corrected row without removing my stale
    one**. Nothing is deleted, so there is nothing for a deletion-count to notice; the union
    did exactly what union means. So the earlier entries' tell is a symptom of *some*
    instances, never a test for the class — the only check that sees it is the one those
    entries also name and which is easy to skip once the numstat looks clean: a
    DUPLICATE-KEY scan over `(date, area, item)` compared against the COMMON ANCESTOR (9
    pre-existing here; 11 after the merge). Run it on every merge that touches the file,
    whatever the numstat says.
    **THE REPAIR HAS ITS OWN TRAP, and I walked into it:** having found the two stale rows, I
    rebuilt the file through `csv.writer(lineterminator="\n")`, which normalised all 22 CRLF
    rows and turned a 2-line fix into **57 added / 42 deleted** — the recorded
    "`read_text()` normalises line endings" lesson, re-earned in the repair for the defect
    beside it. The safe rebuild needs no CSV round-trip at all: *the union minus the stale
    ancestor copies IS main's file plus your own new rows*, so take `MERGE_HEAD`'s bytes
    verbatim and append, which preserves every existing line by construction. Verify with
    `git diff --ignore-cr-at-eol --numstat` AND a raw CRLF count, since the first flag hides
    exactly the damage the second measures.
    **SIBLING, from the same merge: a verification assertion can be wrong in the safe
    direction and still cost you.** Resolving the three ledger `.md` conflicts I asserted
    that nothing outside the conflict hunk had moved — which assumed every addition lands at
    the TAIL. Main had inserted an entry at the HEAD of the Open-queue section, git
    auto-merged it correctly, and my assertion fired on a perfectly good resolution. A
    guard that reddens on correct code gets relaxed, and a relaxed guard catches nothing, so
    the fix is not to loosen it but to assert the property that actually matters: every line
    EITHER side added relative to the common ancestor must survive in the result. That one
    holds whatever the insertion point, and it is what proves an additive merge additive.
- **A SIZE RATCHET WITH ZERO SLACK STILL HAS A BLIND SIDE: IT CANNOT SEE A REMOVAL (found
  2026-09-08, audit edition 10, P1-08):** `_CLAUDE_MD_LINE_CEILING` (rule 5c) was measured at
  exactly 616 immediately after the 2026-09-07 A3 restructuring split `LESSONS.md` and
  `OPEN_QUEUE.md` out of `CLAUDE.md` — and in that same edit, six numbered UI-invariant
  paragraphs (#9, #10, #11, #12, #13, #22) were lost, with a dangling cross-reference
  ("invariant #13 in test_ui_invariants") left pointing at nothing. `test_ui_invariants`
  never stopped enforcing all six mechanically, so the loss was invisible to every test in
  the suite except the one thing that could have caught it and didn't: the ratchet itself,
  because a smaller file only ever reads as SLACK to a `<=` check, never as a violation. A
  ceiling that fires on growth past a number is not the same guarantee as "the protected
  content is still present" — the two were conflated here because the ratchet was born at the
  same moment as the loss, so its first honest measurement already excluded the missing
  content and had nothing to compare against. The general lesson: a line/byte-count ratchet
  on a document that also carries NAMED, individually-load-bearing sections (numbered
  invariants, in this case) protects the whole only against bloat, not against a shrink that
  quietly drops one of the named things — that needs its own check (here, restored by this
  same fix: the six numbers are back, the cross-reference resolves, and the ceiling was
  re-measured to 665). No content-presence guard for individual invariant NUMBERS existed
  before or after this fix beyond `test_ui_invariants` itself asserting their DOM/JS
  fingerprints — which is real enforcement of the behavior, just not of the constitution's
  own prose describing it. Worth a maintainer decision, not resolved here: whether a cheap
  "every `#N` referenced by test_ui_invariants's own comments has a matching CLAUDE.md
  paragraph" check is worth adding, or whether periodic human/audit review remains the
  intended catch for this specific failure mode.

- **SUBSTRING CONTAINMENT USED WHERE IDENTITY IS MEANT IS NOW A TWICE-FOUND P0 CLASS IN THIS CODEBASE,
  IN TWO UNRELATED SUBSYSTEMS, AND THE GUARD FOR IT WAS ALREADY WRITTEN BOTH TIMES (2026-09-08, live
  visual audit §4.1):** the commodity Price × coverage overlay draws a clean chart headed
  "Price × coverage — Dy · Articles: 36" in which `Dy` has been silently resolved to the English word
  **"already"** (`alrea·dy`), `Nd` to the French **"indiqué"** (`i·nd·iqué`) and `Pr` to **"proposed"** —
  because `resolve_keyword()` (`src/analytics/queries.py:149`) falls back from exact match to
  `normalized_term LIKE '%term%'` ordered by mention count. Terms with no substring collision (`lithium`,
  `cobalt`) resolve to nothing, which is exactly **why it never looks broken**: the failure is invisible
  on every term that would have exposed it. The same window's Keywords, When/Where/Who and Sources
  lenses all honestly report zero for the same seed — **only the lens with a chart lies**, so a
  cross-lens consistency check inside one window is a cheap, general detector for this whole class.
  THE PART THAT MATTERS MOST: `src/analytics/supply_chain_ripple.py:110` already carries
  `_exact_keyword_id` whose docstring names this exact hazard, this exact fallback, and even the exact
  worked example ("a commodity 'Lead' silently matching the unrelated common word/verb 'lead'") — the
  hazard was identified, the guard was written, the reasoning was recorded, and the commodity path calls
  the **unguarded** resolver anyway. Six weeks earlier the 2026-09-08 transversal audit found the same
  shape in `src/bulletin/grounding.py`, where a fabricated figure that is a substring of a real one
  verdicts as grounded. **A guard that lives in one caller is a comment, not an invariant.** **AND IT IS THREE, NOT TWO (same session, found later the same day):** the Observatory's ranked-table drill-through calls `openAnalysisFor(hit.name)` (`app-observatory.js:444`), passing a curated keyword-CLUSTER LABEL into the analysis window as a LITERAL FULL-TEXT QUERY — measured, `"Elections & democracy"` (the corpus's #1 galaxy) returns `total=0` while `"Public finance"` returns **19 unrelated articles presented as that galaxy's evidence**, against its real 150-mention/6-source membership, with nothing signalling the mismatch. **The shared shape across all three is not "substring" — it is FAILING OPEN INTO A PLAUSIBLE ANSWER INSTEAD OF CLOSED INTO AN HONEST REFUSAL**, which is exactly why none of them looks broken and none was caught by a test: the empty case is visible and merely unhelpful, and the coincidental-match case is invisible and wrong. The rule worth writing as a test is therefore about the DIRECTION OF FAILURE, not about `LIKE`: where a display surface resolves an identity, a text match may never stand in for it, and a failure to resolve must render the honest empty state rather than the nearest thing found. When a
  fuzzy resolver and an exact resolver both exist for one quantity, the fuzzy one is the default every
  new caller will reach for; the durable fix is a test that enumerates the callers of the fuzzy path and
  asserts that none of them is a display surface, not a third exact-match helper in a third file.

- **AN EMPTY STATE REACHED THROUGH A PARSE FAILURE IS THE APP STATING A FALSEHOOD IN THE VOICE IT
  RESERVES FOR FACTS (2026-09-08, live visual audit §4.2):** with `/api/briefing` and
  `/api/database/stats` returning HTTP 200 and a malformed body, Home rendered "**Your library is
  empty** — head to Collect to gather your first material" and "**No Leads yet** … an empty feed means
  the signals haven't accumulated, **never** that the engine is gone" against a database holding 453
  articles and 3,618 sources — with zero occurrences of *failed*, *error*, *unavailable* or *retry*,
  zero uncaught exceptions, and the health pill still reading **healthy**. The empty-state copy is
  genuinely good writing and correct for a genuinely empty corpus; that is what makes this dangerous.
  **"Degrade loudly" is not satisfied by a well-written empty state, because an empty state is a
  positive claim about the user's data.** The distinction a UI must keep is not success-vs-failure but
  *"the server answered and the answer was empty"* vs *"the answer could not be read"* — and a
  `try/catch` that falls through to the render path collapses exactly those two. Test the malformed-body
  case, not only the 500 case: a 500 usually has a handler, and a 200 with garbage usually does not.

- **A `#`-ANCHOR ANYWHERE IN CONTENT IS A NAVIGATION HAZARD WHEN A `popstate` HANDLER TREATS THE HASH AS
  A TAB NAME (2026-09-08, live visual audit):** Help renders 50 visible in-page table-of-contents links
  against **103 headings, of which 0 carry an `id`** (`mdToHtml()` emits bare `<h2>/<h3>`). Clicking one
  changes the hash, `app-shell.js:166`'s `popstate` listener calls
  `showTab(location.hash.slice(1), false)`, `showTab` finds no `tab-1-install--first-run`, falls back to
  home and rewrites the URL — measured: visible panel `tab-help` → `tab-home`, hash `#help` → `#home`.
  **The defect is not in Help.** Any surface that ever renders an internal anchor — an article body, a
  law document, any future markdown — hits the identical path, so this is a risk *category* rather than
  a documentation bug, and the fix belongs in the `popstate` handler (check the hash against the known
  tab-id set before calling `showTab`, else let the browser do its native in-page scroll), not in the
  markdown renderer alone.

- **A CONTRAST HARNESS THAT EXCLUDES THE ELEMENT'S OWN BACKGROUND IS WRONG IN BOTH DIRECTIONS, AND TWO
  AGENTS CATCHING IT INDEPENDENTLY IS THE ONLY REASON IT WAS CAUGHT (2026-09-08, this audit's own
  instrument):** the first cut composited text against the *ancestor* chain and popped the element
  itself, so a filled button's label was scored against the panel *behind* the button — inventing
  failures on filled controls (two were hand-verified at a real 6.65:1) and missing real ones. The
  recorded lesson "score the composited colour, not the declared token" is necessary and **not
  sufficient**: the composite must include every layer the text is actually painted on, the element's own
  `background-color` first among them. Corrected mid-run and the whole 17-theme sweep re-run; one agent
  finding was subsequently REFUTED by its own verifier using the fixed instrument. **An audit's
  instrument is part of its subject matter** — when two independent agents report the same
  false-positive class, that is data about the tool, not noise from the agents.

- **ASSIGNING ONE APP INSTANCE TO TWO AGENTS MANUFACTURES A FINDING (2026-09-08, fleet hygiene):** port
  8020 was handed to both a first-run-journey agent and a first-launch-state agent. The first created a
  passphrase; the second then reported as a P0 that "the assigned virgin locked instance was already
  unlocked-encrypted before this session began." It was a true observation and an entirely manufactured
  defect. **A stateful fixture is single-assignment.** Where two agents genuinely need the same
  irreversible flow, give them separate data directories, and treat any finding about the *initial state*
  of a shared fixture as suspect until the assignment map is checked.

- **A CONSOLIDATION JOIN KEYED ON A SHORT LOCAL ID SILENTLY CROSS-WIRES AGENTS (2026-09-08, the same
  audit's own bookkeeping):** merging 466 findings with their verifiers' verdicts on the bare finding id
  (`F1`, `LAW-1`) attached one agent's verdict to another agent's finding, because a dozen agents each
  number their findings `F1…Fn` independently. The tell was the row count changing when it should not
  have. Key the join on **(workflow, scope, id)** and, where a scope string is decorated
  ("law (port 8013, ink theme…)"), match by token overlap rather than equality — and always print
  matched-vs-unmatched counts, because a join that silently drops or mis-attaches is indistinguishable
  from one that works.

- **A SYNTHESIS FED A TRUNCATED BLOB REPORTS THE GAP AS THE APP'S, NOT THE HARNESS'S — AND IT DOES IT
  MOST CONFIDENTLY IN THE HONESTY SECTION (2026-09-08, the visual audit's own matrix workflow):** the
  workflow script handed its ten stream results to the synthesiser as
  `JSON.stringify(ok).slice(0, 220000)`. The blob was larger, so four streams fell off the end, and the
  synthesis stated in its coverage section that "none of the 8 GUI-gallery skins were tested by any
  agent in this batch" and that "`reduced_motion`, `prefers-contrast` and any browser-zoom test were
  never exercised" — when both skin agents had run 164 combinations and the media-prefs agent had
  exercised all three plus greyscale, colour-blind simulation and a full axe pass. It also reported 365
  combinations against an actual 599. **Every one of those sentences is the good behaviour — an agent
  saying what it did not reach — pointed at the wrong subject**, which is exactly what makes it
  dangerous: the section a reader trusts most is the section a truncated input corrupts first, and it
  corrupts it into a *false negative about coverage*, the one error class an honesty section exists to
  prevent. TWO RULES FOLLOW. (1) Never silently `.slice()` an aggregate into a synthesis prompt: pass a
  count alongside it (`N streams, M findings`) so the synthesiser can notice the arithmetic does not
  add up, or summarise per-stream first and synthesise the summaries. (2) When a synthesis claims
  something was **not** covered, check that claim against the per-agent results before repeating it —
  a coverage claim is the cheapest of all claims to verify and the most expensive to get wrong.

- **AN INSTRUMENT THAT RETURNS "NOTHING FOUND" FOR AN INPUT IT CANNOT PARSE CERTIFIES A FIX AS A SUCCESS
  ON EXACTLY THE GROUND THE FIX CHANGED (2026-09-09, the visual audit's contrast harness, second defect
  in the same tool):** the scan's colour parser matched only `rgba?(...)` and returned `null` for
  anything else; every caller read `null` as "nothing here" and skipped the element. Chromium serialises
  any colour computed through `color-mix()` as `color(srgb 0.32 0.39 0.34)` — 0–1 floats, no `rgb(`
  anywhere. Four theme contrast fixes had just re-derived `--muted`/`--accent-text` *through*
  `color-mix()`. So the post-fix sweep returned zero failures for those four themes, and the zero meant
  the instrument had stopped looking at precisely the elements the fix touched. The failure is worse
  than the harness's earlier composited-background bug (recorded above) because that one INVENTED
  failures — noisy, self-announcing — while this one HID them, silently, in the direction of the answer
  everyone wanted. THREE RULES. (1) **An unparseable input is a reported count, never an empty list**:
  the corrected scan returns a `__UNPARSED_COLOURS__` record at the head of its results with the
  syntaxes and occurrence counts, so an unknown form arrives as a number rather than a clean sweep.
  (2) **When a fix changes the REPRESENTATION of the thing being measured — a token becomes a function,
  an id becomes a hash, a scalar becomes an object — re-validate the instrument before believing the
  green.** The check to run is the one that was run here: inject a deliberately, unmissably failing
  case IN THE NEW REPRESENTATION (a `color-mix()` at 1.15:1) and confirm the instrument reports it;
  the old parser said `total_failures: 0` and the corrected one said `ratio: 1.15`. (3) A theme the
  broken sweep flagged (`mint`) still had to be re-measured end to end after the instrument was fixed —
  4.18:1 before, ≥4.99:1 after — because a number produced by a broken instrument is not evidence even
  when it turns out to be right.

- **A DEFECT CLASS IS NOT FIXED UNTIL YOU HAVE ENUMERATED ITS CALL SITES; FIXING "THE ONE THE AUDIT
  NAMED" LEAVES THE OTHERS, AND THEY ARE WORSE (2026-09-09, audit §4.1's fuzzy `resolve_keyword`
  fallback):** the audit hand-verified ONE surface — `GET /api/insights/trend?term=Dy` resolving to the
  English word "already" — and the fix routed `queries.py`'s five display callers through `exact=True`.
  That was correct and it was not the class. A `grep` for the function turned up eleven call sites, and
  two more of them were the same defect: `src/briefing/producers.py`'s `price_narrative`, which does not
  merely LABEL a chart but runs a significance test on the mis-resolved keyword and publishes the result
  to Home as a Lead ("Dy: price moves vs coverage — correlate +0.97 (p=0.00522, n=5)", card key
  "already"); and `src/api/link_analysis.py`'s `/api/links/shared`, which feeds the corpus window's Links
  subtab. **THE LINKS ONE IS THE INSTRUCTIVE CASE**, because it shows what an incomplete fix costs: after
  the first fix, one corpus window seeded on `Dy` answered `resolved: null` on Trend, Context and
  Keywords — honestly empty, exactly as intended — while Links quietly returned 36 articles about
  "already". The partial fix did not just leave a hole; it made the hole *more* convincing, because the
  surfaces around it had started telling the truth. Enumerate the call sites, decide each one
  deliberately (a genuine human-typed search box may legitimately stay fuzzy), and record which ones you
  left and why. COROLLARY, from the same pass: the fix's own docstring listed `producers.py` among the
  callers "unchanged by this fix" — and was falsified an hour later by the follow-up fix to that very
  file. A docstring that enumerates other modules' behaviour is a claim with a shelf life; the reviewer
  who spots it stale is the lucky case.

- **THE `test` CI JOB IS NOT ONLY pytest, AND THE STEP AFTER IT IS THE ONE A LOCAL GREEN SUITE HIDES
  (2026-09-09):** three commits in a row failed CI's `test` job on this branch while the local full
  suite passed 9967/0 and CI's own pytest step passed 9975/0. The failure was the **mypy step that runs
  after pytest in the same job** — one `union-attr` error, from a `Retry-After` fallback reading
  `exc.limit.limit` where `exc.limit` is typed `Limit | None`. `CLAUDE.md`'s session rituals already say
  "mypy ratchet ≤ baseline in CI", so this was a ritual skipped rather than a rule missing: `pytest -q`
  green reads as "the tests pass", and the job is called `test`, and both of those make it easy to stop
  before `python -m mypy src/`. **Run every step the job runs, not the one that shares its name** — for
  this repo that is `pytest`, then `mypy src/`, then the ruff blocking lane, the ruff ratchet and the
  i18n gate. The fix itself is worth a line too: the None case was handled by *checking* it rather than
  by widening the `except`, because an `AttributeError` swallowed by a bare `except` is
  indistinguishable from a genuine failure to read the value, and that branch's whole job is to be the
  honest last answer.

- **A TEST THAT SAMPLES TWO QUANTITIES MUST GATE ITS WINDOW ON BOTH, OR THE UNGATED ONE BECOMES A COIN
  FLIP AT THE MERCY OF THE RUNNER (2026-09-09, `test_wal_reader_starvation.py` on the Linux core-only
  lane):** this test had already been round the loop once. Its window was time-boxed, three CI lanes
  failed because the WAL volume depended on how many writes a runner fit into that time, and the authors
  made the window WRITE-GATED — recorded at length in the module docstring. What that fixed was the
  volume; what it left alone was the *other* sampled quantity, the number of checkpoint attempts landing
  inside the window, which stayed a pure function of thread scheduling. The comments show the authors
  feeling this without naming it: they cut the checkpointer's sleep 0.05 → 0.02 because "at 0.05s left
  only 2 attempts". CI then produced **1**, and with one attempt the discriminating assertion is a coin
  flip — releases happen every `_TEST_RELEASE_INTERVAL_S`, so a lone attempt can miss all of them and
  report busy on FIXED code. The general rule: **whatever a test measures, gate on it.** The window now
  waits for a sample floor the same way it waits for writes, and falls short LOUDLY rather than
  measuring something meaningless. THREE THINGS THIS COST, all worth repeating. (1) The first mutation I
  ran to check the guard still bit targeted `_release_transaction` and the mutant SURVIVED — I was one
  step from reporting "this guard is toothless, pre-existing", when the registry's own docstring says
  plainly that a bare `commit()` does not free the WAL read-mark and `result.close()` does. **A
  surviving mutant means the guard is weak OR the mutation was wrong, and those look identical.** (2)
  Adding a second reason for the window to time out made a pre-existing failure message
  self-contradictory — "hit its cap before the writer committed 12 times (only 33 landed)" — because it
  had only ever had one reason to fire. Widening a condition means auditing every message that explains
  it. (3) Both the fix and the message now have their own forced-failure probes, because a branch that
  cannot be shown to fire is indistinguishable from dead code.

- **A GUARD THAT ASSERTS OVER A WHOLE OBJECT LITERAL PASSES ON THE COMMENT — AND ON THE WRONG KEY
  (2026-09-09).** A test read `_ADV_LOADERS` whole and asserted `"loadSources()" in loaders`. Deleting
  the call left the guard green, because the comment ABOVE the call still said the word — the exact
  family `js_source_helper`'s own docstring records, and the reason `strip_comments` exists. But the
  second half is worse and is not in that docstring: the whole-literal read would ALSO have passed with
  the call moved into the WRONG ENTRY, which is precisely the failure the test existed to catch (a
  loader in the `sources` fold does not open the `collect` fold). Both mutants survived the first
  attempt. **Slice to the one entry you are claiming about, strip comments, and mutate the wrong-place
  case as well as the missing case** — "present somewhere in this literal" is a much weaker claim than
  it reads as.

- **A CONSTANT THAT APPEARS ON BOTH SIDES OF AN ASSERTION IS NOT PINNED BY IT (2026-09-09).** The VACUUM
  preflight's whole safety argument is the number 2.0 — SQLite writes a complete second copy of the
  database before swapping it in. The test asserted `needed_bytes == db_bytes * VACUUM_HEADROOM`, which
  holds for *any* value of the constant, **including 1.0**, the value that says the rebuild needs no room
  of its own. Dropping it to 1.0 passed every other test in the file. The repair is behavioural and
  comes in a PAIR: a volume with room for the file but not for the copy must be REFUSED, and ample space
  must still be ACCEPTED — otherwise a headroom raised until nothing ever passes satisfies the first
  test while breaking every real vacuum. **When a constant carries the argument, assert the behaviour on
  both sides of it, never the arithmetic that contains it.**

- **`display:none` HIDES FROM THE SCREEN READER TOO, AND AN ICON RAIL IS EXACTLY WHERE THAT BITES
  (2026-09-09).** The sidebar's rail hid every nav label with `display:none`. Those labels are the ONLY
  accessible name each nav button has — no `aria-label`, no `title` — so the app's entire primary
  navigation announced as six unnamed buttons, `button-name` CRITICAL. The page's one level-1 heading
  lives in the same hidden container, so one rule produced two findings. Hide a label VISUALLY (the
  `.sr-only` clip) and it keeps its name. **Clip rather than `aria-label`**: an aria-label is a second
  copy of every tab name, in twelve locales, that the i18n walker does not maintain, so it drifts.

- **WIDENING A SWEEP FINDS WHAT DEEPENING IT CANNOT — AND A "RESPONSIVE" DEFECT IS RARELY WIDTH-ONLY
  (2026-09-09).** Ten surfaces measured ZERO axe violations at 1440×900. The identical run at 768×1024
  reported a CRITICAL on every one of them. Before concluding a class is clean, run the same instrument
  at the other breakpoints — the cost is minutes and the finding was invisible otherwise. And do not
  file it as a tablet bug: the same rail is applied by `html[data-sidebar="collapsed"]` at ANY width, and
  collapsing the sidebar is a first-class documented affordance, so a desktop reader who used it was in
  the same rail. **Ask what else turns the state on before scoping the fix to the viewport that revealed
  it.**

- **AN "ORPHAN TO DELETE" CAN BE AN "ORPHAN TO RE-TRIGGER" — ASK WHAT IT IS THE ONLY PATH TO
  (2026-09-09).** The dead-code worklist listed `loadIndicesData`/`loadMarketData` as unreferenced
  functions to remove. Two later audits, one filed under HONESTY, said restore their buttons instead.
  The deciding fact is not which record is newer: `_renderFeedVerdicts` has **no other entry point**, so
  deleting them would have removed the app's only surface for "this official feed refused" — the exact
  opposite of degrading loudly. **Before deleting unreachable code, grep what it uniquely reaches.**
  Unreachable is a statement about callers, not about value.

- **A CONSENT-GATE CHECK AGAINST AN ALREADY-ONLINE FIXTURE PROVES NOTHING (2026-09-09).** The audit
  harness boots with `OO_NO_SCHEDULER=1`, and the boot-time kill-switch activation lives inside the
  `OO_NO_SCHEDULER != 1` block — so that instance starts ONLINE, `ensureOnline` returns true immediately,
  and the popup never appears. A first pass read that silence as "no consent popup" and nearly filed it
  either as a defect or as a pass. **Engage airplane mode explicitly before asserting anything about a
  gate**, and state which state the observation was made in.

- **A FIX IN UNREACHABLE CODE IS A SOURCE FIX, NOT A LIVE ONE — AND SAYING WHICH IS PART OF THE FIX
  (2026-09-09).** A truncation defect was repaired in `renderCorpusSources` and the commit described it
  as fixing "the analysis window's Sources sub-tab". It is not that surface: the function is reached only
  through the retired `#corpus-win` modal that nothing opens. The repair was real in the source and
  unreachable at runtime. **Grep the call chain to a live entry point before describing what a fix
  changes for a user.** The correction paid for itself — checking the live surface found that the
  window claimed to be a "strict superset" of the retired modal and had silently dropped one of its
  columns.

- **A FIXTURE THAT WRITES ROWS THE READ PATH DOES NOT READ IS AN UNFAITHFUL CORPUS (2026-09-09).** A test
  corpus inserted `keyword_mentions` directly and the ranked table came back with **0 mentions** beside a
  correctly-resolved pair of keywords. The table reads the DENORMALISED `Keyword.mention_count` counters
  the app maintains at index time, not the mention rows. That surprise was useful twice: it made the
  fixture faithful, and it narrowed an over-wide claim — the endpoint had said the table and the set it
  opens "cannot disagree", when what is guaranteed is MEMBERSHIP; the counts are a separate store with
  their own freshness envelope. **When a fixture's numbers come out wrong, suspect the read path before
  the write.**

- **THE ENGINE BINDS ONCE PER PROCESS, SO A FUNCTION-SCOPED FIXTURE THAT RE-POINTS `OO_DATA_DIR` GETS THE
  FIRST STORE (2026-09-09).** Two such fixtures in one file: the second setup hit `UNIQUE constraint
  failed: sources.domain`, and its half-flushed session then left the single-writer write gate HELD,
  which `conftest`'s own guard reports as "would hang the next writer". Make store-building fixtures
  **module-scoped and idempotent** (look rows up before creating them), and close the session in a
  `finally`.

- **TWO RESOLVERS FOR ONE QUANTITY DIVERGE EVEN WHEN THEY AGREE TODAY (2026-09-09).** The Observatory's
  drill-through resolved a galaxy's membership from term STRINGS while the galaxy's own numbers came from
  an id resolver that also matches a family member's `canonical_key` variants. On the live corpus they
  agreed on every super-group — because every member there happens to be a ring member, so the family
  branch never fires. That is what made the defect latent, **not what made it safe**. A two-article
  corpus with a possessive variant reproduces it in one query. **When a "measured latent" divergence has
  a construction that reproduces it, the honest close is to remove the second resolver, and the guard
  must assert the two really do disagree on its fixture before asserting which one is right** — otherwise
  it passes vacuously on every corpus where they agree.

- **A CHARACTER-CLASS CAPTURE SILENTLY SKIPS THE MALFORMED VALUE IT WAS MEANT TO CATCH (2026-09-09).**
  A guard sampled chart coordinates with `matchAll(/<rect x="([0-9.]+)"/g)` and then asserted every
  sample was finite. `x="NaN"` does not match that class, so the bad mark **dropped out of the sample**
  and the assertion passed over the remaining good ones. The mutation that removes a per-point date
  fallback — turning one mark's x into `NaN`, which a browser then silently declines to draw — survived
  **twice** on this blindness before the capture was widened to `([^"]*)`. **A guard must be able to SEE
  the value it rejects**: capture permissively and validate explicitly, never let the pattern do the
  validating. The same shape hides any "unparseable" case behind a "well-formed" regex.

- **A SECOND RENDERER RE-DERIVES THE RULES, AND GETS THEM WRONG — SO SHARE THE RULES EVEN WHEN YOU KEEP
  TWO RENDERERS (2026-09-09).** The indices tile's 42px `idxSpark` sat beside `dashChartSvg` and had
  independently reproduced all three things the shared toolkit exists to refuse: index placement (on a
  board whose end-of-day series skip weekends *by nature*, so it is the difference between "closed on
  Monday" and "no gap"), one path drawn straight through a hole, and a line through as few as two points.
  Whether the two renderers should become one is a LAYOUT decision — the tile is deliberately small and
  the card's click opens the full interactive chart — but the honesty rules are not. **Invariant #16's
  "ONE toolkit" is not about the number of functions; it is that the rules must not be re-derived per
  surface.** Point the second renderer at the same helpers (`_seriesRuns`, `_SPARSE_BAR_MAX`) and leave
  the layout question to the maintainer.

- **A SOURCE-GREP GUARD CANNOT SEE A FALSY-BUT-STATED VALUE — DRIVE THE FUNCTION (2026-09-09).** The
  agenda's new span/year rendering was guarded by six assertions over `agRow`'s source, and they killed
  five of six mutants. The two they could not reach were behavioural: `origin_year != null` degraded to
  `if (e.origin_year)` still contains every substring the grep looks for, and so does a `join(" · ")`
  that leaves a dangling separator when one half of the range is absent. A node suite that EXTRACTS the
  shipped function by name and EXECUTES it caught both in one line each. **The rule: guard the source for
  what must stay present, and drive the function for what must be TRUE.** The two are different tests and
  neither substitutes for the other — the grep survives a browser CI cannot run, and the drive survives a
  refactor that keeps every keyword.

- **SHIPPING A DISPLAY FOR DATA NOBODY HAS ENTERED IS HALF A FIX, AND THE HALF MUST BE NAMED
  (2026-09-09).** `catalog.py` computed month-spans and `origin_year`/`until_year` for six weeks with its
  own test file while `agRow` read none of it. Wiring the display took an hour; then
  `grep -c "end_month\|origin_year\|until_year" configs/world_events.yml` returned **0** — no shipped
  event exercises any of it, so the surface renders nothing today. The temptation is to add a plausible
  entry ("Dry January runs 01-01 to 01-31, held since 2013") and call the item closed. That is inventing
  sourced facts, which is the thing this project refuses everywhere else. **Ship the code half, then
  record the content half as blocked on RESEARCH rather than on code, and say in the ledger row that the
  improvement is not yet visible.** A row that reads "shipped" over an unexercised surface is how a future
  session comes to believe a feature works.

- **REASONING ALREADY DONE DOES NOT TRANSFER ITSELF TO THE NEXT LINE — THE DIFFERENTIAL IS WHAT
  CATCHES IT (2026-09-09).** Six wikitext patterns got a linear scan whose skip rule is sound only
  for families whose body cannot cross the skip target. The docstring for `[url label]` already
  spelled out, with a counterexample, why `\S+` breaks that: it crosses `]` freely, so a match can
  END past the first `]` after its opener. The line directly below it — `[url]`, the same `\S+`, the
  same `]` — was written with the strong rule anyway. No amount of re-reading found it; a randomised
  differential over a few thousand generated documents found it in seconds, on
  `"[https:// [https://]] "`, where the skip lands past a real match and it is silently lost.
  **When a change's correctness rests on a per-case argument, write the cases down AND generate
  inputs — the argument you already made is exactly the one you will stop re-checking.**

- **A FIX INSIDE THE MODULE WRITTEN TO PREVENT THAT FIX'S PROBLEM (2026-09-09).** After all six
  quadratic substitutions in `plain_from_wikitext` were linear, the `<ref>` shape was still
  quadratic end to end. The cause was `strip_blocks` — the linear block scanner built two days
  earlier *specifically* to kill this shape — searching with the OPENER pattern `<ref[^>]*>`, which
  is the shape. `re.Pattern.search` carries the same cliff as `re.Pattern.sub`, for the same reason,
  and a scanner that takes a regex as a parameter inherits whatever cliff that regex has. It was
  found only because the end-to-end linearity test was WIDENED from the two shapes it used to claim
  to all ten that reach the function; the narrow test was green throughout. **A test that asserts a
  property for the cases you fixed will not tell you about the case you did not think of — widen
  the property to everything that reaches the code, and let it fail.**

- **A CHEAPER ANCHOR CAN BE A CORRECT ANCHOR AND STILL BREAK THE SKIP (2026-09-09).** The linear
  driver needs a cheap prefix that marks every position the real pattern could start at. `[[` marks
  every start of `[[File…]]`, is a literal (twice as fast as a compiled regex through `str.find`),
  and is WRONG: with `[[` the attempt fails at the WORD rather than at the closer, and the skip rule
  is licensed by a failure at the CLOSER. `"[[x[[File a]]"` then loses a real match. **The
  precondition is "the anchor IS the pattern's fixed prefix", which is strictly stronger than "the
  anchor marks every start" — and the weaker reading is the one that looks obviously right while
  someone is optimising.** Kept as a named test with the counterexample, because the next
  performance pass will reach for exactly that change.

- **A DOCKET ENTRY CAN FILE A PRODUCT DEFECT AS A CHORE, AND THE FILING IS WHY NOBODY LOOKS
  AGAIN (2026-09-09).** `test_doctor_healthy_returns_zero` was recorded as an order-dependent
  test needing "a future test-hygiene pass" — a category that reads as *our tests are untidy*,
  which nobody urgently reads. It reproduced in one command, and the cause was not the tests:
  `doctor` reported a database file that exists with no tables as a CRITICAL, with the driver's
  fifteen-line `SELECT` dump as its detail, in a report written for someone who is not a
  programmer. The state is reachable by a real operator (an interrupted first launch; a
  stamped-but-unupgraded database), and the branch directly above already handled the same
  situation gracefully when the file was merely absent. **GENERAL FORM: when a test's failure is
  attributed to test hygiene, ask whether the assertion it makes is one a USER would also make.
  If it is, the ambient state it stumbled into is a state a user can be in, and the test found a
  defect rather than caused one.** Verified by mutant which half carried it: the product fix
  alone closes the ordering failure; the test's own tidy-up changes nothing.

- **PRICE THE CHECK A DEFERRAL ASKS FOR, NOT THE CHANGE IT DEFERS (2026-09-09).** The docket
  had carried "fr publishing furniture still leaks — a fr batch would globalise
  (collision-check needed); low-df, deferred" for months. The deferral was reasoned, and its
  cost model was wrong: the *change* needed corpus measurement, but the *check* was
  corpus-independent and took one query. It came back NO — `fr:publicité` is the French member
  of the Wikidata-verified `advertising` ring, so the edit would have deleted the French side of
  a concept English keeps, which is the blind-by-language filter the maintainer rejected in
  2026-06-19. **And running it found the larger thing nobody had looked for: the same mechanism
  already fires in the opposite direction, 38 times, unmeasured** — `fr:dette` (debt) killed by
  Danish *dette*, `pt:lei` (statute) by Italian *lei*, and `de:Podcast`/`fr:podcast`/`pt:podcast`
  removed from the *podcast* ring by the deliberate global "podcast" furniture entry, the rule
  eating its own ring. **GENERAL FORM: a deferral names its blocker; check whether the blocker is
  the decision or the evidence, because evidence often costs a fraction of what the deferral
  assumed — and a check run for one direction reports on both.**

- **REMOVING A `GROUP BY` KEY TO MERGE DUPLICATE ROWS SILENTLY DOUBLES THE AGGREGATES
  (2026-09-09).** `keywords_by_tag` grouped by `(Keyword.id, KeywordTag.source)`, so a keyword
  tagged by both the baseline pass and the operator came back twice. The obvious repair — drop
  `source` from the `GROUP BY` — removes the duplicate row and is worse than the bug: the two tag
  rows FAN OUT the outer join to `KeywordMention`, so `sum(count)` doubles while
  `count(distinct article_id)` stays right, which is exactly the pattern that survives a
  cursory check. The fix is to select the matching keywords as a DISTINCT id subquery and take
  the aggregate against that, with the tag table absent from the aggregating query. **GENERAL
  FORM: the row count is the symptom you were looking at, so it is the thing you will verify.
  When a `GROUP BY` key is removed, re-derive every aggregate in the same `SELECT` — a wrong
  number looks exactly like a right one.**

- **A TEST FOR "THIS IS ASYNCHRONOUS" MUST OBSERVE DURING, NOT AFTER (2026-09-09).** The first
  guard that the mailbox pull is enumerable in `/api/jobs` joined the worker thread and then
  asserted the job was listed. It failed — correctly, because `/api/jobs` lists running and
  failed jobs, and a finished one is neither. Rewritten to block the fake fetch on an event and
  read `/api/jobs` while the worker is stuck, it proves the thing that matters: the request
  already returned while the work is still going. **GENERAL FORM: the old synchronous
  implementation passes any assertion made after the work is done. Put the observation inside
  the window the change created, or the test is about nothing.**

- **`git checkout <file>` RESTORES TO THE INDEX, WHICH IS NOT WHERE UNCOMMITTED WORK IS
  (2026-09-09).** Mid mutation-run, a mutant was reverted with `git checkout -q src/api/jobs.py`
  on a file carrying an *uncommitted* change — which silently discarded it, and the next run
  reported two failures that read like a broken fix. Caught in seconds only because the guard
  under test named the missing registration. **GENERAL FORM: when mutating a working tree
  deliberately, back up by COPY and restore by COPY. Reaching for git during a mutation run
  restores someone else's idea of the file.**

- **A WIRING GUARD PINNED TO AN IMPORT'S PUNCTUATION FAILS WHEN THE IMPORT GROWS
  (2026-09-09).** `test_corpus_algebra_endpoint_is_wired` asserted the literal string
  `"from src.analytics.conjunction import corpus_algebra"`. It broke the moment the endpoint
  imported a sibling from the same module — a guard about *what* is wired failing over *how*
  an import is spelled, which is a false alarm that trains the next reader to relax the
  guard rather than look at it. **GENERAL FORM: assert the SEAM and the CALL, never the
  punctuation of the statement that reaches it.** The repaired version checks that the module
  is imported at all and that the function is actually *called* — which is what the original
  was reaching for, and strictly stronger than what it had.

- **WORK THAT EXISTS AND CANNOT BE REACHED IS INDISTINGUISHABLE FROM WORK THAT DOES NOT
  EXIST (2026-09-09).** `per_article_intensity` and `conditional_trend` had shipped with the
  Conjunction Lens, carried unit tests, and were called by nothing — the endpoint returned its
  base dict verbatim and a repo-wide grep found neither name outside its own module. The
  tests kept passing the whole time, so nothing anywhere was red. **GENERAL FORM: a
  unit-tested function with no caller is a green light over a dead surface. When auditing a
  module, grep each public name for a call site OUTSIDE its own tests — the ones with none
  are the shipped-but-unreachable set, and they are cheap to close precisely because the hard
  part was already done and verified.**

- **A NUMBER IN A CODE COMMENT IS A CLAIM, AND A CLAIM NOBODY RE-CHECKS OUTLIVES ITS FACT
  (2026-09-09).** The ooMap comment states "175 countries (285 rings, 10,521 coordinate
  pairs)" as the per-frame cost being removed. That is not reasoning, it is a measurement,
  and the file it measures ships in the repo and can be regenerated. A test now counts
  `world_countries.json` and asserts the three figures in the comment match it. **GENERAL
  FORM: a comment may state reasoning freely, but the moment it states a NUMBER derived from
  something in the tree, that number wants a guard — otherwise the next person to regenerate
  the data leaves a confident, precise, wrong figure behind for years.**

- **PRE-REGISTRATION IS ONLY HONEST IF IT CANNOT REACH THE STATISTIC (2026-09-09).** Adding
  "declare your expected direction before the test" to the lunar correlator sounds purely
  additive, and the failure mode is that the declaration becomes an input: a branch that
  reads `expected_direction` before computing `r` turns a p-hacking *fix* into a new
  p-hacking *surface* wearing an honest name. The property is testable and was made the
  first test — the same series under `None`, `"positive"` and `"negative"` must return
  byte-identical `r`, `p`, `n` and window, with the verdict a post-hoc label off the sign.
  **GENERAL FORM: when a change adds an operator's DECLARATION to a measurement, assert that
  the measurement is unchanged across every declaration. The whole value of the feature is
  that assertion; without it you have added a knob to the thing you were protecting.**
  The same entry's second half: a CONTRADICTED expectation must render exactly as plainly as
  a matched one, because reporting only the matches is the publication bias pre-registration
  exists to prevent — reproducing it inside the tool that offers pre-registration would be
  worse than not offering it.

- **A PARTIAL REDRAW MUST REFUSE, NOT HALF-UPDATE (2026-09-09).** Replacing one layer of a
  rendered view is only safe while every assumption it was drawn under still holds. The ooMap
  focus path returns `false` — sending the caller to the full render — when there is no
  rendered signals layer to update, and the conditions it re-derives (kind chips, year label,
  click-resolution list, marker listeners) are each a thing that silently goes wrong if
  skipped: a stale click list opens the WRONG event's detail, which no test of the visible
  markers would catch. **GENERAL FORM: for a fast path beside a slow one, enumerate what the
  slow path also did and either redo it or refuse. And write down the precondition that makes
  the shortcut sound — here, that the projection is view-independent — as a test, because if
  it ever stops holding the failure is misplacement, not staleness, and it will look like a
  data bug.**

- **A REGRESSION TEST CAN MAKE A GAP LOOK SETTLED (2026-09-09).** `seed_sources` skipped
  any domain already in the database and never re-read the row, so catalogue metadata that
  arrived later — a new explicit country, or the title-suffix and ccTLD fallbacks that did
  not exist when older rows were created — could never reach an existing source.
  `test_seed_is_idempotent` asserted precisely that (`created=0, skipped=2`, database
  untouched), which is a correct test of create-only behaviour and reads, to the next
  person, as the question having been asked and answered. **GENERAL FORM: a test that pins
  current behaviour is evidence the behaviour is INTENTIONAL, not evidence it is right.
  When auditing, separate "this is guarded" from "this was decided" — the guard tells you
  someone wrote the line, not that anyone weighed the alternative.**

- **"FILL WHAT IS MISSING" AND "SYNC FROM THE CATALOGUE" ARE DIFFERENT FEATURES, AND ONLY
  ONE IS SAFE TO RUN UNASKED (2026-09-09).** Reconciling source metadata on every seed is
  fine while it writes ONLY empty fields; the moment it overwrites, a routine re-seed
  silently reverts anything the operator set by hand — data loss disguised as maintenance,
  triggered by a boot-time call nobody thinks of as a write. The NULL-only rule is also
  what makes it idempotent. **GENERAL FORM: when adding a background reconcile, write down
  which direction wins and make the losing direction impossible, not merely unlikely; the
  first mutant to try is the overwrite.**

- **PROVENANCE IS A FACT ABOUT THE ROW, NOT ABOUT THE THING (2026-09-09).** The source
  catalogue's tags mix two kinds: descriptive tags (`news`, `fr`) that are true of the
  SOURCE, and a `via:<origin>` marker that records how THIS row came to exist. Copying the
  whole tag string onto a pre-existing row would have made a hand-registered source claim
  it arrived via a catalogue it never came from. **GENERAL FORM: before copying a metadata
  blob from one record onto another, check whether any field in it describes the RECORD
  rather than the subject — those fields do not travel, and the ones that do are usually
  the majority, which is what makes the exception easy to miss.**

- **A DOCUMENT CAN CARRY BOTH SPELLINGS OF ONE ANCHOR, AND THAT IS WHY NOBODY SEES IT
  (2026-09-09).** Three of `USER_MANUAL.md`'s dead in-page links pointed at
  `#32-collect` while the same file, a few hundred lines later, linked the same heading
  correctly as `#32-collect-in-settings--collect`. Anyone reading either passage sees a
  plausible link; only comparing them reveals one is dead. A dead in-page anchor also has
  no failure mode a reader would report — it renders as an ordinary link and does nothing
  when clicked. **GENERAL FORM: link rot inside a document is invisible to reading and
  silent when exercised, so it needs a mechanical check, and the check is about ten lines:
  slugify the headings, extract the in-page targets, subtract.**

- **PORTING A SHIPPED FUNCTION INTO A TEST MAKES THE PORT THE THING UNDER TEST
  (2026-09-09).** The anchor guard needs the app's `slugifyHeading`, which lives in
  JavaScript; the test ports it to Python. If the port drifts, every assertion still runs
  and every one is meaningless — it validates documents against a convention the app does
  not use, and it goes green either way. The port is therefore pinned first, against the
  exact examples the original function's own comment cites as its verification cases.
  **GENERAL FORM: a re-implementation inside a test is untested code in the position of
  maximum leverage. Pin it to the original's own documented cases before using it, and
  prefer examples the original author already wrote down over ones you invent.**

- **"NO CONSISTENT RULE CAN RESOLVE THESE" IS A HYPOTHESIS, NOT A MEASUREMENT
  (2026-09-09).** The docket explained nine dead links as unresolvable by any single
  slugifier "alongside the reference anchors", which reads as an analysis and licensed
  deferring them as cosmetic. Collapse-matching each dead target against the real headings
  resolved all nine, with exactly one candidate each — and then found seven more of the
  identical class in other documents nobody had checked. **GENERAL FORM: when a deferral
  rests on an impossibility claim, the cheapest test is to try the obvious rule and count
  the failures. An impossibility that has never been measured is a guess with a
  confident tone, and the sweep it discourages is usually where the rest of the defect is.**

- **"BOUNDED" MEANS "DOES NOT GROW WITH THE USER'S DATA", NOT "SMALL TODAY" (2026-09-09).**
  `search_omni.py` promises "never scan-on-type: every group is served by an index or a
  small bounded table", and the useful test of a candidate group turned out not to be its
  current row count but whether that count is a function of the corpus. The events
  catalogue (154 entries) and the Help documents (~600 KB) ship WITH the app and are the
  same size on every install, so a contains-match over them is honest at 1.4 ms. The
  keyword table looks comparable on a fresh install and reaches 406,723 rows on a real
  corpus, which is why the same technique there would be a 400k-row scan per keystroke.
  **GENERAL FORM: before adding a linear pass to a hot path, ask what the population is a
  function of. A table that grows with usage and a file that ships with the binary are
  different kinds of thing, however similar they look on a developer's empty database.**

- **MEASURING A COLD IMPORT AS IF IT WERE THE FEATURE (2026-09-09).** The first timing of
  the new Help-content index read **3.46 seconds** — alarming, and wrong. Almost all of it
  was `import src.api.main`, which production has already paid before any search runs; the
  index itself is 28 ms. The second error in the same run was measuring the first query
  before any warm-up, which charged one group 8 ms instead of 0.3. **GENERAL FORM: a
  first-call measurement in a fresh interpreter includes the module graph and every lazy
  cache the real process built at boot. Import what production imports, warm what
  production warms, and only then start the clock — otherwise the number is about the
  measurement harness, and it will be quoted as being about the code.**

- **A RENDERER THAT SWITCHES ON A KIND SILENTLY DROPS THE KIND IT DOES NOT KNOW
  (2026-09-09).** The omnibar's `_omniItems` is an `if/else-if` chain over `g.kind`; a
  backend group with no branch produces no row, no warning and no error — the API returns
  it, the palette renders nothing, and every test on both sides passes. That is the same
  built-and-unreachable shape as a tested function with no caller, arriving from the other
  direction. **GENERAL FORM: when a consumer dispatches on a type tag, adding a producer
  case is not complete until the consumer case exists, and the guard belongs in the same
  commit — an `else` that logs the unknown kind is the cheaper structural fix where the
  surface can afford it.**

- **A GUARD THAT CHECKS A CAPABILITY'S NAME IS NOT CHECKING THE CAPABILITY (2026-09-09).**
  `index.html` claims the `#an` window is "a strict superset" of the retired `#corpus-win`
  modal, and that claim is what licenses deleting the modal. The test enforcing it asserted
  that the `#an` nav carries a `data-tab` with each retired facet's NAME — and passed for
  months while three facets were strict SUBSETS: Sources dropped every catalogue fact,
  Links dropped the distinct-source count that separates echo from corroboration, Keywords
  dropped PMI. **GENERAL FORM: when a test exists to license a DELETION, the thing it must
  compare is what the survivor DISPLAYS against what the deleted thing displayed. A tab
  called "Sources" existing is compatible with every fact behind it having been lost, and
  the check that a name is present is the cheapest possible assertion to write and the
  easiest to mistake for the expensive one.** Same family as the `app.js`-split lesson (a
  negative assertion passing for free against a file that no longer contains what it
  checks); this is its positive-space twin.

- **A SOURCE-TEXT ASSERTION FOR "X IS RENDERED" SURVIVES CODE THAT READS X AND THROWS IT
  AWAY (2026-09-09, found by a mutant against my own new test).** The guard was
  `assert_present(renderer_source, "s.tags")`. The mutant `const tags = (false &&
  s.tags.length)` — read the field, discard it — kept the substring and the test stayed
  green. **GENERAL FORM: a substring proves a field is MENTIONED, never that it reaches the
  output. Where the fact matters, extract the fragment into a pure named function and
  EXECUTE it; where it does not, keep the grep but write down that it is a smoke check, so
  the next reader does not bank on it.** The extraction is cheap and pays twice: the cell
  became testable, and the ten assertions it now carries (tags-only rows, empty arrays, a
  null row, escaping) are cases no grep could have expressed.

- **A DEFAULT PARAMETER VALUE HIDES A BRANCH FROM EVERY TEST THAT USES THE DEFAULT
  (2026-09-09).** A per-link independence verdict guarded on `sources > 1 and citations ==
  sources`. Dropping the `sources > 1` half killed nothing: the fixture's floor was
  `min_citations=2`, so `citations == sources == 1` never occurred. But `min_citations` is a
  caller-settable `Query(ge=1)`, so the case is one query-string away — and there the mutant
  labels a link cited by ONE article from ONE outlet as coming from distinct outlets, the
  most misleading verdict the field can carry on the least corroborated row there is.
  **GENERAL FORM: when a mutant survives, check whether a DEFAULT is what makes it look
  equivalent before concluding that it is. The branch is unreachable only for callers who
  take the default, and the parameter exists precisely because some caller will not.**

- **A CODEMOD THAT EDITS PYTHON MUST BE DRIVEN BY THE PARSER, AND MUST REFUSE TO WRITE
  WHAT DOES NOT PARSE (2026-09-09).** Migrating 27 call sites, the script placed its new
  import with a regex for the last top-level import line. That regex matched the OPENING
  line of a multi-line parenthesised `from x import (` and inserted the statement INSIDE
  the parentheses, leaving three test files syntactically invalid. **The test suite did
  not catch it** — an unparseable file is a collection error *in itself*, not in the files
  it makes assertions about, so the suites those files guard reported nothing. `ruff` did,
  as `invalid-syntax`, and only because the ratchet is run on every change. **GENERAL FORM:
  a regex sees lines, and Python statements are not lines. `ast` knows where a statement
  ends (`end_lineno` covers parenthesised continuations), and an `ast.parse()` on the
  result before writing turns "I hope this is valid" into a precondition.** Corollary worth
  keeping: a lint ratchet run every time is a syntax check the test suite structurally
  cannot be.

- **A READER THAT CAN FIND NOTHING MUST RAISE, NEVER RETURN EMPTY (2026-09-09).** The
  shared reader for `src/api/diagnostics` — built so a future package split cannot go
  vacuous at 27 sites — has two ways to find nothing: the path is gone, or the package
  holds no `.py`. Both raise. Returning `""` would be the natural defensive instinct and is
  the exact opposite of safe here: an empty string passes **every** `assert X not in
  source` in the suite, silently, which is the failure the reader exists to prevent
  arriving through the reader itself. **GENERAL FORM: when a helper feeds negative
  assertions, its empty result is indistinguishable from the condition those assertions
  are testing for. Make "found nothing" an error, and pin that with a test, because the
  refusal reads like defensiveness to the next person tidying up.** Same shape as the
  ordering rule beside it: the reader includes a module `__init__.py` never imports,
  because a forgotten import line must not quietly shrink what the assertions run over.

- **A LINE-ANCHORED REGEX OVER HTML ANSWERS A QUESTION ABOUT FORMATTING, NOT ABOUT
  MARKUP (2026-09-10).** Comparing two UI surfaces for which capabilities each
  offered, I grepped `<button[^>]*onclick="cap"` — which requires the whole opening
  tag on ONE line. Several of the buttons wrap across lines, so the comparison
  reported one surface as MISSING three capabilities it plainly has, and I nearly
  recorded that conclusion in the ledger. Parsing the attribute instead
  (`onclick="cap\(([^"]*)\)"` over the whole section, or a real parser) gave the
  opposite answer. **GENERAL FORM: whenever a grep's result would change a decision,
  ask what the pattern assumes about LAYOUT — line breaks inside a tag, attribute
  order, single vs double quotes, whitespace around `=`. HTML and code are not
  line-oriented, and a pattern that silently matches nothing looks exactly like a
  feature that is absent.** The tell here was the finding being too convenient: it
  said the surface I was arguing for was already ahead.

- **A BUTTON THAT RENDERS UNCONDITIONALLY CLAIMS ITS CAPABILITY; REFUSING ON CLICK IS
  THE SURFACE LYING TWICE (2026-09-10).** The Methods appendix and signed-evidence
  exports took a query string, so on an id-seeded corpus — a Lead's exact article set,
  a facet drill, anything from `openAnalysisForIds` — they refused. The second lie was
  the refusal's own text: "Run a search first", said to a reader who had just opened a
  forty-article Lead corpus. The capability existed end to end (the endpoint had always
  accepted `article_ids | query`, with tests proving it); only the client threw the
  field away. **GENERAL FORM: a control whose availability is not conditional is a
  promise. When a path cannot serve it, the honest options are to disable it with a
  reason or to make it work — and a refusal message written for one entry point will
  be actively misleading at another.** Look hardest at the paths a feature was NOT
  originally built for: they inherit the control and not the plumbing.

- **READING THE HANDLER IS NOT READING THE BEHAVIOUR — FIND WHAT IT ACTS ON (2026-09-10).**
  Asked whether the omnibar's Enter opens the analysis window, I read `palKey`, saw
  `Enter → palRun(_palSel)`, and reported that no entrance existed. The entrance was in
  `renderPalette`, which unshifts the Analysis row and marks it `↵`. The handler answers
  "what does the key do"; the question was "what will it do to". **GENERAL FORM: for a
  keyboard or click handler that operates on a SELECTION, the behaviour lives where the
  selection is built and ordered, not where the key is bound. Read the ordering before
  concluding anything about what the key reaches** — and the same applies to a dispatcher
  keyed on a variable, a router matching a path, or a reducer switching on an action.
  The failure is asymmetric and worth fearing: it produces a confident negative ("this is
  not built") about work that exists, which is the kind of claim a ledger carries forward.

- **A KEYBOARD BADGE IS A PROMISE, AND SELECTION ORDER DECIDES WHETHER IT IS KEPT
  (2026-09-10).** The Analysis row said `↵ ↗` unconditionally, while `_palFiltered =
  [...statics, ...live]` with the selection at index 0 means Enter runs the first STATIC
  match whenever the typed text matches a command. Measured against the shipped command
  labels the collision is ordinary — `search`, `collect`, `open`, `data`, `help`,
  `settings` — so the badge was wrong on exactly the queries most likely to be typed by
  someone learning the palette. **GENERAL FORM: a shortcut hint rendered per-row is a claim
  about the CURRENT list, not about the row; when the list is assembled from several
  sources, the hint has to be computed from the assembled order or it will drift the moment
  a second source matches.** Same family as a control that renders unconditionally and
  refuses on click: the surface describing a capability it does not have here and now.

- **A SOURCE-LEVEL ASSERTION ABOUT A TRANSFORM CANNOT SEE THE TRANSFORM (2026-09-10).**
  Adding a "readable" rendition to the dump reader, the first test round asserted that the
  endpoint IMPORTS the shared reducer and that the UI labels the pane honestly. A mutant
  replacing `res["plain"] = plain_from_wikitext(raw)` with `res["plain"] = raw` **survived
  both** — an endpoint serving raw wikitext under the word "Readable", which is exactly the
  lie the careful naming existed to prevent. **GENERAL FORM: checking that the right
  function is imported, called, or named proves the WIRING; only calling the thing proves
  the OUTPUT. When a change's whole value is that some text differs from some other text,
  the test has to compare the two.** Stubbing the expensive dependency (here `find_page`,
  so no dump file is needed) is usually cheaper than the source-level guard it replaces,
  and strictly stronger.

- **WHEN A DOCKET ASKS FOR A CAPABILITY THE CODEBASE CAN ONLY APPROXIMATE, SHIP THE
  APPROXIMATION UNDER ITS OWN NAME (2026-09-10).** The dump reader's open work said
  "wikitext rendering". What exists is `plain_from_wikitext`, whose docstring targets
  "keyword/WWW-quality text, not rendering fidelity" — it PEELS templates and DROPS tables.
  Measured on a page whose population figure lived only in its infobox, the figure is
  **gone** after the strip, not laid out differently. Labelling that "Rendered" would tell a
  reader the page never had an infobox. **GENERAL FORM: the gap between what was asked for
  and what the tools can do is not closed by the label. Name the thing you actually built,
  state what it drops, keep the complete version one click away, and leave the original ask
  open in the docket — a renamed approximation silently retires a requirement nobody
  decided to drop.**

- **WHEN A CHECK GOES RED, DIFF THE LAST-GREEN HEAD AGAINST IT BEFORE READING THE FAILURE
  (2026-09-10).** A `Core-only install` lane failed on a WAL-starvation concurrency test.
  The fastest conclusive move was not the log: it was
  `git diff --stat <last-green-head> <red-head>`, which showed three ledger files and one
  line of `CLAUDE.md` — **zero code**, with every code change in the PR already present in
  the green run. That settles authorship in one command, before any theory about the
  failure exists. **GENERAL FORM: a red check raises two separate questions — what broke,
  and whether this change could possibly have broken it. The second is often answerable in
  seconds and, when the answer is no, it reframes the first from "debug my change" to
  "characterise someone else's flake", which is a different and much shorter investigation.**

- **THE STRONGEST EVIDENCE OF NON-DETERMINISM IS THE SAME COMMIT DISAGREEING WITH ITSELF
  (2026-09-10).** Local reproduction attempts are weak evidence about CI: different
  hardware, different load, different everything. This repo happens to build each head
  under TWO parallel workflow runs, and on one commit the same check FAILED in one and
  PASSED in the other. That single fact is worth more than the 14 local passes gathered
  first (8 sequential, 6 under artificial CPU load), because it holds the code exactly
  constant and varies only the run. **GENERAL FORM: before spending a re-run to prove a
  flake, check whether the evidence already exists — a sibling run, a matrix leg, a
  scheduled build on the same SHA. And when reporting a flake, prefer same-commit
  disagreement over "it passes on my machine", which an experienced reviewer will
  discount.**

- **A STALE DOCSTRING ON A NOW-PASSING TEST MISLEADS PRECISELY THE PERSON DEBUGGING IT
  (2026-09-10).** The starvation test's docstring still read *"MUST FAIL on unpatched main
  … that is false today"*, written when it was a red-first regression test. The fix landed;
  the test now asserts the fixed guarantee and normally passes. But anyone arriving via a
  red check reads that prose and concludes the fix was never applied — sending them to
  re-implement something that exists a few lines away in the same subsystem. **GENERAL
  FORM: a test written to FAIL first carries prose that expires the moment it starts
  passing, and nothing forces an update. When landing the fix that flips such a test, flip
  its docstring in the same commit — the words are part of the test's output, and they are
  read hardest at the worst moment.**

- **AN ACCESSIBILITY FIX APPLIED TO EVERY CANDIDATE IS USUALLY A SECOND DEFECT
  (2026-09-10).** `scrollable-region-focusable` is satisfied by putting `tabindex="0"`
  on the scrollable element, and the tempting fix is to mark every `<pre>`. But a tab
  stop on a block that does not scroll is a keystroke that does nothing, and a Help
  document full of short code samples becomes a corridor of dead stops — worse for the
  keyboard user the rule exists to protect. The honest test is the element's REAL
  measured geometry (`scrollWidth > clientWidth`), and the mark has to be REMOVED again
  when a re-render makes a block fit. **GENERAL FORM: an axe rule names a condition,
  not a remedy. Satisfying it everywhere the selector matches will pass the audit and
  can still degrade the experience — fix the elements that actually have the problem,
  and be willing to unfix them when they stop having it.** The neighbouring temptation
  is the same shape: adding `role="region"` alongside would trade this rule for the
  accessible-name rule, and inventing "code sample 3" per block is screen-reader noise.

- **WHEN TWO FUNCTIONS WRITE THE SAME CONTAINER, A FIX IN ONE IS UNDONE BY THE OTHER
  (2026-09-10).** `#doc-prose` is written by `openDoc` (loads a document) and by
  `filterDoc` (re-renders it from the find box). A post-render pass added only to
  `openDoc` survives until the reader types one character. **GENERAL FORM: before adding
  a post-render step, grep for every writer of that container's `innerHTML` — the count
  is usually more than one, and the second path is typically the incremental/filter/
  refresh one that was added later and is exercised less in manual testing.** Cheap to
  check, invisible when wrong, and a mutant that deletes the second call is worth having
  in the matrix.

- **A "SLOW DOWNLOAD" COMPLAINT IS NOT NECESSARILY ABOUT THE DOWNLOAD (2026-09-10, the
  collect-throughput investigation).** The field report was "the rate of article download
  is now abnormally slow", and every instrument the app owns for that question — the
  bandwidth governor, `collect_target_kbps`, the per-job rate sampler — measures bytes
  over the wire. Measured with a harness that served every fetch from memory, throughput
  was **flat at ~2.3 articles/s from 1 worker to 50**: the transport was never the
  constraint, ~400 ms of pure-Python CPU per article was, and N worker threads simply took
  turns under the GIL. **GENERAL FORM: before tuning the thing the complaint names,
  measure the pipeline with that thing removed. If the number does not move, the name in
  the complaint is a symptom.** The corollary is uncomfortable and worth stating: a
  control loop that varies concurrency to hit a byte-rate target is inert on a CPU-bound
  pipeline, and it will still produce confident-looking permit adjustments the whole time.

- **A LARGE `re` ALTERNATION IS O(alternatives) AT EVERY POSITION, AND `re.I` REMOVES THE
  ESCAPE HATCH (2026-09-10, `dateextract._MONTH_ALT`).** 555 multilingual month names,
  4,159 characters, embedded in ten patterns scanned over a 60,000-character window.
  Measured cost of two patterns that match the SAME dates: `_DMY_RE` (`11 September
  2001`) **1.24 ms**, `_MDY_RE` (`September 11, 2001`) **43.73 ms** — a 35× spread whose
  only cause is which end the alternation sits on. `_DMY_RE` begins `\b(\d{1,2})`, so
  CPython fast-skips to positions that can match; `_MDY_RE` begins with the alternation,
  so the engine tries up to 555 branches at every word boundary. CPython's `re` has no
  trie/Aho–Corasick optimisation for alternations (the `regex` module and Rust's engine
  do), and `re.IGNORECASE` disables the literal-prefix scan that would otherwise help.
  **GENERAL FORM: when a hand-built alternation grows past a few dozen literals, its cost
  stops being "a bigger pattern" and becomes a linear scan per input position. Put the
  cheap discriminating token FIRST where the grammar allows, and otherwise pre-scan for
  the literals actually present and rebuild the alternation from those — measured here at
  33× on typical news prose, with identical matches by construction, since a literal
  absent from the text could never have matched.** The trap in that fix, found before it
  was written: 55 of the 555 names are not a single `\w+` run (four Arabic two-word names,
  plus Devanagari and Bengali forms), so a naive tokenised pre-scan silently loses recall
  in exactly the languages the multilingual tables were added for.

- **A COST THAT GREW 10× OVER A MONTH LOOKS LIKE A SUDDEN REGRESSION TO THE PERSON
  LIVING WITH IT (2026-09-10).** `extract_dates` went 14 ms → 62 ms → 142 ms per article
  across 2026-06-15 / 07-01 / 07-15 and has been flat ever since. The report arrived on
  09-10 and named "the past few days". Bisecting the last few days would have found
  nothing and concluded there was no problem. **GENERAL FORM: when a complaint says
  "recently" and the recent window is clean, widen the window before declaring the report
  wrong — a plateau that everyone has stopped noticing is still the ceiling, and the
  operator's sense of "recent" is calibrated to when it started hurting, not to when it
  changed.** Measuring seven trees cost one afternoon and turned "no regression" from a
  dismissal into a date.

- **AN ENVIRONMENT-VARIABLE FEATURE FLAG READ INSIDE A PER-TOKEN LOOP IS A REAL COST
  (2026-09-10, `extract._is_code_token`).** The flag read is the first line of a predicate
  called once per unigram and once per token of every bigram and trigram window — ~8,150
  `os.getenv` calls per article, 130,497 over a 16-article profile, and `os.getenv` is not
  free (`os.environ.__getitem__` → `encodekey`). **GENERAL FORM: a reversibility flag is
  cheap at a function boundary and expensive inside the loop that function is part of.
  Read it once per call site that can afford it, and cache it.** Same profile, same
  function: `_alnum_transitions` recomputes the identical answer for the identical token
  up to six times, because the unigram pass and the two n-gram passes each ask
  independently.

- **A LEARNED CEILING THAT PERSISTS TO DISK IS A PERFORMANCE BUG WITH A LONG HALF-LIFE
  (2026-09-10, `scheduler/capacity.py` + `bandwidth.py`).** `mem_low` (system-wide
  available memory under a fixed 512 MB) triggers a MULTIPLICATIVE permit cut — measured
  50 → 1 in five 1.5 s ticks — and that floor is then written to
  `data/collect_capacity.json` and used as both the seed and the `ramp_ceiling` of every
  later pass, across restarts. Over a slow transport that is 1.91 → 0.45 articles/s, a
  4.2× slowdown with no code change and no visible cause. Recovery is ×2 per clean pass,
  but only fires if the pass stops tripping a threshold that is about the whole MACHINE,
  not about the collector — so a box also running a local model can sit under it forever.
  **GENERAL FORM: when a self-tuning mechanism persists its worst observation, the
  recovery path is the load-bearing half, and it must be driven by something the
  mechanism itself can influence. And it must be VISIBLE where the operator watches the
  work** — here `capacity.state_report` is rendered only inside the diagnostics report
  payload, so the task manager shows a pass running 1 worker of a configured 50 and says
  nothing about why. The neighbouring case is worse in kind: `cpu_saturated` fires at
  92 % system-wide CPU, which a healthy CPU-bound collector produces BY ITSELF, so the
  governor throttles the collector for doing its job well.

- **A DIFFERENTIAL THAT GENERATES ITS OWN INPUTS MUST GENERATE THEM DETERMINISTICALLY —
  `str.hash` IS RANDOMISED PER PROCESS (2026-09-10, the month-narrowing proof).** The
  harness picked each test case's letter-casing with `hash(name + shape) % 4`, ran the two
  trees in two interpreters, and reported **4,372 differences**. Every one was the harness:
  `PYTHONHASHSEED` randomises `str.__hash__`, so the two sides were comparing *different
  texts*. The failure is nasty because it looks exactly like a real regression — the dates
  matched and only the provenance snippets differed, which reads as a subtle casing bug in
  the code under test. **GENERAL FORM: in a cross-process differential, every input must be
  a pure function of a declared seed. `random.Random(n)` is safe, `zlib.crc32` is safe,
  `hash()` and set/dict iteration order are not.** The tell is a diff that is enormous and
  uniform rather than sparse and specific.

- **A GUARD THAT SURVIVES EVERY MUTATION IS NOT PROVEN CAUTIOUS, IT IS UNPROVEN — AND MAY
  BE DOING HARM (2026-09-10, same work).** The month-presence scan shipped with two extra
  safety nets: an "always keep the case-unsafe names" set and a second scan over
  `casefold()`. Both survived the whole mutation matrix. The tempting reading is "cheap
  insurance, keep them"; the correct one was to go find the REAL argument, which turned out
  to be stronger — the scan lowers the same token with the same method as `_month_of`, the
  one function every month loop resolves through and which skips on a miss, so a token the
  scan cannot key is a token the old path refused too (verified exhaustively: 555 names × 5
  casings × every language hint, zero violations). And the keep-set was **actively
  harmful**: its predicate `n.casefold() != n` matched all ~26 Greek month names, silently
  pinning 30 extra branches into the alternation of every article in every language —
  eroding the very win it was guarding. **GENERAL FORM: when a mutation cannot kill a
  guard, that is a question, not a reassurance. Either find the input that makes it
  load-bearing, or find the invariant that makes it unnecessary and pin THAT as the test.
  Do not keep it "just in case" — an unfalsifiable guard is one nobody can safely change
  later, and this one was quietly paying its own cost.**

- **`rx is SOME_MODULE_PATTERN` BREAKS THE MOMENT PATTERNS ARE BUILT PER DOCUMENT
  (2026-09-10, same work).** The year-less date loop iterated
  `((_DM_NOYEAR_RE, …), (_MD_NOYEAR_RE, …))` and re-derived which member it was on with
  `if rx is _MD_NOYEAR_RE`, to apply the homograph guard that stops `"Marta 30 godina"`
  becoming 30 March. Narrowing rebuilds those patterns per document, so `rx` is never the
  module-level object again: the guard would have stopped firing **silently**, and the
  extractor would have resumed a fabrication it had a verifier finding for. Caught by
  reading the loop before editing it, and the mutation that puts the identity test back is
  in the matrix. **GENERAL FORM: identity comparison against a module global is a hidden
  coupling to "this object is a singleton". Any change that makes an object per-request,
  per-document or per-tenant breaks every such test at once, and breaks them by silently
  taking the other branch rather than by raising. Carry the discriminating FACT in the
  loop's own tuple instead of re-deriving it from identity.**

- **PUT THE CHEAP DISCRIMINATING TOKEN FIRST, OR THE ENGINE SCANS EVERY POSITION
  (2026-09-10).** Two patterns in the same module, matching the same dates, over the same
  22 KB: `_DMY_RE` ("11 September 2001") **1.24 ms**, `_MDY_RE` ("September 11, 2001")
  **43.73 ms**. The only difference is which end the 555-name alternation sits on —
  `_DMY_RE` opens `\b(\d{1,2})` so CPython fast-skips to digit positions, `_MDY_RE` opens
  on the alternation so the engine tries branches at every word boundary. **GENERAL FORM:
  a regex's cost is set by what its FIRST element lets the engine skip. When a pattern must
  begin with a large literal set, the fix is to shrink that set to what the input can
  actually contain — measured here at ~10x, with matches identical by construction because
  a literal absent from the text could never have matched.**

- **A CONTROL LOOP THAT READS A MACHINE-WIDE SIGNAL WILL THROTTLE ITSELF WHEN IT IS THE
  LOAD (2026-09-10, P4).** The bandwidth governor cut a fetch permit every 1.5 s tick
  whenever system CPU was ≥ 92% — and the collector is CPU-bound in pure Python, so a
  perfectly healthy pass on a small box produces exactly that reading BY ITSELF. Measured:
  50 permits to 1 in 73 seconds, for doing its job well, freeing nothing, because the CPU
  it "gave back" was its own. The module's own comment already said CPU saturation "costs
  throughput, not the machine"; nobody noticed the response to it still cost throughput.
  **GENERAL FORM: when a self-protective control reads a whole-machine gauge, ask what
  that gauge reads while the thing it governs is working normally. If the answer is
  "saturated", the control is wired to fight itself.** The reading that separated the
  cases — `cpu_proc_pct` — was already sampled, already written to the perf log, and
  consulted by no decision at all: the fix was a comparison, not an instrument. Watch the
  scale when making it: `psutil.cpu_percent()` is normalised 0-100 across the machine
  while `Process.cpu_percent()` SUMS across cores, so 380% of 4 cores is 95% of the box,
  and conflating them inverts the answer.

- **A SELF-TUNING MECHANISM THAT PERSISTS ITS WORST OBSERVATION NEEDS A RECOVERY PATH IT
  CAN ACTUALLY REACH (2026-09-10, P4b).** `capacity.py` records the worker floor a machine
  reached under memory pressure and uses it as the next pass's seed AND ramp ceiling,
  across restarts. Its relax branch needed a pass below a pressure share — but `mem_low`
  is a WHOLE-MACHINE reading (available memory under a fixed 512 MB), so on a box also
  running a local model every pass qualified as pressured, the floor walked to 1,
  `min(current, floor)` re-pinned it, and the quiet pass could never arrive. Result:
  1.91 → 0.45 articles/s, no code change, no visible cause, surviving restarts.
  **GENERAL FORM: the recovery half of a learned limit is the load-bearing half, and it
  must be driven by something the mechanism itself can influence. A limit learned from a
  condition the subject cannot change is not a measurement of the subject — it is a
  permanent sentence.** The fix that worked was narrow and checkable ("a ceiling of 1
  cannot survive two passes") rather than a claim of full recovery, because nothing had
  shown more workers were safe. And it was only safe because a DIFFERENT mechanism
  (`memguard`, which pauses collection outright) is what actually protects the machine —
  worth confirming before relaxing anything, since the tempting alternative is to raise
  the threshold, which is regressing a safety number the measurement says works.

- **WRITING THE RELAXED CASE THROUGH THE EXISTING BRANCH ALSO INHERITS ITS LABEL
  (2026-09-10).** Routing the new "pressure the worker count did not cause" case into the
  existing relax branch was right for the arithmetic and wrong for the record: that branch
  stamps `reason: "a pass with no memory pressure"`, which is a false statement in the very
  file an operator opens to find out why their collector is slow. **GENERAL FORM: when you
  reuse a branch for a second cause, check what it WRITES as well as what it computes.
  Shared code paths quietly share their explanations, and a stored reason is read long
  after the arithmetic stops mattering.**

- **A PAYLOAD NOBODY DRAWS IS THE SAME DEAD END AS A FEATURE NOBODY CAN REACH
  (2026-09-10, P5).** Both concurrency caps were correct, measured, and exposed —
  `state_report` inside the diagnostics report payload, the machine-floor cap into a log
  line. Neither reached the task manager, which is where an operator watches collection.
  So a pass running one worker of a configured fifty was, from the only window anyone
  looks at, indistinguishable from "the app got slow". **GENERAL FORM: "the number is
  available" and "the number is where the question is asked" are different claims. When
  shipping a diagnostic, name the surface the question actually gets asked on — a
  diagnostics export is where you look once you already suspect something.**

- **"ABSENT" AND "MEASURED ZERO" ARE ONE CHARACTER APART IN SOURCE AND OPPOSITE ON SCREEN
  (2026-09-10, P5).** The permit count must not draw when no pass is in flight (0 workers
  and no pass are different facts, and a "0" there is a number where there is no
  measurement) but MUST draw when a running pass really is at zero. The whole distinction
  lives in `pg.permits != null` versus a truthiness test, and no source-level assertion
  can tell the two apart — both are "the function mentions permits". **GENERAL FORM: any
  honesty rule of the shape "absent means absent" needs a test that EXECUTES the renderer
  with both inputs; grep-level guards pass on the mutant.** Six mutants, six dead, and the
  measured-zero case is the one that would otherwise have been fixed into a bug.

- **A NODE HARNESS PROVES THE HTML AND CANNOT SEE THE PAGE (2026-09-10, P5).** The
  Workers panel passed 7 mutation-killed behavioural checks on its rendered HTML, and the
  first real click-through showed the reason truncated to *"this machine backed o…"*
  running off the panel edge — because `.vitals-pop .vr b` clamps a row's VALUE to 160px
  with an ellipsis. That is correct for a figure and destroys a sentence, and it silently
  destroyed the one thing the whole section exists to let an operator read. The HTML the
  tests asserted on was right the entire time. **GENERAL FORM: a DOM-level test verifies
  what you built; only a rendered page verifies what is legible. When a slice's value is
  that someone can READ something, the click-through is part of the slice, not a follow-up
  — and "browser-unverified, a click-through is owed" is a debt that hides exactly this
  class of defect.** The corollary is the cheerful one: the click-through also let the
  ×12 claim be verified by switching the locale live, instead of asserted from the fact
  that the keys exist.

- **PUTTING PROSE WHERE A FIGURE GOES INHERITS THE FIGURE'S TRUNCATION (2026-09-10).**
  The row helper was built for `label → number`, so its value slot is `max-width:160px;
  white-space:nowrap; text-overflow:ellipsis`. Reusing it for a sentence looked natural in
  source and was wrong on screen. **GENERAL FORM: before reusing a layout helper, read its
  CSS, not just its signature — a helper named `row` encodes assumptions about what its
  value IS, and prose and figures want opposite treatments.**

- **THE BACKEND'S OWN `method`/`reason` STRINGS ARE ENGLISH, AND A HOVER IS A CAVEAT
  SURFACE (2026-09-10).** The first cut piped `capacity.state_report()`'s `method` and the
  machine floor's `reason` straight into `title=`, which renders untranslated English to
  every non-English operator — and this project's informed-consent non-negotiable puts
  every caveat in 12 locales. `renderMachineFloor` had already set the right precedent for
  the very same payload: translate the prose, keep only the measured NUMBERS and literal
  tokens (an env var to type) from the backend. **GENERAL FORM: a payload field named
  `method`, `reason` or `caveat` is documentation for a reader, so it is prose, so it is
  subject to i18n. Passing it through to the UI is the easy path and the wrong one; the
  mutant that puts it back belongs in the matrix.**
