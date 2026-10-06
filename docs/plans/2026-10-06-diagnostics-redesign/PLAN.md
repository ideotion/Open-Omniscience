# Plan: one Diagnostics button, one zip (R119)

From the export thread, 2026-10-06. **Go given by the coordinator at 04:17 with eight conditions; this version applies them** (the list is in section 0a). **Revised 08:40 for the user's answers to questions 28 to 30 (R122, R123, R124; section 0b): the Light checkbox goes, "All keywords" stays as a small link, and the button runs a Quick build by default with a Thorough toggle. The revision needs the coordinator's go before any of it is built.** No code is written for the button yet. Inputs: the user's 03:27 message, the five needs files in `needs/` (crash read, keyword, WAL, Wikipedia, RC), FINDINGS.md section 8, `open_items.csv`, the 10 bundles I extracted (8 machines) and the crash read's tables for all 17. Every figure below was measured from those bundles unless it says "budget" or "estimate". The member-by-member table is `members.csv` beside this file.

## 0. In short

1. **One button, "Diagnostics".** Of the 45 buttons and links in Settings, Advanced, Diagnostics, seven go, two become small text links ("again" and, by R123, "All keywords"), "All diagnostics" is renamed, and the Light checkbox is replaced by a Quick/Thorough toggle (R122, R124; section 3). The buttons that do work (runs, maintenance, curation) stay where they are.
2. **One zip.** Today's largest bundle is 632 KB zipped (Lenovo; 629 KB measured by the crash read) against the new 4 MB. The redundancy removal alone takes it to 560 KB, and the new data I budget in section 6 brings it to about 0.75 MB. So the 4 MB constant is a ceiling that the splitter only meets for an unusually large archive, and the common case is one file with no manifest zip and no readme.
3. **76 members become 55**: 45 stay (five of them extended or trimmed), two are merge targets (`storage`, `contention`), and eight are new: a run history, a vitals history, self-test verdicts, database damage, transfers, boots, the keyword pipeline, and the Wikipedia lane history that plan already put on #1314. The machine record is not a member: it is a `machine` block in the manifest header, which is written even when a member is declined (RC: the reading goes in the header once).
4. **No owner pushes to `bundle.py` again.** A slot table I add once names every owner member and its producer function; a producer that does not exist yet simply shows as "not in this build". Plan's `wiki-lane-history.json` on #1314 is the one exception the coordinator accepted; it stays as built.
5. **The user answered questions 28 to 30** (relayed 08:31; section 0b): R122 = 28a (the Light checkbox is removed; R119 amends R28), R123 = 29b ("All keywords" stays as a small text link, the other two keyword buttons go), R124 = 30 (a Quick build by default, plus a toggle for a Thorough one).
6. **#1315 merges after its two should-fix, not as it was.** Both are fixed at 068f24513 (section 12).
7. **Order:** #1315, then item 2 with the read release (built), then the recorders as members of their own (the instruments the 72 h run needs), then the button. If item 2 is held up in review, the recorders go first. The recorders matter first for the run, because a recorder shipped late has no history for the hours before it, and the run's zips on 10-09 must carry them even if the button slips (section 9).

## 0a. The coordinator's eight conditions (04:17) and where each landed

| # | Condition | Where |
|---|---|---|
| 1 | Fold in rc.md: the manifest header carries the stamped tier reading, total RAM now with the tier it would give now, RAM available now, the versions and `allocator_setting()` once; `release-run.json` keeps the last 10 runs' restore phase summaries; `boots.json` takes RC's fields | section 6 (the `machine` block in the manifest header replaces `machine.json`; the other two rows were already in) |
| 2 | No control goes before the zip carries what it gave; the two keyword buttons that go (R123) go only in the PR that makes the digest ride the zip wherever they worked; the digest's RAM gate is measured and fixed before PR D or in it | section 3 (the rule and the per-control check), section 9 |
| 3 | PR C's recorders ride the zip on their own (members added in C, moved into the slot table in D); if B is held up, C goes first | sections 7 and 9 |
| 4 | The minutes before a kill are recorded once: agree with WAL which of vitals' 5-minute flush and WAL's 15-second snapshot carries that tail; the other points to it | section 6a |
| 5 | One name for the lane member: `wiki-lane-history.json` | `members.csv` soak-window row corrected |
| 6 | #1315 merges after its two should-fix, not as it is | section 12 |
| 7 | Before D says ready: walk the new panel in Chromium, open every drop-down, pick an option and confirm it takes effect, and save a one-file and a five-file hand-over | section 9 |
| 8 | The code says what the Quick build's 10-minute scan budget protects: the collection pause and the user's wait (R124 keeps a budget for Quick; Thorough has none) | section 8 |

Moving the misfiled actions (Enrich, Discover, clean-up, fold, re-index) out of the panel is a separate proposal, after D. The coordinator dropped Q-C's option c (the user does not want to press twice); R124 answers it with one button and a toggle, so nobody presses twice.

## 0b. The user's answers to 28 to 30 (relayed 08:31) and what they change

| Ruling | Answer | What it changes in this plan |
|---|---|---|
| **R122** | 28a: remove the Light checkbox. R119 amends R28. | The checkbox row of section 3 is a removal. The app still declines a member the machine cannot carry (R27) and the manifest says which; `declined-light` stays a recognised outcome so old bundles read. The route keeps `profile=light` for the maintainers, unreachable from the panel. |
| **R123** | 29b: keep "All keywords" as a small text link, remove the other two keyword buttons. | "Keyword log" and "Last keyword files again" go; "All keywords" stays under the button as a text link, its route and file names unchanged. This is the layer that lets Quick skip the digest on a large corpus without leaving anyone without it (section 8). Condition 2 still decides the PR in which the two buttons go: the one whose test shows the digest member carries what they gave; where it does not, the button stays and the table says so. |
| **R124** | 30: a quick diagnostics by default, plus a toggle for a thorough one, "so a crash leaves us as much as possible". | One button, two builds. **Quick** (default): records first, about 3 minutes, then at most about 10 minutes of scans, the scans that did not fit named in the manifest. **Thorough**: every scan. The toggle takes the Light checkbox's place and starts off each time the panel opens (never stored). The zip says which mode ran (section 8). |

**Go (coordinator, 08:42):** for section 0b and the revised sections 2, 3, 8, 9, 10, 11 and 13, with my three recommendations: (1) Quick runs shortest first, with the 30 s floor and partial cuts allowed; (2) Thorough keeps the 300 s deadline per scan; (3) R122 to R124 go into `RULINGS_INDEX.md` and `OPEN_QUEUE.md` in D. The order stays as in section 9.

**How long Thorough can pause collection (measured, section 2 and 8):** the records run before the window, so the pause is the scans alone. **Four builds ran the full profile: 1,645 to 2,661 s (27 to 44 minutes).** The other eleven comparable builds ran the Light profile, which skipped benchmark, source-audit and the keyword digest (the three scans that cost 118 to 307 s each on a large corpus); adding what those three cost where they ran gives **2,330 to 2,832 s for them, so 27 to 47 minutes over the 15 builds, median 42**. Today's whole build is 9 to 48 minutes, so **Thorough pauses collection about as long as today's full build, less the three minutes of records**; and a machine that was using Light (11 of the 15) will see a much longer Thorough than it has seen, because Light no longer exists to skip those three. The ceiling is **16 scans x 300 s = 80 minutes**: no scan can hold the window past its own 300 s deadline, which Thorough keeps. Quick's pause is at most 600 s (10 minutes) by construction.

**Parts stay under 4 MB each, in both modes.** The mode changes what goes into the archive, not how it is cut: `UPLOAD_PART_BYTES = 4_000_000` (decimal, so every part is also under 4 MiB), one file when the archive fits, the numbered scheme above it. The test cuts an incompressible 9 MB archive into three parts of fewer than 4,000,000 bytes each and keeps a 3,999,999-byte archive as one file, on both modes' member sets. Measured: Thorough is today's full archive (262 to 629 KB zipped on the 17 builds) plus the budgeted new data (about 0.75 MB), so one file; Quick is smaller.

## 1. What the user asked, clause by clause

| Clause | Where it lands |
|---|---|
| "a single diagnostics button that downloads a zip with everything" | section 3 (one button), section 5 (one file when it fits) |
| "(or multiple zips, so long as they weigh less than 4 MB each)" | one constant, `UPLOAD_PART_BYTES = 4_000_000` (decimal, so under 4 MiB as well); the numbered scheme of R115 stays for an archive above it |
| "Include the session forensics into that zip" | already a member; it goes in once (the JSON; the duplicate txt and its stand-alone download link go) and it gains the earlier unclean ends (D+E) |
| "Make that all diagnostics button into a simpler diagnostics ... remove all redundancies" | section 3 (controls) and section 4 (members): 13 members fold into one verdict file, 7 merge, 3 drop, 8 appear only when they hold something |
| "review and update the diagnostics tools ... gathering more data to understand what's not working ... every aspect of the app" | section 6: each gap in FINDINGS 8 and each needs file, with its member, owner and bound |
| the R111 limit | the app gathers everything itself and asks the user nothing; no new network call (the transport is read as a SETTING, no address lookup) |

## 2. What exists today (measured)

- **The panel has 45 buttons and links and five checkboxes**; about 20 of them open or download a report. Eight explanatory paragraphs at its end describe buttons that no longer exist (the debug bundle, the performance report, the scaling benchmark, "all gathered keywords", the keyword self-test, the engine report, the date-extraction log, the network log): no code in `src/static` calls their routes.
- **76 members (78 files with the manifest and the journal)**; 17 bundles read: 2.0 to 4.7 MB raw, 262 to 629 KB zipped. 6.8 per cent of the raw bytes are exact duplicates (3.2 of 47.0 MB over 17 bundles); `debug-bundle.json` embeds eight members that also stand alone (408 KB raw of its 1.32 MB on Lenovo).
- **A build takes 9 to 48 minutes** (543 to 2,888 s over the 10 manifests; sum of the members' median times 30 minutes) and holds the machine exclusive, so collection is paused for all of it. Eight members reached their 300 s deadline in at least one build (bulletin-weekly 8 of 10, performance 6 of 10, leads-quality 4 of 10, benchmark 4 of 10 ended partial; article-length, source-audit, keyword-engine and keyword-growth were skipped at the deadline in 1 to 3). **Records and scans** (`members.csv` columns `kind` and `median_s`, from the 17 manifests): 16 members are scans, the whole-corpus reads (performance, bulletin-weekly, leads-quality, keyword-engine, keyword-growth, article-length, lemma-preview, date-extraction, criteria-calibration, card-audit, non-article-scan, merge-diag, country-code-duplicates, and three that cost under a second on a small corpus but 118 to 307 s on the five large ones: benchmark, source-audit, keyword-log-digest); the other 60 are records. The records took **163 to 225 s (median 188 s)** in every build, collection untouched if they run first; the scans took 380 to 2,661 s. Two builds are not comparable (Asus 10-03 and 10-04: 14 and 12 members in error, 4 declined by the Light profile). **Eleven of the other 15 ran the Light profile**, which declined benchmark, source-audit and the digest, so their scans took 1,564 to 2,208 s without those three; **the four builds that ran everything took 1,645 to 2,661 s (27 to 44 min)**, and with the three added at their measured cost (300, 300, 167 s) the 15 come to 27 to 47 min, median 42 min. (An earlier version of this sentence classified by median alone and so counted benchmark, source-audit and the digest as records, because eleven builds declined them and their median is 0.)
- **The only per-tick memory series is five minutes long.** `collect_perf` in the debug bundle holds 200 ticks spanning 5 to 6 minutes (330 KB raw on Lenovo, 25 per cent of that member), and the file it comes from keeps 5,000 lines, about two hours, only while a pass runs. No file holds the shape of a memory climb over a day.
- **What the zip carries that the new data will not**: the error-log tail has article web addresses in its lines, and `date-extraction.json` has 60 article titles with excerpts of up to 1,200 characters. The new members below hold counts, times, sizes, settings and reasons only. The new button's hover text (12 locales) must say what the zip contains, because today's does not.

## 3. The panel after

**The rule (condition 2): no control goes before the zip carries what it gave.** Each removal below lands in the PR that has a test showing the replacing member carries the same data; if it does not, that control stays and the table says so. Concretely: `session-forensics.json` must hold every field the `.txt` held before the `.txt` and its download go; the two bulletin and file-lock buttons go only once the members they match carry the same route payload; the two keyword buttons that go (R123) go only in the PR that makes the digest ride the zip wherever they worked, which first needs the digest's RAM gate measured (section 9, step 4); "Source and article quality" goes only if its member (`source-audit` with the article-quality scans) carries what the `.zip` held, which I check in D and leave the button where it differs.

| Control | Disposition | Why |
|---|---|---|
| All diagnostics (1 MB files) | **becomes "Diagnostics"** | the one button |
| Light bundle checkbox | **removed (R122 = 28a)**, replaced by the Thorough toggle | R28 amended; the app already declines a member by itself under R27 and says so in the manifest |
| **Thorough toggle** (new, `#diag-thorough`) | **added (R124)**: off by default and off again each time the panel opens, never stored (no setting, no localStorage); sends `mode=thorough` to the existing build route | Quick is the default build; the toggle asks for every scan. Its hover text (12 locales, the shared bubble) says what each costs: Quick, about 3 minutes plus at most 10 with collection paused, scans that did not fit are named in the file; Thorough, every scan, collection paused for the scans, 27 to 47 minutes measured on a large corpus (42 typical) |
| All diagnostics, again | **becomes a text link** under the button, shown only when a built archive exists, with its time and size | the first-run report shows why "again" has to exist; it should not be a second button |
| Session forensics (view) | stays | a view of the previous session; no download |
| Session forensics, Download (.txt) | removed | the zip carries it (asked for) |
| Keyword log, Last keyword files again | **removed (R123 = 29b)** in the PR where the digest member is shown to carry what they gave | R111 says nobody is asked for per-keyword exports; the routes stay |
| All keywords | **stays, as a small text link under the button** (R123) | Quick may skip the digest on a large corpus (it is a scan); the link is the way to get it whole, so no one is left without it |
| Bulletin language & render (.json), Windows file locks (.json) | removed | both are members already |
| Source & article quality (.zip), TEMP | removed | its own label says delete after the analyst used it; route stays |
| Rollup benchmark (.json) | stays | a heavy operator run that is not a member and has no equivalent |
| FDR self-test, Flood, Bury, Lunar-correlation | stay | analytic features, not reports about the install; not mine to move |
| Fold report, Search re-index report | stay | the report of an action beside its button |
| Keyword-growth curve, lemmatization preview, IR gold set, IR eval | stay | instruments |
| Unattended run, P0 validation, Chronology, 0.4 release run | stay | runs and views; their reports are members |
| Enrich, Discover, clean-up, fold, re-index buttons | stay | actions, not diagnostics; misfiled here, moving them is a separate change |
| The eight stale hint paragraphs | removed | they describe nothing |
| AI diagnostics section | untouched | needs a live model; `ai.json` carries its summary |

## 4. The zip: members

Full table: `members.csv`. In words (76 today, 55 after):

- **45 stay**: 39 as they are (among them all the data-quality scans: date extraction, lemma preview, card audit, leads quality, source audit and the rest), four extended (`session-forensics`, `chronology`, `soak-window`, `release-run`), `debug-bundle` trimmed, and `keyword-log-digest` unchanged until its gate is measured.
- **13 fold into `selftests.json`** (12 self-tests and `recursive-loop.json`): a mechanism proof is a function of the build and was byte-identical on every instance read, so the file keeps one verdict per test (full output only for a failure). That keeps the one thing a self-test tells you, whether the code works on this machine.
- **7 merge**: four storage members into `storage.json`, `write-gate` and `stall-forensics` into `contention.json` (both WAL's asks, with the section names kept inside), `run-journal-raw` into `run-journal`.
- **3 drop**: `power-profile` and `elections-floor` (identical on all 17; the build id says which), `session-forensics.txt`.
- **8 appear only when they hold something** (the AI job stubs, 75 to 216 bytes on every machine that never ran the job): the manifest names the empty ones once.
- **`debug-bundle.json` is trimmed**: the eight embedded copies go, and `collect_perf` is cut to its newest 20 ticks (the hourly history moves to `vitals.json`).
- **Placeholders stay** (`.declined`, `.skipped-deadline`, `.error`, 60 bytes each): they cost nothing and keep a skipped member impossible to mistake for a complete one.
- `manifest.json` gains an `area` per member and a `replaces` list on a merged member, so a reader of an old bundle can map names.

**Size on the biggest instance seen (Lenovo, 1.83 M articles):**

| Stage | Raw | Zipped |
|---|---|---|
| Today | 4.69 MB | 632 KB |
| Removals only (duplicates, constants, stubs, selftests, txt, readme) | 3.86 MB | 560 KB |
| Plus the budgets below (an estimate, not a measurement) | about 4.9 MB | about 0.75 MB |
| Plus the keyword digest on a machine that lacked it | +1.1 MB | +155 to 181 KB |

Removing the redundancy saves 11 per cent zipped (18 to 29 per cent raw). It matters for a reader's time more than for size; the size problem was R115's cap, not the content.

**Budgets (raw JSON, enforced by the slot wrapper: the newest records stay, the cut is named in the member):** vitals 260 KB (measured raw on the test's fixture, 25 loggers: 140 KB for the full retention, 189 KB with the three previous sessions' tails, 246 KB with 58-character logger names; 200 KB, and the first figure of 160 KB, would have cut the 48 hours or the tails; 260 KB is 6 per cent above that fixture and is not a maximum: a logger name has no length ceiling, and a member that passes it drops the oldest log hours first and says so; the fixture is `test_the_heaviest_member_fits_its_budget_with_three_previous_tails_and_cuts_nothing`), machine 20 KB, runs 40 KB, selftests 4 KB, database-damage 40 KB, transfers 40 KB, boots 30 KB, storage 120 KB, contention 200 KB, keyword-pipeline 60 KB, session-forensics +60 KB (D), release-run 150 KB (87 KB at the largest seen), wiki-lane-history 300 KB (plan measures it on a fixture: 12 editions by 168 hours). The listed budgets add to 1,324 KB raw: that is the most the new members can add together, not what a zip carries (the largest release-run seen is 87 KB of its 150 KB, and a young install has little in most of them), so the plan's "about 1.2 MB raw" is a figure for a heavy machine and not their sum; about 200 KB zipped at five-fold (the measured ratio is 6 to 8), and the PR bodies carry the measured totals.

**What each number protects.** 4,000,000 bytes: the user's limit. About 1.1 MB typical: the largest upload known to have arrived is 1.14 MB and uploads above about 1.2 MB failed in September, so the budgets keep the common case under the size that is known to work, and the first zip above it is a rare, informative event. A member's budget: one history, which grows with the number of loggers, cannot take the room the other members' newest records need in a typical zip; it is not what keeps a part under 4,000,000 bytes, and at 260 KB raw the vitals member is 6 per cent of one part (the splitter still guarantees every file is within the cap whatever the content).

## 5. Delivery

- **One file when the archive fits.** `GET /all-job/volumes` answers with the finished archive itself (named `oo-diagnostics-<stamp>.zip`): no split, no manifest zip, no `volumes-readme.json`. That saves the split (seconds to a minute), the doubled disk footprint the splitter documents, and two of the three files the user handles. An archive above the cap goes through the numbered scheme exactly as R115 built it.
- **One constant.** `UPLOAD_PART_BYTES` moves from 1,000,000 to 4,000,000 in `src/analytics/upload_parts.py`, which the keyword exports and the splitter share (so a keyword set that stays reachable by route is also in 4 MB parts). If a larger upload fails, it is that one line.
- **The page.** #1315's hand-over stays: one file saves on the finishing click, up to five save together, above five the bar shows. Strings re-keyed in 12 locales. The throw-after-save nit and the scroll-then-save order test ride this PR (they are in the same function).
- **What the app can and cannot observe.** `runs.json` records each file the page was served (name, bytes, time, whether the server finished sending). The browser saving it is not observable and the plan does not pretend it is.

## 6. The new data, gap by gap

All of it is counts, times, sizes, settings and reasons: no term, no article, no address. The app gathers it; the user does nothing.

| Gap (source) | Member | Owner and source | Bound |
|---|---|---|---|
| The first failed run's journal is in no bundle (FINDINGS 8.6, crash read 1, WAL 5) | `runs.json` | export: `data/diagnostics/runs.jsonl`, a begin line at the start and an end line at the finish, so a begin without an end reads as killed; each served file | last 10 runs |
| Build id and process start; no launcher (8.7); versions of duckdb, SQLite, libc (8.2); the resolved memory tier and total MiB (8.3); Wikipedia transport (8.4, plan) | the `machine` block of `manifest.json` (the header: written at the start of the build, present even when a member is declined, so there is no `machine.json`) | export assembles. RC's stamp (total, nominal, tier, cores, serve default, `resolved_at`, allocator and arena cap) is carried once as the live process's reading, beside total RAM now, the tier that total would give now and the memory available now: the tier is read once at import, and on a ballooning VM it moves (OOS-10 says `small` at 4.6 to 4.96 GiB; the 09-30 machine ran the rollup off at 07:15 and on at 21:15 with its total at 4,349 to 6,908 MiB), so a difference between the stamp and now shows as measured drift. The block is written once and not repeated in `debug-bundle.json`, `session-forensics.json` or `soak-window.json`, as RC asked. The transport is the SETTING (proxy or pool configured, which), with the walk's and the stream's median and 95th-percentile answer time from plan's lane history; the names, never the values, of set `OO_*` variables; `allocator_setting()` once (RC's function, read as a setting, no probe) | 20 KB, inside the manifest |
| Memory-growth shape; the minutes before a kill; per-thread state at death (8.8, keyword 6); drive free series (WAL 2); log lines by logger (crash read: the 300-line tail is a sample) | `vitals.json` | export: `src/monitoring/vitals_history.py`, riding the 5 s liveness tick that `session_hwm.py` already has, no new thread. 5-minute buckets for 48 h and hourly for 14 days (min, mean, max, n per bucket) of process RSS, available memory, swap, drive free, database size, threads, plus log-line counts by logger and level; the last 60 minutes with the three busiest threads and their innermost two frames. Flushed every 5 minutes and at a clean end; read at the next boot as the previous session's tail. A gap is shown as a gap, never interpolated. **It does not claim the minutes before a kill**: it records the time of its last flush and points to the member that carries that tail (section 6a). | 260 KB |
| SIGABRT frame; earlier unclean ends; peaks on every end (8.1, 8.7; crash read 1) | `session-forensics.json`, `chronology.json` | export: D+E as planned in PLAN_D_E (10 ends, 60 trace lines each, whose first block is the crashing thread; 4 KB of peaks per end; `git_head` on the boot record) | +60 KB |
| Damaged database not detected (8.5; WAL 4) | `database-damage.json` | WAL: `data/database-damage.json` from its E1 | 40 KB |
| Storage words that misled (WAL 1); drive vs freelist | `storage.json` | WAL: `freelist_bytes` and `drive_free_bytes` renamed in the merge | 120 KB |
| Who held the gate, checkpoint, guard and pool history (WAL 2, 3, 6) | `contention.json` | WAL | 200 KB |
| Backups, exports and restores that failed (WAL 5) | `transfers.json` | WAL | 40 KB |
| What each boot replayed; the tier and allocator at boot (RC 1, 2; WAL 2) | `boots.json` | RC: the stamp goes on every boot record of `session_history.jsonl` in the PR after #1312, with WAL's fields (log bytes at open, phases, previous end clean); sessions before 10-01 have no allocator field and will not get one | 30 KB |
| A restore that failed and why (RC 3: rows B and J wait for the real restore; the 09-19 runs recorded `measured` after a child exit 1) | `release-run.json` | RC extends `last_release_run_report()` itself, which the member already calls, so no `bundle.py` edit: the restore phases in full (label, seconds, return code, scrubbed stderr tail, restore block), `restore_why` per board row, and the restore phase summaries of the last 10 runs | 150 KB |
| Rollup build attempts and the killed-build marker; corpus sizes; re-index; ranking counts (keyword 1 to 5) | `keyword-pipeline.json` | keyword | 60 KB |
| Wikipedia pace, errors by kind, stream gaps, tick split, drain holds (wikipedia.md) | `wiki-lane-history.json` | plan, on #1314 | 300 KB |
| Whether the code works here | `selftests.json` | export | 4 KB |

**6a. The minutes before a kill are recorded once (condition 4).** Two instruments could write them: vitals' 5-minute flush (it can lose up to five minutes, the ones that matter in a kill) and WAL's light snapshot in its findings PR (every 15 seconds while available memory is within 1.5 times the guard's line, which is exactly the lead-up). My proposal, agreed with WAL below: **WAL's snapshot carries the tail**, because it already has the trigger and the finer step; `vitals.json` carries the hours and days before it, states the time of its own last flush, and names WAL's member for what follows (`tail_in`). A reader opens one file for the shape of the climb and one for the last minutes, and no number is in both. Where WAL's snapshot is not built yet, `tail_in` reads `not-in-build` and the 5-minute flush is the only record, said so in the member.

Not met, and why: **per-thread MEMORY at death** cannot be read from inside the process (Linux has no per-thread resident size; tracemalloc would slow the app two to four times). The nearest honest record is process memory beside the busiest threads' CPU and top frames in the last hour, which is what `vitals.json` carries, and it says so in its caveat. **Kernel and filesystem messages** (btrfs errors) are read only where the machine lets the app, as counts with first and last time, "not readable" otherwise, per WAL's need; the existing reader already fails that way on Qubes.

## 7. Slots: how owners add data without touching `bundle.py`

One table, `src/api/diagnostics/slots.py`, added once by me: `(member name, "module:function", owner, budget in bytes)`. Contract for a producer:

- `def diagnostics_member(max_bytes: int) -> dict`, JSON-able, never raises (an exception becomes `{"error": ...}` in the wrapper, as today), keeps the newest records and says what it dropped when it hits `max_bytes`;
- counts, times, sizes, settings and reasons only; every figure carries its method and n;
- it opens its own session if it needs one (slots are non-DB members, so the existing deadline thread applies, 300 s).

**Timing (condition 3).** PR C's recorders (`vitals.json`, `runs.json`, the D+E changes) are added to the bundle as members of their own in C, with their own routes, so the 72 h run's zips carry them whether or not D lands; D moves them into the slot table without changing their names or contents. A module or function that does not exist yet gives the manifest outcome `not-in-build` and no file. A test checks that a slot whose module imports has its function (a typo cannot hide as "not yet built"), that names and budgets are unique, and that the sum of budgets stays within what section 4 states. The owners start now against this contract; they do not wait for my PR. A member that already has an owner-side producer needs no slot: `release-run.json` calls `last_release_run_report()` (RC's module), `soak-window.json` calls plan's, so those owners extend their own function.

**Duplicates cannot come back.** A guard test asserts that `debug-bundle.json` carries none of the sections that are members of their own, and a second one that a bundle built from stub members has no two members sharing an identical subtree of 300 bytes or more. RC reports `release-run` also embedded in `data-dir-persistence` and `country-code-duplicates` (0.02 MB over 17 bundles); I did not find it in the Asus bundle I read, and the guard will say so if it exists.

## 8. The build: records first, then Quick or Thorough scans (R124)

Today every member runs under one exclusive window, so collection is paused for the whole build (9 to 48 minutes). After:

1. **Records first, before the window is taken.** The 60 records (histories, state, counts, the machine block, the session forensics) read state and should show the collector working. Measured 163 to 225 s on all 17 builds. Collection keeps running.
2. **Then the window, for the scans only** (16 members; `kind=scan` and `est_s` in the slot table, `est_s` being the median wall time over the 17 builds, `members.csv` `median_s`; an owner's new scan states its own, and a scan with none counts as 300 s).
   - **Quick (default).** A shared budget, one constant `SCAN_BUDGET_S = 600`. Scans run shortest first by `est_s` (the cost where the scan has work to do: its median over the builds where it ran for more than 5 s, capped at 300, so a scan that costs nothing on a small corpus is not ordered as if it always did); a scan starts only while at least 30 s of the budget are left, and gets the smaller of its own 300 s deadline and the time left, so **600 s is a hard bound on the pause**. A scan the budget cuts is `partial-deadline` with what it gathered (the same outcome eight members already end with at 300 s today); one that never started is `skipped-budget`, with its `est_s` and the reason, in the manifest. **Modelled on the 15 comparable builds' own times** (the three scans the Light profile skipped taken at 300, 300 and 167 s, and the members the R27 decline keeps out left out): 7 to 12 scans run, 4 to 8 are skipped and 0 to 1 is cut partial, and the scans take 574 to 600 s. Skipped every time: benchmark, bulletin-weekly, performance and source-audit; leads-quality in 14 of 15 and keyword-engine in 13 (these five are the members that already end at their 300 s deadline today); keyword-growth in 6, **the keyword digest in 5 and cut partial in 4**, article-length in 2. So on a large corpus Quick will usually not carry the digest whole, and the "All keywords" link is how a user who needs it gets it (R123). Whole build: about 3 + 10 = 13 minutes at most.
   - **Thorough.** No shared budget: every scan runs under its own 300 s deadline, as the scans do today, and a scan that reaches it is named `partial-deadline`. The pause is the scans' share, **27 to 47 minutes (median 42; four builds ran the full profile, 27 to 44, and the other eleven are those plus the three scans Light skipped), at most 16 x 300 s = 80 minutes**; nothing here lifts the 300 s deadline, because that is what keeps one scan from holding collection paused for an unbounded time. Records still run first outside the window, so Thorough pauses collection about three minutes less than today's full build.
3. **The constant carries its reason in the code** (condition 8): what the 600 s protect is the collection pause, since the scans hold the machine exclusive, and the user's wait before there is a file. The budget is a bound on those two costs and nothing else, and a scan that does not fit is named, never silently cut.
4. **The toggle.** `#diag-thorough` replaces the Light checkbox; unchecked every time the panel opens; `mode=thorough` goes to the existing build route; the route keeps `profile=light` for the maintainers only. The manifest header's `profile` block becomes `mode` (`"quick"` or `"thorough"`), `scan_budget_s` (600, or null for Thorough) and a `scans` block (planned, ran, partial, skipped, each skipped one with its `est_s`), so any zip says what it is and what it left out. The panel's progress text names the mode while it runs. The R27 decline (a member the machine cannot carry) is unchanged and named as before.
5. **Cancel.** The build already cancels cooperatively between members (`_all_diagnostics_members`); a cancel releases the window at once, and the existing rule stands that a cancelled run writes no half archive.

I will measure the Quick split on a large synthetic corpus in Chromium before it ships (the panel walk of condition 7 covers the toggle: tick it, build, confirm the manifest says thorough; untick it, build, confirm quick), and say so in the PR.

## 9. Order, and what each waits on

All four touch `bundle.py` and the ledger files, so one at a time, each by merge commit.

1. **#1315** merges after its two should-fix (section 12).
2. **PR B, item 2 with the read release and the R115 hardening**: built and mutation-tested locally (item2m, 9 of 9 mutants killed for the release). Waits on #1315 and on #1314 if it lands first. It goes before the redesign because the redesign rewrites the lines it hardens. **If B is held up in review, C goes first** (condition 3): they touch different code, and the recorders are the time-critical one.
3. **PR C, the recorders**: vitals, run history, D+E, each a member of its own in C (condition 3). Built in a worktree while B is in review. These are the instruments the 72 h run needs, and a recorder only has history from the update on, so it ships before the button. I will show their cost on a 4 GB machine (one small write per five minutes), because an instrument on a periodic path must not become a load.
4. **Before D, or in it: the keyword digest's RAM gate is measured and fixed** (condition 2). The digest declines on an estimate (3 of 17 bundles carry it) although the export spills to disk, and the keyword buttons are the only way today to get it on a machine where the gate declines. I measure the gate against the real spill behaviour, and the two keyword buttons that go (R123: Keyword log and Last keyword files again) go only in the PR where the digest is shown to ride the zip on the machines where the buttons worked; "All keywords" stays as a small link, so a Quick build that skips the digest on a large corpus leaves no one without it.
5. **PR D, the button**: sections 3, 4, 5, 7, 8 and R119. It adds the manifest `machine` block, `selftests.json` and the slot table, and moves C's members into the slot table. **Before D says ready (condition 7) I walk the new panel in Chromium: every drop-down opened, an option picked and its effect confirmed, and both a one-file and a five-file hand-over saved.**
6. **Owner PRs** fill the slots from now on, in any order, with no `bundle.py` edit.
7. After: the slow-member optimisation (OPEN_QUEUE).

The user's deadline: a build with the new button before about 03:30 UTC on 10-09. If the coordinator wants fewer rounds, B and C can merge into one PR; I recommend against it (two reads, two checks, but each is smaller and B is already reviewed).

## 10. Ledger

R119 in `RULINGS_INDEX.md` and `OPEN_QUEUE.md`, in the PR that ships the button: one Diagnostics button, one zip, 4 MB. It **amends R115** (1 MB becomes 4 MB; the numbered scheme stays above it) and **R28** (the Light toggle goes, R122). **R122 (28a), R123 (29b) and R124 (30)** go in `RULINGS_INDEX.md` and `OPEN_QUEUE.md` in the same PR, each with its ledger row, quoting the user's words for R124. Shipped rows through `ledger_shipped.py new` with the real PR number; LESSONS entries for the duplicate-embedding and the five-minute series, with the ceiling raised in the same PR. `planned.py` reports R27, R28, R115, E1 and Q1139 for these files: R27 stays, E1 and Q1139 are untouched.

## 11. Questions for the user (through the coordinator)

**Q-A (question 28). The Light checkbox (R28). ANSWERED a (R122).** R28 is the user's own ruling, so only the user can change it.
 a) Remove it. One run; the app skips only what the machine cannot carry (R27) and the manifest says which. (Recommended: one button, and R111 says users are not asked about inner workings.)
 b) Keep it beside the button.

**Q-B (question 29). The keyword buttons. ANSWERED b (R123).** Under condition 2 they go only in the PR that makes the digest ride every zip.
 a) Remove all three (Keyword log, All keywords, Last keyword files again); the keyword digest rides every zip; the routes stay for the maintainers. (Recommended: R111 says nobody is asked for per-keyword exports.)
 b) Remove two, keep "All keywords" as a text link under the button.
 c) Keep all three.

**Q-C (question 30). How long may the button take? ANSWERED by the user in their own words (R124): a quick diagnostics by default, plus a toggle for a thorough one.** Today 9 to 48 minutes, with collection paused.
 a) Records first (about 3 minutes), then the whole-corpus scans share a stated budget of about 10 minutes; a scan that does not fit is named in the manifest as skipped. (Recommended: eight members already end at their deadline in most builds, so this makes the cut visible and bounded.)
 b) Records first, scans without a budget (today's time for the scans).

(Option c, records only with scans on a second run, was dropped by the coordinator: the user does not want to press twice.) **Answers (08:31): 28a, 29b, and for 30 a Quick default with a Thorough toggle (R124), which is option a for the default build and adds the toggle for the thorough one.** All three are recorded as R122 to R124 in the PR that ships the button. Each is reversible.

## 12. #1315

**Merges after its two should-fix, not as it was** (condition 6). The coordinator's check of 5aae87b9f found no blocks and two should-fix items: S1 (the hint about the browser's several-downloads prompt was overwritten 0.8 s into the unclicked hand-over) and S2 (the same-archive branch was pinned only by a nine-file case, which the five-file gate excludes, so a hoist would have sent a usual two-file bundle twice). Both are fixed at 068f24513 with five of five mutants killed (one further mutant, hoisting the count into the same-archive branch, is equivalent because the save starts at the set's own position, and the script says so). The hand-over saves one file on the finishing click and up to five in a set, so a single 0.6 to 0.9 MB zip works through the same path with no change; the redesign adds the single-file branch behind it. #1315 is not ready until its CI and the coordinator's delta read of 068f24513 are green.

## 13. Limits and risks, stated

- Quick leaves some scans out on a large corpus (modelled: 4 to 8 of 16), each named in the manifest with why; a reader of a Quick zip must read `scans.skipped` before concluding a scan found nothing. The two extremes are one tick apart, by design (R124).
- Thorough pauses collection for 27 to 47 minutes on a large corpus (42 typical; four builds ran the full profile, eleven are Light builds with the three skipped scans added at their measured cost), 80 minutes at the ceiling, and longer than any machine that used Light has seen; the hover text says so before the user starts it, and the toggle never stays on between visits, so a long pause is always chosen on purpose.
- A 4 MB upload may fail where 1.2 MB failed; the budgets keep the common case near 0.75 MB and the constant is one line.
- Merged and dropped members break an analyst script that reads them by name; `replaces` in the manifest maps them, and the coverage map and its guards change in the same PR (row C reads the coverage block and each member's outcome, so the board is unaffected).
- Auto-saving after minutes was walked in Chromium only; Firefox and WebKit are unverified, and the visible bar remains the fallback.
- The 72 h run began without the recorders; what they record starts at the update.
- The budgets in section 4 are estimates until PR C and the owner members exist; the PR bodies will carry the measured sizes.
- A removed control's data must be in the zip first (section 3); where a member turns out to lack something its button gave, the button stays and the table says so.
