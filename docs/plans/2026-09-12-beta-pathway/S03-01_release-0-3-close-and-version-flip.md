# S03-01 — Close 0.3 and flip the version to 0.4.0 · 0.3, `RELEASE_0.4_GATE.md` row G

> **Scope:** `pyproject.toml` (the one version literal), the `README.md` `**Version:**` line and its "latest
> tagged release" note, `docs/CHANGES.md`, `docs/product/RELEASE_0.3_GATE.md` §1/§3 (row 5's status, the tag
> record), `docs/product/RELEASE_0.4_GATE.md` §3 (row G), the ledger. Must NOT touch: any code path, any test,
> the tag itself (a session never pushes, moves or deletes a tag), `.github/workflows/release.yml`, the row-5
> criteria.
> **Implements:** Q109.
> **Gated on:** the operator — row 5's run (the 0.3 gate §7.1) and the maintainer's word on the tag the remote
> already carries (§2). No ⛔ question is touched.
> **Sequencing:** first on the 0.4 board (the gate header: "the flip to `0.4.0` follows the tag"); every other
> 0.4 brief assumes `main` reads `0.4.0` once row G closes.

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
own section for those questions (their verified context and option lists). Grep the tree before building
anything — the sheet's anchors were verified at `main`@`bebcef4` on 2026-09-12 and may have moved. The sheet
section for Q109 is §2 (the train); the `OPEN_QUEUE.md` entries to consult are the 2026-09-15 head entry and
the 2026-07-20 "THE 0.3 CLOSE GATE" entry (`grep -n "THE 0.3 CLOSE GATE" docs/ledger/OPEN_QUEUE.md`).

## 1. The rulings this slice implements — verbatim, by ID

- **Q109** — **(a)** «Yes: row 5 (the Tier-A quarantine run, 8 articles) + the `v0.3.0` tag from your
  machine; then the version flips to `0.4.0`.» [placement note from the JSON: operator step]

## 2. Where this stands in the tree — the staleness guard, with anchors

- Sheet §2 context (VERIFIED at `bebcef4`): "0.3 measured-and-verified (closing: one open row, the Tier-A
  quarantine run + the `v0.3.0` tag from your machine) … `pyproject.toml` still reads `0.3.0`." The version
  half holds; the tag half is CONTRADICTED by the remote — the next three bullets.
- grep-verified in this brief: `grep -n '^version' pyproject.toml` → `15:version = "0.3.0"`.
- grep-verified in this brief: `git ls-remote --tags origin` → `refs/tags/v0.3.0` at
  `917e8095f8c40f5a68d974e3db1c5adb2c94ce0b`; after `git fetch --no-tags origin tag v0.3.0`,
  `git tag -l --format='%(objecttype) %(taggerdate)' v0.3.0` → `commit` with no tagger date: a LIGHTWEIGHT tag
  on the 2026-08-23 merge of PR #979 ("0.3.0: three defects the field runs surfaced, and the last row on the
  board"), an ancestor of HEAD (`git merge-base --is-ancestor v0.3.0 HEAD`).
- Read through the GitHub API in this brief (the `gh` CLI is absent in the sandbox): a release `v0.3.0`
  exists, pre-release, created 2026-08-23T12:39:48Z, published 12:42:06Z, three assets
  (`open_omniscience-0.3.0-py3-none-any.whl`, `open_omniscience-0.3.0.tar.gz`, `SHA256SUMS`) uploaded by
  `github-actions[bot]` at 13:01Z; `release.yml` run #3 on `v0.3.0` at that sha concluded `success`. Confirm
  before building on it — an API read, not a tree fact.
- grep-verified: `README.md:8` reads `**Version:** 0.3.0 (alpha — the measured-and-verified cycle; latest
  tagged release: `v0.2.0`)` — stale about the tag; `tests/test_repo_invariants.py:1860–1864` pins that
  line's number to the installed package version, and `test_version_single_sourced_from_pyproject` (`:1868`;
  grepped) pins `src.__version__` to the package metadata — the flip touches exactly these two files.
- grep-verified: `docs/CHANGES.md:5` `## 0.3.0 — measured & verified (the `0.2` cycle, version set
  2026-07-18)`; `:431` the 0.2.0 section records "Tagged `v0.2.0`"; nothing records a 0.3.0 tag.
- grep-verified: `docs/product/RELEASE_0.3_GATE.md:33` row 5 `**OPEN** — criteria **agreed 2026-08-23**; the
  pass has not been run`; §7.1 (`:799–871`) is the four `curl` commands; §7.3 (`:882–918`) "Tag day" — its
  step 4 prescribes an ANNOTATED tag (`git tag -a v0.3.0 <sha>`), step 5 "push the tag, and nothing else"; the
  §3 amendment log's last entries are dated 2026-09-07 and record no tag.
- grep-verified: `docs/product/RELEASE_0.4_GATE.md` header — "`pyproject.toml` reads `0.3.0` and stays there
  until `v0.3.0` is tagged; the flip to `0.4.0` follows the tag" — and §4 "Not in this gate: the `v0.3.0` tag
  … the version flip". `.github/workflows/release.yml:64–74` refuses a tag whose number differs from
  `pyproject`.
- grep-verified: `grep -n "v0\.3\.0" docs/ledger/shipped.csv` → no row records the tag; and
  `git rev-parse --is-shallow-repository` → `true` here, so any history search follows CLAUDE.md rule (5b).

## 3. Slices — what to build, in order

### S1 — Reconcile the record with the remote (docs-only draft PR)
- **What:** a `RELEASE_0.3_GATE.md` §3 line stating what the remote holds (the lightweight tag at `917e809`,
  the published pre-release, the green `release.yml` run — sha and URL quoted) WITHOUT changing row 5's
  status; a `RELEASE_0.4_GATE.md` §3 line for row G ("tag present on the remote since 2026-08-23; row 5's run
  and the flip pending"). `README.md:8`'s "latest tagged release: `v0.2.0`" is corrected only once the
  maintainer confirms the tag stands (§5 step 1); the number `0.3.0` on that line waits for S3.
- **Why (ruling):** Q109 = a names the tag as part of the close; the base working mode §2 ("record it as
  VERIFIED-PRESENT … fix the stale claim in the doc that misled you, in the same PR").
- **Acceptance (the named artifact):** the two §3 entries quoting the sha; nothing else in the diff.
- **May not decide:** whether a lightweight tag on a commit that predates row 5's run IS the close Q109 names.

### S2 — Row 5, from the maintainer's machine (operator)
- **What:** the four `curl` calls of the 0.3 gate §7.1 against the live instance, in order: the non-default
  `?write=true&include_prose_gate=false` start; the status poll confirming `dry_run: false` AND
  `include_prose_gate: false`; the keyword re-index; the composition read (`url_taxonomy` under `nav-soup-v2`
  — §7.1 says to expect 8 there). Then row 5 ticked in §1 with that number and a §3 line. A decline is
  recorded the same way (§7.1's own branch).
- **Why (ruling):** Q109 = a "row 5 (the Tier-A quarantine run, 8 articles)".
- **Acceptance:** the composition payload quoted in the 0.3 gate. `not-measurable-here`: a run on the
  maintainer's corpus.
- **May not decide:** nothing — the criteria were agreed 2026-08-23; only the run is owed.

### S3 — The flip to `0.4.0` (draft PR, after S2 and the maintainer's word on the tag)
- **What:** `pyproject.toml` `0.3.0` → `0.4.0`; the README `**Version:**` line (the repo-invariants coupling);
  a `## 0.4.0` section opened in `docs/CHANGES.md` in the file's own format; `RELEASE_0.4_GATE.md` §1 row G →
  CLOSED with the merge commit, plus its §3 line; one `shipped.csv` row. No tag: `v0.4.0` belongs to the 0.4
  exit clause (rows A–E, G–V), not to this slice.
- **Why (ruling):** Q109 = a "then the version flips to `0.4.0`"; the 0.4 gate header's sequence
  (pass → tag → flip, as at 0.2→0.3).
- **Acceptance:** the gate's "closes when" — the tag on the remote (already there) and `main` reading `0.4.0`;
  the merged PR is the artifact.
- **May not decide:** whether the flip may precede a row-5 run the maintainer has not made (§6).

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), each run separately with its exit code captured. Plus:
`pytest -q tests/test_repo_invariants.py` (the README coupling and the single-sourcing pin);
`grep -rn "0\.3\.0" README.md docs/CHANGES.md pyproject.toml` before and after S3, every remaining hit
explained; the numstat rule and the duplicate-key scan on `shipped.csv` (CLAUDE.md rules (5b)/(5c)); the
whole-tree guard set. Chromium (Q1128 = a): one boot of the flipped tree, one screenshot of the sidebar
version under the brand (invariant #4, `#version` filled by `loadHealth`) reading `0.4.0`, locale en — no
other surface changes and no new user-facing string, so nothing ×12 is added by this slice.

## 5. Operator steps

1. Confirm — or repudiate — the `v0.3.0` tag and release of 2026-08-23 as the 0.3 close (the tag is
   lightweight where §7.3 prescribed annotated), in a `RELEASE_0.3_GATE.md` §3 line of their own or on the S1
   PR. Artifact: that §3 line.
2. Run S2 on their machine; tick row 5. Artifact: the composition payload quoted in §1/§3.
3. Merge S3. Artifact: `main` at `0.4.0`.
4. Nothing else: no new tag now (the session git proxy refuses tag pushes; `v0.4.0` waits for the 0.4 exit).

## 6. What this slice may not decide

- The tag's standing: it exists, predates row 5's run, and is lightweight where the checklist said annotated.
  Only the maintainer says whether it IS the close or whether the pass → tag order is re-done; a session
  never moves, deletes or re-cuts a tag.
- Whether the flip may precede a row-5 run the maintainer declines to make — Q109 = a orders row 5 before
  the flip; a decline is §7.1's own legitimate branch and needs the maintainer's line, not a session's.
- The wording of `docs/CHANGES.md`'s 0.4.0 header and whether README keeps its "latest tagged release" note.
- No ASSUMPTION, no CONFLICT and no ⛔ question is touched by this slice.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.4_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every ruling in §1 in `docs/ledger/RULINGS_INDEX.md`, updated to the test or
  PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
