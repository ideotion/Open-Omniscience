# Q509 — the per-form counts, and the total that does not sum them

`S04-07` PR 2. Run with:

```
python docs/audit/cross-language-forms-2026-09-17/forms_probe.py
```

It seeds ten articles through the **real** `index_article` (never by inserting rows),
rebuilds the FTS index, and calls the shipped `insights_concept_forms` handler directly.
`forms_output.txt` is that run, verbatim.

## What it demonstrates, and why each line is in the fixture

**The per-form figures OVERLAP, and the total does not.** One article — *"the climate
summit, or le climat, in one article"* — deliberately carries two forms of one concept.
It is counted under `climate` **and** under `climat`, and **once** in the total:

```
forms with a hit : climat 3 · climate 3 · clima 1 · klima 1
sum of the forms : 8
TOTAL (distinct) : 7
```

Without that one document the readout would have been additive (6 = 6) and the caveat
that says *"these do not add up to the total"* would have been a claim with no
measurement behind it. That is the difference this probe exists to close: the caption is
now something the fixture **shows**, not something the endpoint asserts.

**The cap bites, and says by how much.** `covid-19` is a 120-form ring, so it exercises
the switch Q503's note gives the reader:

```
=== term='covid-19' literal_cap=True  ===  measured_forms: 40   total_forms: 120  capped: True
=== term='covid-19' literal_cap=False ===  measured_forms: 120  total_forms: 120  capped: False
```

`total_forms` is the same **120** on both sides. The cap bounds which forms were counted
and never the number reported as the concept's size — the anti-capping rule, on the
surface most exposed to breaking it. The reader sees *"40 of 120 forms counted"* and
knows the list under it is partial.

**A form that cannot be counted is absent with a reason, never a `0`.** No form was
unmeasurable in this run (`unmeasured forms: 0`), so that refusal is proven in
`tests/cross_language_lens_node_test.js` against a payload that carries one, rather than
here. A `0` would say *"this corpus has nothing in that language"*, which is a different
fact from *"this could not be counted"*.

## What it does NOT settle

- **Scale.** Ten articles. The per-form cost is one full-text count per form, so an
  uncapped readout on a 120-form ring is 120 counts against the live corpus — see the
  PR body for the measured per-form figure and the projection. The operator's own run on
  the real corpus is the number that matters and is listed as an operator step.
- **Ordering.** `ordering: corpus-frequency` here because the resolver was given a
  frequency map. On a corpus where no form has been measured it falls back to
  `ring-order` and says so; that path is covered in `tests/test_concept_resolution.py`.
- **The browser.** This drives the handler, not the chip. What the reader sees is driven
  in `tests/cross_language_lens_node_test.js` and walked in Chromium; see the PR body.
