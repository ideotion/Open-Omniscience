# Cumulative integrity audit — 2026-07-13

**Scope:** verify that everything the project CLAIMS shipped is present + correct in the
CURRENT `origin/0.2` tree (`a25e5ca2`, S1–S6 all merged), *cumulatively* — i.e. not silently
reverted by a later merge (the #548 hazard). Read-only (this is PR #1). No code changed here;
findings are triaged ACT / PROPOSE / DEFER for the maintainer, and the ACT set is fixed in the
stacked PRs that follow.

**Claim set:** the 324 `docs/ledger/shipped.csv` rows + the `docs/ROADMAP.md` ✅ rows + the
merged-PR history they reference.

---

## Dashboard

| | |
|---|---|
| Claims in the ledger (shipped.csv rows) | 324 |
| Rows with an ABSENT key_path (breadth scan) | 3 → **1 real** (a deliberate retirement), 2 false-positives |
| Named test files referenced / present | 46 / 45 (the 1 absent = the deliberate retirement) |
| Tests collected in the suite | 3553 (clean collection, no import errors) |
| Vacuous tests found (assert-True-only / pass-only) | 0 |
| Honesty non-negotiable guards present | ✅ `assert_no_score_fields`(import-time) · `install_airplane_socket_guard` · `WriterGate`/`write_lock` |
| Deep-verified high-value/high-risk claims (fan-out) | 16 (see the tables) |
| **Headline** | **The tree has HIGH cumulative integrity — no #548-style silent revert found.** The one absent artifact is a documented retirement; the seed CI-red is a swallowed-exception diagnosability bug, not a correctness regression. |

**Coverage & method (never implying more than was done):**
- **Breadth (all 324 rows, scripted):** every `key_paths` file/glob checked for existence in
  the current tree; every referenced `tests/test_*.py` checked for existence. This catches a
  reverted/never-landed artifact but NOT a subtly-wrong implementation.
- **Deep-verify (16 curated high-value/high-risk claims, agent fan-out):** each claim
  verify-against-tree (grep the artifact, read it, assess the named test for
  pass/skip/vacuous/proxy, check the invariant guard); every negative independently
  skeptic-REFUTED; only survivors kept.
- **NOT deep-verified:** the ~300 lower-risk rows beyond breadth (UI slices, i18n keying
  batches, doc slices, individual card producers) — sampled via breadth only. This audit does
  NOT claim line-by-line correctness of those; it claims their artifacts are present and the
  honesty-critical + complex + data-safety claims are deeply verified.
- **Environment:** py3.13 `.venv` (duckdb 1.5.4, cryptography, numpy, sqlalchemy; **no
  sqlcipher3** → the encrypted-store + httpfs lanes are CI-only and SKIP here, honestly). No
  network. CI-only results are marked as such, never claimed as locally-run.

---

## DELIBERATE CHOICE (absent/changed, but an intentional documented decision — no action)

| id | claim | current-tree evidence | verdict | sev | conf | disposition |
|----|-------|-----------------------|---------|-----|------|-------------|
| DC-1 | shipped.csv (2026-06-18) references `tests/test_backup_staging.py` | file ABSENT; `git log` shows it went with commit `f273050d` "Remove the size-capped single-file backup CREATE (keep restore for migration)" + `ead43db9` "stage builds on the data dir". The single-file CREATE was **retired** (ledger: unified backup, 2 GiB single-file CREATE removed); staging is still exercised by `test_stream_backup` / `test_backup_adaptive_sizing` / the volume+folder paths. | DELIBERATE (retired feature took its test) | P3 | CONFIRMED | No action. The ledger row is a historical record of when it shipped, not a live claim. |

## NOT-REACHED (a claimed artifact/path is missing from the current tree)

| id | claim | current-tree evidence | verdict | sev | conf | reproduction | disposition |
|----|-------|-----------------------|---------|-----|------|--------------|-------------|
| _(none surviving — the 2 other breadth flags were false-positives: `src/backup/merge.merge_corpus` is a `module.function` ref and the function EXISTS at merge.py:166; `AUTONOMOUS_SESSION_BRIEF_…_S1..S6` is a shorthand for the 6 files that all exist.)_ | | | | | | | |

## BUG (present but wrong / a CI-red / a diagnosability hole)

| id | claim | current-tree evidence | verdict | sev | conf | reproduction | disposition |
|----|-------|-----------------------|---------|-----|------|--------------|-------------|
| BUG-1 (seed) | The columnar CI lane `tests/test_columnar_httpfs_loader.py::test_ci_encrypted_persisted_round_trip` is RED in CI. | `secure_crypto_available()` (columnar.py:255) ends in a bare `except Exception: return False` that **swallows** the real cause — the module HAS a `_LOG` logger (columnar.py:77) but the except does not log. So when the real httpfs LOAD/encrypted-ATTACH fails on the CI duckdb, the test fails at `assert secure_crypto_available() is True` with NO visible cause. SKIPS locally (no sqlcipher3/httpfs). | BUG (diagnosability; the swallowed exception hides the named cause) | P2 | CONFIRMED (swallow) / PLAUSIBLE (root cause — not reproducible offline) | In CI with `OO_CI_INSTALL_HTTPFS=1` the round-trip asserts False-is-True. | **ACT** (Phase 3, first): surface the exception via `_LOG` + a `secure_crypto_reason()` diagnostic so the red shows WHY; then the named cause is diagnosable (likely a duckdb 1.5.x LOAD/ATTACH API coupling — see the P2.4 ledger finding). |

## FAKE (a test that asserts nothing / a proxy for the real claim)

| id | claim | current-tree evidence | verdict | sev | conf | disposition |
|----|-------|-----------------------|---------|-----|------|-------------|
| _(none found — 0 vacuous/pass-only test bodies across the suite; the deep-verify fan-out flagged none surviving refutation — see the fan-out section.)_ | | | | | | |

---

## Deep-verify fan-out — 16 high-value claims

Filled from the `cumulative-integrity-audit` workflow (verify-against-tree → skeptic-refute).
**Result: 16/16 HOLD, CONFIRMED, 0 negatives.** Every deep-verified claim is present + correct +
backed by a non-vacuous test in the current tree — no FAKE (vacuous/proxy test), no NOT-REACHED,
no surviving BUG among this set. Several agents RE-RAN the named suites (write-gate 5/5,
P0-validation 31/31) or reproduced the mechanism in-process (airplane guard); the one sandbox
failure (airplane unix-socket) was the sandbox blocking `socket()` construction, not a guard
defect (it passes outside the sandbox).

| claim id | verdict | conf | current-tree evidence (excerpt) |
|----------|---------|------|----------------------------------|
| `no-score` | HOLDS | CONFIRMED | card.py:256 runs `assert_no_score_fields(Card)` at import; a real reflective check over `dataclasses.fields` vs the banned name/fragment lists; pinned non-vacuously in test_producers_card_shapes.py (direct call + runtime `_check_no_score_keys` over every producer with a `fired>=3` floor). |
| `airplane-guard` | HOLDS | CONFIRMED | airplane.py:132 patches getaddrinfo/create_connection/connect(_ex); raises `AirplaneModeError` for non-loopback under the kill switch BEFORE the real call; loopback/AF_UNIX pass. Wired in main.py:229 (`run_deferred_startup`). Test spies prove the real call is never reached (`reached==[]`) and fire when delegation occurs. Reproduced in-process. |
| `single-writer-gate` | HOLDS | CONFIRMED | writer.py WriterGate (reentrant, depth-balanced) + `register_write_gate` on before_flush / do_orm_execute / after_transaction_end; wired on the REAL SessionLocal (session.py:143). test_write_gate_dataloss: exact-count no-loss under contention + a load-bearing isolation control. Re-ran: 5 passed. |
| `s1-p0-validation` | HOLDS | CONFIRMED | run_restore(commit=False) returns BEFORE the os.replace commit; live corpus only read; `committed==True` on a preview is a FAIL alarm; per-check verdicts pass/fail/not-measurable-here; `_summarize` is an explicit conjunction ("NOT a composite quality score"). Test monkeypatches the REAL live_db_path + asserts byte-unchanged. Re-ran: 31 passed. |
| `s2-fts-bound` | HOLDS | CONFIRMED | main.py:1057 `def search_articles` (plain def → threadpool, no loop freeze); fts.py:518 `search_ids` returns ids (final order) → only the page rows loaded (no whole-match materialization). |
| `s3-adaptive-sizing` | HOLDS | CONFIRMED | stream_backup.py `_adaptive_volume_size`: `n = sum(ceil(s/vsize) for s in per-member sizes) + reserve` — the PER-MEMBER ceil sum + reserve, NOT ceil(total/vsize); keeps N+M under the 255 parity ceiling. Matches the real emit loop. |
| `s3-httpfs-gate` | HOLDS | CONFIRMED | `_verified_httpfs_path` sha256-verifies the bundled binary vs the registry pin before LOAD-by-absolute-path; in-memory fallback otherwise; the `duckdb-httpfs-extension` pin ships BLANK; no network autoload. |
| `s4-composite-i18n` | HOLDS | CONFIRMED | i18n.js:136 `tf(s,vars)` = template lookup + `{named}` interpolation (unmatched left verbatim), exported on OOI18N; `Card.title_i18n`/`title_vars` validated + in `to_dict`; the rising template key present in all 12 locale files. |
| `s5-usgs-price` | HOLDS | CONFIRMED | `_SUPPLY_MEASURES` = {production, mine_production, reserves, net_import_reliance} only (no trade/monetary); a non-supply measure is refused; `_is_price_text` word-boundary currency detection (Europium survives); `_supply_value` strips grouped thousands. Negative-space tests hold. |
| `s5-subjectivity` | HOLDS | CONFIRMED | script guard: `_dominant_script(text)` vs the lexicon's stored script → `_gap()` on mismatch (never a fabricated density 0.0); mtime-aware cache; the gap dict carries no score field. |
| `s5-gold-builder` | HOLDS | CONFIRMED | build_and_save_gold_set: temp-write → `load_gold_set` validate → `os.replace` atomic swap (unlink+re-raise on failure), so an invalid set never lands; `_parse_grade` rejects float/bool/non-numeric loudly. |
| `s6-perception` | HOLDS | CONFIRMED | `hallucination_rate = fp/(tp+fp)` = fp/predicted; `de_us_centring` split; `place_coordinate` scored apart; no composite. Hand-computed test metrics correct; no extraction feature added. |
| `s6-producers` | HOLDS | CONFIRMED | on_the_horizon bucket `watch`, through_time bucket `context` — never `urgent`/alert; no score field; registered last (fail-safe) in `_DEFAULT_PRODUCERS`. |
| `backup-parity` | HOLDS | CONFIRMED | parity.py systematic MDS GF(2⁸) code (0x11d, Cauchy generator); `recover_volumes` re-verifies data+parity, rebuilds erased volumes, checks each vs its manifest sha256; >M raises. Exhaustive-erasure test real. |
| `streaming-backup-ram` | HOLDS | CONFIRMED | `write_parity` encodes in ~32 MiB bands (never whole volumes); run-unique emission names + atomic manifest swap + gc-after-finalize; no whole-archive materialization in the parity/checksum stages. |
| `s2-guard-coverage` | HOLDS | CONFIRMED | `guarded_read` (heavy.py:208, cap + single-flight + statement_deadline) + `_deadlined` (insights.py:103, + TTL cache) are APPLIED (not just defined) across the raw insights endpoints + cards + link_analysis; the omnibar degrades to an honest empty-with-note. |

---

## Per-PR / per-session index (verified present in the current tree)

- **S1** (Tier-0 release kit): `src/monitoring/p0_validation.py` + `/api/diagnostics/p0-validation*` + `docs/product/P0_VALIDATION_RUNBOOK.md` — present.
- **S2** (snappiness): `src/scheduler/maintenance.py` (idle maintenance) · `/api/articles` def + FTS bound · `docs/design/5TB_ARCHITECTURE_REVIEW.md` — present.
- **S3** (DB architecture): `src/analytics/columnar.py` (D1 loader, gated) · `rollup_serve` persisted path · `src/backup/stream_backup.py` (DB-9 adaptive sizing) · `docs/design/DB10_RETENTION_VACUUM_MEMO.md` — present.
- **S4** (product quality): `datediag` CJK probe · `kwTransHtml` breakdown · the Leads carousel · `#an` context concordance · `i18n.js` `tf()` + `Card.title_i18n` · `engine_report._generic_terms` · the wizard sources step — present.
- **S5** (rulings + instruments): `src/stats/usgs.py` · `src/analytics/subjectivity.py` + `configs/subjectivity/*.txt` · `src/analytics/gold_builder.py` · `engine_report.lemma_preview_report` · the `int`-country curation — present.
- **S6** (backlog): `producers.on_the_horizon`/`through_time` · `src/analytics/perception_eval.py` — present.

## Forward-build gaps confirmed (feed Phase 4)

- **`journal_size_limit` is set NOWHERE** (grep-verified) — WAL pragmas live in
  `src/database/session.py:94 _sqlite_pragmas` (journal_mode=WAL + busy_timeout); the WAL has
  no resting ceiling between the inter-pass TRUNCATE checkpoints (STORAGE_5TB_PLAN §3 Phase-A).
- **No per-search timing breakdown** — `search_ids` (fts.py:518) + `_query_articles`
  (main.py:935) are un-instrumented (PLANNING §4 Phase-0, measure-before-optimize).


---

## Phase 2 — triage (conservative; bias to PROPOSE)

| finding | tag | reasoning |
|---------|-----|-----------|
| **BUG-1** columnar CI-red swallowed exception | **ACT** | Objective + CONFIRMED + mechanical/reversible: a bare `except Exception: return False` that bypasses the module's own `_LOG` and hides a CI failure cause is unambiguously a diagnosability bug. Surfacing it (log + a reason() diagnostic) changes no behaviour on the success path and is fully reversible. The named ROOT cause of the CI red is PLAUSIBLE-not-CONFIRMED offline (needs the httpfs/CI lane), so the fix SURFACES it (making the red diagnosable) rather than guessing a blind code change to the crypto path. |
| DC-1 `test_backup_staging.py` absent | — (no action) | DELIBERATE retirement; staging still covered elsewhere. Historical ledger row, not a live claim. |
| all 16 deep-verified claims HOLD | — (no action) | Present + correct in the tree. |
| forward-build gap: `journal_size_limit` set nowhere | **DEFER→Phase 4** | Not a defect (a documented Phase-A delta); a safe measurement-first BUILD, not an audit fix. |
| forward-build gap: no per-search timing breakdown | **DEFER→Phase 4** | Same — a measure-before-optimize instrument (PLANNING §4 Phase 0). |

**Net: exactly ONE ACT finding (BUG-1).** No PROPOSE items surfaced (nothing needed judgment
against a deliberate choice); no DEFER-for-ruling items. The forward-build gaps are Phase 4.
The audit's headline stands: the cumulative claim set is intact.
