## 2026-10-12 — analytics/stoplist: R111 step T2 rest (PR #1341)

- **2026-10-12 · analytics/stoplist (R111 step T2 rest, PR #1341; the stoplist thread, one independent read, the coordinator's check of the folds).** A word the shipped stoplist hides was still counted by
the readers that turn a group or a ring into keyword ids and by the source topics. `supergroup_stats.resolve_member_keyword_ids` (Observatory, rising test, stats, drill-through) and
`api.insights._supergroup_totals` (the Groups panel), `group_stats.resolve_group_keyword_ids` (ring stats, the country drill) and `queries.ring_country_split` now skip a keyword on the list (the
shipped stopwords plus the user's exclusions, `filters.hidden_set()`); `source_topics.derive_source_topics` leaves a hidden tagged keyword out with one `NOT IN`, in the query, so the
`COUNT(DISTINCT article)` stays right where an article carries two keywords of one topic. Only the list hides, not a listing's length rule: a group member and a topic tag are deliberate picks, and
`ai` is both (a length rule emptied the AI family and eight existing tests said so). Thirteen terms of the shipped rings were already on the list (`news` in news-media, `work` in occupation ...), so
the earlier "curated-group totals matter only if a curated member is later stoplisted" was already false. The AI keywords are left on purpose (typed LLM outputs the user confirms or rejects). The
independent read found no block; its fixes were the two ring-level readers the first draft missed, a topic test that passed without the filter (replaced by an overlap test that fails without it), a
chunked `NOT IN` that bounded nothing (ANDed clauses are one statement) and a shipped-row sentence that said the panel and the sky share one resolver. The bulletin half (coverage columns, story
keyword sets, article keywords) is a patch for the export thread. Lesson: `docs/ledger/lessons.d/2026-10-12-t2-count-distinct-filter-in-the-query-and-deliberate-picks.md`.
