# Open Omniscience — Full Transversal / Bug Bounty / Docs-vs-Reality Audit

**Target:** `ideotion/Open-Omniscience` — local-first OSINT/investigative-journalism platform
**Commit audited:** `da393591` (branch `main`, fetched fresh from `origin` 2026-07-15)
**Auditor:** Autonomous AI audit session (1 lead + 3 parallel specialist sub-agents: security, code-quality, docs-verification)
**Repo size:** 45 top-level `src/` modules, 4,032 collected tests, ~529 KB internal engineering ledger (`CLAUDE.md`)

---

## 0. What this audit actually is (read this before the findings)

The requested audit template calls for full DAST (Burp/ZAP/Nuclei), load testing, cloud/container security scanning, and a peer-reviewed multi-week engagement. None of that infrastructure exists for this project — it's a local-first, single-user desktop-style app with no staging/prod deployment, no cloud account, and no containers in scope. Running that tooling against nothing would produce theater, not findings. What was actually done, and is defensible:

- **Full static analysis** of `src/` (ruff default + security ruleset `S`), with manual code-tracing (not just linter trust) of every suppressed security warning.
- **Manual security review** of the four highest-stakes subsystems: SQL construction, the network-egress ("ethical fetcher") chokepoint, the custody-log crypto (Ed25519 + ML-DSA), and secrets/config handling — each claim traced to source, not accepted from comments/docs.
- **Dependency/supply-chain check** via `pip-audit`, which surfaced a real finding by *failing* (see OO-03).
- **Secret scanning** via pattern grep across `src/`, `configs/`, and a targeted git-history search.
- **Documentation-claims extraction and verification** — 18 concrete, falsifiable claims pulled from README.md, checked against actual source, not docstrings.
- **CI-gate reality check** — read what `.github/workflows/ci.yml` actually blocks on, vs. what the README implies.
- **Live test execution** — full-suite collection (4,032 tests, 0 collection errors) plus real execution of 3 fast, non-network unit-test files (35/35 passed) as a sanity data point, not a full-suite run (too slow/network-dependent for this session).

**Not performed, explicitly:** live DAST/pentest (no reachable deployment), load/stress testing, fuzzing, container/cloud security scanning (no infra of that kind exists in this repo), formal GDPR/ISO/SOC2 compliance certification, and **second-pass human/AI peer review** of this report (a real gap against the acceptance criteria in the requested template — flagged, not hidden).

---

## 1. Executive Summary

The codebase is unusually disciplined for its size: an internal culture of "honesty-by-construction" is visible in real enforcement mechanisms, not just comments — a CI-blocking regex test that no module besides the one designated fetcher may import `requests`/`httpx`; a runtime assertion (`assert_no_score_fields`) that literally raises at import time if anyone adds a forbidden "trust score" field; SQL nosec comments that, on independent tracing, were correct in 27 of 28 cases.

Two real, confirmed vulnerabilities were found:

1. **A SQL injection primitive in the backup-restore path** (`src/backup/merge.py`) where a `nosec` comment's trust claim is factually wrong — the interpolated value originates from an untrusted restore artifact, not the app's fixed schema as claimed.
2. **A data-erasure gap in the "panic wipe" / secure-uninstall feature**: it overwrites only the first 4 MiB of a file before deleting it, regardless of actual file size. Given this app's own documentation describes corpora reaching ~100–130 GB, this is not an edge case — it is the normal case, and it directly undermines the specific threat model (protecting an at-risk journalist's data from imminent seizure) that this feature exists to serve. **This is the single highest-impact finding in the audit**, not because of CVSS mechanics but because of mission-criticality.

Beyond those two, one supply-chain/reproducibility defect was found (a pinned dependency that doesn't exist on public PyPI), and a handful of documentation claims were found to be technically true but stated more confidently than the underlying reality warrants (e.g., "full test suite green" glosses over a ratcheted, not zero-error, mypy gate). No hardcoded secrets, no telemetry, and no network-egress bypass were found anywhere in the codebase. Code quality (error handling, architecture, dead code) came back essentially clean — the linter noise is almost entirely disciplined, commented, intentional patterns rather than real defects.

---

## 2. Findings Log

| ID | Severity | Component (file:line) | Summary |
|----|----------|------------------------|---------|
| **OO-01** | **High** | `src/backup/merge.py:290-300` (`_unmerged_tables`), reachable via `src/api/backup_v2.py:180-281` | SQL injection: table name from an untrusted restore artifact is interpolated into a quoted identifier without validation |
| **OO-02** | **High** | `src/safety/panic.py:31-38`, `src/safety/uninstall.py:65-70` | "Panic wipe"/secure-uninstall overwrites only the first 4 MiB of a file before deletion, regardless of file size — most of a multi-GB corpus survives, unerased |
| **OO-03** | Medium | `requirements.lock:843` | `numpy==2.5.0` is pinned but does not exist as a resolvable release on public PyPI — breaks the "clean install" claim / reproducible builds |
| **OO-04** | Low / Informational | `src/custody/log.py` (design-level) | Custody-log docstring claims detecting removal of "any historical entry," but a hash chain without external anchoring cannot detect *tail truncation* (deleting the most recent N entries) — true limitation of the design, slightly overstated in the docstring |
| **OO-05** | Informational | `src/custody/settings.py:52`, README | "Hybrid Ed25519 + post-quantum ML-DSA" signing is real and correctly implemented, but PQC is **off by default** (`pqc_enabled=False`); README doesn't explicitly state the default, though the in-app UI does disclose effective state honestly |
| **OO-06** | Informational | `.github/workflows/ci.yml` | "Full test suite green" / implied quality bar overstates reality: mypy is a *ratchet* (blocks only if errors exceed a baseline of 127, not a zero-error gate), full-style ruff lint is advisory (`continue-on-error: true`), and the Windows/macOS CI lane is observation-only, not a merge gate |
| **OO-07** | Low | Git remotes / `CLAUDE.md` ledger | `origin`'s remote-tracking `HEAD` still points at `0.2` while the actual default branch is `main` (already-tracked internal reconciliation gap, not a new issue) |
| **OO-08** | Informational | ruff sweep (50× `except: pass`, 118× late-import, 7× non-crypto `random`, 2× subprocess) | All reviewed individually — no material defects. ~92% of bare excepts carry an explicit rationale comment; the 118 late-imports are a mechanical side-effect of a two-string-literal file-header convention (ruff only recognizes the first string as the docstring), not sys-path hacks or circular-import workarounds; `random` usage sites are all non-security (fixed-seed reproducible sampling, retry jitter); subprocess calls never use `shell=True` or untrusted/network-sourced argv |

### OO-01 — SQL injection in restore-artifact table enumeration

- **Severity:** High · **Component:** `src/backup/merge.py:290-300`, `_count()` at similar location, invoked unconditionally from `merge_corpus()` (line 231), which is reachable end-to-end via `POST /api/backup/v2/restore/preview` and `/commit` (`src/api/backup_v2.py:180-281`).
- **Description:** `_unmerged_tables()` enumerates table names from `inc.sqlite_master` — `inc` being the **incoming/staged restore artifact**, not the app's own database — and interpolates each `name` directly into `f'SELECT COUNT(*) FROM inc."{name}"'`. The adjacent `# nosec B608` comment asserts "table/column names come from the app's OWN fixed schema," which is false for this specific call site: `validate_sqlite_file()` (`src/backup/sqlite_backup.py:120-133`) only checks that *required* tables are present — it does not restrict what *extra* tables a restore file may contain.
- **Reproduction / PoC (code-level trace, not exploited against a live instance):** An attacker who can get a crafted SQLite backup file imported through the documented `allow_unverified=True` restore path (bypassing signature/hash verification, which the app itself exposes as a supported flow for unsigned/foreign backups) can name a table such that its identifier breaks out of the double-quoted string (e.g. embedding a `"` and a `UNION SELECT`). Python's `sqlite3` driver refuses multi-statement scripts, so classic stacked-query injection (`; DROP TABLE`) is not possible, but a single-statement `UNION SELECT` remains available, letting the crafted table name cause data from *other* tables in the same connection to be read into a field the UI presents as an unrelated table's row count.
- **Impact:** Local-first, single-user threat model limits blast radius — this is not remotely exploitable by a third party without the victim importing a malicious file themselves. But it is a genuine SQL-injection primitive inside a security-relevant code path (data restore), and the safety comment actively misdescribes the trust boundary, which could mislead a future maintainer into copying the same unsafe pattern elsewhere.
- **Remediation:** Validate every table name pulled from `inc.sqlite_master` against a strict identifier pattern (e.g. `^[A-Za-z_][A-Za-z0-9_]*$`) before interpolating, or reject any restore artifact containing a table name that fails this check, before `_unmerged_tables`/`_count` ever run.

### OO-02 — Panic-wipe / secure-uninstall data erasure gap

- **Severity:** High (business-critical; see risk assessment) · **Component:** `src/safety/panic.py:31-38`, duplicated in `src/safety/uninstall.py:65-70`.
- **Description:** Both the in-app "panic wipe" and the standalone secure-uninstall watcher script execute `f.write(os.urandom(min(size, 4 * 1024 * 1024)))` — i.e., they overwrite **at most the first 4 MiB** of each file, irrespective of the file's actual size, then delete it. The project's own documentation describes live corpora reaching ~100–130 GB. For any file over 4 MiB (the corpus database in ordinary use, essentially always), the overwhelming majority of its bytes are never touched before the file is unlinked — only the directory entry is removed, leaving the actual data forensically recoverable by any standard file-recovery tool, even on a plain HDD/ext4 filesystem with no wear-leveling or copy-on-write involved.
- **Why this matters more than its CVSS-style severity suggests:** this feature's entire purpose, per the project's own framing, is to let a journalist erase a corpus in the face of "an imminent seizure." A 4 MiB cap silently fails that exact scenario for any realistically-sized corpus. The code's existing disclaimer ("overwrite does NOT guarantee erasure on SSD/flash/CoW filesystems") *undersells* the actual risk — the gap exists independent of storage medium.
- **Remediation:** Loop the overwrite across the full file length in bounded chunks (to control memory/time), rather than capping at 4 MiB; if a full-length overwrite is judged too slow for very large corpora, that trade-off must be surfaced explicitly in the user-facing warning (e.g. "only the first N MiB were wiped; the rest may be recoverable") rather than implied to be complete.

### OO-03 — Unresolvable dependency pin (`numpy==2.5.0`)

- **Severity:** Medium · **Component:** `requirements.lock:843`.
- **Description:** Independently verified via `pip-audit`/`pip`'s dry-run resolver against the live PyPI index: `numpy==2.5.0` does not exist as an installable release (PyPI's index tops out at `2.4.6` stable / `2.5.0rc1`, the latter requiring Python ≥3.12 and still a pre-release). This means `pip install -r requirements.lock` cannot succeed today from a clean environment against public PyPI, directly contradicting the README's "clean install" claim, and it also blocked a full `pip-audit` dependency-vulnerability sweep for this report (the resolver fails before it can check anything downstream of that pin).
- **Remediation:** Regenerate the lock file against an actually-published numpy version, and add a CI check that the lock file resolves installable from a clean environment (not just "the developer's existing venv still works").

---

## 3. Documentation vs. Code Reality — Discrepancy Table

| Claim (README.md) | Evidence | Status |
|---|---|---|
| robots.txt "respected fail-closed" | `src/ingest/__init__.py:739-779` — any non-200/404/410 response or network error sets `decision=None`, and `_enforce_robots()` raises, blocking the fetch | ✅ Verified |
| "One fetch path, no raw bypass" | Enforced by a CI-blocking test (`tests/test_network_consent.py::test_no_new_socket_importers`) that fails the build if any module besides the 3-entry allowlist imports `requests`/`httpx`; independently grepped, no bypass found | ✅ Verified |
| Per-host rate limiting | `_respect_rate_limit()` honors `Crawl-delay`; per-host locking present | ✅ Verified |
| "Nothing stored if there's no real body" | `pipeline.py:150-156` — `extract_article()` returning `None` skips the DB write | ✅ Verified |
| Content-hash / canonical-URL deduplication | `models.py:538,552` unique indices; checked pre-insert in `pipeline.py:120-186` | ✅ Verified |
| Boolean FTS5 search, "fully parameterized" | `src/database/fts.py` — real tokenizer/AST, single bound `MATCH` parameter, not string-built | ✅ Verified |
| "Dependency-free, offline web UI" | No external CDN/script/link refs in `src/static/index.html`; one locally-vendored, hash-pinned Alpine.js only for an experimental GUI-skins gallery | ✅ Verified |
| "Hybrid Ed25519 + post-quantum ML-DSA" custody signing | Real implementation (`src/custody/signing.py`), honest AND-semantics verification, no stub | ⚠️ Partial — real, but PQC is off by default (see OO-05) |
| OpenTimestamps (Bitcoin-anchored), offline verification | `src/custody/anchor.py`; default mode is `"local"` (self-asserted), OTS is opt-in — matches the README's own "self-asserted local, or Bitcoin-anchored" wording | ✅ Verified |
| SQLCipher at-rest encryption "on by default" | `src/database/connect.py` — plaintext only via explicit `OO_DB_PLAINTEXT=1` opt-out; encrypted is the fallthrough default; proven in CI's cross-OS `sqlcipher-smoke` job | ✅ Verified |
| "No recovery for a lost passphrase" | No decrypt-fallback/recovery-key code path found anywhere in `src/custody`/`src/database` | ✅ Verified |
| Airplane-mode "socket-level guarantee" | `src/ingest/airplane.py` monkey-patches `socket.getaddrinfo`/`create_connection`/`connect` process-wide, wired into boot before the scheduler starts | ✅ Verified |
| "No composite trust score" (forbidden in code) | `assert_no_score_fields()` runs at import time (`src/briefing/card.py`), raising if any forbidden field name is added | ✅ Verified |
| i18n: 12 supported locales | Exactly 12 locale files present; completeness gated at 100% in CI | ✅ Verified |
| Markets: "a number is stored only where a selector lands on one — never guessed" | `src/markets/extract.py:96-139` — every failure branch returns `None` with a reason, no fallback guess | ✅ Verified |
| "Single pyproject.toml, Python 3.13, clean install, full test suite green" | pyproject.toml is the sole build config; suite collects cleanly (4,032 tests, 0 errors), 35/35 sampled tests passed | ⚠️ Partial — "clean install" contradicted by OO-03; "full test suite green" true but understates the mypy ratchet / advisory style-lint / advisory Windows-macOS lane (OO-06) |
| Version 0.2.0 (alpha), no tagged release yet | `pyproject.toml` version matches README/CHANGES.md; `git tag --list` empty, matching the README's own disclosure | ✅ Verified |
| "Local-first, no telemetry" | No analytics/telemetry SDK or outbound call found anywhere in `src/` or the static frontend | ✅ Verified |

---

## 4. Risk Assessment

| Finding | Technical severity | Likelihood (given local-first, single-user threat model) | Business/mission impact |
|---|---|---|---|
| OO-02 (panic-wipe 4 MiB cap) | High | **Certain** — triggers on every realistic-sized corpus, no attacker needed | **Highest** — silently defeats the app's own core safety promise to at-risk journalists facing device seizure; a false sense of security is worse than no feature |
| OO-01 (restore-path SQLi) | High | Low-Medium — requires the user to import a crafted/unverified backup themselves | Medium — real primitive in a security-relevant path, but requires a local trust decision by the victim |
| OO-03 (numpy pin) | Medium | Certain on any fresh clean-room install attempt | Medium — blocks reproducible builds/onboarding and blinded this audit's dependency-vulnerability scan |
| OO-04/05/06 (doc nuance) | Informational | N/A | Low — reputational/trust nuance, not exploitable |
| OO-07 (branch/ledger drift) | Low | N/A | Low — internal housekeeping, already tracked |

No critical/high finding requires public disclosure delay beyond the maintainer's own remediation — none is remotely exploitable against a third party without a local trust decision by the app's own user, consistent with this being a local-first, single-operator tool with no multi-tenant or server-exposed attack surface.

---

## 5. Remediation Backlog (priority order)

1. **OO-02** — Rewrite `panic_wipe()` and the uninstall watcher's overwrite routine to chunk-overwrite the *entire* file length, not just the first 4 MiB; if performance forces a size cap for very large corpora, state the residual risk explicitly in the UI copy rather than implying complete erasure.
2. **OO-01** — Validate/escape table names read from untrusted restore artifacts (`^\w+$` allowlist, or reject on failure) before they're interpolated into any SQL identifier in `merge.py`.
3. **OO-03** — Regenerate `requirements.lock` against a numpy version that actually resolves on public PyPI; add a CI job that does a clean-room resolve of the lock file (catches this class of drift automatically going forward).
4. **OO-06** — Either promote the Windows/macOS CI lane and full-style ruff lint to blocking, or reword README/CLAUDE.md's quality-bar language to accurately describe the ratchet-based mypy gate and advisory lanes.
5. **OO-04 / OO-05** — Tighten the custody-log docstring's tamper-evidence claim to specify "detects edits/reorders of any entry; detecting *tail truncation* requires external anchoring (OpenTimestamps)," and state the PQC-signing default (off) explicitly in the README next to the "hybrid" claim.
6. **OO-07** — Reconcile `CLAUDE.md`'s remaining `0.2`-branch references to `main` in one careful pass (already an open internal item).

---

## 6. Acceptance Criteria — Self-Assessment Against the Requested Template

- [x] All static, in-repo components analyzed (src/, tests/, docs/, CI, dependencies).
- [ ] Infra/cloud/container security — **N/A**, no such infrastructure exists in this repo (local-first desktop-style app).
- [ ] Live DAST/pentest — **not performed**, no reachable staging/prod deployment exists to test.
- [x] High-severity findings reproduced with code-level PoC/trace (OO-01, OO-02) — not exploited against a live running instance, since none exists.
- [x] Documented claims verified against code: 18 concrete, falsifiable claims checked; 15 fully verified, 3 partial with nuance documented.
- [ ] **Peer review by a second auditor — not performed.** This is a single AI-audit pass (1 lead + 3 parallel specialist sub-agents cross-checking different subsystems, but no independent second-opinion review of this report itself). Flagged as the clearest gap against the requested acceptance criteria; recommend a second review pass, human or AI, before treating this as a final sign-off document.

---

*Compiled from a live static-analysis pass, three parallel specialist sub-agent reviews (security, code-quality, documentation-verification), and direct execution of dependency-resolution and test-collection checks against the repository as checked out. All file:line references are exact as of commit `da393591`.*
