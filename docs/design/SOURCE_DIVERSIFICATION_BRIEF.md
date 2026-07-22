> **Status update (2026-07-22, docs-audit remediation pass):** verified against live `main` by a subagent fan-out audit of the whole `docs/design/` tree — confirmed NOT executed — this brief's dedicated 14-cluster live-network run has never happened. English-source share is 68.8% as of 2026-07-22 (2358/3429), down from the brief's 73% baseline, but that drift is incidental (most likely from the unrelated law-catalog acquisition batches), not from a diversification run. See [`ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md`](./ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md) for the full remediation plan.

# Source diversification brief — language & region equilibrium

**Purpose.** The collected corpus runs ~79% English because `configs/sources.yml` is
~73% English by source count (2,345 / 3,205). The honest fix is upstream: add many
**real, live-verified** non-English / non-Anglophone-region sources so the initial
repartition is healthier. The goal is an **honest equilibrium reflecting digital-content
reality — NOT equality** (many outlets in e.g. India publish in English; that is real —
set `language: en`, `country: in`).

**Where to run this.** A **local Claude Code CLI checked out in this repo**. That is the
only environment with all three prerequisites: (1) open egress so `curl` auto-decodes gzip,
the UA dodges bot walls, and `robots.txt` is readable; (2) the real `configs/sources.yml`
for domain dedup; (3) `pytest tests/test_source_taxonomy.py` to enforce the tag gate.
The Claude chat app is NOT suitable — it has no subagents, restricted egress (only big
well-known outlets pass, and those are already in the catalog), and no repo to dedup
against (an actual 2026-07-01 run there netted 0 usable new sources — all 3 it could
verify were already present).

---

## PART 0 — CAPABILITY PREFLIGHT (do this first, out loud, honestly)

Actually TEST your tools — do not assume:
- **A. SUBAGENTS:** do you have a Task/sub-agent tool that genuinely spawns workers?
  Name the exact tool. "Described in a prompt" does not count.
- **B. LIVE WEB:** fetch one real feed end-to-end NOW as a probe —
  `curl -sSL --max-time 20 https://feeds.bbci.co.uk/news/rss.xml | head -c 300` —
  and confirm you got real RSS/Atom XML (HTTP 200, parseable).

Branch:
- A yes + B yes → **ORCHESTRATED MODE** (Part A): spawn workers, merge.
- A no  + B yes → **SINGLE-WORKER MODE** (Part B, run it yourself, one cluster at a time).
- **B no (can't actually fetch feeds) → STOP. Emit ZERO source entries.** Report that you
  cannot verify anything here and refuse. Fabricating `verified: true` feeds you never
  fetched is the single worst outcome and is strictly forbidden.

**Overriding rule (all modes):** a source entry may exist ONLY if this session (or a
subagent of it) fetched and parsed that exact feed in this run. Never write more entries
than you actually verified. `verified: true` is a claim you are personally staking.

---

## PART A — ORCHESTRATED MODE (only if PART 0 = subagents + web both real)

You are the orchestrator; you do NOT research yourself. Read `configs/sources.yml` once
to build the existing-domain dedup set. Spawn ONE worker per cluster below (multiple Task
calls in a SINGLE message, waves of ~6), each `subagent_type: general-purpose`, pasting
PART B VERBATIM with `{{CLUSTER}}` filled in and the dedup set passed along. Then
concatenate returned blocks, GLOBAL-dedup by domain, write `sources_diversify_<YYYY-MM>.yml`
+ `.report.md`, and run `python -m pytest tests/test_source_taxonomy.py`. Do NOT edit
`configs/sources.yml` directly. If you're about to write more entries than your workers
returned, you invented data — stop.

The 14 clusters:

1. Arabic (pan-Arab, Egypt, Gulf, Levant, Maghreb)
2. South Asia — Hindi, Bengali, Urdu (+ English-language IN/PK/BD outlets)
3. South Asia — Tamil, Telugu, Marathi, Malayalam, Kannada
4. Chinese (mainland/HK/Taiwan/diaspora) + Japanese + Korean
5. SE Asia — Indonesian/Malay, Vietnamese, Thai, Tagalog/Filipino
6. Lusophone — Brazil, Portugal, Angola/Mozambique
7. Latin American Spanish (MX/AR/CO/CL/PE/VE… not Spain-only)
8. Sub-Saharan Africa — Swahili, Amharic, Hausa, Yoruba
9. Africa — major English/French outlets (NG/KE/GH/ZA/SN/CI/DRC/ET…)
10. Persian + Turkish (label state vs independent)
11. Russian (incl. independent-in-exile) + Ukrainian
12. CEE/Balkans/Greece — Polish, Romanian, Serbian, Greek, Hungarian
13. Francophone beyond France — Maghreb, West/Central Africa, Québec
14. Worldwide fact-checkers (`source_type: fact-checker`) in the above languages

---

## PART B — WORKER / SINGLE-WORKER BRIEF (cluster = `{{CLUSTER}}`)

Return 5–30 REAL, LIVE-VERIFIED feeds for this cluster as a YAML `sources:` block + a
rejection log. Fewer-but-real always beats hitting a number. Honesty is absolute.

**Non-negotiables:**
- NEVER fabricate a URL/domain/field. Every entry = a feed YOU fetched & parsed this run.
- Primary outlets only (national papers, public broadcasters, wire agencies, established
  independents, fact-checkers, respected magazines, gov/IGO/NGO portals). NO aggregators
  (no Google News), NO storefronts/SEO/content-farms.
- De-US-centring: ZERO US-focused sources. Real country; omit `country` if unsure (a wrong
  country is worse than none).
- State-media welcome for plurality — LABEL it with an ownership tag, never invent a score.
- `language` = the feed's CONTENT language (English-language Indian paper → `language: en`,
  `country: in` — that's real and wanted).

**Dedup:** skip any domain already in `configs/sources.yml` (registrable domain, lowercased,
strip leading `www.`); no two of your entries share a domain.

**Verify each (all must pass or drop):**
1. `curl -sSL -A "Mozilla/5.0 (compatible; OpenOmniscience/0.2)" --max-time 20 <url>`
   → HTTP 200, parses as RSS/Atom (feedparser/XML).
2. ≥3 entries, each with non-empty title AND link.
3. Liveness: ≥1 entry dated within ~120 days.
4. `robots.txt`: if it Disallows the feed path for `*`, DROP (record reason).
Use the post-redirect final URL as `rss_url`. Find feeds from the outlet's own site
(`/rss`, `/feed`, `/rss.xml`, or `<link rel="alternate" type="application/rss+xml">` in `<head>`).

**Output — YAML in EXACTLY this schema:**
```yaml
sources:
  - name: <Outlet name>
    domain: <registrable domain, lowercase, no scheme/www>
    rss_url: <verified final URL>
    rate_limit_ms: 2000
    enabled: true
    verified: true
    last_verified: <YYYY-MM-DD>
    language: <ISO 639-1>
    country: <ISO alpha-2 lowercase>          # omit if truly unknown
    region: <europe|asia|africa|middle-east|north-america|south-america|americas|oceania|global>
    source_type: <news|wire-agency|magazine|broadcaster|investigative|academic-research|
      scientific-journal|think-tank|government-primary|igo|ngo-civil-society|fact-checker|
      data-portal|religious|blog|financial-data>
    tags: [<topical tags + optionally ONE ownership tag: independent|state-owned|
      public-broadcaster|state-media|corporate|party-affiliated|nonprofit|cooperative|
      wire-agency>]
    priority: 3
```

**Tag rules (CI-enforced by `tests/test_source_taxonomy.py`):** topical tags + ≤1 ownership
tag; NEVER a country/territory NAME or a language code in `tags`; `lean-*` only with a real
basis {`lean-left`|`lean-center-left`|`center`|`lean-center-right`|`lean-right`}.

Also return a rejection log (each dropped candidate + reason: dead / not-XML / robots /
duplicate / stale / country-unknown). Return ONLY the YAML block + the rejection log.

---

## Merge checklist (whoever imports the batch)
- YAML parses; no duplicate domains within the batch or vs `configs/sources.yml`.
- Every entry `verified: true` with a `last_verified` date.
- `python -m pytest tests/test_source_taxonomy.py` passes.
- Then append the verified `sources:` entries into `configs/sources.yml`.
