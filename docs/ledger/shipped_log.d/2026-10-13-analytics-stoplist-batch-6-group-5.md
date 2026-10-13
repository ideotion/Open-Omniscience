## 2026-10-13 — analytics/stoplist: stoplist batch 6, language group 5 (PR #1371)

- **2026-10-13 · analytics/stoplist (R131, the fifth of the T5 batches; the stoplist thread, one independent read).** 381 words: ja 216, ko 26, zh 139; `ja.yml` and `zh.yml` are new files (the loader unions every
file in the directory) and eight entries with Latin letters inside Japanese or Chinese text sit in `_multilingual.yml`, because the script guard (`tests/test_stopword_file_scripts.py`) and the tool's own map
(`stopword_batch.FILE_SCRIPTS`) now know both scripts. These languages differ from the earlier groups: their keywords are whole sentences, so the accepted candidates are mostly page chrome read as one keyword (ja 133,
zh 98), plus function words, weekday and date words, number and clock debris and the stock reporting phrases. **Left out:** the fragments the triage coded `fr` (ko 232 with the apostrophe forms, ja 60, zh 25: a Korean noun
cut at its particle is a real word, and a stopword drops every phrase that contains it), every sentence that names a person, an organisation or an event, the mojibake and the English words (`reserved`, `aired`, `20s`).
The words are declared in `tests/test_analytics_extract.py::added_since_migration`. Hidden at query time, no re-index. The lists the tool was given and each language's tool output are in
`/mnt/project-files/keyword-session/t5-group5-2026-10-13/`.
