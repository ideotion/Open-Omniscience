# Law adapter fixtures — provenance

**These files are HAND-AUTHORED, not fetched.** They were written from the documented
CLML (Crown Legislation Markup Language) element vocabulary to exercise the adapter's
structure, date discipline and refusal paths. They are **not** captured samples of any
real response, and nothing here should be read as evidence that the live service returns
this exact shape.

Why: `legislation.gov.uk` is not reachable from the build sandbox — the egress proxy
answers `CONNECT tunnel failed, response 403` (verified 2026-08-20, and previously
recorded 2026-07-24 for the same host plus `eur-lex.europa.eu` and
`gesetze-im-internet.de`). Writing a file and calling it a captured sample would be a
fabricated verification, so the provenance is stated instead.

What that means for the adapter:

* the fixtures prove the adapter's **behaviour** — that it refuses an unrecognised root,
  keeps a number out of its own provision text, never invents a date, reports elements it
  does not model, and refuses when it has recovered too little of the body;
* they do **not** prove the adapter reads the real service correctly. That needs one
  document fetched on a machine with egress. `law_ingest_report` (the law-ingest
  reliability diagnostic) is the instrument that will say so, per document, the moment
  real structured documents exist.

The textual content is invented for the fixture (a fictitious "Example Measurement Act")
so nothing here reproduces third-party material. Real UK legislation is Crown copyright,
published under the Open Government Licence; when a captured sample is eventually added,
record its URL, retrieval date and licence here.

## `synthetic/treaty/` (v0.6.0 C-L2)

Also HAND-AUTHORED and invented, like everything above: six HTML bodies of one fictitious
"Treaty on Measurement Standards" and a synthetic catalogue on the reserved `.test` TLD. They
prove that a **declared identity** aligns six language versions into one identity; they say
nothing about what the UN Treaty Collection or WIPO Lex actually serve, because neither host
is reachable from the build sandbox and no page of either was read. See
`synthetic/README.md`.

## `gii/` (gesetze-im-internet, Q925 = a's second adapter, 2026-11-19)

**These two files are NOT hand-authored**, unlike everything above. They are byte-for-byte
EXCERPTS of the portal's own XML files, cut at a `<norm>` boundary and closed with
`</dokumente>`; nothing inside a kept norm was changed.

| fixture | the portal's file | norms kept |
| --- | --- | --- |
| `gii/gg_excerpt.xml` | `gg/BJNR000010949.xml` (Grundgesetz) | the first 7 of 220 |
| `gii/bdsg_2018_excerpt.xml` | `bdsg_2018/BJNR209710017.xml` (BDSG 2018) | the first 8 of 113 |

Where they came from: `gesetze-im-internet.de` is egress-blocked from the build sandbox (the
proxy answers 403 to CONNECT, re-checked 2026-11-19), so they were taken from an independent
public archive that mirrors the portal's XML daily — the `data` branch of the GitHub
repository `QuantLaw/gesetze-im-internet`, commit `0d22c0e8e411a1d43d9e586ff87ce53cc86e66f1`
("scrape 2026-11-19T04:01:18"), paths `data/items/gg/BJNR000010949.xml` and
`data/items/bdsg_2018/BJNR209710017.xml`. Their `builddate` attributes (2026-05-06 and
2026-07-13) are the portal's own.

What that proves, and what it does not: the adapter reads the REAL shape of the portal's
files, as of that day, rather than a shape written from documentation. It does not prove the
portal serves `/<act>/xml.zip` to this app, or that its `robots.txt` allows it — the release
run's law probe answers that on a machine with egress, and records the adapter's reading of
the fetched archive beside it. The `/<act>/xml.zip` address and the `/gii-toc.xml` index are
the ones two independent open-source tools download (`bundestag/gesetze-tools`'s `lawde.py`,
and the mirror's own `scrape.py`).

Licence: German federal statutes are official works (*amtliche Werke*) under § 5 (1) of the
German Copyright Act (UrhG) and enjoy no copyright protection, so the excerpts may be
reproduced here.
