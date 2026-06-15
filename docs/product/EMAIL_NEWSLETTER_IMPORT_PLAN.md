# Mass `.eml` Newsletter Import — design & plan

**Status:** ruled & in build (2026-06-15). Ledger entry: CLAUDE.md →
"MASS LOCAL .eml NEWSLETTER IMPORT". Builds on the existing, tested
`src/ingest/email.py` (`parse_email` / `ingest_emails`).

## Goal

Let an operator drop a folder of `.eml` files and have each newsletter become a
first-class **Article** in the one unified corpus — searched, deduplicated,
keyword/When·Where·Who-analysed by exactly the same machinery as a scraped web
article. Local only (no IMAP/network for now). The headline constraint:
**protect the recipient — import the useful metadata but anonymize the
subscriber out of existence.**

## Non-negotiables this feature inherits / sets

- **Zero network on import.** Importing N `.eml` files makes **0 sockets**. This
  is the single strongest recipient protection: open-tracking pixels only fire
  if something fetches them, and we never confirm an open/click to the sender.
  Enforced as a test invariant.
- **Anonymize-at-ingest, no raw retention** (ruled). The DB never stores the raw
  `.eml`, the recipient-bearing headers, or any token-bearing tracker URL. The
  user's own `.eml` files on disk remain the re-import path.
- **No-recovery contingency: RESOLVED (keep no-recovery)** — see CLAUDE.md
  Non-negotiables. Anonymize-at-ingest removes the non-reconstitutable *personal*
  data the contingency feared; we add an import-time disclosure and never add a
  recovery key. Re-open only if a future path stores genuinely
  non-reconstitutable personal content (e.g. live private-mailbox IMAP).
- **Honesty by construction.** Counts of what was stripped are shown; tracker
  wrappers we cannot decode are flagged, never silently presented as the real
  source; the tracker denylist is a **dated, evidence-based** list (freshness
  noted), never claimed exhaustive.

## Metadata policy

**KEEP (recipient-safe):** `From`, `Reply-To`, `Subject`, `Date`, `Message-ID`,
**`List-Id`** (the stable per-newsletter key), the DKIM `d=` sending domain,
`List-Archive` / `List-Post` when present (public).

**DROP (recipient-bearing):** the recipient itself and every header that can
carry it — `To`, `Cc`, `Bcc`, `Delivered-To`, `X-Original-To`, `Return-Path`
(VERP bounce tokens), the `Received` chain, and **`List-Unsubscribe`**
(per-recipient unsub token — this reverses an earlier suggestion to keep it).

## Tracking-link detox (the recipient-protection core)

A reusable, network-free `link_sanitizer` applied to every URL we extract:

1. **Unwrap** redirect wrappers **only when the destination is embedded** in the
   URL (some SendGrid `ls/click?upn=<b64>`, generic `?url=`/`?u=` redirects) →
   store the clean destination.
2. **Strip** recipient-identifying query params via a dated denylist
   (`mkt_tok`, `mc_eid`/`e`, `_hsenc`, `_hsmi`, `ck_subscriber_id`, `oly_enc_id`,
   `oly_anon_id`, `vero_id`, …) from any URL we keep.
3. **Drop** open-tracking beacons (1×1 / zero-size images, known beacon hosts).
4. **Flag, don't trust.** Most ESP wrappers (Mailchimp `list-manage`, Substack
   `/redirect/<uuid>`, Beehiiv `link.mail.beehiiv.com/ss/c/<token>`) resolve the
   destination **server-side** — unrecoverable without a network call we refuse,
   and the wrapper path is often itself recipient-keyed. For these: keep the
   wrapper **domain** + the (recipient-safe) visible anchor text, **drop the
   token-bearing path**, mark `tracker-wrapped`.
5. **Redact the recipient's own echo.** We parse `To`/`Cc` only to know the
   recipient address, **redact** any literal echo of it from subject/body/URLs,
   then discard it unstored. Bonus: removing per-recipient personalization makes
   two subscribers' copies of the same newsletter hash identically → our
   existing content-hash dedup collapses them into one Article.

**Downstream:** the existing external-link guard / link-preview / "ingest linked
page" paths operate on the cleaned URL and **never auto-follow** a
`tracker-wrapped` link — following it would phone home as the recipient.

## Source resolution — "is a BBC newsletter the same source as the scraped BBC site?"

**Today: no.** `Source.domain` is `unique` and matched by exact string;
`registrable_domain`/`normalize_domain` strip only `www.`, not arbitrary
subdomains — so a newsletter from `email.bbc.com` would not match the seeded
`bbc.com` source and would spawn a parallel source.

**Resolver (per incoming `From`-domain):**

1. Reduce to the **registrable domain (eTLD+1)** with a properly Public-Suffix-aware
   reducer. To keep zero-network boot we **vendor a dated PSL snapshot**
   (`PSL_AS_OF` + a freshness test, like the model catalog), not the
   auto-updating `tldextract`. `email.bbc.com` → `bbc.com`.
2. **Exact** `Source.domain` match → attach.
3. **Alias** match via `is_equivalent_domain` (already carries
   `bbc.com ↔ bbc.co.uk`) → attach.
4. **No match** → create a new source `domain = <eTLD+1>`, tagged
   `newsletter`/`email`, **disabled for scraping**.

**Rules:**
- **Silent auto-attach** on a deterministic eTLD+1/alias hit. The action is
  surfaced (not hidden) in a dedicated import view with live progress, every
  import detail, and an **undo** for the automated attaches — reversible because
  we store the send-domain + the attached `source_id` as provenance.
- **Never fuzzy-merge** (`bbc.com` ≠ `nbc.com`): deterministic rules only.
  Anything weaker becomes a **user-confirmed suggestion**.
- **Preserve send-domain + `List-Id` as filterable provenance** so an
  email-sourced article stays distinguishable from a web-scraped one (same idea
  as per-edition Wikipedia sources and the DDG-discovered class).
- **Platform inversion.** For newsletter *platforms*
  (`substack.com`, `beehiiv.com`, `ghost.io`, `mailchimp`… several already in
  `catalog/normalize.SOCIAL_HOSTS`), do the **opposite** — key the source on the
  publication subdomain / `List-Id`, never collapse hundreds of publishers into
  one platform domain.

## Already handled (verified)

- **Import date.** Both the web pipeline (`pipeline.py:114`) and the email path
  (`email.py:187`) set `created_at = now` at ingest — that *is* the import date.
  The newsletter's own date is kept separately as `published_at` (its `Date`
  header). No separate `scraped_at` column exists; `created_at` is the universal
  acquisition timestamp. **Nothing to add.**

## To retire

- `scripts/import_eml.py` — broken against the live schema (references
  `content_hash`/`html_content`/`is_newsletter`/`metadata`/`scraped_at` columns
  that do not exist on `Article`) **and** it captures `To`/`Cc`. Flagged for
  removal; not silently deleted (maintainer-authored).
- `configs/email_sources.yaml.example` + the ROADMAP "Email & Newsletter
  Intelligence Implementation Plan" are aspirational design notes, not status.

## Slices (one PR each, draft onto `0.09`)

- **S1 — anonymization core (this PR).** `src/privacy/link_sanitizer.py`
  (pure, network-free) + `src/ingest/email.py` hardening (recipient-echo
  redaction, body link sanitization, per-import sanitize counts) + `.eml`
  file/directory ingest reusing `ingest_emails` + tests (including the
  zero-network and never-store-recipient guarantees).
- **S2 — metadata, resolution & provenance.** Safe-metadata extraction
  (`List-Id`, `Reply-To`, send-domain) + email-provenance storage (send-domain,
  `List-Id`, resolved-via, auto-attached `source_id`) + the eTLD+1 PSL resolver
  + silent auto-attach + platform inversion + tests.
- **S3 — surfaces.** Upload/import API endpoint, the import-progress / **undo**
  window, the import-time **disclosure** (×12 locales), USER_MANUAL section.

## Acceptance (S1)

- Importing a directory of `.eml` files yields one Article per non-empty,
  non-duplicate message; re-import is a dedup no-op.
- No recipient address (To/Cc) and no recipient-bearing header is stored;
  a recipient address echoed in the body is redacted from stored content.
- Tracker query-params are stripped; embedded-destination wrappers are
  unwrapped; server-side wrappers are flagged `tracker-wrapped` with the path
  dropped; beacons are dropped.
- A test asserts the import path makes **zero** network calls.
