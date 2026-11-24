## 2026-11-24 — an index a window drops on purpose is rebuilt by EVERY "ensure this index" at open, not only by the heal you moved

Row 407 (R825) moved the R23 bulk-build heal out of `init_db` (a CREATE INDEX over a corpus-sized table inside the
call that opens the database is minutes with nothing on screen) into a background job. Moving the heal was not
enough: two OTHER open-path self-heals also recreate indexes the window drops, because each was written to
"make sure this index exists" long before a window could drop it on purpose. `ensure_hot_indexes` rebuilds four of
the fourteen (`ix_mention_covering`, `ix_mention_date_keyword`, `ix_mention_created_id`,
`ix_mention_article_count`), and `ensure_keyword_mention_source_column` recreates `ix_keyword_mentions_source_id`
unconditionally. The second was found only by a test that runs the REAL `init_db` against a store with an open
marker and fails on any CREATE INDEX naming a droppable index; reading the heal's call site would never have shown it.

THE RULE: when you make a step that creates something "not at open any more", grep the open path for every OTHER
creator of the same objects (`CREATE INDEX` over the same names, `ensure_*`), and pin it with a test that watches
the statements the real open path runs (`before_cursor_execute`), not with a source assertion on the one call you
moved. Both self-heals now skip what the marker owes (`maintenance._owed_to_bulk_heal`).
