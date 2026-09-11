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

## The 11,404 rows that were NOT JUDGED (and how to finish them)

`stage_a_not_judged.csv` carries every row the completed run left without a verdict — kept,
never rejected. They are not failures of the candidate; they are places the run could not
reach an answer.

| reason | n | what it means |
| --- | ---: | --- |
| `robots_unavailable` | 7,847 | robots.txt could not be read. **Three different facts** until 2026-09-11 — see below. |
| `homepage_unreachable` | 3,553 | the homepage did not answer on either scheme |
| `crawl_delay_too_long` | 2 | the host's declared `Crawl-delay` exceeds the probe budget |
| `error` | 2 | an unexpected exception inside one host, recorded rather than ending the run |

**The `robots_unavailable` bucket was un-attributable, and now is not.** It never contained
"this host has no robots.txt" — a 404/410 means everything is allowed and proceeds normally.
It contained a **refusal** (401/403), a **broken host** (5xx), and a **network failure**, under
one label. From 2026-09-11 the fetcher carries the cause and Stage A records
`robots_refused` / `robots_server_error` / `robots_unreachable` instead.

Why it matters which: over the completed run these were **7,847 against 262 explicitly
disallowed — thirty to one**, at a **uniform 25–53 %** across the fourteen highest-volume
countries on every continent, and the bucket includes hosts that certainly do serve a
robots.txt. A host-level policy signal varies by country; a pathway-level one is uniform. On a
Tor-routed run most of this is very likely the exit's reputation rather than the publisher's
wish — but *likely* is not *measured*, which is exactly what the split now makes possible.

**To finish them**, with a kit built on or after 2026-09-11, against the run directories the
original produced:

```
python3 run_stage_a.py --only shortlist  --retry robots_unavailable
python3 run_stage_a.py --only remainder  --retry robots_unavailable
```

`--retry` re-judges the rows whose **last** verdict carries that reason; the old lines stay in
the cursor and the new ones outrank them, so nothing is lost and the run is resumable as usual.
The legacy `robots_unavailable` key is kept in `REASONS` for exactly this — nothing emits it any
more, but it still selects the rows a pre-split run wrote. Add `homepage_unreachable` to the
same flag to retry those too.

Fail-closed is unchanged throughout: every one of these still refuses the fetch. The cause
exists so the catalogue can stop spending an absence like a verdict.

---

## The two fleet runs (8 VMs each), and where their results live

| run | worklist | candidates | verified | artifacts |
| --- | --- | ---: | ---: | --- |
| first pass | `w3` institutions | 37,079 | 2,373 (6.40%) | [`fleet_w3_2026-09-11/`](fleet_w3_2026-09-11/) |
| second pass | `w5` retry of the deferrals | 23,237 | 267 (1.15%) | [`fleet_w5_retry_2026-09-11/`](fleet_w5_retry_2026-09-11/) |

The second pass is the one that turned the first pass's 62:1 robots figure into something
that can be read: **a fifth of the `robots_unavailable` bucket was dead hosts**, not shy
publishers, and only 29 of the 15,875 turned out to be an actual `Disallow` once the file
could be read. It also recovered `bmi.bund.de` and 36 other national and state bodies across
53 countries, each of which had been excluded by a single robots.txt fetch that failed once.
Its `RESULTS.md` carries the transition matrix, and a content-integrity scan over all 6,036
verified rows to date.
