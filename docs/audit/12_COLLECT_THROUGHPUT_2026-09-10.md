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

| # | change | measured value | risk |
|---|---|---|---|
| P1 | narrow the month alternation to names present in the text | `extract_dates` 140 → ~20 ms; ~1.8× collector throughput | recall-bearing; needs the 55 non-letter-run names handled and the 152 date tests green |
| P2 | hoist `OO_CODE_TOKEN_FILTER` out of the per-token path; memoise `_alnum_transitions` | ~8 % of ingest CPU | none — pure |
| P3 | bound `htmldate`'s `dateparser` fallback in `extract_article` | up to 434 ms on pages with awkward date metadata | changes published-date recall on those pages |
| P4 | stop treating the collector's own CPU as contention, or measure *process* CPU headroom rather than system-wide | prevents a self-inflicted 50 → 1 walk-down | needs a ruling: the flag is also a real signal when another process is the load |
| P5 | surface `learned_ceiling` / `machine_floor` in the task manager beside the permit count | none — honesty | UI + i18n ×12 |

P1 is the one that matters. P2 is free. P4 and P5 are the pair that turn "the app got
slow" into a number the operator can read.

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
