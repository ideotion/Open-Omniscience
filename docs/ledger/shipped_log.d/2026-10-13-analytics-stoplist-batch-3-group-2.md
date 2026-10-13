## 2026-10-13 — analytics/stoplist: stoplist batch 3, language group 2 (PR #1358)

- **2026-10-13 · analytics/stoplist (R131, the second of the T5 batches; the stoplist thread, one independent read).** 415 words appended to the six files ru uk pl cs sk sl (ru 28, uk 124, pl 64, cs 87, sk 54, sl 58) from the
triage's accepted candidates, judged against the same merged log as group 1 (sha256 6467504ab8ab, verdicts sha256 beb3efd563e5 as cited in each batch comment). By the triage's codes: 278 function words, 69 number words, 49 calendar
words, 12 attribution verbs (`ph`, the class group 1 did not have), 7 site chrome, 1 fragment. Reading each word's `language_signature` left out the ten `lng` words the Russian and Ukrainian logs hold in another
language (a Russian word hidden through the language-agnostic union is hidden in Russian too: `оккупанты` is signal there), the English `uploads` and the Latin fragments, the Russian fragment `кий`, and pl `maju`
(Indonesian "forward", 18 articles), pl `amet` (lorem ipsum, also a name), sl `glede` (Norwegian "joy", 17 articles). The independent read of the PR took out four more the log could not show: uk `ось` (Russian "axis"), pl `jaka` (Serbian "strong"), cs `mimo` (Spanish "mime"), cs `dubna` (the city). The batch tool no longer writes the readers' labels into the data comment (no model name goes into a
shipped file; the hash pins the readers) and `tests/test_stopword_batch.py` uses neutral labels and fails if the tool writes them again. The words are declared in
`tests/test_analytics_extract.py::added_since_migration`; the one apostrophe word (`ljudstva'`) has its curly spelling declared. Hidden at query time, no re-index. The lists the tool was given and each language's tool output are in
`/mnt/project-files/keyword-session/t5-group2-2026-10-13/`.
