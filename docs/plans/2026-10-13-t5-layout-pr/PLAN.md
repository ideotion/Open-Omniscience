# T5 layout PR: the repeat-agreement marker, the twice-read languages and the empty-ring caveat (R131, 2026-10-13)

The last PR of the T5 keyword cleanup (R131: the stoplist batches first, one language group per PR, then this one). Two parts.

## Part 1: the `repeat_agreed` marker and the twice-read languages

The coordinator's brief (relayed to the keyword thread 2026-10-13; it is the maintainer's marker ruling for the languages whose single triage reading is not trusted alone). It is kept here so it lives in the repo:

1. **Converter** (`probe/to_verdicts.py` in the triage pool, now owned by the keyword thread): write the flag `repeat_agreed` on an N row whose blind repeat also returned N with confidence H and a code that is not `gn` or `lv`. A repeat that returned anything else keeps today's handling (`unstable` if it disagreed, `not_repeated` if there is no repeat row). Never write `repeat_agreed` together with `unstable` or `not_repeated`.
2. **Tool** (`scripts/stopword_batch.py`): `repeat_agreed` is an accepted flag beside `single_reader`; it never unblocks anything (a row with `repeat_agreed` plus `unstable`, `not_repeated` or any unknown flag still blocks). `TWICE_READ = {vi, ko, as, tl}`: for those languages `--apply` accepts a row only if it carries `repeat_agreed` or is listed in a hand-review file (like group 6's second hand reading), and refuses it otherwise with its own reason (`not_twice_read`); for every other language the flag is recorded, not required.
3. **The converter's `--check-tool`** learns the flag: the row matrix covers it, and the check fails if the tool ever accepts `repeat_agreed` with `unstable` or `not_repeated`, or accepts a TWICE_READ row without the marker.
4. **Provenance**: each batch's comment gives the count of rows with `repeat_agreed`, and for a TWICE_READ language says which rule let each word in.
5. **Retroactive check**: Korean shipped in #1371 before the marker existed. The new rule is run over #1371's Korean words; any word with neither a repeat agreement nor a hand review comes out of the stoplist in the same PR, listed in its body.
6. **Vietnamese** still waits for a reader. `as` and `tl` go through the same gate if they have not shipped yet (Tagalog had: #1368 shipped 37 `tl` words, so the same check ran over them and is reported).

What the PR does, as measured:

* Tool and tests: `scripts/stopword_batch.py` (`ACCEPTED_FLAGS`, `FLAG_STEMS`, `TWICE_READ`, `--hand-reviewed`, the `not_twice_read` refusal, the provenance counts) and `tests/test_stopword_batch.py`.
* Converter, in the pool: the flag, its refusal to write beside the two blocking ones, the extended `--check-tool`, and `DECISION-FILE-FORMAT.md`. The decision file is regenerated as a NEW file (`full.repeat-agreed.tsv`, sha256 prefix `47400de97c79`) and the old one (`beb3efd563e5`) stays, because the shipped batches name it. Row for row only the flags column differs, by an appended `repeat_agreed` on 6,580 N rows; the gate accepts 6,623 N/H rows without a blocking flag, and the other 43 are rows whose repeat called the word N/H under a `gn` or `lv` code.
* Retroactive check, with the tool's own gate over the shipped words: Korean 26 words, **one comes out** (`참석했다`, "attended": first called a phrase fragment, then an everyday verb, so the readings disagreed); the ten Latin-token Korean entries in `_multilingual.yml` all carry the marker; Tagalog 37 words, none comes out.

## Part 2: the "all hidden" ring caveat as a translated template

`src/analytics/queries.py::_empty_ring_caveat` said, in English only, why a concept resolved to no keyword (every keyword hidden by the stoplist or the user's exclusions, with a count, or none indexed yet). The count is data, so the sentence cannot be a static locale key. Now the payload carries the English sentence (`caveat`), the fixed template it was made from (`caveat_i18n`) and the values (`caveat_vars`), the same discipline as the Home cards' `title_i18n` / `title_vars`; the ring map fills the template with `OOI18N.tf`; the four templates (ring and group, hidden and not indexed) are keyed in all twelve locales (Arabic included, right to left).

Not done: nothing else in the app reads those two payloads' `caveat` as a template; the drill endpoint's caveat is emitted in the same shape but no screen shows it today.
