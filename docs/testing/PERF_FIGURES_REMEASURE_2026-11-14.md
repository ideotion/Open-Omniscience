# Cited performance figures: re-measured or marked (2026-11-14)

This covers OPEN_QUEUE's list of cited figures with no source or measuring statement (R310's premise sweep, items (a) to (h)). Each figure is either re-measured here, with the machine, size and date, or marked as a field observation this box cannot reproduce. A field figure is never replaced by a probe figure: when both exist, both are kept, each with its label.

## The machine

All PROBE figures below come from one run on 2026-11-14:

- **Machine:** a cloud VM with 4 vCPUs (Intel Xeon @ 2.30 GHz) and 15 GiB RAM, running Linux 6.18. The disk is a fast virtual disk.
- **Software:** Python 3.13.18, SQLite 3.53.1, and SQLCipher 4.20.0 community (on SQLite 3.54.1).
- **Libraries:** the optional libraries were installed in a throwaway environment at the project's pinned ranges: vaderSentiment 3.3.2, numpy 2.5.3 and pqcrypto 0.4.0 (`pqcrypto>=0.3.4,<1.0`).
- **Other load:** none on the box, except the 32 spinners in (f).

## The figures

| item | cited figure and site | what was run here | result | verdict |
|---|---|---|---|---|
| (a) | shutdown write-back «about 90 s for 1.4 GB» (`src/api/main.py`, `src/monitoring/forensics.py`, `src/database/shutdown_checkpoint.py`, `src/monitoring/win_power.py`) | a fresh store in WAL mode with auto-checkpoint off, filled with 380,000 rows of 3,000 random bytes: a 1.57 GB `-wal` of distinct, appended pages. Then `PRAGMA wal_checkpoint(TRUNCATE)` was timed once, plain and encrypted | plain 3.2 s, encrypted 3.0 s | **PROBE only; the field figure stays an unreproduced field observation.** The probe log is append-only on a fast disk. The field log's page scatter, its disk and the date are not recorded, so the 30x gap is not explained by anything measured here |
| (b) | «a cold alerts compute measured 558 s in the field» (`src/api/main.py`) | not run | none | **unreproduced field observation.** Store size, date and statement are not recorded, and this box has no corpus at field scale |
| (c) | «the briefing refresh measured 36 s at the live corpus scale» (`src/signals/near_dup.py`) | `near_duplicate_clusters(threshold=0.5)`, the briefing's call, on N documents of 20,000 characters each, cut from this repo's `docs/` (fixed seed 7), with the cache cleared | 200 docs: 7.97 s pure Python, 1.00 s with numpy. 1,000 docs: 40.1 s pure Python, 5.18 s with numpy | **PROBE; the field figure stays an unreproduced field observation** (the live scale is not recorded). The probe agrees with the comment's reason: the pure-Python inner loop dominates, and numpy cuts it about 8x |
| (d) | VADER on an 80 KB English page, «1.5 s per pass, now 36 ms» (`src/analytics/sentiment.py`) | `polarity_scores` on the first 80,000 characters of `docs/USER_MANUAL.md`: stock analyzer 5 runs, `make_analyzer()` (the linear one) 21 runs | stock median 1,029 ms (979 to 1,146); linear median 21.4 ms (20.9 to 24.2) | **reproduced** (about a 48x ratio, against about 42x cited). The original statement is in `src/analytics/vader_linear.py`'s docstring: 2026-09-27, the same text. The machine was not recorded |
| (e) | ML-DSA-65 round trip «1.6 ms» (`src/custody/signing.py`) | the probe's own round trip (keygen, sign, verify), 201 runs | median 0.73 ms, p95 1.41 ms | **reproduced** (same order; this box is faster). The cited figure's library version is not recorded |
| (f) | «worst assembly of a real 4-worker pool under 8x CPU oversubscription: 92 ms», «132 ms against 120 ms», «2 of 200» (`src/monitoring/llm_throughput.py`, `tests/test_llm_throughput.py`) | 32 busy-loop processes (`while True: pass`) on the 4 vCPUs. Then 200 trials of creating a `ThreadPoolExecutor(max_workers=4)` and timing until four submitted calls pass a 4-party barrier together | median 12.1 ms, p99 28.1 ms, worst 32.1 ms (no spinners: worst 1.7 ms) | **reproduced in kind, not in magnitude**: the worst case here is about a third of the cited 92 ms. The cited spinner type and trial count are not recorded. The 132 ms and 2-of-200 figures belong to the retired timing assertion, which was not re-run. The design does not depend on these magnitudes: the rendezvous is structural, and its 10 s timeout is about 300x the worst case measured here |
| (g) | `Config._load_yaml_files` parses the 1.4 MB sources file for an attribute nothing in `src/` reads (`src/config/settings.py`) | not run (WAL's sweep timed `Config()` at 3.8 to 5.0 s alone on 2026-10-27, finding A8) | none new | **kept.** The "sequence argument made in the PR #1548 fold" does not appear in PR #1548's body or its commits; #1548 changed `src/law/track.py` and `src/api/database.py` only. The argument behind (g) is WAL's finding D2 in `wal-lane/premise-sweep-2026-10-27.md`, which says to leave it. Removing the code is a source change outside this measurement pass, so the queue entry stays as written |
| (h) | `keyword_mentions` whole-table count, field figures 43 s, 55 s and 182 s (`src/api/database.py`) | not re-run: it already carries a labelled PROBE (9.9 M rows, SQLCipher 4.12.0, `count(id)` 1.1 s, `count(*)` 0.73 s) | none new | **already recorded.** The field figures stay observations of the bare `count(*)` on a 12 M-row corpus. What would settle it is still one `keyword_mentions_recount_after_s` figure from a field box |

## How to re-run

The scripts were throwaway scratch files and are not in the repo. Each recipe is stated in full above, and none needs the network:

- (a) runs on a 1.4 GB scratch file and uses about 3.2 GB of disk while it runs.
- (c) and (d) read `docs/`.
- (e) needs the `[pqc]` extra.
- (f) needs nothing but the standard library.
