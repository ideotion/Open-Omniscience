## 2026-10-27 — a merge that is not transactional is stopped BEFORE it begins, because the stop is the only atomic part

**Found while giving the persisted rollup refresh the generation check of #1551.** `refresh_keyword_daily` merges the mention tail with an UPDATE, an INSERT and, last, a watermark write. DuckDB runs them as separate statements, so a stop between the first statement and the watermark leaves a merged store whose watermark did not move, and the next refresh adds the same tail again.

**Rules.**
1. Put the comparison (a generation, an epoch, a deadline) at the last boundary BEFORE the first write of a non-transactional sequence, and never inside it. The cost is the width of the sequence, named as a stated limit; the alternative is a stop that corrupts.
2. A stop before the writes drops what the stopped step staged (here the stage table), so the persisted file does not carry the leftovers of every stopped attempt, and the retry is then compared with a full rebuild in the test: the proof that nothing was added twice.
3. The hook is the build's own (`on_batch(stage, rows_done)`), passed through the refresh to the full path too: one signature, one comparison, no second path.
