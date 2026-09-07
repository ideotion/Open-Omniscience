# Prompt 19 — Agenda, hazards, maps and newsletters

> **Scope:** `src/events/`, `src/hazards/`, `src/geo/`, `src/ingest/email.py`.
> **Gated on:** G8 (religious calendars — the dates are the maintainer's), I1 (mailbox credentials),
> I2 (OSM priority), G4 partially.
> **Sequencing:** independent. Four loosely-coupled areas; take them one at a time.

## 0. Working mode

Read `_WORKING_MODE.md`, then the CLAUDE.md **"CALENDAR/AGENDA"** entry (2026-07-17), the
**"MASS LOCAL .eml NEWSLETTER IMPORT"** plan entry, and the maps ruling Q1a from the 2026-07-13 omnibus.

## 1. Agenda and events

### S1 — Recurrence, spans and the honest projection tiers

RRULE expansion of imported VEVENTs is unbuilt (`src/events` has no `rrule`); month-span banners
("Dry January") and `since:`-origin display are unbuilt; saved-filter smart calendars are parked.

The rule that must survive all of it is already learned the hard way: **a dated instance projected into
another year is a fabrication for anything movable.** Filling `month`/`day` from an instance's real date made
every dated VEVENT ghost into every displayed year, which is how three contradictory moon states landed on one
day and how a 2025 Easter appeared in later years. Dated instances place via `next_occurrence` only.

The elections work adds a third confidence tier and it belongs here: `scheduled` (official, sourced),
`window` (a legal window — the France-2027 `confirmed:false` pattern) and `projected` (a sourced rule plus
last-held). A projection's caveat is visible by default ×12; a passed projected date is marked "status
unknown — check the official source", which is itself a lead, and is **never** silently re-projected; and no
sourced rule plus last-held means **no entry at all**, a gap rather than a guess.

### S2 — Hazards beyond two providers

`src/hazards/parse.py` covers GDACS and USGS. Designed and unbuilt: NWS, ReliefWeb, FEWS NET, EONET, WHO; the
nuclear/radiological urgent tag-family rule; and relaying official short-horizon forecasts with provenance.
The `_hazard_tier` no-promotion rule stays: magnitude is a provider-declared **band**, never urgency.

### S3 — The calendar and climate data

Religious calendars (Islamic tabular dates with the honest ±1-day moon-sighting caveat; Hindu and Buddhist
from sourced published tables, **never** a fabricated panchanga) — the maintainer supplies the dates (G8).
Eclipse canon from a bundled public table with provenance. Moon quarter phases, an accepted loss when the
redundant feed was retired, are recoverable via the same verified Meeus method that already computes full and
new moons. The online-calendar catalog expansion is a networked acquisition pass. **PRH-22:** `world_events.yml`
holds only CHOGM as a real floating event.

El Niño span banners stay blocked on the ONI clearnet verification — the dataset is
`verification_status: flagged` and surfacing unverified data prominently would breach the standing rule.

### S4 — Open-Meteo and the lunar framework

Slice 1 (the suggest-to-fetch corroboration card) shipped. Unbuilt: anomaly baselines against stated
baselines, signal-keywords from explicit threshold rules (kind `signal`, never mixed with text keywords), the
reader weather-context row, the temporal-map overlay. The lunar-effects framework — correlating daily series
against the lunar series with BH-FDR **mandatory** and a pre-registration hypothesis UI — is the shape that
keeps it science rather than numerology, and the series already ship.

## 2. Maps

### S5 — Q1a: the OSM preprocessing bridge

The ruling is the data-source path: OSM preprocessed **offline** into boundary and gazetteer artifacts feeding
every thematic map — finer admin-0 boundaries, sub-national admin-1, a richer gazetteer. No WebGL stands; live
street-level detail is out of scope.

What exists is the download manager and a bounded `osmpbf.js` preview. What is missing is the preprocessing
step itself, which is a build-time artifact with a registry entry and a freshness test, not a runtime parse.
Border honesty is a stated requirement of the ruling: a disputed boundary is rendered as disputed, never
resolved silently.

Also here: the `ooMap` embed on When/Where and Insights; per-slide perf on huge corpora (the signals layer
rebuilds the whole SVG on each slider move); and the observed-IP choropleth **dimension**, which must stay
distinct from the catalog-asserted country dimension — asserted and observed-infrastructure are different
classes and blending them silently would be the fabrication.

## 3. Newsletters

### S6 — The eTLD+1 resolver and the import UX (plan S2/S3)

Unbuilt: a vendored dated Public-Suffix-List snapshot with a freshness test, exact `Source.domain` match then
the alias map then a new disabled email source; **silent** auto-attach on a deterministic eTLD+1 or alias hit,
with a dedicated import UI announcing it and an **undo** for the automated attaches (feasible because
send-domain and the attached source id are stored as provenance). Never fuzzy-merge — `bbc` is not `nbc`.

The platform **inversion** is the part that is easy to get backwards: for newsletter platforms (Substack,
beehiiv, Ghost, Mailchimp) key on the publication subdomain or the List-Id and never collapse many publishers
into one platform domain.

### S7 — The live mailbox path

A task-manager-visible job over a long pull (today it is a synchronous endpoint). **I1:** stored and encrypted
credentials for repeat pulls — a real decision, because it adds a secret to the store. The import-time
no-recovery disclosure ×12 needs verifying rather than assuming.

The anonymise-at-ingest guarantees are what resolved the no-recovery contingency and none of them may be
weakened: no recipient identity, no raw `.eml`, no recipient-bearing header, tracking-link detox, and never a
fetch at import (N files ⇒ zero sockets, which is what stops an open-tracking pixel confirming a read).

## 4. Scope fence

Never fabricate a date, a hazard level or a boundary. Deduced events stay labelled deduced. The agenda's
computed astronomy layer (Meeus, verified against the book's worked examples and against almanac dates) is the
one authority for moons and seasons — do not re-add a feed that duplicates it method-unstated.
