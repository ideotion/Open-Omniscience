## 2026-10-27 — the keys existed in all twelve locales; the status line never asked for them

**Found by qual's sweep (R291), read in the source.** The background-AI status line printed `done`, `cancelled` and `error` raw. The three words had been in every locale for a long time (they serve other screens), so the first diagnosis, "a key is missing", was wrong; the code simply never called `t()` on them, and the worker's English line was printed without its keyed frame (`detail_i18n` / `detail_vars`) and beside the translated pill that says the same.

**Rule.** Before adding locale keys for a raw word, grep the locale files for the word itself: a missing key and a missing `t()` call look the same on the page and cost different work. Ask for the key by a literal `t("word")` through a closed map (the string scan reads literals), show a word outside the list as sent, and use `hasOwnProperty` on the map so a prototype name is not printed as a function.
