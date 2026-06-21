"""
Selective backup: excluding imported newsletters from the corpus snapshot.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer 2026-06-21: a backup must be able to LEAVE OUT imported-newsletter
(.eml / mailbox) articles, so a user fixing the importer can back up without the
faulty ones and re-import clean copies. The filter runs ONLY on the disposable
plaintext corpus snapshot (never the live DB) and must remove every dependent row
(any table with an article_id column) so the restore's foreign_key_check is clean.
Stdlib-only (sqlite3) — runs without the app's heavy deps.
"""

import sqlite3

from src.backup.artifact import _drop_newsletter_articles


def _make_db(p):
    con = sqlite3.connect(str(p))
    con.executescript(
        """
        CREATE TABLE sources (id INTEGER PRIMARY KEY, domain TEXT);
        CREATE TABLE articles (id INTEGER PRIMARY KEY, source_id INTEGER, title TEXT);
        CREATE TABLE keyword_mentions (id INTEGER PRIMARY KEY, article_id INTEGER, term TEXT);
        CREATE TABLE article_analyses (id INTEGER PRIMARY KEY, article_id INTEGER, kind TEXT);
        CREATE TABLE settings (k TEXT, v TEXT);
        """
    )
    con.executemany(
        "INSERT INTO sources (id, domain) VALUES (?,?)",
        [(1, "newsletters.import.local"), (2, "bbc.com"), (3, "mailbox.import.local")],
    )
    con.executemany(
        "INSERT INTO articles (id, source_id, title) VALUES (?,?,?)",
        [(10, 1, "nl a"), (11, 1, "nl b"), (12, 3, "mbx"), (20, 2, "real")],
    )
    con.executemany(
        "INSERT INTO keyword_mentions (article_id, term) VALUES (?,?)",
        [(10, "x"), (11, "y"), (12, "z"), (20, "keep")],
    )
    con.executemany(
        "INSERT INTO article_analyses (article_id, kind) VALUES (?,?)",
        [(10, "summary"), (20, "summary")],
    )
    con.execute("INSERT INTO settings VALUES ('a','b')")
    con.commit()
    con.close()


def test_drops_only_newsletter_articles_and_their_dependents(tmp_path):
    p = tmp_path / "corpus.db"
    _make_db(p)
    n = _drop_newsletter_articles(p)
    assert n == 3  # 10, 11 (.eml) + 12 (mailbox)
    con = sqlite3.connect(str(p))
    cur = con.cursor()
    # newsletter articles + dependents gone; the real article + its rows remain
    assert [r[0] for r in cur.execute("SELECT id FROM articles ORDER BY id")] == [20]
    assert [r[0] for r in cur.execute("SELECT article_id FROM keyword_mentions ORDER BY article_id")] == [20]
    assert [r[0] for r in cur.execute("SELECT article_id FROM article_analyses")] == [20]
    # source rows LEFT (a future re-import re-attaches); non-article tables untouched
    assert cur.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 3
    assert cur.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 1
    con.close()


def test_no_newsletter_source_is_a_noop(tmp_path):
    p = tmp_path / "c.db"
    con = sqlite3.connect(str(p))
    con.executescript(
        "CREATE TABLE sources(id INTEGER PRIMARY KEY, domain TEXT);"
        "CREATE TABLE articles(id INTEGER PRIMARY KEY, source_id INTEGER);"
    )
    con.execute("INSERT INTO sources VALUES (1,'bbc.com')")
    con.execute("INSERT INTO articles VALUES (1,1)")
    con.commit()
    con.close()
    assert _drop_newsletter_articles(p) == 0
    con = sqlite3.connect(str(p))
    assert con.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 1
    con.close()
