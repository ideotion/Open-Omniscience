# Why article download is slow — a measured investigation (2026-09-10)

Open Omniscience — GPL-3.0-or-later. Copyright (C) 2026 Ideotion.

**THE ASK.** *"the app's overall performance and efficiency has significantly lowered.
Notably, its capacity to download articles. The rate of article download is now
abnormally slow."*

**THE HEADLINE, stated before the evidence because it inverts the question.** The
collector is not slow at downloading. It is slow at *finishing* an article, and it is
**CPU-bound in pure Python**, so the download machinery — `collect_parallelism`, the
bandwidth governor, the worker pool — is steering a knob that, past about eight workers,
moves nothing. Measured on this 4-core box: throughput is **flat at ~2.3 articles/second
from 1 worker to 50**.

**AND: no regression landed in the last few days.** The A/B below runs the same harness
against seven trees from 2026-06-15 to today. Per-article cost has been flat since
**2026-07-15**. What actually happened is older and larger: between 2026-06-15 and
2026-07-15 the per-article extraction cost went from **118 ms to 263 ms**, and
`extract_dates` alone went from **14 ms to 142 ms — a 10× growth** — which is where the
throughput ceiling now sits.

Everything below is reproducible with `scripts/analysis/collect_throughput_bench.py`,
committed alongside this document.

---

## 1. What one article costs

`collect_throughput_bench.py stages`, 12 articles of 22 KB body text, HEAD:

| step | ms/article | share |
|---|---:|---:|
| `extract_dates` | **139.9** | **53.4 %** |
| `extract_locations` | 79.4 | 30.3 % |
| keyword extraction (baseline) | 31.8 | 12.2 % |
| `extract_article` (trafilatura) | 6.9 | 2.6 % |
| `classify_non_article` | 3.7 | 1.4 % |
| **total** | **261.8** | |

End to end through the real pipeline (`store_fetched` → `ArticleBatch.flush`, real DB,
real write gate) the figure is **~400–430 ms of CPU per stored article**; the ~140 ms
above the table is trafilatura's second parse, dedup reads, the keyword-mention inserts
and the batch commit.

Two of those five steps are 84 % of the cost, and both are text scanners.

## 2. Throughput is flat in the number of workers

`collect_throughput_bench.py sweep`, 16 sources × 6 items = 96 articles, 4 cores:

| workers | 20 ms/fetch (fast link) | 1.5 s/fetch (the Tor shape) |
|---:|---:|---:|
| 1 | 2.10 art/s | 0.45 art/s |
| 4 | 2.33 | 1.21 |
| 8 | 2.32 | 1.49 |
| 16 | 2.18 | 1.89 |
| 50 | 2.27 | 1.91 |

On a fast link **parallelism buys nothing at all** — 1 worker and 50 workers land within
noise of each other, and 16 is marginally *worse* than 4. Over a slow transport it buys a
real 4× up to about 16 workers and then hits the same wall.

That wall is the GIL. Every worker spends ~400 ms per article inside pure-Python regex
and token loops, so N worker threads take turns rather than running.

**The consequence for the settings that exist today:** `collect_parallelism = 50` is not
a throughput setting on this shape of machine. `collect_target_kbps` cannot be reached by
adding workers. And the honest reading of the C16 commit's own note — *"WALL TIME DOES
NOT MOVE… this relocates CPU, it does not remove it"* — is that the collector's problem
was never where the CPU ran, it is how much of it there is.

## 3. Where the CPU actually goes: a 555-name regex alternation

`collect_throughput_bench.py patterns`:

```
the month alternation is 555 names / 4,159 chars
    45.04 ms  _MD_NOYEAR_RE     pattern=12,887  <- carries the month alternation
    43.73 ms  _MDY_RE           pattern= 4,208  <- carries the month alternation
    42.84 ms  _RANGE_MDY_RE     pattern= 4,244  <- carries the month alternation
    42.78 ms  _MY_RE            pattern= 4,229  <- carries the month alternation
     8.52 ms  _WD_RE            pattern=   883
   219.21 ms  TOTAL over 42 patterns

10 patterns carry the alternation: 178.6 ms = 81% of all pattern time
```

`_MONTH_ALT` is the union of `_MONTHS` and `_MONTH_LANG_OVERRIDES` — **555 month names
across every supported language, 4,159 characters**, embedded in ten compiled patterns
and run with `re.IGNORECASE` over the whole 60,000-character scan window.

**It is not narrowed by the article's language.** `_extract` computes
`base = (language or "")[:2].lower()`, but the language hint is only consulted *after* a
match, in `_month_of`. So an English article is scanned against Vietnamese, Greek,
Arabic, Hungarian, Turkish and Persian month names — ten times over.

The 40× spread between two patterns that match the same dates is the tell:

* `_DMY_RE` (`11 September 2001`) costs **1.24 ms**. It begins `\b(\d{1,2})`, a digit
  literal, so CPython's engine fast-skips to positions that can possibly match.
* `_MDY_RE` (`September 11, 2001`) costs **43.73 ms**. It begins with the alternation, so
  the engine tries up to 555 alternatives at essentially every word boundary in the text.

CPython's `re` has no trie/Aho–Corasick optimisation for large alternations; `re.I`
removes what literal-prefix scanning it does have.

### What a fix is worth (prototyped and measured, not estimated)

One cheap tokenised pre-scan collects the month names *actually present* in the text
(typically 0–3 of the 555), then the same patterns are rebuilt over only those names and
cached. Same matches by construction — a name absent from the text could never have
matched — with the longest-first ordering and the post-match `_month_of` homograph
resolution untouched:

| text | four dominant patterns, now | prototype | |
|---|---:|---:|---:|
| months in ~30 % of paragraphs (typical news) | 182.4 ms | 5.6 ms | **33×** |
| months in ~5 % of paragraphs | 177.4 ms | 4.4 ms | 41× |
| no month names at all | 171.6 ms | 1.6 ms | 104× |

That would take `extract_dates` from ~140 ms to roughly ~20 ms and per-article extraction
from ~262 ms to ~140 ms — **about a 1.8× collector throughput increase on any machine
where CPU is the ceiling, which by §2 is every machine once parallelism ≥ 8.**

**One wrinkle a fix must handle rather than skip:** 55 of the 555 names are not a single
letter-run (the four Arabic two-word names — `كانون الثاني` — plus Devanagari and Bengali
forms). A naive `\w+` pre-scan would miss them and silently lose recall in exactly the
languages the multilingual tables were added for. They need a separate substring check,
which is cheap (55 `str.find` calls over 22 KB) and must be *tested*, not assumed.

**This is a recall-bearing change to the highest-stakes extraction module, so it is
recorded as a proposal, not applied here.** 152 date-extractor tests pass on this tree
(`tests/test_dateextract*.py`, `tests/test_wave8_dates_fa_hu.py`) and are the baseline any
fix must hold green.

## 4. Cheaper, unambiguously safe wins in the same path

**`_is_code_token` reads an environment variable per token.**
`src/analytics/extract.py:344` opens with
`os.getenv("OO_CODE_TOKEN_FILTER", "1") == "0"`, and `_terms` calls it once per unigram
*and* once per token of every bigram and trigram window — roughly 6× the token count.
Profiled over 16 articles: **130,497 calls, ~8,150 per article**, and `os.getenv` →
`os.environ.__getitem__` → `encodekey` accounts for **0.36 s of the 15.8 s profile**.
`_alnum_transitions`, the per-character loop behind it, is another 0.80 s and recomputes
the same answer for the same token up to six times. Hoisting the flag to a cached read and
memoising per token is behaviour-preserving and worth **~8 % of ingest CPU**.

**`extract_article` parses the same HTML twice.** `src/ingest/extract.py:41` calls
`trafilatura.extract(...)` and then `trafilatura.extract_metadata(...)` on the same
string. Cheap here (6.9 ms) *because the fixture carries `article:published_time*`.
Without a parseable date, `extract_metadata` falls through `htmldate.find_date` into
`dateparser`'s full locale search: **measured at 434 ms per article**, 44 % of the whole
profile, with `regex.compile` called 954 times. That is a tail every page with awkward
date metadata pays, on the ingest hot path.

## 5. The A/B: nothing regressed in the last few days

`collect_throughput_bench.py stages --repo <worktree>` across the cycle
(⚠ the clone this session started from was **shallow** — 517 commits, per CLAUDE.md
rule 5b — and `git fetch --unshallow` was required before any of this archaeology was
trustworthy):

| tree | `extract_dates` | total per article |
|---|---:|---:|
| 2026-06-15 | 14.0 ms | 117.6 ms |
| 2026-07-01 | 61.7 ms | 181.9 ms |
| **2026-07-15** | **141.9 ms** | **263.3 ms** |
| 2026-08-01 | 140.8 ms | 257.5 ms |
| 2026-08-13 | 144.9 ms | 273.2 ms |
| 2026-08-23 | 136.8 ms | 258.6 ms |
| 2026-09-05 | 147.9 ms | 273.3 ms |
| 2026-09-10 (HEAD) | 141.8 ms | 259.7 ms |

Whole-pass throughput agrees: 2026-08-23 → **2.59 art/s**, 2026-09-05 → **2.51**,
HEAD → **2.54**. Within noise.

Two further hypotheses were tested and **refuted**:

* **Corpus growth.** Pre-filling 0 / 5,000 / 25,000 articles with 40 keyword mentions
  each (up to 1M mentions, a 527 MB database) changed pass throughput not at all:
  2.22 / 2.28 / 2.30 art/s. The dedup and keyword indexes hold. *Caveat: plaintext store;
  SQLCipher pays a codec decrypt per page on top, so this is a floor.*
* **Boot / import weight.** `import src.api.main`: 2.41 s (2026-06-15) → 3.50 s (HEAD).
  Real growth, irrelevant at this scale.

## 6. The mechanism that CAN produce a sudden, persistent slowdown

Nothing above explains a *step change* a few days ago. One thing in the tree can, and it
is worth checking on the live install before anything else, because it survives restarts.

`collect_throughput_bench.py governor`, w_max = 50, 1.5 s tick:

```
no contention                        50 ->  50   reason='at-ceiling'
cpu_saturated (sys CPU >= 92%)       50 ->   1   reason='cpu-saturated'   (73 s to the floor)
writer_saturated                     50 ->   1   reason='writer-saturated'
mem_low (avail < 512 MB)             50 ->   1   reason='mem-low'         (7.5 s to the floor)
    mem_low permit trace: [50, 25, 12, 6, 3, 1, 1, 1, 1] ...
```

Three observations, in order of how much they matter:

1. **`mem_low` halves permits every tick and reaches 1 in five ticks**, and — unlike the
   other two flags — that floor is **persisted**. `scheduler/capacity.record_pass` writes
   it to `data/collect_capacity.json`, and the next pass uses it as both the seed *and*
   the `ramp_ceiling`, so the collector cannot climb back within a pass. Over Tor that is
   the difference between **1.91 and 0.45 articles/second — a 4.2× slowdown that survives
   restarts.** Recovery is a geometric ×2 per clean pass (six passes from 1 to 50), but it
   only fires if the pass stops tripping `mem_low` — and the floor is a **fixed 512 MB of
   system-wide available memory** (`collect_perf._DEFAULT_MEM_FLOOR_MB`), which a box also
   running Ollama can sit under permanently regardless of what the collector does.
2. **`cpu_saturated` fires at 92 % system-wide CPU** — which, by §2, is what a *healthy*
   collector on a small box produces by itself. The governor then treats the collector's
   own useful work as contention and walks the permit count down. `bandwidth.py`'s comment
   says CPU saturation "costs throughput, not the machine"; the response to it still
   reduces throughput.
3. **`machine_floor.capped_workers` caps fan-out at 8** on any machine under 4 GB total or
   1 GB available (`FLOOR_MAX_WORKERS`, landed 2026-09-03). By the table in §2 that is
   1.49 vs 1.91 art/s over Tor — a **22 % cut** — applied silently.

This was live in the harness, not just modelled: during a *healthy* 50-worker pass here
the governor was already walking down (`permits: 50 … 49, 49, 48, 47`) and the app's own
verdict was `writer-bound`.

**The operator cannot see any of this where they watch collection.**
`capacity.state_report` is rendered only inside the diagnostics report payload
(`src/api/diagnostics.py:2421`, `collection.learned_concurrency`); the task manager's
Active/Schedule subtabs never mention that the pass is running 1 worker of a configured
50, or why. A pinned ceiling is therefore indistinguishable from "the app got slow".

## 7. What to check on the live install, in order

1. `data/collect_capacity.json` — if `ceiling` is present and small, **that is the
   slowdown**, and deleting the file restores the configured fan-out for the next pass
   (it is a cache of a measurement, never operator state).
2. The diagnostics report's `collection.learned_concurrency` — `ramp_capped_at` vs
   `configured_max_workers`.
3. `data/collect_perf.jsonl`, last summary line — `bottleneck.verdict`,
   `mem_low_ticks` / `samples`, `peak_permits`.
4. Whether `memguard` is engaging: scheduler status phase `paused-low-memory`,
   and the engage counters in the soak window.
5. `collect_rate_mode` — `"target"` deliberately parks workers at 500 KiB/s; the top-bar
   `#rate-toggle` (invariant #4) flips it.

## 8. Proposals, none applied here

| # | change | measured value | risk | status |
|---|---|---|---|---|
| P1 | narrow the month alternation to names present in the text | `extract_dates` 140 → ~20 ms; ~1.8× collector throughput | recall-bearing; needs the 55 non-letter-run names handled and the 152 date tests green | **SHIPPED — see §10** |
| P2 | hoist `OO_CODE_TOKEN_FILTER` out of the per-token path; memoise the shape predicate | ~8 % of ingest CPU | none — pure | **SHIPPED — see §10** |
| P3 | bound `htmldate`'s `dateparser` fallback in `extract_article` | up to 434 ms on pages with awkward date metadata | changes published-date recall on those pages | open |
| P4 | stop treating the collector's own CPU as contention; make the persisted memory ceiling escapable | prevents a self-inflicted 50 → 1 walk-down and a 4.2× pin that survives restarts | behaviour change to a self-tuning control | **SHIPPED — see §11** |
| P5 | surface `learned_ceiling` / `machine_floor` in the task manager beside the permit count | none — honesty | UI + i18n ×12 | **SHIPPED — see §11** |

P3 is the only proposal still open.

## 10. What shipped (P1 + P2)

Measured by running the two trees **interleaved**, three rounds, so the box's own load
cannot masquerade as a result. (Absolute figures here are lower than §1's for exactly
that reason — the sandbox was busier then. The ratios are what travel, per §9.)

Per-article extraction CPU, 12 articles × 22 KB:

| | base (`a513f898`) | P1 + P2 | |
|---|---:|---:|---:|
| `extract_dates` | 77.6 / 80.8 / 80.2 ms | 7.7 / 7.8 / 8.3 ms | **≈10×** |
| keyword extraction | 23.8 / 24.4 / 25.1 ms | 10.8 / 11.2 / 12.2 ms | **≈2.1×** |
| **total** | **159.4 / 159.9 / 163.0 ms** | **73.8 / 76.7 / 68.0 ms** | **≈2.2×** |

End-to-end collection pass, 96 articles through the real pool, governor and write gate:

| transport | base | P1 + P2 | |
|---|---:|---:|---:|
| 20 ms/fetch, 8 workers | 3.45 art/s | **5.61 art/s** | 1.63× |
| 1.5 s/fetch, 16 workers | 2.62 art/s | **3.63 art/s** | 1.39× |

**P1 — the narrowing.** The ten month-carrying patterns are now compiled from templates
(`_month_re`, a `_MONTH_SLOT` placeholder and a registry), and `_extract` rebuilds them
over `months_present(text)` — after the `_MAX_SCAN` truncation, so the scan sees exactly
the text the patterns will.

*Proof, not assertion.* A differential over **10,629 cases / 11,973 candidates** — every
one of the 555 names in four casings across 19 date shapes, both sides of the `_MAX_SCAN`
boundary, 32 language hints, three anchors — produces an **identical SHA-256** for the
candidates *and* the claimed spans. That differential also earned its keep twice: it
first reported 4,372 differences that were **the harness**, because `str.hash` is
randomised per process and my casing selector used it, so the two sides were reading
different texts; and once fixed it killed six mutations, among them deleting the
substring pass (−986 candidates) and restoring the identity check described below.

*What the review changed.* The first cut carried two extra guards — an "always keep the
case-unsafe names" set and a second scan over `casefold()`. Both **survived every
mutation**, and the honest reading of that was not "keep them anyway": the real
correctness argument is that the scan is *exactly as case-strict as `_month_of`*, the one
function every month loop resolves through, because both lower the same token with the
same method. Verified exhaustively — 555 names × 5 casings × every language hint, zero
cases where the old path yields a date the narrowed one cannot. The keep-set was also
**actively harmful**: its predicate matched all ~26 Greek names (whose `casefold` differs
from their `lower`), silently pinning 30 extra branches into every article's alternation
in every language. Both were removed and replaced by the property, pinned as a test.

*The one real trap.* The no-year loop discriminated its two patterns with
`rx is _MD_NOYEAR_RE`. Under P1 those are patterns rebuilt per document, so they are
never the module-level object — the homograph guard would have stopped firing silently
and `"Marta 30 godina"` would have fabricated 30 March. The loop now carries
`month_first` explicitly; restoring the identity test is mutation M4 and is killed.

**P2 — the flag out of the token loop.** `code_token_filter_enabled()` is read once per
document instead of ~8,150 times, and the pure half of the predicate
(`_is_code_token_shape`) is memoised behind a bounded `lru_cache(4096)`.
`_is_code_token` keeps its exact signature for its three external callers.
A differential over 3,840 terms in 8 languages with an adversarial vocabulary is
byte-identical with the flag **on and off** — and the two hashes differ from each other,
so the check discriminates rather than passing vacuously.

**Tests.** `tests/test_dateextract_month_narrowing.py` (14 tests: the in-process
differential, its own anti-vacuity twin, the partition of the two scan passes, the
case-symmetry property, the pattern-registration guard, longest-first ordering asserted
on behaviour rather than on pattern source, and the truncation boundary). 172 existing
date tests and 21 code-token tests stay green; a 1,599-test sweep across date, keyword,
extraction, analytics, ingest and collect suites is green apart from two
`sqlcipher3 driver unavailable` failures that reproduce identically on the unmodified
tree.

## 9. What this investigation did not measure

* Real hosts, real robots, real Tor. `--delay` is a constant; the app will always look
  better here than in the field.
* SQLCipher. Every DB figure is a floor.
* The pass **tail** and the housekeeping lane — discovery, source enrichment, the briefing
  refresh, the WAL checkpoint. They run *around* `run_scrape_once`, on threads that
  compete for the same GIL, and are outside these numbers. If the perceived slowdown is
  specifically "fewer articles per hour" rather than "each article takes longer", the
  inter-pass tail is the next thing to instrument.
* Any claim about the operator's specific machine. The ratios travel; the absolute
  numbers are this 4-core sandbox's.

## 11. What shipped (P4 + P5)

Neither is a speed change. P4 stops two self-inflicted throttles; P5 makes the remaining
one legible. Together they are what turns "the app got slow" into a number the operator
can read.

### P4a — the CPU back-off asks *whose* load it is

`cpu_saturated` was `cpu_sys >= 92` alone. The collector is CPU-bound in pure Python
(§2), so a healthy pass on a small box produces that reading **by itself** — and the
governor then cut a permit every 1.5 s tick, measured at **50 → 1 in 73 seconds**,
reducing throughput and freeing nothing, because the CPU it "gave back" was the
collector's own. `bandwidth.py`'s own comment already said CPU saturation "costs
throughput, not the machine"; the response to it still cost throughput.

The reading that separates the cases was **already sampled, already logged, and consulted
by no decision**: `cpu_proc_pct`. `collect_perf.cpu_contention()` now compares them, with
the scale difference stated rather than assumed — `psutil.cpu_percent()` is normalised
0–100 across the machine, `Process.cpu_percent()` sums across cores — so our share is
`cpu_proc_pct / cpu_count` and "most of the load is not us" is `others > ours`, a ratio
rather than a second magic number.

| the machine is full because… | old | new |
|---|---|---|
| the collector itself (99 % sys, 390 % of 4 cores) | back off | **no back-off** |
| another process (99 % sys, 40 % of 4 cores) | back off | back off |
| attribution unavailable (no `cpu_proc_pct`, no core count) | back off | back off |

The back-off this app owes the operator's own browser, editor and local model is
**untouched** — this only narrows it to the cases with evidence. Unmeasurable falls back
to the old rule deliberately, and `cpu_others_pct` is logged as `None` there, never 0:
"we could not attribute this" and "there was no other load" are opposite facts.

**THE TRADE-OFF THIS INTRODUCES, stated rather than glossed.** The API server lives in the
same process, so collector threads and the event loop compete for one GIL. The old
blanket back-off therefore had a side effect nobody designed: cutting permits freed GIL
time for the server, so the local UI stayed more responsive during a heavy pass. Not
cutting them can make the UI feel slower while collecting on a small box. That is a real
cost and it is accepted here for two reasons — the throughput it was buying was
*negative* (the CPU was handed back to the same process that wanted it), and the app
already has a purpose-built surface for the actual concern: S3.4's `server_load` block and
the client backoff it drives, fed by `latency.py`'s loop-block watchdog.

**The better signal exists and is not wired**, recorded as a follow-up rather than built
here: event-loop lag is a *direct* measurement of "we are starving our own server", where
CPU saturation is a proxy that cannot tell starving the server from doing the work. A
governor that backed off on measured loop lag would protect responsiveness without
throttling throughput for its own sake. That wants its own measurement pass.

### P4b — the persisted memory ceiling is escapable again

`mem_low` is a reading about the **whole machine** (available memory under a fixed
512 MB), which a box also running a local model can sit under no matter what the
collector does. Under the old rule that was a trap with no exit: every pass counted as
sustained, the floor walked to 1, `min(current, floor)` re-pinned 1, and the relax branch
needed a quiet pass that could never arrive. Over a 1.5 s/fetch transport that is
**1.91 → 0.45 articles/s with no code change, no visible cause, and it survives restarts**
because `collect_capacity.json` does.

A pass that **already ran at a ceiling of 1** and still saw sustained pressure has
demonstrated that concurrency is not the lever, so it now takes the relax branch — one
geometric step, not a jump to the top.

The guarantee is deliberately narrow and checkable: **a stored ceiling of 1 cannot still
be 1 after the next pass.** It does *not* claim the machine climbs back to `w_max` while
external pressure lasts — the record oscillates 1↔2, which is the honest outcome, because
nothing has shown more workers are safe. A machine whose pressure really *is* its own
fan-out reaches a floor above 1, the descent worked, and that measurement still pins
exactly as before.

**This does not weaken the protection**, and the separation is why it is safe: the
ceiling is a *concurrency tuning* hint, while what protects the machine is
`scheduler.memguard` — a different mechanism, with its own thresholds (RSS ≥ 85 % of
total, or available ≤ 256 MB, three consecutive samples), which **pauses collection
outright** and is not a permit count at all. It is untouched and in force at every worker
count.

The stored `reason` also stopped lying: the relax branch wrote "a pass with no memory
pressure", which for this case is false in the very file an operator opens to find out
why their collector is slow.

### P5 — the caps reach the window where collection is watched

Every input already existed and none of it arrived anywhere useful: `state_report` was
rendered only inside the diagnostics report payload (`src/api/diagnostics.py`), and the
machine-floor worker cap only into a log line. `capacity.concurrency_report()` composes
them, rides the `status()` payload the task manager **already polls** (no new endpoint,
no new poll), and the Schedule subtab grows a **Workers** section: what is fetching now,
the limit this pass, the configured maximum, and one plain sentence saying why.

The two causes are kept **apart** because the remedies differ — a learned ceiling is a
measurement that heals itself (and the note says it is a cache, deletable), a machine
floor is a policy with a documented override, and the panel offers `OO_ALLOW_BIG_SCANS=1`
where it applies. A healthy machine gets a plain "nothing is holding it back", so the
section is not only a bad-news panel; an unreadable block says so rather than rendering
as healthy.

The refusal that needed a behavioural test: **no pass in flight draws no permit count at
all**, because 0 workers and no pass are different facts — while a *measured* 0 must still
draw. Those are one character apart in the source (`pg.permits != null`) and opposite on
screen, which no source-level assertion can tell apart.

### Tests

`tests/test_collect_concurrency_panel.py` (10), `tests/concurrency_panel_node_test.js`
(runs the shipped `_concurrencyHtml`; **7 mutants, 7 dead**), plus new cases in
`test_collect_capacity.py` and `test_collect_perf_monitor.py`. 14 strings keyed ×12
locales, spliced in place; all three i18n gates green at CI's own thresholds
(`--min 100`, `--max-untranslatable 569`, `--max-unkeyed-t-calls 312`).

`test_memory_budget.py::test_without_a_denominator_the_old_strict_behaviour_is_kept`
asserted the semantics P4b makes untrue **on purpose**, so it was updated deliberately
with the reason in the test — its actual intent (no denominator is ever invented, and
pressure still pins) is now checked at a ceiling where it still applies.

### Browser-VERIFIED, and it earned the click-through

Not owed this time — driven in Chromium against the running app, with
`data/collect_capacity.json` seeded to the exact state P5 exists to explain (a ceiling
of 1 against a configured 50). The page loads, the first-run wizard dismisses, the real
`ooSubtabs` component opens the Schedule subtab, and the section renders with **no
console errors**. The `#oo-tip` bubble (invariant #17) shows the translated method on
hover, and switching to French through `OOI18N.setLang('fr')` renders every string
translated — so the ×12 claim is *verified*, not asserted.

**It also found a defect no node test could.** `.vitals-pop .vr b` clamps a row's value
to 160px with an ellipsis — correct for a figure, and it truncated the reason to
*"this machine backed o…"* running off the panel edge, destroying the one thing this
section exists to let an operator read. The reason is now a wrapping line rather than a
`.vr` value. The HTML was correct throughout; only the rendered page showed it, which is
precisely the argument for the click-through rather than an argument against the node
harness.

---

## 12. What shipped (P3) — and why the item turned around under measurement

P3 was recorded as a SPEED item: *"`trafilatura.extract_metadata` → `htmldate.find_date`
→ `dateparser` runs a full locale search: measured 434 ms per article."* Bounding it was
expected to be a straight trade of published-date recall for throughput, which is why it
was left as a ruling rather than a cleanup.

Measuring it first changed the argument. `collect_throughput_bench.py dates` is the
reproduction; run it before touching any of this.

### 12.1 The bound costs nothing where a real date exists

| date placement | unbounded | bounded |
|---|---|---|
| `meta article:published_time` | 2026-03-04 · 1.6 ms | **2026-03-04** · 1.5 ms |
| JSON-LD `datePublished` | 2026-03-04 · 1.5 ms | **2026-03-04** · 1.4 ms |
| `<time datetime>` | 2026-03-04 · 2.3 ms | **2026-03-04** · 2.3 ms |
| `<span class="date">` | 2026-03-04 · 2.2 ms | **2026-03-04** · 2.3 ms |

Those four are what a real news page uses. Nothing is traded on any of them, which is the
precondition for the rest of the argument being worth making.

### 12.2 The reason it shipped is not the speed

On a page with **no publication date at all**, the last resort does not answer "unknown".
It answers.

| the page's only date-like text | unbounded returns | bounded returns |
|---|---|---|
| `Copyright 2019 The Institute.` | **2019-01-01** | `None` |
| a *Related articles* sidebar | **2011-01-12** | `None` |
| `Officials met on 11 September 2001…` in the body | **2001-09-11** | `None` |

Each of those is stored as *this article's publication date* and travels into the
timemap, the agenda and every trend as fact, with nothing downstream able to tell it from
a real one. `None` is the true answer and one the app already renders honestly. A project
whose first non-negotiable is *no fabricated anything* cannot keep a date source that
fabricates on exactly the pages where it is the only source.

### 12.3 What the bound genuinely loses, stated rather than glossed

| date placement | unbounded | bounded |
|---|---|---|
| `<a class="date">` | 2026-03-04 | **lost** |
| `<td class="date">` | 2026-03-04 | **lost** |
| a date only in free text | 2026-03-04 | **lost** |

Two of the three are not the free-text resort at all — they are htmldate's element scan
narrowing from `.//*` to a fast list (`div h2 h3 h4 li p span time ul`), so an anchor or a
table cell falls outside it. These are correct dates the bounded path misses. That is why
`OO_EXTENSIVE_DATE_SEARCH=1` restores the old behaviour whole, with §12.2 attached to it.

### 12.4 The 434 ms reproduces — but only once the page is not in English

The recorded figure did not reproduce at first, and chasing that is where the real
characterisation came from. htmldate's `custom_parse` handles the English date shapes
without ever reaching `dateparser`; only the shapes it cannot parse go to the locale
search. So the cost is **language-dependent**, which matters rather a lot for a collector
that reads twelve.

| language | distinct dated nodes | unbounded (cold) | bounded | ratio |
|---|---:|---:|---:|---:|
| en | 150 | 12.4 ms | 9.1 ms | 1.4× |
| fr | 150 | 27.7 ms | 9.4 ms | 3.0× |
| **es** | 150 | **219.7 ms** | 9.2 ms | **23.9×** |
| **ru** | 150 | **206.7 ms** | 15.1 ms | **13.7×** |

**Two corrections to the recorded figure, both of which a reader needs.** First, it is not
a flat per-article tail: `htmldate.extractors.try_date_expr` is an `@lru_cache(8192)` over
candidate expressions, process-wide, so the same page measured *warm* costs ~10 ms rather
than ~220 ms. A long run sits between the two and moves toward the cold figure as the
corpus's distinct date expressions exceed 8,192. Second, the first run of the bench itself
reported **1.2× for a 30× effect**, because it reused `_body()` — which deliberately seeds
30 % of its paragraphs with *"On 11 September 2001…"*, so htmldate found a date early and
never reached the last resort. The mode now builds on a date-free body, and says so where
the function is defined.

### 12.5 Guarded

`tests/test_extract_date_bound.py` — twelve tests, and the middle block is the load-bearing
one: it asserts that the unbounded search returns a **wrong** date where the bound returns
none, and fails loudly if upstream ever stops fabricating, because the case for the bound
would then have to be re-argued rather than quietly inherited. Four mutants, four dead:
restoring the upstream default, hardcoding the bound past the flag, defaulting the flag on,
and reading the flag by truthiness instead of an explicit `"1"`.

---

## 13. What shipped (P6) — a control whose headline is that it does not fire

P6 came out of P4a's own honest cost: the API server shares this process, so collector
threads and the event loop compete for one GIL, and the blanket CPU back-off that P4a
removed had an undesigned side effect — cutting permits freed GIL time and kept the local
UI responsive during a heavy pass. The queue recorded loop lag as the direct measurement
of that concern, and asked for *a threshold picked from real readings, not guessed*.

### 13.1 The readings, and they say the premise does not hold

`collect_throughput_bench.py loop` puts a **synchronous** handler body on a real event loop
— the shape `latency.py` exists to police — and runs it against real per-article extraction
in collector threads.

| workers | art/s | handler p50 | handler p95 | lag p50 | lag p95 | lag peak | window ≥250 ms |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | — | 3.5 ms | 4.0 ms | 0.9 | 2.4 | 3.1 | 0 % |
| 1 | 30.8 | 3.4 ms | 4.3 ms | 5.5 | 15.3 | 53.2 | 0 % |
| 8 | 23.3 | 3.4 ms | 3.8 ms | 1.7 | 10.7 | 11.2 | 0 % |
| 16 | 22.3 | 3.5 ms | 5.3 ms | 1.9 | 12.1 | 104.3 | 0 % |
| 32 | 22.5 | 3.4 ms | 4.0 ms | 1.6 | 20.1 | 379.7 | 3 % |

**The handler column does not move.** From zero collector threads to thirty-two, a
synchronous handler on the loop costs 3.4–3.5 ms at p50 and ~4 ms at p95. CPython switches
the GIL every 5 ms, so a loop task loses slices, not seconds. **P4a's stated cost is
therefore smaller than it was recorded as being**, and the control P6 asks for does not fire
on the workload that motivated it.

### 13.2 So it ships as a net, and the design is mostly refusals

*The reading is a fraction, not a peak.* `latency.loop_pressure(threshold_ms)` reports what
share of the watchdog's window breached. Neither published number works as a control on its
own: `peak_ms` is sticky over a 10 s window against a 1.5 s governor tick, so the 379.7 ms
singleton above would keep cutting workers for seven ticks after the loop recovered;
`latest_ms` reads near zero on a loaded server that happened to be free at that instant,
which `loop_lag`'s own docstring already said. The fraction calls a spike a spike.

*An absent reading is absent.* No running loop, or a watchdog that never started, gives
`measured: False` with a reason and a `None` fraction — never `0.0`. A broken read reports
itself rather than returning a healthy shape, and never breaks the tick.

*Off is expressed as off.* `OO_LOOP_LAG_BACKOFF_FRACTION=0` disables the control and still
publishes the reading. A threshold set so high it can never be reached would be a disabled
control that still looks armed.

*The reading rides every sample.* Since this control does not fire on the measured
workload, the number is most of what it delivers: an operator must be able to tell *we
watched and it was fine* from *nobody looked*.

### 13.3 P4a's lesson, promoted from a comment to a mechanism

A synchronous call on the event loop blocks it **by itself**, and no number of collector
permits handed back will move that. Cutting anyway is precisely the failure P4a removed —
descending against a cause the descent cannot reach. The difference here is that the
outcome is measurable *within the pass*, so the control checks its own work:
`CollectionMonitor._loop_lag_gate` cuts while the lag holds, and after
`_LOOP_LAG_PATIENCE` (8 ticks = 12 s, deliberately longer than `latency.py`'s own 10 s
window, so the samples being judged were taken *after* the first cut) with no improvement
it says so once and stands down. A healthy tick re-arms it, so standing down is
per-episode rather than for the pass.

The defaults — 250 ms sustained across a quarter of the window — sit far outside anything
the bench produced. If this fires, something is happening the bench could not make happen.

### 13.4 Guarded

`tests/test_loop_lag_backoff.py` — seventeen tests, and the discrimination the queue asked
for is driven through the real `_tick`: a CPU-saturated collector with a responsive loop
must not be cut (that was the measured 50-to-1 collapse), a starving loop must. **Eleven
mutants, eleven dead**: deciding on the peak instead of the fraction, treating an absent
reading as measured, removing the give-up rule, latching it for the whole pass, giving up
while the cuts *are* working, letting loop-lag mask a more certain harm, raising instead of
reporting on a broken read, dropping the reading from the sample when the control is quiet,
bypassing the gate entirely, keeping the observation only when the control acted, and
emitting the pass note on a zero reading.

The last two came from re-reading the diff before pushing rather than from the matrix, and
they are the same defect twice: the worst reading of the pass was being recorded *inside*
the gate, so it went missing in the two cases a reader most needs it — the back-off
switched off by configuration, and lag that stayed under the bar. Both would then have read
as a pass with no lag at all. An observation must not be conditional on the control having
chosen to act.

One more found the same way, and it would have been a red CI rather than a silent hole:
two of the tick tests set `cpu_sys=99, cpu_proc=390`, which reads as *"the machine is full
and it is us"* on a 4-core box and as *"it is someone else"* on a 16-core runner — where
the tick would back off for CPU saturation and never reach the property under test. The
core count is now pinned, because it is not what those tests are about.
