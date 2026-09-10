# Autonomous session brief — verify the discovered candidates and grow the shipped catalogue (2026-09-10)

**Status:** READY TO RUN in an internet-connected session. Nothing in it has run against the
network yet: this sandbox reaches `pypi.org` (HTTP 200) and answers `000` for every publisher
host probed (`feeds.bbci.co.uk`, `www.lemonde.fr`, `theanguillian.com`), so the fetch stage was
built and tested with a fake fetcher only. **The first thing the executing session does is the
probe in §1; if it fails, it stops and says so.**
**Anchor:** the source-qualification plan (`docs/plans/2026-09-10_SOURCE_QUALIFICATION_THROUGHPUT.md`,
§10) and the maintainer's questions of 2026-09-10: *"can we use an internet connected session with
an attachment … to create a workflow of agents to check candidate sources and increase the current
list of 3600 sources? … think of token usage and maximize model choice and prompt quality to avoid
using most of my credit."*
**Reads with:** `_WORKING_MODE.md` (the session rules), `SOURCE_DIVERSIFICATION_BRIEF.md` (the
non-negotiables for a source entry, which this brief keeps verbatim), the 2026-09-10 ruling in
`docs/ledger/OPEN_QUEUE.md` (the curated catalogue is qualified at seed — which is why what this
brief adds to `configs/sources.yml` is collected from day one on every install).

## 0. The answer, and the design principle behind it

**Yes.** And the way to keep it cheap is to notice that checking a feed is not a judgement. It is
a fetch, a parse and three rules — and a model adds nothing to it but cost. So the pipeline is
**script-first**: a zero-token stage does everything mechanical for all 22,045 news candidates
(robots, homepage, feed discovery, feed validation, language of the headlines), and the model is
handed only the residue that needs judgement — *is this a journalism outlet, which topics* — in
batches of forty, on the cheapest model that can read a list, with canaries in every batch and
every answer re-validated in plain code before it can reach the catalogue.

The trap this avoids, with the arithmetic: one agent per candidate is ~22,000 agents, each
paying the injected `CLAUDE.md` (~14k tokens) before it reads a single row — roughly **450M
tokens** to produce, mostly, "this domain has no feed", which `feedparser` would have said for
free. The design below spends **zero** on that question and about **5M tokens, four fifths of
them on Haiku**, on the one that needs a reader.

Every candidate that comes out the far end has been **fetched and parsed in the run**, judged
journalism by a model whose batch passed both canaries, reviewed by the maintainer in the PR
diff, and appended to the curated catalogue by a splice that refuses anything it cannot vouch
for. Under the 2026-09-10 ruling those rows are then **qualified at seed** on every install —
which is what "increase the initial list" means in this app.

## 1. Prerequisites (do these in order; each is a hard stop)

1. **An environment whose network policy allows the candidate hosts.** The default sandbox
   policy does not (see the probe above). Create or pick an environment with unrestricted
   egress — see https://code.claude.com/docs/en/claude-code-on-the-web — and start the session
   there. **Probe before anything else, and report the numbers:**
   ```
   for h in pypi.org feeds.bbci.co.uk www.lemonde.fr theanguillian.com; do
     printf '%-22s ' "$h"; curl -s -o /dev/null -m 12 -w '%{http_code}\n' "https://$h/"; done
   ```
   Anything other than `200`/`3xx` on the publisher hosts means the session cannot do this work.
   Stop, write the four numbers into the PR body, and do not retry through another tool.
2. **The attachment.** A zip holding the instance's sources export
   (`open-omniscience-sources.csv`, the 85,690-row file the maintainer produced with
   `GET /api/sources/export`) — the shortlist is regenerated from it in step 4. Unzip it under
   `data/candidates/` (git-ignored: `data/` is the app's own data directory).
3. **The venv**, per `_WORKING_MODE.md` §6:
   `TMPDIR=$PWD/.tmp-pip python3.13 -m venv .venv && TMPDIR=$PWD/.tmp-pip .venv/bin/pip install -e ".[analysis,dev]"`.
   `feedparser`, `py3langid` and the fetcher's dependencies come with it.
4. **The worklist.** `scripts/analysis/complement_candidates.py --export data/candidates/open-omniscience-sources.csv --out-dir data/candidates/complement`
   writes `shortlist.csv` (the T1–T3 gap classes, 3,588 rows) and the report. Work the shortlist
   first, then the T4 remainder (`--per-country-cap 100000` writes it uncapped) — ordering, never
   exclusion.

## 2. The pipeline

### Stage A — feeds, zero tokens · `scripts/analysis/verify_candidate_feeds.py`

```
.venv/bin/python scripts/analysis/verify_candidate_feeds.py \
    --candidates data/candidates/complement/shortlist.csv \
    --out-dir data/candidates/feeds --workers 8 --limit 4000 --resume
```

Per candidate, through the app's own guarded fetcher (`make_fetcher`: robots.txt fail-closed,
honest bot UA, 2 s per-host politeness, size caps, the operator's proxy if protected mode is
configured): dedupe against every shipped catalogue (registrable domain + known aliases); one
homepage fetch; feed discovery from the page's own `<link rel="alternate">` then a short list of
conventional paths, **at most six feed fetches per host**; the diversification brief's three
rules (parses as RSS/Atom · ≥3 entries with title and link · newest dated entry within 120
days); language of the headlines via the repo's guarded detector (below its floors it says
unknown and the export's value is kept, with the basis recorded).

Outputs in `--out-dir`: `verified.jsonl` (every candidate, every field of evidence — the resume
cursor), `rejections.csv`, `verified_sources.yml` (**only** the rows that passed, in the
`configs/sources.yml` schema, `verified: true` with the run's date), `summary.json`.

Cost: **0 tokens**. Wall clock: ~5 s per host end to end at 8 workers ≈ 1,500 hosts/hour, so
the 3,588-row shortlist is ~2.5 h and the full 22,045 news rows ~15 h — hence `--limit` and
`--resume`: run it in chunks across sessions; a chunk that dies loses nothing already written.
`--workers 16` halves the wall clock; per-host politeness is unaffected (the fetcher enforces it
per host, the workers only spread across hosts). Do not raise it further: the point of the
bound is that nobody's server sees more than one polite request every two seconds.

### Stage B — judgement, the only model stage · `triage_batches.py` + the workflow

```
.venv/bin/python scripts/analysis/triage_batches.py prepare \
    --verified data/candidates/feeds/verified.jsonl --out-dir data/candidates/feeds/triage
```

writes `batch_NNNN.json` files of 40 feed-verified rows (domain, name, homepage title,
description, up to 8 recent headlines, country, language, the Wikidata type), `canaries.json`
(two hand-known rows with expected answers — The Guardian = journalism, the European Commission
= not — mixed into every batch, never at the edges) and `vocabulary.json` (the shipped
catalogue's own topical tags, ≥5 uses, minus ownership/lean/provenance: the model chooses from
this list and from nothing else).

Then run the Workflow tool with `scripts/analysis/triage_verified_feeds.workflow.js` and
`args = { batches: <the "batches" array from manifest.json>, canaries: ".../canaries.json",
vocabulary: ".../vocabulary.json", model: "haiku", escalate_model: "sonnet", effort: "low" }`.
Each agent reads its batch file itself, writes `batch_NNNN.result.json`, and returns a
four-field summary — **nothing large passes through the orchestrator's context**. A batch
whose agent reports a canary miss is re-run once on the escalation model; a batch that still
misses is left untrusted.

```
.venv/bin/python scripts/analysis/triage_batches.py merge \
    --verified data/candidates/feeds/verified.jsonl --triage-dir data/candidates/feeds/triage \
    --out data/candidates/feeds/verified_triaged.yml --today 2026-09-1X
```

re-validates every result file **in plain code** — every domain echoed exactly once, every
kind/confidence in its enum, every topic in the vocabulary, both canaries as expected — and
writes the entries for rows that are feed-verified AND journalism AND confidence high or
medium AND from a batch whose canaries passed. A batch that failed a canary is never merged,
whatever its other rows say; every rejection carries its reason in `triage_rejections.csv`.

**Model choice, and why.** Haiku 4.5 for the batches: a closed-set reading of evidence that is
in the prompt, with the answer forced through a JSON schema — the task small models do
reliably and the one the repo's own triage doctrine was written for. Sonnet 5 for the
orchestrating session and the escalations. **No Opus/Fable anywhere**: nothing here is a
design decision, and a stronger model reading the same forty rows gives the same answer at
several times the price.

**Prompt quality, the four things that make a cheap model safe here:** closed enums for every
field (a value outside them is rejected in code, never coerced); the evidence in the file and
"do not browse" (browsing is where an agent's budget disappears, and it makes the answer
unreviewable); canaries with expected values the model never sees; and echo-back — every input
domain must come back exactly once, so a dropped row is a failed batch rather than a silent gap.

**Token budget, worked example.** Suppose 40 % of the shortlist has a live feed → ~1,450
verified rows → **37 batches**. Each agent: ~14k injected `CLAUDE.md` + ~1k prompt + ~5k batch
file + ~3k output ≈ **23k tokens on Haiku**; 37 batches ≈ 0.9M. Escalations at 10 % ≈ 4 × 30k on
Sonnet. The orchestrating turn: ~50k. **Under 1.2M tokens for the shortlist; ~6M for all 22k
news rows at the same yield** — against ~450M for the naive design. The `CLAUDE.md` injection
is the dominant term, which is why the batch is 40 rows and not 5: halving the batch doubles
the bill for the same answers.

### Stage C — review and the splice · `scripts/merge_source_batch.py`

```
.venv/bin/python scripts/merge_source_batch.py --batch data/candidates/feeds/verified_triaged.yml          # dry run: the plan
.venv/bin/python scripts/merge_source_batch.py --batch data/candidates/feeds/verified_triaged.yml --apply  # appends to configs/sources.yml
.venv/bin/python -m pytest -q tests/test_source_taxonomy.py tests/test_catalog_domain_collisions.py tests/test_seed_sources.py tests/test_catalog_sources.py
```

The splice appends rendered entries to the **end** of `configs/sources.yml` as text — it never
re-serialises the file (the recorded never-round-trip-a-curated-file lesson) — and refuses an
entry without `name`/`domain`/`rss_url`/`verified: true`/`last_verified`, a domain already in any
shipped catalogue by registrable domain or alias (it would be shadowed and never registered —
the 475-entry loss the catalogue already carries), a duplicate within the batch, and a
row-provenance, country-name or language-code tag. Dry run by default; idempotent on `--apply`.

Then the PR: the `sources.yml` diff is append-only and is the review surface; the batch YAML,
`summary.json`, `triage_summary.json` and both rejection CSVs go under
`docs/research/sources/candidate_batches/<date>/`; `verified.jsonl` (megabytes) stays out of the
repository — attach it to the PR or keep it locally. The maintainer's review of that diff is the
curation act that makes the rows `via:curated`, and the 2026-09-10 ruling does the rest.

## 3. What NOT to do — the credit traps, named

- One agent per candidate, or per feed. Stage A exists so this never happens.
- Passing rows through the orchestrator (`args` holding 8,000 rows, or agents returning them).
  Files in, files out; the orchestrator sees counts.
- Letting the triage agents browse "to check". Browsing is unbounded spend and an unreviewable
  answer; the evidence is in the file, and a thin row is a `low` confidence row, not a search.
- Opus/Fable for classification, or `effort` above `low` on the batches.
- Unbounded feed probing (a site with no feed must cost a fixed handful of polite fetches).
- Re-running Stage A without `--resume`, or Stage B for batches whose result files exist.

## 4. Honesty rules carried, verbatim in spirit from the diversification brief

- **Never fabricate** a URL, a field, a language or a country: `verified: true` is a claim this
  run stakes by having fetched and parsed that feed; an unknown language or country is omitted.
- **robots.txt fail-closed** and 2 s per host: a refusal is a verdict (`robots_disallowed`),
  never worked around, never retried under another UA.
- **No scores, no ranks.** The gap classes order the work; the model's confidence gates what a
  human sees, never what the app collects; nothing here writes a `reliability_score`.
- **The model decides nothing alone.** Canaries, enums and echo-back in code; the maintainer's
  PR review; the qualification re-check on the six-month clock after the fact.
- **State the yield.** `summary.json` and `triage_summary.json` carry every reason count; the
  PR body quotes them — "N candidates, M feeds found, K journalism, J appended" — so the next
  run can be sized from a measurement instead of this brief's estimates.

## 5. Decisions the maintainer should take before or at the first merge

- **D1 — where the rows land.** Recommended, and what the tooling does: `configs/sources.yml`
  via the splice, after PR review — the rows become `via:curated` and, under the 2026-09-10
  ruling, qualified at seed. The alternative is a separate generated file with its own
  provenance (which would need a seeder entry and a decision on whether it counts as curated).
- **D2 — the acceptance bar.** Recommended: journalism AND confidence high or medium; `low`
  rows are listed with the model's note for a human pass, never merged unread.
- **D3 — the chunk and the target.** Recommended: the 3,588-row shortlist first (one session,
  ~3 h of Stage A wall clock), read the yield, then the T4 remainder in chunks of ~4,000. If 40 %
  of news rows have a live feed and 70 % of those read as journalism, the full run adds on the
  order of **6,000 sources** — a 2.7× catalogue. That is an estimate; Stage A's first chunk
  replaces it with a measurement.
- **D4 — institutions and religious organisations** (the other 59,923 discovered rows) stay
  out of this pipeline by type (plan R5). If the official-sources vertical wants gazettes or
  statistical offices from them, that is a different worklist with different rules.

## 6. Closeout (every session)

Rows in `docs/ledger/shipped.csv` for what shipped; the yield numbers in the PR body; any
ruling given in the turn into `docs/ledger/OPEN_QUEUE.md`; the gates of `_WORKING_MODE.md` §4
before push (the splice changes `configs/sources.yml`, so the catalogue tests above are the
ones that matter, plus `pytest -q` in full). A partial run is a good outcome — say how far it
got and where the cursor is.
