# Decisions round — 2026-09-22: everything standing between here and the beta

**What this is.** The maintainer asked, after the diagnostics toggle: *"give me a clear numbered
list of decisions with your recommendations and alternative choices to help you finalize
everything. Make sure to integrate all plans made on PR1131."* This is that list, in the house
answer-sheet format (`R19`, `Q1206`).

**It is built from a full re-read of PR #1131's plans**, not from memory: the seven gate files
`RELEASE_0.3_GATE.md` … `RELEASE_0.9_GATE.md`, all 427 lines of `docs/ledger/RULINGS_INDEX.md`,
`docs/design/PREFLIGHT_QUESTIONS_2026-09-18_RELEASE_RUN.md`, and a marker sweep over all 223
top-level entries of `docs/ledger/OPEN_QUEUE.md`. **Nothing already answered is re-asked.**

**Part A re-states nothing — it POINTS.** Forty-one decisions are already recorded as open, each
with its own `ANSWER` line where it lives. Part A gives you one line and my recommendation for
each so you can answer them here in chat; the recording session copies the letters back to their
primary records. **Part B is the only genuinely new material**: six collisions between the
2026-09-21 field-slowness plan and PR #1131's slices that no document records yet, the
awareness mechanism you asked for, and the sequencing of PRs 3–7.

---

## §0 — How to answer, and how the answers are processed

- Write a letter after `ANSWER Dnn:`. A note in your own words is welcome and is recorded
  verbatim; **where the note contradicts the letter, the note is the ruling.** Answering in chat
  with the same `Dnn = letter` form is equivalent.
- **Blank on a ⛔ question stays PENDING** — never defaulted. **Blank on any other question takes
  the stated default as an ASSUMPTION**, reversible at any time, and the session that acts on it
  labels it as one.
- Processing: the letters are parsed by the first session that receives this back; this file stays
  the primary record; one `OPEN_QUEUE.md` entry indexes the round; `RULINGS_INDEX.md` gets a row
  per answer; the gate files and briefs the answers touch are amended in the same PR; **no ruling
  is invented, and contradictions are listed, never resolved by the recording session.**
- ⛔ = never taken autonomously. 🔒 = changes what the app retains or contacts.

---

# PART A — already open, waiting only on you

## §A1 — The six that BLOCK work (⛔; nothing may proceed)

**D01 ⛔ · Q823 — ODbL: may OSM-derived data ever leave the machine?**
Blocks `RELEASE_0.5_GATE.md` row D. `src/backup/attribution.py` already **raises
`PendingRulingError`** the moment an `osm_*` table appears, so **the export, the bulletin and the
evidence ZIP will refuse the day S05-04 lands the OSM lane.** Sub-question nobody has ruled: does
a byte-for-byte copied Geofabrik `.pbf` count as "leaving the machine"?
→ **My recommendation: allow OSM-derived rows in exports with the ODbL attribution block the
attribution module already knows how to write, and read a copied extract as redistribution (so it
carries the same block).** It is the licence's own bargain and the code is written for it.
`ANSWER D01:`

**D02 ⛔ · Q925 — the law adapter order and the first managed dataset.**
117 verified sources are ranked in `LAW_ADAPTER_SEAM.md` and **none is chosen**; 0.4 row Q cannot
close. → **Recommendation: `legislation.gov.uk` first** — it is the one of the three live-probe
hosts with a stable bulk interface, and the framework was built against it.
`ANSWER D02:`

**D03 ⛔ · Q1009 — the four storage round-2 values (blob dedup · pack AEAD · keyed-HMAC addressing
· sqlite3mc trial).** Answer as four letters in order, e.g. `y, OOENC2, y, y`. Blocks 0.5 row F,
0.9 row F, the Wikipedia tail-walk's depth, **and a live CodeQL finding** (`ENCRYPTION_KEY`
derived from the corpus passphrase by a single SHA-256 since 2026-06-19) that is deliberately
unfixed because the brief forbids touching the store.
→ **Recommendation: `y, OOENC2, y, y`.** Own AEAD over `age` because the format must be
self-describing for the 0.9 backup freeze (`Q102`).
`ANSWER D03:`

**D04 ⛔ · Q1113 — the compromised embassy platforms (institutions B5).** Today's state is
exclusion by an existing flag, which is not a decision. Nothing was published; nobody was
contacted. → **Recommendation: keep them excluded and record the exclusion as the ruling** — the
alternative is a publication decision about a third party's breach, which the project has no
standing to make.
`ANSWER D04:`

**D05 ⛔ · RC02 — is removing the legacy single-file restore authorised for 0.7?**
**This is a live document-vs-document contradiction, and both sides are on the record**: register
C1 says *"the removal … is authorised, but not before 0.7"*; sheet `Q215` says *"Keep the restore
half forever, as the docstring commits."* 0.4 row K was built on `Q215`'s side only because RC02
came back blank. → **Recommendation: `Q215` — keep the restore half forever.** It costs a read
path; removing it strands the operator whose only backup predates volumes.
`ANSWER D05:`

**D06 ⛔ · RC10 — does `Q114`'s «add them» reach `dumps.wikimedia.org`?**
Until ruled, 0.4 row V's closing probe stays `not-measurable-here` and two PROMPT_06 slices stay
operator-side indefinitely. → **Recommendation: yes, add it.** It is the same class of host as the
others already added, and the app already fetches from it under the invariant-#14 gate.
`ANSWER D06:`

## §A2 — The protocol itself is failing its own test

**D07 ⛔ · PF11 — `LESSONS.md` has outgrown rule (1) a second time.**
Rule (1) was amended 2026-09-07 because one 1.3 MB file could only be "read in full" by skimming.
PF11 measured `LESSONS.md` at 985,788 bytes on 2026-09-18; **re-measured today it is 993,078, and
the mandatory pair is 1,051,279** — past 1 MB again and still growing, the same failure mode one
file over. **A session may not amend the protocol.** This is unanswered and appears nowhere in
`RULINGS_INDEX.md`.
- **a** — a size ratchet on `LESSONS.md` + compress older entries to verdict + pointer.
- **b** — reclassify `LESSONS.md` as consult-by-grep, like `OPEN_QUEUE.md` (it stops being
  mandatory reading and gains an index).
- **c** — leave rule (1) as written.
→ **Recommendation: b, with a's ratchet added on top.** (a) alone loses the lessons' texture,
which is where their value is; (c) is the status quo that already produced the failure. (b) is
what rule (1)'s own 2026-09-07 amendment did for the queue, and it worked.
`ANSWER D07:`

## §A3 — The 0.8 entry, and one feature nobody has scoped

**D08 ⛔ · The app-wide one-model decision — 0.8 cannot open without it.**
`RELEASE_0.8_GATE.md` row C. Feeds the `Q1142`/D8 conflict (D18 below).
→ **Recommendation: defer the decision but open 0.8 anyway** by rewriting row C as *"the model in
force at 0.8's close is the one shipped"* — the current entry condition means one unanswered
question stops an entire release from starting.
`ANSWER D08:`

**D09 · RC12 — the version/scope of the poll-data feature.** Your own note redirected the whole
feature (*"let them access to the poll's questions exact verbatim, let them detect questions that
orient answers … We should review everything regarding this for version ."*) and the version
number was never written, so `FUTURE_DEVELOPMENTS.md` §Poll analysis still owes its rewrite. **No
default exists** — a second blank keeps it pending. → **Recommendation: 0.6**, alongside the
other analysis-surface work.
`ANSWER D09:`

**D10 · The eclipse canon (RC13's unwritten `± eclipses` suffix).** Neither dropped nor funded; no
session may settle it by building *or* by removing. → **Recommendation: `− eclipses`** — the
religious-calendar session is already briefed and eclipses are a separate astronomical dataset.
`ANSWER D10:`

## §A4 — Ten CONFLICTs: two answers recorded, you pick one

Each ran on the later channel's side because the 2026-09-15 confirmation round came back with
**0 of 22 `ANSWER` lines carrying a letter**. All ten are reversible on one word. *Where a side is
already built, I say so — reversing it is work, not just a letter.*

| # | conflict | running on | my recommendation |
|---|---|---|---|
| **D11** | Stoplist merge: `Q1103` frozen-forever vs `Q1104` merge-by-batch — **the same sheet contradicts itself**, and 0.4 row M is HELD until you pick | neither; the row ships with no merge | **`Q1104`** — your own `Q1103` note («we will update the list as we update the app») already reads as the merge side |
| **D12** | Subnational law: `Q903` — **you marked both (a) and (b)** | placed at 0.7 to keep both scopes | **(a)** national + supranational through beta |
| **D13** | The multi-model bench: `Q1142` run it in 0.5 vs D8 wait for the one-model ruling | RC04's default: no bench in 0.5 | **D8** — a bench whose answer is overridden by a later ruling is wasted |
| **D14** | Live `ollama.com` library browse: `Q1143` consented opt-in vs D9 drop it | dropped | **D9 (drop)** — keep the consented-host list as small as it is |
| **D15** | Political-lean vocabulary: `Q1129` keep the stance vs L9 remove `lean-*` | removed from the offerable set | **L9** — a model offering a lean label is the composite score the project refuses |
| **D16** | Topical filtering: `Q1130` `via:*` only vs L10 `via:*` + coverage-state — **already BUILT on L10** | L10 | **L10**, confirm what shipped |
| **D17** | Tor-exit-resolve: `Q1138` park until 0.9 vs I3 build now — **already BUILT as a 0.9 slice** | `Q1138` | **`Q1138`**, confirm |
| **D18** | The 64,910 `kind_overrides`: `Q1105` build a review surface vs B4 measurement only | B4: no tool | **B4** — 64,910 proposals is not a worklist a person can work |
| **D19** | Re-verification window: `Q1108` 6 months vs B7 90 days beside the whole history — **BUILT on B7** | B7 | **B7**, confirm |
| **D20** | Religious calendar: `Q1135` drop it vs G8 a dedicated networked session | G8's session is briefed, unbuilt | **G8** — run the session |

`ANSWER D11:` `ANSWER D12:` `ANSWER D13:` `ANSWER D14:` `ANSWER D15:`
`ANSWER D16:` `ANSWER D17:` `ANSWER D18:` `ANSWER D19:` `ANSWER D20:`

## §A5 — The pre-flight round (2026-09-18) — never answered, and it gates your own button

Fourteen questions in `docs/design/PREFLIGHT_QUESTIONS_2026-09-18_RELEASE_RUN.md`, answerable at
their own `ANSWER PFnn:` lines. **PF11 is D07 above.** My recommendation for each of the other
thirteen, so you can answer them as a block:

| id | question | recommend |
|---|---|---|
| **PF01** | tick the 0.3 row-5 quarantine pass on which instance | **a** — release-scale only |
| **PF02** | destination drives for the two instances | **a** — each its own ≥3.2× drive |
| **PF03** | soak length | **b** — 96 h, a day's margin over the bar |
| **PF04** | how the run's artifacts reach the next session | **a** — commit to a branch |
| **PF05** | a pre-migration backup for row K's real-restore proof | **b** — none exists |
| **PF06** | does 0.4 row R close now | **a** — close it |
| **PF07** | the three broken ride-along opt-outs (settings that silently don't take) | **a** — fix before the 0.4 tag; a control that lies is worse than a missing one |
| **PF08** | the speed-unit error: four strings + invariant #4 say `KiB/s`, the code means `kbit/s` — an **8.192× overstatement** | **b** — change the arithmetic to real KiB/s. (a) fixes the label and leaves the knob meaning something else than every other byte figure in the app |
| **PF09** | bind i18n to `reader.js` (22 permanently-English strings) | **a** — yes; "every string ×12" is a non-negotiable and 22 is not an exception |
| **PF10** | in-map controls covering 79–112% of the map at phone width | **a** — collapse to one button |
| **PF12** | Japanese segmenter | **a** — `sudachipy`, per the locked `Q506` |
| **PF13** | the twelve owed click-throughs | **b** — name a sample; twelve full walks is days of your time against a Chromium record that already exists |
| **PF14** | the `guarded_session` SSRF gap: press now or fix first | **b** — **fix first.** This is the one PF where I differ from the sheet's own default: the gap is in the fetch path, and the release run's whole point is to produce evidence about that path |

`ANSWER PF01:` … `ANSWER PF14:` *(answer inline here or in the primary file)*

## §A6 — Twelve items that never entered the rulings pipeline at all

Found only in `OPEN_QUEUE.md`; no `Qnnn` anywhere. Each is one line + my recommendation; say
"all defaults" to take them as a block.

| # | item | recommend |
|---|---|---|
| **D21** | **Nothing verifies `main` itself.** Of the 40 most recent completed runs, **34 cancelled · 2 failure · 4 success — and all four successes are the `schedule` cron**; the `cancel-in-progress` exemption for the default branch is written and does not take. So a semantic conflict between two individually-green PRs lands unseen. **The mechanism is deliberately UNMEASURED** (pending-supersession vs. the exemption evaluating true are indistinguishable from what was measured) and the fix is a COST decision: a per-SHA group runs a full macOS + Windows + Ubuntu matrix at roughly one merge every four minutes | **d — rule that the nightly cron IS the referee for `main`**, and say so in the ritual so nobody reads a cancelled main run as a pass. It is the option PR #1040 named and it costs nothing: the cron referee already exists in fact. (a) a merge queue is the real fix and changes the merge ritual; (b) per-SHA concurrency spends the money; (c) accepting PR-run-only coverage is honest only if the ledger stops implying `main` is verified |
| **D22** | Should quarantined articles leave the keyword aggregates (PRH-06)? | **yes**, and the ruling covers the language series and the equilibrium lever in the same pass |
| **D23** | `install.sh`'s dead `OLLAMA_MODELS` hint (34 lines) | **delete it** — a documented affordance nothing wires is a lie in a shell script |
| **D24** | Stopword/ring collision hides 38 `en`/`fr` concepts | **c — exempt ring members from `global_stopwords()`**; the ratchet option keeps 38 concepts invisible |
| **D25** | Indices tile → full chart? | **a — stay a tile** |
| **D26** | ooMap embed: new timeless mark kind vs country choropleth | **b — choropleth** |
| **D27** | Conjunction Lens `vocabulary_contrast` exposure | **a — leave unexposed** |
| **D28** | Retire `#tab-search` / the Enter-to-analysis ordering | **leave it** — it changes an interaction you use daily |
| **D29** | What does `scrape_app_provided_only` mean on old installs? | **the row's ORIGIN**, and widen the match accordingly |
| **D30** | Is `law.db` beside `law_documents` the end state or a step? | **the end state** — the split is honest: the roster is relational, the corpus is not |
| **D31** | The `_OOS_` token in bulletin/evidence filenames vs `Q212`'s `OpenOmniscience` | **leave it** — renaming is a migration, not a token swap |
| **D32** | Should the `OO_REQUIRE_CONSENT` hard block ever ship? | **no** — leave it the documented option it is |

`ANSWER D21:` … `ANSWER D32:`

---

# PART B — NEW: what this round actually raises

## §B1 — Six collisions between the field-slowness plan and PR #1131's slices

**These are recorded nowhere.** The 2026-09-21 field report's seven PRs and PR #1131's 38 slices
were written three days apart by sessions that could not see each other, and they overlap on six
points. Every one is a decision because the cheap path and the correct path differ.

**D33 · Three corpus-sized rewrites all want `keyword_mentions`, and nobody sequenced them.**
PR 5 (`R23`, the bulk build on the live store), 0.5 row B's alpha-3 language migration (`RC08.1`)
and the C5 pragma rebuild each rewrite the same 11 M-row table. On the field corpus each is
measured in hours.
- **a** — **fuse them into one pass**: one rewrite, one disclosure window, one "rebuilding N of M".
- **b** — run them in sequence as three slices, each with its own window.
- **c** — sequence them but share the rebuild machinery.
Default if blank: **a**. → **Recommendation: a.** Three separate corpus-sized rewrites on a 27.7 GB
encrypted store is most of a day of the operator's instance being unusable, three times, for work
that touches the same rows.
`ANSWER D33:`

**D34 · The lane databases are invisible to the memory budget, and `R26` raises the other half.**
`src/config/memory_budget.py` tiers the corpus engine (`small` = pool 6 / overflow 2 / **8 MB**
cache). Every *lane* database opens its own engine at `src/versioned/store.py:178` with
**hardcoded** `pool_size=2, max_overflow=4` and `cache_size=-16000` — **16 MB each, twice the
whole small tier's corpus cache, additive and unbudgeted.** `R26` says raise the tier pool; raising
it without folding the lanes in budgets the smaller half.
- **a** — fold the lanes into `memory_budget.py` (a lane's pool and cache scale with the tier).
- **b** — leave them hardcoded and *document* the additive cost in the budget's own disclosure.
- **c** — leave them entirely as they are.
Default if blank: **a**. → **Recommendation: a.** The budget's value is that it is the one place
that knows the machine; a second, larger allocation it cannot see is how two surfaces come to
disagree about one quantity — the same reason `Q1012` put the bandwidth budget per-process.
`ANSWER D34:`

**D35 · PR 7 (`R24`) wants the backup format, and 0.9 freezes it.**
`R24` changes how same-engine backups carry mention rows. `Q102` freezes the backup format at
0.9.0 ("every backup made since 0.9.0 restores forever") and row K allows **ONE** format bump.
- **a** — ship PR 7 **before** 0.9 and spend the one bump on it.
- **b** — ship PR 7 **after** 1.0 as a new format version.
- **c** — ship PR 7's speed-up in a way that does not change the format (bulk-insert the same rows).
Default if blank: **c**. → **Recommendation: c**, falling back to **a**. The 9.86 M orphaned
keywords on the field instance are a correctness problem, not only a speed one, and (c) fixes them
without spending the freeze's only bump.
`ANSWER D35:`

**D36 · An Alembic batch rebuild silently drops all three FTS triggers; `verify_copy` checks one.**
SQLite's batch-alter mode recreates a table, which drops its triggers. `src/backup/merge.py`
knows only `article_fts_ai` (`_FTS_INSERT_TRIGGER`) — so a migration that rebuilds `articles`
leaves the corpus with a **silently half-indexed FTS** and nothing notices. 0.5 row B's migration
is exactly such a rebuild.
- **a** — fix in PR 3: `ensure_fts` becomes the single authority, every migration calls it, and
  `verify_copy` checks all three triggers.
- **b** — fix it inside 0.5 row B's slice, where the rebuild actually happens.
Default if blank: **a**. → **Recommendation: a.** This is a latent data-integrity bug today, not
only when row B lands.
`ANSWER D36:`

**D37 · Nothing stops two whole-corpus jobs running at once.**
The re-index drain, the bulk build, a migration, the diagnostics bundle and an import each take
the single write gate for minutes to hours, and none of them knows the others exist. The field
instance's 1,329-second gate hold is what this looks like from the API's side.
- **a** — build one **admission gate** for corpus-sized work: a job declares its scale, and the
  gate serialises them and says which one is holding.
- **b** — keep per-job guards and add the missing ones case by case.
Default if blank: **a**. → **Recommendation: a**, as PR 3. It is also the surface that would have
made findings F4, F5 and F10 self-explaining instead of unexplained.
`ANSWER D37:`

**D38 · One step of my own 2026-09-21 report's operator advice rests on a lever a 2026-08-03
measurement already found not to be one.**
§9.1 step 3 tells you to set `OO_SQLITE_CACHE_MB=64` for the drain, and step 1 justifies the RAM
with *"the OS page cache is what makes random writes on a 27.7 GB store survivable."* Those are
**two different caches**, and only the second argument is measured. The 2026-08-03 import-cache
regression measured SQLite's own `cache_size` directly (encrypted, WAL, page_size 16384, 1 GB
incoming): raising it from 32 MiB to 2048 MiB moved **RSS** from 1,060 to 2,042 MB while the
balance **spilled to the file during the open transaction** — so `cache_size` is a *residency
dial, not a throughput lever*, and the lesson's own words are that the rule it replaced *"turned
it UP on exactly the machines least able to pay."* The report's write-bound chain does not depend
on this, and step 1's OS-page-cache reasoning is sound and separate — but step 3's expected
benefit is **unmeasured**, and it is advice aimed at a 4-to-7 GB VM.
- **a** — correct §9.1 in place: keep the RAM advice, drop or qualify the `OO_SQLITE_CACHE_MB`
  step, and cite the 2026-08-03 measurement so the next reader meets it.
- **b** — leave the report as the record of what was thought on 2026-09-21 and note the
  correction in the ledger only.
Default if blank: **a**. → **Recommendation: a.** The report is now the document future sessions
read about this instance; an unmeasured knob sitting in a numbered operator checklist is exactly
what the awareness mechanism in §B2 exists to prevent, and it would be odd to build that while
leaving this one in place.
`ANSWER D38:`

**D44 ⛔ · `R26` cannot make the medium tier safe — found by building it (2026-09-23).**
`R26` says raise the pool, never lower the worker cap. On the **small** tier that closes F1
exactly: the cap is 8, the pool went 8 → 12, the margin is 4, and the invariant is now
test-enforced against *both* constants so neither can move alone. On **medium**,
`collect_parallelism` ships at **50** and the floor's cap applies only *below* the floor —
so nothing bounds the fan-out, and a pool sized to 54 connections at 16 MiB each would be
864 MiB of worst-case page cache on an 8 GB box.
- **a** — a **reservation at checkout**: the collector may not take the last
  `_API_MARGIN` connections. This bounds concurrent DB checkouts, **not** fetch fan-out —
  every worker still fetches; they queue briefly for a connection instead of starving the
  API. Arguably not the "worker cap" `R26` forbids lowering, but that is your call, not
  mine.
- **b** — a **cap derived from the pool** on medium too. Honest and simple; `R26` forbids
  it in as many words.
- **c** — **leave it**, and let the pass summary keep reporting
  `api_headroom.sufficient: false` on that tier. The margin already bought four more
  served calls before the pool empties.
Default if blank: **⛔ none — this stays PENDING.** → **Recommendation: a.** It is the only
option that makes the invariant true on the tier where 50 workers are real, and the
distinction it rests on (checkouts vs fan-out) is exactly the one `R26`'s wording leaves
open. *Shipped state meanwhile:* the small tier is fixed, medium is improved and
**honestly reported as insufficient** rather than implied fixed.
`ANSWER D44:`

**D45 ⛔ · The article-row rewrite is a TAIL cost, not a constant factor — measured while
building PR 4 (2026-09-23).** Audit §9.2 item 4's third named factor is "the article-row
rewrite taken off the pass", from §4.1's `[CODE-READ]` that the stamp UPDATE "rewrites the
whole record". Measured, the statement is **narrow** — five columns, `updated_at`,
`top_keyword_id/count/tied_n`, `keyword_indexed_at` — but SQLite is a row store, so the
question is whether the untouched content blob rides along. It does, and the shape is a
**cliff, not a slope**: WAL bytes for exactly that UPDATE stay at **16,440 (one 16 KiB
page) for every stored row size up to ~16.3 KB**, then jump to 4 pages at 16,400 bytes, 6
at 40 KB and 10 at 80 KB.
- That matters because **below the cliff a narrow side table would cost the same one
  page** (its own leaf). So moving the four hot columns out of `articles` buys **nothing**
  for a typical article and helps only the long-form tail.
- Whether a given corpus crosses it is **not something this session can see**. Real
  non-repetitive prose compresses **2.0–2.4x** (measured on this repo's own docs), which
  would put the cliff near 35–38 KB of raw text — but `articles` carries **both** a plain
  `content` column and a `compressed_content` one, and if ingest populates both the row
  payload is raw + compressed and the cliff arrives far earlier. That is the operator's
  store to answer:
  ```sql
  SELECT count(*) AS articles,
         sum((length(content) + coalesce(length(compressed_content), 0)) > 16300) AS over_cliff,
         cast(avg(length(content) + coalesce(length(compressed_content), 0)) AS int) AS mean_row_bytes
  FROM articles;
  ```
- **a** — **leave it, and measure first.** Ship the query above with the next bundle; the
  answer decides whether there is anything here worth a migration.
- **b** — **move the four hot columns to a narrow side table.** Pays only on the tail, and
  costs a migration plus every read path of four columns on the most-read table.
- **c** — **move the COLD content blob out instead**, leaving `articles` as narrow hot
  metadata. The only option that makes every future hot-metadata write cheap rather than
  this one; much larger, and it overlaps §9.2 item 7's segmented derived index for 0.5.
- **d** — **coalesce the TWO article-row writes into one**, which is new information: §4.1
  describes *"an UPDATE of the article row"*, **singular**, and the row is in fact rewritten
  **twice** per apply — once for `sentiment_*`, once for `top_keyword_*` +
  `keyword_indexed_at` — because a query between the two assignments autoflushes the first.
  Two flushes of one object are two UPDATEs, so **above the cliff the cost is double what
  the audit states**. Pre-existing rather than introduced by PR 4 (verified in a `git
  worktree` at its base: two there as well), and counter deferral does **not** coalesce
  them, because the batched keyword prefetch and the source-self-name read still autoflush
  between the two. Assigning the sentiment adjacent to the stamp would halve it **with no
  schema change and no migration** — the cheapest option on this list by a wide margin. The
  reason it is not simply done: it moves an assignment relative to the when/where/who
  `SAVEPOINT`, immediately beside a comment explaining why `keyword_indexed_at` is
  deliberately assigned *before* `begin_nested()` so that a WWW-pass rollback cannot undo
  the record of a keyword pass that did complete. Getting that ordering wrong is a
  data-correctness bug in the delete-then-reinsert path, not a slow query.
Default if blank: **⛔ none — this stays PENDING.** → **Recommendation: d first, then a.**
`d` is cheap, needs no migration, and pays on **every** article above the cliff rather than
on a tail; `a` then decides whether anything further is worth doing. `c` is the one worth
designing if the distribution says it matters, and `b` optimises the tail at the price of
the common path's read simplicity. *Shipped state meanwhile:* **nothing built for this
item**, and PR 4 says so rather than letting "the constant factors in apply" read as all
three.
`ANSWER D45:`

## §B2 — The awareness mechanism you asked for

*"find a way so that future bug discovery would not contradict what has been planned … to help
future unaware sessions to become aware of the changes, and to avoid redoing some thinking that
has already been done."*

**Why nothing today does this.** `shipped.csv` has a `key_paths` column — but it is
**retrospective**: it says which files *were* touched, never which files a *planned* decision
owns. `RULINGS_INDEX.md`'s "where enforced" names paths only sometimes and only in prose (`R22`–
`R25` name none). **`CLAUDE.md` contains zero references to `FUTURE_DEVELOPMENTS.md`, `ROADMAP.md`
or the `beta-pathway` folder** — so a session fixing an unrelated bug has no instruction pointing
at them. The only grep instruction is *"before asking the maintainer anything"*, never *"before
editing a file"*. And `LESSONS.md:7476-7497` records this failing **once already**: a session
trusted a stale code comment saying `page_size=16384` was unratified, and spent one of your
decisions re-ratifying it.

**What I propose to build** — a reverse index keyed on the thing a session actually does (open a
file), not on the thing it must remember (grep the ledger):

1. **`docs/ledger/PLANNED_INDEX.tsv`** — generated, one row per `path → {ruling id, kind, one
   line, where to read, blocked?}`, harvested from the 38 slice briefs, the seven gate files,
   `RULINGS_INDEX.md`'s "where enforced" and every ⛔/PENDING entry in `OPEN_QUEUE.md`.
2. **`scripts/planned.py <path>`** — "what has already been decided about this file?", and
   `--diff` for a whole changeset.
3. **A CI step** that runs `--diff` on the PR's changed paths and prints the hits.
4. **`CLAUDE.md`** gains the pointer (it currently names none of the plan files) and one ritual
   line: *before editing a file, ask what is planned for it.*
5. **A test** in `test_repo_invariants.py` that the index is regenerable and current — so it
   cannot rot the way the ruling-ID comments did (8 of 10 sampled source files cite ruling IDs;
   nothing enforces it).

**D39 · How hard should it bite?**
- **a** — advisory everywhere: the CI step prints, never fails.
- **b** — advisory, **except blocking on a ⛔ path**: touching a file owned by a blocked ruling
  fails the lane unless the commit says `ACK <id>`. Mirrors the `PendingRulingError` guard that
  already exists in `src/backup/attribution.py` for `Q823`.
- **c** — blocking on every hit.
Default if blank: **b**. → **Recommendation: b.** (a) is a lint nobody reads; (c) makes every
unrelated bug fix argue with the ledger.
`ANSWER D39:`

**D40 · Where does the index get its paths?**
- **a** — auto-extract backticked paths from the briefs and gate rows (no brief edits; some noise).
- **b** — add a `**Touches:**` header to each of the 38 briefs (a 38-file diff; exact).
- **c** — **a** now, with **b**'s header taking precedence wherever someone writes one.
Default if blank: **c**. → **Recommendation: c.** It works on day one and gets sharper as briefs
are touched anyway.
`ANSWER D40:`

**D41 · The `CLAUDE.md` size ratchet.** This costs roughly 12 lines in the constitution, which
rule (5c) says is *"normal for a PR that adds a non-negotiable … or an amendment to the protocol
itself"*. Confirming so the ratchet is raised deliberately rather than as a side effect.
- **a** — yes, spend the lines in `CLAUDE.md`.
- **b** — put it in `LESSONS.md` instead (but see D07: that file is over 1 MB and may stop being
  mandatory reading, which would make this invisible).
Default if blank: **a**. → **Recommendation: a.**
`ANSWER D41:`

## §B3 — The remaining field-slowness PRs

**D42 · Order and scope of PRs 3–7.** PR 1 (`R21`, shipped) and PR 2's toggle (`R28`, shipped as
#1165) are done; `R26`'s pool raise is PR 2's other half.
- **a** — **2b (pool, `R26` + D34) → 3 (instrumentation + admission gate, D37 + D36) → 6 (`R25`
  import stages) → 4 (`R22` counters) → 5 (`R23` bulk build, fused per D33) → 7 (`R24`, per D35)**.
- **b** — the report's original 2→3→4→5→6→7.
- **c** — jump straight to PR 5, the order-of-magnitude step.
Default if blank: **a**. → **Recommendation: a.** It front-loads the two that make the rest
measurable (the pool stops the API 500s; the instrumentation names F4/F5/F10) and puts the bulk
build after the migration sequencing D33 settles.
`ANSWER D42:`

**D43 · The §8 A/B nobody can run here.** PR 1 removed four per-pass costs and **claims no
speed-up figure**, because the only machine where the write-bound behaviour reproduces is yours.
- **a** — run the A/B on your instance before PR 5 (drain alone, commit batch 200, measure rate).
- **b** — skip it; ship the remaining PRs on code-reading alone.
Default if blank: **a**. → **Recommendation: a.** Without one measurement, PR 5's
"order-of-magnitude step" is a claim rather than a finding.
`ANSWER D43:`

---

## §C — Contradictions recorded, NOT resolved

Per §0, the recording session never resolves these. Three are live:

1. **`Q1103` vs `Q1104`** — the same answer sheet, the same day, opposite answers on the stoplist
   merge (D11).
2. **`Q903` (a) and (b) both selected** on subnational law timing (D12).
3. **Register C1 vs sheet `Q215`** on the legacy single-file restore (D05) — 0.4 row K is already
   built on one side.

And one premise-vs-measurement mismatch, which is mine to fix rather than yours to rule (D38).

## §D — What I will do if this comes back blank

Every non-⛔ default above, taken as a labelled ASSUMPTION: **D33 a · D34 a · D35 c · D36 a ·
D37 a · D38 a · D39 b · D40 c · D41 a · D42 a · D43 a**, and the awareness mechanism built as
described. **The ⛔ items (D01–D08, D10 where marked) stay pending and I build nothing behind
them.** The Part A pointers stay where they are, unanswered, as they have been.
