# Audit log — Open Omniscience

Append-only, chronological record of every action taken during the audit, its purpose,
and the salient observation. This is the proof trail behind every finding in
`AUDIT_REPORT.md`. Read-only audit: no source code was modified.

- **Auditor:** automated forensic review (staff-level auditor role).
- **Date:** 2026-06-08.
- **Target:** repository at `/home/user/Open-Omniscience`, branch `claude/eager-goodall-NuiEB` (HEAD `f275a76`, the merged `0.06` line).
- **Environment:** existing `.venv`, Python 3.13.12. Network treated as OFF (no live scraping/law-fetching performed). Safe/stub inputs only.
- **Defaults adopted:** non-destructive; isolated env; network off; report in English; deliverables written to repo root.

| # | Action (command / file) | Purpose | Salient observation |
|---|---|---|---|
| 1 | `git log --oneline -6`; `git branch --show-current` | Establish HEAD & branch | HEAD `f275a76` (0.06 world-law); branch `claude/eager-goodall-NuiEB`. |
| 2 | `find src tests -name '*.py' \| wc -l`; LOC counts | Inventory | 236 py files; src ≈ 31,763 LOC; tests ≈ 11,719 LOC. |
| 3 | `python --version` | Stack check | Python 3.13.12 (matches `requires-python >=3.13`). |
| 4 | `ruff check src` (rule histogram) | Static lint, whole src | ~530 findings: 213 E402, 177 F401, 72 UP035, 27 B033, 15 B904, 7 F841, … → **F-001**. |
| 5 | `ruff check src/signals src/briefing src/integrity src/annotations src/law src/awareness/emotion.py` | Lint the 0.06 code | **All checks passed** (the new trees are clean). |
| 6 | `grep … pyproject.toml`; `.github/workflows/ci.yml` | Lint/CI policy | `[tool.ruff.lint] select = E,F,I,UP,B,C4,SIM`; CI ruff step has `continue-on-error: true` (advisory); pytest blocking on 3.13 → **F-001**. |
| 7 | `ls data/ audit/ logs/`; `git check-ignore …`; `grep .gitignore` | Repo-hygiene / leakage | `data/`, `audit/`, `logs/`, `*.key`, `*.db` all **git-ignored** (no secret/DB leak) → **F-008**. Working tree holds runtime artifacts (610 KB `open_omniscience.db`, `custody_log.db`, `keys/`) → test pollution **F-004**. |
| 8 | `tail audit/errors.log` | Runtime errors | Repeated **real DNS/HTTP attempts** to `test-source-1.com`/`test-source-2.com` during test runs → **F-003**. |
| 9 | `grep -rln 'test-source-1' tests/`; read `tests/test_scraper.py:40-114` | Locate network-in-test | `test_scraper.py` drives legacy `scraper.scraper.Scraper`; `test_scraper_logging`/`test_rate_limiting` call `scrape_all_sources()` unmocked → **F-003**. |
| 10 | `grep -rln 'scraper.scraper' src/api src/ingest src/scheduler` | Is legacy scraper live? | **No live references** — `src/scraper/scraper.py` is dead w.r.t. the running app → **F-003**. |
| 11 | `sed -n '170,176p' src/scraper/scraper.py` | Robots posture (legacy) | `return True  # Assume allowed if robots.txt is unreachable` → robots **fail-OPEN** in dead code, contradicting the project's fail-closed claim → **F-003**. |
| 12 | `grep utcnow`/`except: pass`; `grep -rln quarantine src/` | Anti-pattern scan | `datetime.utcnow()` = **0** in src; no `except: pass`; **quarantine not imported** by live code → **F-008**. |
| 13 | seed-count `grep` + `grep -c name: configs/*.yml` | Doc-fidelity (counts) | `sources.yml` = 1905 raw entries; spectrum 278; legal 51. README "~1,780" now understates the default seed → **F-007**. |
| 14 | repro script: string vs int sort of `{"2","11"}` | Verify suspected bug in 0.06 | `sorted(m)[0]="11"` ≠ `sorted(m,key=int)[0]="2"` → key mismatch in `story_prominence` novelty path → **F-002 (Verified mechanism)**. |
| 15 | `python -m pytest -q` (full suite) | Dynamic verification | **691 passed, 6 skipped** in ~123 s (exit 0). |
| 16 | `python -m pytest -rs` (skip reasons) | Coverage honesty | 6 skips = optional deps absent: pqcrypto/ML-DSA (×2), opentimestamps (×3), 1 live-OTS opt-in → PQC hybrid path unexercised → **F-006**. |
| 17 | `_DOCS` file-existence check (src/api/main.py) | Doc-fidelity (in-app docs) | All 12 registered in-app docs exist on disk (USER_MANUAL … LAW, BRIEFING, INTEGRITY, ANNOTATIONS) → **F-008**. |
| 18 | `ls scripts/bootstrap.sh`; `Makefile`; `pyproject [scripts]` | Doc-fidelity (entrypoints) | `scripts/bootstrap.sh` present (README ref OK); Makefile targets complete; console entry `open-omniscience = src.api.main:main`. |
| 19 | secret scan `grep -rnE '(password|secret|api_key|token)=…' src/` | Security | **No hardcoded secrets** in live src → **F-008**. |
| 20 | `python scripts/verify_evidence.py` (no args) | Doc-fidelity (runnable example) | Prints usage — the documented **offline evidence verifier exists and runs** → **F-008**. |
| 21 | `grep corpus_actors/story_prominence/near_duplicate_clusters src/briefing/producers.py` | Footprint | Briefing refresh runs the near-dup pass **≥2× over the same recent-news set** (echo_chamber + lonely_signal) + once over law docs → **F-005**. |
| 22 | `alembic upgrade head` on a temp DB (prior turn, re-confirmed) | Migration health | `d4e5f6a7b8c9 → e5f6a7b8c9d0` clean; `law_documents`/`law_revisions` created → **F-008**. |

**Not performed (out of scope / network off):** live fetches of the curated legal
`documents:` URLs (so their current liveness is **unverifiable** here → **F-010**); the
ML-DSA hybrid-signature path (pqcrypto not installed → **F-006**); any UI accessibility
audit of the HTML beyond static reading; a full read of all 236 modules (prioritised the
0.06 surface, entry points, security/ethics-sensitive paths, and doc-fidelity).
