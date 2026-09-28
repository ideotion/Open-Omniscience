"""Seed a plaintext data folder for the S6 walk (the Living sources view).

The walk cannot make the Wikipedia stream, the law tracker or a map download produce
changes on demand with no network, so each is written the way its own code writes it:

* the Wikipedia lane through ``create_lane`` and the pipeline's ``ensure_entity``: two
  followed pages, a change with its text stored and a diff, one only COUNTED, one whose
  kind the lane does not know, one on a page nobody follows, a feed cursor and one open gap;
* two tracked pages in the main database, one with revisions and a diff, one never checked;
* two law documents, a real change with a flagged diff and a re-check with no change;
* three map regions: done, paused by airplane mode, failed with an error.

Everything here is invented and labelled so (the ``.invalid`` hosts, the ``Walk`` titles).
"""
from datetime import UTC, datetime, timedelta

from src.database.models import LawDocument, LawRevision, WikiPage, WikiRevision
from src.database.session import SessionLocal, init_db
from src.geo.osm_downloads import get_manager as osm_manager
from src.versioned.models import VersionedChange, VersionedCursor, VersionedGap, VersionedRevision
from src.versioned.pipeline import ensure_entity
from src.versioned.store import create_lane, lane_session

init_db()
now = datetime.now(UTC)
naive = now.replace(tzinfo=None)

create_lane("wiki")
with lane_session("wiki") as lane:
    rome = ensure_entity(lane, "en:Walk Rome", title="Walk Rome", language="en")
    lyon = ensure_entity(lane, "fr:Walk Lyon", title="Walk Lyon", language="fr")
    lane.flush()
    first = VersionedRevision(entity_id=rome.id, revision_ref="1001", content_hash="h1",
                              content="Rome is a city.\n", diff_method="no-previous-text")
    lane.add(first)
    lane.flush()
    second = VersionedRevision(
        entity_id=rome.id, revision_ref="1002", content_hash="h2",
        content="Rome is the capital city of Italy.\nIt has <b>many</b> churches.\n",
        diff_method="unified", diff_added=2, diff_removed=1, diff_from_ref="1001",
        diff_text=("--- 1001\n+++ 1002\n@@ -1 +1,2 @@\n-Rome is a city.\n"
                   "+Rome is the capital city of Italy.\n+It has <b>many</b> churches.\n"),
    )
    lane.add(second)
    lane.flush()
    lane.add_all([
        VersionedChange(entity_id=rome.id, change_ref="c1", feed="stream:en", change_kind="edit",
                        recorded_at=now - timedelta(minutes=5), ingested_revision_id=second.id,
                        byte_delta=38),
        VersionedChange(entity_id=rome.id, change_ref="c0", feed="stream:en", change_kind="create",
                        recorded_at=now - timedelta(days=2), ingested_revision_id=first.id,
                        byte_delta=16),
        VersionedChange(entity_id=lyon.id, change_ref="c2", feed="stream:fr", change_kind="edit",
                        recorded_at=now - timedelta(minutes=20), byte_delta=-120),
        VersionedChange(entity_id=lyon.id, change_ref="c3", feed="stream:fr", change_kind="log",
                        recorded_at=now - timedelta(hours=3)),
        VersionedChange(external_id="en:Somewhere else", change_ref="c4", feed="stream:en",
                        change_kind="edit", recorded_at=now - timedelta(minutes=2)),
        VersionedCursor(feed="stream:en", contiguous_through=now - timedelta(minutes=3), updated_at=now),
        VersionedCursor(feed="stream:fr", contiguous_through=now - timedelta(hours=6),
                        updated_at=now - timedelta(minutes=1)),
        VersionedGap(feed="stream:fr", reason="reconnect"),
    ])
    lane.commit()

db = SessionLocal()
try:
    tracked = WikiPage(wiki="en", title="Walk Tracked Page", watched=True,
                       last_checked_at=naive - timedelta(hours=1))
    never = WikiPage(wiki="fr", title="Walk Page jamais vérifiée", watched=True)
    db.add_all([tracked, never])
    db.flush()
    db.add_all([
        WikiRevision(page_id=tracked.id, revid=501, parent_revid=500, timestamp=naive - timedelta(hours=2),
                     editor="WalkEditor", comment="expanded the history section", size=4200,
                     delta_bytes=812, diff="+A new paragraph about the history.\n-An old line.",
                     created_at=naive - timedelta(hours=1)),
        WikiRevision(page_id=tracked.id, revid=502, parent_revid=501, timestamp=naive - timedelta(minutes=50),
                     editor="192.0.2.7", editor_anon=True, comment="", size=1200, delta_bytes=-3000,
                     diff="-Most of the article.", flagged=True, flag_reasons="large-removal",
                     created_at=naive - timedelta(minutes=45)),
    ])
    code = LawDocument(jurisdiction="fr", title="Walk Code civil (extract)",
                       url="https://law.walk.invalid/fr/code", last_checked_at=naive - timedelta(hours=4))
    act = LawDocument(jurisdiction="uk", title="Walk Act 2026", url="https://law.walk.invalid/uk/act")
    db.add_all([code, act])
    db.flush()
    db.add_all([
        LawRevision(document_id=code.id, content_hash="l1", delta_bytes=-640, observed_at=naive - timedelta(hours=4),
                    flagged=True, flag_reasons="large-removal",
                    diff="-Article 12: the old wording.\n+Article 12: the new wording."),
        LawRevision(document_id=code.id, content_hash="l2", delta_bytes=0, observed_at=naive - timedelta(hours=1)),
    ])
    db.commit()
finally:
    db.close()

m = osm_manager()
done = m._entry_for("antarctica")
done.status, done.total_bytes, done.downloaded_bytes = "done", 31_000_000, 31_000_000
paused = m._entry_for("asia")
paused.status, paused.paused_by = "paused", "airplane"
paused.total_bytes, paused.downloaded_bytes = 1_300_000_000, 212_000_000
failed = m._entry_for("africa")
failed.status, failed.error = "error", "HTTP 503 from the mirror"
m._save()
print("seeded: wiki lane (4 followed changes, 1 not followed, 1 open gap), 2 tracked pages, 2 law documents, 3 map regions")
