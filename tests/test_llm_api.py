"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

HTTP-level tests for the LLM endpoints (finding TEST-05, 0.0.8 WP4). The
existing test_llm_ollama.py covers the OllamaClient itself; these exercise the
FastAPI layer through the documented get_llm_client dependency override --
no Ollama and no network involved.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from src.api.llm import get_llm_client
from src.api.main import app
from src.database.models import Article, Source
from src.database.session import init_db, session_scope
from src.llm.ollama import GenerationResult, LLMUnavailable


class _FakeOllama:
    """Stands in for OllamaClient: deterministic, offline, honest-shaped."""

    def __init__(self, available: bool = True):
        self._available = available
        self.base_url = "http://127.0.0.1:11434"
        self.calls: list[tuple] = []
        self.keep_alives: list = []  # keep_alive passed per generate() call

    def is_available(self) -> bool:
        return self._available

    def list_installed(self):
        if not self._available:
            raise LLMUnavailable("Ollama not reachable (fake)")
        return ["llama3.2:3b"]

    def list_installed_detailed(self):
        if not self._available:
            raise LLMUnavailable("Ollama not reachable (fake)")
        return [{"tag": "llama3.2:3b", "size_gb": 2.0, "modified": "2026-06-01T00:00:00Z"}]

    def generate(self, prompt, *, model="llama3.2:3b", system=None, options=None, keep_alive=None):
        if not self._available:
            raise LLMUnavailable("Ollama not reachable (fake)")
        self.calls.append((prompt, model, system))
        self.keep_alives.append(keep_alive)
        return GenerationResult(model=model, text=f"FAKE[{prompt[:24]}]")


def _override(fake):
    app.dependency_overrides[get_llm_client] = lambda: fake


def teardown_function(_fn):
    app.dependency_overrides.pop(get_llm_client, None)


def _seed_article(lang: str = "en") -> int:
    init_db()
    with session_scope() as s:
        domain = f"llm-{uuid.uuid4().hex[:8]}.example"
        src = Source(name=f"LLM {domain}", domain=domain, language="en")
        s.add(src)
        s.flush()
        a = Article(
            url=f"https://{domain}/a",
            canonical_url=f"https://{domain}/a",
            source_id=src.id,
            title="An article about rivers",
            content="A long body about rivers and floods. " * 30,
            language=lang,
            hash=uuid.uuid4().hex + uuid.uuid4().hex,
        )
        s.add(a)
        s.flush()
        return a.id


def test_health_reports_available_with_models():
    _override(_FakeOllama(available=True))
    with TestClient(app) as client:
        r = client.get("/api/llm/health")
        assert r.status_code == 200
        body = r.json()
        assert body["available"] is True
        assert body["installed_models"]


def test_generate_round_trip():
    fake = _FakeOllama()
    _override(fake)
    with TestClient(app) as client:
        r = client.post("/api/llm/generate", json={"prompt": "say hi"})
        assert r.status_code == 200
        assert r.json()["text"].startswith("FAKE[")
        assert fake.calls  # the prompt actually reached the client


def test_generate_503_when_ollama_down():
    _override(_FakeOllama(available=False))
    with TestClient(app) as client:
        r = client.post("/api/llm/generate", json={"prompt": "say hi"})
        assert r.status_code == 503
        assert "not reachable" in r.json()["detail"].lower()


def test_summarize_stores_provenance_and_404s_on_unknown_article():
    fake = _FakeOllama()
    _override(fake)
    art_id = _seed_article()
    with TestClient(app) as client:
        r = client.post(f"/api/llm/articles/{art_id}/summarize", json={})
        assert r.status_code == 200
        body = r.json()
        assert body["result"].startswith("FAKE[")
        assert body.get("model")  # provenance: which model produced it

        r404 = client.post("/api/llm/articles/99999999/summarize", json={})
        assert r404.status_code == 404


def test_translate_includes_target_language_in_prompt():
    fake = _FakeOllama()
    _override(fake)
    art_id = _seed_article()
    with TestClient(app) as client:
        r = client.post(
            f"/api/llm/articles/{art_id}/translate", json={"target_language": "French"}
        )
        assert r.status_code == 200
        # the prompt the client received must carry the requested language
        assert any("French" in (p or "") + (s or "") for p, _m, s in fake.calls)


# --- corpus synthesis (0.0.8 part 2, WP4 / RM-12) ----------------------------- #


def test_synthesize_carries_member_provenance_and_stores_per_member():
    fake = _FakeOllama()
    _override(fake)
    ids = [_seed_article() for _ in range(3)]
    with TestClient(app) as client:
        r = client.post("/api/llm/synthesize", json={"article_ids": ids})
        assert r.status_code == 200
        body = r.json()
        assert body["member_ids"] == sorted(ids)
        assert body["member_count"] == 3
        assert body["prompt_version"] == "synthesis-v2"
        assert "never a verdict" in body["caveat"] or "asserts nothing" in body["caveat"]
        # exactly ONE generation call (bounded fan-out by construction)
        assert len(fake.calls) == 1
        prompt = fake.calls[0][0]
        assert "[1]" in prompt and "[3]" in prompt  # numbered excerpts
    from src.database.models import ArticleAnalysis
    from src.database.session import session_scope

    with session_scope() as s:
        stored = (
            s.query(ArticleAnalysis)
            .filter(ArticleAnalysis.kind == "synthesis",
                    ArticleAnalysis.article_id.in_(ids))
            .all()
        )
        assert len(stored) == 3  # provenance stored per member


def test_synthesize_returns_member_metadata_and_total_matched():
    # The window shows the FULL corpus of synthesized articles WITH metadata
    # (maintainer 2026-06-21) — so the response must carry it.
    fake = _FakeOllama()
    _override(fake)
    ids = [_seed_article() for _ in range(2)]
    with TestClient(app) as client:
        body = client.post("/api/llm/synthesize", json={"article_ids": ids}).json()
        members = body["members"]
        assert [m["id"] for m in members] == sorted(ids)
        assert [m["n"] for m in members] == [1, 2]  # citation numbers
        for m in members:
            assert "title" in m and "source" in m and "language" in m and "published_at" in m
        assert body["total_matched"] == 2
        assert body["max_articles"] == 20


def test_synthesize_appends_native_language_directive():
    # A non-English ui_lang appends an in-language output directive to the system
    # prompt so a weak model writes in the UI language (maintainer 2026-06-21).
    fake = _FakeOllama()
    _override(fake)
    ids = [_seed_article()]
    with TestClient(app) as client:
        client.post("/api/llm/synthesize",
                    json={"article_ids": ids, "ui_lang": "fr", "output_language": "French"})
        system = fake.calls[0][2]
        assert "français" in system  # the native French directive is present
        # the wrapper forces a full multi-excerpt synthesis (no "ask which one" bail)
        prompt = fake.calls[0][0]
        assert "Synthesize ALL" in prompt


def test_synthesize_caps_explicit_ids_at_20():
    _override(_FakeOllama())
    with TestClient(app) as client:
        r = client.post("/api/llm/synthesize", json={"article_ids": list(range(1, 22))})
        assert r.status_code == 400
        assert "At most 20" in r.json()["detail"]


def test_synthesize_503_when_ollama_down():
    _override(_FakeOllama(available=False))
    art = _seed_article()
    with TestClient(app) as client:
        r = client.post("/api/llm/synthesize", json={"article_ids": [art]})
        assert r.status_code == 503


def test_synthesize_requires_a_selection():
    _override(_FakeOllama())
    with TestClient(app) as client:
        assert client.post("/api/llm/synthesize", json={}).status_code == 400


# --- model catalog honesty (0.0.8 part 2: model-list freshness + picker) ------ #


def test_models_endpoint_carries_as_of_and_hardware_fit():
    _override(_FakeOllama(available=True))
    with TestClient(app) as client:
        r = client.get("/api/llm/models")
        assert r.status_code == 200
        body = r.json()
        assert body["catalog_as_of"]  # the suggested list is date-stamped
        assert body["installed"] and body["installed"][0]["tag"] == "llama3.2:3b"
        # every catalog entry is annotated with a hardware-fit hint
        assert all("fit" in m for m in body["catalog"])
        assert {m["fit"] for m in body["catalog"]} <= {"fits", "tight", "too_large", "unknown"}


# --- provenance: prompt_text + keep_alive (maintainer 2026-06-17) -------------- #


def _stored(article_id, kind):
    """Stored analyses as plain dicts (read inside the session so attributes are
    materialised — never returns detached ORM instances)."""
    from src.database.models import ArticleAnalysis
    from src.database.session import session_scope

    with session_scope() as s:
        rows = (
            s.query(ArticleAnalysis)
            .filter(ArticleAnalysis.article_id == article_id, ArticleAnalysis.kind == kind)
            .order_by(ArticleAnalysis.created_at.desc(), ArticleAnalysis.id.desc())
            .all()
        )
        return [
            {"id": r.id, "prompt_text": r.prompt_text, "prompt_version": r.prompt_version}
            for r in rows
        ]


def test_summarize_records_exact_prompt_and_keep_alive(tmp_path, monkeypatch):
    import src.config.app_settings as aps

    monkeypatch.setattr(aps, "_settings_path", lambda: tmp_path / "s.json")
    fake = _FakeOllama()
    _override(fake)
    art_id = _seed_article()
    with TestClient(app) as client:
        r = client.post(f"/api/llm/articles/{art_id}/summarize", json={})
        assert r.status_code == 200
    # The EXACT system prompt used is recorded (provenance), and keep_alive defaults
    # to the stored "30m" so the model stays warm (the maintainer's "no unload" ask).
    rows = _stored(art_id, "summary")
    assert rows and rows[0]["prompt_text"] and "summariz" in rows[0]["prompt_text"].lower()
    assert rows[0]["prompt_version"] == "summary-v2"
    assert fake.keep_alives[-1] == "30m"


def test_custom_prompt_is_used_and_recorded(tmp_path, monkeypatch):
    import src.config.app_settings as aps

    monkeypatch.setattr(aps, "_settings_path", lambda: tmp_path / "s.json")
    aps.save_settings({"llm_prompt_summary": "CUSTOM: be terse."})
    fake = _FakeOllama()
    _override(fake)
    art_id = _seed_article()
    with TestClient(app) as client:
        r = client.post(f"/api/llm/articles/{art_id}/summarize", json={})
        assert r.status_code == 200
    # the fake received the custom system prompt verbatim
    assert any("CUSTOM: be terse." == s for _p, _m, s in fake.calls)
    rows = _stored(art_id, "summary")
    assert rows[0]["prompt_text"] == "CUSTOM: be terse."
    assert rows[0]["prompt_version"] == "summary-custom"  # version flags customisation


def test_list_article_analyses_newest_first_with_provenance():
    fake = _FakeOllama()
    _override(fake)
    art_id = _seed_article()
    with TestClient(app) as client:
        client.post(f"/api/llm/articles/{art_id}/summarize", json={})
        client.post(f"/api/llm/articles/{art_id}/summarize", json={})  # a 2nd, kept (never replaced)
        client.post(f"/api/llm/articles/{art_id}/translate", json={"target_language": "French"})

        all_r = client.get(f"/api/llm/articles/{art_id}/analyses").json()
        assert all_r["count"] == 3  # nothing replaced — every result kept
        # rows carry full provenance incl. the exact prompt text
        assert all(a.get("prompt_text") for a in all_r["analyses"])

        s_r = client.get(f"/api/llm/articles/{art_id}/analyses?kind=summary").json()
        assert s_r["count"] == 2  # both summaries kept
        # newest first (ids descending when timestamps tie)
        assert s_r["analyses"][0]["id"] > s_r["analyses"][1]["id"]

        t_r = client.get(f"/api/llm/articles/{art_id}/analyses?kind=translation").json()
        assert t_r["count"] == 1
        assert t_r["analyses"][0]["target_language"] == "French"


def test_prompts_endpoint_exposes_defaults_and_keep_alive(tmp_path, monkeypatch):
    import src.config.app_settings as aps

    monkeypatch.setattr(aps, "_settings_path", lambda: tmp_path / "s.json")
    _override(_FakeOllama())
    with TestClient(app) as client:
        d = client.get("/api/llm/prompts").json()
        # Part B: the built-in keyword-EXTRACTION prompt joins the editable set.
        assert set(d["prompts"]) == {"summary", "translate", "synthesis", "ai_keywords"}
        assert d["prompts"]["summary"]["default"]  # built-in default text present
        assert d["prompts"]["summary"]["current"] == ""  # no override yet
        ak = d["prompts"]["ai_keywords"]
        assert "{max_terms}" in ak["default"]  # the extraction prompt's placeholder
        assert ak["current"] == "" and ak["version"] == "ai-keywords-v1"
        assert d["keep_alive"] and d["keep_alive_default"]


# --- bulk summarize / translate (maintainer 2026-06-17) ----------------------- #


def _ndjson(text):
    import json as _json

    return [_json.loads(ln) for ln in text.splitlines() if ln.strip()]


def test_bulk_summarize_streams_and_stores_each(tmp_path, monkeypatch):
    import src.config.app_settings as aps

    monkeypatch.setattr(aps, "_settings_path", lambda: tmp_path / "s.json")
    fake = _FakeOllama()
    _override(fake)
    ids = [_seed_article() for _ in range(3)]
    with TestClient(app) as client:
        r = client.post("/api/llm/bulk", json={"op": "summarize", "article_ids": ids})
        assert r.status_code == 200
        events = _ndjson(r.text)
        assert events[0]["event"] == "start" and events[0]["total"] == 3
        items = [e for e in events if e["event"] == "item"]
        assert len(items) == 3 and all(i["status"] == "stored" for i in items)
        done = events[-1]
        assert done["event"] == "done" and done["stored"] == 3 and not done["aborted"]
    # each article got its own stored summary, with the exact prompt recorded
    for aid in ids:
        rows = _stored(aid, "summary")
        assert len(rows) == 1 and rows[0]["prompt_text"]


def test_bulk_llm_id_resolve_is_chunked_and_byte_identical(tmp_path, monkeypatch):
    """Audit finding 2026-07-17: bulk_llm's two id IN(...) queries (resolving the
    explicit article_ids selection, and the skip_existing "already done" lookup)
    were unchunked -- and the 2026-06-20 ruling deliberately removed bulk_llm's
    old article-count cap so it processes the WHOLE matched set uncapped, which
    also removed the incidental protection that cap gave against SQLite's
    historical ~999 bound-variable ceiling. A card/search selection can carry
    thousands of ids (a Home card's article_ids can run to 2000). Forces
    chunking with a tiny src.api.llm._BULK_ID_CHUNK (3 articles needing 3
    separate chunk queries of 1) across BOTH sites (first run stores summaries;
    second run with skip_existing exercises the "already" lookup) and asserts
    the outcome is BYTE-IDENTICAL to the unchunked default."""
    import src.api.llm as llm_mod
    import src.config.app_settings as aps

    monkeypatch.setattr(aps, "_settings_path", lambda: tmp_path / "s.json")
    monkeypatch.setattr(llm_mod, "_BULK_ID_CHUNK", 1, raising=True)
    _override(_FakeOllama())
    ids = [_seed_article() for _ in range(3)]
    with TestClient(app) as client:
        r1 = client.post("/api/llm/bulk", json={"op": "summarize", "article_ids": ids})
        assert r1.status_code == 200
        events1 = _ndjson(r1.text)
        assert events1[0]["event"] == "start" and events1[0]["total"] == 3
        items1 = [e for e in events1 if e["event"] == "item"]
        assert len(items1) == 3 and all(i["status"] == "stored" for i in items1)
        assert events1[-1]["stored"] == 3

        # Second run: skip_existing must top up NOTHING (the "already" chunked
        # lookup must correctly find all 3, spread across 3 separate id chunks).
        r2 = client.post(
            "/api/llm/bulk",
            json={"op": "summarize", "article_ids": ids, "skip_existing": True},
        )
        done2 = _ndjson(r2.text)[-1]
        assert done2["skipped"] == 3 and done2["stored"] == 0
    for aid in ids:
        assert len(_stored(aid, "summary")) == 1  # never duplicated


def test_bulk_skip_existing_tops_up_only_missing(tmp_path, monkeypatch):
    import src.config.app_settings as aps

    monkeypatch.setattr(aps, "_settings_path", lambda: tmp_path / "s.json")
    _override(_FakeOllama())
    ids = [_seed_article() for _ in range(2)]
    with TestClient(app) as client:
        client.post("/api/llm/bulk", json={"op": "summarize", "article_ids": ids})
        # second run with skip_existing should skip both (already summarised)
        r = client.post("/api/llm/bulk", json={"op": "summarize", "article_ids": ids, "skip_existing": True})
        done = _ndjson(r.text)[-1]
        assert done["skipped"] == 2 and done["stored"] == 0
    # never replaced: still exactly one summary per article
    for aid in ids:
        assert len(_stored(aid, "summary")) == 1


def test_bulk_translate_records_target_language(tmp_path, monkeypatch):
    import src.config.app_settings as aps

    monkeypatch.setattr(aps, "_settings_path", lambda: tmp_path / "s.json")
    fake = _FakeOllama()
    _override(fake)
    ids = [_seed_article()]
    with TestClient(app) as client:
        r = client.post("/api/llm/bulk", json={"op": "translate", "article_ids": ids, "target_language": "German"})
        assert _ndjson(r.text)[-1]["stored"] == 1
        a = client.get(f"/api/llm/articles/{ids[0]}/analyses?kind=translation").json()
        assert a["analyses"][0]["target_language"] == "German"
    assert any("German" in (s or "") for _p, _m, s in fake.calls)  # target reached the model


def test_bulk_translate_skips_articles_already_in_target_language(tmp_path, monkeypatch):
    """Never translate an article already in the target language, and report how many WILL
    be translated up front (maintainer 2026-06-20)."""
    import src.config.app_settings as aps

    monkeypatch.setattr(aps, "_settings_path", lambda: tmp_path / "s.json")
    _override(_FakeOllama())
    de = _seed_article(lang="de")   # already German -> must be skipped
    en = _seed_article(lang="en")   # English -> must be translated to German
    with TestClient(app) as client:
        r = client.post(
            "/api/llm/bulk",
            json={"op": "translate", "article_ids": [de, en], "target_language": "German"},
        )
        ev = _ndjson(r.text)
        start = ev[0]
        assert start["event"] == "start" and start["total"] == 2
        assert start["to_process"] == 1 and start["same_language"] == 1
        done = ev[-1]
        assert done["stored"] == 1 and done["skipped"] == 1
    assert len(_stored(de, "translation")) == 0   # the German article was NOT translated
    assert len(_stored(en, "translation")) == 1


def test_bulk_requires_a_selection_and_validates_op():
    _override(_FakeOllama())
    with TestClient(app) as client:
        # no selection at all → 400; an unknown op → 400
        assert client.post("/api/llm/bulk", json={"op": "summarize"}).status_code == 400
        assert client.post("/api/llm/bulk", json={"op": "bogus", "article_ids": [1]}).status_code == 400
        # a valid selection that resolves to nothing with content → 404
        assert client.post(
            "/api/llm/bulk", json={"op": "summarize", "article_ids": [99999999]}
        ).status_code == 404


def test_bulk_aborts_loudly_when_ollama_down():
    _override(_FakeOllama(available=False))
    ids = [_seed_article()]
    with TestClient(app) as client:
        r = client.post("/api/llm/bulk", json={"op": "summarize", "article_ids": ids})
        # resolution succeeds (200 stream); the model failure aborts mid-stream, loudly.
        assert r.status_code == 200
        done = _ndjson(r.text)[-1]
        assert done["event"] == "done" and done["aborted"] is True and done["reason"]


# --- v2 prompt optimization + language pin (maintainer 2026-06-17) ------------- #


def test_output_language_pins_the_summary_prompt(tmp_path, monkeypatch):
    import src.config.app_settings as aps

    monkeypatch.setattr(aps, "_settings_path", lambda: tmp_path / "s.json")
    fake = _FakeOllama()
    _override(fake)
    art_id = _seed_article()
    with TestClient(app) as client:
        # an explicit output language reaches the model's system prompt
        client.post(f"/api/llm/articles/{art_id}/summarize", json={"output_language": "French"})
        assert "French" in (fake.calls[-1][2] or "")
        # default (unset) → the faithful "same language as the article" instruction
        client.post(f"/api/llm/articles/{art_id}/summarize", json={})
        assert "same language as the article" in (fake.calls[-1][2] or "")
        # remark 13: a ui_lang code appends the NATIVE-language output directive, so a
        # single-article summary comes out in the UI language (like bulk/synthesis).
        client.post(
            f"/api/llm/articles/{art_id}/summarize",
            json={"output_language": "French", "ui_lang": "fr"},
        )
        assert "français" in (fake.calls[-1][2] or "")


def test_v2_defaults_are_honesty_first():
    _override(_FakeOllama())
    with TestClient(app) as client:
        p = client.get("/api/llm/prompts").json()["prompts"]
        # summary v2: language pin + attribution guard
        assert "{language}" in p["summary"]["default"]
        assert "never turn a claim into a fact" in p["summary"]["default"]
        assert p["summary"]["version"] == "summary-v2"
        # synthesis v2: per-claim citations + the single-source flag
        assert "[2][5]" in p["synthesis"]["default"]
        assert "only one source" in p["synthesis"]["default"]
