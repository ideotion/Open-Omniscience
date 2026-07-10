# Autonomous build brief — Scalable data-management architecture + source-IP geolocation

Companion to `docs/design/DATA_ARCHITECTURE_SKELETON.md` (the architecture-of-record).
This is the paste-ready brief for an autonomous Claude Code session that builds the
**decided, safe, high-value** slices. It deliberately defers the parts still gated on a
VERIFY item or a maintainer ruling (the WARC archive, eviction, the authentication-evidence
capture). Decisions ratified in the 2026-06-19 design session.

---

## Mission

Build the **scalable data-management layer** (so a decade-old corpus stays fast on a
2-core / 6 GB machine **without hiding or losing any data**) and the **source-IP capture +
offline geolocation + map layer**. Small, additive, reversible slices — **one draft PR per
slice onto `0.09`, stacked, CI-subscribed.** The maintainer merges; nothing self-merges.

## First, orient (mandatory)

1. **Read `CLAUDE.md` in full** — the binding ledger and working mode. Follow THE PROTOCOL:
   record every new ruling in `CLAUDE.md` the same turn; extend
   `tests/test_repo_invariants.py` for any critical invariant.
2. Re-cut every branch from a **freshly fetched `origin/0.09`** (it goes stale within
   minutes).
3. The live DB is **not** auto-alembic'd: every schema change needs a migration **and** a
   boot-time `ensure_*_columns` self-heal. Full pytest needs the **py3.13** venv;
   `node --check` any JS; keep `i18n --min 100`; keep `mypy` ≤ baseline.

## Maintainer rulings — 2026-06-19 (decided context)

- **Cross-time recall is sacred.** No feature may bias toward recent data, default to a
  recent window, or make old data slower-to-reach or second-class. Time-partitioning is
  **abandoned** unless proven byte-identical with no recency bias — do not build it.
- **Performance must NOT depend on hiding data.** Speed comes from *maintained counters + a
  derived columnar read-model*, with **every article fully present and searchable always.**
- **Honesty envelope mandatory** on maintained aggregates: `{value, basis: exact|estimated,
  as_of, method, n}`. `basis` is a **disclosure, not a score** — `assert_no_score_fields`
  stays green.
- **Derived columnar store = persisted + encrypted under the SAME passphrase** as the
  canonical store (one `connect()` factory; no second key surface; invisible to the user).
  It is a **disposable cache**; the SQLCipher store stays the source of truth. **Never write
  a plaintext derived file** — if encryption can't be proven, fall back to in-memory.
- **Capture posture = default-anonymize + opt-in high fidelity** (do not reverse
  anonymize-at-ingest).
- **Source IP wanted**, geolocated **offline** onto the map, with heavy honesty caveats.
- **Tiered-retention eviction is designed but NOT built this session** (needs the archival
  format first; default-off; index/analytics/metadata stay hot, only raw text relocates to
  a local archive, transparent on-open fetch, reversible).

## Slices (each = one or more draft PRs onto `0.09`, in dependency order)

### Slice 1 — Honesty envelope (foundation)
- Reusable helper (`src/analytics/envelope.py`) → `{value, basis, as_of, method, n}`;
  serialization convention for maintained aggregates.
- **Acceptance:** helper + test; `assert_no_score_fields` passes (`basis` not a score);
  `as_of` real, never fabricated.

### Slice 2 — Maintained keyword counters (SQLite-only, no new dependency)
- Add `Keyword.mention_count`, `Keyword.article_count`, `Keyword.last_reconciled_at`
  (migration + self-heal). Maintain on the **single-writer** index path. A **bounded
  background reconcile** (where `warm_cache` runs) recomputes exact + stamps
  `last_reconciled_at`. Hot endpoints (`top`, `supergroups`, `trending`) read counters via
  the **Slice-1 envelope**: `exact` when fresh, else fall back to the cached live `GROUP BY`
  marked `estimated`.
- **Cascade-delete honesty:** `ondelete=CASCADE` bypasses ORM hooks → drift possible;
  deletes are rare (corpus is additive); reconcile repairs it; unreconciled = `estimated`,
  **never silently wrong**.
- **Acceptance:** counter ranking identical to live `GROUP BY`; injected drift shows
  `estimated` then repairs to `exact`; counter read is O(keywords), not a mention scan (the
  real win vs the 132 s freeze). Tests cover maintain-on-ingest, reconcile, envelope basis,
  single-writer, no-score.

### Slice 3 — A1 read-model seam (interface only)
- Route whole-corpus aggregate reads through ONE documented boundary
  (`src/analytics/readmodel.py`) so the columnar store (Slice 4) plugs in **without touching
  endpoints**. v1 wraps the current counter-backed queries: behavior byte-identical.
- **Acceptance:** single entry point (tested); responses unchanged. Thin, irreversible seam.

### Slice 4 — Derived columnar engine: persisted + encrypted DuckDB (likely 2–3 stacked PRs)
- **Engine bring-up:** a persisted DuckDB store (e.g. `data_dir()/analytics.duckdb`)
  **encrypted under the same passphrase** via the one `connect()` factory. DuckDB must run
  **fully offline** — extension autoload **disabled**, no network on open (test asserts it).
- **Encryption gate (must pass):** create the store with a sentinel; assert (a) the sentinel
  is **absent** from the raw file bytes, (b) open **without** key **fails**, (c) open
  **with** key returns it. Cite DuckDB's documented AES backend in the PR.
- **Hard fallback:** if the gate fails or offline can't be guaranteed → fall back to
  **DuckDB in-memory** (rebuilt lazily on first analytics use). **Never** persist a plaintext
  derived file.
- **Incremental maintenance + reconcile:** new articles' aggregates are added to the store
  at index time (off the request path); a periodic full reconcile repairs drift; the
  **honesty envelope** discloses the brief windows where it's behind.
- **Endpoint integration (behind the Slice-3 seam):** port the heavy whole-corpus
  aggregations (`associations`, `graph`, `framing`, `supergroups`, `trending`/
  `trending-windows`, `map-coverage`) to read from the columnar store; **identical
  results**, sub-second.
- **Invariant:** the canonical store stays the source of truth; a missing/cold derived store
  **falls back to the live query** (slower, never wrong). Add a test that the
  trusted/canonical correctness path never *depends* on the derived store (it's an
  accelerator). Excluded from backups (rebuildable).
- **Acceptance:** results match the pre-columnar endpoints exactly; cold/missing store
  degrades to live query; encryption gate + offline test green; no score; envelope basis
  preserved.

### Slice 5 — K1/K2 identity seams (cheap, additive; do NOT touch existing dedup)
- (K2) `Article.canon_version` stamping which canonicalization produced `canonical_url`.
  (K1) `Article.content_multihash` (self-describing, e.g. `sha2-256:…`) **alongside** the
  existing `Article.hash` — **never reformat `Article.hash`** (unique, dedup-load-bearing).
  Populate forward + backfill.
- **Acceptance:** new articles carry both; dedup unchanged; backfill works; additive tests.

### Slice 6 — Source IP capture + offline geolocation + `ooMap` server-location layer (3 stacked PRs)
- **6a — Capture:** record the **server IP we connected to** at fetch (hook the single fetch
  path; `getpeername()` on clearnet). **Over SOCKS/Tor the real server IP is unavailable** →
  store `server_ip = null` + reason `"unavailable (proxy/Tor)"`, never a guess. Columns
  `server_ip`, `ip_observed_at` (+ self-heal). Docstring caveat: the IP is **our vantage
  point**, usually a **CDN edge / anycast**, not the publisher.
- **6b — Offline geolocation, two levels:** bundle a dated **CC-licensed country-level** DB
  (DB-IP Lite CC BY 4.0 or IP2Location LITE CC BY-SA 4.0) in-repo with `IP_GEO_AS_OF` +
  freshness test + attribution. The **city-level** DB is too large for the repo → a
  **one-time consented download into `data_dir`** via a fetch action (like wiki dumps/
  models), **never at boot**. Lookup (`src/geo/ip_geo.py`) prefers city when present, falls
  back to country, returns `{country, lat, lon, level, db_vintage}`. **No live API ever**
  (fixture test proves zero sockets). **VERIFY** exact license/size before bundling.
  Re-geolocation = a new vintage, never an overwrite.
- **6c — Map layer:** a switchable **`ooMap` "server location"** layer, visually distinct
  from the editorial `Source.country` layer. Caveats **visible by default**: *server
  location, often a CDN edge / anycast — not the publisher; approximate; dated DB;
  unavailable over Tor; never proof of true origin.* Surface clustering (many "independent"
  sources sharing one host/ASN) as a **shape to investigate, never a verdict** — the
  network-layer cousin of the existing coordination/source-laundering detection.
- **Acceptance:** clearnet records a real IP, Tor records the honest "unavailable";
  geolocation runs with **zero network** (tested), city falls back to country; map renders
  with caveats visible; vintage + level recorded; freshness test green; `i18n --min 100`
  (new strings keyed, non-en AI-drafted + flagged).

## Defer (do NOT build; one-line ledger note + reason)
- **WARC/BagIt archival format, `age` outer envelope, SLIP-39** — durability/encryption
  workstream.
- **Tiered-retention eviction** — needs the archive first; default-off; the guarantees above.
- **TLS chain / SCTs / CT corroboration + provenance Tier vocabulary** — authentication-
  evidence workstream.
- **Time-partitioning** — abandoned unless provably result-invisible.

## Invariants that bite this work
- **No composite scores**; envelope `basis` is a disclosure. **Caveats visible by default**
  (IP/geo + estimated-counter), never behind a toggle.
- **Zero network at boot and at geolocation-lookup time.** Geo-DB (country) bundled; city DB
  and any map asset fetched by a one-time consented action, not at boot.
- **The derived columnar file is encrypted under the same passphrase or it is in-memory —
  never plaintext on disk.**
- **Single-writer gate** for every canonical write; **reads never gate** (WAL); the derived
  store's writes stay off the request path.
- **Additive + reversible**; migration **and** self-heal per column; never reformat
  `Article.hash`; never fabricate an IP, location, or exact count — degrade loudly.
- One PR per slice, **draft onto `0.09`**, stacked, CI subscribed; mark UI PRs
  **"browser-unverified, needs click-through."** Update
  `docs/archive/releases/RELEASE_0.1_RC_GATE.md` rows you touch.

## Close-out
Update `CLAUDE.md` with the session rulings + a Shipped-batch-log entry per slice (verdict +
pointer). Hit a genuine maintainer ruling (not a build detail)? **Skip-and-note** it, don't
guess.
