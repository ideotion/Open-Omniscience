# Candidate kit — runbook for the internet-connected session (RUN.md)

**You are holding a self-contained copy of the candidate-source pipeline.** It was built by
`scripts/analysis/build_candidate_kit.py` from the Open Omniscience repository and carries
everything the run needs: the scripts, the repository modules they import, the shipped
catalogues they dedupe against, the worklists, a self-check and this runbook. `KIT_MANIFEST.json`
names the commit, the date and the file hashes.

**This session has no repository clone, no GitHub access and no database, and needs none.**
Never try to clone or fetch the repository, never touch GitHub, never open a pull request, never
push. The result of the run is a zip you hand back; the catalogue itself is changed later, in a
repository-connected session, by the maintainer.

Amends `docs/design/AUTONOMOUS_SESSION_BRIEF_2026-09-10_CANDIDATE_FEED_VERIFICATION.md` (the
design and the credit arithmetic), whose §1 assumed the run session had the repository: it does
not, and the maintainer ruled the same day that the run is autonomous and detached from GitHub.

## 0. Layout

```
RUN.md                       this file
KIT_MANIFEST.json            commit, date, counts, sha256 of every file
requirements.txt             the exact third-party packages the scripts import
selfcheck.py                 offline proof the kit works here (imports, tests, a dry run)
run_stage_a.py               Stage A on your OWN machine, one command (§8) -- when the cloud
                             session's connection is limited
worklists/worklist_1_shortlist.csv    3,588 rows: the T1–T3 gap classes, capped 100 per country
worklists/worklist_2_remainder.csv    every other discovered news row, T3 overflow first, then T4
worklists/WORKLISTS.md                how both were derived from the export
export/                      the maintainer's sources export, verbatim (provenance only)
scripts/analysis/verify_candidate_feeds.py      Stage A  (zero tokens)
scripts/analysis/triage_batches.py              Stage B  prepare / merge
scripts/analysis/triage_verified_feeds.workflow.js   Stage B  the workflow script
scripts/merge_source_batch.py                   Stage C  dry-run plan only, here
scripts/analysis/complement_candidates.py       how the worklists were classed (reference)
configs/                     the shipped catalogues (dedupe + the topic vocabulary)
src/                         the repository modules the scripts import (fetcher, domains, …)
tests/                       the two fake-fetcher test files the self-check runs
```

Everything the run writes goes under `runs/`. Nothing else in the kit is modified.

## 1. Rules for the running agent

- **Autonomous.** Never ask the user a question; every decision is made in this file. When
  something blocks you, write what happened in `runs/RUN_LOG.md`, package what exists (§6),
  deliver it, and stop. A partial run delivered is a good outcome; a question is not.
- **Detached.** No GitHub, no clone, no PR, no push, no fetching of anything but the candidate
  hosts and PyPI. Do not edit the scripts, `configs/` or `src/`.
- **Frugal.** The only model spend is Stage B, in 40-row batches on Haiku with a single Sonnet
  escalation per suspect batch. No agent per candidate. No agent browses. Never read
  `verified.jsonl` or a batch file into your own context — use `wc -l`, `summary.json`,
  `triage_summary.json`. The orchestrating session's own model should be Sonnet; nothing here
  is a design decision.
- **Patient.** Stage A runs for hours. Run each chunk as a background command and wait for its
  completion notification; never busy-poll, never sleep in a loop. If the harness cuts a run
  off, re-run the same command: `--resume` continues from the JSONL cursor and loses nothing.
- **Polite.** `--workers 12` at most (concurrency is across hosts; each host still sees one
  request every 2 s), robots.txt fail-closed, the honest bot user agent. Do not change any of it.
- **Honest.** Report the counts the scripts print, with their reasons. Never restate an estimate
  from this file as a result.

## 2. Setup — each step is a hard stop

1. **Unzip and enter.** `python3 -m zipfile -e oo-candidate-kit-<date>.zip . && cd oo-candidate-kit-<date>`
   (`unzip -q` does the same where it exists). Every path below is relative to this folder;
   pass ABSOLUTE paths to the model stage.
2. **Egress probe.** Publisher hosts must be reachable, not only PyPI:
   ```
   for h in pypi.org feeds.bbci.co.uk www.lemonde.fr theanguillian.com; do
     printf '%-22s ' "$h"; curl -s -o /dev/null -m 12 -w '%{http_code}\n' "https://$h/"; done
   ```
   (Without `curl`: `python3 -c 'import urllib.request as u,sys; print(u.urlopen(sys.argv[1], timeout=12).status)' https://<host>/`
   per host, a refused connection printing its error.) Anything other than `200`/`3xx` on the
   three publisher hosts means this environment cannot do the work. Write the four numbers in
   `runs/RUN_LOG.md`, tell the user, stop. Do not retry through another tool or proxy.
3. **Python and the venv.** Prefer `python3.13`, then `python3.12` (the pinned numpy needs 3.12
   or newer; 3.11 cannot install the requirements — measured). Then:
   ```
   mkdir -p .tmp-pip && TMPDIR=$PWD/.tmp-pip python3.13 -m venv .venv
   TMPDIR=$PWD/.tmp-pip .venv/bin/pip install -r requirements.txt
   ```
   One retry on a network error; a second failure is a hard stop.
4. **The data directory and the self-check.** Every command in this runbook is run with
   `OO_DATA_DIR="$PWD/data"` exported (the fetcher persists its robots.txt cache there, so later
   chunks reuse it):
   ```
   export OO_DATA_DIR="$PWD/data"
   .venv/bin/python selfcheck.py
   ```
   It imports every module the scripts use, runs the two fake-fetcher test files, builds the real
   fetcher and proves it refuses an unresolvable host cleanly, and runs prepare / merge / the
   splice plan on a synthetic fixture. It prints `SELFCHECK OK` and exits 0, or names what failed.
   A failure is a hard stop: report its output.
5. **Start the log.** `runs/RUN_LOG.md` opens with the date, the Python version, the four probe
   numbers, and the `id` from `KIT_MANIFEST.json`. Append to it at every step below.

## 3. Stage A — feed verification, zero tokens

Two worklists, in this order: `worklist_1_shortlist.csv` (3,588 rows, the gap classes T1–T3),
then `worklist_2_remainder.csv` (the remaining discovered news rows, ~18,500, T3 overflow first).
Work each in chunks so a cut-off costs little; every chunk is the SAME command, resumed:

```
mkdir -p runs/w1
nohup .venv/bin/python scripts/analysis/verify_candidate_feeds.py \
    --candidates worklists/worklist_1_shortlist.csv --out-dir runs/w1 \
    --workers 12 --limit 3000 --resume >> runs/w1/stageA.log 2>&1
```

Run it as a background command; when it completes, read the JSON summary at the end of
`stageA.log` and `wc -l runs/w1/verified.jsonl`. If the line count is below the worklist's row
count, run the same command again (it skips every domain already judged). Repeat until the
count reaches the worklist size; then do the same for worklist 2 into `runs/w2`.

What it does per candidate: dedupe against every shipped catalogue (registrable domain plus
aliases); one homepage fetch through the app's own ethical fetcher (robots.txt fail-closed,
honest bot UA, 2 s per host, size caps); feed discovery from the page's own
`<link rel="alternate">` then a short list of conventional paths, at most six feed fetches per
host; the three rules (parses as RSS/Atom · at least 3 entries with a title and a link · newest
dated entry within 120 days); the language of the headlines through the guarded detector.

Outputs per worklist: `verified.jsonl` (every candidate, every field of evidence — the resume
cursor), `rejections.csv` (domain, reason), `verified_sources.yml` (only the rows that passed, in
the catalogue schema), `summary.json` (counts by reason). Log the `by_reason` block of each
summary in `RUN_LOG.md` as it comes.

Wall clock, an estimate to be replaced by the first chunk's measurement: a feedless host costs
about seven polite requests two seconds apart, so roughly 15–20 s per host per worker; at 12
workers about 2,000–2,500 hosts an hour — worklist 1 in under two hours, worklist 2 in eight to
nine. Cost in model tokens: zero.

## 4. Stage B — triage, the only model stage

For each worklist directory once its Stage A is complete:

```
.venv/bin/python scripts/analysis/triage_batches.py prepare \
    --verified runs/w1/verified.jsonl --out-dir "$PWD/runs/w1/triage"
```

writes `batch_NNNN.json` files of 40 feed-verified rows (domain, name, homepage title,
description, up to 8 recent headlines, country, language, the Wikidata type), `canaries.json`
(two hand-known rows with expected answers, mixed into every batch, never at the edges),
`vocabulary.json` (the shipped catalogue's own topical tags — the model chooses from this list
and nothing else) and `manifest.json` (the absolute batch paths).

**Then the model fan-out, one of two ways.**

*Preferred — the Workflow tool.* Paste `scripts/analysis/triage_verified_feeds.workflow.js` as
the script and pass, as `args`, the `batches` array from `manifest.json` plus the absolute paths
of `canaries.json` and `vocabulary.json`, `model: "haiku"`, `escalate_model: "sonnet"`,
`effort: "low"`. Each agent reads its batch file, writes `batch_NNNN.result.json` beside it and
returns a four-field summary; nothing large passes through the orchestrator. A batch whose
agent reports a canary miss is re-run once on the escalation model.

*Fallback — the Agent tool.* If the Workflow tool is unavailable, launch one subagent per batch
file with `model: "haiku"`, at most eight at a time, giving each the text of the `prompt()`
function in the workflow file with the three paths filled in, verbatim. Collect the summaries;
re-run on `model: "sonnet"` any batch whose summary says `canary_ok: false`, whose `answered`
is short, or whose result file is missing. Never classify a batch in your own context.

If neither tool exists, stop after Stage A: package and deliver (§6), and say that Stage B did
not run and why.

Then, in plain code:

```
.venv/bin/python scripts/analysis/triage_batches.py merge \
    --verified runs/w1/verified.jsonl --triage-dir "$PWD/runs/w1/triage" \
    --out runs/w1/verified_triaged.yml --today $(date -u +%F)
```

re-validates every result file — every domain echoed exactly once, every kind and confidence in
its enum, every topic in the vocabulary, both canaries as expected — and writes the entries for
rows that are feed-verified AND journalism AND confidence high or medium AND from a batch whose
canaries passed. A batch that failed a canary is never merged, whatever its other rows say.
`triage_rejections.csv` carries every rejection with its reason; `triage_summary.json` names the
untrusted batches. Log both.

Budget, as a check on yourself: without a repository there is no `CLAUDE.md` injected into the
subagents, so a batch is roughly 1k of prompt, 5k of batch file and 3k of answer — about 10k
Haiku tokens. At a 40 % feed yield the shortlist is ~37 batches (~0.4M) and the remainder ~185
(~1.9M), plus a handful of Sonnet escalations. If your running total is a multiple of that, stop
and write down why before continuing.

## 5. Stage C preview — the splice plan, dry run only

```
.venv/bin/python scripts/merge_source_batch.py --batch runs/w1/verified_triaged.yml
```

prints what the repository-side splice would accept and refuse (missing fields, a domain already
in a shipped catalogue by alias, an in-batch duplicate, a provenance/country/language tag). It
writes nothing without `--apply`, and `--apply` is never used here: the catalogue in this kit is
a copy. Log the `accepted` / `refused` line. The real append happens in a repository session.

## 6. Deliver — at each milestone and on any hard stop

Milestones: worklist 1 through §5; worklist 2 through §5; and immediately on a hard stop with
whatever exists. Build the archive from the folder root:

```
.venv/bin/python -m zipfile -c "deliverable_$(date -u +%F).zip" runs KIT_MANIFEST.json
```

It contains, per worklist: `verified.jsonl`, `summary.json`, `rejections.csv`,
`verified_sources.yml`, `triage/` (batches, results, manifest, canaries, vocabulary),
`verified_triaged.yml`, `triage_summary.json`, `triage_rejections.csv`; and `RUN_LOG.md`.

Send the archive to the user as a file (the tool that attaches a file to the conversation). If no
such tool exists, print its absolute path and size and say so. In the same message give the
yield table, one line per worklist, from the scripts' own numbers:

```
worklist · candidates · feeds verified · rejected by reason (top 4) · journalism (high/medium) ·
low-confidence (listed, not merged) · untrusted batches · splice plan accepted/refused
```

## 7. What happens next (the maintainer, not this session)

The deliverable is attached to a repository-connected session, which reviews
`verified_triaged.yml`, runs `scripts/merge_source_batch.py --apply` against the real
`configs/sources.yml`, runs the catalogue tests, and opens the pull request. Under the
2026-09-10 ruling the appended rows are qualified at seed on every install.

## 8. The other way: Stage A on your own machine, Stage B and C in a repository session

When the cloud session's connection is limited (the maintainer's case on 2026-09-10: "its real
connection is extremely limited"), split the work by what each stage NEEDS. Stage A needs the
publishers' hosts and no model. Stage B needs a model and no publisher. Stage C needs the
repository. So:

1. **On any machine with a real connection and Python 3.12 or newer**, from the unzipped kit
   folder:
   ```
   python3 run_stage_a.py                 # Windows: py -3.13 run_stage_a.py
   ```
   It creates `.venv`, installs the pins once, probes the four hosts, runs `selfcheck.py`, then
   runs Stage A on worklist 1 and worklist 2 with the same script and the same rules as §3
   (robots fail-closed, one polite request per host every 2 s, at most six feed probes per
   host), and writes `stage_a_results_<date>.zip` beside itself. **Ctrl-C stops cleanly and the
   same command resumes** — every row already judged is kept. Options: `--only shortlist` for
   worklist 1 alone (about two hours), `--limit 300` for a first taste, `--workers 8` on a small
   machine. Zero model tokens throughout. **While it runs**, from a second terminal,
   `python3 run_stage_a.py --status` reports progress from the run's own cursor (rows judged,
   the reasons so far, this session's measured rate and the remaining time at that rate) and
   writes `stage_a_snapshot_<date>T<time>.zip` without touching the run — attach that snapshot to
   a repository session to have Stage B and C run on what exists so far.
2. **Attach that zip to a repository-connected Claude session** and ask for Stage B and C. The
   triage runs there on Haiku from the zip's `verified.jsonl` (no publisher access needed), the
   merge re-validates every answer in code, the splice appends the accepted rows to
   `configs/sources.yml`, the catalogue tests run, and the pull request is opened for review.

The cloud-session path (§2–§6) stays valid for an environment whose network policy allows the
publishers; this one needs no such environment.
