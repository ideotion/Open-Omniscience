# Article and source qualification: the read-only reports

The quarantine job marks articles that fail an explicit, disclosed rule (`quarantined`,
`quarantine_reason`, `quarantine_criteria_version`, `quarantined_at`). It never deletes, and a mark is
reversible. Everything below is loopback only and makes no network call. Start with a DRY RUN
(`write=false`): nothing in the database changes, and applying (`write=true`) waits on a person who has
read the counts AND the samples.

## Run it
- `POST /api/quarantine/start?write=false&include_stubs=true` starts a chunked, resumable pass. Add
  `&include_host_mismatch=true` to also count articles stored on a different site than their source's own.
  A 409 means a run is already in progress: wait for it. Nothing else heavy should run beside it.
- `GET /api/quarantine/status` shows `articles_total`, `articles_done` and the `tally` (`scanned`,
  `quarantined`, `already_quarantined`, `reason:<signal>`, and `host:mismatch` / `host:confirmed` / `host:unknown`).
- `POST /api/quarantine/pause`, `resume` and `cancel` control the run (`/api/quarantine/{action}`).

## Read what the rules picked
- `GET /api/quarantine/samples?signal=<signal>`: up to 20 candidates per signal (`menu_stub`,
  `paywall_stub`, `host_mismatch`, ...), chosen by a fixed hash order so the same corpus gives the same
  rows. A spot-check of what the rules pick, not an error rate and not a verdict. Counts alone do not
  confirm the thresholds; the samples do.
- Host mismatch is REPORT-ONLY: it marks nothing even with `write=true`, because a page on another site can
  be a good article (syndication, redirect, wire feed). Each row shows the source's domain and the two
  sites compared; `unknown` is never counted as a mismatch.
- A person who has read a mismatch and knows the source legitimately publishes on that site can CONFIRM the
  pair: `POST /api/quarantine/host-pairs` (`source_id`, `article_site`, optional `note`),
  `GET /api/quarantine/host-pairs` to list them, `DELETE` to withdraw one. A confirmed pair is a side
  table keyed by (source, article site), never a tag on the source; the report then counts it as
  `host:confirmed` and lists it under `signal=host_confirmed` with its date and note instead of hiding it.
  Only a pair that is a mismatch right now can be confirmed (409 otherwise). A restore carries the pairs: the
  earliest confirmation date wins and notes from both corpora are joined, each incoming note labelled with
  its merge batch.

## Reports that are not part of a run
- `GET /api/quarantine/raw-id-sources`: sources whose whole name is a bare Wikidata Q-id, with article
  counts (lowest source ids first, counts include quarantined articles). Renaming is the separate,
  consented `POST /api/sources/resolve-qid-names`, and renames nothing without review.
- `GET /api/quarantine/source-furniture?source_id=N`: short lines that repeat across one source's newest
  bodies (menu entries, ad slots, banners), for a person to read and, if they are furniture, to add to the
  rule lists by hand. Nothing is stripped, marked or learned automatically; a repeated line is not a
  verdict on the articles carrying it.

## The Maintenance section (Settings → Advanced)
The same dry run and the two reports above can be read without `curl`: Settings → Advanced → Maintenance starts a run
with `write=false` (and, if ticked, `include_stubs` / `include_host_mismatch`), shows the live state and the tally,
the per-signal samples (titles and addresses only; a title opens the local reader) and both reports. It uses only
the routes above, makes no request outside this computer, and offers no way to write: applying a result stays a
deliberate API or CLI act until the maintainer has read counts and samples from their own corpus and ruled
(R196). "Stored on a different site" and "site could not be read" are separate rows, and a signal the run did not
ask for reads "not measured", never zero. Pinned by `tests/test_maintenance_panel.py`.

## What these numbers are not
A `reason:*_stub` count is a CANDIDATE count under rules fitted to few specimens, not a measured error
rate. The thresholds move only after a person has read samples from their own corpus.
