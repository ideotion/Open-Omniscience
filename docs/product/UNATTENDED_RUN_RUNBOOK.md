# Unattended run — leaving the app working while you are away

**Audience:** the operator, dedicating a machine to a multi-day run.
**Companion:** [`P0_VALIDATION_RUNBOOK.md`](P0_VALIDATION_RUNBOOK.md) (the acceptance run).

Written for the 2026-08-12 field ask: a slow PC, ~10 days, a 1M-article corpus imported
onto it, online and collecting, with **one button to press before leaving** and **one
log to copy back** at any point — finished or not.

---

## 0. What this closes, and what it does not

Be clear about the trade before you commit ten days to it.

| 0.3 gate row | Does this run close it? |
|---|---|
| **3** — diagnostics from the real corpus at actual release scale | **Yes** |
| **4** — a full import that re-checks all sources | **Yes**, and only if you do step 2 as a *committed* import — your 2026-08-12 P0 run was `committed=false`, so every row read as a duplicate and the admission gate was never exercised at scale |
| **7** — multi-day collector soak + cold-boot unlock | **Yes** — this is the only way to get it |
| **1** — source-management program field-confirmed | **Partly** — the lifecycle gets exercised at scale; the double-check is still yours |
| **2, 5, 6, 8** | **No** — audit, article clean-up execution, the page-size ruling, and browser verification are separate work |

### What it will *not* do: drain the discovery backlog

At the time of writing there are roughly **42,600 disabled** discovery candidates and
about **3,600 enabled** sources.

Every qualification batch judges its candidates through
`source_audit.per_source_metrics` → `source_quality.collect_article_stats`, which does a
`GROUP BY` over the **whole `keyword_mentions` table** plus a full `articles` scan. That
cost tracks **your corpus**, not the batch — so it is paid once per batch of ~20
candidates regardless of how few there are.

| | batches | at ~5 min/batch on a slow box |
|---|---|---|
| Enabled set (~3,600) | ~180 | ~15 hours |
| Full backlog (~66,000) | ~3,300 | ~11 days of *pure judging* |

Ten days will comfortably judge everything that actually collects. It will not clear the
backlog, and the release gate does not ask it to: those candidates are **disabled**, so
they are never fetched. They are a queue, not a blocker.

---

## 1. Before you leave — five steps

### 1. Put the corpus on the machine
Import the 1M-article database. This takes days on a slow box; let it finish before
going further. The import owns the machine while it runs (collection is paused for its
duration) — that is deliberate.

### 2. Make the import a **committed** one
This is the step that closes gate row 4. A preview (`committed=false`) reads your corpus
and never writes it, which is right for validation and wrong for this: every row comes
back a duplicate and the admission gate is never exercised.

### 3. Check the machine can breathe
Open **Settings → Diagnostics** and note free memory. The button in step 4 measures this
itself and will decline the backlog drain if there is not enough headroom — but knowing
the number tells you which outcome to expect.

Rough shape of the check: a qualification batch holds roughly **1 GB per million
articles** plus about **1 GB of working margin**. That is an *estimate of the scan*, not
a measurement of your machine, and the button reports it as one.

### 4. Press **Start unattended run**
Settings → Diagnostics → *Unattended run*. Optionally type a note for the log
(`10-day run, 1M corpus`). The button:

1. goes online — which starts continuous collection, per the ruled
   online-implies-collecting semantics; it is the same path as the airplane toggle, not
   a second way in;
2. measures memory against corpus size, then starts the bulk source-qualification drain
   **only if that measurement allows it**;
3. arms the expedition log.

It is idempotent. Pressing it twice keeps your original start time, because the window
that matters is the whole absence.

**If it declines to qualify**, it says so with the numbers. That is the design: an
out-of-memory kill on day two costs the entire ten days, while skipping the backlog
costs only the backlog.

### 5. Leave it
Do not stop the app. Do not put it in airplane mode — that is the one control that stops
collection.

---

## 2. While you are away — nothing

The log maintains itself. It is refreshed inside the scheduler's own idle maintenance,
right after the hourly snapshot it reads from, so it costs no poller of its own.

---

## 3. Getting the log back — at any point

Settings → Diagnostics → *Unattended run* → **Copy log**.

- It is a **plain file read** plus in-memory state. It never scans the corpus, so it is
  safe to press mid-run, on a slow machine, with jobs still running.
- It works when nothing has finished. Unfinished jobs are listed with their live state.
- It lands in the clipboard where the browser allows, and in a selectable box either way.
- It is small — a few tens of KB — because the events ring has a ceiling. Paste it whole.

What it contains: how long the run has been up; whether it is still collecting and still
online; free memory; every counter that has an hourly snapshot (articles, sources,
keywords, and the four qualification statuses) with its **delta over the run**; jobs that
are not idle, including failed ones; and the most recent notable events.

What it deliberately does not contain: any figure the recorder has not actually written.
A counter with no snapshot yet reports "not recorded yet" with the reason, never `0` —
"the recorder has not run" and "there are none" are different facts, and on a fresh run
the first is the common one.

---

## 4. On return

1. **Copy the log** and send it.
2. **Run the P0 validation** (see its own runbook) — now on a corpus that has been
   collecting for ten days. Do a **clean shutdown first** if you want the unlock number
   to be bankable: a clean WAL-mode close checkpoints and removes the `-wal`, and the
   report now names which case it measured.
3. **Run All diagnostics (.zip)** — that is gate row 3's artifact.
4. **Disarm** when you want the record closed. It does not stop collection; airplane
   mode is the control for that.

---

## 5. If something goes wrong while you are away

The run is built to degrade rather than stop:

- **Airplane mode** engages → collection stops, the drain pauses honestly and says so;
  the log keeps recording.
- **Memory pressure** → the memory guard pauses the drain between batches. It does not
  auto-resume; restart it on return.
- **Nothing left to judge** → the drain stops honestly after several batches that judge
  nothing, rather than spinning.
- **The app dies** → the clean-shutdown sentinel records an unclean end, and the log
  reports it on the next boot. The log itself survives: it is rewritten atomically in
  place and never grows without bound.

The one failure the button is designed to prevent is the expensive one: an
out-of-memory kill days in, which would end collection and waste the window. That is
why it measures before it starts the drain, and why it declines rather than gambles.
