## 2026-10-13 — a browse page must not read a row it does not show: the quarantine flag sits after the body, so `IS NOT 1` walked the overflow chain of every row the scan stepped over

Diagnostics rank 9 (round of 2026-09-30): on 8 of 16 instances one statement of 24 to 424 s was 91 to 99.6 % of the slowest `GET /api/articles`, and it was
`SELECT articles.id, articles.url, ... articles.content, ...`: every column. Reproduced on a 40,000-article, 2 GB synthetic store
(`src/testing/corpus_gen.py`, about 50 KB an article, plaintext, caches dropped before a shape's first run; cold / warm ms, measured 2026-10-06) and read with
`EXPLAIN QUERY PLAN`. Two causes, both in the shape of the statement and not in a cache. (1) **`quarantined IS NOT 1` cannot use an
index, so the planner read each candidate ROW to test it, and `quarantined` (like `published_at` and `language`) sits AFTER `content` in the
record**: reading any of them walks the whole overflow chain of the body, for every row the scan steps over, including every row an
OFFSET skips (a page 20,000 deep: 715 / 40 ms; the same page with the flag answered from an index: 15 / 4). The exclusion is now
`id NOT IN (SELECT id FROM articles WHERE quarantined IS 1)`: the subquery is answered by the covering `idx_article_quarantined`
(usually a handful of ids, built once as a list), after which the outer test is an id lookup, and the default browse's plan went from
`SCAN ... USING INDEX idx_article_published_at` to `SCAN ... USING COVERING INDEX idx_article_published_at`. The meaning is unchanged: a
row is excluded only when its flag is true, so a pre-migration NULL (never judged) is kept, exactly as `.isnot(True)` kept it. (2) **Selecting
whole rows put every matching row's BODY in the sorter** of any ordering an index does not give (a language filter, a title sort, and a
spill to temp files when they did not fit). A paged browse now asks for ids and loads the page's rows by id in chunks under SQLite's
variable ceiling, the shape the text path has had since S2.5; `limit=None` (the export: every match, bodies included) keeps the single
full-row query.

**What the first version of this change got wrong, found when it was restacked on the repaired-database work:** the id-first form dropped the
whole gate for a reader that INCLUDES quarantined items, and that gate carries one more condition since the repair writes stand-in rows
(`not_a_stand_in_article()`, a place-holder is quarantined, so the default view left it out through the list and the opt-in view needed the
explicit condition). A cherry-pick applied cleanly and the page of a reader who opted in to quarantined items would have shown the place-holder as
an article. Only a test written for the OTHER change (`tests/test_stand_in_rows.py`, the `includes-quarantined` case) failed when the gate was
removed again; `tests/test_browse_plan.py` now pins it too. The rule that follows: **a clean cherry-pick onto a tree that has grown a new
condition for the same statement is not a clean port; read the statement's neighbours for conditions the old change did not know.**

**What the two indexes of the repaired-database work (`idx_article_language_published`, `idx_article_title_nocase`) add:** a title sort and a
language filter read one row per candidate until an index covers them (881 / 42 ms and 1,284 / 56 ms before and after the id-first change alone).
With the indexes the id-first page statement is answered from the index alone, and the plan tests pin both (a covering index in the plan and no
temporary b-tree for the descending orders; an ascending order with the id still descending sorts only the ties of the first key, ids in the sorter).
The 3 ms figures are that module's own measurement; nothing here re-measured a time. **Not proven either:** the 24 to 424 s were measured on the users' much larger
stores and slower disks; nothing here reproduces a statement of that length, and the claim is the plan and the rows read, not a wall time on those machines.
The rule that follows: **test a flag that sits after a large column through an index, by id, never by reading the row**; and when a statement orders or
filters in a way no index gives, make it carry an id and fetch the page. `tests/test_browse_plan.py` pins the answer (the OLD statement, verbatim in shape, as
the reference for every order, filter, direction, page and the include-quarantined view, a NULL flag kept), the plan of the default browse and its deepest
page (no table scan, no sort), the plans of a language filter and a title sort, that a stand-in is left out of every view, and that the statements selecting
`content` carry an id list no longer than the page.
