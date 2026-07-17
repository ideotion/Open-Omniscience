# Law-sources acquisition — the parallel internet-session channel (2026-07-17)

**Status:** plan of record + file contract + ready-to-paste session prompt. **Ruled by the
maintainer 2026-07-17:** *"incorporate as many country's legal systems as possible … a parallel,
autonomous, internet-connected session that would produce a digestible file that would enrich the
current law internet endpoints to scrap, with all proper metadata associated (Cambodian law is in
French, for example)."*

**The channel (the established house pattern** — Wikidata rings, world-news catalog, source
enrichment batches**):** parallel internet-connected Claude sessions research jurisdictions in
REGION BATCHES → each emits one YAML block in the contract below → the blocks concatenate into
**`configs/legal_sources_generated.yml`** → `scripts/validate_legal_catalog.py` lints it offline →
the maintainer vets (the Wikidata-rings precedent: ~6% of unvetted machine research was wrong) →
commit → **the intake seam (shipped with this doc) merges it into the live catalog at boot,
curated-wins** → the law-vertical session's adapters + coverage diagnostic consume the
enumeration metadata (`AUTONOMOUS_SESSION_BRIEF_2026-07-17_LAW_VERTICAL.md`, the completeness
principle).

---

## §1 The file contract — `configs/legal_sources_generated.yml`

Top level:

```yaml
schema: oo-legal-catalog-gen-1
as_of: "2026-07"            # month of the research pass (freshness anchor)
batches:                     # provenance per contributing session
  - {batch: "africa-west", session_date: "2026-07-18"}
sources: [...]               # portal/gazette entries (Source rows; see below)
documents: [...]             # optional: individually trackable consolidated instruments
```

Each `sources:` entry (one per official portal/gazette; a jurisdiction may have several):

```yaml
- name: "Official name (English)"          # required
  native_name: "Nom officiel"              # when it differs
  domain: example.gov.xx                   # required; the registrable domain
  country: kh                              # required; ISO-2 (or eu/int for supranational)
  jurisdiction_note: ""                    # subnational/supranational scope if any
  languages: [km, fr]                      # required; the languages THE LAW IS PUBLISHED IN —
                                           # NOT the country's spoken languages. Cambodia's
                                           # codes exist in Khmer AND French; Switzerland
                                           # publishes de/fr/it; the EU publishes 24.
  legal_language_note: "Major codes have official French versions (civil-law heritage)."
  legal_system: civil_law                  # civil_law | common_law | mixed | religious |
                                           # customary | mixed:<detail>  — DESCRIPTIVE metadata,
                                           # never a quality signal
  source_type: legal                       # legal | ip | case_law | gazette
  kind: consolidated_portal                # consolidated_portal | gazette | case_law | ip_office
  enumeration_url: "https://…/codes"       # THE COMPLETENESS ANCHOR: the source's OWN list of
                                           # its corpus (France: the 76-codes list). Omit only
                                           # if none exists — say so in notes.
  official_count: {value: 76, unit: codes, as_of: "2026-07-18", source_url: "https://…"}
                                           # read OFF the enumeration page, dated; the S5
                                           # coverage diagnostic's denominator. NEVER estimated.
  gazette_feed: "https://…/rss"            # a REAL RSS/Atom feed, only if verified to parse
  structured:                              # bulk/API availability — the adapter planning signal
    api: "https://… or none"
    bulk: "https://… or none"
    formats: [html, pdf, xml, akoma-ntoso, eli]
    api_key_required: false
  license_note: "Open data / crown copyright / unclear — say which"
  tags: [law, legislation, official]
  verification:                            # required; the anti-fabrication core
    status: fetched                        # fetched (✅ you loaded it this session) |
                                           # search-verified (🔎 confirmed via search snippets) |
                                           # lead (❓ believed, unconfirmed)
    retrieved_at: "2026-07-18"
    evidence: "Loaded the enumeration page; 76 codes listed; RSS parses with 20 items."
  confidence: high                         # high | medium | low
  notes: ""
```

`documents:` entries follow the existing curated shape (`jurisdiction, title, url, official_url,
category, consolidated, country, language`) + `verification`. Use sparingly — the per-country
ADAPTERS are the scale path; documents are for jurisdictions with no enumeration where a handful
of key consolidated instruments is all there honestly is.

**Binding rules:** never fabricate — a URL you did not confirm is `status: lead` and ships
DISABLED-in-effect (the validator flags it; the maintainer decides); `official_count` only ever
read off the official page, never estimated; languages = languages OF THE LAW; every entry
carries `verification`; prefer the jurisdiction's PRIMARY consolidated-law database over
aggregators (WIPO Lex / World LII are FALLBACK pointers where no national portal exists — mark
them `kind: consolidated_portal` with a note, never as the country's own).

## §2 The parallel-session prompt (paste below the line into an internet-connected session; one
region batch per session; run several in parallel)

---

You are researching **official primary-source LAW portals** for an offline research tool's
catalog. For each jurisdiction in the INPUT list, find and verify: the national consolidated-law
database, the official gazette (+ RSS if real), the enumeration page listing the corpus (e.g.
France's list of 76 codes en vigueur), bulk/API open-data endpoints, the languages the law is
published in, and the legal-system family. Output ONE YAML block in the exact schema I provide
(fields, enums, and the `verification` block are mandatory). THE ABSOLUTE RULE: **never
fabricate.** A URL you have not loaded in this session is at best `search-verified`; if you only
believe it exists, it is `lead`. A wrong URL is worse than a missing one — this catalog feeds an
automated fetcher. Prefer ACTUALLY LOADING the enumeration page: it upgrades you to `fetched` AND
gives the dated `official_count` (read the number off the page — never estimate). Language
discipline: record the languages THE LAW IS PUBLISHED IN, not the country's spoken languages
(Cambodian codes have official French versions; Switzerland publishes in de/fr/it). Aggregators
(WIPO Lex, LII networks) are fallbacks only, marked as such. Do not narrate per country; emit the
whole batch as one YAML block conforming to `oo-legal-catalog-gen-1`. INPUT JURISDICTIONS:
`{{REGION_BATCH — ~15–20 ISO-2 codes}}`. ALREADY CATALOGUED (skip these domains unless you are
correcting them): `{{paste the domain list from configs/legal_sources.yml}}`. SCHEMA:
`{{paste §1 of this doc}}`.

---

**Batching:** ~12 batches cover the world: Europe-West/East/North, Africa-West/East/South+North,
Middle East, Central+South Asia, East+Southeast Asia, Oceania, North+Central America+Caribbean,
South America, supranational (EU/AU/OAS/ASEAN/GCC/UN treaty bodies). Every UN member appears in
exactly one batch. The 12-UI-language-country floor is already largely covered by the curated
file — batches extend OUTWARD from it.

**Batch status (2026-07-17 — first 8 received + merged, 163 sources / 7 documents):**
africa-west ✅ · africa-east ✅ · africa-central-south ✅ · mena ✅ ·
europe-central-baltics-microstates ✅ · europe-east-caucasus ✅ · south-central-america ✅ ·
southeast-asia ✅. **Still to run:** Europe-West/North (mostly curated-covered — a gap-fill
pass), Central+South Asia, East Asia, Oceania+Pacific, North America+Caribbean, supranational.

**Contract calibrations from the first 8 real batches (binding for future sessions and the
validator alike):**
- `structured.api` / `structured.bulk` accept a URL **or a short descriptive phrase** — every
  session converged on descriptive use ("per-act PDF", "Laws.Africa Content API v2, …"); they
  are adapter-planning metadata, not fetch targets.
- An **http-only** official portal is recorded exactly as found (`http://…`); the validator
  lists it as a WARNING for the maintainer — never silently rewritten to https (that would
  fabricate a capability the site may not have).
- A jurisdiction with **no working portal at all** (e.g. Yemen) is recorded as a domain-less
  `lead` row — the honest-gap record. The app-side loader skips domain-less rows by
  construction, so a gap can never become a Source.
- One host carrying **two roles** (consolidated codes portal AND the gazette) is two rows with
  distinct `kind`; the in-file dedup key is `(domain, kind)`. Registration must later collapse
  them onto one Source row (`Source.domain` is unique) — the S6 adapter session owns that.
- `documents` rows use `jurisdiction:` (a session that writes `country:` gets mechanically
  renamed at intake); a document without a `verification` block defaults to `lead`.

## §3 Intake (shipped with this doc — the file works the moment it lands)

- `src/law/catalog.py` now merges `configs/legal_sources_generated.yml` (when present) into the
  live catalog: **curated wins** on a domain (sources) or `(jurisdiction, url)` (documents)
  collision; extra metadata fields ride along untouched for future consumers (adapters, the
  coverage diagnostic's `official_count` denominators). No generated file → byte-identical
  behavior.
- `scripts/validate_legal_catalog.py` (offline, runs anywhere): schema + enums + ISO codes +
  https URLs + in-file and vs-curated dedup + verification-status accounting (how many
  fetched/search-verified/lead) + per-row errors. **Run it before every commit of the generated
  file; a `lead` row is listed for the maintainer's explicit decision.**
- The vetting gate is the PR review of the generated file (the maintainer merges; the
  Wikidata-rings hand-vetting precedent applies — spot-check especially `official_count` claims
  and any entry whose `confidence` is not high).
- Freshness/registry: when the law-vertical session wires the catalog's `*_AS_OF` freshness
  constant, the generated file's `as_of` joins the external-artifacts registry per the standing
  rule (deliberately not added here to keep this slice docs+intake only).

## §4 How this feeds the law vertical (no duplication — pointers)

The law session brief's completeness principle gets its DATA from this channel: enumeration URLs
+ dated official counts per jurisdiction = the S5 coverage denominators app-wide, *before* an
adapter exists for each country; the `structured:` block is the adapter-priority worklist (build
adapters where `bulk`/`api` exist; HTML-track where they don't); `languages` threads into the
metadata fix the brief now carries (LawDocument.language → corpus `Article.language`, so a
French-language Cambodian code gets French keyword treatment). One channel, three consumers.
