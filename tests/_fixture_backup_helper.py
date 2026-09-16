"""Build / restore the row-K fixture backup in a SUBPROCESS with its own OO_DATA_DIR.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY A SUBPROCESS, AND NOT A monkeypatched env. ``data_dir()`` re-reads the environment
on every call, but ``live_db_path()`` goes through ``src.database.session.engine``, which
is a module-level singleton frozen at import. An in-process "write from data dir A, then
restore into data dir B" would therefore write and restore against the SAME database and
pass while proving nothing -- a self-restore, which sees every row as a duplicate and can
never exercise a handler. Two processes is what actually gives two corpora.

Invoked by ``tests/test_restore_fixture_matrix.py``; prints ONE json object on stdout.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_T0 = datetime(2026, 9, 1, tzinfo=UTC).replace(tzinfo=None)
_SKIP = datetime(2030, 1, 1, tzinfo=UTC).replace(tzinfo=None)

#: PRE-MIGRATION country values: alpha-3, the form Q301 = c will store in 0.5 and the
#: form a backup taken after that flip carries. Restoring one into a 0.4 corpus is
#: exactly the case Q310 = a exists for.
_FIXTURE_COUNTRIES = ("FRA", "DEU", "fr")

_LOCAL_RING = """rings:
  - id: fixture-local-ring
    members: ["en:widget", "fr:bidule"]
"""


def _bootstrap() -> None:
    """Create this data dir's schema from the MODELS, the same metadata the migration
    chain converges on. ``alembic upgrade head`` is exercised separately (and by CI);
    here the point is a corpus, not a migration replay."""
    from sqlalchemy import text

    from src.database.models import Base
    from src.database.session import engine

    Base.metadata.create_all(engine)
    # STAMP the alembic revision. Without it the artifact carries no schema revision and
    # the restore refuses it as pre-0.0.8 -- an honest refusal that would make this
    # fixture test a test of that refusal rather than of the five payloads. Read from
    # alembic's own config, never hard-coded, so a new migration does not silently
    # freeze this fixture at an old head.
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = Path(__file__).resolve().parents[1]
    head = ScriptDirectory.from_config(Config(str(root / "alembic.ini"))).get_current_head()
    with engine.begin() as con:
        con.execute(text("CREATE TABLE IF NOT EXISTS alembic_version "
                         "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
        con.execute(text("DELETE FROM alembic_version"))
        con.execute(text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
                    {"v": head})


def _seed() -> dict:
    """Seed the corpus this data dir owns with one row per payload, then write the
    artifact under the PREVIOUS format literal."""
    from src.backup import artifact as art
    from src.database.models import (
        Article,
        FeedFetchState,
        KeywordTranslation,
        Source,
    )
    from src.database.session import SessionLocal

    _bootstrap()
    with SessionLocal() as s:
        for i, cc in enumerate(_FIXTURE_COUNTRIES):
            src = Source(name=f"Fixture {i}", domain=f"fx{i}.example", country=cc,
                         rss_url=f"https://fx{i}.example/feed.xml")
            s.add(src)
            s.flush()
            s.add(Article(
                source_id=src.id, title=f"Fixture article {i}",
                url=f"https://fx{i}.example/a{i}", canonical_url=f"https://fx{i}.example/a{i}",
                content=f"Fixture body {i}", country=cc, created_at=_T0,
                hash=hashlib.sha256(f"fixture-{i}".encode()).hexdigest(),
            ))
            if i == 0:  # payload 4: a fetch history worth adopting
                s.add(FeedFetchState(
                    source_id=src.id, etag='"fixture-etag"',
                    last_modified="Mon, 01 Sep 2026 09:00:00 GMT", last_status=200,
                    last_checked_at=_T0, consecutive_unchanged=4, skip_until=_SKIP,
                ))
        # payload 3: the tentative translation table
        s.add(KeywordTranslation(
            term="chat", source_lang="fr", target_lang="en", text="cat",
            model="fixture-m1", prompt_version="kw-translate-v1", created_at=_T0,
        ))
        s.commit()

    # payload 2: a LOCAL ring file in this data dir, so the artifact carries one
    from src.analytics import equivalence as eq

    local = Path(eq.local_rings_path())
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(_LOCAL_RING, encoding="utf-8")

    dest = Path(os.environ["OO_FIXTURE_DEST"])
    dest.unlink(missing_ok=True)
    # THE FIXTURE IS GENUINELY OLD-FORMAT, not a resigned copy: the real writer runs
    # with the PREVIOUS literal in place, so the manifest carries it and the signature
    # covers it. A manifest rewritten after the fact has a broken signature and would
    # exercise the signature refusal instead of the schema acceptance.
    previous = os.environ["OO_FIXTURE_SCHEMA"]
    current, art.BACKUP_SCHEMA = art.BACKUP_SCHEMA, previous
    try:
        art.write_backup_v2(dest, passphrase=None)
    finally:
        art.BACKUP_SCHEMA = current
    return {"dest": str(dest), "schema_written": previous, "current_schema": current,
            "bytes": dest.stat().st_size}


def _restore() -> dict:
    """Restore the fixture into THIS (empty, different) corpus and report every payload."""
    from src.analytics import equivalence as eq
    from src.api.backup_v2 import restore_legacy_path
    from src.backup.country_codes import scan_country_code_duplicates
    from src.database.models import FeedFetchState, KeywordTranslation, Source
    from src.database.session import SessionLocal, engine

    _bootstrap()
    src_path = os.environ["OO_FIXTURE_DEST"]
    trust = os.environ.get("OO_FIXTURE_TRUST", "1") == "1"
    report = restore_legacy_path(src_path, None, trust_fetch_history=trust)

    out: dict = {"restore_ok": True, "artifact_kind": report.get("artifact_kind")}
    with SessionLocal() as s:
        out["countries"] = sorted(
            c for (c,) in s.query(Source.country).all() if c is not None
        )
        out["translations"] = [
            (t.term, t.source_lang, t.target_lang, t.text, t.model, t.prompt_version)
            for t in s.query(KeywordTranslation).all()
        ]
        fetch = s.query(FeedFetchState).all()
        out["fetch_rows"] = [
            {"etag": f.etag, "skip_until": f.skip_until is not None,
             "last_checked_at": f.last_checked_at is not None}
            for f in fetch
        ]
    eq.invalidate_ring_caches()
    out["ring_ids"] = sorted(r.id for r in eq.load_rings())
    out["local_ring_present"] = Path(eq.local_rings_path()).exists()

    # payload 1's artifact: the duplicate-key scan, read straight off the restored DB.
    with engine.connect() as con:
        raw = con.connection.dbapi_connection
        out["scan"] = scan_country_code_duplicates(raw)
    out["merge_report_keys"] = sorted(report.keys())
    # The per-table merge counts ride under ``plan`` in a run_restore report (they are
    # `merge_corpus`'s own ``counts`` dict, carried through), which is where an operator
    # reading the persisted report finds them. Read from there rather than from a
    # "counts" key that does not exist -- a measurement no surface reads is the recorded
    # dead-end shape, and the same is true of one a test reads from the wrong place.
    plan = report.get("plan") or {}
    out["fetch_history_block"] = plan.get("_fetch_history")
    out["country_codes_block"] = plan.get("_country_codes")
    out["rings_block"] = report.get("side_files", {}).get("rings") or report.get("rings")
    return out


if __name__ == "__main__":
    mode = sys.argv[1]
    print(json.dumps(_seed() if mode == "seed" else _restore(), default=str))
