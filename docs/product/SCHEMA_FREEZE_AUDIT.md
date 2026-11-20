# Schema-freeze audit: the judgement (0.8 row B)

**Status: RULED R755 (2026-11-20, coordinator, on the proposal F1 to F8; recorded in `docs/ledger/RULINGS_INDEX.md` and
`docs/ledger/OPEN_QUEUE.md`).** This is the written judgement that `RELEASE_0.8_GATE.md` row B and brief S08-02 S5 ask
for: which migration the freeze starts after, and which pending column or table is declared additive. Each choice F1 to
F8 below carries what was ruled on it; where the ruling changed the proposal, the ruling is what stands. The facts it
judges are generated in [`SCHEMA_FREEZE_INVENTORY.md`](SCHEMA_FREEZE_INVENTORY.md) by `scripts/schema_audit.py`, read
at `d8d5d6a06` (2026-11-20). No schema change comes with this document.

The ruling it serves: Q102 = a, «0.9 freezes features and schema», and the 0.8 gate's «this is the last release in
which a schema change may be non-additive».

## 1. What the facts say

**The migration chain.** 85 Alembic revisions, head `d7e3a9b2c5f1`, one merge (#24). Five revisions are non-additive and
four add a column with a back-fill of that new column only:

| # | revision | class | why |
|---|---|---|---|
| 9 | `f1a2b3c4d5e6` | non-additive (index) | drops `idx_article_content` |
| 12 | `a3b4c5d6e7f8` | non-additive (data rewrite) | canonicalises country codes in place; NULLs `credibility_score = 50.0` |
| 15 | `f4b5c6d7e8a9` | non-additive (data rewrite) | NULLs `sources.reliability_score = 5` (a fabricated default) |
| 68 | `ea0be5f53d2f` | non-additive (index) | replaces `idx_keyword_mention_count` with `idx_keyword_counter_freshness` |
| 77 | `d5a1c7e9b3f2` | non-additive (table rebuild) | `upgrade_sources_to_composite_key`: adds `feed_key`, copies `sources` into a new table, drops and renames it; the key becomes UNIQUE (domain, feed_key) |
| 29 | `a2b3c4d5e6f7` | additive, back-fill | `mention_count`, `article_count` NOT NULL DEFAULT 0, filled from mentions |
| 31 | `d3e4f5a6b7c8` | additive, back-fill | `content_multihash`, `canon_version` filled where NULL |
| 78 | `e6b2d8f0a4c3` | additive, back-fill | `outlet_id`, three triggers, an UPDATE of that new column only |
| 82 | `c4e8a2d6f1b9` | additive (derived) | three `keyword_day_*` tables and their triggers |

The other 76 create tables, add nullable or defaulted columns, or add indexes. **The last non-additive revision is #77
`d5a1c7e9b3f2`; #78 to #85 are all additive.**

**Four ways a schema changes, not one.** A reader of the Alembic chain alone would miss three of them:

1. **Alembic** runs only on a staged restore copy (`upgrade_database_file`, `src/database/migrate.py:79`, called from
   `src/backup/merge.py`) and in CI.
2. **A live store is never upgraded by Alembic.** `init_db` (`src/database/session.py`) runs `create_all`, then about
   thirty `ensure_*` self-heals, then `align_stamp_to_head` (`src/database/migrate.py`), which advances the stamp only
   past the data floor `a5b6c7d8e9f0`. Two self-heals are not additive: `ensure_source_composite_key` (the same rebuild
   as #77, `src/database/source_identity.py`) and `ensure_law_source_type` (`src/database/maintenance.py`), a boot-time
   `UPDATE sources SET source_type = 'law'` with no Alembic revision at all.
3. **The five lane stores** (versioned, law, medical, OSM, wiki) have no Alembic and no version check:
   `create_schema` (`src/versioned/store.py`) runs `create_all` and then `add_missing_columns`, which adds only nullable
   or defaulted columns and raises `LaneSchemaError` on anything else. `lane_meta.schema_version` is written as `1` and
   never read. One lane object rebuilds itself: `wiki_lane_fts` drops and rebuilds when its `FORMAT_VERSION` moves
   (`src/wiki/lane_search.py`), clearing two derived tables with it.
4. **Raw-DDL tables** (inventory §4) are `CREATE ... IF NOT EXISTS` with no version, except the FTS tokenizer rebuild
   (`rebuild_with_current_tokenizer`, `src/database/fts.py`) and the columnar store, which is disposable and rebuilds on
   its own marker (`src/analytics/columnar.py`).

**Restore of an older backup.** A corpus backup is brought to head by Alembic on the staged copy (so #12 and #77 run on
old backups), then normalised: country codes by `normalise_staged_country_codes` (`src/backup/country_codes.py`, 0.4
row K and 0.5 row B), the feed key by `oo_inc_feed_key` (`src/backup/merge.py`, 0.5 row J). The alpha-3 storage flip of
an existing store is not a migration: it is the offline command `src/backup/country_migration.py`. Lane backups copy
only the columns both files share (`src/backup/lane_merge.py`). Readers accept `oo-backup-2` and `oo-backup-3`
(`ACCEPTED_BACKUP_SCHEMAS`, which «only ever joins»), `oo-volumes-1` and `oo-volumes-2`, and legacy bare `.db` /
`.ooenc` files.

## 2. The judgement

**F1. The freeze point (ruled: Q102's letter).** The freeze starts after **0.9.0**, as Q102 = a says: every Alembic
revision after the head at the `v0.9.0` tag is additive in the sense of F2. Until then, a non-additive change still
needs its own ruling; this audit grants none. *The state today:* the head has been additive-only since **`v0.5.0`**
(`8cbb54ef4`). The last non-additive revision, #77 `d5a1c7e9b3f2`, came in with `cb0169ee6` (2026-10-16), inside that
tag; the six revisions added after it (#80 to #85, head `d7e3a9b2c5f1`) are all additive. (The proposal had suggested
freezing at the `v0.8.0` tag; it was not adopted, because Q102 is the maintainer's own wording.)

**F2. What «additive» means (ruled: adopted, with two precisions).** Allowed after the freeze: a new table; a new column that is nullable or carries a
constant server default; a new index; a back-fill that writes ONLY the new column or table; a new trigger that writes
only derived tables. Not allowed: dropping or renaming a table or column; changing a type; adding NOT NULL without a
default; tightening a key or constraint; any UPDATE or DELETE of a row's existing source values. *The precisions:* a
back-fill may write only columns added by the same change, and a new NOT NULL column must carry a default.

**F3. Derived data is outside the freeze, by declaration (ruled: adopted).** Rebuilding a table that holds nothing a user or a source
supplied, and that is recomputed from tables that do, is not a schema change for the freeze: the FTS indexes and their
tokenizer (R39), `wiki_lane_fts`, the `keyword_day_*` counters, the columnar store, the OSM view and place indexes,
the dump index, and a re-extraction of derived rows under a new engine (R725/R726: their import hold stands separately and this audit does not lift it). Dropping or replacing an
INDEX is also allowed (#9 and #68 are of this kind): it loses no data and a restore does not depend on it. Each such
rebuild still states itself in the release notes (R319).

**F4. The freeze covers all four paths in §1, not only Alembic (ruled: adopted).** A boot self-heal, a lane store's `create_schema`
and a raw-DDL table are held to F2 exactly like a revision. Two consequences:
- `ensure_law_source_type` is a data rewrite on boot. It is idempotent and has run on every store started since Q919,
  so it may stay; but no NEW boot-time rewrite may be added after the freeze.
- `lane_meta.schema_version` is written and never read. It stays at `1` and say so in the 0.9 guard's
  documentation, rather than give it meaning now; a lane store has no non-additive step to version.

**F5. The pending work, each landed here or declared additive (ruled as below).**

| pending | where cited | declaration |
|---|---|---|
| Blob store (Q1009, R700, R707): `blobs`, `packs`, `blob_staging`, `blob_keys`, `pack_intents`, `pack_pins`, `articles.blob_addr` | `docs/design/BLOB_STORE_PHASE_C_DESIGN_2026-11-14.md` | **Additive**, as long as no migration drops `articles.content`. Moving text into packs (Q-W7) is done by the app at run time, with the column kept and read as a fallback, so an old backup still restores. |
| Language columns to ISO 639-2/3 (Q306, 0.5 row B) | `RELEASE_0.5_GATE.md` row B | **Not additive** (a rewrite of stored values). Either it lands before the freeze, or it follows the alpha-3 country pattern: an offline command the user runs plus a restore normaliser. **Never a boot rewrite.** |
| Country flip of an existing store to alpha-3 | `src/backup/country_migration.py` (code merged; operator run owed) | Already an offline command, not a migration; it stays allowed after the freeze **as an operator command only**, and restore keeps normalising both forms. |
| R725 / R726 re-extraction under a new WWW engine | `RULINGS_INDEX.md`; held during the mass import | Derived (F3). |
| R39 FTS tokenizer rebuild | `RELEASE_0.5_GATE.md` | Derived (F3). |
| Q416 keyword re-normalisation (lemmatisation), R96 segmented index | `OPEN_QUEUE.md`; held | **Never rewrites a user-made row** (watches, saved terms, family overrides, supergroups, tags: anything the user typed or chose). Derived rows may be rebuilt under F3. If a user-made row would need to change, it is mapped at read time and the case comes back for its own ruling. |
| UCDP conflict store and the dossier tables (S08-01) | `S08-01` brief | Additive (new tables). |
| `law_identifiers` (conditional) | `OPEN_QUEUE.md` | Additive (new lane table). |
| Functional index on `lower(sources.domain)` | `OPEN_QUEUE.md` | Additive (index), with the expression-index drift note it carries. |
| R702 rebuild at new settings | `src/database/rebuild.py` | Not a schema change (a physical copy of an identical schema). |

No pending work drops or renames a database table or column. Q313's dropped column is an **export** column (CSV/JSON),
not the database.

**F6. The format identifiers are frozen at their current writers (ruled: adopted, with a test).** `oo-backup-3`, `oo-volumes-2`,
`oo-folder-backup-1`, `oo-folder-verify-1`, `oo-export-request-1`, `oo-parity-1`, `oo-export-1`, `oo-custody-1`.
Readers keep accepting `oo-backup-2` and `oo-volumes-1` through 1.x. After the freeze, a backup may gain a NEW member
only if an older reader ignores it and a newer reader accepts its absence (the blob store's pack member is the case this
is written for); anything else is a format bump and waits for 2.0. `tests/test_restore_future_member.py` holds the rule:
a backup written by this build with one extra member of a role this build does not know restores, and the extra member
is ignored rather than placed.

**F7. A stale default (ruled: fix it).** `merge_batches.artifact_kind` defaulted to `"oo-backup-2"` in the model and
in `merge_corpus`'s fallback, while the writer has been `oo-backup-3` since 0.4 row K. A batch whose caller named no
kind therefore read as an `oo-backup-2` restore. It is fixed in its own PR, #2178: both now record `"unknown"`, and the one
production caller keeps passing the staged artifact's real kind.

**F8. The proof stays the operator's (ruled: on the user's FYI list; it does not block this document).** A real
restore of a pre-audit backup into the post-audit schema is `not-measurable-here` in the sandbox; it is an operator step
of the 0.8 close, beside row B's owed alpha-3 run.

## 3. The audited list and its cross-check

The list below is every table and column of the main database and the lane stores as audited on 2026-11-20. It is what
the freeze will freeze at 0.9.0. `tests/test_schema_freeze_audit.py` compares it with the live models in both directions and names
the table or column that differs: a column the code has and this list lacks, or the reverse, is a red until this
document is updated (and, after the freeze, until the change is shown to be additive under F2). The raw-DDL tables and
the format identifiers are held by the inventory's own test.

```text
main ai_custom_prompt: id, label, output_kind, prompt_text, run_on_ingest, enabled, created_at
main ai_keyword: id, article_id, term, kind, language, model, prompt_version, confirmed, evidence, created_at
main app_state: key, value, updated_at
main article_analyses: id, article_id, kind, result, model, prompt_version, prompt_text, created_at
main article_entities: id, article_id, name, entity_class, mentions, snippet, note, extractor, created_at
main article_index_stamps: article_id, engine, inputs, stamped_at
main article_keyword_association: article_id, keyword_id, frequency, position, relevance_score, created_at
main article_keywords: article_id, keyword_id, frequency, first_position, last_position, relevance_score, created_at
main article_links: id, article_id, url, normalized_url, link_text, position, link_type, classification, external_source_id, source_article_id, is_followable, is_working, last_checked_at, redirect_url, http_status, created_at, updated_at
main article_mentioned_dates: id, article_id, mentioned_on, precision, snippet, confidence, extractor, status, created_at
main article_mentioned_places: id, article_id, name, country, kind, mentions, snippet, lat, lon, note, extractor, created_at
main article_source_relationships: id, article_id, source_id, source_article_id, link_id, relationship_type, time_delta_days, is_temporal_anomaly, confidence_score, notes, created_at, updated_at
main article_title_translations: id, article_id, source_lang, target_lang, title, summary, model, prompt_version, created_at
main article_www_stamps: article_id, engine, inputs, stamped_at
main articles: id, url, canonical_url, source_id, title, content, compressed_content, published_at, language, detected_language, hash, content_multihash, canon_version, server_ip, ip_observed_at, server_ip_reason, fetched_host, created_at, updated_at, region, country, author, word_count, reading_time, sentiment_score, sentiment_label, quarantined, quarantine_reason, quarantine_criteria_version, quarantined_at, top_keyword_id, top_keyword_count, top_keyword_tied_n, keyword_indexed_at, source_revision, newsletter_list_id, newsletter_attached_via
main commodity_prices: id, symbol, market, observed_on, price, currency, unit, source, created_at
main derived_meta: key, value, updated_at
main event_imports: id, family_key, fingerprint, family_name, family_user, imported_at, title, date, sources, uids, updated_at
main external_sources: id, domain, name, url, source_type, credibility_score, political_bias, country, language, description, founded_year, alexa_rank, social_media_followers, is_verified, discovered_via, last_verified_at, created_at, updated_at
main feed_fetch_state: source_id, etag, last_modified, last_status, last_checked_at, consecutive_unchanged, skip_until
main hazard_event_details: id, article_id, provider, event_id, event_type, severity, magnitude, lat, lon, place, event_time, source_url, created_at, updated_at
main host_mismatch_confirmed: id, source_id, article_site, confirmed_at, note
main ipcc_predictions: id, spm_key, sentence_hash, sentence, decision, method_version, decided_at
main keyword_categories: id, name, description, parent_id, color, is_active, created_at, updated_at
main keyword_day_counts: observed_on, keyword_id, mentions
main keyword_day_dirty: observed_on
main keyword_day_state: id, complete, built_epoch, watermark, reuse_floor, floor_gen, cursor, started_at, built_at
main keyword_family_overrides: id, normalized_term, family_key, canonical_label, kind, created_at
main keyword_mentions: id, keyword_id, article_id, count, first_offset, observed_on, country, city, language, source_id, extractor, created_at
main keyword_supergroup_members: id, supergroup_id, normalized_term, ring_id, created_at
main keyword_supergroups: id, name, color, created_at
main keyword_tags: id, keyword_id, axis, tag, source, created_at
main keyword_translations: id, term, source_lang, target_lang, text, model, prompt_version, created_at
main keywords: id, term, normalized_term, language, frequency, category_id, is_ngram, ngram_size, is_entity, entity_type, relevance_score, created_at, updated_at, extractor, mention_count, article_count, last_reconciled_at
main law_documents: id, jurisdiction, title, url, official_url, category, consolidated, watched, baseline_text, baseline_hash, latest_text, latest_text_revid, last_hash, last_size, last_checked_at, last_status, language, country, enacted_on, lane_key, created_at
main law_format_changes: id, document_id, changed_at, from_url, to_url, from_format, to_format, from_hash, to_hash, from_baseline_hash, from_baseline_text, from_latest_text, from_latest_text_revid, reason
main law_revision_summaries: id, revision_id, summary, model, prompt_version, prompt_text, created_at
main law_revisions: id, document_id, observed_at, content_hash, size, delta_bytes, diff, full_text, flagged, flag_reasons, diff_basis, diff_base_revision_id, valid_on, valid_on_dating, lane_key, created_at
main link_classification_rules: id, rule_name, pattern, classification_type, priority, is_active, created_at, updated_at
main market_extraction_rules: id, source_id, category, symbol, label, url, selector, attribute, value_regex, currency, unit, market, enabled, last_run_at, last_status, created_at, updated_at
main merge_batches: id, imported_at, artifact_kind, origin_fingerprint, app_version, alembic_rev, source_digest, manifest_json, counts_json, report_json, status
main merged_rows: batch_id, table_name, row_id, row_key
main metadata_alternates: id, batch_id, table_name, identity, local_row_id, fields, provenance, origin, status, created_at
main places: id, qid, kind, name, names_json, country, country_alpha3, admin_path_json, geometry_ref, lat, lon, population, gazetteer_vintage, article_id, as_of
main source_admission_events: id, source_id, occurred_at, verdict, criteria_version, prior_enabled, prior_status, undone_at
main source_articles: id, source_id, url, title, published_at, author, summary, content_hash, word_count, sentiment_score, is_accessible, last_accessed_at, created_at, updated_at
main source_candidates: id, domain, suggested_name, channel, evidence, status, first_seen, last_seen
main source_credibility_rules: id, rule_name, factor, weight, min_value, max_value, is_inverse, is_active, created_at, updated_at
main source_group_association: source_id, group_id, added_at
main source_groups: id, name, description, color, is_tag_based, tag_pattern, priority, rate_limit_ms, enabled, created_at, updated_at
main source_metadata: id, source_id, language, country, region, city, timezone, robots_txt_url, robots_allowed, crawl_delay, sitemap_url, favicon_url, logo_url, contact_email, social_twitter, social_facebook, social_linkedin, alexa_rank, last_checked, notes
main source_qualification_attempts: id, source_id, attempted_at, verdict, criteria_version
main sources: id, name, domain, rss_url, feed_key, outlet_id, rate_limit_ms, enabled, priority, tags, reliability_score, language, region, country, source_type, update_frequency, cacheability, article_count, counter_reconciled_at, status, qualified_at, qualification_criteria_version, last_crawled_at, catalog_baseline
main spell_deletes: term_delete, keyword_id
main stat_figures: id, agency, series_id, ref_area, time_period, value, unit, methodology_ref, adjustment, base_year, extracted_at, created_at
main stat_snapshots: id, metric, taken_at, value, created_at
main stat_subscriptions: id, source, indicator, country, dataset, params_json, agency, interval_days, enabled, created_at, last_fetched_at, last_status
main watch_matches: id, watch_id, matched_at, n_articles, new_articles, article_ids
main watches: id, name, query, threshold, window_days, enabled, created_at, last_evaluated_at, last_matched_at, last_seen_ids, filters
main wiki_pages: id, wiki, title, pageid, watched, category, baseline_revid, baseline_text, last_revid, latest_text, latest_text_revid, last_checked_at, missing, wiki_categories, created_at
main wiki_revisions: id, page_id, revid, parent_revid, timestamp, editor, editor_anon, comment, size, delta_bytes, tags, minor, bot, diff, full_text, ores_damaging, ores_goodfaith, ores_provenance, flagged, flag_reasons, created_at
main wikidata_items: qid, status, resolved_qid, labels_json, descriptions_json, claims_json, lastrevid, fetched_at
lane lane_meta: id, kind, schema_version, created_at
lane law_document_meta: id, lane_key, identity_id, language, title, translation_kind, translated_by, licence_id, source_authority, source_url, granularity, first_seen_at, updated_at
lane law_identities: id, identity_scheme, document_identity, jurisdiction_alpha3, jurisdiction_level, doc_type, legal_system, status, issuing_body, enacted_on, published_on, commenced_on, repealed_on, created_at
lane law_provisions: id, revision_lane_key, document_lane_key, address, ordinal, num, heading, text, content_hash, created_at
lane medical_cited: id, id_kind, value, seen_at
lane medical_class_changes: id, pmid, version, from_class, to_class, source_file, recorded_at
lane medical_files: id, name, size_bytes, sha256, started_at, finished_at, status, error, articles_read, deletions_read, books_skipped, skipped_json, kept, updated, withdrawn, older_skipped
lane medical_papers: id, pmid, version, citation_status, title, vernacular_title, abstract_json, abstract_copyright, journal, pub_date, pub_date_text, languages_json, publication_types_json, mesh_json, keywords_json, doi, pmcid, provenance_class, notice_kind, status_links_json, text_truncated, source_file, first_seen_at, last_seen_at, withdrawn_at, withdrawn_in_file
lane medical_wanted: id, id_kind, value, added_at
lane osm_admin1_splits: id, alpha3, status, basis_ingest, outline_vintage, outline_source, started_at, finished_at, seconds, regions_json, outside, no_point, error
lane osm_countries: id, alpha2, alpha3, name, relation_id, status, extract_name, extract_bytes, extract_vintage, reader, started_at, finished_at, ingest_seconds, counts_json, blob_json, border_json, error, extract_sequence, border_rings, diff_sequence, diff_timestamp
lane osm_diff_runs: id, alpha3, sequence, diff_timestamp, applied_at, bytes_fetched, fetch_seconds, apply_seconds, counts_json
lane osm_history_changes: id, country_alpha3, osm_type, osm_id, object_version, version_timestamp, change, key, old_value, new_value
lane osm_history_cuts: id, alpha3, status, history_name, history_bytes, history_vintage, reader, started_at, finished_at, ingest_seconds, counts_json, span_json, error
lane osm_history_monthly: id, alpha3, surface, kind, bucket, name, direction, n
lane osm_history_summaries: id, alpha3, surface, rule_version, cut_finished_at, history_vintage, built_at, seconds, rows
lane osm_objects: id, osm_type, osm_id, version, timestamp, country_alpha3, kind, notable, primary_key, primary_value, lat, lon, geom, node_count, members, names, contact, payment, disused, t_name, t_brand, t_brand_wikidata, t_operator, t_opening_hours, t_website, t_phone, t_email, t_wikidata, t_wikipedia, t_cuisine, t_level, t_check_date, t_wheelchair, t_addr_housenumber, t_addr_street, t_addr_place, t_addr_postcode, t_addr_city, t_addr_country, t_addr_unit, t_addr_suburb, t_addr_district, t_addr_state, t_addr_province, t_amenity, t_shop, t_tourism, t_leisure, t_office, t_craft, t_healthcare, t_historic, t_emergency, t_club, t_public_transport, t_aeroway, t_place, t_boundary, t_admin_level, t_highway, t_building, t_sport, t_religion, t_denomination, t_brand_wikipedia, t_operator_wikidata, t_operator_type, t_network, t_ref, t_official_name, t_alt_name, t_old_name, t_short_name, t_loc_name, t_int_name, t_population, t_capital, t_is_in, t_iso3166_1, t_iso3166_1_alpha2, t_iso3166_2, t_border_type, t_type, t_description, t_internet_access, t_takeaway, t_delivery, t_outdoor_seating, t_drive_through, t_smoking, t_fee, t_capacity, t_diet_vegetarian, t_start_date, t_email_verified, t_fax, t_url, t_image, t_wikimedia_commons, t_heritage, t_ele, t_building_levels, t_building_material, t_building_use, t_roof_shape, t_roof_levels, t_height, t_surface, t_oneway, t_maxspeed, t_lanes, t_lit, t_sidewalk, t_service, t_access, t_foot, t_bicycle, t_motor_vehicle, t_bridge, t_tunnel, t_layer, t_junction, t_width, t_smoothness, t_tracktype, t_cycleway, t_parking_lane, t_source, t_note, t_fixme, other_tags
lane osm_places_counts: id, alpha3, part, name, n
lane osm_places_days: id, alpha3, part, day, n
lane osm_places_summaries: id, alpha3, rule_version, cut_finished_at, diff_sequence, built_at, seconds, rows
lane osm_places_values: id, alpha3, part, key, value, n
lane osm_search_indexes: id, alpha3, basis_ingest, names, addresses, addresses_no_point, built_at, seconds
lane osm_tag_changes: id, osm_type, osm_id, key, change, old_value, new_value, diff_timestamp, object_version, recorded_at, country_alpha3, object_event
lane osm_view_cells: id, alpha3, level, cx, cy, n, slat, slon
lane osm_view_indexes: id, alpha3, basis_ingest, rows, no_box, built_at, seconds
lane versioned_baselines: id, entity_id, revision_ref, captured_at, revised_at, content_hash, content, byte_size
lane versioned_changes: id, entity_id, external_id, change_ref, feed, change_kind, occurred_at, recorded_at, cursor_token, byte_delta, ingested_revision_id
lane versioned_cursors: id, feed, token, updated_at, contiguous_through
lane versioned_disclosures: id, text_key, shown_at, note
lane versioned_entities: id, external_id, qid, title, language, country_alpha3, pinned, watching, admitted_reason, first_seen_at, last_checked_at, deleted_at
lane versioned_entity_facts: id, entity_id, name, value_json, revision_ref, observed_at
lane versioned_gaps: id, feed, detected_at, from_token, to_token, from_time, to_time, reason, closed_at
lane versioned_revisions: id, entity_id, revision_ref, observed_at, revised_at, content_hash, content, byte_size, diff_from_ref, diff_added, diff_removed, diff_byte_delta, diff_text, diff_method, article_id
lane versioned_size_samples: id, measured_at, file_bytes, method
lane wiki_lane_docs: id, source, owner_id, edition, page_id, title, revid, extent, successor_revid, revised_at, mask, chars, indexed_at
lane wiki_lane_hourly: id, hour_start, metric, edition, kind, n, sum_ms, max_ms, sum_bytes, sum_pages, max_retry_after_s, last_detail, last_at
lane wiki_lane_index_queue: kind, ref, failed_at
lane wiki_lane_index_state: key, format_version, segmenters, docs, chars, created_at, updated_at
lane wiki_lane_tracked: owner_id, revid, successor_revid, edition, has_text, article_rev
lane wiki_walk_cursors: edition, pass_no, continue_json, pages_seen, requests, response_bytes, started_at, updated_at, completed_at, edition_articles, edition_articles_read_at, consecutive_failures, last_error, last_error_at
lane wiki_walk_pages: edition, page_id, title, qid, length_bytes, last_revid, walked_at, pass_no
lane wiki_walk_samples: id, hour_start, transport, requests, pages, response_bytes, busy_ms
lane wiki_warm_editions: edition, pages_with_text, texts_fetched, requests, response_bytes, promoted, updated_at
lane wiki_warm_pages: id, edition, page_id, title, wanted_revid, wanted_at, due_since, latest_revid, latest_text, latest_bytes, latest_revised_at, fetched_at, previous_revid, previous_text, previous_bytes, previous_revised_at, deleted_at, promoted_at, no_text_reason
lane wiki_warm_scan: key, last_change_id, updated_at
```
