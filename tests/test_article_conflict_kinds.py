"""The article conflict breakdown (field 2026-11-15): WHY two rows that share a hash differ.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``Article.hash`` is SHA-256 of the body with its whitespace collapsed, so a same-hash pair with different
bytes is either the same text laid out differently, or a body rewritten after it was stored. The merge
still keeps the local row and still counts every such pair as a conflict; this pins the breakdown that
says which kind each one was, and that the totals are unchanged.
"""

from __future__ import annotations

from src.backup.merge import ARTICLE_CONFLICT_KINDS, merge_corpus
from src.utils.url_utils import generate_content_hash
from tests.test_merge_engine import _BATCH_META, _article_rows, _build_corpus


def _art(n: int, content: str, hash_: str | None = None) -> dict:
    return {"url": f"https://s.example/{n}", "source_domain": "s.example",
            "hash": hash_ or generate_content_hash(content), "title": f"t{n}", "content": content}


def test_each_kind_is_counted_and_the_totals_stay_what_they_were(tmp_path):
    base = ["alpha beta gamma", "one two three", "red green blue", "sun moon star", "same text"]
    h = [generate_content_hash(t) for t in base]
    local = [
        _art(0, "alpha beta gamma"),                 # whitespace only (incoming adds line breaks)
        _art(1, "one two three EDITED", h[1]),       # the LOCAL body was rewritten after hashing
        _art(2, "red green blue"),                   # the INCOMING body was rewritten
        _art(3, "sun moon star CHANGED", h[3]),      # both rewritten
        _art(4, "same text"),                        # a plain duplicate
    ]
    incoming = [
        _art(0, "alpha\nbeta  gamma", h[0]),
        _art(1, "one two three"),
        _art(2, "red green blue CHANGED", h[2]),
        _art(3, "sun moon star OTHER", h[3]),
        _art(4, "same text"),
        _art(5, "brand new article"),
    ]
    working, staged = tmp_path / "w.db", tmp_path / "s.db"
    _build_corpus(working, [{"domain": "s.example"}], local)
    _build_corpus(staged, [{"domain": "s.example"}], incoming)

    counts, _ = merge_corpus(staged, working, _BATCH_META)

    assert counts["articles"]["conflict"] == 4
    assert counts["articles"]["duplicate"] == 1
    assert counts["articles"]["new"] == 1
    kinds = counts["_article_conflicts"]
    assert set(kinds) == set(ARTICLE_CONFLICT_KINDS)
    assert kinds == {"whitespace_only": 1, "local_changed": 1, "incoming_changed": 1,
                     "both_changed": 1, "unclassified": 0}
    assert sum(kinds.values()) == counts["articles"]["conflict"]
    # the sample is still taken, and the local rows are untouched
    assert {c["hash"] for c in counts["articles"]["conflicts"]} == {h[0], h[1], h[2], h[3]}
    by_hash = {r["hash"]: r["content"] for r in _article_rows(working)}
    assert by_hash[h[1]] == "one two three EDITED" and by_hash[h[0]] == "alpha beta gamma"



def test_a_body_that_is_not_text_is_counted_and_never_aborts_the_merge(tmp_path):
    """A BLOB body, or one that is not valid UTF-8, used to be counted in SQL only; the breakdown reads it in
    Python, so it must decode with replacement rather than raise inside the merge transaction."""
    import sqlite3

    working, staged = tmp_path / "w.db", tmp_path / "s.db"
    h = generate_content_hash("body text")
    _build_corpus(working, [{"domain": "s.example"}], [_art(0, "body text"), _art(1, "other body")])
    _build_corpus(staged, [{"domain": "s.example"}], [_art(0, "body text"), _art(1, "other body")])
    con = sqlite3.connect(staged)
    con.execute("UPDATE articles SET content = ? WHERE hash = ?", (b"body\xff text", h))
    con.execute("UPDATE articles SET content = CAST(? AS TEXT) WHERE hash = ?",
                (b"other \xfe body", generate_content_hash("other body")))
    con.commit()
    con.close()

    counts, _ = merge_corpus(staged, working, _BATCH_META)

    assert counts["articles"]["conflict"] == 2
    assert sum(counts["_article_conflicts"].values()) == 2
