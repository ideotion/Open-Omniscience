## 2026-10-13 — analytics/stoplist: stoplist batch 5, language group 4 (PR #1368)

- **2026-10-13 · analytics/stoplist (R131, the fourth of the T5 batches; the stoplist thread, one independent read).** 150 words appended to id (48), ms (64) and tl (38); `ms.yml` and `tl.yml` are new files (the loader
unions every file in the directory). By the triage's codes: 65 function words, 69 number words (the Indonesian ordinals and rupiah amounts, the Malay ringgit amounts, the Tagalog clock times and ordinals), 9 calendar
words, 2 attribution verbs, 5 quoted-word debris with a trailing apostrophe. Reading each word's other languages left out id `isn` and two Arabic prayer words, and tl `rin` (the Japanese given name), `naman` (the
Indian given name), `kanya` (Hindi "Virgo"), `halos`, `mula`. **Vietnamese was deliberately not done:** the triage coded 73 of its 82 candidates as fragments, but every Vietnamese syllable is a word and the keywords are
made of them (`thủ` is inside "thủ tướng", `nẵng` inside "Đà Nẵng"), and a stopword drops every phrase that contains it; the list waits for a reader of Vietnamese. The words are declared in
`tests/test_analytics_extract.py::added_since_migration` with the curly spelling of the five apostrophe forms. Hidden at query time, no re-index. The lists the tool was given and each language's tool output are in
`/mnt/project-files/keyword-session/t5-group4-2026-10-13/`.
