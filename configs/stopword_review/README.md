# Stopword review batches (R98, D11)

The stoplist grows in REVIEWED BATCHES, through Settings → Advanced → Keywords → "Stopword
review". One file per language, `<lang>.yml`:

```yaml
language: en
batches:
  - id: en-2026-10-a                 # stable, never reused
    generated: 2026-10-01            # when the candidates were measured
    source: "where they came from"   # the log, the triage thread, a report
    method: "how they were picked and what the numbers mean"
    candidates:
      - {term: comments, articles: 1234, mentions: 5678, class: page_word, note: "optional"}
```

`class` is one of `function_word`, `page_word`, `boilerplate`, `other`. Files whose name starts
with `_` are not batches (`_keep_platform_names.yml` lists the platform names that count, R104).

What the screen does: it shows the candidates with the evidence on this install, records an
accept / reject per word, and EXPORTS the accepted words as a reviewed batch. It never changes a
stoplist itself: a stoplist only changes in a release, merged from an exported batch after the
collision check (a word hidden in one language may be content in another). No control sets a
keyword's kind (R107). These files are a worklist, not engine input, so they are not hashed by
the index engine identity.
