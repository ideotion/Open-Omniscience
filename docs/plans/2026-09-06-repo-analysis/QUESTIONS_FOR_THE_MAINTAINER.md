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

**B2 · The stoplist ruling, (1) vs (2)** (`CLAUDE.md` "KEYWORD-TRIAGE REVIEW + THE STOPLIST RULING"):
(1) derive a versioned per-language stoplist into the repo, once, reviewed; (2) an auto-updating stoplist
derived from the live corpus. Recommendation on record and unchanged: (1) — a stoplist entry is a partially
irreversible corpus-wide deletion (index-time), a poisoning vector, and contradicts propose-never-auto-apply.
*(gates: the `PROMPT_05` prompt's English/French global batch.)*

**B3 · The English (11,263) + French (881) triage proposals.** They can only enter the GLOBAL channel
(`en`/`fr` never reach the scoped channel), so each word needs cross-language review. → Review them as one
batch in a session (a 60-word seeded sample is already hand-classified in
`docs/audit/keyword-triage-2026-09-05-sample.csv`), or leave them until the (1)/(2) ruling? Recommended
default: review a seeded stratified sample per batch, ship only furniture, refuse open-class words.

**B4 · The 64,910 `kind_overrides` proposals** (measured ~50% precision) — treat as a worklist for a
future LLM-perception NER pass, or drop them? Recommended default: keep the file as evidence, build no
tool; revisit when the perception NER kinds exist.

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

---

## D. The AI layer and the Bulletin

**D1 · Bulletin Q4 — Layer A below the hardware gate?** One constant with one read
(`src/bulletin/gate.py:34 LAYER_A_REQUIRES_CAPABLE_HARDWARE = True`). Layer A is pure SQL and needs no
model; today a GPU-less operator is denied the deterministic document. → Flip it? Recommended default:
flip to `False` (the gate then applies to narration only).

**D2 · Bulletin Q2 — an introduction: none, templated from edition facts, or narrated?** Recommended
default: templated (no model), ×12.

**D3 · Bulletin Q3 — mail sending.** Never / opt-in later? Sending is real egress off Tor with stored
credentials. Recommended default: never in the app; download + paste digest stays the exit.

**D4 · Bulletin Q1/Q5** — ratify the eight shipped sections as the section list, and the checkbox-per-
section review screen as the ruled design? Recommended default: ratify both as-is.

**D5 · The refused-field list in the AI check** is uncapped (30 caveat lines on the 08-12 shape) — the
shipping session asked "say the word if you'd rather it collapsed behind a count". → Collapse? Recommended
default: collapse behind a count with expand.

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

**D8 · The multi-model specialisation bench** (`docs/design/MULTI_MODEL_SPECIALISATION_2026-08-10.md`,
design of record, nothing built) — still wanted now that one model (Ministral 3 3B) is ruled app-wide?
Recommended default: no build; keep the design as the record of why one model won.

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
work stays operator-side forever. Five consecutive sessions have been refused at `CONNECT` with
`"selective": false`; the variable was never the prompt. Hosts, by the work they unblock:
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

---

## H. UI and browser verification

**H1 · The Observatory** — the sandbox has Chromium, so the `ooSky` renderer can be built AND
Chromium-verified in-session; the design says the surface is "NOT conservative-flaggable" and needs your
click-through. → Build it now (Chromium-verified, then your pass), or hold until the AppVM Gecko runner
exists? Recommended default: build now; stamp "Chromium-verified · awaiting human UX pass".

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

**J2 · `structlog`** is declared in `pyproject.toml:79` with zero call sites (the codebase uses stdlib
`logging`, ~612 sites). → Drop it (a dependency change: both venv profiles re-verified) or adopt it?
Recommended default: drop.

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

**L8 · `PR pending` in the shipped ledger.** Nine rows carry a bare `PR pending` in `refs` although all
nine merged. → Sweep them to real PR numbers, or rule that `PR pending` is an acceptable permanent value?
Default: sweep them once, then record the convention. *(gates: `PROMPT_02`.)*

**L9 · A political-lean tag deduced from keyword evidence.** The source-tag vocabulary currently offers
`lean-*` entries, so the LLM can propose one from keyword evidence — which is a fabricated editorial
judgement, and the sweep declined to filter it unilaterally. → Remove the lean scale from the offerable
vocabulary? Default: remove it, and keep human-asserted lean tags. *(gates: `PROMPT_04`.)*

**L10 · ~30 non-topical vocabulary entries** (`via:*`, thin-coverage, data-gap, legal formats) are
offerable as topical tags because the vocabulary is resolved live from `Source.tags`. → Filter them by a
recorded rule ("deciding `independent` is not a topic is a taxonomy ruling a human makes")? Default:
filter the `via:*` and coverage-state prefixes, leave the judgement words to you.

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
