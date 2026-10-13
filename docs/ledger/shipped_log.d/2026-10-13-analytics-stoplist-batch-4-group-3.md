## 2026-10-13 — analytics/stoplist: stoplist batch 4, language group 3 (PR #1362)

- **2026-10-13 · analytics/stoplist (R131, the third of the T5 batches; the stoplist thread, one independent read).** 288 words appended to sr (134), bg (49) and el (107) from the triage's accepted candidates (221 function
words, 31 number words, 29 calendar words, 8 site chrome), judged against the same merged log as groups 1 and 2 (sha256 6467504ab8ab). Reading each word's `language_signature` and what the word means in the other
languages of the project left out the Serbian `tri` and `kojima` (added by the independent read: the Indonesian port Tri Sakti, the Vietnamese "tri thức", the surname Kojima), `kod` (code in Swedish, Norwegian, Polish, Turkish), `dok`, `ono` (the surname), `ove` (the given name), `toga`, `smo` (the SMO acronym), `niko`, `niti` (NITI Aayog), `iza`,
`bile`, `tome`, `neka`, `ovi`; the Bulgarian `шест` (Russian "pole"), `ото`, `макар` (the given name); and the English `microgreens` and `servicers` in the Greek log. The words are declared in
`tests/test_analytics_extract.py::added_since_migration` with the curly spelling of each Greek elided form (`απ'`, `κατ'`, `καθ'`, `παρ'`). Hidden at query time, no re-index. The lists the tool was given and each
language's tool output are in `/mnt/project-files/keyword-session/t5-group3-2026-10-13/`.
