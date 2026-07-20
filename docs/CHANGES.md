# Changelog

> The repository’s **default branch is `main`** (permanently, since 2026-07-15 — the branch name and the version number are independent). Historically each cycle branch `0.0N` produced release `0.0.N`, the consolidated `0.09` cycle produced **`0.1.0`, the first alpha**, the `0.1` cycle produced **`0.2.0`, data safety at scale** (tagged `v0.2.0` after the live-corpus P0 validation), and the current cycle is **`0.3.0`, measured & verified** (see the README's version note).

## 0.3.0 — measured & verified (in progress, unreleased)

The `0.3` cycle turns the instruments the project has built into a standing improvement
loop, and recalibrates the analytics against a real ~500k-article corpus. On the board
(each item ships via its own reviewed PR; nothing below is claimed done until it lands):

- **The recursive improvement loop v1** — the machine-readable KPI snapshot + diff and
  the standing improvement-cycle protocol
  ([`docs/design/V1_PATHWAY_2026-07-14.md`](design/V1_PATHWAY_2026-07-14.md) §2).
- **Scale recalibration of the analytics surfaces** — the six delegated 2026-07-18
  briefs: Leads/card-system selection calibration (+ the convergence exploration
  amendment and the **no-capped-figures rule**: a displayed number is never a cap),
  lemmatization default-on, entity-families cleanup (furniture acronyms, cross-script
  aliases, truthful kind filters), the groups layer (keyword → group → super-group
  naming, the circle grammar, honest group statistics with mandatory dominance
  disclosures, keyword→group navigation, the clickable concept map).
- **The law vertical build-out** — proving the tracker end-to-end on the merged
  world-wide legal-source catalog (225 sources / 162 jurisdictions), adapters for
  structured sources, coverage diagnostics against official enumerations.
- **The browser-verification burn-down** — the AppVM runner + `ui_walk`, graduating the
  accumulated "browser-unverified, needs click-through" frontend backlog.
- **The Observatory** — the corpus-as-night-sky exploration tab (design of record:
  [`docs/design/OBSERVATORY_DESIGN.md`](design/OBSERVATORY_DESIGN.md)), gated on the
  group-statistics core and maintainer click-through.

## 0.2.0 — data safety at scale (the `0.1` cycle, version set 2026-07-10)

The `0.2` cycle re-engineers the app to survive **large corpora** — a live multi-day run
reached ~100–130 GB. Shipped so far: a streaming, bounded-RAM, resumable, verifiable
backup/restore engine (`oo-volumes-2` — no plaintext corpus snapshot, incremental
changed-volume re-emit); the collector out-of-memory root-cause fix (pass recycling + an
RSS memory guard + inter-pass WAL checkpoints); unlock-at-scale instrumentation; and a
synthetic-corpus scale-test harness. **Tagged `v0.2.0`** after the maintainer's
live-corpus validation of the P0 scale set via the in-app push-button P0 validation job
(see [`docs/product/SCALE_ROADMAP.md`](product/SCALE_ROADMAP.md) and
[`docs/product/P0_VALIDATION_RUNBOOK.md`](product/P0_VALIDATION_RUNBOOK.md)).

- **Backup at scale, rebuilt (`oo-volumes-2`).** The large-corpus backup no longer
  materialises the whole corpus twice (a plaintext snapshot + a zip) before writing a
  volume — the OOM-on-the-save-path a 100 GB field run hit. It streams each member
  directly into independently-authenticated encrypted volumes with bounded RAM end to
  end (including banded Reed–Solomon parity), never decrypts the corpus at backup time,
  re-emits only changed volumes on a refresh, resumes an interrupted run, and verifies
  the signed manifest + every volume checksum. Restore streams member-by-member,
  disk-preflights staging, and hands the artifact to the unchanged additive-only merge.
- **The collector out-of-memory fix.** A 21.6-hour continuous crawl pass grew RSS past
  the VM's RAM and was OOM-killed. Passes now recycle on a time budget, an RSS memory
  guard pauses collection (never kills it) under measured memory pressure, and the WAL
  is checkpoint-truncated between passes — flat RSS across recycled passes, soak-verified.
- **Unlock at scale, root-caused.** Boot ran the FTS5 `'rebuild'` — a corpus-scaled
  encrypted-page re-read — unconditionally on *every* unlock; the sync triggers already
  maintain the index, so it now rebuilds only when needed. Measured on a 112k-article /
  2.7 GB encrypted synthetic corpus: 28.6 s → 0.002 s per boot. Per-phase unlock timing
  is instrumented so any long phase is visible and honest.
- **Snappiness under load.** The heavy read endpoints gained bounded concurrency, request
  single-flighting and server-side deadlines so a burst of polls can no longer spiral into
  a freeze; the keyword-daily rollup now serves windowed trends by default and rebuilds on
  corpus change instead of scanning the mentions table live.
- **A synthetic-corpus scale harness + storage forensics.** A generator + benchmark runner
  reproduces the scale behaviours in-dev (GAMMA), and session forensics + an itemised
  storage-footprint report name what the on-disk gigabytes actually are (database triple,
  wiki dumps, OSM regions, staging, and the external Ollama model store).
- **Push-button P0 data-safety validation.** The live-corpus acceptance run is now one
  in-app job (Settings → Diagnostics): it drives the real backup engine against your
  corpus, verifies it, probes a staged restore + a dry-run merge preview (your live corpus
  is never replaced or deleted — the restore preview never writes it), and reads the unlock + collector instrumentation into
  one report with a per-check verdict — measurements only, no score, never a fabricated
  pass. Procedure: [`docs/product/P0_VALIDATION_RUNBOOK.md`](product/P0_VALIDATION_RUNBOOK.md).
- **Offline word segmentation for zh/ja/th.** An optional `[segmentation]` extra
  (jieba/janome/pythainlp, pure-local, dictionaries in-wheel) turns whole-sentence CJK/Thai
  keyword junk into real recurring words; a core install stays byte-identical (graceful
  degrade). Korean + Marathi join the managed languages with vendored stoplists.
- **Backup & diagnostics UX truth-telling.** Backup UI reads job state as truth (honest
  paused-state label, verify/pause-resume wiring); the "all diagnostics" export runs as a
  cancellable background job instead of freezing the app on a large corpus.
- **De-US-centring + honesty riders.** Transnational bodies get an honest "Global" region;
  discovery filters CDN/analytics/boilerplate + social noise from candidate sources; opt-in
  local-LLM language detection is surfaced as a third, clearly labelled "AI-derived ·
  unreliable" provenance class that never overwrites an asserted language.
- **Seamless install on Debian/Ubuntu/Tails.** When the stdlib `venv`/`ensurepip` module is
  missing (it ships in a separate apt package that Tails and minimal Debian don't preinstall),
  the installer now installs it **automatically** instead of stopping with a manual command —
  seamless on Tails, where it explains that this needs an administration password and a Tor
  connection, and is honest that Tails ships Python 3.11 and that apt packages are amnesic
  unless persisted (Persistent Storage → Additional Software). It never hangs on an
  unanswerable sudo prompt (CI / `--unattended` / no TTY), refuses to claim success if
  `ensurepip` is still missing afterwards, and can be opted out with `OO_NO_APT=1`.
- **Housekeeping.** The FRED OECD share-price index ids were corrected to 2-letter ISO
  (the indices board was empty on most continents), Hungarian + Persian relative-day words
  and robots-dead default calendar feeds were fixed, the roadmap was consolidated to one
  board, and spent session briefs / release plans were archived.

## 0.1.0 — deeper sense-making (the 0.09 cycle, released 2026-07-02)

The `0.09` cycle delivered its slate (the `0.08` cycle below shipped in full):
space-time convergence detection + the watch-rule attention engine, SQLCipher
at-rest encryption with the additive-only + volumes+parity backup redesign, the
corpora/analysis-window system, the omnibar global-search rework, agenda views +
catalog depth, the ooMap world map, local AI (Settings → AI), newsletter import,
official statistics with vintages, and a large slice of the i18n long tail — and
ships as **0.1.0**, the first alpha. Known accepted limits are recorded in
[`docs/archive/releases/RELEASE_0.1_PLAN.md`](archive/releases/RELEASE_0.1_PLAN.md) §4; the row-by-row
release gate is [`docs/archive/releases/RELEASE_0.1_RC_GATE.md`](archive/releases/RELEASE_0.1_RC_GATE.md).
See [`docs/FUTURE_DEVELOPMENTS.md`](FUTURE_DEVELOPMENTS.md) for what comes next.

- **The world map, rebuilt: a choropleth you can read — with the temporal map
  folded in.** The old dot-only "temporal map" is retired into one universal map
  component (`ooMap`, the map sibling of `ooChart`/`ooSubtabs`) that now fills the
  content area. Countries are **coloured by a measured dimension** on a theme-aware
  scale — **sources**, **articles**, **keyword mentions**, or **mean tone** —
  switchable from a picker *inside* the map, with zoom/pan/legend controls overlaid
  Google-Maps-style. Granularity toggles between **country** and **continent**
  aggregation (a weighted mean for tone, never a mean-of-means), and a **Places**
  overlay plots the corpus's *mentioned* places as a distinct deduced layer. The
  space-time **Signals** layer and its **time slider** live inside the same map now,
  so nothing from the temporal map is lost. Honesty is built in: a country with no
  data shows a **"no data" hatch** (never a guessed colour), sentiment rides a
  **diverging** scale with the VADER-English-only caveat and an `n=` count, unlocated
  data is bucketed and stated, and country/continent names localise ×12 (via the
  browser's own CLDR for the ~200 territories). Counts only — no composite scores.

- **One Export, one Import.** All the scattered backup and import surfaces collapsed
  into two buttons in Settings → Data & backup: **Export / Back up…** opens one dialog
  that inventories what you have (corpus · LLM models · offline maps · Wikipedia dumps,
  with real counts and sizes), takes a destination folder and a passphrase, and streams
  the encrypted volumes + parity plus the large public blobs; **Import…** scans a folder,
  shows what it found (a volume backup, large data, newsletters, models) and restores it
  **additively** — nothing you already have is ever overwritten. The old standalone
  panels and the ~2 GiB-capped single-file backup *create* were retired (the legacy
  single-file *restore* stays for migrating old archives). The dialogs' consent wording
  (no-recovery passphrase, additive restore) ships in all 12 languages.

- **Big backups that survive corruption: volumes + parity.** A journalist's corpus
  can outgrow a single file — and the encrypted-backup path relied on **one
  AES-GCM call**, which hard-caps at ~2 GiB, so at a multi-GB corpus a backup
  simply **failed** ("data too long"). The large encrypted backup is now a **set of
  independently-authenticated <600 MB volumes** plus a signed manifest, written with
  a **streaming** cipher (no whole-archive-in-RAM, no size cap) so a truncated,
  reordered or extended stream fails authentication instead of yielding a half-good
  archive. On top of the volumes, **Reed-Solomon erasure parity** lets **any few
  lost or corrupt volumes be rebuilt exactly** — including a corpus volume, so a
  monolithic encrypted database genuinely survives partial corruption. Every rebuilt
  volume is re-checked against its manifest hash before it's trusted; parity needs
  numpy (the analysis extra) and degrades *loudly* to volumes-only when it's absent,
  never a silent partial restore. Reachable from Settings → Data & backup as a
  cancellable, resumable job.

- **Back up your maps, models and Wikipedia dumps to a folder or drive.** Public,
  re-downloadable blobs (offline-map regions, Ollama models, Wikipedia dumps) are
  far too large to ride the encrypted single-file backup — so a new **large-data
  backup** streams them file-by-file into a destination folder you pick (e.g. an
  external drive), with a manifest, **checksum dedup** (an unchanged blob is never
  re-copied), atomic writes, and a free-space preflight. Restore copies them back
  **additively** (skip-if-present, never overwriting a differing local file), and
  only *finished* downloads are ever included. It runs as a pausable, resumable
  task-manager job. These blobs are copied **as-is** (not whole-file re-encrypted —
  that's what makes 100 GB feasible); your private corpus stays in the encrypted
  backup.

- **Choose exactly what to back up and what to restore.** The full-backup and
  restore panels gained a **"What to back up / restore"** fieldset — keep or exclude
  **imported newsletters**, point to the separate models/large-data backups — so you
  can, for example, back up a curated corpus *without* a batch of faulty `.eml`
  imports and re-import clean ones later (restore is additive, so leaving the bad
  ones out is the way to replace them). Local LLM models also get their own separate
  `.oomodels` backup with checksum dedup, so a restore never re-pulls multi-GB
  models. And a **"Remove imported newsletters"** maintenance action deletes exactly
  the newsletter/mailbox articles (and every dependent row, including the search
  index) from the *live* corpus, leaving the source rows so a clean re-import
  re-attaches.

- **Import a whole folder of newsletters — as a pausable job.** The `.eml` importer
  now scales to a folder of tens of GB: instead of a browser upload capped at ~1,000
  files, a **server-side folder-import job** walks the tree in bounded chunks,
  commits in **batches** (not one fsync per message — much faster on a big folder),
  shows honest progress + a rule-of-three ETA, appears in the task manager, and can
  be **paused and resumed** — with an on-disk cursor so a resume survives an app
  restart instead of rescanning from zero. Every message still goes through the same
  anonymise-at-ingest path (recipient never stored, tracking links de-toxed and never
  followed), and content-cleanup now strips leaked CSS/JS/comments and decodes HTML
  entities from the stored body.

- **Settings → AI: install Ollama, queue model downloads, tune the prompts.** The
  read-only "Models" panel became a full **AI** subtab. When Ollama is absent it can
  now **download, verify and run the official installer** — the long-standing "we
  can't fabricate a per-OS checksum" blocker is gone because GitHub's releases API
  **attests a SHA-256 digest per asset**, so the app verifies the script against that
  attestation and *refuses to run* on a mismatch or when no digest is attested;
  elevation is explicit (it runs only with passwordless privilege, else it shows you
  the exact verified `sudo sh …` command). Model pulls are now a **queue** — one at a
  time, the rest wait, each cancellable — with a downloads section showing real byte
  progress. You can **edit the built-in prompts** (summary, translate, synthesis, and
  the AI-keyword extractor) and define your own **custom extractors** (a managed list
  of prompts, runnable on demand or on ingest), whose results are stored separately
  and always labelled **"AI-derived — unreliable,"** never fed into the trusted
  keyword index. Pulls and installs egress over clearnet via the Ollama process
  (disclosed at consent) and are refused under airplane mode.

- **Read, summarise, translate — and synthesise many articles.** The offline reader
  gained **Summary** and **Translation** tabs (the latest result plus every earlier
  one, with a generate-now control and a target-language picker), and **bulk
  Summarize-all / Translate-all** runs over a whole matched set as a client-side
  **queue** (one at a time, per-job cancel) that skips articles already in the target
  language. Every result carries its full provenance — the exact prompt text and
  model — and none of it is ever keyword-indexed. **Synthesis** moved out of a
  cramped card into a proper window with a **transparent selection step** (you see
  and pick which articles are included), per-claim citations, single-source flags,
  and export to Markdown / a standalone page; it and the summaries write in the UI
  language.

- **Re-indexing your corpus is a background job you can pause.** The whole-corpus
  re-index (Settings → *Clean up keywords* / *Re-index the whole corpus*) moved off
  the browser (where closing the tab restarted it from article 0) into a **backend
  job** with an on-disk cursor, so it survives a tab close or app restart and
  **resumes from where it stopped**, and it appears in the task manager with
  pause/resume. *Clean up keywords* now runs a **keyword-only** pass (skipping the
  date/place/entity and sentiment work — about ⅔ less work) and reconciles each
  keyword's language to its **signature-majority**, fixing the first-write-wins
  language tags; commits batch for speed with a per-article fallback so a transient
  lock never drops an article, and an FTS `optimize` runs after a bulk pass.

- **Cleaner keywords across 18 languages.** The keyword engine leaked function words
  in space-segmented languages; it now ships **full stopword lists (stopwords-iso)
  for 18 managed languages**, adds temporal-deictic adverbs (yesterday / gestern /
  вчера / mañana …) and platform furniture (podcast/newsletter/cookies), and a new
  **open-class detector** (`analyze_keyword_log.py --generic-terms`) surfaces
  corpus-ubiquitous words as *candidates for review* — proposed to a human, never
  auto-swept, because adjectives and common nouns are dual-use (health/policy are
  topics *and* noise). The two channels are honest about collisions: a language-scoped
  list can't hide a word in another language, while a globalised one is
  collision-checked. Junk clears on the next re-index.

- **Keywords now show their translation.** A reader once saw top keywords in Arabic
  they couldn't read; the engine's answer is to **translate, never blind** — every
  keyword is shown regardless of language **with its translation** (`original →
  translation`), which also surfaces trans-language concepts. Translations come from
  **verified Wikidata-QID rings** (hundreds of concept rings, generated on a networked
  machine and *hand-vetted* — mis-resolved journals/bands/place-names dropped) with a
  clearly-flagged local-LLM fallback for keywords in no ring. Rings bind into keyword
  families and super-groups, and a durable **concept super-group** scaffold gives
  each umbrella concept cross-language reach by construction.

- **Better search ranking — and a way to measure it honestly.** Full-text search now
  ranks with **BM25F**, weighting a **title** match above a body match (reversible —
  equal weights reproduce the old ranking). To keep quality changes evidence-based
  rather than guessed, a native **IR-evaluation harness** (nDCG / MRR / Recall / MAP,
  reported per-language and per-axis, never one blended score) can score the live
  search against a **graded gold set** you supply, and A/B two weight sets — runnable
  from the Diagnostics panel or a documented gold-set file. Conflation changes report
  their recall gain and precision change *separately*, with the example sets, never
  merged.

- **Drill your corpus by who, where and when.** The analysis window's When/Where/Who
  subtab became a **facet surface**: people, organisations, places and a new **by-year
  temporal facet** render as clickable chips (counts only), and clicking a value
  **drills** — spawning a refined analysis window over exactly the articles that
  mention that entity, place or year. It reads the article-indexed mention tables
  (never the slow keyword→articles join), stays deduced-never-confirmed, and adds no
  score.

- **Lead cards now flip — and "cards" are "Leads."** A briefing card is a sourced,
  caveated *prompt to investigate*, so the user-facing name is now **Lead** (earlier
  entries in this changelog call them "cards"). Each Lead is a **two-sided flip
  card**: the front is the lead at a glance, and one click reveals the back — the
  **caveat** (right beside the "Open corpus" action, so you read the warning as you go
  to explore), the method, the "why am I seeing this," and the evidence. The caveat
  stays informed-consent-by-layering: it's in the DOM by default, revealed by a flip,
  never hidden behind a toggle.

- **Eight experimental interfaces (Settings → GUIs).** An opt-in sandbox gallery
  offers **eight alternative skins** of the same app — Aurora, Atlas, Command, Field,
  Focus, Terminal, Canvas, Editorial — switchable live. Each is a scoped skin over the
  one render logic (so no functionality is lost), inherits the active theme, and
  **preserves every ethical guarantee by construction**: caveats visible, the one
  network-consent popup, no scores, no outbound resources (the only JS dependency,
  Alpine, is vendored locally and checksum-pinned — never a CDN). The long per-interface
  rationale is in `docs/product/GUI_ALTERNATIVES.md`.

- **A more balanced source catalog, with honest channel labels.** **224
  live-verified non-English sources** were added toward a real language/region
  equilibrium (no mono-stance region, managed languages only, all enabled off for
  review), and in-app **Wikidata source discovery** proposes further candidates
  (`enabled:false`, for you to review). Separately, each source now carries a
  **content-provenance channel** — *newsletter*, *news*, *web-article*, *wiki*,
  *statistics*, … — an **asserted fact** the ingest path knows, **never a credibility
  judgement**. That fixed a real mislabel: imported newsletters had defaulted to
  "news" across every facet and reading-diet view; they now correctly read
  "newsletter."

- **Optional in-memory rollups for a snappier Insights on a big corpus.** The
  windowed keyword aggregations that froze Insights on a large corpus can now be
  served from a **process-lifetime in-memory rollup** — **off by default**
  (`OO_COLUMNAR_SERVE=1`), built once in the background, safe by construction (any
  problem falls back to the identical live query), and never a plaintext file (the
  encrypted store stays the source of truth). It's honest about what it serves (a
  `basis` disclosure with the source and as-of). The *persisted* encrypted rollup
  remains blocked on bundling per-OS crypto binaries — verified, not fabricated:
  DuckDB ≥1.4 was tested and still refuses a securely-encrypted write without the
  OpenSSL extension.

- **Field-hardening from the live tests.** A cluster of reliability and honesty
  fixes: airplane mode is now a **socket-level guarantee** — a process-wide guard
  wraps the socket layer so, while the kill switch is engaged, *any* non-loopback
  connection is refused **before** the real socket call, so no missed call site or
  third-party library can egress (loopback and Unix sockets always pass; transparent
  while online). A malformed IPv6 URL in a scraped page no longer aborts an article's
  whole link-extraction (one bad `href` is skipped, the good links kept). The idle
  **polling storm** was tamed (vitals back off to a 6 s chip-only cadence when the
  panel is closed). The **`/favicon.ico` 404** on every page is gone (the brand eye is
  served and declared). And several Home **Leads that lost their corpus on click** now
  carry their exact article set, so clicking opens precisely the articles the Lead was
  built from.

- **Official statistics, with honest provenance and revisions.** Settings → *Statistics*
  now fetches published figures from documented machine endpoints (the World Bank API and
  Eurostat SDMX) and stores each one with its full provenance and a first-class **vintage** —
  a re-fetch later is a *new* row, never an overwrite, so revisions are preserved as evidence.
  Producers are shown **side by side and never averaged**, and a *Triangulate* view flags any
  cell that mixes incomparable units, seasonal adjustment or base years. Every figure you
  fetch is **tracked for auto-refresh** (a periodic re-fetch that captures new vintages while
  you are online; disable or remove any you don't want). No score is ever computed; the fetch
  is refused under airplane mode.
- **Watches — save a condition, get a Lead when it matches.** Insights → *Watches* lets you
  save a search the app keeps an eye on: when your corpus gains enough *new* articles matching
  it (your own threshold, within a recent window), it fires a **watch** Lead card on Home and
  records it in the watch's history (open the exact article set in one click). Entirely
  local — no notifications, no network, no escalation: a watch is a prompt to read, never a
  verdict or a score. On by default; you can enable/disable/edit/delete each one.
- **Two new manipulation-pattern Leads — naming a shape, never a verdict.** Home can now
  surface two structural patterns in your own corpus. **Source laundering**: when many
  *distinct* sources all cite the same single origin, the apparent corroboration traces to one
  source wearing many hats (independence is measured by distinct sources, not article count;
  social/storefront links are excluded). **Recycled claim**: when a recent article is
  near-identical to a much *older* one, the same text has resurfaced after lying dormant (the
  trigger is a measured time gap, and a single source recycling its own evergreen is flagged as
  such). Both reuse the proven citation-graph and near-duplicate tools — no AI, no score — and
  state the innocent explanation beside the pattern (a widely-cited primary source, or an
  anniversary/evergreen re-run, looks identical). Each opens the exact article set in one click.
- **Pull newsletters live from a mailbox (IMAP/POP3).** Settings → *Newsletters* can now pull
  newsletters directly from a mailbox instead of exporting `.eml` files one at a time. Every
  message goes through the same **anonymise-at-ingest** path as the file import — the recipient
  is never stored, no raw message is retained, and tracking links are de-toxed and **never
  followed** (so a pull can never reveal that you opened or clicked). It's a consented network
  action: refused under airplane mode, connecting over TLS to your provider (your IP is visible
  to them, like any email client — not via Tor), with credentials used for the one fetch and
  never stored.
- **Uninstall now has modes — and offers a backup first.** Settings → Safety → *Uninstall*
  lets you choose **Minimal** (remove the program, keep the app folder and your data),
  **Full** (also delete the app folder, data still kept), **Secure** (also wipe your data
  and keys), or **Customize** (tick exactly what to remove). Before a screen shows you the
  exact paths that will be removed, and the destructive modes offer **“Download a backup
  first.”** Secure is honest about its limit: an overwrite can’t guarantee erasure on
  SSD/flash/copy-on-write disks — the real protection is that your corpus was encrypted and
  the key is destroyed. A short uninstall log is written to your home folder so you can
  confirm what happened. The shutdown is also quieter now (no scary database-teardown lines).
- **The keyword log is now a small per-language archive.** On a large corpus the keyword
  diagnostics log had grown to ~20 MB — awkward to share. **Download keyword log** now
  produces a **`.zip` split per language** (a `summary.json` of the corpus-wide structures
  plus one `keywords/<lang>.json` per language), which compresses to a few MB and is **kept
  under 20 MB** — if it ever would exceed that, the lowest-mention keywords are trimmed *per
  language* (so no language is squeezed out) and the manifest says exactly what was dropped.
  Every keyword's data is unchanged; nothing is scored.
- **A date-extraction diagnostics log, to help make extraction better.** Settings →
  Diagnostics has a new **Download date-extraction log (.json)** button. For a bounded sample
  of your articles it shows, side by side, the dates the extractor *found* and the date-like
  text it *skipped* — plus coverage broken down by language (so a language the extractor has
  no month names for stands out immediately). Like the other diagnostics it's generated only
  when you click, stays on your machine, and is never transmitted; share it if you'd like to
  help improve the extractor. Counts and bounded samples only, no scores.
- **The dates a story is *about* are now caught as you collect.** Date extraction already
  ran automatically at ingest, but it was only catching fully-spelled-out dates and quietly
  missing the way news actually writes time — "yesterday", "on Tuesday", "11 September" (no
  year), and non-English numeric dates like `11/06/2026`. It now resolves those against the
  article's own publication date and language at ingest, so the reader, the date filter and
  the agenda's deduced-events all see the fuller set. Every extracted date stays a
  **candidate you can confirm or reject**, shown with the exact snippet it came from — still
  no bare years, still never invented.
- **Set a download speed, not a worker count — the bandwidth-governed collector.**
  Settings → Collect now offers a **collection-speed slider** (a download-rate target in
  kbps) with a **“Maximum”** end-stop and a live **“Now: X kbps”** readout. Behind it, a
  bandwidth governor raises or lowers how many sources are fetched at once to approach
  your target — always across **different** sites, never hammering one (robots.txt and
  per-host rate limits are unchanged) — and **backs off automatically** when the CPU,
  memory or the encrypted database become the limit. The default now targets **≥ 500
  kbps** out of the box. A new **collection-performance log** (in the debug bundle)
  records the real download rate, in-flight fetches, writer-gate contention and CPU/
  memory each second, and classifies the limiting factor at the end of each pass, so a
  slow collection has an honest, shareable explanation. *A target is best-effort, not a
  guarantee — real speed is bounded by the sources, your connection (much lower over
  Tor), your CPU and the single encrypted writer.*
- **More sources now carry their country.** Hundreds of catalog sources stated their
  country only in their title (e.g. *TASS (Russia)*, *El País (Spain)*, *The Indian Express*)
  but left the structured field blank, so they were invisible to every geographic view. We
  promoted those titles into the real `country` field and added a hand-reviewed pass for
  national outlets, agencies, governments and institutions — lifting coverage across
  under-represented places (Dominica, Grenada, the Marshall Islands, Ethiopia, Ghana, Kenya,
  Qatar and more), with **zero US sources added**. The seeder now honours the
  *Name (Country)* convention automatically. We deliberately leave a source's country
  **blank rather than guess wrong**: a title that names a *topic* (*German History*,
  *Greek History Podcast*), a *language edition* (*Kyodo News (English)* is Japanese), an
  *international* body, or a place an org is merely named after (the US-based *German
  Marshall Fund*) is never mistaken for an origin — a wrong country is worse than none.
- **See a commodity's price next to your coverage of it.** Open a commodity from the
  Markets board (its title or **Analyse ↗**) and the analysis window now offers a **Price**
  tab that lays the **price curve over your corpus's coverage timeline** for that topic —
  each on its own labelled axis, on a shared time line, so you can see *when* coverage rose
  or fell around price moves. It says plainly that this is **co-occurrence in your corpus,
  never causation**, and it never invents a shared scale or a hidden score.
- **A "Trending now" glance on Home.** Home now shows the **past-week rising keywords** at a
  glance, each with a small honest chart, and a click opens that keyword's full analysis
  ("More in Insights →" jumps to the complete Trends view). It's a launchpad, not a new
  number — every item links to where the real detail lives, the rising measure is the plain
  recent-vs-earlier rate (never a score), and the panel simply stays hidden until there's
  something trending.
- **Manage every download from the task manager.** The task-manager window's controls now
  cover **offline-map (OpenStreetMap) region downloads** as well as Wikipedia dumps — pause,
  reorder in the queue, and a new **Resume** for any paused or failed download (resuming
  asks the one network-consent prompt first, since it reopens a connection). Progress shows
  the real bytes and percent; a download rate/ETA is deliberately *not* shown until the
  download itself reports one (no guessed numbers).
- **Zoom into a trend.** Each sparkline in the Insights → Trends "past 24h / week / month"
  panel now has a **maximize** control that opens that keyword's daily series as a full
  interactive chart (zoom, pan, hover-readout) in a dialog — the same honest chart toolkit
  used across the app (it draws bars, not a fake curve, when there are few data points).
- **Read and analyse an article in one place — reader tabs.** The offline article reader
  now opens with a tab bar: **Read · Keywords · Sentiment · Related · Links**. Reading,
  related articles, and the links the article cites are there as before; two new tabs
  analyse just that one article — its top **keywords** (by how often each is mentioned)
  and its **tone** (shown with the honest note that the tone method is English-only, so
  non-English scores are unreliable). Everything stays local, and the analysis tabs load
  only when you open them.
- **Honest "collecting" status in airplane mode.** When you switch airplane mode on while
  a background collection pass is running, the top-bar activity chip now clearly reads
  **"Collecting paused…" in red** (the same colour as the engaged airplane button) with the
  spinner stopped — it can no longer briefly keep showing the green "Collecting…" after the
  network is cut. The chip follows the real collector state by construction, never a
  fabricated one.
- **Two monoliths decomposed (audit PR H — no behaviour change).** The single-page UI
  shed its giant inline blocks: the CSS and JavaScript now live in cached
  `/static/app.css` and `/static/app.js` (a classic script loaded at the same point, so
  the UI behaves identically), shrinking `index.html` from ~9,700 to ~1,680 lines. The
  extraction is reversal-verified — re-inlining reproduces the original byte-for-byte.
  On the backend, every API router registration moved out of `main.py` into a single
  `src/api/_wiring.py:wire(app)` helper; the served API route set is **proven
  byte-for-byte identical**. The externalised assets serve with explicit
  `text/javascript`/`text/css` types on every platform. (Still to come, since they need
  a headless browser or are deeply coupled: converting inline event handlers to
  `addEventListener` + a stricter CSP, and extracting the metrics/CORS setup.)
- **Accessibility + a calmer poll (audit PR G).** Charts now expose a **text
  alternative** for screen readers — every chart carries `role="img"` with a
  translated summary (series, point count, date range, value range) plus a
  visually-hidden data table of the actual points. The always-on background polls
  (network state, collection activity) now use **adaptive idle backoff**: they refresh
  quickly while something is changing and slow down when the app is idle (and pause
  when the tab is hidden), cutting the idle polling load on the encrypted database
  while live state stays fresh via the scheduler/airplane push updates. (Toasts and
  the task-manager/command-palette dialogs already announced and trapped focus.)
- **Deeper test coverage (audit PR F).** Three new unit-isolated test files pin
  previously thinly-tested logic directly (not only via the heavy subprocess torture
  harness): the **backup-merge engine** (FK remap, bit-level dedup, conflict-keeps-local
  -and-reports-both, merge provenance), **every briefing producer's card shape** (valid
  fields/bucket, serialisable, no composite-score key), and the **background
  scheduler's** continuous/idle loop, run-now non-overlap and failure isolation (driven
  by events, not timing). The feed-backoff timing tests gained a skip-when-inconclusive
  guard so a pathologically slow CI box can't redden the absolute-seconds bound while
  the backoff logic stays asserted.
- **`reliability_score` honesty guard (audit PR E).** The per-source
  `reliability_score` (1–10) is **operator-set provenance** — a value *you* assign,
  never a quality verdict the app computes. It's now documented in
  [ETHICS.md](ETHICS.md) as the one intentional exemption to the no-composite-score
  rule, labelled **"operator-set, not computed"** in the UI (with the full
  explanation in the hover, ×12 locales), and locked by a repo invariant so it can
  never quietly become a derived/computed score. *(Default applied; the maintainer
  can choose to retire it from the API instead.)*


- **CI hygiene (audit PR D).** The CI workflow now declares least-privilege
  `permissions: contents: read`, **pins** `actions/checkout`/`actions/setup-python`
  to full commit SHAs (with version comments for Dependabot), adds a **blocking**
  correctness-lint lane (`ruff --select=F,B`, undefined-names + likely-bugs; the full
  style sweep stays advisory), and cancels superseded runs (`concurrency`). Enabling
  the blocking lane meant clearing the pre-existing F/B backlog: proper exception
  chaining (`raise … from …`), dead-import/dead-variable removal, and a couple of
  trivial bugbear fixes — all behavior-preserving (full suite green).


- **Safety & privacy hardening (audit PR C).** Closed a handful of edge gaps:
  the Wikipedia dump **edition code is now validated** before it can reach a
  filesystem path or fetch URL (a `../`/`/` in `wiki` is rejected with a clean 400 —
  path-traversal guard, at both the helpers and the four dump API endpoints); the
  **local LLM (Ollama)** now refuses to run while **airplane mode** is engaged and
  refuses a non-loopback `OO_OLLAMA_URL` (the local model never talks to a remote
  host); **CORS** was trimmed (dropped the dead `Authorization`/`Origin`/`User-Agent`
  allow-headers, shortened the preflight cache); DuckDuckGo discovery now passes its
  result URLs through the existing `http(s)` scheme allowlist; and the broken,
  recipient-capturing **`scripts/import_eml.py`** was removed (it referenced columns
  the live schema doesn't have and stored `To`/`Cc` addresses, against the
  anonymize-at-ingest rule).


- **Documentation accuracy pass (audit PR B, docs-only).** Brought the docs back in
  line with the code: the stale inline-handler figure (an old `onclick`-only count) is
  now the verified **295** (229 `onclick` + 35 `onchange` + 15 `onkeydown` + 14 `oninput` + 2 `onmouse*`)
  across CLAUDE.md and the audit log; the **ETHICS.md GPLv3 checklist** no longer
  overstates per-file headers (most modules carry an SPDX notice; the `LICENSE` file is
  authoritative — GPL needs no per-file header); the dead **`audit/scrape_log.csv`**
  runtime mandate was replaced with the real on-click diagnostics mechanism
  (`data/*_preflight.jsonl` + `field_test.jsonl` → the Settings debug bundle, never
  auto-transmitted); the README's "all 29 audit findings closed" now spells out that
  the `0.07` audit fixed 20 and deferred 9, all closed in `0.0.8` (`findings.csv` reads
  29/29 FIXED); and the **task-manager window** + **Wikipedia tracked-changes timeline
  tab** moved to "In progress / next" to match the RC gate's honest 🔶 (their shipped
  halves stay ✅).
- **Briefing caveats are now visible by default (ethics regression fix).** Each Home
  briefing card showed its **Caveat** only when you turned on a default-OFF "Show
  method & caveat" toggle — a regression against the permanent informed-consent rule
  that caveats are *visible by default, never hidden behind a calm-UI toggle*. The
  caveat now renders inline under every card's summary; the toggle (renamed **Show
  method**) gates only the verbose method/math. The caveat colour is now theme-aware
  so it clears **WCAG AA 4.5:1 on all 17 themes** (the old hardcoded amber failed
  contrast on the light themes); the corpus-tier and chain-of-custody warnings adopt
  the same colour. A new UI invariant (`#23`) locks the visibility in so it cannot
  regress again.

- **Collect, Sources, and Wikipedia moved into Settings (content-first).** The three
  acquisition/configuration tabs left the sidebar; their controls now live under
  **Settings → Collect** (scheduler, manual ingest, batch picker), **Settings →
  Sources** (managed-source list, candidates, add-source form), and **Settings →
  Wikipedia** (change-tracking, watch-a-page, and flagged-changes folded in beside
  the offline dumps that were already there). The sidebar is for *content* —
  acquisition/configuration belongs in Settings. Nothing is lost: the ⌘K palette,
  the on-page buttons, and any old `#ingest` / `#sources` / `#wiki` link all route
  into Settings automatically.

- **A leaner top bar.** The always-on CPU·RAM·↓ vitals strip moved off the top bar
  into the **task-manager window's System tab** (open it with the new task-manager
  button — vitals were already shown there); the raw API-reference (`/docs`) link
  left the bar too (still in the ⌘K palette and the Help tab). The bar is now just
  search · status · task-manager · help · language · airplane. A side benefit: the
  background poll no longer fetches vitals every 5 seconds — only when the
  task-manager window is open or a scrape is running.

- **The airplane (network) button moved to the top bar — icon-only.** It now lives
  in the top-bar status cluster instead of the sidebar foot, as a compact
  icon-only control (no text label): the airplane glyph's **fill** still encodes
  the state and hovering explains it. **Nothing about the safety changes** — the
  same one consent popup fires on every offline→online transition, and the
  onboarding coachmark follows the button to its new home. (UI-shell §3.)

- **New: an Analysis window over your search results (Group F, first slice).** A
  full-screen **Analysis** tab now opens from the Search tab's **Analyze →** button
  (and the sidebar): it shows the **keywords shared across the articles your search
  matched** — each keyword clickable into its own analysis window — and the
  **matched articles** themselves, under one subtab bar. A new article-set endpoint
  (`/api/insights/corpus-keywords`) aggregates keywords over the matched set
  (bounded to the top N by relevance, **disclosed**; counts only, never a score or
  verdict). A **When/Where/Who** subtab shows the people/organisations and places
  deduced across the matched articles (`/api/insights/corpus-www` →
  `corpus_who`/`corpus_where`; deduced from text, never confirmed). A **Links**
  subtab surfaces the outbound URLs **shared by two or more** of the matched
  articles (`/api/links/corpus`) — *shared-origin structure*, stated plainly:
  several articles citing the **same** link are one origin echoed, **not**
  independent confirmation. A **Sentiment** subtab shows the tone distribution of
  the matched articles from the stored per-article score — and **states plainly**
  that the tone method (VADER) is **English-lexicon based**, so it reports the
  English-scored share and warns that non-English scores are unreliable (closing a
  known disclosure gap). A **Sources** subtab shows how each source covers the
  matched set — article **volume**, mean tone, and the publication **span** — side
  by side, stated as *coverage, never credibility* (no ranking, no verdict). An
  **Advanced** tab lets you refine the analyzed set in place — search terms, source,
  language, and a date range — and re-runs every subtab at once (prefilled from your
  search; the groundwork for folding the Search tab in). The Mindmap subtab follows
  in a later slice. ×12 locales; guarded by
  `test_ui_invariants` #22. *(Later in 0.09: this window stopped being a single
  singleton — a search, keyword or Lead now **spawns its own named, closeable,
  persisted analysis tab** (a multi-document workspace), and both the sidebar
  **Analysis** tab and the separate **Search** tab were retired once the omnibar and
  the spawned windows had absorbed their tools.)*

- **Every outbound "source ↗" link opens the local preview first — everywhere.**
  Previously only Home-card evidence routed through the local link preview; search
  rows, the markets board, world-law, the agenda/events, and insights context still
  jumped straight out. They now all use one `extLink()` helper that opens the
  preview popup (what your corpus knows about the URL + a transparent outbound link
  whose text is the full address) before leaving the machine. No surface can
  regress to a bare jump (invariant #6e sweep; `test_ui_invariants`).

- **Windows: backups no longer fail with a file-in-use error.** Creating a backup
  (download, or an encrypted snapshot) made a temp `.db` via `mkstemp` but left its
  file descriptor open while unlinking the path — harmless on Linux/macOS, but
  Windows refuses to delete an open file (`WinError 32`). The three backup sites
  now close the descriptor **before** touching the path. (Also greens the Windows
  CI lane.) Plus CI portability fixes: the path-join test accounts for macOS
  `/private/tmp` and Windows `D:/tmp`, and the POSIX `install.sh` tests skip on
  native Windows (the runner only has a distro-less WSL `bash`).

- **The unlock screen now shows THE brand eye.** The passphrase/unlock screen drew
  a *different* eye (a double-arc + circle) from the rest of the app. It now uses
  the **one canonical brand mark** — the pointed-oval lid + #-grid iris, identical
  to the main UI and `assets/icon.svg`. One identity everywhere. Locked by
  `test_ui_invariants` #5 (now covers `unlock.html`).

- **Airplane-mode transition now shows which way you're crossing.** Toggling the
  network flashed a single red wash for *both* directions — conflating the two
  opposite meanings. Now the flash is **direction-aware**: going **offline** (the
  safe, grounded action) flashes a calm hue (never an alarming red); going
  **online** (the consented one) flashes the live accent. The consent popup and
  airplane semantics are unchanged. Guarded by `test_ui_invariants` #14c.

- **Insights indexes itself — the "Index corpus" button is gone.** Indexing
  already follows ingestion automatically (every new article is indexed as it's
  collected). Now any *legacy* backlog of not-yet-indexed articles is cleared by a
  **silent background top-up** the moment you open Insights — the visible
  "N to index" count simply ticks down to 0 on its own. No button, no manual
  reindex, no waiting-for-a-click; the existing "N/M articles indexed" pill is the
  honest freshness readout. (Removed the button + its command-palette action.)
  Guarded by `test_ui_invariants` #21.

- **The vitals bubble graduates to a Task-manager window.** The activity/vitals
  popover is now a wider, dedicated **tabbed window** (the same universal subtab
  component, its 5th surface) with **Tasks** and **System** tabs — the first slice
  of the long-requested task manager. The proven live job list (Stop/Pause/Cancel,
  dump-queue reorder) and the vitals readout are unchanged underneath; they're
  just organised under tabs in a real window instead of one long bubble. Title is
  now "Task manager". Next slices split Tasks → Active/Queue and add History +
  Sources/Schedule with per-job bandwidth/ETA controls. Guarded by
  `test_ui_invariants` #20. (×12: "Task manager", "Tasks".) *(Later in 0.09: those
  next slices shipped — Tasks split into **Active / Queue / Schedule**, downloads
  gained per-job **resume** and reorder across dumps and offline-map regions, and the
  standalone `/tasks` page was rebuilt into a Windows-Task-Manager-style window.)*

- **Home card families are now a lens, not a wall.** The briefing's card groups
  render a **vertical subtab bar** (the same universal `ooSubtabs` component, now
  on a 4th surface) with **"All cards" as the default** — a single prioritised
  feed — and one tab per family. Each family carries a **color hue**, shown as a
  dot on its tab and a **left accent on every card**, so the feed stays scannable
  even in "All". Cards are also **denser** (4+ fit per row). Completes the Home
  redesign (UI_SHELL_REDESIGN §5). Guarded by `test_ui_invariants` #19b. (×12: the
  one new string, "All cards".)

- **Home opens on its content: a compact stats strip on top, Quick actions gone.**
  The "At a glance" counts (articles · sources · keywords · …) are now a **slim,
  permanent strip pinned to the very top** of Home instead of a large panel pushed
  below the fold, and the **Quick actions** card grid is removed (everything it
  linked to is one click away in the sidebar). Home now leads with the at-a-glance
  strip then the Briefing — denser and content-first (UI_SHELL_REDESIGN §5; the
  card-families-as-subtabs slice follows). Guarded by `test_ui_invariants` #19.

- **One universal subtab grammar across the app.** Insights, Settings and the
  corpus/analysis window each had their own hand-rolled subtab code (different
  markup, different active-state tricks, inline `onclick`s). They now share **one
  reusable component** (`ooSubtabs`): a `<nav class="tabs">` of `data-tab` buttons
  that the component drives with proper **ARIA** (`role=tablist/tab`,
  `aria-selected`), **keyboard** navigation (←/→/↑/↓/Home/End with roving
  tabindex), and the existing hover-bubble + ×12 translation conventions — no
  inline handlers. Same look and behaviour everywhere, and the next surfaces
  (Home families, Markets categories) get it for free. Guarded by
  `test_ui_invariants` #18.

- **Home: the hero card is gone; the onboarding card now speaks 12 languages.**
  The full-width hero ("Understand the world as it really is." + the research-desk
  blurb + three nav buttons, with a time-of-day greeting) took space, served no
  purpose for an installed user, and was hardcoded English — it's **removed**
  (block + greeting JS + the dedicated `.hero` CSS), so Home opens straight on the
  Briefing. The **"Welcome — your corpus is empty" onboarding card** (heading,
  explanation, and "Seed sources" button) is now **keyed ×12 locales**, so it
  translates with the rest of the UI instead of staying English.

- **Commodity cards: the narrow-window data-point bug is fixed (honest sparsity).**
  A commodity card's mini-chart silently swapped in the **entire price history**
  whenever the selected window held fewer than two points — so the *smallest*
  time scale (e.g. "1 month" on a monthly series) paradoxically showed the **most**
  points (the full 5-year curve), while "1 year" showed ~12. The card now
  **respects the window**: `renderDashboard` no longer widens to full history, and
  `dashChartSvg` renders **honestly per invariant #16** — a connecting line only
  when the window is dense enough (`lineMin = 8`), otherwise **discrete dots** with
  the point count `n` and the early-corpus caveat ("dots shown, no curve
  interpolated through sparse points"); an empty window says so plainly. No more
  curve faked through a handful of points, and the smallest scale shows exactly
  the points that fall inside it. (No new strings — the caveat keys already ship ×12.)

- **Airplane-mode onboarding coachmark — teach the one online/offline switch.**
  The app boots offline (airplane mode) by design, which left first-time users
  with no hint how to start. A dismissible bubble (`#net-coach`) now anchors to
  the airplane button and invites *"You're offline. Switch off airplane mode to
  go online and start collecting,"* with a **Go online** and a **Not now**. It is
  the **invitation layer only**: "Go online" routes through the normal
  `toggleNetwork()` → **the ONE consent popup still fires** (`ensureOnline`); the
  coach never flips the network itself (guarded by `test_ui_invariants` #14b). It
  is **prominent on the first two launches, subtle after, capped, and retired for
  good** once you go online or tap "Not now" (remembered locally — never naggy).
  It anchors to the button by position, so it follows the button when the
  top-bar move lands. Ships **×12 locales** (3 new strings; "Go online" reused).

- **Restore is now ADDITIVE-ONLY — the destructive replace path is gone.** A
  journalist's corpus is evidence; a restore must never overwrite it (maintainer
  ruling 2026-06-13). The two destructive "replace the live database" restore
  paths — `POST /api/database/restore` and `POST /api/safety/restore/encrypted`,
  both via `restore_from_bytes` (which did an `os.replace` of the live file) —
  have been **removed entirely** (not merely demoted), along with the functions
  behind them (`restore_from_bytes`, `restore_encrypted_backup`). The **merge
  engine is now the ONLY restore** (`/api/backup/v2/restore/{preview,commit}`):
  it complements the corpus duplicate-lessly, keeps your local version on a
  conflict, and can refuse — but never replaces. The legacy "Restore
  (destructive)" buttons and their "replaces the current corpus" wording are
  retired from Settings (backup *creation* — the raw `.db` and encrypted
  snapshot downloads — stays). A new guard test
  (`tests/test_additive_restore_only.py`) fails the build if any replace-restore
  endpoint or function ever reappears, so the guarantee can't silently regress.
  The torture suite (SIGKILL-mid-merge, atomic swap, crown no-silent-decrypt) is
  unchanged and green — the merge restore it covers is untouched.

- **Downloaded Wikipedia dumps can feed the corpus (the living-source path).**
  Until now a downloaded multistream dump could be *read* one page at a time but
  never *entered the corpus*. `ingest_dump_pages(wiki, titles)` (and the
  `POST /api/wiki/dumps/corpus-ingest` endpoint) now read a **bounded,
  operator-chosen list of titles** from the local dump (offline — no network) and
  upsert each as a corpus article through the **same `index_article` hook** the
  watched-page sync uses (keywords + When×Where×Who follow). Articles are keyed
  on the canonical wiki URL, so a page ingested from a dump and later refreshed by
  the live tracker update the **same row** — no duplicate; per-edition source
  (`Wikipedia (xx)`, `xx.wikipedia.org`) keeps them filterable. The shared upsert
  is factored out of the watched-page sync (`upsert_wiki_corpus_article`), so both
  paths are identical by construction. The list is bounded on purpose — a full
  edition is millions of pages, so whole-dump streaming stays a later slice; honest
  per-title reasons (`no-multistream-dump`, `title-not-in-index`) come straight from
  the reader. `tests/test_dump_corpus.py` builds a tiny, format-faithful dump and
  proves create / idempotent-unchanged / honest-skip.

- **The Back button navigates tabs instead of escaping to the passphrase
  screen.** Tab switching used `history.replaceState`, so it left no history
  entries; and a locked API response did `location.href = "/unlock"`. The only
  prior entry was therefore `/unlock`, so the browser Back button landed the user
  on the passphrase screen. Now each user tab-switch **pushes** a history entry
  (a `popstate` handler re-renders the tab on Back/Forward; the initial load
  still *replaces*, so the first tab isn't a dead Back), and every hop to/from
  `/unlock` uses `location.replace` — the locked redirect and the post-unlock
  return both replace — so the unlock screen never sits in the back stack.
  `tests/test_back_button_nav.py` pins the contract.

- **Corpus-wide WHO: people & organisations across the whole corpus.** The
  When/Where/Who substrate (T12) persists the deduced people and organisations
  per article; a new aggregation now rolls them up to the **whole corpus** —
  `GET /api/insights/who` (and `queries.who_aggregate`) returns the most-seen
  names with **honest counts only**: distinct-article **spread** and summed
  in-text **mentions**, ordered by spread. Filterable by class
  (`person` | `organization`), by window (`days`), and by `country`; `min_articles`
  hides one-offs; `coverage_articles` states the denominator (how many articles
  carry any who-extraction at all). There is **no score** — names are lexical
  surface forms the extractor does **not** disambiguate (same-name people merge;
  a name is not a confirmed identity), so every figure ships with a `method`
  string and the standing caveat *"Deduced from text, never confirmed."* This is
  the ruled corpus-wide WHO aggregation remainder of When/Where/Who.
  `tests/test_who_aggregate.py` proves the counts, ordering, class/window/country
  filters, the `min_articles` HAVING, and the honesty (no score, method+caveat).

- **Windows portability: explicit UTF-8 on every text file read/write.** Eight
  text reads/writes relied on the platform default encoding — harmless on
  Linux/macOS (UTF-8) but a hard crash on Windows (cp1252) with
  `UnicodeDecodeError: 'charmap' codec can't decode byte …` the moment a file
  holds a non-ASCII byte. The primary culprit was the **seed-catalog loader**
  (`yaml.safe_load(path.read_text())` over `configs/sources.yml`, which carries
  accented source names) — plus the law catalog, the coverage targets, the
  settings/sources YAML, an exported sources file, and serving `index.html`.
  All now pass `encoding="utf-8"`, covering **both** the builtin `open()` and
  pathlib's `Path.read_text()`/`write_text()`. This is a **real runtime bug**
  for Windows users, not just a test-lane artifact — surfaced by the Windows
  portability observation lane. A new **static ratchet**
  (`tests/test_utf8_file_io.py`) scans `src/` and fails the build if any text
  read/write (builtin `open` **or** `read_text`/`write_text`) ever ships without
  an explicit encoding again — necessary because the bug is invisible on the
  Linux CI that gates merges (Linux already defaults to UTF-8). Binary opens and
  computed-mode opens are exempt by construction.

- **Corpus-wide WHERE: places across the whole corpus.** The When/Where/Who
  substrate (T12) persists the places deduced per article; a new aggregation
  rolls them up to the **whole corpus** — `GET /api/insights/where` (and
  `queries.where_aggregate`) returns the most-mentioned places with **honest
  counts only**: distinct-article **spread** and summed in-text **mentions**,
  ordered by spread, each carrying the gazetteer **lat/lon** when known (`null`
  otherwise — no fabricated position; `placed` counts the mappable rows).
  Filterable by `kind` (`city` | `country`), by window (`days`), and by the
  place's own `country`; `min_articles` hides one-offs; `coverage_articles`
  states the denominator. There is **no score**, and every figure ships with a
  `method` string and the caveat *"Deduced from text, never confirmed."* — the
  sibling of the corpus-wide WHO aggregation. `tests/test_where_aggregate.py`
  proves the counts, ordering, coordinates, the kind/window/country filters, the
  `min_articles` HAVING, and the honesty.

- **Parallel collection: fetch many hosts at once, politely; write serially.**
  The collect pass can now fetch **different hosts concurrently** via a bounded
  worker pool (`collect_parallelism`, default **1 = sequential, unchanged**;
  raise it to opt in). This is the remaining half of the Tor speedup (parallel
  *dumps* shipped earlier): N concurrent fetches over Tor = N circuits = aggregate
  throughput multiplies — and it composes with per-host stream isolation so each
  concurrent host is on its **own circuit**. The binding guardrail holds by
  construction: the `EthicalFetcher` now takes a **per-host lock** around the
  robots check + rate-limit + GET + body read, so **one host is hit by at most
  one request at a time** (politeness is never traded for speed) while different
  hosts run in parallel. Writes stay safe — each worker uses its **own** DB
  session and writes **serialise through the single-writer gate**, so "parallel
  fetch, serial write" is achieved without a separate writer thread; aggregation
  runs on the consuming thread (no shared-counter races). Kept **opt-in (default
  1)** until field-validated; the task manager will tune it. Exposed in the
  scheduler config API. `tests/test_parallel_collect.py` proves same-host
  serialisation (the politeness guarantee), different-host concurrency, that the
  pool covers every source, and the setting round-trip.

- **Per-host Tor stream isolation: each source rides its own circuit.** Over a
  SOCKS (Tor) proxy, the `EthicalFetcher` now gives **each host its own Tor
  circuit** — a per-host SOCKS username triggers Tor's `IsolateSOCKSAuth`, the
  same primitive the parallel dump downloads use (#110), now applied to ordinary
  collection. This is the safe answer to "protect the user from other sources":
  no exit node or circuit observer can link the user's activity **across**
  different sources, and it needs **no clearnet exposure** (it's Tor Browser's
  "isolate by first-party domain" model). A host's page fetch **and** its
  `robots.txt` share that host's circuit, so the isolation is complete (robots
  is never leaked onto a shared base circuit). It's automatic and on by default
  when a SOCKS proxy is configured (`OO_TOR_STREAM_ISOLATION=0` disables it), and
  a **no-op** for an HTTP proxy or no proxy — the isolation is computed once from
  the *original* host so every redirect hop stays on the one circuit. No new
  anonymity is claimed; this only compartmentalises what the user's proxy already
  provides. The complementary clearnet-for-Tor-hostile-sources hybrid stays an
  explicit, consented, per-source choice (never automatic) — see
  `FUTURE_DEVELOPMENTS.md` → "Reliable Tor & per-source transport".
  `tests/test_tor_stream_isolation.py` proves per-host circuits, distinct
  circuits per host, the robots+page sharing, and the disabled/non-SOCKS no-ops.

- **The single-writer gate: writers serialise, so two never collide on the
  SQLite lock (keystone #1).** The store is single-writer by design, but two
  *writers* still race at the SQLite layer, and a long collection pass could
  hold the writer past `busy_timeout` — the loser then raised "database is
  locked" and historically discarded fetched data (the field-log copper/nickel
  loss; `run_write_with_retry` was the surgical band-aid). The proper fix is now
  in place: a process-wide, reentrant write gate (`src/database/writer.py`)
  through which every write queues *in Python* — only one thread is ever inside
  a write transaction, so SQLite never sees two concurrent writers and the
  timeout never fires. It is wired automatically via SQLAlchemy session events
  (acquire on a session's first `flush`, release on `commit`/`rollback`), so the
  ORM write paths — ingest, markets, wiki, law, the API write endpoints — need
  **no call-site change**; the handful of raw-SQL writes that bypass the ORM
  (VACUUM) take the gate explicitly. The gate is reentrant (a thread can hold it
  across nested sessions), observable (honest `grants`/`contended`/wait-time
  counters that will feed the task-manager System view), SQLite-only (a server
  PostgreSQL backend keeps its own MVCC), and disableable via `OO_WRITE_GATE=0`
  as a field escape hatch. Readers are untouched — a read-only transaction never
  takes the gate, so WAL concurrency is preserved. This supersedes the retry as
  the primary mechanism (the retry stays as defense-in-depth) and is the
  prerequisite for safe **parallel collection** (parallel fetch, serial write).
  New `tests/test_write_gate.py` proves the contract and that six threads
  writing a real file-backed store concurrently never lock and are serialised.

- **Collection efficiency & honesty from the field log (RSS conditional GET +
  discovery commerce filter).** Two fixes from the 2026-06-13 field analysis:
  - **RSS conditional GET (finding F).** At 1-minute collection intervals ~93%
    of feed items were duplicates — the feeds had not changed, yet each was
    re-downloaded and re-parsed every pass. The fetcher now sends
    `If-None-Match` / `If-Modified-Since` (from per-feed validators) and treats
    **`304 Not Modified` as a valid result** (empty body, not a `FetchError`);
    `ingest_source` stores the `ETag`/`Last-Modified` per feed in a new
    `feed_fetch_state` table and **skips parsing entirely on a 304**. The table
    is separate from `sources` on purpose — `create_all` materialises a missing
    *table* on every existing database at boot, so there is no ADD COLUMN
    migration to run and no "no such column" risk in the collection hot path
    (validators are opaque HTTP tokens, stored and echoed verbatim, never
    parsed). Backward compatible: a plain fetch sends no conditional headers and
    behaves exactly as before. (Per-feed *backoff* for feeds that never send an
    ETag is deferred to the continuous-collection batch, where the scheduling
    lives.)
  - **Discovery no longer suggests storefronts (finding D).** Citation discovery
    had surfaced `shop.popsci.com`, `store.popsci.com` and
    `popularscienceprints.com` — merch, not journalism. A conservative,
    explainable filter (`is_commerce_domain`) drops candidates with a leftmost
    `shop.`/`store.`/`buy.` label, a `.shop`/`.store` commercial gTLD, or a
    `…prints` name. Discovery candidates are never auto-enabled, so the only
    cost of a rare false positive is one un-suggested domain.

- **Continuous collection + airplane-mode boot + per-country fair ordering
  (content-first, the field-test "scraping stopped" fix).** Three linked changes
  realise the maintainer's ruling that *"scraping should never stop"* and the app
  should *"boot offline, then collect continuously once the operator says go"*:
  - **The app now boots in AIRPLANE MODE (offline) every time** — startup engages
    the offline state explicitly, so nothing scrapes until the operator crosses
    online once (the one consent, `POST /api/scheduler/start`). Zero-network boot
    was already a non-negotiable; it is now *explicit and visible* in the airplane
    toggle. The old "autostart at boot" is retired by this ruling (boot is always
    offline). Gated by `OO_NO_SCHEDULER`, so tests/headless setups are untouched.
  - **When online, collection is CONTINUOUS.** The scheduler no longer runs one
    pass and then idles `interval_minutes` (which is exactly why a field tester
    saw scraping "stop" — it was idling, not crashing). With `continuous=true`
    (the new default) passes run back-to-back with only a short, interruptible
    gap, so while online the corpus fills permanently. `continuous=false` restores
    the old run-once-then-wait cadence.
  - **Per-country round-robin ordering** (`round_robin_interleave`) reorders each
    pass so every country gets a turn before any country gets a second — one
    source per country, then repeat. This breaks the US-volume bias *structurally*
    (equal turns per country, not turns proportional to how many sources a country
    has). Within-country order is preserved; sources without a country share one
    bucket; nothing is ever dropped. The activity/plan preview reflects this order
    honestly. (Parallel fetch, the onboarding country/language picker, and demoting
    the cross-kind arbitration modal to a silent queue are the next Group-B slices.)

- **Parallel, circuit-isolated dump downloads (the Tor speed fix for dumps).**
  Dump downloads ran strictly one at a time (`max_concurrent = 1`), so over Tor
  a single slow circuit was the ceiling — 56K-modem speeds. Now up to
  `max_concurrent` dumps download **in parallel** (default 3, env-tunable via
  `OO_DUMP_CONCURRENCY`); dumps write files, not the DB, so there's no
  single-writer contention. Crucially, each download carries a **per-stream
  SOCKS token** (its URL), so Tor's `IsolateSOCKSAuth` gives each its own
  circuit instead of sharing one — aggregate throughput actually multiplies.
  The T9 reorderable queue is **preserved**: when more dumps are requested than
  the capacity, the excess queues and stays prioritisable (fr-before-en still
  works). Slot accounting is race-safe (a slot is claimed under the lock before
  launch), and a stale `downloading` status from a killed process is demoted to
  `paused` (resumable) on reload. Bounded + conservative because dumps share one
  host — per-host politeness is never traded for speed.

- **No per-run source cap — collection covers EVERY source.** The scheduler
  capped each pass at `max_sources_per_run` (clamped 1–1000), which silently
  *selected* which sources to skip — a selection that can't be justified
  (maintainer 2026-06-13). The cap now defaults to **0 = unbounded**: rss/crawl
  passes, market rules, and watched wiki/law items all cover everything, every
  pass; a positive value is still honoured as an explicit soft cap. The
  "Max sources / run" control is removed from the UI. (Ordering still decides
  what runs *first* — the bandwidth priority ladder — but nothing is excluded.)
  Implemented via a shared `capped()` guard (`src/database/query.py`) because
  SQLite `LIMIT 0` returns nothing, the opposite of "no limit".

- **One guarded socket factory: the kill switch and proxy now cover every
  fetch path (closes a transport leak).** Four paths — Wikipedia dump
  downloads, the MediaWiki API client, ORES scoring, and the gated DuckDuckGo
  discovery — built their own bare `requests` sessions, so **airplane mode did
  not stop them** and, worse, the in-app proxy was **not applied**: a user who
  set Tor only in the app (not the OS) would have had multi-GB dump downloads
  egress over **clearnet** — a silent transport downgrade the project forbids.
  They now all route through `src.safety.fetcher.guarded_session`, a
  `requests.Session` subclass that checks the global kill switch on **every**
  verb (so it cannot be forgotten) and applies the protected-mode proxy. The
  stale hardcoded `OpenOmniscienceBot/0.4` User-Agent is replaced by the honest
  version from pyproject (Wikimedia's API mandates a descriptive bot UA, kept
  even over Tor; the DuckDuckGo HTML endpoint keeps its browser UA). The
  socket-importer ratchet allowlist shrinks **6 → 3** (only the EthicalFetcher,
  loopback Ollama, and the factory itself may import an HTTP client now).
  New `tests/test_guarded_session.py` pins the three guarantees and proves all
  four consumers are wired through the factory.

- **No fetched data is lost to a transient database lock.** A field session
  (2026-06-13) caught commodity prices that were **fetched successfully over
  Tor and then discarded** — copper, aluminum, nickel, zinc all stored with
  `OperationalError: database is locked` because the import's commit lost the
  single-writer race against a long-running collection pass (which can hold the
  writer past the 30 s `busy_timeout`), and the import gave up on the first
  error. The write is now wrapped in `run_write_with_retry`
  (`src/database/write.py`): on a transient lock it rolls back and re-runs the
  idempotent unit of work with exponential backoff + jitter, so the points
  persist instead of vanishing. Non-lock errors still surface immediately;
  this is the safety net ahead of the single-writer queue that will remove the
  contention entirely.

- **CI made deterministically green again (pinned tools + real fixes).** Two
  unpinned linters had drifted and were reddening **every** PR with no code
  change, each masking the next:
  - **mypy** (unpinned floor) reported one extra error (129 > 128). Pinned to
    `mypy==2.1.0`; baseline lowered to **127** after fixing the two genuine
    latent bugs the type errors flagged — the HTTP 429 handler read
    `exc.retry_after`, absent on slowapi's `RateLimitExceeded` (the handler
    meant to degrade gracefully would itself raise `AttributeError`), and an
    article metadata row called `html.escape()` on a possibly-`None` region.
  - **bandit** (unpinned) then failed on `B314`: `src/wiki/dumpread.py` parsed
    Wikipedia dump XML with the stdlib parser, vulnerable to entity-expansion /
    XXE attacks. Fixed for real — the dump (untrusted network input) is now
    parsed with **`defusedxml`** (a genuine defense, not a suppressed warning),
    and bandit is pinned (`bandit==1.9.4`).

- **Installer: the passphrase moment, fixed live.** The one-line
  `curl | bash` install crashed at "Initialising the database" on a fresh
  machine — encryption-by-default means a new store NEEDS the user's
  passphrase choice, which a blind non-interactive init cannot make. The
  installer now: tries env-driven init first (existing stores,
  `OO_DB_PLAINTEXT`/`OO_DB_PASSPHRASE`); otherwise **asks on a real
  terminal** (reading `/dev/tty`, so it works under `curl | bash`):
  encrypted with confirm-twice, the honest no-recovery warning and length
  guidance, or plaintext behind a typed `PLAINTEXT` confirmation with the
  risk stated, or defer; with no terminal it **defers honestly to the
  in-app first-launch prompt** — starter sources seed themselves at the
  first unlocked boot, so nothing is lost. Never a traceback, never a
  silent default.

- **V0.1 alpha preparation: the reflective plans (docs).** Two
  maintainer-commissioned analyses landed: **user-centric reflections**
  (FUTURE_DEVELOPMENTS — six personas, six contradictions faced honestly,
  deduced features A1–A9 with the Claim Workspace as flagship: a guided
  evidence-trail pipeline answering "is this true?" without ever issuing a
  verdict) and the **transversal audit 07**
  (`docs/audit/07_TRANSVERSAL_AUDIT_V01.md` — tool-by-tool science/truth/
  disclosure table, tamperability incl. source-side cloaking, long-use
  performance unknowns, ranked missing sources, neutrality as
  representation-vs-declared-baselines, ten named aggregator biases and
  which updates can fix, steps B0–B7). Plus the recorded superseding
  Wikipedia ruling: edition-wide automatic tracking after a dump download
  (per-article tracking to be retired) — design + filed questions, not yet
  implemented, per instruction.

- **Wikipedia pages become first-class corpus articles (the living-source
  bridge, maintainer-ruled 2026-06-12).** Watched pages now enter THE corpus:
  one article per page (canonical wiki URL) under a per-edition "Wikipedia
  (xx)" source, carrying the **newest version** of the text — the tracker
  refreshes `latest_text` (+ the revid it corresponds to) whenever edits
  land, and the corpus row re-indexes idempotently through the one
  `index_article` hook, so **general full-text search, the keyword
  aggregator and When×Where×Who all follow the latest version
  automatically**. Wikitext is reduced to plain text by a bounded, stated
  lexical strip. `POST /api/wiki/corpus/sync` backfills existing watchlists
  locally (zero network). Migration `b6c7d8e9f0a1`. Honest gap recorded as
  now-blocking for the full version engine: stored revision diffs are
  truncated summaries, not reconstructable patches — the per-revision
  storage decision (full text vs patches+checkpoints) is elevated in
  FUTURE_DEVELOPMENTS, and the dedicated tracked-changes tab is the named
  next slice.

- **Local-first link previews on Home cards (T16 slice 1 — invariant #6
  extended, first target).** External evidence links on Home cards no longer
  jump straight out: they open a **local preview** first — what your database
  already knows about the URL (known source, a stored local copy with the
  reader link, how many of your own articles cite it with examples, tracked
  law/Wikipedia matches, the local copy's top keywords) — built from local
  reads only and saying so. The outbound anchor's **visible text is the full
  URL**, and clicking it still passes the external-link confirmation popup
  (layered consent). Enforced in the invariants suite (#6e). +12 chrome
  strings ×12 locales.

- **Offline dump reader (T14 slice 1) + the ruled dump-list limit.** New
  Wikipedia dump downloads default to the **multistream** form and its tiny
  companion index rides along automatically — that pair is what makes a
  downloaded dump *readable*: Settings → Wikipedia gains **"Read a page from
  a downloaded dump"**, which scans the index for the title, decompresses one
  small block at its byte offset, and shows the page's raw wikitext entirely
  on this machine (zero network; scan stats shown; a case-insensitive match
  is offered and labelled; legacy single-stream files are honestly reported
  as non-seekable with a re-download hint). The dump-download language list
  is now **limited to the app's languages** (the 12 UI locales + the
  stoplist-evidenced corpus languages) per the maintainer ruling — the
  watched-pages edition picker keeps the full curated list. +17 chrome
  strings ×12 locales; 9 new tests against a format-faithful synthetic
  multistream dump built in-test.

- **The omnibar (T13 slice 1).** The Ctrl/⌘-K command palette now federates
  over the corpus itself: `/api/search/omni` serves the first three hits per
  group — articles (FTS5, relevance-ordered), keywords (indexed prefix),
  sources, watched Wikipedia pages, tracked law documents — **with the true
  totals disclosed in each group header** (the display bound never hides the
  magnitude). Index-backed only, never scan-on-type; a half-typed Boolean
  ("drought AND") falls back to a phrase match instead of erroring
  mid-keystroke. Article hits open the LOCAL reader first; keyword hits open
  their corpus window; "Run the full Boolean search" hands off to the Search
  tab prefilled — nothing the Search tab does is lost. A discreet Boolean
  reminder sits at the palette's foot (hover carries the long form). +8
  chrome strings ×12.

- **Weather corroboration cards — "if this, then SUGGEST user to fetch"
  (maintainer-asked 2026-06-12).** When ≥3 collected articles mention the same
  climate-event word (curated 12-language seed vocabulary,
  `configs/corroboration_rules.yml`, provenance in-file) together with the same
  deduced place inside one time window, a Home card in the *investigate* bucket
  OFFERS an independent check — it is computed locally and states "this card
  made no network call". The fetch is one bounded (place, window) Open-Meteo
  ERA5 reanalysis slice (`POST /api/weather/context`), triggered only from the
  card's button behind the one consent popup, through the single ethical fetch
  path (kill switch, robots fail-closed, protected-mode proxy inherited);
  results render one chart per variable (mixed units on one axis would be a
  fabricated comparison) with CC BY 4.0 attribution, the
  reanalysis-not-station-truth note and the disk cache disclosed; transport
  failures return the honest verdict taxonomy. +7 chrome strings ×12 locales.
  Slice 1 of the Open-Meteo layer (see FUTURE_DEVELOPMENTS). Alongside it, the
  **Open Commons Mirror sister project** (server-scale open-data preservation,
  the "reliable memory" pillar — tamper-evident by hashes and transparency
  logs, tamper-resistant by independent replication) is recorded as a designed
  concept with the maintainer's intent and open questions.

- **Performance batch (maintainer field report 2026-06-12: 6.4k articles /
  228k keywords / 243 MB corpus got "very slow"; the keyword export failed).**
  Measured on a synthetic corpus of exactly that shape (`scripts/perf_harness.py`,
  deterministic, in-process, zero network), fixed, re-measured — same machine,
  comparative numbers: **keyword diagnostics export 14.1 s → 4.0 s** (encrypted
  profile 33.8 s → 7.8 s) and **streamed** (bounded memory, immediate first
  byte; envelope byte-compatible, contract-tested); **Home briefing recompute
  36.6 s → 1.5 s** (the MinHash inner loop was 95% of it: exact numpy
  vectorisation with a parity-tested pure fallback + a memo across the three
  producers that cluster the same window, audit finding F-005); insights map
  ~550 ms → ~215 ms (tuple aggregation instead of ORM entities). Mechanics
  shipped: a covering index on `keyword_mentions` (model + migration
  `e2f3a4b5c6d7` + boot self-heal for installs that never run alembic);
  per-language cap applied BEFORE the work (semantics unchanged); statement
  deadlines on the heavy read path (typed 503 — "aborted after N s" — never a
  hung UI; `OO_STATEMENT_TIMEOUT_S`, default 60); `PRAGMA optimize` + bounded
  first-boot ANALYZE at startup; `mmap_size` for PLAINTEXT stores only (never
  through the SQLCipher codec — that speed-up cannot exist, so it is not
  claimed); Library/coverage counts cached 30 s with `computed_at`/`cache_ttl_s`
  disclosed in the response; and a **Settings → Database maintenance** tool
  (VACUUM + optimize) reporting real freed bytes, with "reclaimable space" from
  `PRAGMA freelist_count` (+8 chrome strings ×12 locales).

- **Agenda astronomy layer (T11 slice 1).** Full and new moons computed
  **locally** with the standard Meeus algorithm (ch. 49, periodic + planetary
  corrections) — zero network, zero data files — and **verified against gold
  references in the test suite**: the book's own worked example (49.a, the
  February 1977 new moon) to within ~26 seconds, and the published 2024
  almanac full-moon dates. `/api/events/astronomy?year=` serves the phases
  with `method` and `accuracy` fields (ΔT non-application stated, never
  hidden); the agenda month grid shows moon glyphs whose hover bubble carries
  the method — informed consent down to the moon. +2 chrome strings ×12.

- **When×Where×Who persists at ingest (T12, the convergence substrate).**
  The date/place/entity extractors — reader-only until now — persist their
  deduced candidates **at indexing time** through the one `index_article`
  hook, so live ingest, re-index and backfill all anchor them: new
  `article_mentioned_places` and `article_entities` tables (people and
  organizations separate by design), every row carrying **snippet provenance
  and the rule note** that decided it, idempotent per article, and a
  deduction failure never blocks keyword indexing (tested). Deduced stays
  labelled deduced — never promoted to fact.

- **Seasons + the climate record (T11 slice 2).** Equinoxes and solstices
  computed locally (Meeus ch. 27, verified against the book's example 27.a
  to ~9 s and the published 2024 dates) with **hemisphere-honest naming** —
  "June solstice", never "summer solstice": seasons are opposite across
  hemispheres and undefined at the equator, and the payload says so. The
  bundled **El Niño episode dataset** (`/api/events/climate`) follows the
  NOAA CPC ONI convention with per-file provenance and an explicit
  **verification-pending flag** — drafted entries are never presented as
  verified before the clearnet check. IPCC-as-a-source with
  prediction-tracking ("were their anticipations right after all?") and
  agenda↔Wikipedia linking recorded as designed concepts with filed
  questions.

- **Markets/indices: transport-aware honesty (the 2026-06-12 Tor diagnosis).**
  Feed failures now carry a **verdict taxonomy over the real error**:
  *refused* (connection refused/reset — over Tor commonly one exit's refusal;
  the live log imported 21/28 FRED series while others failed in the same
  run) ≠ *robots-disallowed* (the host's choice, honored, never retried or
  evaded) ≠ *dead-series* (HTTP 404/410 — the catalog entry needs a verified
  replacement; retrying cannot help) ≠ *unreachable* ≠ *offline* (kill switch
  engaged). Transient verdicts get ONE bounded feed-level retry on top of the
  fetcher's own backoff; policy verdicts never. The Indices/Markets boards
  list each failure with its verdict and honest note, and a **Retry failed
  feeds** button re-runs exactly the honestly-retryable keys
  (`import-all?keys=`). The dead World-Bank-monthly FRED ids
  (PGOLDUSDM/PSILVUSDM/PSAWMUSDM) now surface as *dead-series* instead of
  undifferentiated failures — replacements await clearnet verification (this
  build environment cannot reach FRED to verify; honesty over speed).
  USER_MANUAL gains the "Running over Tor" chapter. +5 chrome strings ×12.

- **Settings: backup v2 becomes the UI's primary path (the OS-grade mandate's
  last user-facing mile).** Data & backup now leads with the signed archive:
  one passphrase-encrypted file carrying everything (plaintext only as a
  deliberate, explained choice that excludes signing keys), and **Restore =
  merge with a preview**: upload → dry-run plan table per data domain (new /
  already present / conflicts-kept-local, with conflict samples), the
  verification verdict up front, Apply disabled when verification fails (the
  engine would refuse anyway — the UI does not invite it), one-shot commit
  token, safety snapshot stated, import history visible. The legacy
  replace-style tools are demoted into a collapsed "older tools" block —
  available, never silently lost. ~36 chrome strings ×12 locales; UI contract
  pinned by tests. *(Later in 0.09: this single encrypted file hit the AES-GCM
  ~2 GiB ceiling on large corpora, so the **volumes + parity** large backup was
  added for those (see the entry at the top); and the demoted replace-restore
  "older tools" were **removed entirely** — restore is now additive-only.)*

- **Network switch → airplane mode + online consent (field report #2 item 1).**
  The sidebar toggle is now ONE constant airplane glyph whose **fill is the
  state** (filled = offline engaged) — action glyphs no longer label state.
  **Every offline→online transition passes a single consent popup**: it names
  the action ("Start a collection pass…", "Fetch market and index data…",
  "Download a Wikipedia dump"…) and lists the machine's **local interface
  addresses** read from the kernel's tables (`/api/system/interfaces`,
  psutil) — never a public-IP echo before consent, because that would itself
  be a network call; the popup says honestly that the public address is
  whatever the ISP/VPN presents, unchecked. Scheduler responses now carry the
  network state, so the toggle repaints **immediately** on implicit
  transitions (collect-start clears the kill switch) instead of waiting for
  the 5 s poll. Kill-switch reliability gains a build-failing **socket-importer
  ratchet**: exactly six modules may import an HTTP client (the guarded fetch
  path, loopback Ollama, the gated discovery channel, three wiki fetchers);
  any new direct importer fails the suite until consciously routed through the
  fetch path. UI invariant #14 enforces all of it; +15 chrome strings ×12
  locales.

- **Keyword policy: the three systemic findings from field report #4.**
  (1) **Source self-names are suppressed at extraction** as a per-article
  rule, never a stoplist: a keyword equal to the article's OWN outlet name
  ("The Moscow Times" ×213 in the live export) or domain label is byline/
  footer boilerplate and is skipped — while the same term mentioned by OTHER
  sources stays a real keyword, so coverage *about* an outlet is untouched.
  Re-indexing applies it retroactively (indexing replaces an article's
  mentions). (2) The diagnostics export gains **per_source_concentration**:
  keywords whose articles sit ≥90% in one source while covering ≥25% of that
  source's articles (both sides ≥10) are listed as boilerplate/navigation
  suspects — the Swedish "alla artiklar" ×118 shape — with real counts and
  stated thresholds, strongest first, capped at 200; flagged, never
  auto-hidden. (3) Every exported keyword carries **language_mismatch**:
  true when the stored language disagrees with the signature's dominant
  article language (the de-tagged-English attribution noise) — evidence for
  the operator, never a silent correction.

- **A permanent language switcher in the top bar.** All 12 locales in one
  menu — conventional flag as a visual cue only, the **native name** is the
  identifier (flags ≠ languages); one click re-translates the entire UI
  through the one exact-match engine, keeps the Settings selector in sync,
  and persists locally. Constant top-bar footprint; RTL-aware menu placement.
  UI invariant #15 enforces it.

- **The one chart toolkit (`ooChart`), slice 1.** Interactive charts as
  ruled: cursor-anchored **wheel zoom through time**, **drag-pan**,
  hover/click → exact **pinned X/Y readout**, double-click reset, legend
  chips that toggle series — with the detailed-curves rules built into the
  component: the **full-resolution series always renders** within the visible
  window (never downsampled), and **sparse series render as honest points**
  (n shown, early-corpus caveat, a line only when ≥8 points support it — no
  curve interpolated through 3 dots). Labelled discrete gridlines via the
  shared formatter; ISO week/month buckets parsed natively. Wired first onto
  the markets symbol chart and the Insights keyword trend; UI invariant #16
  enforces the rules. +4 chrome strings ×12.

- **The universal "hover for information" convention.** One consistent,
  theme-aware affordance across the whole UI: anything carrying layered
  information shows a **dotted accent underline** (text) or a **tiny accent
  corner dot** (buttons, pills, icons), and opens one shared styled bubble on
  hover, **keyboard focus, or touch long-press** — capabilities the native
  tooltip never had. Marking is automatic (driven by the translated `title`
  mechanism + a MutationObserver), so new surfaces inherit it and it cannot
  be forgotten; the bubble re-reads the live translated text, so all 12
  languages work by construction. One delegated listener and pure CSS —
  no per-element handlers, no animation loops. UI invariant #17 enforces it.

- **Task manager + download arbitration, slice 1 (the twice-repeated ask).**
  Every network task is now a **visible job**: `/api/jobs` aggregates live
  from the owning systems — the collection pass, every Wikipedia dump with
  its real queue position, the fetch currently on the wire (domain only) —
  deliberately keeping no shadow state, so the view cannot disagree with
  reality. The dump downloader becomes a **true queue** (one download at a
  time; later requests genuinely queue, persisted across restarts) with
  **operator reordering** — the "fr before en" case works end-to-end (↑↓
  buttons + API, tested). The activity-chip popover is now **Tasks &
  collection**: jobs with progress bars and Stop/Pause/Cancel (stopping
  collection states its kill-switch side effect — informed consent), the
  detailed collection panel, hardware vitals as the compact bottom row. New
  heavy starts **ask** when another network task runs (who is busy, proceed
  or wait) — never a silent pile-up. +18 chrome strings ×12.

- **The corpora system, slice 1 — the Links substrate + the window.** A
  keyword now opens as a **corpus window** (⊞ Corpus next to the resolved
  term): Trend (the interactive toolkit), member Articles, and **Links** —
  the anti-false-triangulation view: which member articles **share outbound
  links**, with per-URL independence notes ("a shared origin means agreement
  is ONE path, not independent confirmation") and distinct-source counts.
  `/api/links/shared` serves counts and structure only, never a credibility
  verdict; the method travels in the response. +12 chrome strings ×12.

- **De-US-centring the source catalog (the cycle's KEY POINT, first batch).**
  Three real defects fixed at the root: (1) `Source.country` had a silent
  `default="US"` — every source created without an explicit country was labelled
  American (the live-test "US = 1,553" inflation; the canonicalised catalog's real
  US share is ~14%). The default is gone; unknown is now honestly NULL. (2) Mixed
  country encodings ("US" / "us" / "united-states") across five tables. (3) The
  keyword-mention indexer truncated legacy values into *wrong* codes
  ("china"→`ch`=Switzerland, "germany"→`ge`=Georgia), corrupting the temporal
  map's geography. **One conversion layer** (`src/catalog/countries.py`: all 249
  ISO 3166-1 codes + names + aliases + continents, iso-codes-derived, dependency-
  free) now canonicalises every write path (seed, CSV import, metadata, mention
  indexing) to lowercase ISO-2 and renders **full country names** everywhere
  user-facing. Migration `a3b4c5d6e7f8` canonicalises existing databases,
  re-derives default-suspect US values from the catalog/ccTLD (else NULL — the
  value was never asserted), and rebuilds mention geography from the corrected
  sources. The shipped catalogs (1,750 entries) are rewritten canonical, with a
  regression test rejecting any drift. The Library tab's World coverage panel
  gains **Regional balance** — per-continent sources + countries-covered against
  the working floors in `configs/catalog_targets.yml` (labelled aspirations,
  drafted from the real catalog shape) and a top-country **concentration guard**;
  `scripts/catalog_coverage_report.py` prints the same acceptance metric offline.
  Sources/coverage APIs return `country_name`/regions and accept full-name
  filters; the tab anchor is now `#library` (legacy `#database` links redirect);
  the coverage panel polls live (Refresh button retired). +14 chrome strings ×12
  locales.

## 0.08 part 2 — the sense-making horizon

Part 2 of the `0.08` cycle (the whole roadmap push ships under `0.08` per maintainer
direction; plan: [`docs/archive/releases/RELEASE_0.0.8_PLAN_PART2.md`](archive/releases/RELEASE_0.0.8_PLAN_PART2.md),
WP1–WP5 all delivered):

- **Methods appendix** (*Search → Methods appendix*): one click turns the current search
  into a Markdown document carrying the app version, the **verbatim** query, and a
  provenance row per article (source · date · URL · content SHA-256) — optionally with the
  signed evidence bundle in the same response, so a fact-checker hands over document +
  proof together. Records selection only; asserts no conclusion (and says so).
- **Versioned export contract** (`oo-export-1`): JSON exports are self-describing envelopes
  (schema, app version, generated-at, the exact generating query, count); CSV columns stay
  byte-identical with the same provenance as `X-OO-*` headers. Plus a **citation-graph
  export** (`/api/links/export.graphml` / `.json`): the who-cites-whom graph, counts only,
  the no-inferred-credibility caveat embedded in the file; opens in Gephi/yEd/NetworkX.
- **Scheduler accountability**: every run — success *and* failure — appends one auditable
  line to `scheduler_runs.jsonl` (served by `/api/scheduler/runs`); an **opt-in drop-folder
  export** writes each run's new-articles delta as envelope JSON into a local folder a
  newsroom pipeline can watch (empty = off, the default).
- **Corpus synthesis** (*Search → Synthesize results*): one local-model call across ≤ 20
  articles — shared facts, disagreements, open questions, with numbered citations back to
  the members; stored per member with model + prompt-version provenance; "assistance,
  never a verdict" travels with the output.
- **Offline source discovery** (RM-19, first increment): the app stages source
  *candidates* from two network-free channels — domains your articles repeatedly cite, and
  packaged-catalog outlets for thinly-covered countries. Transparent by construction:
  every candidate carries its evidence, runs are budgeted (`discovery_per_run`) and logged,
  a Home card announces what awaits review, and **promotion still creates a disabled
  source you must enable**. The DuckDuckGo channel deliberately does not exist yet — it
  ships only behind the external-lookup gate once this staging UX has proven itself.
- New table `source_candidates` (migration `a9b8c7d6e5f4`); +33 tests across the part.

## 0.08 — executing the product roadmap: trust gates + investigation recipes

The `0.08` cycle executed the post-audit product roadmap
([`docs/archive/releases/RELEASE_0.0.8_PLAN.md`](archive/releases/RELEASE_0.0.8_PLAN.md), WP1–WP9 all
delivered) and closed **every remaining audit finding — the register reads 29/29 FIXED**.

- **Investigation recipes (the headline).** The Home briefing gains three space-time
  scenario cards, computed entirely from your own corpus (producers never touch the
  network): **Promises due** (an article mentioned a date that was *in the future* when
  published — it has now arrived), **Edit-war burst** (a tracked Wikipedia page editing at
  ≥3× its own prior weekly rate), and **Region gone quiet** (a usually-covered country
  stopped arriving — honestly caveated as a fact about *your corpus*, not the region).
  Each card carries an **"Open investigation ↗"** button that opens a dedicated dashboard
  (`/investigate`) **in a new browser tab** — related panels auto-assembled from existing
  APIs, the card's caveat verbatim at the top, and a "Go deeper" strip where every
  suggestion is a manual action with its parameters shown. Fully URL-parameterised:
  shareable, re-openable, several investigations in parallel while the main UI stays free.
  The card schema guard extends to recipes: score/verdict-shaped parameters are
  mechanically rejected. Per-recipe switches live in **Settings → General**.
- **The one external call is now opt-in.** *Discover by topic* (the only feature that
  contacts a third-party service — it sends your topic query to DuckDuckGo) is **disabled
  by default** and refuses with an honest message until enabled in **Settings → Safety →
  External topic discovery** ("Your query leaves this machine"); `OO_DISCOVERY_EXTERNAL=1`
  for headless use. RSS discovery of your own sources stays local-path and ungated.
- **Weekly security cadence.** CI runs bandit + pip-audit every Monday on a schedule, so a
  freshly published CVE surfaces without waiting for a push.
- **`Mapped[]` ORM migration.** All 296 columns across the 26 models moved to SQLAlchemy
  2.0 typed mappings with **zero schema drift, proven** (byte-identical before/after schema
  dumps, committed as evidence). mypy fell 303 → 128 errors, and CI gained a **type-check
  ratchet**: the error count can never rise again.
- **Test depth.** +42 tests: the politeness-delay arithmetic (fake clock), endpoint
  coverage for the last untested routers (reporting — including evidence-bundle **tamper
  detection** — LLM HTTP layer, framing, keyword management), the discovery gate, the
  recipes, and a new repo invariant: **no `print()` in library code** (CLI surfaces
  allowlisted), enforced forever.
- Suites at cycle close: **858 passed / 6 skipped** (full) and **754 / 6** (core-only).

## 0.07 — full audit cycle (hardening, truth-up, performance)

A six-phase, evidence-driven audit of the whole repository (baseline → architecture →
quality → stabilize → optimize → docs; reports in [`docs/audit/`](audit/), findings in
[`docs/archive/audits/findings.csv`](archive/audits/findings.csv)). 29 findings: 20 fixed, 9 deferred with
rationale. Highlights:

- **Ethics invariant restored (ETH-01, the audit's one real invariant breach):** RSS-feed
  *discovery* used to fetch pages with raw `requests`, bypassing robots.txt, the SSRF
  guard, and per-host rate limiting. It now goes through the same `EthicalFetcher` as all
  ingestion, with regression tests proving robots-fail-closed and SSRF refusals apply.
  The one remaining external call — *Discover by topic* querying DuckDuckGo — is now
  explicitly documented as a user-triggered, opt-in exception (`docs/SECURITY.md`).
- **Safe-by-default config:** `.env.example` rewritten to the real `OO_*` surface
  (previously advertised `0.0.0.0` binds, a wildcard Ollama CORS, an auto-download that
  doesn't exist, and JWT/auth secrets for an auth system that doesn't exist); Config
  defaults now loopback; the app version is single-sourced from package metadata
  (was reported three ways: 0.02 / 0.03 / 0.0.7).
- **Performance (measured, `scripts/benchmark_audit.py`):** dropped a B-tree index over
  the full article body that no query used — **a 50k-article DB shrinks 354 → 130 MB
  (−63%)** (migration `f1a2b3c4d5e6`; run `make migrate` on existing databases).
  Recency-browse verified at p50 1.3 ms on 50k rows; near-duplicate clustering verified
  linear (no O(n²)).
- **Reliability:** the fetcher now retries *transient* failures (network errors, 429,
  5xx) with bounded backoff — never 4xx or robots/SSRF refusals — staying rate-limit
  polite. New regression tests for the body-size cap, redirect cap, and DNS-rebinding
  refusal.
- **A core-only install is now green:** analysis-dependent tests skip (instead of
  failing) when the `[analysis]` extra is absent.
- **Dead code quarantined:** six packages (~4,400 LOC: `ingestor`, `scraper`,
  `custom_types`, `compliance`, `audit`, `reports`) moved to `quarantine/dead_src/`;
  `bandit -r src/` now reports zero issues.
- **CI:** runs on every pushed branch (the old trigger was pinned to `0.04` and silently
  skipped pushes to the default branch); adds a core-only-install job, plus bandit and
  pip-audit gates.
- **Docs truth-up:** `docs/ARCHITECTURE.md`'s fossil "NOT FUNCTIONAL / conceptual only"
  database section replaced with the verified reality (SQLite supported and tested;
  PostgreSQL honestly labelled untested scaffolding with no search); doc sprawl
  consolidated (`NEXT_VERSION` merged into `ROADMAP`, presentation archived, ~68 MB of
  legacy audit dumps pruned from the tree — retrievable from git history).
- Lint/format: `ruff --fix` + `ruff format` across the tree (887 → 312 advisory
  remainder); style debt no longer obscures diffs.

## 0.07 — space & time, and a calmer GUI

The `0.07` cycle threads the separate verticals (news · insights · law · markets) onto a
shared **space-time** spine and tidies the interface. *(This entry covers the space-time /
GUI slice; other `0.07` work — events agenda, hazards relay, keyword super-groups,
personality, i18n — ships in sibling pull requests.)* Nothing weakens the local-first,
no-server, no-telemetry posture; every new surface states its limits.

- **Temporal map (new tab).** Every locatable, datable signal on one zoomable
  equirectangular world map under a **time slider** from antiquity to the near future:
  curated historical/scheduled **anchors** (`configs/world_timeline.yml`), your **geocoded
  corpus** (publication date), **dates mentioned in article text** (extracted), and opt-in
  live **hazards**. Density strip + play, per-kind legend, semantic-zoom labels, persisted
  layer/window prefs, click-for-detail with a **"Find coverage in your corpus"** cross-link
  and a **"Near in space & time"** panel (co-occurrence, *never* cause). **Honest by
  construction:** a pin needs *both* a coordinate and a date (no coordinate → no pin);
  country-level pins flagged approximate; scholarly date doubt carried in the note.
  Offline **coastlines** via `scripts/build_world_outline.py` (public-domain Natural Earth;
  lat/lon graticule fallback — never fabricated). `GET /api/timemap` (+ `/range`).
- **Article date-tags.** A high-precision extractor (`src/timemap/dateextract.py` — explicit
  dates only; no bare years or relative phrases) turns the dates a story is *about* into
  **per-article tags** in a dedicated table (`article_mentioned_dates`), each a **candidate
  with its provenance snippet**, **confirmable/rejectable** in the offline article reader and
  **filterable** across the corpus (`GET /api/article-dates/by-date`). `/api/article-dates/...`.
- **Customize → Settings.** The floating "Customize" drawer becomes a first-class
  **Settings → Appearance** section; Settings is reorganized into **Appearance · General ·
  Wikipedia · Data & backup · Safety**. Both standalone Customize buttons removed to free the
  chrome; the sidebar footer gains a **Settings** shortcut.
- **Discoverability.** A Home **"See it in space & time"** scenario card and an Insights-map →
  Temporal-map link.

## 0.06 — Phase B: safety, sense-making, accessibility & governance

A second slice of the `0.06` work, organised around four themes from
the "Next version — action plans" section of [`ROADMAP.md`](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md). Each ships an honest Phase 1 today; none weakens the
local-first, no-server, no-telemetry posture. See [`GOVERNANCE.md`](GOVERNANCE.md).

- **At-risk-user safety (`src/safety/`).** New **Settings → Safety** panel and `/api/safety`
  routes: a passphrase **encrypted backup/restore** (AES-256-GCM + scrypt — reuses the
  audited crypto primitives; a wrong passphrase or tampered file fails *loudly*, never
  silently); a **panic wipe** that overwrites-then-deletes the corpus, keys and caches
  (honest about the SSD/copy-on-write limit — only full-disk encryption guarantees a true
  wipe); and a **Protected fetch mode** that sends a generic User-Agent through a proxy you
  run (e.g. Tor), labelled with its honest limit — *we cannot guarantee anonymity*. Also a
  `panic` CLI and an `--ephemeral` run mode (RAM-only data dir, wiped on exit).
- **Story lineage — "trace to the primal source" (`src/signals/lineage.py`).** For a
  near-duplicate cluster echoed across many outlets, reconstruct the **primary → first
  report → echoes** chain by publication time, detect **wire attribution** ("according to
  Reuters", "(AFP)"), and surface the structure so original reporting is foregrounded over
  derivative echoes. Honest bright line: *"earliest we saw" ≠ "the truth"* — it shows
  structure; the human judges. New Home producers **Story lineage** and **Coverage advisor**
  (surfaces geographic/linguistic skew in *your* collection — a suggestion, never a filter).
- **Accessibility & i18n.** A keyboard **skip-to-content** link, ARIA landmarks/labels on
  navigation and icon-only buttons, a polite **live region** for toasts, `aria-current` on
  the active tab, and a keyboard-operable command palette. New chrome strings translated to
  the complete locales (de/es/fr now 100%); `scripts/i18n_report.py` measures locale
  coverage and can gate CI.
- **Governance & acceptable use ([`GOVERNANCE.md`](GOVERNANCE.md)).** A statement of purpose
  and explicit **dual-use red lines** (no individual tracking, no biometric ID, no
  private-channel ingestion, no automated verdicts, no central server, no silent filtering —
  *absent by construction, not configurable*), enforced by a **red-lines tripwire test** in
  `tests/test_repo_invariants.py`.

## 0.06 — the intelligence layer (Phase A: the Home briefing)

The first slice of the `0.06` "intelligence layer" — the **GUI spine**. The unifying
idea is *one measurement engine, many domains*; this ships the engine's framework and
its first pure primitive, and turns **Home into a triage briefing**. Guiding docs:
[`ROADMAP.md`](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md) (what & why) and
[`ROADMAP.md`](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md) (how); user guide: [`USER_MANUAL.md`](USER_MANUAL.md).

- **`src/signals/` — pure, DB-free measurement primitives.** First shipped:
  `concentration` (Gini coefficient + top-N share), property-tested with exact
  hand-computed values and honest *undefined → None* behaviour (no fabricated zeros).
  The *same maths* intended for media-ownership and people-prominence concentration.
- **`src/briefing/` — the card + briefing framework.** A `Card` is one measured signal
  + evidence + method + caveat, sorted into an editorial bucket. A **producer registry**
  makes every feature `corpus → [Card]`, so new capabilities appear in the *same* feed.
  Producers **degrade loudly** (return nothing + log) when inputs/optional deps are
  absent — never a fabricated card.
- **Home is now the briefing:** cards grouped by bucket (*rising · overtold · undertold
  · investigate · check-the-framing · watch · context · data-integrity*), with triage
  (dismiss/restore, reversible) and a **method & caveat** transparency toggle. Built on
  the existing tested shell — same element IDs, no functional regression.
- **"Now"-status producers (no new math, real numbers):** Rising (trending),
  Framing-split (per-source VADER tone of a trending term), Record-reshaped (Wikipedia
  flagging), Price↔narrative (honest scipy correlation), Stale-data (market-rule
  freshness), and **Diet self-audit** (the new `concentration` primitive over *your*
  sources).
- **Card → draft → newsletter:** pin cards into a draft accumulator (+ your notes) and
  **export Markdown** in which every claim carries its source links, method and caveat —
  reproducible journalism. Custody receipts referenced via Evidence & custody.
- **Performance:** precompute → cache → serve cached. The briefing never computes per
  request; the scheduler refreshes it after each scrape (`briefing_cache.json`).
  Dismissals/draft are small local JSON files — single-user, local-first, never sent.
- **Honesty guard *in code*:** `assert_no_score_fields()` rejects any `Card` field that
  implies a composite trust/quality score (the §6 ban) — enforced at import and by a
  test. Numeric values live in `signal` as a single measured quantity with a method,
  never a blended score.
- **API:** `/api/briefing` (cached feed), `/refresh`, `/dismiss`·`/restore`, and the
  `/draft` accumulator with `GET /draft/export.md`. New in-app doc `USER_MANUAL.md`.
- **Tests:** `test_signals_concentration.py`, `test_briefing.py`, `test_briefing_api.py`
  — full suite green; no regressions.

### Phases B–E — the signal substrate, source integrity, annotations, verticals

- **`src/signals/` complete (Phase B):** the pure, DB-free measurement substrate —
  `near_dup` (MinHash + LSH near-duplicate clustering), `coordination` (an actor graph
  from near-dup co-publication + lockstep timing + shared host), and `novelty`
  (information contributed vs an incremental corpus index). Property-tested on crafted
  fixtures (a syndicated story collapses; an independent original stays separate; a pure
  echo scores ~0 novelty).
- **Source integrity & anti-amplification (Phase C, `src/integrity/`):** the §6 keystone.
  A per-source **profile of measured dimensions with NO composite score** (enforced by a
  test); **user-guided actor-collapse** — the app *proposes* collapsing a coordinated
  flood with its evidence, the user *disposes* (per-cluster or global), every applied
  collapse stays flagged + expandable, reverting reproduces the raw equal counts exactly,
  and **no collapse is applied without an explicit action**. The 40-puppet-flood
  acceptance is a passing test. New cards: **echo-chamber**, **lonely-signal**,
  **capacity-implausible**. New **Source integrity** GUI tab. See `USER_MANUAL.md`.
- **Crowdsourced signed annotation bundles (Phase D, `src/annotations/`):** publish
  source annotations (ownership/leaning/coordination/corrections) as a **hybrid-signed,
  portable bundle** (reusing the custody signer); import the bundles you trust (opt-in
  **web of trust**); **transparent aggregation** shows *who asserted what* and surfaces
  dissent, never averaging it into a score. A tampered bundle is refused. See
  `USER_MANUAL.md`.
- **World-law change-tracking vertical (§5, `src/law/`):** a **worldwide catalog of real
  official primary sources** (national legislation databases, official gazettes, IP
  offices, open case-law/filing systems — `configs/legal_sources.yml`) seeded **by
  default**, ingestible/searchable through the same ethical pipeline. A curated set of
  consolidated-law documents is tracked for change (baseline → normalised-text diff →
  honest large-change flag, reusing the Wikipedia engine), exposed via `/api/law/*`, a new
  **World law** GUI tab, and a `law` scheduler mode. New cards: **law-change** (watch) and
  **model-legislation** (cross-jurisdiction near-dup). New `LawDocument`/`LawRevision`
  tables via Alembic migration. A research mirror, never legal advice — every record links
  to its official gazette. See `USER_MANUAL.md`.
- **Phase E (composable cards):** **emotion-category** measurement around a keyword
  (`src/awareness/emotion.py`, lexicon-based, ships a minimal English sample, overridable
  via `OO_EMOTION_LEXICON`, degrades loudly); **IP/legal news cards** (IP-litigation
  pulse + ownership-change deal-language).
- **Novelty-weighting (§6 D, opt-in):** `story_prominence(weight_by_novelty=True)` and
  `/api/integrity/prominence?weight_by_novelty=true` additionally down-weight
  low-information echoes — off by default (anti-amplification stays user-guided, never
  silent), the equal view reproduced exactly when off.
- **Honesty guards everywhere in code:** no composite trust score on a Card, a Source
  profile, or an annotation kind; anti-amplification is never silent; aggregation never
  averages dissent.
- **i18n:** new chrome strings added to the maintained locales (en/de/es/fr); the
  English-fallback design keeps every other locale working.
- **Tests:** `test_signals_near_dup.py`, `test_integrity.py` (incl. novelty-weighting),
  `test_annotations.py`, `test_awareness_emotion.py`, `test_law.py` (+ A's tests). Full
  suite green.

## 0.05 — full interface redesign (now the default branch)

A ground-up redesign of everything the user sees, built on top of the existing,
tested data layer (same endpoints, same element IDs — no functional regression).
Reasoned from the personas outward in [`docs/DESIGN.md`](DESIGN.md).

- **New shell:** a collapsible **sidebar grouped by intention** (Investigate ·
  Collect · Trust · System) replaces the flat tab strip; a slim top bar carries
  live status and the command-palette trigger.
- **Renamed for humans:** *Ingest → Collect*, *Database → Library*, *Chain of
  custody → Evidence & custody*; **Markets** is marked advanced and can be hidden.
- **New Home dashboard:** orientation for non-technical users — at-a-glance counts,
  scheduler state, and big quick-action cards.
- **In-app Help/docs reader:** renders the User Manual (and other guides) inside the
  app, offline, with find-on-page — backed by a new read-only, allow-listed
  `/api/docs` endpoint.
- **Command palette (Ctrl/⌘-K):** jump to any tool, run common actions, or open any
  doc, all by typing.
- **Live customization drawer:** 8 themes, accent swatches, density, text size,
  sidebar collapse, and per-tool visibility — stored locally only, never transmitted.
- **Refined visual system:** token-based theming, depth, motion, accessible focus
  rings, responsive/off-canvas layout — still 100% dependency-free (no CDN, no web
  fonts, no framework), so it runs fully offline.

### Toward 50,000 sources — honestly

- **Political-spectrum catalog (`configs/sources_spectrum.yml`):** ~280 new, real,
  well-known outlets across ~95 countries / ~30 languages, hand-tagged by **leaning**
  (lean-left … lean-right) and **ownership** (public-broadcaster / state-media /
  wire-agency) with topic keywords — the editorial dimension Wikidata can't provide.
  Merged at seed time (de-duped by domain); leanings are reputational, contestable
  and easy to override.
- **Generator tuned for scale:** `configs/catalog_query.yml` now targets ~50k+ —
  ~249 countries × broader media types at `limit: 5000`. The honest path to tens of
  thousands of *real, attributable* sources is running the Wikidata generator (and
  `--merge-csv` for GDELT/Media Cloud), **not** fabricating dead RSS URLs. See
  `docs/ROADMAP.md`.

### A contradictory take + a second interface to compare

- **`docs/DESIGN.md`** argues the *opposite* case — that a polished,
  customizable "console" may be the wrong fit for a sovereign, offline,
  trust-first tool — and proposes an antithesis.
- **"Desk" (`/desk`, `src/static/desk.html`):** a calm, editorial, content-first
  alternative interface. No persistent sidebar (navigation is on-demand via a
  job-framed home + a ⌘K jump overlay), two opinionated themes (Ink/Paper), serif
  typography, a reading-width column, and a persistent "nothing leaves this
  machine" trust line. It shares the *exact* engine and content panels with the
  default ("Console") interface, so the comparison isolates the philosophy.
- **Two installer icons:** `install.sh` now creates **Console** and **Desk**
  launchers (distinct icons); `scripts/launch.sh` takes a `console|desk` argument
  and detects an already-running server, so both can run side by side on the same
  data. New read-only `/desk` route serves the alternative.

### Coverage honesty, branch hygiene & docs alignment

- **`docs/ROADMAP.md` — a coverage ledger.** Names every blind spot and labels it
  *voluntary* (deliberate) or *involuntary* (to be measured). **Images and all
  visual/binary media are now an explicit, documented exclusion** (owner's choice:
  storage on one affordable machine, and honest image analysis isn't feasible at
  scale) — already enforced by the crawler's `_SKIP_SUFFIXES`. Also records the
  social-media exclusion, paywall/robots policy, and the planned register-
  triangulation + capture–recapture method for *sizing* the unknown.
- **No work lost across branches.** `0.05` (branched from `claude/kind-lovelace-ulpTc`)
  already contained the chain-of-custody feature; the only artifact unique to `0.04`
  was `docs/PRESENTATION_PUBLIC.md`, now cherry-picked onto `0.05`.
- **User Manual aligned to the 0.05 interface:** sidebar groups, the command palette
  (⌘K), Customize, the Home dashboard, the in-app Help/docs reader, the two
  interfaces (Console `/` and Desk `/desk`), and the renamed tools (Ingest→Collect,
  Database→Library, Chain of custody→Evidence & custody).

### Multilingual UI, link co-citation, and measurable coverage

- **Multilingual UI wired (i18n Phase 2):** `i18n.js` is now included in both Console
  and Desk, with a **Language** picker (12 languages) in Settings. Dynamically-
  rendered chrome is translated automatically via a debounced `MutationObserver`;
  English fallback for untranslated strings; RTL via `<html dir>`. (Behaviour still
  wants a browser pass.) Complete reference translations ship for en/fr/es/de; the
  rest are selectable English-fallback stubs.
- **Article link detection wired (link analysis P0/P1):** ingest now populates
  `article_links` with outbound **external** links (best-effort, fail-open;
  internal/image/ad/social/tracker excluded; `OO_NO_INDEX=1` disables). New
  read-only `/api/links` endpoints — `stats`, `top-cited` (url|domain, windowed),
  `articles-by-link` — answer "which articles cite the same source." Counts only,
  no scoring (the old fabricated link analyzer stays quarantined).
- **Coverage made measurable:** honest **ccTLD inference** (`src/catalog/cctld.py`)
  backfills missing `country`/`language` at seed time (generic/ambiguous ccTLDs stay
  unknown), lifting country-tagged coverage ~19% → ~33%; and **source provenance** is
  recorded as a `via:<origin>` tag — first steps of the `ROADMAP.md` measurement plan.

## Unreleased — UI polish, live data, and a full user manual

A wave of usability work on top of the feature set below, plus documentation:

- **Live, animated data:** the active tab refreshes itself on an interval while on
  screen — live article/database counts, scheduler state, Insights indexing
  progress, and Wikipedia tracking — with smooth count-up tweens for headline
  numbers.
- **Sources / Database split:** the old combined tab became two — **Sources**
  (add + a filterable, sortable, paginated management table with inline
  enable/priority/delete and CSV import/export) and **Database** (live honest
  stats + clickable World-coverage view).
- **Scheduler-first Ingest tab:** automatic ingestion (start/stop/scrape-now, RSS /
  crawl / markets / Wikipedia modes, language/type/tag targeting with a **Preview
  targets** action) is the primary surface; manual feed/URL ingest sits below.
  Empty-DB onboarding banner with a one-click first run.
- **Markets dashboard:** analysis-first cards with adjustable time scales and
  out-of-the-box curated data; the feed/rule configuration is tucked into a
  collapsible "most users won't need this" section.
- **Offline article view** + framing surfaced in Insights.
- **Insights keyword filtering:** stronger multilingual stopword removal plus a
  user-editable exclusion list (Settings → Keyword filtering, and ✕ in Insights).
- **Wikipedia language picker moved to Settings**, **grouped by continent**
  (Europe/Asia/Africa/…, largest editions first within each), expanded to ~147
  editions across all continents (plus a "Constructed" bucket), with a
  **type-to-filter** search box; it also accepts any free-text edition code.
  `src/wiki/languages.py` gained a `region` field + `languages_by_region()`, and
  `/api/wiki/languages` now returns both a flat list and a continent-grouped
  `groups` form.
- **Docs:** added an extensive end-user manual ([USER_MANUAL.md](USER_MANUAL.md))
  covering every tab, control, setting, workflow, env var and API area, and an
  [ROADMAP.md](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md) capturing in-flight design decisions
  (notably a planned chain-of-custody "automatic, background, dummy-proof"
  redesign — not yet built).

## Unreleased — tabbed UI, markets, worldwide coverage, insights, wiki

A large feature wave (all tested; dependency-free vanilla-JS UI; no fabricated data):

- **Tabbed UI + management:** Sources & Database (live stats, source management,
  world coverage), Settings (theme + SQLite **backup/restore**), in-app
  **scheduler** (start/stop, rss/crawl/markets modes) and a **bounded recursive
  crawler** (same-domain discovery, robots fail-closed, depth/page caps).
- **Markets:** per-source **price-extraction rules** (numbers only from a verified
  CSS selector — `Test` action), **official CSV price feeds** (FRED→World Bank/EIA)
  + custom-URL import, charts and honest price↔news correlation, and a packaged
  worldwide markets catalog. See [USER_MANUAL.md](USER_MANUAL.md).
- **Worldwide source catalog:** a **data-derived generator** (Wikidata CC0 +
  optional GDELT/Media Cloud) for news + institutions per country, coverage report,
  and **CSV import/export** of the source list. See [ROADMAP.md](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md).
- **Insights — keyword & entity analytics:** extraction at ingest (people/orgs/
  places as single units; opt-in spaCy), a mention store with context, and
  trends / PMI associations / per-country-city map. See [USER_MANUAL.md](USER_MANUAL.md).
- **Wikipedia change-tracking (foundation):** per-language editions, delta storage
  (diffs not re-copies), and honest large-edit/revisionism flagging (incl. ORES).
  See [USER_MANUAL.md](USER_MANUAL.md).

New migrations: `b7c1d2e3f4a5` (market rules), `c3d4e5f6a7b8` (keyword mentions),
`d4e5f6a7b8c9` (wiki tracking).

## Unreleased — honest chain of custody (Phase 5)

The deferred "signed chain-of-custody reporting" pillar, built honestly and made
operator-configurable:

- **Custody core (`src/custody/`):** an append-only, hash-chained, **signed** log
  of actions on an item; **hybrid Ed25519 + post-quantum ML-DSA** signatures with
  AND semantics and honest labels (never a silent downgrade); "existed no later
  than T" timestamping via a self-asserted local clock or Bitcoin-anchored
  **OpenTimestamps**; pluggable anchoring (offline `local` default, OpenTimestamps,
  and public-chain providers that refuse honestly rather than faking receipts).
  Offline verification via `scripts/verify_custody.py`.
- **GUI-configurable settings (`src/custody/settings.py`):** post-quantum signing,
  anchoring mode, and auto-log-on-ingest are now runtime-editable from a **Chain of
  custody** web-UI panel and `GET/PUT /api/custody/settings`, persisted to
  `custody_settings.json`. The API/UI always report the **effective** state
  (preference *and* library availability), so PQC/OpenTimestamps can never appear
  enabled when the supporting extra is absent. Auto-log defaults to the legacy
  `OO_CUSTODY_ON_INGEST` flag until a preference is saved.
- Documented in [USER_MANUAL.md](USER_MANUAL.md); endpoints added to
  [ARCHITECTURE.md](ARCHITECTURE.md).

## 0.4 — Trustworthy core + honesty pass

A near-total rebuild around a small, genuinely-working spine, plus a ruthless
audit/debug pass. Highlights:

**Core (Phases 0–1):** single `pyproject.toml` on Python 3.13; clean DB session
layer (no import-time side effects, WAL); one ethical fetch path (robots.txt
fail-closed, rate-limited) → trafilatura extraction → dedup + provenance; real
SQLite **FTS5 Boolean search** (AND/OR/NOT, phrases, precedence); CSV/JSON export;
dependency-free offline web UI; Qubes-aware installer; honest docs.

**Capabilities (Phases 2–5):** local LLM via Ollama (HTTP, loud 503 degradation);
commodity prices + **real scipy correlation** (no fabricated p-values); real
source-uptime monitoring + z-score anomalies; IMAP email into the unified corpus;
honest EXIF metadata verification; **Merkle + Ed25519 signed evidence bundles**
with a standalone verifier.

**Phase 6 — repository honesty:** purged ~19k lines of fabricated/dead code (live
ratio 36%→68%); removed the hallucinated LLM model catalog; auto-seed the full
~1,780-source catalog on first run; Alembic migration path with a CI drift gate;
salvaged Pillar-2's genuine statistics into `src/analysis` and **quarantined the
remaining pillars** (intent preserved — see PILLAR_INTENT_MAP).

**Full re-audit (2026-06):** quarantined the fabricated `link_analyzer` stack;
fixed broken endpoints and salvaged-stat bugs (chi-square crash, regression CI,
odds-ratio); closed the evidence-verification trust hole (pinned key + full-item
Merkle + domain separation); fixed email charset corruption, ingest rollback
isolation, the core-only-install boot, and the whole P2 backlog (DI to
`Depends(get_db)`, shared rate limiter, bounded uploads, cache/url/regex/compression
fixes). See [HISTORY.md](HISTORY.md). 400+ tests, all green.

## 0.01–0.03 (historical)

Early concept releases (forked from HTTrack). Largely non-functional / design-only;
superseded by the 0.4 rebuild. Retained only in git history.
