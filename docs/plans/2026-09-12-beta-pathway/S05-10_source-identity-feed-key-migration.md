# S05-10 — A source is keyed on its FEED: the migration · 0.5, `RELEASE_0.5_GATE.md` row J

> **Scope:** the `Source` model in `src/database/models.py` (`domain` UNIQUE today, `rss_url` nullable),
> the create-only seeder `src/ingest/seed_sources.py`, the alias-aware dedup in
> `src/discovery/cited_sources.py`, the restore-merge's `m.domain = i.domain` joins in `src/backup/merge.py`,
> the qualification overlay (`src/catalog/qualification_overlay.py`, `configs/source_qualification.yml`),
> `is_disqualified_domain` in `src/discovery/channels.py`, the citations tally in
> `src/discovery/source_trail.py`, the shadow ratchet in `tests/test_catalog_domain_collisions.py`, the
> `source` filter of `/api/articles`. Must NOT touch: the backup format version (bumped once in 0.4 row K),
> `read_artifact`'s forever-acceptance, the admission flip and the splice (0.4 row S), the catalogue's
> `lean-*` vocabulary (reported, never filtered — Q1129).
> **Implements:** Q1102 ⛔ = b (answered) — *proposed placement* 0.5, after the 0.4 format bump has been
> exercised on a real restore; the maintainer may pull it forward in the gate's §3.
> **Gated on:** 0.4 row K exercised on a real restore (the placement's reason); 0.4 row S (the identity
> predicates it changes: `enabled AND qualified`, the overlay editor). Nothing PENDING.
> **Sequencing:** data-safety-critical — never concurrent with S05-02 (the other identity migration); the
> order between rows B and J is not ruled (§6). The full skeptic matrix applies to every slice.

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
own section for those questions (their verified context and option lists). Grep the tree before building
anything — the sheet's anchors were verified at `main`@`bebcef4` on 2026-09-12 and may have moved.

## 1. The rulings this slice implements — verbatim, by ID

- **Q1102** ⛔ — **(b)** «(b) Key a source on its FEED» — the option's full text in the sheet: «— a
  migration + data-safety review reaching the alias dedup, the restore-merge joins, the overlay, the
  citations tally.» [placement: proposed placement 0.5, after the 0.4 format bump has been exercised on a
  real restore] — the sheet's context: 475 of 3,870 seeded entries are shadowed by a same-domain sibling;
  75 are language services (BBC Arabic, DW Español …) that differ only by feed path; 192 carry `lean-*`
  tags the survivor lacks.

## 2. Where this stands in the tree — the staleness guard, with anchors

- `Source.domain` is `String(255), nullable=False, unique=True`; `rss_url` is `String(500)` nullable;
  `country` `String(2)` and `language` `String(10)` (grep-verified in this brief: the `Source` class in
  `src/database/models.py`). The seeder is create-only: an entry whose domain an earlier sibling claims is
  never registered, silently (`OPEN_QUEUE.md`, register B11; `LESSONS.md` 2026-09-07 entries).
- The four reaches the ruling names, located: the alias-aware dedup at `src/discovery/cited_sources.py:111`
  ("Existing source domains for ALIAS-AWARE dedup (never re-create a known outlet)"); the restore-merge
  joins `JOIN sources m ON m.domain = i.domain` at `src/backup/merge.py:2025, 2031, 2038, 2078, 2088`; the
  overlay `load_overlay` at `src/catalog/qualification_overlay.py:93` over
  `configs/source_qualification.yml`; the citations tally `source_citation_tally` at
  `src/discovery/source_trail.py:193` with `TALLY_CAVEAT`; plus `is_disqualified_domain` at
  `src/discovery/channels.py:169` (all grep-verified).
- The ratchet: `_BOOT_SHADOWED_ENTRIES_BUDGET = 475` at `tests/test_catalog_domain_collisions.py:68`, with
  `test_the_shadowed_entries_include_real_language_losses` and
  `test_a_shadowed_entry_is_reported_apart_from_an_idempotent_skip` (grep-verified `def` names). The lesson
  behind it (`LESSONS.md`, 2026-09-07): shadowing is a property of the CATALOGUE — decided by the input's
  own first-wins rule, never from database state; and the number is captured from the production seeder,
  never from a rebuild of its inputs (494 vs 475).
- `/api/articles` filters `source` by exact domain (404 on a typo; sheet §7 VERIFIED) — ambiguous once
  several sources share a domain.
- 0.4 rows K and S are not in the tree at this brief's writing — verify both landed, and that the
  maintainer's real-restore artifact for row K exists, before the first migration line.
- Tests to extend: `tests/test_merge_ruled_identities.py`, `tests/test_merge_source_qualification.py`, the
  `tests/test_backup_*.py` / `tests/test_restore_*.py` families, `tests/test_catalog_domain_collisions.py`.

## 3. Slices — what to build, in order

### S1 — The identity design, measured first (Q1102 = b)
- **What:** before any schema change, the migration's own predicate run over the real catalogue: how many
  entries gain a row under a feed key, how many entries have NO feed (`rss_url` NULL — what keys them),
  how many domains become shared; the design of the key (the feed URL, normalised) written with those
  numbers; `domain` kept as an attribute; the shadow ratchet's budget lowered to the measured residue in
  the same PR — never raised.
- **Acceptance:** the numbers in the PR body; the residue named; the design reviewed before S2.

### S2 — The schema migration and the seeder (Q1102 = b)
- **What:** the unique constraint moves from `domain` to the feed key; the seeder registers the 475
  shadowed entries (language services and `lean-*` rows recovered); before/after row counts recorded;
  older backups restore forever — the restore path maps a domain-keyed `sources` member onto feed keys
  without duplicating (the four reaches below).
- **Acceptance:** the row counts before/after (the gate's clause); the shadowed count falls from 475 to
  the measured residue (the gate's clause); `alembic upgrade head && alembic check` green.

### S3 — The four reaches (the data-safety review)
- **What:** the alias-aware dedup keyed on the feed; the restore-merge joins re-keyed with a negative-space
  fixture (an old backup carrying two feeds of one domain must yield two sources, and a domain-keyed backup
  must not duplicate an existing feed-keyed source); the overlay keyed per feed; `is_disqualified_domain`'s
  semantics decided per §6; the citations tally proven stable across the migration by a fixture (the gate's
  clause).
- **Acceptance:** each reach has its own test and mutation check; the tally fixture is green.

### S4 — The surfaces (the `source` filter, the sources list)
- **What:** `/api/articles`' `source` filter and the sources UI distinguish feeds sharing a domain; a typo
  still 404s; every changed string ×12.
- **Acceptance:** the Chromium click-through of the sources list and a filtered search in `en` and `ar`.

### S5 — The real restore (operator)
- **What:** a real PRE-migration backup restored on the maintainer's machine, the duplicate-key scan read.
- **Acceptance:** 0 duplicates from the scan (the gate's clause; `not-measurable-here`).

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), each run separately with its exit code captured. Plus: the full
skeptic matrix — a data-loss lens and the negative-space lens on S2–S3 (a feed with no domain, a domain with
two feeds, a source with no feed, a backup from before the migration, a backup from after); every new guard
mutation-checked by name; the CI restore of 0.4 row K's fixture backup on the migrated store; the whole-tree
guard set; the numstat rule on any ledger file; `node --check`; the three i18n gates; the Chromium record.
The real restore is `not-measurable-here`.

## 5. Operator steps

1. On the maintainer's machine: restore a real pre-migration backup after the migration, run the
   duplicate-key scan → its output showing 0 duplicates (`not-measurable-here`).
2. The click-through of the sources list and a filtered search (Q1128 = a) → the record on the PR.

## 6. What this slice may not decide

- The order between rows B and J inside 0.5 — not ruled; only concurrency is forbidden.
- What keys a source that has no feed (`rss_url` NULL) — the ruling says "its FEED"; the design in S1
  proposes and asks.
- Whether `is_disqualified_domain` stays domain-level (one bad feed disqualifies its siblings) or becomes
  feed-level — not ruled; proposed with the measured consequence.
- Whether the migration needs a backup-format bump of its own or the restore normaliser absorbs it — 0.4
  row K named ONE bump for 0.4; nothing is said for 0.5; asked before building.
- Nothing about the `lean-*` scale (Q1129: reported, never filtered) or the admission flip (0.4 row S).

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.5_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every §1 ruling in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
