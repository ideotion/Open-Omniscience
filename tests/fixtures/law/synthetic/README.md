# The synthetic jurisdiction — `ZZZ` (Q1018 = a, brief S04-10 S2)

Q1018 asks for "a synthetic wiki edition, a synthetic OSM extract and a **synthetic
jurisdiction** in `tests/fixtures/`, so every lane's pipeline runs end-to-end in CI
without a socket". This is the law lane's.

## Why `ZZZ`, and why that matters

`ZZZ` is an ISO 3166-1 **user-assigned** alpha-3 code: the standard reserves `AAA`,
`QMA–QZZ`, `XAA–XZZ` and `ZZA–ZZZ` for private use and will never assign them to a
country. So a fixture keyed on `ZZZ` cannot collide with a real jurisdiction, and a row
that leaks from a test into a real store is *identifiable as synthetic on sight* rather
than sitting in the corpus as a plausible foreign statute.

It also exercises a real path rather than a special case: `country_display_code("ZZZ")`
returns `"ZZZ"` (an unrecognised value comes back unchanged, which is the catalogue's
long-standing contract — junk stays visible instead of being masked by a fabricated
code), so the law model's alpha-3 guard sees a well-formed code and the pipeline runs
exactly as it would for `GBR`.

## What is here

| file | what it is |
| --- | --- |
| `act.v1.clml.xml` | The Measurement Standards Act, first capture. Three provisions across two parts. |
| `act.v2.clml.xml` | The same Act after an amendment: section 2 reworded, section 4 inserted. |
| `act.translation.clml.xml` | An **official translation** of the same Act, in `zxx-fr`. A different document with the same identity. |

## What they are NOT

These are **not** real legislation and not a real CLML export. They are hand-written to
the shape `src/law/adapters/clml.py` parses, small enough to read in a diff, and shaped
so that the things this slice claims can be *measured*: the amendment changes one
provision and adds another, so a per-provision timeline has something to show and a
whole-document byte delta could not stand in for it.

The `zxx-fr` language tag is deliberate: `zxx` is the ISO 639-2 code for "no linguistic
content", so this tag cannot be mistaken for real French any more than `ZZZ` can be
mistaken for a real country.

## `treaty/` — one synthetic treaty in six language versions (v0.6.0 C-L2)

The `ZZZ` Act above is aligned across languages because its bodies carry the same
`act-number`. A treaty page offers no number a parser can read, so its language versions
are aligned by a **declared identity** in the catalogue (`src/law/declared.py`). These
files run that path without a socket.

| file | what it is |
| --- | --- |
| `treaty/catalogue.yml` | A synthetic `documents:` catalogue, jurisdiction `INT`. Six rows declare one identity (`act-number` `mtdsg:xviii-1`, `doc_type: treaty`); a seventh declares a **different** treaty; an eighth declares nothing. |
| `treaty/treaty.{en,fr,es,ru,ar,zh}.html` | The six language bodies, plain HTML (so the tracker reads no number from them, which is the point). |

Everything here is **invented**: the hosts are on the reserved `.test` TLD
(`tests/test_law_declared_identity.py` fails if a real host ever appears), the language tags are
`zxx-<lang>` (`zxx` is ISO 639-2 for "no linguistic content", so none of them can be mistaken
for real French, Arabic or Chinese), and the sentences were written by the model that wrote the
test, **not reviewed by a native speaker** -- they only need to be six different texts in six
scripts, one of them right-to-left. They are not the text of any real treaty, and no live UN
Treaty Collection or WIPO Lex URL appears anywhere in this tree: live ingestion waits on the
operator's verified URLs.

The translation kinds are deliberately mixed (`original`, `official` x2, `intergovernmental`,
and two rows that state none and so record as `unrecorded`) so the test sees every state arrive.
