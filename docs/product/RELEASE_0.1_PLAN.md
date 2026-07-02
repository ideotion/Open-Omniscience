# V0.1 — the 0.09 → 0.1 release plan (execution record)

> **Authority.** Maintainer, 2026-07-02 (verbatim intent): *"proceed with everything
> autonomously, I won't be here to check things up or approve anything. I trust you.
> Go with your plan. Push everything to go 0.1."* — combined with the standing
> coherence mandate from the same session: *"make sure everything is coherent, that
> all documents and guides and in-app documents are coherent, and that the app really
> says what the docs say, and reversely… Ethics is a major constraint, and a must-have."*
> This document is the plan **and** the record of how each decision was arbitrated
> under that grant. `docs/product/RELEASE_0.1_RC_GATE.md` stays the row-by-row gate;
> this file is the sequenced execution + the arbitration log. Under-claim is safe,
> over-claim is not — every "verified" below cites how.

## 1. State of the tree at reconciliation (2026-07-02, HEAD = c217c5f + this branch)

Established by a 19-agent verification sweep (12 gate verifiers + 2 adversarial
critics + 7 docs↔app/ethics coherence auditors), a full local test run, and hand
verification of every critical finding:

- **Full suite GREEN locally on py3.13 + real SQLCipher: 2 496 passed · 7 skipped ·
  0 failed** (7 m 08 s). This matters because —
- **The default branch had no completed CI verdict since 2026-06-29**: every run
  across ~80 merges was superseded-cancelled in queue (GitHub cancels *pending*
  runs in a concurrency group even with `cancel-in-progress: false`). The one
  completed run in that window (2026-06-30, c87844b) was a **failure** — the stale
  backup-invariant red that 9bc4e1f fixed on 07-01. "Merged ≠ green" had become
  structural.
- **The mypy ratchet was RED at HEAD (132 > 127)** — five type errors merged
  unblocked during the CI-verdict gap (rollup-serve/trending/diagnostics type
  hygiene). Fixed on this branch; ratchet re-measured at exactly 127.
- **The built release artifacts were empty of data files** (wheel: 308 entries, 0
  static/configs/locales; sdist likewise) — tagging would have published
  checksummed artifacts that cannot serve the UI or seed sources, under release
  notes instructing `pip install *.whl`. Discovered by actually building and
  inspecting; being fixed + proven by fresh-venv install-and-boot.
- **The app boots and runs end-to-end in this container** (py3.13 venv, encrypted
  store, 3 395 sources auto-seeded, zero network at boot) and is drivable with
  Playwright/Chromium — so the fork-3 "browser-unverified" debt is being closed
  with a real click-through campaign here, not deferred.
- The RC gate snapshot (last reconciled 2026-06-17) **under-claimed heavily**: the
  volumes+parity backup, unified Import/Export, two-windows consolidation,
  Search-tab absorption, commodity-enlarge→ooChart, fixity tool, Tor manual
  chapter, threat-model statements, guarded socket factory, French easter eggs and
  the .eml-at-scale dedup fix are all shipped + test-pinned at HEAD (evidence in
  the 2026-07-02 gate reconciliation).
- The docs, however, lagged the app by ~3 weeks in both directions: a 128-defect
  two-direction inventory (doc-claims-app-lacks / app-has-doc-lacks /
  stale-reference / ethics-claim-unenforced), 14 of them release-blocking.

## 2. What 0.1 means mechanically

- `pyproject.toml` version `0.0.9` → **`0.1.0`** (single-sourced; the flip touches
  pyproject + the README status prose + a CHANGES 0.1 section).
- Tag **`v0.1.0`** on a SHA where (a) the full suite is green in a **completed** CI
  run and (b) the version already reads 0.1.0 (release.yml verifies tag == pyproject
  and fails loudly otherwise).
- `release.yml` then builds sdist+wheel, emits `SHA256SUMS`, and publishes the
  GitHub release. It gains a **test gate** on this branch (it previously published
  without running any tests).
- The `0.09` branch remains the cycle branch of record; opening the next cycle
  branch (and its name) is left to the maintainer — nothing in the tag requires it.

## 3. Workstreams (all executed on this branch, each verified before commit)

| # | Workstream | Content | Verification |
|---|---|---|---|
| A | **Tree health** | mypy 132→127; suite green | ratchet re-run; full pytest |
| B | **Release plumbing** | packaging carries static/configs/locales; release.yml test gate; ci.yml `workflow_dispatch` (forceable completed run at the release SHA) | build + fresh-venv install + boot to HTTP 200; YAML parse |
| C | **Honesty/ethics code fixes** | custody auto-log default flipped **ON** (the UI already claimed it; Item-N ruling 2026-06-15 ruled it); field-test mode flipped to **opt-in** for the public tag (self-declared temporary instrumentation); "Back up first" buttons rerouted off the 2 GiB-capped path; DB-IP **CC BY 4.0 attribution rendered** on the Server-IPs map layer (license compliance); airplane-button "refused" wording made true-at-time-of-claim; Host-header/DNS-rebinding guard on the loopback API | per-fix tests + invariant suite |
| D | **Upgrade path** | ensure_* self-heal battery extended for every 0.09-cycle `add_column` without one (keywords.extractor, wiki_pages.latest_text(+revid), wiki_revisions.full_text, swept for others) + a drift guard so the hole can't reopen; pre-upgrade-backup advice in release notes (downgrade is best-effort) | schema-without-columns test; drift test |
| E | **Docs ↔ app reciprocity (both directions) + ethics coherence** | the 128-defect inventory applied: USER_MANUAL (analysis window, ooMap, unified backup, sidebar/Settings anatomy, Governments, flip-Leads, AI tab, statistics wording, managed-language lists, socket-guard disclosure), README/QUICKSTART (install flow, first-launch, feature truth-up both directions), ETHICS.md (rate-limit/UA/encryption claims corrected; bundled-artifact attribution table), SECURITY.md (at-rest + airplane sections; honest external-call enumeration), CHANGES.md 0.09 backfill 06-18→07-01 + same-cycle contradiction sweep, USE_CASES/ROADMAP banners | every claim re-verified against code before writing; retired-name greps prove the sweeps |
| F | **Browser verification (fork-3 debt)** | in-container Playwright campaign: first-run wizard → every sidebar tab, every Settings/Insights/analysis subtab, unified Export/Import dialogs, language round-trip (fr), agenda views, /tasks page, help — console errors + HTTP ≥400 collected, screenshots archived; failures fixed and re-run | campaign report JSON; zero-console-error bar on passing steps |
| G | **Fresh review pass at RC** (gate §4 last row) | executed as: the 19-agent sweep + the all-249-URL frontend↔backend route audit (zero mismatches) + full-suite green + the browser campaign + hand-verification of every critical finding (mypy, packaging, custody default, CI gap) | this document + the gate reconciliation cite the evidence |
| H | **Ledger & protocol** | shipped.csv rows for everything landed; gate reconciled 2026-07-02; this plan committed; CLAUDE.md Open-queue pointer | ledger diff |
| I | **Flip + tag** | 0.1.0 flip PR → merge → dispatch CI at the SHA → completed green → `v0.1.0` tag → release published → artifacts + SHA256SUMS verified downloadable | the release page itself |

Sequencing: A–F land as one stacked branch (this one) → draft PR → merge → CI
dispatched and watched to **completion** → I (flip) as a second small PR → merge →
CI green → tag. If anything reddens, fix forward before tagging — the tag is
earned, not scheduled.

## 4. Arbitrations taken under the autonomy grant (accepted-with-reason)

The gate's §4 standard is *"every known finding closed or consciously accepted,
and the closure verifiable."* These are the conscious acceptances — each revisitable
in 0.2, none silent:

1. **Inline-handler retirement (audit-06)** — count has grown to ~453 with the new
   surfaces. Accepted for 0.1-alpha: it blocks CSP hardening, not users; a
   delegated-listener sweep is browser-risky and belongs with the deferred
   dead-UI-code cleanup pass. → 0.2.
2. **a11y systematic batch** — partial coverage exists via the shared components
   (ooSubtabs roving tabindex, dialogs, sr-only map summaries). The full
   keyboard/screen-reader pass → 0.2.
3. **i18n chrome tail (~150 untranslatable strings)** — keyed coverage stays 100%
   ×12 and every *consent/caveat* surface is keyed; the tail is literal
   data/examples, link-embedded help paragraphs, and the newest panels. The
   unified Export/Import dialog (a consent-bearing surface) is the priority slice;
   the remainder is a recorded burn-down, not a silent gap.
4. **State-into-DB (D1/D4)**, **stored mailbox credentials**, **task-manager
   History subtab**, **per-country scrape priority**, **"Your lens"/corpus
   passport**, **GUI self-update mechanics** (never built; bootstrap.sh +
   install.sh re-run is the survival path), **offline LLM kit RM-08**,
   **date-extraction recall (F4)**, **Thai/zh segmenter** (disclosed limitation),
   **free-disk preflight on giant downloads** — all explicitly deferred with the
   gate rows annotated. None regressed; none are honesty gaps.
5. **Fresh full re-audit of all ~463 PRs since audit-06** — replaced by workstream
   G's evidence set (above). A from-scratch line-by-line re-audit is 0.2 work; the
   claim "reviewed at RC" is made only as far as G's evidence carries it.
6. **Swagger `/docs` CDN exception** — the FastAPI docs UI loads its assets from a
   CDN when the user opens `/docs` in a browser (the app process itself never
   egresses). Recorded in SECURITY.md rather than vendored this cycle.
7. **climate_events.yml** stays flagged VERIFICATION-PENDING in-file (honest flag,
   NOAA CPC check remains a maintainer networked step).
8. **Vendored Alpine 3.14.1 vs upstream 3.15.12** (rolling freshness issue #440) —
   pinned + sha-verified + local-only; refresh is routine maintenance, not a tag
   blocker.
9. **Legal documents are drafts** (CGU/RGPD/mentions — `docs/legal/`, surfaced at
   first launch with an explicit acceptance step). They self-describe as working
   drafts; for a 0.1 **alpha** that honesty is acceptable. Final texts are a
   maintainer/legal step.
10. **Windows/macOS** stay observation-only per ruling #5 (Debian is the target);
    release notes state exactly that.

## 5. What the parallel sessions own (not planned here)

- **Scaling/keyword-engine lane** (`modest-hopper-*`): D-series rollups, opt-in
  columnar serve, perf at the 59k-article corpus. Their opt-in flags ship OFF; if
  their work merges before the tag it rides along, else it's 0.1.x.
- **Source-equilibrium lane** (`article-language-equilibrium-*`): source
  diversification, per-language cadence, coverage views. Same policy.

## 6. Post-0.1 seeds (the 0.2 slate, so nothing is lost)

The arbitration list in §4 (items 1–8), plus: the open-class keyword review loop
(sr/az stoplist sources, fr furniture), P5.2 embeddings + P6 entity→QID +
lemmatization-ON + BM25F default (all gated on the maintainer's graded gold set),
persisted columnar (httpfs packaging decision), dead-UI-code deletion pass
(browser-verified), WARC/BagIt archive + tiered retention, the Open Commons Mirror
sister project, elections/civic vertical, remaining manipulation cards
(bury/event-timed/outrage), Home "Latest in your corpus", clickable in-article
keywords, content-provenance column hygiene, win/mac graduation, signing keys.
