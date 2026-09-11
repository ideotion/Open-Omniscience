# Questions for the maintainer — 2026-09-06 repo analysis

**What this is.** Every decision the 2026-09-06 analysis found still open, in one place, each with the
context a reader needs to answer it without opening the ledger, the options as the ledger or the design
doc states them, and — where one exists — the standing recommendation. Nothing here is a new ask; every
question already exists somewhere in `CLAUDE.md`, `docs/FUTURE_DEVELOPMENTS.md` or a design doc, and the
pointer is given so the answer can be recorded where the ruling belongs.

**How to answer.** Reply inline (a number and a letter is enough — "B1: b", "D4: yes"), or edit this file.
Each answer becomes a ruling recorded in `CLAUDE.md` by the session that executes the affected prompt.
Every question names the prompt(s) it gates (the `PROMPT_NN_*.md` files in this folder).

**If a question goes unanswered,** the executing session proceeds under the *recommended default* written
beside it and records the assumption — the 2026-06-15 "always choose autonomously" ruling — EXCEPT where
the question is marked ⛔ (an irreversible, outward-facing or data-safety decision): those prompts stay
gated and the session builds everything else.

---

> ## ⚠ STATUS — verification pass completed 2026-09-11 (read before answering anything below)
>
> **This file was written on 2026-09-06 and went unmaintained.** Its 2026-09-10 banner said only A3 had
> been re-checked and carried everything else forward **unverified**. On **2026-09-11 every question in
> sections A–L was checked against the tree, one at a time**, so no later reader has to redo it. **The
> premises below are dated 2026-09-11 now, not 2026-09-06.**
>
> * **Eight are answered — do not re-ask them as posed:** A2, A3, C7, D1, D5, H1, J2, L8. The code
>   already says what each question was for. D7 is answered in half and D2 in part; both are marked.
> * **Seven carried a figure or framing that has since moved:** A4, B4, D8, H4, J1, L7, L8. (L8 is in
>   both lists: it is answered, *and* its count was wrong when written.) The tree's figure is given.
> * **The remaining 29 hold, verified.** Where the check sharpened a question — an option the question
>   never listed, or a stance the code already states — that is written under the question itself.
>
> **H2 and L2 are the same question** (is Chromium-in-sandbox plus your own click-through the
> verification bar?), asked once in each section. Answer it once.
>
> **Two corrections to this file's own framing**, both of which change what an answer would mean:
> **L9 and L10 are not oversights.** `src/ai_layer/source_tags.py:390-404` and its
> `_NON_TOPICAL_CLASSES` table state, in the code, that non-topical vocabulary is **"Reported, never
> filtered"**, with the reason (“deciding `independent` is not a topic is a taxonomy ruling a human
> makes”) and the measurement (the field run proposed one of these **once in 921 assignments**). Both
> recommended defaults there would *overturn a deliberate, reasoned position* rather than fix a gap.
>
> **The method.** Each verdict names a path and a line, never a memory of the docket — a docket line
> says what was true when someone wrote it; the code says what is true now. The verdicts:
>
> | # | verdict | what the tree says on 2026-09-11 |
> | --- | --- | --- |
> | A1 | operator | unchanged — the quarantine run and the `v0.3.0` tag are yours |
> | A2 | **answered by action** | `docs/product/RELEASE_0.4_GATE.md` exists (2026-09-09), stood up **before** the tag — the option the recommendation did *not* pick, justified in the file's own header. What is left is ratifying its rows D/E/F, which it marks as proposals |
> | A3 | answered + shipped | unchanged from the 2026-09-10 banner |
> | A4 | figure moved | `docs/FUTURE_DEVELOPMENTS.md` has **51** `## ` sections, not 50. All three duplicate pairs are still present. The (a)/(b)/(c) ruling stands |
> | B1 | holds **+ a third option** | `select_unqualified` has no `enabled` filter; `evaluate_and_stamp` writes only `status`. But `src/scheduler/runner.py` already carries a `scrape_unqualified` settings escape hatch that relaxes the runner to `status != disqualified` — **the question lists (a) and (b) and never mentions it** |
> | B2 | holds, **narrower than posed** | option (1)'s artifact already exists: `configs/stopwords_iso` + `configs/stopwords_extra`, versioned, registry-tracked (`STOPWORDS_ISO_AS_OF = "2026-07"`). So the ruling is not *whether to build* a versioned stoplist — it is whether triage-derived additions may merge **into that one** |
> | B3 | holds | `docs/audit/keyword-triage-2026-09-05-sample.csv` present; no batch-review artifact |
> | B4 | framing moved | **there is no proposals file in the repo.** `propose_kind_overrides` (`src/ai_layer/triage.py:572`) is a generator; 64,910 is a measurement recorded in a design doc. “Keep the file as evidence, build no tool” is therefore already the state |
> | B5 | operator | `configs/source_qualification.yml` absent as stated; `scripts/merge_source_qualification.py` present |
> | B6 | holds | `PATHOLOGY_ABS_FLOOR` at `src/catalog/qualification.py:42`; `high_link_density` exists in `src/analytics/source_quality.py` |
> | B7 | holds | `collect_article_stats` (`src/analytics/source_quality.py:210`) takes no window parameter |
> | B11 | holds, figures exact | 227 / 299 / 475 pinned in `tests/test_catalog_domain_collisions.py` |
> | C1 | holds **— and the code states a stance** | wiring present as listed. But `read_artifact` (`src/backup/artifact.py:649`) documents that it accepts legacy artifacts **“forever (D7)”**. The question treats removal as open; the code already committed the other way. Reconcile before answering |
> | C2 | holds | no checkpoint-interval constant anywhere in `src/` |
> | C3 | holds | `src/backup/import_queue.py:120` names C3 by name as the blocked item |
> | C4 | holds | `STORAGE_5TB_PLAN.md` §8 lists all six rulings unmarked; 3–6 unanswered |
> | C5 | holds | no rebuild op; the A/B bench that proved the mechanism was removed 2026-07-31, its ordering fact preserved at `src/database/connect.py:357` |
> | C6 | holds | no `httpfs` binaries in the tree; only `tests/test_columnar_httpfs_loader.py` |
> | C7 | **answered + shipped** | the data-location chooser is built: `src/static/unlock.html:336-560` runs a step between legal acceptance and the passphrase, against `/api/system/data-location`, `…/check` and its POST. The recommended default was taken |
> | D1 | **answered + shipped** | `src/bulletin/gate.py:41` reads `LAYER_A_REQUIRES_CAPABLE_HARDWARE = False`. **Already flipped** — the question asks for a flip that happened |
> | D2 | partly answered | `src/bulletin/introduction.py` has **both** `deterministic_introduction()` and a narrated path with a stated `fallback_reason`. “None” is out; what is left is which one an edition opens on |
> | D3 | holds | zero SMTP call sites anywhere in `src/` |
> | D4 | holds | ratification only; nothing in the tree to check |
> | D5 | **answered + shipped** | `src/static/app-diagnostics.js:1733` renders refusals in a `<details>` whose summary is the count plus a per-field shape — exactly the recommended collapse-behind-a-count-with-expand |
> | D6 | holds | mechanism built and honest (`src/llm/weights_pin.py`: three states, never-inherited); **both pin dicts are empty**. Blocked on egress, not on a ruling — see M6 |
> | D7 | **half shipped** | the probe half is done: `_probe_ots()` → `OTS_AVAILABLE, OTS_REASON` (`src/custody/timestamp.py:68,119`), and `src/custody/signing.py:80` carries the D7 rationale. The **pqcrypto 1.0 migration half is untouched** (`pyproject.toml:252` still pins `<1.0`) and is the only part still open |
> | D8 | framing moved | 485 lines as stated. `run_shape` has **eleven callers, all in `tests/test_specialisation.py`, and zero in production** — the sharper form of “nothing built” |
> | D9 | holds | only click-out links to ollama.com (`app-ai-tools.js`, `app-settings.js`); no in-app browse |
> | D10 | holds | the gate machinery exists (`src/ai_layer/perception_extract.py` active/cleared distinction); no production sweep setting |
> | E1, E2 | operator | unchanged; E2 is blocked by F1 |
> | E3, E4 | hold | nothing from either family is in the tree |
> | F1 | operator / infra | unchanged — nothing in a session can route around a proxy `CONNECT … 403` |
> | G1–G11 | hold | all product rulings. Spot-checked: G3's bloc rosters are genuinely unpopulated **with a stated reason** (`_BLOC_GAP`, `unpopulated_reason=`), not merely absent; G4/G5/G7 have nothing built; G11's `_default_strategy` (`src/stats/aggregate.py:330`) is exactly as the question describes, comment and all |
> | H1 | **answered by action** | the Observatory is **built** — `src/static/oosky.js`, `src/static/app-observatory.js`, invariant #31 in `CLAUDE.md`, Chromium-verified. The recommended default was taken |
> | H2 | holds | — and is the same question as L2 |
> | H3 | holds | `#ins-term` at `src/static/index.html:1173` and `exploreTerm()` still wired |
> | H4 | **figure moved the wrong way** | counted on 2026-09-11 with an explicit handler-name pattern: **335** in `index.html` + **278** across `app-*.js` = **613**, against the register's 590. The CSP still carries `'unsafe-inline'` (`src/api/main.py:556`). The debt grew ~4% while the question waited |
> | H5 | holds | nothing 3D is in the tree — the explorer was never built, so retiring it costs nothing |
> | I1 | holds | `src/api/ingestion.py:151`: “Credentials are used transiently (not stored)” |
> | I2 | holds | gazetteer/admin-1 priority unbuilt either way |
> | I3 | holds | `socks5h`/`socks4a` remote resolution is **detected** (`_is_remote_resolving_proxy`, `src/ingest/__init__.py:298`), but no `RESOLVE 0xF0` implementation exists |
> | I4 | holds | no `oo-netcut` anywhere in the tree |
> | J1 | figure moved | **6,312 lines / 129 routes** (register: 6,200 / 126) |
> | J2 | **answered + shipped (2026-09-07)** | `structlog` is **removed** from `pyproject.toml`, and the comment at line 92 cites “(J2, ruled on the recommended default ‘drop’)”. Zero `import structlog` in the tree. **Do not re-ask** |
> | J3 | holds | unchanged |
> | L1 | holds | `index.html:689` `data-tab="countries"` is `.active`; `app-gov-law.js:74` passes `{initial: "countries"}` |
> | L2 | holds | same question as H2 |
> | L3 | holds | the manifest's `excluded` block is documented at `src/api/diagnostics.py:3791` |
> | L4 | holds | `100/hour` ×3 in `src/config/settings.py:67-70` |
> | L5 | holds, exactly | `_SPARSE_BAR_MAX` lives in `app-corpus.js` and `app-markets.js` only; `commodityOverlaySvg` (`app-analysis.js:455`), `ringDumbbellSvg` (`app-insights.js:279`) and `ooDonut` (`app-library.js:1145`) carry no reference to it |
> | L6 | holds | `pdf = ["pypdf>=4.0"]` is still an optional extra (`pyproject.toml:165`) |
> | L7 | framing moved | `scripts/ui_clickthrough_seed.py:11` says **state A boots *without* `OO_DB_PLAINTEXT`, “so the app genuinely starts locked”**. The runner already drives an encrypted store for one state; the question is true only of states B/C |
> | L8 | **answered + shipped, and its count was wrong** | `CLAUDE.md` rule (5b) records the sweep as settled 2026-09-07 with **twelve** rows resolved, not the nine this file claims, and writes down the shallow-clone trap that nearly published ten identical wrong PR numbers. A column-aware check on 2026-09-11 confirms **zero** unresolved placeholders in `refs` |
> | L9 | holds — **but see the correction above** | `lean-*` is offerable, and the code classifies it under `_NON_TOPICAL_CLASSES["stance-or-ownership"]` while explicitly declining to filter it |
> | L10 | holds — **but see the correction above** | `_NON_TOPICAL_CLASSES` (`src/ai_layer/source_tags.py:441`) is the “~30 entries”, already enumerated and classified, and marked “Reported, never filtered” |
>
> **One trap this pass found, for whoever runs rule (5b) next.** `grep -c 'PR pending' docs/ledger/shipped.csv`
> returns **1**, and has since the sweep succeeded — the hit is the *summary text of the row that records
> the sweep*, which quotes the phrase (including the words “now returns 0”). A line-grep reports a false
> positive on its own success record. The check that works reads the **`refs` column**:
> `python -c "import csv;print([r for r in csv.DictReader(open('docs/ledger/shipped.csv',newline='')) if 'pending' in (r['refs'] or '').lower()])"`
>
> **Decisions raised after the 2026-09-06 analysis are in section M**, appended below rather than filed
> elsewhere, so there is one place to look.
---

## A. Release and process

**A1 · NOT A QUESTION ANY MORE — an operator step.** Recorded here because it is the last thing
between the tree and the `v0.3.0` tag, and because the earlier draft of this file asked it as a question.
The gate's own row body records **"agreed 2026-08-23 (row body); pass not run"**, so Tier A is signed off:
8 articles (BBC `/topics/<id>` index pages, an explicit path-segment rule corroborated by a measured 0.0
function-word density), criteria version `nav-soup-v2`. Tier B (the 451 index pages above the ≥100-word
guard) is deliberately NOT proposed — its prose is unmeasured. What remains is four operator actions, in
order: (1) `POST /api/quarantine/start?write=true&include_prose_gate=false` — **the flag is load-bearing**,
without it the run also applies the prose gate, which is a different, unagreed population; (2) re-index
("Clean up keywords") so the junk keywords go; (3) report the count under `nav-soup-v2` and tick row 5;
(4) with CI green at the SHA, `git tag -a v0.3.0 <sha>` and push **the tag only** — never create the
release in the GitHub UI (that is the collision that shipped `v0.2.0` with no assets). *(gates:
`PROMPT_01`.)* → The only thing to say here is if you have **already** run it, or if
you want to decline after all.

**A2 · Stand up `RELEASE_0.4_GATE.md` now or at the tag?** The 0.3 gate's §5 already writes the three
carried rows (3-at-scale diagnostics on the ~1M instance, row 4 committed full import with the
disqualified-source spot-check, row 7b the ≥72 h soak). → Create the 0.4 board in the same PR that closes
0.3, or wait? Recommended default: create it at the tag, starting verbatim from §5.

> **VERIFIED 2026-09-11 — ANSWERED BY ACTION, and not the way this recommended.**
> `docs/product/RELEASE_0.4_GATE.md` exists, dated 2026-09-09, i.e. **stood up before the tag** — the
> option the recommended default declined. The file argues its own case in its header ("a postponed
> data-safety demonstration nobody writes down becomes one that never happens") and separates rows
> A/B/C (carried by explicit rulings) from D/E/F (marked as this-session proposals). **What is left to
> answer is not “now or at the tag” — it is whether rows D, E and F become bars.**

**A3 · ⛔ The ledger restructure — four yes/no rulings** (`docs/design/LEDGER_RESTRUCTURE_PROPOSAL_2026-08-04.md`
§7; `CLAUDE.md` is now 1,339,174 bytes / 14,985 lines / 161 Open-queue bullets, up from 797 KB when the
proposal was written): (1) move the Open queue verbatim to `docs/ledger/OPEN_QUEUE.md`? (2) amend
protocol rule (1) as proposed in §4.2 (read the non-negotiables + invariants + lessons every session, the
queue on demand)? (3) retire SHIPPED entries out of the queue (§4.4)? (4) add the size ratchet (§4.5)?
*(gates: `PROMPT_03`.)* Recommendation on record: yes to all four.

**A4 · `docs/FUTURE_DEVELOPMENTS.md` — how far may the reality-check go?** 19 of 50 sections carry
stale "designed-only" claims, four sections are embedded historical ledgers, three pairs are duplicates
(§1/§22 Wikipedia, §35/§43 statistics, §2/§49 legacy-restore removal). Options: (a) banner-only (a status
line at the top of each stale section, duplicates cross-linked, nothing moved); (b) banner + archive the
four embedded ledgers to `docs/archive/`; (c) merge the duplicate pairs (risk: a recorded ruling lost in
the merge — §22 carries the superseding auto-track ruling). *(gates: `PROMPT_02`.)* Recommended
default: (b), never (c) — rule 5 of the protocol forbids compressing away a ruling.

> **VERIFIED 2026-09-11 — premise holds; one figure moved.** `docs/FUTURE_DEVELOPMENTS.md` now has
> **51** `## ` sections, not 50. All three duplicate pairs are still present and none of the four
> embedded ledgers has been archived. The (a)/(b)/(c) ruling is unchanged.

---

## B. Sources, qualification and discovery

**B1 · ⛔ The `enabled` vs `qualified` split** (`CLAUDE.md` 2026-07-26 item 9, still unanswered; verified
2026-09-06: `select_unqualified` at `src/catalog/qualification.py:231` has no `enabled` filter,
`evaluate_and_stamp` never writes `enabled`, and the runner at `src/scheduler/runner.py:419-426` requires
BOTH `enabled=True` AND `status == qualified`). Today ~42k disabled discovery/cited candidates are
trial-fetched over Tor for a verdict that has no collection effect. → (a) restrict trials to `enabled=True`
sources (candidates need a separate enable step first; no wasted trial fetches), or (b) let a `qualified`
verdict flip `enabled=True` (qualification becomes the Phase-2 auto-promotion — consistent with the
2026-07-20 "qualification IS the admission gate" ruling, but a real Tor-bandwidth decision over 73k
rows)? *(gates: `PROMPT_04`, which also builds the promotion frontier and the
audit view + undo either way.)* Recommendation: (b), with the existing hardware-aware per-pass budget as
the bandwidth bound and the audit view's undo as the safety valve.

> **VERIFIED 2026-09-11 — premises hold, and the question is missing an option.** `select_unqualified`
> has no `enabled` filter and `evaluate_and_stamp` writes only `status`, exactly as stated. But the
> runner already carries a **third path this question never mentions**: `src/scheduler/runner.py` reads
> a `scrape_unqualified` setting and, when it is on, relaxes the filter from `status == qualified` to
> `status != disqualified`. So the choice is not only (a) or (b) — there is an existing escape hatch
> whose relationship to both options should be settled in the same ruling, or it will quietly survive
> whichever one you pick.

**B2 · The stoplist ruling, (1) vs (2)** (`CLAUDE.md` "KEYWORD-TRIAGE REVIEW + THE STOPLIST RULING"):
(1) derive a versioned per-language stoplist into the repo, once, reviewed; (2) an auto-updating stoplist
derived from the live corpus. Recommendation on record and unchanged: (1) — a stoplist entry is a partially
irreversible corpus-wide deletion (index-time), a poisoning vector, and contradicts propose-never-auto-apply.
*(gates: the `PROMPT_05` prompt's English/French global batch.)*

> **VERIFIED 2026-09-11 — the ruling is narrower than it reads.** Option (1)'s artifact **already
> exists**: `configs/stopwords_iso` and `configs/stopwords_extra` are versioned in-repo, curated, and
> registry-tracked (`STOPWORDS_ISO_AS_OF = "2026-07"`, `src/services/stopwords.py:417`). So this is not
> a build-or-not decision. The live question is whether **triage-derived additions may merge into that
> existing file** — which is the same irreversibility argument, applied to a smaller change.

**B3 · The English (11,263) + French (881) triage proposals.** They can only enter the GLOBAL channel
(`en`/`fr` never reach the scoped channel), so each word needs cross-language review. → Review them as one
batch in a session (a 60-word seeded sample is already hand-classified in
`docs/audit/keyword-triage-2026-09-05-sample.csv`), or leave them until the (1)/(2) ruling? Recommended
default: review a seeded stratified sample per batch, ship only furniture, refuse open-class words.

**B4 · The 64,910 `kind_overrides` proposals** (measured ~50% precision) — treat as a worklist for a
future LLM-perception NER pass, or drop them? Recommended default: keep the file as evidence, build no
tool; revisit when the perception NER kinds exist.

> **VERIFIED 2026-09-11 — there is no file.** `propose_kind_overrides` (`src/ai_layer/triage.py:572`)
> is a *generator*; nothing in the repo holds the 64,910 proposals, which are a measurement recorded in
> `docs/design/KEYWORD_TRANSLATION_DISAMBIGUATION_2026-09-05.md`. The recommended default — keep the
> evidence, build no tool — is therefore **already the state of the tree**, and answering “drop them”
> would mean deleting a design-doc measurement rather than a worklist.

**B5 · `configs/source_qualification.yml` — the operator loop.** The overlay loader, adoption, export
endpoint and merge script shipped 2026-09-04; the file does not exist because a session must not write
verdicts (fabricated-by-curation). → Will you run
`GET /api/diagnostics/source-qualification-export?fmt=yaml` on each instance and
`python scripts/merge_source_qualification.py …`, and commit the result? Operator step, no session can do it.

**B6 · `PATHOLOGY_ABS_FLOOR` (0.5) — the gate's decisive criterion is unreachable** (strongest field
signal 0.211). Options recorded 2026-08-03: (a) keep 0.5 as a rare-catastrophe detector and say so in the
panel; (b) lower it with a stated new meaning; (c) add `high_link_density` (415 of 675 label hits) as a
second extraction-failure criterion. Recommendation: (c), keeping (a)'s wording. *(gates: the
`PROMPT_04` prompt's criteria slice; the data-safety-adjacent one.)*

**B11 · ⛔ What identifies a source — a domain, or a feed?** (New, raised 2026-09-07 by measuring the
catalogue rather than reading it; **recommendation corrected the same day after a skeptic pass refuted its
premise — see below**.) `Source.domain` is UNIQUE and the seeder is create-only, so entries whose domain an
earlier sibling already claims are never registered on any install, silently. **475 of the 3,870 entries a
real boot seeds**, across 299 domains — 227 of them inside `configs/sources.yml` alone, which is the only
figure the first cut of this question quoted. They are not redundant rows, and they are two different
losses:

- **Language services.** 75 shadowed entries declare a language and declare a DIFFERENT one than the sibling
  that survives. `bbc.com` carries 31 entries and the 30 that lose are BBC Arabic, Hausa, Swahili, Persian
  and the rest; `dw.com` shadows DW Arabic, Deutsch, Español and Brasil. (108 "differ" if a missing
  `language` field is counted as a value; 33 of those are absent-vs-present artifacts on shared-domain
  journal families, so 75 is the figure that carries the argument.)
- **Editorial metadata.** 220 of the losses are `sources_spectrum.yml` losing to `sources.yml`, and **192
  shadowed entries carry a `lean-*` tag the survivor does not have** — `cnn.com` loses `lean-center-left`,
  `dailymail.co.uk` loses `lean-right`. `src/catalog/taxonomy.py` defines that scale, so the political-lean
  catalogue is 79% shadowed and its vocabulary barely reaches the database it was written for.

Deleting the losers to "clean up" would delete precisely the breadth the language-equilibrium lever exists
to balance, and the editorial dimension the spectrum catalogue exists for. The loss is now counted and
ratcheted at both scopes (`tests/test_catalog_domain_collisions.py`); recovering it is the open question.
→ **(a)** leave it, with the count visible — the app collects one feed per outlet and the ratchet stops it
growing; **(b)** key a source on its FEED, which reaches the alias-aware dedup, the restore-merge's
`m.domain = i.domain` joins, the `configs/source_qualification.yml` overlay, the citations tally and
`is_disqualified_domain` — a migration plus a data-safety review, not a small slice; **(c)** split the cases
that genuinely live on distinct hosts into their own catalogue rows, leaving the rest alone.

**Recommendation: (a) now, and (b) is the real question — because (c) cannot recover the language services
at all.** The first draft recommended (c) on the premise that `feeds.bbci.co.uk/arabic` "is a real distinct
host". **It is not: it is a PATH.** Measured — all 31 `bbc.com` entries share the one RSS host
`feeds.bbci.co.uk`, all 22 `dw.com` share `rss.dw.com`, all 11 `rfi.fr` share `www.rfi.fr`; of the 54
colliding domains only **3** have pairwise-distinct RSS hosts (`arxiv.org`, `edition.cnn.com`,
`abcnews.go.com` — section families, not language services), and **zero** of the 3,429 catalogue entries
carry a path in `domain`. So (c) is executable only for the least valuable third of the set and cannot touch
the mission case; the language services differ by feed PATH, which is exactly what (b) keys on. The honest
form of the question is therefore: **is one feed per outlet acceptable, or is per-outlet multilingual
coverage worth a source-identity migration?** *(gates: `PROMPT_04` S7.)*

**B7 · A recency-windowed re-check.** The 6-month re-verification reads a source's WHOLE history, so it
cannot see a source that degraded recently. Adding a window touches `collect_article_stats`, which the
audit report shares. → Build it as its own reviewed slice? Recommended default: yes, window = the last
90 days, published beside the whole-history verdict, never replacing it.

---

## C. Data, backup and import

**C1 · ⛔ Legacy single-file restore — remove it now?** The create path was retired 2026-06-25; the
restore half is still wired (`src/backup/artifact.py:436,605`, `src/api/backup_v2.py:49,123,187,252,294,374`,
`src/static/app-backup.js:604,660`). FUTURE_DEVELOPMENTS §49 makes removal conditional on (a) every
legacy backup you hold having been merged and (b) the unified import surfacing legacy archives. → Confirm
(a); the session verifies (b). *(gates: `PROMPT_07`/`PROMPT_08` slice "retire legacy restore".)*

> **VERIFIED 2026-09-11 — wiring present, but the code has already taken a side.** Every call site
> listed is still there. However `read_artifact`'s own docstring (`src/backup/artifact.py:649`) reads
> **“Accepts, forever (D7): … legacy bare SQLite backups, and legacy v1 .ooenc files”**. That is a
> stated commitment to keep the restore half, which is the thing this question proposes removing.
> **Reconcile the two before ruling** — either the docstring's “forever” is the ruling and this question
> is closed, or answering it also means amending that line.

**C2 · ⛔ The import checkpoint interval K** (2026-08-08 entry): verify+swap once per K backups instead
of per backup saves ~17 × (verify + snapshot + swap) on an 18-backup queue, but nothing is durable until
a swap — a kill at item 12 today keeps eleven; at K=18 it loses twelve merges. You have killed this import
twice. → Pick K (1 = today's behaviour). Recommendation: K = 3, with the verify sub-timings the first
completed backup now reports used to re-derive it.

**C3 · Import prefetch (staging the next backup while the current one merges).** Three blockers were
recorded (singleton manager, plaintext staging ownership, the digest check must run first). → Build it
after C2, or not at all? Recommended default: build only if the first real `verify_copy` number shows
prepare still dominating (the 2026-08-08 entry's own sequencing).

**C4 · ⛔ Storage plan §8 rulings 3–6** (`docs/design/STORAGE_5TB_PLAN.md`; 1 and 2 are ruled): (3)
blob-store dedup ON? (4) OOENC2 vs `age` for pack AEAD? (5) keyed-HMAC blob addressing + opaque pack
names? (6) authorise the sqlite3mc benchmark trial (benchmark only, no migration)? Recommendations on
record: yes / OOENC2 / yes / yes. *(gates: `PROMPT_22` — deliberately NOT written as a
build prompt in this plan; a design-refresh prompt only, until these are ruled.)*

**C5 · The DB-10 migrate-op for corpora born before the 16384/INCREMENTAL rulings.** The bench proved the
rebuild mechanism; a user-facing "rebuild this store at the ruled pragmas" op (app-stopped, hours + one
spare drive, cp-class cost) is unbuilt. → Build it, or document the manual rebuild only? Recommended
default: build it as a Settings → Advanced action with the honest cost estimate from `rebuild.seconds`.

**C6 · The per-OS `httpfs` binaries (D1).** The loader, pins table and CI lane exist; the binaries are
your networked build (`docs/maintenance/EXTERNAL_DEPENDENCIES.md`), and `extensions.duckdb.org` is
egress-blocked in the sandbox. → Still wanted for 0.4, or park D1/D2/D3 persisted-columnar until a
measured need? Recommended default: park; the in-memory serve already covers the windowed queries.

**C7 · The data-location chooser (fix-session 2026-07-14 slice 2).** Default = the app data folder, or
"choose a folder" creating an `OOS data` subfolder, decided at first launch after language + legal
acceptance, before the passphrase; reuses the A11 `OO_DATA_DIR` seam. → Still wanted? Recommended
default: yes, it is small and the seam exists.

> **VERIFIED 2026-09-11 — ANSWERED AND SHIPPED. Do not re-ask.** The chooser is built and wired:
> `src/static/unlock.html:336-560` runs a data-location step **between legal acceptance and the
> passphrase**, exactly as specified, against `GET /api/system/data-location`, `POST …/check` and
> `POST …`, and it is skipped silently when there is nothing to choose. The recommended default was
> taken.

---

## D. The AI layer and the Bulletin

**D1 · Bulletin Q4 — Layer A below the hardware gate?** One constant with one read
(`src/bulletin/gate.py:34 LAYER_A_REQUIRES_CAPABLE_HARDWARE = True`). Layer A is pure SQL and needs no
model; today a GPU-less operator is denied the deterministic document. → Flip it? Recommended default:
flip to `False` (the gate then applies to narration only).

> **VERIFIED 2026-09-11 — ANSWERED AND SHIPPED. The flip already happened.** `src/bulletin/gate.py:41`
> reads `LAYER_A_REQUIRES_CAPABLE_HARDWARE = False`, and line 139 (`gate_covers_document =
> LAYER_A_REQUIRES_CAPABLE_HARDWARE`) is the single read the question describes. A GPU-less operator is
> no longer denied the deterministic document. **Do not re-ask.**

**D2 · Bulletin Q2 — an introduction: none, templated from edition facts, or narrated?** Recommended
default: templated (no model), ×12.

> **VERIFIED 2026-09-11 — partly answered by what is built.** `src/bulletin/introduction.py` carries
> **both** a `deterministic_introduction()` (templated from edition facts, no model) and a narrated path
> whose absence is reported honestly (`fallback_reason`, rendered at `src/bulletin/render.py:264`). So
> option “none” is off the table and both others exist; what is left to rule is **which one an edition
> opens on by default**.

**D3 · Bulletin Q3 — mail sending.** Never / opt-in later? Sending is real egress off Tor with stored
credentials. Recommended default: never in the app; download + paste digest stays the exit.

**D4 · Bulletin Q1/Q5** — ratify the eight shipped sections as the section list, and the checkbox-per-
section review screen as the ruled design? Recommended default: ratify both as-is.

**D5 · The refused-field list in the AI check** is uncapped (30 caveat lines on the 08-12 shape) — the
shipping session asked "say the word if you'd rather it collapsed behind a count". → Collapse? Recommended
default: collapse behind a count with expand.

> **VERIFIED 2026-09-11 — ANSWERED AND SHIPPED, as recommended.** `src/static/app-diagnostics.js:1733`
> already renders the refusals inside a `<details>` whose `<summary>` is the **count plus a per-field
> shape** (`field ×n · field ×n`), expanding to the full per-language lines. That is the recommended
> collapse-behind-a-count-with-expand, built. **Do not re-ask.**

**D6 · Model-weights pin.** Weights are the one downloaded artifact with no pin (the DuckDB extension and
the Ollama installer both verify digests; weights download at whatever `main` points to). → Add a
per-roster-model revision pin in `configs/external_artifacts.yml` and REFUSE a mismatch (re-pin
deliberately)? Recommended default: yes — this is house doctrine, not a new idea.

**D7 · The `X_AVAILABLE` capability-probe class.** `PQC_AVAILABLE` (`src/custody/signing.py:61`) and
`OTS_AVAILABLE` (`src/custody/timestamp.py:62`) are set from bare imports, so a library that imports but
cannot sign reports "available" (the pqcrypto 1.0 near-miss). → Sweep the tree for the class and probe a
round trip instead? And migrate to pqcrypto 1.0 (new API + `verify` returns `None`) behind the upgrade
checklist, or stay on `<1.0` indefinitely? Recommended default: sweep yes; stay on `<1.0` until a
custody-path session with the full skeptic matrix.

> **VERIFIED 2026-09-11 — the sweep half is SHIPPED; only the migration half is open.**
> `src/custody/timestamp.py:68` defines `_probe_ots()` and line 119 sets `OTS_AVAILABLE, OTS_REASON`
> from a **round-trip probe**, not a bare import, and `src/custody/signing.py:80` documents the same
> defect class for `PQC_AVAILABLE` (“THE DEFECT THIS CLOSES (D7, ruled from the 2026-08-20
> near-miss)”). **The only live half is pqcrypto 1.0**: `pyproject.toml:252` still pins
> `pqcrypto>=0.3.4,<1.0`, per the recommendation to stay there until a custody-path session with the
> full skeptic matrix.

**D8 · The multi-model specialisation bench** (`docs/design/MULTI_MODEL_SPECIALISATION_2026-08-10.md`,
design of record, nothing built) — still wanted now that one model (Ministral 3 3B) is ruled app-wide?
Recommended default: no build; keep the design as the record of why one model won.

> **VERIFIED 2026-09-11 — premise holds, in a sharper form.** 485 lines as stated. `run_shape` has
> **eleven callers, every one of them in `tests/test_specialisation.py`, and none in production code** —
> so the module is exercised but never reached by the app, which is the precise shape of “design of
> record, nothing built”.

**D9 · Q8 — the live ollama.com library browse** (searchable, filterable by provider/date/size,
consented). Still wanted, given the one-model ruling and the buried custom-model field? Recommended
default: drop it; record the reason.

**D10 · Perception extraction — which languages/fields go live?** The gate refuses `who` in several
languages (hallucination past the floor) and passes `where` broadly. → Enable the sweep in production on
the cleared fields only, or keep it export-only until a graded gold set exists (operator step R6)?
Recommended default: cleared fields only, sweep ON, with the per-field refusals rendered (already built).

---

## E. Keyword translation and disambiguation

**E1 · The month-occupancy number** (`GET /api/diagnostics/month-occupancy?sample=400&download=1`, or
`month-occupancy.json` in any bundle taken after 2026-09-05) — slice 3 (the date-aware month block + a
re-index) is gated on it. → Will you run it and send the file? Operator step.

**E2 · `dumps.wikimedia.org` on the egress allowlist** — the single highest-value operator step for the
ambiguity map (slice 4) and the sense inventory (slice 6); five sessions have hit the allowlist. Operator
step (see F1).

**E3 · Wiktextract share-alike** (CC BY-SA 3.0/4.0 revision mixture; only 4.0 is GPLv3-compatible, one
way) — ruling still owed, gating nothing in slices 1–4. Recommended default: exclude Wiktextract.

**E4 · The SKOS thesaurus family** (UNESCO Thesaurus ar/en/fr/ru/es, EuroVoc, AGROVOC, IPTC Media Topics)
as the ru/ar synonym-tier source — "open access" is not a licence identifier. → Authorise a licence check
in the next networked session? Recommended default: yes, IPTC Media Topics first (built for news).

---

## F. Egress allowlist entries (one consolidated ask)

**F1 · ⛔ Add these hosts to the build sandbox's egress allowlist**, or accept that the corresponding
work stays operator-side forever. Six consecutive sessions have been refused at `CONNECT` with
`"selective": false` (the sixth re-probed `dumps.wikimedia.org` on 2026-09-07, `pypi.org` 200 as the
control); the variable was never the prompt. **A seventh, same day, probed the three statistics hosts
this section names and got the same answer** — `api.worldbank.org`, `sdmx.oecd.org` and
`dataservices.imf.org` each returned `CONNECT <host>:443` → `HTTP/1.1 403 Forbidden` at the proxy
(`127.0.0.1:41027`), i.e. refused before TLS, while `pypi.org` returned 200 as the control. So GOV-01
(the one-command 36-code verification), the OECD/IMF message-version read and the S6 operator list are
blocked at the TCP layer here, not by tooling — nothing in a session can route around it. Hosts, by the
work they unblock:
`dumps.wikimedia.org` (E2) · `api.worldbank.org`, `data.worldbank.org` (the 36-code verification is ONE
command: `scripts/verify_worldbank_indicators.py`) · `sdmx.oecd.org`, `api.imf.org` (SDMX message-version
verification) · `www.legislation.gov.uk`, `eur-lex.europa.eu`, `gesetze-im-internet.de` (the law
adapters' live half) · `extensions.duckdb.org` (C6) · `www.afdb.org`, `data.uneca.org`, `au.int`,
`asean.org`, `www.nato.int` (bloc rosters, Task 4) · `wikidata.org`, `query.wikidata.org` (ring
refresh). If none of these will be opened, say so once and the plan's operator lists become the only
route — the prompts are written for both cases.

---

## G. Verticals and the V1 pathway

**G1 · V1-1..V1-9** (`docs/design/V1_PATHWAY_2026-07-14.md` §7; only V1-1 is partially resolved and V1-7 is
now ruled through DB-10): V1-2 user-supplied API keys (recommended: allow, stored in encrypted settings,
never bundled) · V1-3 restrictive-licence sources (recommended: exclude from defaults, prefer UCDP) · V1-4
PubMed bulk vs API (recommended: API-first) · V1-5 win/mac at 1.0 (decide at 0.9 planning) · V1-6 the KPI
bars K1–K14 (tune the placeholders) · V1-8 elections required for 1.0 (recommended: yes) · V1-9 the 1.0
Wikipedia edition bar (recommended: ≥1 full edition + the machinery). *(gates: `PROMPT_23`, which is
written as a design-and-scaffold prompt — no vertical is built until its ruling lands.)*

**G2 · Elections roster acquisition** — a parallel networked session per the 2026-07-14 §4.5 ruling
(per-country recurrence rules + electoral-authority sources, three-tier scheduled/window/projected).
→ Authorise the acquisition session? Recommended default: yes, the law-batches contract as the template.

**G3 · Bloc rosters (Task 4 of the governments prompt)** — "several hundred member-rows each wanting a
dated source URL, and a partial roster is more dangerous than none". → Authorise its own networked
session? The registry is deliberately EMPTY until then. Recommended default: yes.

**G4 · IPCC as a source** — which products first (AR6 SPMs? WG reports?), is `pypdf` acceptable (it is
already an optional extra for the law PDFs), automatic vs curated prediction extraction? Recommended
default: AR6 SPMs, `[pdf]` extra, operator-curated from a suggested list.

**G5 · Official-statistics breadth** — the agencies directory is 29 of ~152; `news_url` per agency is a
networked research pass. → Authorise it (the law-batches pattern)? Recommended default: yes.

**G6 · Poll analysis (a)(b)(c)** (FUTURE_DEVELOPMENTS §"Poll analysis"): (a) how hard to lean on Tier 4;
(b) ever say "push poll" or only describe the mechanic; (c) answer "who's winning" more directly?
Recommended defaults: Tier 2 only for now; describe the mechanic; never.

**G7 · Open-Meteo layer** — variables first (precipitation, temperature, soil moisture?), baseline period
(1991–2020?), cache budget per place, signal-keywords as a toggleable layer or in trends by default?
Recommended defaults: precipitation + temperature; 1991–2020; toggleable layer, off.

**G8 · Religious calendars + the eclipse canon** — you said you would provide the dates (2026-06-17 ruling
9). Still the plan? Nothing is fabricated meanwhile.

**G9 · App self-update (1)–(5)**: update channel (default branch / tags only / user choice) · signature
trust root shipped in-tree? · auto-check cadence vs fully manual (ruled MANUAL 2026-06-17) · `curl|bash`
vs git-clone installs: re-run `install.sh` or in-place swap? · anchor each release hash? Recommended
defaults: tags only; no key yet (checksums, stated); manual; re-run `install.sh` on a snapshot; no
anchoring until a key exists. *(gates: `PROMPT_21` slice "self-update mechanics".)*

**G10 · Wikipedia living source, questions 1–5** (FUTURE_DEVELOPMENTS §"Wikipedia as a first-class
LIVING source"): scope of dump ingestion (all pages vs a subset) · analytics mixing (same pools vs a
per-source-type layer) · version storage depth (ruled: full text per revision) · change feed (ruled: the
tracker IS the feed) · backups (carry dump-derived articles fully, or reference the dump). Recommended
defaults: subset first (watched + their categories + top-N), per-source-type layer with merge/split,
reference the dump + carry revisions. *(gates: `PROMPT_18`, V1-9.)*

**G11 · The default aggregation strategy for an intensive indicator with no exact weighting** (`S4` of
`PROMPT_14`; `src/stats/aggregate.py::_default_strategy`). Today a bloc/region opens on the plain MEMBER
MEAN when no exact weighting is computable — every strategy is still shown side by side, so this decides
only which one the surface opens on. It was flagged in the code as a judgement call, and this session did
**not** flip it: which figure a reader sees first is an editorial decision, not a bug, and the arithmetic
cuts both ways.

The case for flipping: a population-weighted mean of a per-capita indicator **equals**
`Σ numerator / Σ denominator` — the true aggregate, not an approximation — *provided* the numerator is
reconstructed and the weight series is real for the same members and the same year. Where that holds, the
code already classifies the basis as `exact` and opens on it, so the question is only about the case where
it does **not** hold. The case for keeping the member mean: with a reconstructed-but-not-real numerator the
weighted figure is an approximation wearing the clothes of a true aggregate, and the code's own comment
says so ("the reconstructed numerator is not the real one"). A plain member mean is visibly a mean of
members and misleads nobody about what it is. Gini stays refused either way (pooling biases it low).

→ (a) keep the member mean as the opening view, or (b) open on the population-weighted mean, labelled
approximate, whenever the weight series exists? Recommended default: **(a)**, unchanged — an approximation
that reads as a true aggregate is the failure mode this project refuses everywhere else, and the reader who
wants the weighted figure has it one click away with its basis stated. *(gates: `PROMPT_14` S4.)*

---

## H. UI and browser verification

**H1 · The Observatory** — the sandbox has Chromium, so the `ooSky` renderer can be built AND
Chromium-verified in-session; the design says the surface is "NOT conservative-flaggable" and needs your
click-through. → Build it now (Chromium-verified, then your pass), or hold until the AppVM Gecko runner
exists? Recommended default: build now; stamp "Chromium-verified · awaiting human UX pass".

> **VERIFIED 2026-09-11 — ANSWERED BY ACTION; the recommended default was taken.** The Observatory is
> built and in the tree: `src/static/oosky.js` (the pure polar geometry) and
> `src/static/app-observatory.js` (the wiring), Chromium-verified in the remote sandbox, with the five
> non-regressible properties recorded as **UI invariant #31** in `CLAUDE.md` and enforced by
> `tests/test_observatory_ui.py`, `tests/oosky_node_test.js` and `test_ui_invariants` (#31). **What
> remains is only your click-through**, which is H2/L2's question, not this one.

**H2 · The Gecko/AppVM bar (R3).** Every frontend stamp reads "Chromium-verified (remote sandbox) ·
awaiting human UX pass". → Is the AppVM runner still wanted, or is your own click-through the bar?
Recommended default: your click-through is the bar; retire the AppVM item from the plan.

**H3 · The Insights search bar** (`#ins-term` + `exploreTerm`, still present) — removal is
absorption-gated on the omnibar. → Confirm the omnibar → analysis window now absorbs term exploration
(mind-map + trend for a term), so the bar may go? Recommended default: remove, behind the absorption test.

**H4 · Inline-handler retirement** (590 `on*=` attributes: 331 in `index.html`, 259 in `app-*.js`; the
CSP still carries `'unsafe-inline'`). It is the largest single UI debt and the prerequisite for a
nonce-based CSP. → Fund it as its own sequence of browser-verified slices? Recommended default: yes, one
module per slice, `app-boot.js` first.

> **VERIFIED 2026-09-11 — premise holds and the debt GREW.** Counted with an explicit handler-name
> pattern (`onclick|onchange|oninput|onkeydown|…`, not a bare `on[a-z]*=` that also matches prose):
> **335 in `index.html` + 278 across `app-*.js` = 613**, against the 590 this question recorded five
> days earlier. The CSP still carries `'unsafe-inline'` (`src/api/main.py:556`, commented “nonce-based
> CSP is future work”). Every slice shipped meanwhile added handlers in the existing style, which is
> what an un-ruled retirement costs per week.

**H5 · The 3D keyword explorer** — Q5a (2026-07-13) deprioritised it; the Observatory ruling (2026-07-18)
supersedes it. → Confirm the explorer is retired in favour of the Observatory. Recommended default: yes.

---

## I. Newsletters, maps, agenda

**I1 · Stored credentials for repeat mailbox pulls** — today the IMAP/POP3 pull never stores credentials.
→ Keep never-store (re-enter each pull), or store in the encrypted settings? Recommended default:
never-store; a task-manager job over a long pull still lands.

**I2 · OSM data-source path** — the no-WebGL ruling is firm (Q1a). → Priority order: sub-national admin-1
boundaries first, or the richer gazetteer first? Recommended default: gazetteer (it also feeds
When×Where), then admin-1.

**I3 · Tor-exit-resolve (SOCKS RESOLVE 0xF0)** for the source-IP gap over Tor — assessed 2026-07-20,
design of record pending your go; explicitly excluded from gate row 1. → Go / no-go? Recommended
default: go, as its own skeptic-matrixed slice.

**I4 · `oo-netcut` (the privileged OS-level airplane layer) and the Stem/Tor integration** — both
design-only for months. → Still wanted for 0.4, or park to 0.5+? Recommended default: park both;
record.

---

## J. Structural debt

**J1 · `src/api/diagnostics.py` is 6,200 lines / 126 routes (ROADMAP S-1).** → Authorise a
behaviour-neutral split into a package (`src/api/diagnostics/`), with the all-diagnostics ratchet
proving nothing was lost? Recommended default: yes.

> **VERIFIED 2026-09-11 — premise holds; both figures moved up.** `src/api/diagnostics.py` is now
> **6,312 lines** carrying **129 routes**, against the 6,200 / 126 recorded on 2026-09-06.

**J2 · `structlog`** is declared in `pyproject.toml:79` with zero call sites (the codebase uses stdlib
`logging`, ~612 sites). → Drop it (a dependency change: both venv profiles re-verified) or adopt it?
Recommended default: drop.

> **VERIFIED 2026-09-11 — ANSWERED AND SHIPPED (2026-09-07). Do not re-ask.** `structlog` is **gone**
> from `pyproject.toml`, and the comment left in its place at line 92 names this very question: “structlog
> REMOVED 2026-09-07 (J2, ruled on the recommended default ‘drop’)”. Zero `import structlog` anywhere in
> `src/` or `tests/`. Two later removals (`jinja2`, 2026-09-08) cite it as the precedent shape.

**J3 · Postgres parity or honest SQLite-only** (PARKED ARCH-06). → Document SQLite-only and remove the
implication of dual support? Recommended default: SQLite-only, documented.

---

## L. Small decisions the investigation agents surfaced

These were raised inside a PR body or a report and never became recorded questions. Each is genuinely
small; each has a default that the executing session will take if you say nothing.

**L1 · Governments opens on Countries.** Three separate verification passes (2026-08-13, 2026-08-20 and
the design-doc sweep) independently re-flagged that the Governments tab lands on the Countries subtab,
which reads as the tab having no content. → Change the default landing subtab, or keep it? Default: keep,
and add nothing — it is only a finding if you agree it is one.

**L2 · The verification stamp.** Every browser-verified surface currently reads *"Chromium-verified
(remote sandbox) · awaiting human UX pass"*. The Gecko/AppVM bar recorded in the fork-3 amendment has
never been met. → Is Chromium-in-sandbox plus your own click-through the standing bar, or does the AppVM
runner still gate a surface being called verified? Default: Chromium + your pass is the bar; the AppVM
runner becomes an optional strengthening rather than a gate. *(gates: `PROMPT_15`.)*

**L3 · Three `download=1` diagnostic exemptions.** The all-diagnostics ratchet lists three endpoints as
exempt-with-reason. → Confirm the three reasons still hold, or fold them in? Default: leave them, the
reasons are stated in the manifest's `excluded` block.

**L4 · The rate limit.** The API's default is 100 requests/hour on the guarded routes; the 2026-07-22 GUI
run produced 384 console lines that were 100% rate-limit refusals under 14 concurrent agents. → Is 100/h
the intended figure for a single-user local app, given that one browser tab plus a running walk can reach
it? Default: leave it and note the artifact in any future harness.

**L5 · `_SPARSE_BAR_MAX` reach.** The n<10 → bars rule reaches four of seven renderers;
`ringDumbbellSvg`, `commodityOverlaySvg` and `ooDonut` do not carry it. The dumbbell plots discrete pairs
so arguably needs no rule; the commodity overlay draws a real price line and probably does. → Extend to
the overlay only, all three, or none? Default: the overlay only. *(gates: `PROMPT_15`.)*

**L6 · `[pdf]` in the default install.** The law vertical degrades loudly without it, so a default install
cannot read a PDF statute. → Promote `[pdf]` into the default extras? Default: leave it optional and say
so in the law coverage report. *(gates: `PROMPT_13`.)*

**L7 · The synthetic corpus for the click-through runner.** It currently runs with `OO_DB_PLAINTEXT=1`.
The encrypted path is the one every real user is on, and the codec is where the app's slow surfaces live.
→ Should the runner drive an encrypted store instead? Default: keep plaintext for speed and add one
encrypted run before a release. *(gates: `PROMPT_15`.)*

> **VERIFIED 2026-09-11 — framing moved.** The runner is not uniformly plaintext:
> `scripts/ui_clickthrough_seed.py:11` records that **state A boots *without* `OO_DB_PLAINTEXT`, “so the
> app genuinely starts locked”**, while state B sets it for speed. So an encrypted store is already
> driven for the locked-boot surface, and the real question is narrower — whether the **seeded, walked**
> states should be encrypted too.

**L8 · `PR pending` in the shipped ledger.** Nine rows carry a bare `PR pending` in `refs` although all
nine merged. → Sweep them to real PR numbers, or rule that `PR pending` is an acceptable permanent value?
Default: sweep them once, then record the convention. *(gates: `PROMPT_02`.)*

> **VERIFIED 2026-09-11 — ANSWERED AND SHIPPED (2026-09-07), and this file's count was wrong.** The
> recommended default was taken: `CLAUDE.md` rule (5b) records the sweep as settled, with **twelve** rows
> resolved, not nine, and writes down the trap that nearly spoiled it — a 56-commit **shallow clone**
> whose oldest commit already contained every row, which answered `#944` for ten of them before
> `git fetch --unshallow` gave twelve distinct numbers, each corroborated by its merge's branch name. A
> column-aware check on 2026-09-11 confirms **zero** unresolved placeholders in `refs`. **Do not
> re-ask** — but see the grep trap recorded in the status banner above before running the obvious check.

**L9 · A political-lean tag deduced from keyword evidence.** The source-tag vocabulary currently offers
`lean-*` entries, so the LLM can propose one from keyword evidence — which is a fabricated editorial
judgement, and the sweep declined to filter it unilaterally. → Remove the lean scale from the offerable
vocabulary? Default: remove it, and keep human-asserted lean tags. *(gates: `PROMPT_04`.)*

> **VERIFIED 2026-09-11 — holds, but this is NOT an oversight, and the default would overturn a
> reasoned position.** `lean-*` is offerable, as stated. What the question omits is that the code
> **already classifies it and already declined to filter it**, on the record:
> `src/ai_layer/source_tags.py` puts the whole scale in `_NON_TOPICAL_CLASSES["stance-or-ownership"]`
> under the comment “A political-lean or ownership tag DEDUCED from keyword evidence would be a
> fabricated editorial judgement — the one class where a wrong proposal is not merely noise”, and it
> carries the measurement: **the field run proposed one of these once in 921 assignments**
> (`independent`), so this is “latent, not live contamination”. The table is annotated **“Reported,
> never filtered”**, which is the propose-never-auto-apply rule applied to itself. Answering “remove
> it” is a real choice — just not a bug fix.

**L10 · ~30 non-topical vocabulary entries** (`via:*`, thin-coverage, data-gap, legal formats) are
offerable as topical tags because the vocabulary is resolved live from `Source.tags`. → Filter them by a
recorded rule ("deciding `independent` is not a topic is a taxonomy ruling a human makes")? Default:
filter the `via:*` and coverage-state prefixes, leave the judgement words to you.

> **VERIFIED 2026-09-11 — holds, same correction as L9.** The “~30 non-topical entries” are not
> unexamined: they are **enumerated and classified** in `_NON_TOPICAL_CLASSES`
> (`src/ai_layer/source_tags.py:441`) as `provenance` (`via:`, `world-catalog`), `coverage-state`
> (data-gap, thin-coverage, fragmented, …) and `stance-or-ownership`, and the module comment at
> lines 390-404 records the measurement behind leaving them alone — a naive near-synonym merge “would
> have destroyed a real hierarchy in 14 of 17 candidates”. They are marked **“Reported, never
> filtered”** with the reason: “deciding that `independent` is not a topic is a taxonomy ruling a human
> makes”. Your default (filter the `via:*` and coverage-state prefixes) is compatible with that stance
> — it is exactly the half that needs no judgement — but it is a **change to a stated position**, not
> the closing of a gap.

---

## K. Operator steps this plan cannot replace (for the record, no answer needed)

- Run the Tier A quarantine + re-index (A1); cut `v0.3.0` from your machine.
- Send the month-occupancy file (E1) and, when possible, a ~1M-instance bundle (0.4 row 3-at-scale).
- Generate `configs/source_qualification.yml` from real instances (B5).
- Grade the IR gold set (Settings → Diagnostics, ~10 minutes) — unblocks the BM25F default and the
  static-embedding pilot; and the ~50-anchor triage grading sitting.
- Run `scripts/verify_worldbank_indicators.py` on a machine with plain HTTPS to `api.worldbank.org`.
- The `[segmentation]` extra + a re-index on the live corpus (the zh/ja/th stoplist batch waits on it).
- The 168-seed ring batch on a networked machine (runbook delivered 2026-07-20; the generator OVERWRITES
  its `-o` target — never point it at the live rings file).
- The kernel-log host checks on machines A and B (crash brief §8), and the field twins after the batch.
- The ≥72 h soak on a release-scale instance (0.4 row 7b) and the committed full import (0.4 row 4).

---

## M. Decisions raised after this analysis (2026-09-07 → 2026-09-10)

Appended here rather than filed in a new document, because this session's most expensive mistake was
a correction filed as a *new* entry that two later readers never reached. Same rules as above: a
recommended default is written beside each, and ⛔ marks one that should not be taken autonomously.

### M1 · Two items I closed on my own that asked for a ruling — ratify or reverse

Both were docket entries reading "a ruling is wanted", and in both the stated reason for deferring
was *"this deserves its own reviewed line"* — which expires the moment it gets one. I closed them and
said so plainly in `OPEN_QUEUE.md`, with the reversal written beside each. **What I could not
measure is whether you wanted to be asked**, so it is put to you rather than assumed.

* **M1a · The `--min 100` i18n gate now compares an unrounded percentage** (PR #1109, `0b96f653`).
  It compared `round(100 * covered / n, 1)`, so at 3265 keys a locale missing ONE key scored
  `100.0` and passed — the gate behind "every consent/caveat string ships ×12" could not see a
  single missing key. Reversal: `percent_exact` → `percent` on one line of `main()`.
  → **Recommended: ratify.** The deferral's measurable half (would tightening redden a parallel
  branch?) was measured green before and after.
* **M1b · The scale-bench drift guard now tests CALLS, not names** (`7b93a9ad`). It regexed
  `inspect.getsource()` and could not tell a call from an import, so it passed a bench that
  imported a self-heal and never ran it. Reversal: revert the one test file.
  → **Recommended: ratify.** It caught a real defect of mine one commit earlier and was measurably
  weaker than its own docstring claimed.

### M2 · ⛔ The airplane toggle says two different things, and one understates the guarantee

The main UI and the task-manager window carry differently-worded titles for the *same* button:

| surface | current wording |
| --- | --- |
| `app-core.js` | "Online — click to go offline (airplane mode); **every new network request will be refused**." |
| task manager | "Online — click to go offline (airplane mode); **stops all collection**." |

Until 2026-09-10 only the main UI's pair was translated, so a French operator read a translated title
in the app and an English one in the task manager for one toggle. **That half is fixed.** What is not
is the wording: airplane mode is a *socket-level* guarantee refusing every non-loopback target, and
"stops all collection" names only one consumer of the network — an operator reading just that title
could reasonably believe a non-collection request still goes out.
→ **Recommended: align the task-manager wording to the stronger, true claim.** Not done here because
rewording a user-facing consent string is a product decision. Cost if you say yes: one string
re-translated ×12. Marked ⛔ only because it is consent copy, not because it is hard.

### M3 · The ooMap embed on When/Where — a design choice with nothing to measure

Recorded in full in `OPEN_QUEUE.md` (2026-09-10). The coordinates are already on the wire and the
client discards them, so this is not a geocoding project. But ooMap's marker layer is *time*-filtered
and a corpus place has no time coordinate, so:

* **(a)** give ooMap a **timeless mark kind** — a change to a shared component four surfaces draw
  through, which must answer what the time slider means for a layer that does not participate in it; or
* **(b)** aggregate places to **country** and use the existing choropleth, answering the coarser
  question "which countries do this corpus's mentioned places sit in".

→ **Recommended default: (b).** The two options answer *different questions*, which is why no
measurement settles it — the reason this one stayed open while I closed others.

### M4 · The newsletter attach — ruled in principle, needs a go-ahead because it moves data

The 2026-06-15 ruling pairs the silent auto-attach with an announcing import UI and an undo, so it is
one coherent slice and needs no new ruling. The provenance column it waited on **shipped**
(`cc8d8651`), and the preview can now reach its best answer. What remains changes **data placement** —
articles move between sources — which is why it is not a thing to start unasked.
→ **Recommended: confirm the sequencing** (attach → announcing UI → undo, in that order) before a
session begins it.

### M5 · The i18n remainder — 470 strings, and the cheap half is done

Whole sentences are now **0 of 80**; all 74 keyable strings shipped in PR #1109. Of the 470 left,
about 150 begin with a lowercase letter — an *upper bound* on fragments split out of a sentence by
inline markup, which per-key translation genuinely cannot fix without markup surgery across
seventeen `app-*.js` modules.
→ **Question: is that surgery worth it, or is 470 an acceptable floor?** Recommended default: treat
it as the floor for now and revisit only if a field report names a specific untranslated surface. No
tidy breakdown of the 470 is published on purpose — two heuristic classifiers over the same set
disagreed by 176 strings in one bucket, so only method-stated figures ship.

### M6 · Not a question — the operator steps this session could not take

For completeness beside section K, unchanged and still yours: the `v0.3.0` tag (A1), the two model
pin values that need `huggingface.co` / `ollama.com` (this sandbox's proxy answers `CONNECT … 403`),
and the AI-15 lookup — whether the Ollama account `LiquidAI` is the publisher's own, deliberately
not guessed for seven consecutive sessions because it is the provenance claim behind the default model.
