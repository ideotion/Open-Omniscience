# Stage A on the institutions worklist — 8-VM fleet run, 2026-09-11

The first run of worklist 3 (institutions, 37,079 rows), executed by the maintainer across
**eight VMs** with `run_stage_a.py --only institutions --shard i/8`.

## The sharding held

| | |
| --- | --- |
| union of all 8 shards | **37,079** distinct domains |
| sum of the 8 shards | **37,079** |
| overlapping pairs | **0** |

Every host was asked exactly once. The host-keyed split (`sha256(registrable_domain) % n`,
never `hash()` — which is salted per process and would have put the same host in two shards)
did what it was built to do, so eight machines cost a publisher no more requests than one.

## What was found

| shard | candidates | verified | robots_unavailable | feed probes |
| --- | --- | --- | --- | --- |
| 1 | 4,518 | 291 | 1,875 | 8,739 |
| 2 | 4,750 | 278 | 2,055 | 9,233 |
| 3 | 4,549 | 291 | 1,965 | 8,946 |
| 4 | 4,575 | 313 | 1,984 | 8,680 |
| 5 | 4,665 | 307 | 2,001 | 8,789 |
| 6 | 4,724 | 324 | 2,014 | 8,838 |
| 7 | 4,676 | 287 | 2,069 | 8,638 |
| 8 | 4,622 | 282 | 1,912 | 8,961 |
| **total** | **37,079** | **2,373** | **15,875** | **70,824** |

**2,373 verified feeds (6.4%)**, every one new to every shipped catalogue —
UNESCO national commissions, health agencies, environmental protection authorities,
competition authorities, ambulance services.

## Why a row was not verified

| reason | n | of 37,079 |
| --- | --- | --- |
| `robots_unavailable` | 15,875 | 42.8% |
| `no_feed_found` | 7,381 | 19.9% |
| `homepage_unreachable` | 7,357 | 19.8% |
| `feed_unparseable` | 3,139 | 8.5% |
| `feed_stale` | 453 | 1.2% |
| `robots_disallowed` | 255 | 0.7% |
| `feed_too_few_entries` | 195 | 0.5% |
| `feed_undated` | 44 | 0.1% |
| `host_timeout` | 3 | 0.0% |
| `crawl_delay_too_long` | 2 | 0.0% |
| `error` | 2 | 0.0% |

## The finding: 62 : 1

`robots_unavailable` **15,875** against `robots_disallowed`
**255** — a **62:1**
ratio, measured on the live network across eight machines.

The earlier 22,045-row run gave 30:1 from a sandbox that answers `000` to every publisher, so
that figure was reasoning from the SHAPE of the measurement. This one is not: it is eight real
hosts on real networks, and it points the same way, harder. An explicit `Disallow` is a
publisher decision and it is **rare** (0.7%). "We could not read
robots.txt" is not a publisher decision at all, and it is 43%
of the population.

That is why the 2026-09-11 ruling — *"never drop a refused row — keep them deferred"* — is the
correct one, and why these rows come back through `worklist_5_retry.csv` rather than being
counted as refusals.

## What comes next

**23,237 rows are deferred**, not rejected, and are owed another look.
`scripts/analysis/build_retry_worklist.py` rebuilds that list from these runs at any time — it
is derived, so it is not committed here. The re-run uses the cause attribution that shipped on
2026-09-11, so the flat `robots_unavailable` label above will split into `robots_refused` /
`robots_server_error` / `robots_unreachable` and the 62:1 will finally say WHICH.

The 2,373 verified rows go to Stage B triage.
