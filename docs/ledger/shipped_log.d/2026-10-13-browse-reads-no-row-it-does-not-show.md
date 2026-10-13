## 2026-10-13 — browse reads no row it does not show (PR #1349)

- **2026-10-06 · api/browse-reads-no-row-it-does-not-show (WAL / disk thread, diagnostics rank 9; restacked 2026-10-13 on the merged repaired-database work, PR #1349).**
`GET /api/articles` no longer reads an article row it does not return. The quarantine exclusion is answered from the covering
`idx_article_quarantined` by id (the old `IS NOT 1` read each candidate row, and its flag sits after the body, so every skipped row paid
its overflow chain), and a paged browse asks for ids first and loads the page's rows by id, so a sort or a language filter never carries
bodies into the sorter. On a 40,000-article, 2 GB synthetic store a page 20,000 rows deep went from 715 to 15 ms cold and the default
browse's plan from `USING INDEX` to `USING COVERING INDEX`; the export keeps its single full-row query. The reader that includes quarantined
items keeps the stand-in condition (`_quarantine_gate(True)`), which the first form of this change dropped. With the language and title indexes of the
repaired-database work the language filter's and the title sort's page statements are answered from their index too (plan tests; no new time
measured). Lesson: `LESSONS.md` fragment "a browse page must not read a row it does not show".
