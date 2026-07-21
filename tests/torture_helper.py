"""
Subprocess workhorse for the DB-reliability torture suite.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each invocation runs in its OWN process with its OWN ``OO_DATA_DIR`` (set by the
test), because the app engine binds its database at import time -- and because
half of these scenarios end in deliberate SIGKILL. Output protocol: the LAST
stdout line is a JSON verdict (alembic logs precede it).

Commands:
    build A|B [--artifact PATH] [--passphrase PW] [--custody ok|tampered|none]
    merge ARTIFACT [--passphrase PW] [--commit] [--kill-at HANDLER|swap]
    dump                       content-signature per table (id-independent)
    fts-find TOKEN             FTS match count
    verify-custody             local chain + imported chains state
    make-old PATH REV          historical-schema corpus with minimal rows
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path


def _emit(obj: dict) -> None:
    print(json.dumps(obj))


def _h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


SHARED_BODY = "Shared body: the two corpora both scraped this exact page."


def cmd_build(args) -> None:
    from src.database.session import init_db, session_scope

    init_db()
    from src.database.models import (
        Article,
        CommodityPrice,
        Keyword,
        KeywordMention,
        KeywordSuperGroup,
        KeywordSuperGroupMember,
        LawDocument,
        Source,
        WikiPage,
        WikiRevision,
    )
    from src.paths import data_dir

    mode = args.mode
    with session_scope() as s:
        src = Source(name="Shared Wire", domain="wire.example")
        s.add(src)
        s.flush()
        if mode == "B":  # filler shifts B's ids so remapping is actually exercised
            src_b = Source(name="B Local", domain="b-local.example")
            s.add(src_b)
            s.flush()
            s.add(
                Article(
                    url="https://b-local.example/filler",
                    canonical_url="https://b-local.example/filler",
                    source_id=src_b.id, title="B filler",
                    content="b filler body", hash=_h("b filler body"),
                )
            )
            s.flush()
        shared = Article(
            url="https://wire.example/shared", canonical_url="https://wire.example/shared",
            source_id=src.id, title="Shared story", content=SHARED_BODY,
            hash=_h(SHARED_BODY), language="en",
        )
        s.add(shared)
        s.flush()
        body = f"unique-to-{mode} body text"
        uniq = Article(
            url=f"https://wire.example/{mode}", canonical_url=f"https://wire.example/{mode}",
            source_id=src.id, title=f"Only in {mode}", content=body, hash=_h(body),
            language="en",
        )
        s.add(uniq)
        s.flush()
        kw_shared = Keyword(term="elections", normalized_term="elections", language="en", frequency=3)
        kw_uniq = Keyword(term=f"kw-{mode}", normalized_term=f"kw-{mode}", language="en", frequency=1)
        s.add_all([kw_shared, kw_uniq])
        s.flush()
        s.add(KeywordMention(keyword_id=kw_shared.id, article_id=shared.id, count=2,
                             observed_on=date(2026, 6, 1), country="fr", extractor="baseline"))
        s.add(KeywordMention(keyword_id=kw_uniq.id, article_id=uniq.id, count=1,
                             observed_on=date(2026, 6, 2), extractor="baseline"))
        sg = KeywordSuperGroup(name=f"group-{mode}", color="#123456")
        s.add(sg)
        s.flush()
        s.add(KeywordSuperGroupMember(supergroup_id=sg.id, normalized_term="elections"))
        wp = WikiPage(wiki="fr", title=f"Page_{mode}", baseline_revid=100, last_revid=101)
        s.add(wp)
        s.flush()
        s.add(WikiRevision(page_id=wp.id, revid=101,
                           timestamp=datetime(2026, 6, 1, tzinfo=UTC), editor="ed",
                           size=10, delta_bytes=5))
        s.add(LawDocument(jurisdiction="eu", title=f"Reg {mode}",
                          url=f"https://law.example/{mode}",
                          baseline_hash=_h(f"law{mode}"), last_hash=_h(f"law{mode}")))
        s.add(CommodityPrice(symbol="XAU", market="spot", observed_on=date(2026, 6, 1),
                             price=1000.0 if mode == "A" else 1234.5, currency="USD",
                             unit="ozt", source="feed:gold"))
        s.add(CommodityPrice(symbol=f"SYM{mode}", observed_on=date(2026, 6, 2), price=42.0,
                             currency="USD", unit="kg", source=f"feed:{mode}"))

    (data_dir() / "app_settings.json").write_text(
        json.dumps({"version": "oo-app-settings-1",
                    "theme": "dark" if mode == "B" else "light"}), "utf-8")
    (data_dir() / "calendar_feed_imports.json").write_text(
        json.dumps({"holidays": {"name": "Holidays", "events": {
            "fp-shared": {"title": "New Year", "date": "2026-01-01",
                          "sources": [f"feed{mode}"], "uids": []},
            f"fp-{mode}": {"title": f"Only {mode} day", "date": "2026-07-01",
                           "sources": [f"feed{mode}"], "uids": []}}}}), "utf-8")

    if args.custody != "none":
        from src.custody.log import CustodyLog

        with CustodyLog() as log:
            log.record("article:shared", _h(SHARED_BODY), "ingest", actor="op")
            log.record("article:uniq", _h(f"unique-to-{mode} body text"), "ingest", actor="op")
        if args.custody == "tampered":
            from src.database.connect import connect as db_connect

            con = db_connect(data_dir() / "custody_log.db")
            con.execute("UPDATE custody_entries SET item_hash = ? WHERE seq = 1", ("f" * 64,))
            con.commit()
            con.close()

    out: dict = {"built": mode}
    if args.artifact:
        from src.backup.artifact import write_backup_v2

        pw = args.passphrase if args.passphrase != "-" else None
        env = write_backup_v2(Path(args.artifact), passphrase=pw)
        out["artifact"] = args.artifact
        out["members"] = len(env["manifest"]["members"])
    _emit(out)


def cmd_merge(args) -> None:
    from src.backup import merge as merge_mod
    from src.backup.artifact import cleanup_staging, read_artifact
    from src.database.session import init_db

    init_db()

    if args.kill_at == "swap":
        real_replace = os.replace

        def _kill_replace(src_p, dst_p):  # SIGKILL exactly at the swap boundary
            if str(dst_p).endswith("open_omniscience.db"):
                os.kill(os.getpid(), signal.SIGKILL)
            return real_replace(src_p, dst_p)

        merge_mod.os.replace = _kill_replace  # type: ignore[attr-defined]
    elif args.kill_at:
        def _kill_handler(*_a, **_k):
            os.kill(os.getpid(), signal.SIGKILL)

        setattr(merge_mod, args.kill_at, _kill_handler)

    # Opt-in re-index crash injection (regression test for the "awaiting indexing"
    # count on a genuine whole-batch re-index failure): forces the post-swap
    # re-index step to raise, so the caller can assert run_restore's exception
    # handler reports the TRUE imported-article count as "failed", never 0.
    if args.crash_reindex:
        def _crash_reindex(*_a, **_k):
            raise RuntimeError("torture: forced re-index crash")

        merge_mod.reindex_imported_articles = _crash_reindex  # type: ignore[assignment]

    pw = args.passphrase if args.passphrase != "-" else None
    try:
        staged = read_artifact(Path(args.artifact).read_bytes(), passphrase=pw)
    except Exception as exc:  # noqa: BLE001 - verdict protocol
        _emit({"error": type(exc).__name__, "message": str(exc)[:300]})
        return
    try:
        # The torture suite validates the MERGE ENGINE (commutativity, idempotency,
        # crash-safety, dedup). The post-swap re-index of imported articles (P0-4) is a
        # one-directional post-step with its own test (test_reindex_on_import) — it makes
        # the FULL restore direction-dependent in DERIVED data BY DESIGN, so disable it
        # here to keep the engine's symmetry/determinism assertions meaningful. ``--reindex``
        # opts a specific test into the real post-swap re-index step (default stays off).
        report = merge_mod.run_restore(staged, commit=args.commit, reindex_imported=args.reindex)
        _emit({"report": report})
    except Exception as exc:  # noqa: BLE001
        _emit({"error": type(exc).__name__, "message": str(exc)[:300]})
    finally:
        cleanup_staging(staged)


_DUMP_SIGNATURES = {
    # id-independent content signatures: natural keys + payload, never row ids.
    "sources": "SELECT domain || '|' || COALESCE(name,'') FROM sources",
    "articles": "SELECT hash || '|' || COALESCE(title,'') || '|' || content FROM articles",
    "keywords": "SELECT normalized_term || '|' || COALESCE(language,'') FROM keywords",
    "keyword_mentions": (
        "SELECT k.normalized_term || '|' || a.hash || '|' || km.count"
        " FROM keyword_mentions km JOIN keywords k ON k.id = km.keyword_id"
        " JOIN articles a ON a.id = km.article_id"
    ),
    "keyword_supergroups": "SELECT name FROM keyword_supergroups",
    "wiki_pages": "SELECT wiki || '|' || title FROM wiki_pages",
    "wiki_revisions": (
        "SELECT p.wiki || '|' || p.title || '|' || r.revid"
        " FROM wiki_revisions r JOIN wiki_pages p ON p.id = r.page_id"
    ),
    "law_documents": "SELECT jurisdiction || '|' || url FROM law_documents",
    "commodity_prices": (
        "SELECT symbol || '|' || COALESCE(market,'') || '|' || observed_on || '|' ||"
        " price || '|' || COALESCE(source,'') FROM commodity_prices"
    ),
}


def cmd_dump(_args) -> None:
    from src.backup.sqlite_backup import live_db_path
    from src.database.connect import connect as db_connect
    from src.database.session import init_db

    init_db()
    con = db_connect(live_db_path())  # factory: opens encrypted stores too
    out = {}
    for table, sql in _DUMP_SIGNATURES.items():
        rows = sorted(r[0] for r in con.execute(sql).fetchall())
        out[table] = hashlib.sha256("\n".join(rows).encode()).hexdigest()
        out[table + "_n"] = len(rows)
    con.close()
    _emit({"dump": out})


def cmd_fts_find(args) -> None:
    from src.backup.sqlite_backup import live_db_path
    from src.database.connect import connect as db_connect
    from src.database.session import init_db

    init_db()
    con = db_connect(live_db_path())
    n = con.execute(
        "SELECT COUNT(*) FROM article_fts WHERE article_fts MATCH ?", (args.token,)
    ).fetchone()[0]
    con.close()
    _emit({"matches": n})


def cmd_verify_custody(_args) -> None:
    from src.custody.log import CustodyLog
    from src.paths import data_dir

    with CustodyLog() as log:
        ok, problems = log.verify()
    imported = []
    db = data_dir() / "custody_log.db"
    from src.database.connect import connect as db_connect

    con = db_connect(db)
    try:
        has = con.execute(
            "SELECT 1 FROM sqlite_master WHERE name='custody_imported_entries'"
        ).fetchone()
        if has:
            imported = [
                {"chain_id": r[0][:16], "entries": r[1], "verified": bool(r[2])}
                for r in con.execute(
                    "SELECT chain_id, COUNT(*), MIN(verified)"
                    " FROM custody_imported_entries GROUP BY chain_id"
                )
            ]
    finally:
        con.close()
    _emit({"local_ok": ok, "local_problems": problems[:3], "imported": imported})


def cmd_make_old(args) -> None:
    from src.database.migrate import upgrade_database_file

    path = Path(args.path)
    upgrade_database_file(path, target=args.rev)
    con = sqlite3.connect(str(path))
    con.execute(
        "INSERT INTO sources (name, domain, rate_limit_ms, enabled, priority,"
        " reliability_score, language, region, source_type) VALUES"
        " ('Old Wire', 'old.example', 2000, 1, 2, 5, 'en', 'global', 'news')"
    )
    sid = con.execute("SELECT id FROM sources WHERE domain='old.example'").fetchone()[0]
    body = "an article that lived in an old-schema corpus"
    con.execute(
        "INSERT INTO articles (url, canonical_url, source_id, title, content, hash)"
        " VALUES ('https://old.example/1', 'https://old.example/1', ?, 'Old story', ?, ?)",
        (sid, body, _h(body)),
    )
    con.commit()
    if args.strip_version:
        con.execute("DROP TABLE alembic_version")
        con.commit()
    if args.alien_version:
        con.execute("UPDATE alembic_version SET version_num = 'feedfacecafe'")
        con.commit()
    con.close()
    _emit({"made": str(path), "rev": args.rev})


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("mode", choices=["A", "B"])
    b.add_argument("--artifact", default=None)
    b.add_argument("--passphrase", default="-")
    b.add_argument("--custody", default="none", choices=["ok", "tampered", "none"])
    m = sub.add_parser("merge")
    m.add_argument("artifact")
    m.add_argument("--passphrase", default="-")
    m.add_argument("--commit", action="store_true")
    m.add_argument("--kill-at", default=None)
    m.add_argument("--reindex", action="store_true")
    m.add_argument("--crash-reindex", action="store_true")
    sub.add_parser("dump")
    f = sub.add_parser("fts-find")
    f.add_argument("token")
    sub.add_parser("verify-custody")
    o = sub.add_parser("make-old")
    o.add_argument("path")
    o.add_argument("rev")
    o.add_argument("--strip-version", action="store_true")
    o.add_argument("--alien-version", action="store_true")
    args = p.parse_args()
    {
        "build": cmd_build,
        "merge": cmd_merge,
        "dump": cmd_dump,
        "fts-find": cmd_fts_find,
        "verify-custody": cmd_verify_custody,
        "make-old": cmd_make_old,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
