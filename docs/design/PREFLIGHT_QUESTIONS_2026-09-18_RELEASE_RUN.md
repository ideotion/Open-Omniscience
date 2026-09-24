# Pre-flight questions — the 0.4 release run and the last 0.4 sessions (2026-09-18)

**What this is.** On 2026-09-18 the maintainer asked, after prompts 0–16 of the 2026-09-15 train had run:
*"Check everything out and let me know what I need to perform before executing prompt 17 … If you have any
questions, ask them now before I launch these sessions with your updates."* The audit is in the PR that carries
this file (the 0.4 release-run button, `RELEASE_0.4_GATE.md` §3 of the same date). Every question below is one
the audit could not answer from the tree, the ledger or a sensible default — each was grepped against
`docs/ledger/RULINGS_INDEX.md` first (protocol rule (6)); the ones already asked in
`RULINGS_CONFIRMATION_2026-09-15_REGISTER_ROUND.md` (`RC01`–`RC17`) are NOT re-asked, only pointed at where a
pre-flight step depends on them. Nothing here is decided by this session.

## §0 — How to answer, and how the answers are processed

- Write a letter after `ANSWER PFnn:` (a note in your own words after it is welcome and is recorded verbatim;
  where the note contradicts the letter, **the note is the ruling**). Answering in chat with the same
  `PFnn = letter` form is equivalent; the receiving session copies the letters here.
- **Blank on a ⛔ question stays PENDING** — never defaulted. **Blank on any other question takes the stated
  default as an ASSUMPTION**, reversible at any time, and the session that acts on it labels it as one.
- Processing (the same §0.2 protocol as the 2026-09-12 sheet): the letters are parsed mechanically by the first
  session that receives the file back (Prompt 17a's first task, or Prompt 17's if 17a never runs); this file
  stays in place as the primary record; ONE `OPEN_QUEUE.md` entry indexes the round; `RULINGS_INDEX.md` gets a
  row per `PFnn`; the gate files, briefs and prompts the answers touch are amended in the same PR; no ruling is
  invented; contradictions with an existing ruling are listed, never resolved by the recording session.

---

## §1 — The run itself (operational; each changes the checklist, none changes the code)

#### PF01 · The 0.3 row-5 quarantine pass — tick the opt-in, and on which instance?
Ruling `A1` deferred the Tier-A quarantine run with no date; `RC01` is blank, so its ASSUMPTION (b) keeps the
version at `0.3.0` until row 5 runs. The button carries row 5 as an opt-in checkbox that defaults OFF, because a
button may not decide an operator step. Ticked, it runs `RELEASE_0.3_GATE.md` §7.1's four commands in order
(`write=True`, prose gate off) and reads the mode back before trusting the tally — and it CHANGES that corpus's
quarantine stamps.
**What it costs, and where it runs (amended 2026-09-24, ruling `FD01`, from the six-machine field round in
`docs/audit/16_FIELD_DIAGNOSTICS_SIX_MACHINES_2026-09-24.md`):** row 5 is a quarantine pass over every article
FOLLOWED BY A WHOLE-CORPUS KEYWORD RE-INDEX with the orphan prune — seven hours on a 289k-article laptop, and 50 to
61 hours on three 4 GB VMs, where it had not finished and their soaks never started. It now runs LAST, after the
soak, the collect and the bundle, with collection and the Wikipedia lane paused for its duration and put back
after it; the report is written before it starts, its progress is published and sampled, a job whose counter does
not move for two hours is paused (resumable, never discarded), and a restart inside it keeps the completed soak.
- **a** — tick it on the release-scale instance only: row 5's tally and composition come out in that run's
  report (`phase_results.row5_quarantine`, board row G), row G's precondition is met on one corpus, the ~1M corpus is untouched.
- **b** — tick it on both instances: the same, on both corpora (twice the write, twice the evidence).
- **c** — leave it unticked on both: row 5 stays deferred, row G keeps waiting, the version stays `0.3.0`.
Default if blank: **c** (the status quo). *Not asked here:* whether the flip may proceed WITHOUT row 5 on the
existing `v0.3.0` pre-release — that is `RC01`, answerable at its own `ANSWER RC01:` line.
ANSWER PF01:

#### PF02 · The two instances and the destination drive(s)
The run's disk gate is measured per run at preflight: the backup alone refuses without ~1.2× that instance's
corpus free on the destination; the fresh-install restore degrades to `not-measurable-here` without ~3.2×.
- **a** — two separate app instances (own data dir, own port, ideally own machine), EACH with its own
  destination drive holding ≥ 3.2× that instance's corpus free.
- **b** — two instances on one machine sharing ONE destination drive: allowed, but the second press's preflight
  sees only what the first left, and two backups compete for the drive; stagger the presses so the first run's
  backup phase has finished (its status says so) before the second is pressed.
- **c** — the ~1M instance is the ONLY instance you will run: press *Run as the ~1M-article instance* there and
  skip the first button — the `million` profile runs everything the other does and additionally makes row C's
  bundle the required artifact.
Default if blank: **a**.
ANSWER PF02:

#### PF03 · The soak length to enter (`rr-hours`, default 72)
- **a** — 72: the bar exactly; board row B's `reaches_bar` reads true at 72 h and the run collects at once.
- **b** — 96 (or any number above 72): the same bar with a day's margin; *"more than 72 hours"* in your own
  words reads as this.
Default if blank: **b** (enter 96). Either way *Collect now* ends the window early and the report says how long
it really was; a process restart mid-window is reported INTERRUPTED and the run is RESUMED with the *Resume run*
button (the backup and the restore are not redone; the soak starts a new stretch, because the bar is continuous)
— the Chronology box above the run shows every stretch and how much of the 72 h the current one still needs.
ANSWER PF03:

#### PF04 · How the artifacts reach the Prompt 17 session
The session runs in a fresh clone and cannot read your disk. The report carries the destination path, the app
version, the article count, cores and RAM figures — never the passphrase, never a hostname or an IP; read it once
before committing it.
- **a** — commit them: the run's final report (`data/diagnostics/release-run/oo-release-run-<profile>-<run_id>-final.json`
  and the `.txt` download), the P0 report it names (`data/diagnostics/oo-p0-validation-*.json`), and the
  all-diagnostics ZIP it names (`oo-all-diagnostics-*.zip`, or — if it is over ~50 MB — its `unzip -l` listing
  plus the coverage member) into `docs/audit/release-run-<date>-<profile>/` on a branch pushed to `origin`;
  name the branch in Prompt 17's first line.
- **b** — paste the `.txt` rendering into the session's first message: the session then works from prose; the
  JSON evidence and the bundle are not re-openable and row C's coverage check cannot be re-run by the session.
Default if blank: **a**.
ANSWER PF04:

#### PF05 · A pre-migration backup for row K (`rr-legacy`, optional)
Row K's proof wants the alpha-3 restore normaliser exercised on a backup written BEFORE the format bump
(PR #1146, `oo-backup-2 → oo-backup-3`). The run restores the path you give it in the same fresh-install way as
the new backup and reads the same integrity and duplicate-key scan off it.
- **a** — one exists: enter its path (a `.oobak.ooenc` file or a dated folder from before 2026-09-16).
- **b** — none exists: row K's real-restore proof is read off the NEW backup only, the pre-bump → new path stays
  `not-measurable-here` in the report, and row K's §3 line says so.
Default if blank: **b**.
ANSWER PF05:

---

## §2 — Rulings the last sessions asked for and no default can safely take

#### PF06 · Row R and Q803's default
Row R shipped the Equal Earth seam, Natural Earth 50m and the CONTESTED both-claims layer; Q803's ruled DEFAULT
(OSM's border convention) waits on the 0.5 OSM artifacts. The exit clause as written says rows G–V close before
the tag.
- **a** — row R CLOSES in 0.4 on the three shipped parts; Q803's default moves to the 0.5 board beside the OSM
  artifacts it waits on, with a row that says so.
- **b** — row R stays OPEN and the 0.4 exit waits for the 0.5 OSM artifacts.
Default if blank: **a**, labelled ASSUMPTION in Prompt 17's PR — the tag is your own act and can wait on **b**.
ANSWER PF06:

#### PF07 · Where the fix for the three broken ride-along opt-outs lands (row H)
Disclosed 2026-09-16, not fixed (live-reproduced): the calendars and law ride-alongs gate on settings fields that
do not exist (`auto_import_calendars`, `auto_track_law` — the `getattr` default wins, a constant `True` at
runtime), and the hazard feeds' `auto_track_signals` IS a field but `PUT /api/scheduler/config` does not declare
it, so the opt-out is accepted with a 200 and discarded — a consent control that reports success it did not
deliver. The consent hover already says so per lane.
- **a** — Prompt 17a (the remaining 0.4 session work), its own small PR on row H, fixed before the tag.
- **b** — 0.5: recorded on the 0.5 board; 0.4 ships with the disclosure in the consent hover.
Default if blank: **a** (a consent surface that discards a choice is the informed-consent non-negotiable's own
subject).
ANSWER PF07:

#### PF08 · The collection-speed knob's unit — four strings and invariant #4's wording
`collect_target_kbps` is kilobits per second (the code and the Settings slider agree: `500 kbps`); the top-bar
knob's hover, two toasts and `index.html`'s comment say `500 KiB/s`, an 8.192× overstatement. CLAUDE.md
invariant #4 carries the same wrong unit, so the correction is a constitution edit.
- **a** — the four strings become `kbit/s` (what the code measures), re-keyed ×12 (never a new key beside the
  old one); invariant #4 amended to "target 500 kbit/s"; the stored setting and the governor unchanged.
- **b** — everything becomes KiB/s and the governor's arithmetic changes to bytes: a behaviour change to the
  one rate authority — the stored `collect_target_kbps` value would mean something else on every install.
- **c** — leave as is.
Default if blank: **a**.
ANSWER PF08:

#### PF09 · The reader page and the i18n engine
`reader.js` carries 22 permanently-English strings; the reader page never loaded the engine, by a recorded
2026-06 choice ("the SPA chrome is the i18n target"). The three i18n gates exclude it by design.
- **a** — bind the engine to the reader page and key the 22 strings ×12 (Prompt 17a); the recorded choice is
  retired in the queue.
- **b** — keep the reader page English-only; the recorded choice stands.
Default if blank: **b** (the status quo is a recorded choice, not an omission).
ANSWER PF09:

#### PF10 · In-map controls at phone width — which shape, on every ooMap surface?
Measured 2026-09-16 at 390×844: the control groups cover 79 % of the world map before the worldview picker and
112 % with it (the groups overlap). Three shapes were listed and none chosen, because it changes the
"controls inside the map" convention itself.
- **a** — a disclosure: below 600 px the groups collapse to ONE in-map button that opens them (the convention
  kept; the map visible).
- **b** — one non-wrapping row that scrolls horizontally (changes controls no slice touched).
- **c** — the groups move under the map at narrow widths (the convention gives way at phone width).
- **d** — leave as is for 0.4 and record it on the 0.5 UI-shell slice `S05-09`.
Default if blank: **d** (a convention change wants your letter; nothing regresses by waiting).
ANSWER PF10:

#### PF11 ⛔ · Protocol rule (1)'s achievability — `LESSONS.md` has outgrown its own amendment
Rule (1) was amended 2026-09-07 because reading one 1.3 MB file "in full" could only be obeyed by skimming;
the pair CLAUDE.md + LESSONS.md then measured 573,850 bytes. `LESSONS.md` alone is now 985,788 bytes and the
pair measures 1,043,989 (`wc -c`, 2026-09-18) — past 1 MB again, the same failure mode one file over. A session may not amend the protocol.
- **a** — `LESSONS.md` gets the same line ratchet as CLAUDE.md, and entries older than the current cycle
  compress to verdict + pointer into `SHIPPED_LOG.md` (the verbatim archive), in one PR you read before merging.
- **b** — rule (1) is amended the other way: `LESSONS.md` is consulted like the queue (by grep, for the work at
  hand) and only CLAUDE.md stays mandatory-in-full.
- **c** — leave rule (1) as written.
⛔ A blank stays PENDING: the sessions keep reading both files in full, and the file keeps growing.
ANSWER PF11:

#### PF12 · The Japanese segmenter for row N's S8
Q506 🔒 = (b) names `jieba` (zh) and `sudachipy` (ja); the tree's `[segmentation]` extra carries `janome` (ja)
today, used for keyword extraction only.
- **a** — `sudachipy` + its core dictionary, as Q506 says (a compiled wheel plus a large dictionary package, in
  the extra, registered in `configs/external_artifacts.yml`; `janome` retired from the extra).
- **b** — keep `janome` (pure Python, dictionary bundled, already installed) on the FTS path too, and record
  Q506's `sudachipy` clause as superseded by this letter.
Default if blank: **a** (Q506 is a locked ruling; the session follows it unless you write **b**).
ANSWER PF12:

#### PF13 · The twelve maintainer click-throughs (rows H, I, J, K, L, M, N, O, P, S, T, U)
Q1128 = (a): Chromium in the sandbox + your own click-through = verified. Every one of those rows now has its
Chromium record under `docs/audit/` and is "awaiting the maintainer's own pass".
- **a** — you do each pass and write one line per row (one file, `docs/audit/MAINTAINER_CLICKTHROUGH_0.4.md`:
  date, surface, what was clicked, what was wrong); Prompt 17 closes each row on that line plus its Chromium
  record.
- **b** — for 0.4 only, your pass covers a SAMPLE you name here (e.g. rows I, J, P, S) and the rest close on
  their Chromium records; the release notes say which rows had the human pass.
Default if blank: **a** (the ruled bar as it stands).
ANSWER PF13:

#### PF14 · `guarded_session` and the connect-time SSRF guard — before or beside the soak?
Disclosed 2026-09-17: `ssrf_guard.connect_scope` has one caller (`EthicalFetcher`), so every `guarded_session`
consumer (the Wikipedia lane's stream, dumps, ORES, DuckDuckGo) gets the kill switch, the airplane socket guard
and the honest UA — not the connect-time SSRF validation. The lane runner is now live, so the stream runs over
that path for the whole soak.
- **a** — press the buttons now; a Prompt 17a slice makes `GuardedSession` enter `connect_scope`, with its own
  live reproduction, in parallel (the soak's evidence is memory and uptime; the tagged tree differs from the
  soaked one by every PR merged after the run in any case).
- **b** — fix first: that slice merges BEFORE the buttons are pressed (one session's delay; the soak then runs
  the guarded path).
Default if blank: **a**.
ANSWER PF14:

---

## §2b — Answered elsewhere, needed before the sessions launch (pointers, not questions)

- `RC01` (the version flip without row 5), `RC10` ⛔ (`dumps.wikimedia.org` on the session allowlist — row V),
  `RC13` (the religious dates session — assumption (b) is what Prompt 17b executes; write `+ eclipses` or
  `− eclipses` after the letter or the eclipse canon stays unstated), `RC02` ⛔, `RC03` ⛔, `RC12`: all at
  their own `ANSWER RCnn:` lines in `RULINGS_CONFIRMATION_2026-09-15_REGISTER_ROUND.md`.
- `Q925` ⛔ (the law adapter order and the first managed dataset) and `Q1113` ⛔ (the embassy platforms): at
  their lines in the 2026-09-12 sheet; each blocks only the part of its row the exit clause names.
