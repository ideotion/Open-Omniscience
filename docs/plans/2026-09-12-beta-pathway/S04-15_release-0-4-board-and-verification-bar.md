# S04-15 — The release ritual and the allowlist · 0.4, `RELEASE_0.4_GATE.md` row V

> **Scope:** `.github/workflows/release.yml` (how the notes are produced), a generator under `scripts/` that
> reads `docs/ledger/shipped.csv`, the no-telemetry re-check line in the notes, the board's rows D / E / F
> statuses in `RELEASE_0.4_GATE.md`; the session environment's egress allowlist (an operator setting outside
> the tree). It must NOT: push a tag, create a release in the GitHub UI, edit the version, merge, or change
> the three lanes.
> **Implements:** Q111, Q114 ⛔ = a, Q117, Q1128; the gate row also cites Q116 (not in this slice's JSON —
> quoted below from `RULINGS_INDEX.md`).
> **Gated on:** the `v0.3.0` tag (row G, `S03-01`) is where the ritual is first exercised; the allowlist is
> the maintainer's environment setting; nothing PENDING.
> **Sequencing:** the generator should exist before the next tag it serves; the allowlist before any slice
> whose live half reads `not-measurable-here` (S04-09, S04-10, S04-11, S04-12, S04-13).

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
own section for those questions (§2 — its VERIFIED train context; §12 for Q1128, whose context is the
register's H2 / L2). Grep the tree before building anything — the sheet's anchors were verified at
`main`@`bebcef4` on 2026-09-12 and may have moved; this brief re-checked them at `7ca142e`.

## 1. The rulings this slice implements — verbatim, by ID

- **Q111** — **(a)** «Tag + GitHub release notes generated from `shipped.csv` since the previous tag + the
  no-telemetry re-check stated in the notes (the per-release ritual already in `CLAUDE.md`).» [placement:
  per-release ritual]
- **Q114** ⛔ — **(a)** «Add them to the session environment's allowlist.» [placement: operator step: the
  session environment's allowlist] (the sheet's hosts: `www.legislation.gov.uk`, `eur-lex.europa.eu`,
  `www.gesetze-im-internet.de`, `laws.e-gov.go.jp`, `echanges.dila.gouv.fr` · `dumps.wikimedia.org`,
  `stream.wikimedia.org`, `*.wikipedia.org`, `www.wikidata.org`, `query.wikidata.org` ·
  `download.geofabrik.de`, `planet.openstreetmap.org` · `api.worldbank.org`, `sdmx.oecd.org`, `api.imf.org` ·
  `extensions.duckdb.org` · `proj.org`)
- **Q117** — **(a)** «D and E become bars; F ("the browser bar reaches a human, a second engine, or is closed
  as-is") is closed as-is with Q1128's answer.»
- **Q1128** — **(a)** «Chromium in the sandbox + your click-through = verified; Gecko stays best-effort.»
- **Q116** (gate row; index row) — **(a)** «Planning (web) + build (CLI) + verification (AppVM/Chromium), as
  today.» — nothing to build.

## 2. Where this stands in the tree — the staleness guard, with anchors

- `.github/workflows/release.yml:86–104` writes `release_notes.md` from a FIXED heredoc (title, install line,
  the SHA-256 block) — no `shipped.csv` content, no telemetry line; `:64–76` refuses a tag that disagrees with
  `pyproject`; `:110–142` is the idempotent create / upload / edit path (the `v0.2.0` UI-collision fix) —
  grep-verified. No generator exists: `ls scripts/ | grep -i "release\|notes\|changelog"` returns nothing.
  The `shipped.csv`-derived notes are VERIFIED-ABSENT.
- The tag ritual: `docs/product/RELEASE_0.3_GATE.md:882–919` §7.3 "Tag day" (CI green at the exact SHA; the
  tag cut from the maintainer's machine because the session git proxy refuses tag pushes; push the tag and
  nothing else; `release.yml` creates the pre-release) — grep-verified.
- The no-telemetry ritual is in `CLAUDE.md` ("PER-RELEASE: RE-CONFIRM THE NO-TELEMETRY CLAIM"): the socket-
  importer ratchet in `tests/test_network_consent.py` (16 socket-capable libraries) + a re-read of the
  outbound call sites, stated in the release notes; the claim lives in
  `docs/legal/POLITIQUE_DE_CONFIDENTIALITE.md` + 11 translations and `docs/USER_MANUAL.md` (grep-verified the
  file and the test exist).
- `docs/ledger/shipped.csv`: 990 rows as of 2026-09-12 (CLAUDE.md), mixed CRLF / LF, `merge=union`; rows carry
  `date · area · item · status · refs · key_paths · summary`; `refs` never keeps `PR pending` (rule (5b)).
- The board: `RELEASE_0.4_GATE.md` §1 reads D "BUILT — awaiting a run to read", E "PARTIAL", F "CLOSED
  2026-09-15"; §3 records Q117 and the exit clause (rows A–E, G–V closed on named artifacts; the notes carry
  the no-telemetry re-check). Nothing here re-decides them.
- The environment: the base working mode §6 — egress allowlisted; `pypi.org` and `github.com` pass; publisher
  hosts answer `CONNECT … 403` with `"selective": false`; the probe is `curl -o /dev/null -w '%{http_code}'
  https://<host>/` plus one host known to work; the 2026-09-07 probe of `dumps.wikimedia.org` answered `000`.
  TLS verification and `HTTPS_PROXY` are never disabled.

## 3. Slices — what to build, in order

### S1 — Release notes generated from `shipped.csv`
- **What:** a script under `scripts/` that reads `shipped.csv` in BINARY (the CRLF / LF rule), selects the rows
  "since the previous tag" by a rule the PR states (the previous tag's commit date against `date`, with the
  edge cases named), groups by `area`, and emits Markdown where EVERY line traces to a row (nothing
  summarised, nothing invented); `release.yml` prepends its output to the fixed install / checksum block and
  keeps the idempotent edit path; a repo test runs the generator on the real CSV and the current tag range.
- **Why (ruling):** Q111. **Acceptance:** the generated file for the current tree quoted in the PR; the test.

### S2 — The no-telemetry re-check, stated in the notes
- **What:** the notes carry a section naming the tree SHA, the ratchet run (`pytest -q
  tests/test_network_consent.py`, exit code captured) and the outbound call-site re-read — produced by the
  session that prepares the tag, from a real run, never templated as a pass.
- **Why (ruling):** Q111 (the CLAUDE.md ritual). **Acceptance:** the section exists in the `v0.4.0` notes
  (gate) — first exercised at `v0.3.0` if S1 lands in time, else written by hand for that tag from the CSV.

### S3 — The verification bar in the notes
- **What:** a "verified surfaces" list naming, per surface, the Chromium record and whether the maintainer's
  click-through happened (Q1128 = a); rows D and E cited by their artifacts once they exist; nothing about a
  second engine (F is closed as-is).
- **Why (ruling):** Q117, Q1128. **Acceptance:** the list in the notes; no "verified" stamp without both halves.

### S4 — The allowlist (operator; nothing in the tree)
- **What:** the hosts of Q114 added to the session environment's allowlist by the maintainer; a session then
  probes `dumps.wikimedia.org` and one control host and records the HTTP status; until it is not `000`, every
  live-verification step in the other briefs reads `not-measurable-here`.
- **Why (ruling):** Q114 ⛔ = a. **Acceptance:** the probe returns an HTTP status (gate).

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), each run separately with its exit code captured. **PREMISE
CORRECTED 2026-09-15, measured while executing this brief: `scripts/` is NOT covered by any of the three
lanes** — `ci.yml` lints `src/ tests/`, types `src/` and runs bandit over `src/`, and
`scripts/ruff_ratchet.py`'s own `TARGETS` is `("src/", "tests/")`, so a generator under `scripts/` is seen by
none of them (67 files there carry 23 blocking-class `F,B` findings and 81 advisory ones that no gate
reports). Run the three tools on the new file BY HAND and say so; the coverage gap is recorded as a finding
in `LESSONS.md`, not fixed here, because adding `scripts/` to a max-gate ratchet's tree changes the
population it measures. Then the whole-tree guard set after the file
addition; the generator's test on the real CSV; the `shipped.csv` numstat + duplicate-key scan; a dry run of
`release.yml`'s notes step locally (the heredoc + the generated block) with the output quoted. No app string
changes: the notes are a repository artifact, not an app surface, so the i18n gates are unaffected (say so
in the PR).

## 5. Operator steps

1. Add the Q114 hosts to the session environment's allowlist; artifact: a session's probe record
   (`<host> → <status>`, control host included). `not-measurable-here` until then.
2. On tag day (row G first, then the `v0.4.0` exit), follow `RELEASE_0.3_GATE.md` §7.3 from the maintainer's
   machine: CI green at the SHA, the tag pushed alone, the workflow's release verified against its
   `SHA256SUMS`; the notes carry S1–S3.
3. The click-through records the notes cite (Q1128 = a), one per surface.

## 6. What this slice may not decide

- **"Since the previous tag"** — the selection rule and its edge cases (rows dated before the tag but merged
  after it; rows with several PRs) are stated in the PR, revisable.
- **Where the generated notes live** — only in the workflow's release body, or also committed under `docs/`;
  the PR proposes, the maintainer picks.
- **Whether `v0.3.0` uses the generator** — depends on landing order; either way the no-telemetry line is
  written from a real run.
- **The allowlist's exact spellings** (`*.wikipedia.org` is a wildcard the environment may not accept) — the
  maintainer's environment decides; the probe record says what answered.
- **Rows A–C** (operator runs) and the version flip — other rows; nothing here touches them.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.4_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every ruling in §1 in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
