# Audit 17 — measurement tables — 2026-11-23

Base commit `b2f02a23e`. Sandbox: Python 3.12.14, plaintext mode (`OO_DB_PLAINTEXT=1`), synthetic corpora built through the app's own ORM (`src.database.session.init_db`, `SessionLocal`), loopback-only. Harness scripts lived outside the repo (not committed). Every number below is [MEASURED] unless tagged otherwise.

## T1 — Corpus seeding (write path, FTS triggers live) and export

| N articles | seed time | seed rate | DB size | export (`write_backup_v2`) | export rate | FTS MATCH (20 runs) |
|---:|---:|---:|---:|---:|---:|---:|
| 500 | — | — | — | — | — | — |
| 2,000 | 1.11 s | 1,800 art/s | 8.1 MB | 0.64 s | 12.8 MB/s | 0.11 ms |
| 20,000 | 16.81 s | 1,190 art/s | 70.3 MB | 2.51 s | 27.95 MB/s | 0.12 ms |

Command shape: `OO_DATA_DIR=<fresh> OO_DB_PLAINTEXT=1 python3 bench_seed.py <N> <backup.oo>` (init_db → ORM insert in 500-row chunks → `src.backup.artifact.write_backup_v2` → 20× `SELECT rowid FROM article_fts WHERE article_fts MATCH 'government AND parliament' LIMIT 20`).

## T2 — Restore of a real backup into a fresh instance (`restore_legacy_path`)

| backup | articles | wall time | of which quiesce `sleep` | result |
|---|---:|---:|---:|---|
| backup_500.oo | 500 | ≥180 s | ~180 s (timeout) | **HTTP 400 refusal**: "another job is still writing to your corpus (reindex-resume) after waiting 180 s — nothing was written" |
| backup_2k.oo | 2,000 | 158.44 s | 153.56 s (618 × 0.25 s polls) | committed; `merge_corpus` itself 0.74 s |
| backup_20k.oo | 20,000 | >570 s (run timed out) | — | not finished in the window |
| backup_20k.oo, quiesce wait neutralised (measurement-only monkeypatch) | 20,000 | **17.5 s** (1,143 art/s) | 0 | committed |

cProfile of the 2 k restore: 1,578,462 calls in 158.44 s; top entries `time.sleep` 618 calls / 153.56 s ← `threading.wait` ← `wait_for_quiescence` (`src/database/corpus_lease.py:232`) ← swap barrier (`src/backup/merge.py:10009`); `active_leases` called 619 times, each a glob+read+stat of `<data dir>/leases`.

## T3 — `merge_corpus` alone (staged copy → empty working DB, `cache_mb=256`)

| N | merge time | rate | profile note |
|---:|---:|---:|---|
| 2,000 | 13.99 s | 143 art/s | — |
| 20,000 | 12.44 s | 1,607 art/s | 11.66 s of 12.44 s inside `sqlite3.Connection.execute` (SQL-bound) |

## T4 — Post-import re-index drain (`reindex_imported_articles` / `reindex_articles`)

| N | wall time | rate | output |
|---:|---:|---:|---|
| 500 | 51.3 s / 53.5 s / 90.0 s (3 runs) | 5.6–9.8 art/s | reindexed 499–500, failed 0–1; 1,542 keywords / 40,000 mentions |
| 2,000 | 190.93 s | 10.5 art/s | reindexed 2,000, failed 0; 2,032 keywords / 160,000 mentions |

cProfile, 500-article run (90 s wall): **19,954,311 calls**; top by tottime: `lock.acquire` 57.0 s, `select.poll` 15.7 s, `posix.write` cum 43.0 s, `index_article` (`src/analytics/store.py:767`) cum 10.9 s (parent process; worker IPC dominates). [ARITHMETIC] 1,282,083 imported articles (audit 15's corpus) at the measured 10.5 art/s ≈ **34 h**; field-measured on Qubes VMs: 50–61 h unfinished (audit 16).

Separately [MEASURED]: first `reindex_imported_articles` over the imported 2 k batch ended in `IntegrityError: its text is withheld (a database driver's words)` on an `executemany` after the rows were written (second run then reported `already_certified: 2000`).

## T5 — Live-server read latency (uvicorn on 127.0.0.1:8123, 20,000-article corpus, plaintext)

| endpoint | latency | status |
|---|---:|---|
| `GET /api/health` (first hit) | 928 ms | 200 |
| `GET /api/search/omni?q=go` (2-char, first hit) | 529 ms; warm 37–42 ms | 200 |
| `GET /api/search/omni?q=government` | 253 ms | 200 |
| `GET /api/search/omni?q=government parliament election` | 442 ms | 200 |
| `GET /api/search/instant?q=government` | 24 ms | 200 |
| `GET /api/insights/trending` | 399 ms | 200 |
| `GET /api/insights/corpus-coordination` | **1,920 ms** | 200 |
| `GET /api/insights/corpus-keywords` | 147 ms | 200 |
| `GET /api/insights/leads-view` | 59 ms | 200 |
| `GET /api/insights/status` | 55 ms | 200 |
| `GET /api/timemap?q=government` | 41 ms | 200 |
| `GET /api/backup/reindex-backlog` | 27 ms | 200 |
| `GET /api/jobs` | 117 ms | 200 |

## T6 — Automated gates (all run locally at the base commit)

| gate | command | result |
|---|---|---|
| ruff blocking lane | `ruff check --select=F,B --extend-ignore=B008 src/ tests/` (ruff 0.17.5, pinned) | clean |
| ruff advisory lane | `ruff check src/ tests/` + `scripts/ruff_ratchet.py --max 432` | 389 findings (ceiling 432; ratchet notes it could drop to 389) |
| mypy | `mypy src/` | no issues in 834 files |
| bandit | `bandit -r src/ -q` | 343 findings, all LOW (B110×203, B101×37, B112×28, B105×23, B311×14, B404/B603/B607×19, B405/B606×4, B107×1); no HIGH/MEDIUM |
| pip-audit | `pip-audit==2.10.1 -r requirements.lock --disable-pip` | 6 packages, 74 advisories: pillow 12.3.0 ×42 (fix 13.0.0), pypdf 6.19.0 ×18 (fix 6.20.0–6.21.4), soupsieve 2.8.4 ×6, anyio 4.14.0 ×3, urllib3 2.7.0 ×3, certifi 2026.6.17 ×2 |
| targeted pytest | 8 test files (backup merge, volume job, security, version floors, dependency hygiene, import checkpoint, restore matrix, CI concurrency) | 138 passed + 40/40 after env fix (9 initial failures were the sandbox lacking an installed package, not repo defects) |
| grep sweeps | TODO/FIXME, pickle/eval/exec, os.system, shell=True, secret-like literals, f-string SQL, innerHTML | 3 TODOs in src; no pickle/eval/exec/os.system in runtime src; shell=True only in `scripts/analysis/`; no secret-like literals in `src/ configs/ .env.example`; 71 f-string SQL sites all `nosec`-annotated (sampled); 32 `src/static/*.js` files assign `innerHTML` |
