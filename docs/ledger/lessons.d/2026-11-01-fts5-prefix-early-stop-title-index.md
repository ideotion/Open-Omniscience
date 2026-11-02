## 2026-11-01 — FTS5: the ORDER BY decides whether a prefix query can stop early, and four things the instant title index measured

**What was found** (docs: `/mnt/project-files/perf-5tb/DECISION.md`, bench scripts beside it; synthetic Zipf corpus, so the shape transfers and the milliseconds do not):

1. **`MATCH 'inf*' ORDER BY bm25(...)` reads and scores every match.** 4.2 s p50 for one typed character at 1 M documents, growing linearly (0.67 s at 200 k). The same index read `ORDER BY rowid DESC LIMIT n` stops after `n` hits: 0.2-0.4 ms from 200 k to 3 M documents. The ordering, not the engine, was the cost. A prefix index (`prefix='1 2 3 4'`) costs 167 % of the text and 2.3x ingest on bodies, ~0.14 KB a document on titles.
2. **A prefix LONGER than the longest `prefix=` length is not looked up: FTS5 merges the doclists of every word it could complete into.** For a title's commonest word (566 k of 1 M titles) that is 18-30 ms, against 0.15 ms for the same word as an exact term. Rewriting the long prefix as an OR of the exact words that start with it (taken from an `fts5vocab` view) removed most of it; the frequent-word case remains and grows with the corpus.
3. **`fts5vocab` reads the doclist of every term it returns** (it computes `doc`/`cnt`), so it is cheap for rare completions and not for frequent ones.
4. **A SQLite progress handler cannot enforce a per-query deadline on FTS5**: the doclist walk happens inside the virtual-table code between VM opcodes (a 25 ms budget produced a 75 ms worst case). The bound on one keystroke is the cost of the worst single index file, so index FILE SIZE is the deadline knob. One 3 M-document file had a 330 ms tail; six 500 k files had 37 ms.

**The rule it gives:** before adding a "search as you type" surface, decide the ordering first. Anything that needs a global ranking needs every match. If the surface can say "newest first, not ranked" and stop at ten, give it its own small index and say so on the surface. Do not size a prefix index for bodies.

**Where it is enforced:** `src/database/fts_title.py` (`ORDER_SQL`, `INDEXED_PREFIX_MAX`, `EXPAND_MAX_TERMS`), `tests/test_fts_title.py`, `tests/test_search_instant.py`, `tests/instant_rung_node_test.js`.

**A contentless_delete FTS5 table needs no `optimize` to forget deleted words (measured, an Opus read suspected otherwise).** On SQLite 3.45.1 and 3.53.1, 1,500 titles' words (last 8 characters of 12-letter terms, since terms are prefix-compressed in the file) were all in the file before and none after a plain DELETE + VACUUM, with or without `optimize`. The external-content `article_fts` does need it. Check the file, not the theory.
