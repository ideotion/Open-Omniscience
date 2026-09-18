# The Wikipedia lane end to end on the recorded fixture — 2026-09-18

The proof that can be produced **here**. The operator's ≥ 72 h run against the live
service is theirs and is documented in
[`docs/product/WIKI_LANE_SOAK_RUNBOOK.md`](../../product/WIKI_LANE_SOAK_RUNBOOK.md);
this is the same pipeline, the same drain and the same counters, driven against
`tests/fixtures/wiki/recentchange_stream.sse` with the **airplane socket guard armed**.

`run.py` is the harness, kept beside the record so the run can be repeated rather than
believed:

```
OO_DB_PLAINTEXT=1 OO_NO_SCHEDULER=1 OO_DATA_DIR=<tmp> .venv/bin/python run.py --out .
```

## What it measured

| | |
|---|---|
| **name resolutions** | **0** — counted at `socket.getaddrinfo`, because a DNS lookup is itself egress. Not "no requests were made": no name was even looked up |
| events decoded | 20, of which 15 kept — 1 malformed, 1 foreign edition, 1 outside namespace 0, 1 redirect, each counted under its own name |
| pages admitted | **2**, both `corpus_mention`, from a HOT set naming `Fixture Alpha` and `Fixture Beta` |
| changes recorded | **15** — every kept event, including the ones for pages the lane does not follow |
| baselines captured | 2 (first sighting of each admitted page) |
| gaps | 0 — nothing was missed, and the block says so rather than being absent |
| rows / day | 15 on the run's day, `0` on the seven before it — real zeros inside a measured window |
| bytes / day | **741,594** between two file-size samples two hours apart |
| budget | 20 GB total, **358,256 bytes** held, not exhausted |

## Why the growth figure exists at all in a run this short

A rate needs **two** readings of the same quantity. The harness stamps a second size
sample two hours on rather than sleeping for two hours — the arithmetic is the point,
and a script that slept to prove it would be proving patience. With one sample the
block reports `measured: false` **with a reason**, never a rate of zero; that path is
covered in `tests/test_wiki_counters.py`.

## What this does NOT show

Anything about Wikimedia's live behaviour. Every Wikimedia host answers `000` from this
sandbox (probed 2026-09-17, `api.github.com` answering `200` as the control), so the
scale figures in the answer sheet — edits per day, EventStreams retention, the scoring
endpoint — remain **FROM MEMORY** until the operator's run replaces them. The fixture
is a recorded stream with deliberate negative space in it; it proves the pipeline
handles what it was recorded handling, and nothing about volume.

The moved page (`Fixture Alpha` → `Fixture Alpha (renamed)`) is in the fixture on
purpose: it is what caught the seen-map keeping only the newest title, which dropped a
plainly-mentioned page out of the HOT tier with nothing saying why.
