"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com

---

T3 — keyword policy systemic fixes (field report #4 queued findings):
source self-names suppressed as a per-article RULE (never a stoplist — other
sources' mentions of the outlet stay); per-source concentration suspects
surfaced with real counts in the diagnostics export (flag, never auto-hide);
language-attribution mismatches flagged from signature evidence.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text


@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app) as c:
        yield c


def test_self_name_forms_cover_name_and_domain():
    from src.analytics.store import _self_name_forms
    from src.database.models import Source

    src = Source(name="The Moscow Times", domain="www.themoscowtimes.com")
    forms = _self_name_forms(src)
    assert "the moscow times" in forms
    assert "moscow times" in forms  # leading article stripped
    assert "themoscowtimes" in forms  # registrable domain label
    assert "themoscowtimes.com" in forms
    # Shared single words are NOT suppressed — "moscow" stays a real keyword.
    assert "moscow" not in forms and "times" not in forms
    assert _self_name_forms(None) == set()


def test_index_article_suppresses_own_source_name_only(client):
    from src.analytics.extract import BaselineExtractor
    from src.analytics.store import index_article
    from src.database.models import Article, Keyword, KeywordMention, Source
    from src.database.session import session_scope

    with session_scope() as s:
        own = Source(name="The Moscow Times", domain="kwpol-own.example")
        other = Source(name="Unrelated Gazette", domain="kwpol-other.example")
        s.add_all([own, other])
        s.flush()
        text_body = (
            "The Moscow Times reported on the harvest. The Moscow Times said the "
            "drought continues across the region and the harvest is weak."
        )
        a1 = Article(
            url="https://kwpol-own.example/1",
            canonical_url="https://kwpol-own.example/1",
            source_id=own.id,
            title="Own outlet",
            content=text_body,
            language="en",
            hash="kwpol" + "1" * 59,
            published_at=None,
        )
        a2 = Article(
            url="https://kwpol-other.example/2",
            canonical_url="https://kwpol-other.example/2",
            source_id=other.id,
            title="Other outlet",
            content=text_body,
            language="en",
            hash="kwpol" + "2" * 59,
        )
        s.add_all([a1, a2])
        s.flush()
        ex = BaselineExtractor()
        r1 = index_article(s, a1, extractor=ex)
        r2 = index_article(s, a2, extractor=ex)
        assert r1["self_name_suppressed"] >= 1, "own-source name must be suppressed"
        assert r2["self_name_suppressed"] == 0, "another outlet naming it is CONTENT"

        def terms_of(article_id: int) -> set[str]:
            rows = (
                s.query(Keyword.normalized_term)
                .join(KeywordMention, KeywordMention.keyword_id == Keyword.id)
                .filter(KeywordMention.article_id == article_id)
                .all()
            )
            return {r[0] for r in rows}

        assert "moscow times" not in terms_of(a1.id)
        assert "the moscow times" not in terms_of(a1.id)
        assert "moscow times" in terms_of(a2.id) or "the moscow times" in terms_of(a2.id)
        # cleanup
        for aid in (a1.id, a2.id):
            s.query(KeywordMention).filter_by(article_id=aid).delete()
        s.query(Article).filter(Article.id.in_([a1.id, a2.id])).delete()
        s.query(Source).filter(Source.id.in_([own.id, other.id])).delete()


@pytest.fixture()
def concentrated_corpus(client):
    """One source with 12 articles, a keyword in 11 of them (boilerplate
    shape); a control keyword spread over two sources."""
    from src.database.models import Article, Keyword, KeywordMention, Source
    from src.database.session import session_scope

    with session_scope() as s:
        boiler = Source(name="Boiler Daily", domain="kwconc-boiler.example")
        spread = Source(name="Spread Post", domain="kwconc-spread.example")
        s.add_all([boiler, spread])
        s.flush()
        kw_b = Keyword(term="alla artiklar", normalized_term="alla artiklar", language="sv")
        kw_s = Keyword(term="kwconc-control", normalized_term="kwconc-control", language="en")
        s.add_all([kw_b, kw_s])
        s.flush()
        art_ids = []
        for i in range(12):
            a = Article(
                url=f"https://kwconc-boiler.example/{i}",
                canonical_url=f"https://kwconc-boiler.example/{i}",
                source_id=boiler.id,
                title=f"b{i}",
                content="x",
                language="sv",
                hash=f"kwconcb{i:057d}",
            )
            s.add(a)
            art_ids.append(a)
        a_other = Article(
            url="https://kwconc-spread.example/0",
            canonical_url="https://kwconc-spread.example/0",
            source_id=spread.id,
            title="s0",
            content="x",
            language="en",
            hash="kwconcs" + "0" * 57,
        )
        s.add(a_other)
        s.flush()
        for a in art_ids[:11]:
            s.add(
                KeywordMention(
                    keyword_id=kw_b.id, article_id=a.id, count=1, observed_on=date(2026, 5, 1)
                )
            )
        s.add(KeywordMention(keyword_id=kw_s.id, article_id=art_ids[0].id, count=1))
        s.add(KeywordMention(keyword_id=kw_s.id, article_id=a_other.id, count=1))
        ids = {
            "kw": [kw_b.id, kw_s.id],
            "arts": [a.id for a in art_ids] + [a_other.id],
            "srcs": [boiler.id, spread.id],
        }
    yield ids
    with session_scope() as s:
        s.execute(text(f"DELETE FROM keyword_mentions WHERE keyword_id IN ({ids['kw'][0]},{ids['kw'][1]})"))
        s.execute(text(f"DELETE FROM keywords WHERE id IN ({ids['kw'][0]},{ids['kw'][1]})"))
        art_list = ",".join(str(i) for i in ids["arts"])
        src_list = ",".join(str(i) for i in ids["srcs"])
        s.execute(text(f"DELETE FROM articles WHERE id IN ({art_list})"))
        s.execute(text(f"DELETE FROM sources WHERE id IN ({src_list})"))


def test_export_flags_concentration_suspects(client, concentrated_corpus):
    body = json.loads(client.get("/api/diagnostics/keywords").content)
    sec = body["data"]["per_source_concentration"]
    assert sec["thresholds"]["min_share_of_keyword"] == 0.9
    by_term = {s["term"]: s for s in sec["suspects"]}
    assert "alla artiklar" in by_term, "the boilerplate-shaped keyword must be flagged"
    flagged = by_term["alla artiklar"]
    assert flagged["source"] == "Boiler Daily"
    assert flagged["in_this_source"] == 11 and flagged["source_article_total"] == 12
    assert "kwconc-control" not in by_term, "a spread keyword must not be flagged"
    # The flag NEVER hides: the keyword itself still exports normally.
    terms = {k["term"] for k in body["data"]["keywords"]}
    assert "alla artiklar" in terms


def test_export_flags_language_mismatch(client, concentrated_corpus):
    """kw stored as sv… mentioned only in sv articles -> no mismatch; the
    control keyword (stored en, mentioned in sv+en) depends on dominance —
    assert the field exists and is boolean for every entry."""
    body = json.loads(client.get("/api/diagnostics/keywords").content)
    entries = [k for k in body["data"]["keywords"] if k["term"] in ("alla artiklar", "kwconc-control")]
    assert entries, "seeded keywords must be exported"
    for e in entries:
        assert isinstance(e["language_mismatch"], bool)
    boiler = next(e for e in entries if e["term"] == "alla artiklar")
    assert boiler["language_mismatch"] is False
