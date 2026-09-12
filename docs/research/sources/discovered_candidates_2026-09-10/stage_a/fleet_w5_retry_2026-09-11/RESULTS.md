# Stage A, second pass — the 23,237 deferred rows, re-asked

Run 2026-09-11 by the maintainer across 8 VMs, `worklist_5_retry.csv`, host-keyed shards.
Population: every row the first fleet pass DEFERRED, carried forward by
`scripts/analysis/build_retry_worklist.py` with its identity fields and its earlier reason
as context, and judged **fresh** against a fresh fetch.

**Integrity of the run, checked before anything was read into it:** 8 shards, 23,237 rows,
union = sum = 23,237, **zero overlapping pairs**, and the set of domains judged is exactly
the set the worklist named — no drift in either direction. So every figure below has the
whole population behind it.

| | first pass (w3) | second pass (w5 retry) |
| --- | --- | --- |
| candidates | 37,079 | 23,237 |
| verified | 2,373 (6.40%) | **267 (1.15%)** |
| feed probes | 70,824 | 4,768 |

The combined verified corpus is **2,640 distinct institutions**, and the two sets do not
intersect at all — by construction, and checked rather than assumed.

---

## The deliverable is the transition matrix, not the 267

A deferral records that we learned nothing, so the only way to find out what a deferral was
worth is to ask again and compare. That is what this run bought.

| first pass said | n | → verified | → host is gone | → still stuck at robots | → got an answer |
| --- | ---: | ---: | ---: | ---: | ---: |
| `robots_unavailable` | 15,875 | 223 (1.40%) | 3,237 (20.4%) | 11,809 (74.4%) | 829 (5.2%) |
| `homepage_unreachable` | 7,357 | 44 (0.60%) | 6,495 (88.3%) | 653 (8.9%) | 209 (2.8%) |
| `host_timeout` | 3 | 0 | 1 | 0 | 0 |
| `crawl_delay_too_long` | 2 | 0 | 1 | 0 | 0 |

**The columns do not sum**: "verified" is a subset of "got an answer", and three of the five
rows in the two small cohorts land in neither column (2 timed out again, 1 still declared a
`Crawl-delay` longer than the probe budget).
Full matrix in `AGGREGATE.json`. Three things fall out of it.

### 1. A fifth of the robots bucket was never a robots fact at all

3,237 of the 15,875 rows recorded as `robots_unavailable` came back as
`homepage_unreachable`: the site is not there. The robots fetch failed because **the host is
gone**, and the first pass could not say so because it stopped at the first gate.

This matters for how the earlier 62:1 figure is quoted. "15,875 unavailable against 255
Disallow" is a correct count of what the first pass recorded, and it is **not** a count of
live publishers we are declining to read. At least 20.4% of that numerator is dead hosts.
The ethical conclusion is untouched — fail-closed on an unreadable robots.txt is right
whether the host is dead or shy — but the *cost* of the rule is smaller than the raw ratio
implies, and the honest way to say it is with that subtraction shown.

### 2. Retrying a robots failure does not surface hidden refusals

Of the 15,875, exactly **829 got a readable robots.txt on the second ask, and 29 of those
said Disallow.** So the population we were failing closed on is not concealing a mass of
publishers who had said no: it is overwhelmingly hosts that do not answer.

The 29 are worth one caveat rather than a shrug. Among rows that got an answer at all, the
second pass saw 3.07% Disallow (32 of 1,041) against the first pass's 1.84% (255 of 13,842)
— the hosts that are flaky about serving robots.txt refuse at roughly double the background
rate. n is 32. That is a hint, not a finding, and it is recorded here so nobody has to
re-derive it.

### 3. A dead host stays dead, and that is the measurement a third pass needs

88.3% of the `homepage_unreachable` rows were still unreachable, days later, from eight
different network vantages. 0.60% recovered.

So the decay is measured, not guessed: a first ask verified 6.40%, a second ask of what it
deferred verified 1.15%, and within that, re-asking an unreachable homepage returned 0.60%.
**No third-pass yield is quoted here.** A third pass would run against rows that failed
*twice*, which is a more strongly selected population than either figure above describes,
and extrapolating a curve from two points — one of which is a different population — is the
mistake the two-judge range already made in this project once. Whoever runs it should run it
and see.

### And 771 rows stopped being questions

The verified 267 are not the only thing the pass produced. It also **settled 771 rows into
rejections** — 474 with no feed, 200 unparseable, 42 stale, 32 an explicit `Disallow`, 16 too
few entries, 6 undated, 1 error — and a rejection, unlike a deferral, is finished. Those 32
Disallows in particular are now honoured permanently instead of being re-asked on every future
pass, which is the distinction `build_retry_worklist.py` reads `DEFERRED_REASONS` to preserve.

Final standing of the 23,237: **267 verified · 771 rejected · 22,199 still deferred.**

---

## What the retry recovered, and why it justifies the whole path

The 267 are not a long tail of marginal sites. Among them:

**bmi.bund.de — the German Federal Ministry of the Interior.** Also Brazil's Ministry of
Transport, Bhutan's Ministry of Foreign Affairs, Ministry of Home Affairs and National
Statistics Bureau, three Cameroonian ministries, two Gambian ministries, Georgia's Ministry
of Education and Science, Paraguay's Ministry of Women, Russia's Federal Agency for Mineral
Resources, the Philippine Space Agency, the Ethiopian National Dialogue Commission, Burundi's
National Assembly, the Victorian Auditor-General's Office. **53 countries** are represented,
which is an exact count; 37 of the 267 match a national- or state-body NAME PATTERN, which is
not — one of the 37 is a provincial schools division, so read that figure as a sweep of the
names rather than a census of the bodies.

Every one of them had been excluded by a robots.txt fetch that failed once. There is no
signal anywhere in the catalogue that distinguishes "this publisher declined" from "we
could not reach the file on one Tuesday", and until this run there was no mechanism that
would ever ask again. That is the argument for the retry path, made concrete.

### The composition is skewed, and the skew is real rather than a bug

**116 of the 267 (43%) are Czech municipalities** — `Obec …` sites publishing their
*úřední deska* (the legally mandated official notice board) as Atom. They are distinct
institutions on distinct domains; the concentration comes from a Czech municipal CMS that
exposes `?action=atom` and from WordPress `/feed/`. 42 of them sit on the same
`/uredni-deska?action=atom` path — a distinctive enough shape that it is almost certainly one
vendor's product, which would mean **one supplier's outage takes out dozens of sources at
once**. Worth knowing before these are spliced; not a reason to exclude them.

Incidentally, a Czech úřední deska is the cleanest possible instance of the observable the
open queue's B2 proposes in place of the `primary_source` judgement: *does this feed publish
dated official instruments?* Here the answer is yes by statute.

**26 of the 267 (9.7%) carry a bare Wikidata Q-id as their NAME** (`Q133293483`, …) — the
export never resolved a label. Same class as the identity-field defects already in the
queue: name, country and `wikidata_type` are evidence, not fact.

**Zero of the 267 collide with the 6,400 hosts already in the catalogue.**

**Three of the 267 are flagged by the scan below and must not be spliced unread:**
`brasil.embajada.gob.ve` and `pn-ende.go.id` at the confident tier, and
`bangladeshembassy.es` at the weak one — where reading it settles the matter, because a
Bangladeshi embassy does not publish Spanish casino reviews. That is the intended division of
labour: the weak tier put it in front of a reader, and the reader decided.

---

## The incidental finding, which is larger than the run that produced it

A Stage A row is verified when its feed parses and is fresh. **A hijacked domain satisfies
both beautifully** — an affiliate content farm publishes several times a day, so it is
*fresher* than the ministry it replaced. The two-judge run found a dozen of these by reading
rows one at a time. Scanning the titles Stage A had already fetched finds the same class for
nothing: no tokens, no further network traffic, and no new fetch path.

`scripts/analysis/scan_content_integrity.py`, over all **6,036 verified rows** from the three
runs to date, flags **46** — 0.76%:

| tier | n | what it means |
| --- | ---: | --- |
| `restricted_namespace` | 10 | gambling copy on a namespace no private party can register |
| `placeholder` | 7 | entry titles that are CMS defaults — `test`, `Sample Page`, lorem ipsum |
| `lexicon` | 29 | the same words anywhere else — **a reading list, roughly 0.6 precise** |

### The ten are one story, mostly

Eight of the ten `restricted_namespace` flags are subdomains of **`embajada.gob.ve`** — the
Venezuelan foreign ministry's embassy platform. The corpus holds 13 of those missions and
Stage A verified all 13. Reading their titles: three are genuinely the embassy (Australia,
China, South Africa); eight serve gambling affiliate copy; four have entries titled literally
`test`; two of those four do both. That is **ten of thirteen Venezuelan diplomatic missions
compromised or unconfigured**, on a restricted government namespace — one platform, not ten
independent lapses. The two-judge run had found exactly one of them, by reading.

The remaining two are **`pn-ende.go.id`**, an Indonesian district court, and
**`usf.gov.jm`**, a Jamaican statutory fund. The judges separately found `pn-nunukan.go.id`
— a second Indonesian district court, same `pn-` prefix, same restricted `.go.id`.

Restricted namespaces are the reason this tier is trustworthy: nobody but a government can
*hold* one, so spam under it is a compromise of a live delegation, never a lapsed
registration someone bought.

### Why it flags and never rejects, stated as the thing it cost

The `lexicon` tier's 29 include a national **gambling regulator** publishing a tender for
casino licences, Italian football reporting where *poker* means four goals in a match, a
historic Pamplona social club called the *Nuevo Casino Principal*, and two English sentences
using "betting on" idiomatically. **Three of the 29 — `redgol.cl`, `elivebrescia.tv`,
`radiorukungiri.co.ug` — are already in `configs/sources.yml` as the legitimate news outlets
they are.** A rule that acted on this signal would have deleted them.

So the scanner emits tiers a reader works through, the tier names carry their own confidence,
and `tests/test_content_integrity_scan.py` pins those three catalogued outlets as a permanent
negative control: whatever the rule grows into, it may put them on a reading list and must
never reach a conclusion about them.

**Nothing in the shipped catalogue is a confirmed takeover.** All three catalogue hits are
false positives of the weak tier, checked by reading.

### What it does not do

Recall is unmeasured and certainly partial: it misses `gartzambia.org`, `sedlecko.cz` and
`ordnancerta.com` — all genuine takeovers the judges found — because they sit on ordinary
namespaces, and it would miss any takeover whose copy avoids the lexicon entirely. It is a
cheap first sweep over evidence already in hand, not a detector. Open queue **C6** asked for a
detection rule; this is a partial answer to it and is filed as one.

---

## Files

| file | what it is |
| --- | --- |
| `AGGREGATE.json` | the run roll-up, the disjointness proof, the full transition matrix |
| `shardNof8_summary.json` | each VM's own summary, verbatim |
| `verified_267.csv` | the 267, with the reason each was deferred the first time |
| `content_integrity_flags.csv` | the scanner output below, over all 6,036 verified rows |

The raw `verified.jsonl` (1.8 MB per shard) is **not** committed: it regenerates from the
worklist, and the rows that matter are extracted above.
