## 2026-10-13 — analytics/stoplist: stoplist batch 2, language group 1 (PR #1352)

- **2026-10-13 · analytics/stoplist (R131, the maintainer's go on the T5 batches; the stoplist thread, one independent read).** 313 words appended to the ten files de fr es it pt nl sv da ca nb from the triage's
accepted candidates (function words, month and weekday names, number words, site chrome, apostrophe debris), judged against ONE log merged from the 79 shards of 09-30 so that a word's use in another
language is visible to the tool's `content_elsewhere` guard. Reading each flagged word against its `language_signature` left out eleven words with a content sense elsewhere (`falls`, `moi`, `borde`, `medan`,
`gener`, `sis`, `dues`, and the foreign `results`, `readers`, `donating`, `femmes`) and four Catalan mojibake fragments; the tool refused `laut`, which PROVENANCE keeps out for good and which it had accepted. The tool gained
`STANDING_REFUSALS` (sea, tom, fin, laut; no override; a test ties it to the PROVENANCE heading) and the per-word line "also read in articles tagged ...". The 313 words are declared in
`tests/test_analytics_extract.py::added_since_migration` with the curly spelling of each apostrophe word. Hidden at query time, no re-index. The batch comments cite log sha256 6467504ab8ab and verdicts sha256 beb3efd563e5;
`combine_logs.py` and each language's tool output are in `/mnt/project-files/keyword-session/t5-group1-2026-10-13/`. Lesson in `docs/ledger/lessons.d/2026-10-13-stoplist-log-row-has-one-language-and-a-ruling-in-prose-is-not-enforced.md`.
