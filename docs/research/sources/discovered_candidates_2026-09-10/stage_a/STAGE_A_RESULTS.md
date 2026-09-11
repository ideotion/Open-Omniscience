# Stage A results -- 2026-09-10 22:41 UTC

Kit: `oo-candidate-kit-2026-09-10-a1db266`
Python: 3.13.5 on linux

- **shortlist** (`worklists/worklist_1_shortlist.csv`): 3588 of 3588 candidates judged, 643 feeds verified; by reason: robots_unavailable 1214, verified 643, no_feed_found 578, feed_unparseable 505, homepage_unreachable 451, feed_stale 104, robots_disallowed 37, feed_too_few_entries 28, feed_undated 26, error 1, crawl_delay_too_long 1
- **remainder** (`worklists/worklist_2_remainder.csv`): 18457 of 18457 candidates judged, 2753 feeds verified; by reason: robots_unavailable 6633, homepage_unreachable 3102, verified 2753, no_feed_found 2748, feed_unparseable 2117, feed_stale 565, robots_disallowed 225, feed_too_few_entries 219, feed_undated 93, crawl_delay_too_long 1, error 1

verified means: the feed was fetched and parsed in this run, had at least 3 entries with a title and a link, and its newest dated entry was within 120 days. Nothing here judges what an outlet is -- that is Stage B's question, run elsewhere.

## Stage B, both chunks (run in the repository session, 2026-09-11)

Triage is the only model-spending stage: 40 verified rows per batch on Haiku, two hand-known
canary rows mixed into every batch, closed enums and the shipped catalogue's own topic
vocabulary, and `triage_batches.py merge` re-validating every result file in plain code. A
batch that fails a canary, answers short, or returns a value outside an enum is marked
untrusted WHOLE and none of its rows merge.

- **shortlist**, 643 verified rows, 17 batches: 16 passed code re-validation first time; batch
  11 answered 35 of its 42 rows and passed on a re-run that named completeness as the hard
  requirement. **494 merged, 149 refused** (`triage_shortlist_*`).
- **remainder**, 2,753 verified rows, 69 batches, 2,891 rows including canaries: every batch
  answered in full on the first pass. Two (0026, 0060) returned a `kind` outside the closed
  list -- `corporate` and `tabloid`, where the enum has `trade-or-corporate` and where
  `tabloid` is a TOPIC, not a kind -- which the validator counts as an unanswered row, so both
  batches were untrusted whole and re-run once on the escalation model, as the runbook
  prescribes. **1,657 merged, 1,096 refused** (`triage_remainder_*`).

Canaries were read correctly in all 86 batches across both chunks.

Refusals are by TYPE, not by quality: the largest class is `academic` (57 + 549), then
`institution`, `broadcaster` and `other`. A refusal here is "not an outlet that publishes
reporting", never "a bad source".
