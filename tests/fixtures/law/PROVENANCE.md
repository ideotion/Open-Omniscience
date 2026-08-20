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
