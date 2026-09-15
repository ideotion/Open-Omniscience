# S04-08 — The versioned-source substrate and the lanes · 0.4, `RELEASE_0.4_GATE.md` row O

> **Scope:** a new `src/versioned/` package; `src/scheduler/` (the `mode` setting, its runner branches, the
> housekeeping lane ladder); `src/database/connect.py` (the one keyed path, reused for the lane files); the
> backup MEMBER hook only; one Settings storage surface; the Living sources view replacing `#wiki-tc`;
> `tests/fixtures/`. NOT: the EventStreams client, tiers or wizard (S04-09); the law model (S04-10); the OSM
> lane seed (0.5); the DuckDB columnar store (Q1009 ⛔, 0.5); the backup-format bump (S04-04); alpha-3
> (S04-05); the consent popup's host list (S04-01 — this slice only ADDS a transport line per lane).
> **Implements:** Q716, Q719 🔒, Q720 🔒, Q926, Q1003, Q1004 🔒, Q1005 🔒, Q1006, Q1007, Q1010, Q1011, Q1014,
> Q1015, Q1016, Q1018, Q1020.
> **Gated on:** S04-01 (the per-lane hover). No ⛔ inside the slice; the OSM fixture is synthetic, so Q823 ⛔
> (ODbL) is never touched.
> **Sequencing:** row O precedes P and Q by construction — S04-09 mounts the stream here, S04-10's fixture
> jurisdiction runs here; S04-03's member sizes (Q219) read the lane files this slice creates.

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
own section for those questions (§8 for Q716 / Q719 / Q720, §10 for Q926, §11 for Q1003–Q1020). Grep the
tree before building anything — the sheet's anchors were verified at `main`@`bebcef4` on 2026-09-12 and may
have moved; this brief re-checked them at `7ca142e`.

## 1. The rulings this slice implements — verbatim, by ID

- **Q716** — **(a)** «Wikipedia becomes a lane beside RSS collection; `mode="wiki"` is retired;
  `POST /api/wiki/pages` survives as "pin this page to HOT".»
- **Q719** 🔒 — **(a)** «`wiki.db` (and `osm.db`, `law.db`) beside the corpus, linked by ids; backups per
  lane; a 100 GB lane never bloats the corpus file or its encryption rekey.»
- **Q720** 🔒 — **(a)** «Encrypted with the same passphrase, same threat model, no exceptions.»
- **Q926** — **(a)** «Same answers as the Wikipedia lane (Q719, Q720).»
- **Q1003** — **(a)** «`src/versioned/` shared by the wiki, law and OSM lanes, the wiki adapter first.»
- **Q1004** 🔒 — **(a)** «Yes: `corpus.db` (press, as today) + `wiki.db` + `osm.db` + `law.db`, each
  encrypted alike, each an opt-in backup member, linked by ids.»
- **Q1005** 🔒 — **(a)** «Encrypted, same passphrase, same threat model, because the selection reveals
  interests.»
- **Q1006** — **(a)** «Settings → Storage shows each lane's size, its budget, the honest arithmetic ("at your
  current rate this lane grows ~2 GB/month"), and the disk left; budgets are published defaults sized for the
  reference VM.»
- **Q1007** — **(b)** «SQLite for everything.»
- **Q1010** — **(a)** «Every budget is published and sized for the 2-core / 3.5 GB VM by default; power users
  raise them; nothing silently assumes the maintainer's machine.»
- **Q1011** — **(a)** «The app reads cores, RAM and free disk at boot (no network), proposes budgets from a
  published table, and shows the reading.»
- **Q1014** — **(a)** «Each lane declares its transport in the consent hover; a lane never downgrades Tor →
  clearnet without the explicit consent the non-negotiable requires (Q722's walk waits instead).»
- **Q1015** — **(a)** «Compiled code only in optional extras (`[geo]` = pyosmium); pure Python in core
  (`simplemma`); SSE hand-rolled over the guarded session (no new client library); every addition registered
  in `configs/external_artifacts.yml`.»
- **Q1016** — **(a)** «One view for wiki / law / OSM: timeline of changes, diff, coverage, freshness, budget;
  replaces the tracked-changes modal; a main tab or a Home family — your call in a NOTE.» — no NOTE was
  written; the placement is open (§6).
- **Q1018** — **(a)** «A synthetic wiki edition, a synthetic OSM extract and a synthetic jurisdiction in
  `tests/fixtures/`, so every lane's pipeline runs end-to-end in CI without a socket.»
- **Q1020** — **(a)** «The scheduler runs lanes (press, wiki, osm, law, hazards, discovery) under one online
  consent with one governor and per-lane budgets; the `mode` setting is retired with a migration.»

## 2. Where this stands in the tree — the staleness guard, with anchors

- `src/versioned/` does not exist (grep-verified: `ls src/versioned`). The sheet's §11 context (VERIFIED)
  lists the intake's design for it: identity `(kind, external_id)` + QID · immutable baseline · a change feed
  with cursor, gap detection, budget and politeness · a revision store · the latest as an Article · point in
  time · disclosure · one Living sources view · one diagnostics member per kind · opt-in backup members.
- The mode: `src/scheduler/settings.py:21` `VALID_MODES = ("rss", "crawl", "markets", "wiki", "law")`, `:66`
  `mode: str = "rss"` (sheet VERIFIED; confirmed); `src/scheduler/runner.py:744–761` the wiki-mode branch,
  `:492–496` the per-mode preview count; wiki mode never runs by default and STOPS RSS when selected (sheet).
  A lane ladder exists: `runner.py:1186–1213` `_LANE_KINDS` (markets, hazards, calendar, law, world_discovery,
  qualification, country_data, crawl, backfill) + `_LANE_RATES` / `_LANE_FLOORS`. Settings migration precedent:
  `settings.py:196–240` one-time-migrates `scheduler_settings.json` into the KV store — all grep-verified.
- `POST /api/wiki/pages` is `src/api/wiki.py:155`; `WikiPage(` only at `src/wiki/track.py:47` (confirmed).
  The wiki and law tables live in the CORPUS file: `class WikiPage` `src/database/models.py:2124`,
  `WikiRevision` `:2173`, `LawDocument` `:2227`, `LawRevision` `:2285`. The one keyed path:
  `src/database/connect.py:158` (`OO_DB_PLAINTEXT`), `:196` (`PRAGMA key`), `sqlcipher3` at `:163` / `:219`.
  The member hook: `src/backup/artifact.py:154`, `src/backup/folder_backup.py:161` / `:540` — grep-verified.
- Hardware is already read locally: `src/config/memory_budget.py` (`psutil.virtual_memory` `:97`,
  `os.cpu_count` `:259`), `src/config/machine_floor.py` (three-state `below`),
  `src/database/maintenance.py:1594` (`shutil.disk_usage`), `src/api/scheduler.py:105`
  `status["machine_floor"]`. The reference VM is 2 cores / 3.5 GB (sheet VERIFIED). Settings has NO
  "Storage" subtab (`src/static/index.html:1471–1481`: Graphics · General · Cards · AI · Wikipedia ·
  OpenStreetMap · Agenda · Data & backup · Advanced); the corpus window's "Database & storage"
  (`data-tab="storage"`, `:532`) is another surface; `<dialog id="wiki-tc">` is `:3101`.
- `simplemma>=1.1` is in the `analysis` extra (`pyproject.toml:147`; S04-06 moves it); pyosmium is 0.5; the
  SSE client is S04-09's — this slice adds NO dependency. `tests/fixtures/` holds only `law/` and `pdf/`.
  The socket-guard proof: `src/ingest/airplane.py:259` + `tests/test_airplane_socket_guard.py`.

## 3. Slices — what to build, in order

### S1 — `src/versioned/`: the substrate, wiki adapter first (Q1003, Q1007)
- **What:** the §2 list as a package — identity, immutable baseline, a change feed with cursor and gap
  detection, budget and politeness HOOKS (the fetcher's own, never a second politeness), a revision store
  (diff vs the PREVIOUS ingested version), the latest as an Article through the real `index_article`, a
  point-in-time read, disclosure per kind; SQLite tables, nothing in DuckDB. The wiki adapter binds the
  existing MediaWiki client as its first feed on the fixture; law and OSM get an INTERFACE only.
  **Acceptance:** one fixture page round-trips baseline → change → revision → Article; point in time reads.

### S2 — One encrypted database file per lane (Q719, Q720, Q926, Q1004, Q1005 — full skeptic matrix)
- **What:** `wiki.db`, `law.db`, `osm.db` beside `corpus.db`, opened ONLY through `connect.py`'s keyed path with
  the corpus passphrase, no per-lane plaintext; ids link across files by `(lane, id)` with an integrity check
  (no cross-file foreign keys in SQLite — say so); each lane file an opt-in backup member via the hook, size
  read from the file; an absent lane file reported ABSENT, never a zero-byte lane; every member path through
  the one traversal guard (the 2026-07-10 lesson PROMPT_07 §S1 cites). **Acceptance:** the lane files exist
  encrypted with the corpus passphrase (gate); an unkeyed open fails CLOSED (`DatabaseLockedError` family).

### S3 — Lanes replace the mode; `POST /api/wiki/pages` = "pin to HOT" (Q716, Q1020)
- **What:** extend `_LANE_KINDS` so press, wiki, osm, law, hazards and discovery run as lanes under the one
  online consent (`ensureOnline`, invariant #14), the one governor (`collect_rate_mode` / `collect_target_kbps`,
  `settings.py:63–64`) and per-lane budgets (S4); retire `mode` and `VALID_MODES` with a migration through the
  `_read_raw` precedent, exercised on BOTH stores and disclosed once (×12); keep the endpoint as "pin this
  page to HOT" (the substrate's pin flag; HOT semantics are S04-09's). **Acceptance:** the migration exercised
  on a real settings store (gate); a test anchored to the router definitions proves the endpoint survives.

### S4 — Budgets, the hardware reading, Settings → Storage (Q1006, Q1010, Q1011)
- **What:** a published table (a versioned file under `configs/`, named in the PR) of per-lane budgets sized
  for the 2-core / 3.5 GB VM; cores, RAM and free disk read at boot through the existing modules (no network,
  three-state when unreadable); budgets PROPOSED, the reading SHOWN, power users raise them; per lane: size
  (measured), budget, growth arithmetic from the lane's OWN measured bytes over time (absent with a reason
  when unmeasured, never a projection), disk left; ×12, caveats visible, the method in the hover (#17).
  **Acceptance:** Chromium record in en / fr / ar; a node test that an unmeasured rate renders no figure.

### S5 — Transport per lane, and the CI fixtures (Q1014, Q1018)
- **What:** each lane's transport line in the consent hover; a lane whose transport is unavailable WAITS with
  a named reason — never Tor → clearnet; every lane fetch refused under the kill switch by NAME; any new host
  in `docs/SECURITY.md` + the hover in the same diff (Q1001). Fixtures under `tests/fixtures/`: a synthetic
  wiki edition, a synthetic OSM extract (synthetic geometry and tags only; `PROVENANCE.md` says so), a
  synthetic jurisdiction; the wiki pipeline runs end-to-end in CI with the socket guard armed; S04-10 consumes
  the jurisdiction, 0.5 the OSM. **Acceptance:** no clearnet socket attempted; green with zero resolutions.

### S6 — The Living sources view (Q1016)
- **What:** one view for wiki / law / OSM — timeline of changes, diff, coverage, freshness, budget — through
  `ooSubtabs` (invariant #18), counts and methods, never verdicts; replaces `#wiki-tc`. Propose a MAIN TAB
  (the gate row's reading of the missing NOTE), ask in the PR body, keep the renderer reusable as a Home
  family; ×12, caveats visible. **Acceptance:** Chromium record; the modal gone; the sidebar roster test in
  `tests/test_repo_invariants.py` extended only after the maintainer's word.

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), each run separately with its exit code captured; ratchet numbers
from `ci.yml` (grep-verified: `--max-untranslatable 470`, `--max-unkeyed-t-calls 231`); `node --check` on
every touched script block; the three i18n gates for every new string; the whole-tree guard set after every
file addition; the full skeptic matrix on S2 (a lane file is never created, opened or deleted through any
path but the keyed one; a hostile member name is refused on verify AND restore); mutation-check every guard
by name; the socket-importer ratchet (`tests/test_network_consent.py`); the fixtures under the airplane
guard; the NAMED kill-switch refusal and Tor-wait fixtures; the migration on both stores; the Chromium
click-through record (Q1128 = a) for Settings → Storage, the Living sources view and the hover's transport
lines in en / fr / ar; the `shipped.csv` numstat + duplicate scan.

## 5. Operator steps

1. On the maintainer's machine, upgrade an existing encrypted install: the lane files appear beside
   `corpus.db`, open with the SAME passphrase, and an app-stopped folder copy of the data folder (lane files
   included) restores. Artifact: the folder listing + the unlock record. `not-measurable-here`.
2. The click-through of the two new surfaces and the hover (Q1128 = a), recorded per surface.
3. The NOTE Q1016 asked for (main tab or Home family) — the PR body asks; the answer is recorded in
   `OPEN_QUEUE.md` and `RULINGS_INDEX.md` in the turn it is given.

## 6. What this slice may not decide

- **Q1016's placement** — no NOTE; the brief proposes a main tab and asks; invariant #2's roster grows only on
  the maintainer's word.
- **The legacy rows** — whether `wiki_pages` / `wiki_revisions` / `law_documents` / `law_revisions` MOVE into
  the lane files in 0.4, or the substrate's tables start there while the legacy tables stay read-only until
  S04-09 / S04-10 retire the polling paths. Design note: the second shape; the PR body states the choice.
- **The `mode` migration's mapping** for installs whose persisted mode is not `rss` — design note: every lane
  the old mode implied ON and press ON, because Q716 says "beside".
- **Where "Settings → Storage" lives** (a new subtab or the "Data & backup" panel; invariant #8 applies) and
  **when a lane file is created** (design note: at first enablement; absent is reported absent).
- **The OSM lane** (0.5; Q823 ⛔), the columnar store's future (Q1009 ⛔), per-lane numbers beyond the table's
  shape (Q707's 20 GB is S04-09's); the gate row's *design note* on Q1140 binds nobody.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.4_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every ruling in §1 in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
