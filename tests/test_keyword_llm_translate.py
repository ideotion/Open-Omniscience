"""TENTATIVE LLM keyword translation (Phase 4 of the language-aware keyword work):
the fallback for keywords no VERIFIED ring covers. Pure + stub client, no network.

Doctrine checks: a verified ring translation ALWAYS wins (the LLM is skipped), the
output is cleaned to a single short term, refusals/echoes yield nothing, and the
cache avoids re-asking the model.
"""

from __future__ import annotations

from src.ai_layer import translate as tr


class StubClient:
    """A fake Ollama client: returns mapping[term] as the generated text (echoes the
    term when absent), records calls, optionally raises (a mid-batch outage)."""

    def __init__(self, mapping=None, fail=False):
        self.mapping = {k.casefold(): v for k, v in (mapping or {}).items()}
        self.calls = []
        self.fail = fail

    def generate(self, prompt, *, model, system=None, keep_alive=None):
        self.calls.append(prompt)
        if self.fail:
            raise RuntimeError("ollama down")
        return type("R", (), {"text": self.mapping.get(prompt.strip().casefold(), prompt)})()


def test_parse_translation_cleans_and_rejects():
    assert tr.parse_translation("élection") == "élection"
    assert tr.parse_translation('  "election"  ') == "election"
    assert tr.parse_translation("Translation: élection") == "élection"
    assert tr.parse_translation("- élection") == "élection"
    # multi-line: first usable line wins
    assert tr.parse_translation("élection\n(or vote)") == "élection"
    # rejects empties, sentences, and refusals
    assert tr.parse_translation("") is None
    assert tr.parse_translation("   ") is None
    assert tr.parse_translation("x" * 80) is None  # too long -> a sentence, not a keyword
    assert tr.parse_translation("As an AI, I cannot translate this.") is None
    assert tr.parse_translation("There is no direct translation") is None


def test_translate_keyword_returns_clean_term_or_none():
    c = StubClient({"réforme": "reform"})
    assert tr.translate_keyword(c, "réforme", "fr", "en", model="m") == "reform"
    # same source/target -> no-op (no model call needed)
    assert tr.translate_keyword(c, "reform", "en", "en", model="m") is None
    # echo (model returned the source unchanged) -> nothing added
    assert tr.translate_keyword(c, "budget", "fr", "en", model="m") is None


def test_translate_keywords_skips_verified_ring_and_caches():
    tr.clear_cache()
    c = StubClient({"réforme": "reform"})
    items = [
        {"term": "élection", "language": "fr"},   # VERIFIED via the election ring -> skip the LLM
        {"term": "réforme", "language": "fr"},     # no ring -> tentative LLM translation
        {"term": "budget", "language": "en"},      # same language as target -> skip
    ]
    out = tr.translate_keywords(c, items, "en", model="m")
    assert out == {"réforme": "reform"}
    # the verified ring term never reached the model
    assert all("élection" not in call for call in c.calls)
    # second run is served from the cache (no new model call)
    n = len(c.calls)
    out2 = tr.translate_keywords(c, items, "en", model="m")
    assert out2 == {"réforme": "reform"} and len(c.calls) == n


def test_translate_keywords_survives_a_mid_batch_outage():
    tr.clear_cache()
    c = StubClient(fail=True)  # ollama down -> every call raises
    out = tr.translate_keywords(c, [{"term": "réforme", "language": "fr"}], "en", model="m")
    assert out == {}  # no fabricated translations; the batch just returns what it has


class EndpointStub:
    def __init__(self, available=True, mapping=None):
        self._avail = available
        self.mapping = {k.casefold(): v for k, v in (mapping or {}).items()}
        self.calls = []

    def is_available(self):
        return self._avail

    def generate(self, prompt, *, model, system=None, keep_alive=None):
        self.calls.append(prompt)
        return type("R", (), {"text": self.mapping.get(prompt.strip().casefold(), prompt)})()


def test_translate_keywords_endpoint_gates_on_availability():
    from src.api.ai import AiTranslateItem, AiTranslateRequest, translate_keywords_ep

    tr.clear_cache()
    req = AiTranslateRequest(target_lang="en", terms=[
        AiTranslateItem(term="élection", language="fr"),   # verified ring -> skipped
        AiTranslateItem(term="réforme", language="fr"),     # no ring -> tentative LLM
    ])
    # Offline / airplane: no model call, available=False, no fabricated translations.
    off = EndpointStub(available=False)
    r = translate_keywords_ep(req, client=off)
    assert r["available"] is False and r["translations"] == {} and off.calls == []
    # Online: a tentative translation for the non-ring term only; the ring term is skipped.
    on = EndpointStub(available=True, mapping={"réforme": "reform"})
    r2 = translate_keywords_ep(req, client=on)
    assert r2["available"] is True and r2["translations"] == {"réforme": "reform"}
    assert r2["source"] == "llm-tentative" and r2.get("caveat")
    assert all("élection" not in c for c in on.calls)
