## 2026-10-13 — analytics/stoplist: stoplist batch 7, language group 6 (PR #1376)

- **2026-10-13 · analytics/stoplist (R131, the sixth of the T5 batches; the stoplist thread, one independent read).** 344 words: am 29, eu 56, fo 15, gl 10, ha 25, kk 76, mk 58, rw 14, sw 61; eight new files
(`sw.yml` existed). By the triage's codes: 258 function words, 40 number words, 38 weekday and month names, 8 attribution verbs and button labels. Every candidate of these nine languages carries the triage's
`single_reader` flag, so each word was read a second time by hand (the tool refused most of the other candidates, gl 139 of 151, mk 159 of 218, eu 122 of 184, but almost all of those are multi-word phrases it never adds; the weighing of senses was the readers' work). **Left out by hand:** am `ኛውን` and `ከፉልሃም`,
the closing-quote forms, eu `hamar` (the Norwegian town) and `elkar` (the Basque publisher), ha `kuma` and `inda`, kk `бес` (the Russian "demon"). **Taken out by the independent read:** kk `сол` and `осы`, mk `кон`, eu `baita`, sw `tisa`, `hawa`, `kabla`, `kumi` (each has a content sense in another language). `stopword_batch.FILE_SCRIPTS` and the script guard gain Ethiopic (am)
and Cyrillic (kk, mk). The words are declared in `tests/test_analytics_extract.py::added_since_migration`. Hidden at query time, no re-index. The lists the tool was given and each language's tool output are in
`/mnt/project-files/keyword-session/t5-group6-2026-10-13/`.
