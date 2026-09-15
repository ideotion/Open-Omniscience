# S06-05 — Help's body ×12, the first tranche · 0.6, `RELEASE_0.6_GATE.md` row E

> **Scope:** the translated Help drafts under `docs/i18n/<lang>/<file>`, the `/api/docs` list and
> `/api/docs/{slug}` serving seam (`src/api/main.py`), the Help reader in `src/static/app-settings.js`
> (`loadDocs` / `openDoc`, the banner), the locale JSON for the new chrome strings, a docs-translation test.
> Must NOT touch: the English originals' substance (they stay authoritative), the legal documents
> (`docs/legal/`, their own ×12 pipeline and `tests/test_legal_documents.py`), the Markdown renderer's
> performance (the 2026-09-08 audit's F1 finding — a separate slice, not folded in here).
> **Implements:** Q1122 (placement: «proposed staging 0.6 -> 0.8»).
> **Gated on:** nothing in 0.6; the tranche staging is a *proposed placement* — follow it unless the
> maintainer moves it in the gate's §3. The GUI-gallery precedent (CLAUDE.md invariant #30: AI-drafted,
> flagged for native review) is the pattern.
> **Sequencing:** independent of rows A–D; tranche 1 in 0.6, the remainder owed complete by 0.8 (S08-02).

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then Q1122 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's §12 block for
it. Grep the tree before building anything — the sheet's anchors were verified at `main`@`bebcef4` on
2026-09-12 and may have moved.

## 1. The rulings this slice implements — verbatim, by ID

- **Q1122** — **(b)** «(b) Translate the 167,022-character body ×12» [placement note from the JSON:
  «proposed staging 0.6 -> 0.8»]. The sheet's (a) — an English-by-design exception with a translated banner
  — was NOT chosen, so the «every user-facing string ×12» non-negotiable stands unamended and the body is
  translated (the OPEN_QUEUE head entry, 2026-09-15, records the choice as made knowingly: ~2 M characters,
  AI-drafted, flagged for native review like the GUI-gallery precedent).

## 2. Where this stands in the tree — the staleness guard, with anchors

- grep-verified in this brief: `src/api/main.py:2557–2609` `_DOCS` lists TEN slugs — `user-manual`,
  `quickstart`, `ethics`, `governance`, `security`, `design`, `roadmap`, `architecture`, `contributing`,
  `changes` — the gate row's *proposed* staging said «the eight Help documents» until 2026-09-15, when this
  finding corrected it to ten in the row and its §3 log; stage from the tree (the staleness guard runs both ways).
- `src/api/main.py:2619` `_doc_path` and the `get_doc` docstring (`:2645–2652`): `?lang=fr` serves
  `docs/i18n/fr/<file>` when a translation exists, falls back to English otherwise, and the `X-OO-Doc-Lang`
  header states which was served; `list_docs` returns a `translated` flag per slug. **The serving seam is
  VERIFIED-PRESENT — do not rebuild it.** `ls docs/i18n/*/` — `docs/i18n/fr/QUICKSTART.md` is the ONE
  translated draft in the tree today (1 of the 10 × 11 = 110 owed).
- `src/static/app-settings.js:28–52` `loadDocs()` / `openDoc()`: opens `user-manual` by default, renders the
  banner «Machine-drafted translation — the English original is authoritative. Found a better wording?
  Improve it on the project page.» as a template literal — check whether it is keyed; the unkeyed-t-calls
  ratchet sits at 231 (`ci.yml:209`) and the untranslatable ratchet at 470 (`ci.yml:191`), both zero slack.
- The 167,022 figure is the 2026-09-08 visual audit's measurement of the rendered Help
  (`docs/audit/ui-visual-2026-09-08/findings.csv:127`: 3,755 DOM nodes added, 653.7 ms task duration — the
  most expensive tab switch, 5–10× the next); `wc -c docs/USER_MANUAL.md` = 180,594 bytes today (bytes, not
  characters; the nine other documents I could size total 276,578 bytes). Re-measure per document, in
  characters, before staging the tranches — the ~2 M the gate quotes is the body only.
- `docs/ledger/LESSONS.md:3512` «A MIXED-LANGUAGE DOCUMENT OWES ITS READER THE REASON …»: a document states
  its own coverage (translated of total) above the first figure, computed after the body. `LESSONS.md:8582`:
  the ×12 claim is verified by switching the locale live, «instead of asserted from the fact that the keys
  exist». `tests/test_legal_documents.py::test_documents_endpoint_marks_translation` (grep-verified) is the
  precedent for a translated-documents test; `docs/legal/` carries eleven language directories.

## 3. Slices — what to build, in order

### S1 — The tranche plan, from the tree
- **What:** three tranches, most-visited first (the *proposed* staging): tranche 1 = `user-manual` (opened
  by default — the most-visited by construction) + `quickstart` (one `fr` draft exists); tranches 2–3 = the
  remaining eight, owed by 0.8. Each document ×11 (English is the original), AI-drafted on the LOCAL model
  only (the loopback-only non-negotiable — never an external translation service), each draft flagged for
  native review in its banner. The plan and the per-document character counts written into the gate's §3.
- **Why (ruling):** Q1122 = b; the placement note; invariant #30's precedent.
- **Acceptance:** the tranche list in the gate's §3 with measured sizes; the PR body names which documents
  shipped and which remain.
- **May not decide:** the tranche membership beyond the proposal (the maintainer may move it).

### S2 — The coverage banner on every served document
- **What:** the banner keyed ×12, stating: the served language, «machine-drafted — English is
  authoritative», and the document's translated-of-total figure (sections or characters, the unit named),
  computed from the document AFTER the body is loaded (the lesson: read the report before composing the
  line). The number's grouping stated as English if the shared formatter is not used.
- **Why (ruling):** the informed-consent non-negotiable (caveats visible by default; ×12); `LESSONS.md:3512`.
- **Acceptance:** the banner renders the figure on every document in every locale; the English original
  shows no banner (served = en).
- **May not decide:** the renderer's performance fix (audit F1) — recorded, not folded in.

### S3 — The translated-documents test
- **What:** for every slug in `_DOCS` and every locale of the twelve: either `docs/i18n/<lang>/<file>`
  exists and is UTF-8 Markdown with the same heading skeleton as the English (anchors resolve — the
  omnibar's Help-content group lands on headings, `app-settings.js:45–49`), or the gap is listed; the
  `X-OO-Doc-Lang` header is truthful; a translated-of-total ratchet per tranche that may never fall.
- **Why (ruling):** the gate row's «the tranche's documents pass … and a live locale switch shows them»;
  the «keys exist ≠ ×12» lesson.
- **Acceptance:** the test exists, is mutation-checked (delete one heading in one draft → it reddens by
  name), and rides the whole-tree guard set.
- **May not decide:** a native-review gate (flagged, never a merge condition — the precedent).

### S4 — The live locale switch, recorded
- **What:** Chromium in the sandbox: open Help in each of the twelve locales, record the served language
  per document and the banner's figure; `ar` in RTL; the record in the PR body.
- **Why (ruling):** Q1128 = a; `LESSONS.md:8582`.
- **Acceptance:** twelve records; then the maintainer's pass.
- **May not decide:** anything about the Help chrome's second navigation system (the 2026-09-08 audit) —
  S05-09's shell work, not this slice.

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), separately, exit codes captured — and the fact that the three
i18n gates compare locale JSON and chrome, so they CANNOT see a translated Markdown document: gate 1 green
is no evidence about the drafts; S3's test is the check. Plus: `node --check` on the touched script block;
the three i18n gates for the banner strings; the whole-tree guard set (`tests/test_utf8_file_io.py` reads
every new file); the twelve-locale Chromium click-through record of §3 S4; the per-locale render cost of
Help measured once (CJK and Arabic bodies differ in length — record, do not fix here).

## 5. Operator steps

1. The maintainer decides whether and when a native review happens per language (flagged in the banner;
   not a gate) and may move the tranche staging in the gate's §3.
2. The click-through pass on Help in the twelve locales.

## 6. What this slice may not decide

- **The tranche membership and the 0.6 → 0.8 staging** are *proposed placement* (the planning session's),
  not a ruling — and the gate's «eight» is corrected to the tree's ten in this slice's PR.
- **Whether `changes` (the changelog) counts as Help body** to translate: the ruling says «the body»; the
  tree serves ten documents — state the decision in the PR, do not silently drop one.
- **The translation engine and its quality bar** — local LLM only (ruled by the non-negotiables); no bar
  is ruled; the native-review flag is the honesty layer.
- **The Help renderer's cost** (audit F1) and the omnibar's indexing of translated drafts — separate slices.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.6_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every ruling in §1 in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
