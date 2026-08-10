"""Every constrained-output sweep runs at temperature 0, and says so through ONE constant.

The defect this pins: ``vllm_client`` learned to map ``options`` onto OpenAI sampling
fields so a caller could ask for greedy decoding, and then no production caller ever
asked. Each sweep ran at whatever the server defaults to (1.0 on an OpenAI-compatible
backend), which is why twelve perception-eval passes over one model and one gold set
disagreed about which languages clear the bar.

The assertions drive the REAL functions with a recording client rather than reading the
source, because the thing that matters is what reaches ``generate`` -- a source-level
check would pass against a call site that builds options and drops them.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest

from src.ai_layer.sampling import DEFAULT_TEMPERATURE, TEMPERATURE_ENV, sweep_options


class _Recorder:
    """A client that records every call and answers something parseable."""

    def __init__(self, reply: str = "none"):
        self.calls: list[dict] = []
        self._reply = reply

    def generate(self, prompt, *, model="m", system=None, options=None, keep_alive=None):
        self.calls.append({"options": options, "model": model})
        return type("R", (), {"text": self._reply})()


def _drive_perception(client):
    from src.ai_layer.perception import llm_perception_extract

    llm_perception_extract(client, "Some text.", model="m")


def _drive_triage(client):
    from src.ai_layer.triage import TriageItem, run_triage_batch

    run_triage_batch(client, [TriageItem(term="alpha", article_count=2)], model="m")


def _drive_source_tags(client):
    from src.ai_layer.source_tags import SourceTagItem, run_source_tag_batch

    run_source_tag_batch(
        client,
        [SourceTagItem(domain="a.example", article_count=5, mention_count=9, top_terms=("x",))],
        vocabulary=["news"],
        model="m",
    )


def _drive_langdetect(client):
    from src.ai_layer.langdetect_llm import detect_language_llm

    detect_language_llm(client, "T", "Body text here.", model="m")


def _drive_qualification(client):
    from src.ai_layer.qualification_assist import classify_article_for_qualification

    classify_article_for_qualification(client, "T", "Body text here.", model="m")


def _drive_translate(client):
    from src.ai_layer.translate import translate_keyword

    translate_keyword(client, "election", "en", "fr", model="m")


def _drive_extract(client):
    from src.ai_layer.extract import extract_terms

    extract_terms(client, "T", "Body text here.", model="m")


#: Every path whose reply is parsed against a fixed shape -- an echo-back, a label set,
#: a three-line format, a vocabulary. Prose written for a person is deliberately absent:
#: that decision belongs where the prose lives, not to this constant.
CONSTRAINED_PATHS = [
    pytest.param(_drive_perception, id="perception"),
    pytest.param(_drive_triage, id="triage"),
    pytest.param(_drive_source_tags, id="source_tags"),
    pytest.param(_drive_langdetect, id="langdetect"),
    pytest.param(_drive_qualification, id="qualification_assist"),
    pytest.param(_drive_translate, id="translate"),
    pytest.param(_drive_extract, id="extract"),
]


@pytest.mark.parametrize("drive", CONSTRAINED_PATHS)
def test_every_constrained_sweep_asks_for_greedy_decoding(drive, monkeypatch):
    monkeypatch.delenv(TEMPERATURE_ENV, raising=False)
    client = _Recorder()
    drive(client)
    assert client.calls, "the driver did not reach client.generate at all"
    for call in client.calls:
        assert call["options"] is not None, "sampling options were dropped on the way"
        assert call["options"]["temperature"] == DEFAULT_TEMPERATURE == 0.0


@pytest.mark.parametrize("drive", CONSTRAINED_PATHS)
def test_the_operator_override_actually_reaches_the_call(drive, monkeypatch):
    """A knob nobody can turn is not a knob.

    The counterpart to the test above: the default is greedy, and an operator who wants
    to measure what sampling costs can raise it -- through the same one constant, at
    every call site, without editing code.
    """
    monkeypatch.setenv(TEMPERATURE_ENV, "0.8")
    client = _Recorder()
    drive(client)
    assert client.calls
    assert all(c["options"]["temperature"] == 0.8 for c in client.calls)


def test_a_malformed_override_falls_back_to_greedy_rather_than_to_the_server_default(
    monkeypatch,
):
    """The wrong direction to fail.

    A typo must not silently restore the sampling this module exists to remove, so an
    unparseable or negative value lands on greedy rather than being handed to the
    backend or dropped (which would let the server's 1.0 back in).
    """
    import src.ai_layer.sampling as S

    for bad in ("oops", "", "   ", "-0.5"):
        monkeypatch.setattr(S, "_warned", False)
        monkeypatch.setenv(TEMPERATURE_ENV, bad)
        assert sweep_options()["temperature"] == DEFAULT_TEMPERATURE


def test_both_backends_carry_the_options_through_to_their_own_wire_shape():
    """One constant, two very different request bodies.

    Ollama takes sampling knobs in a nested ``options`` dict; the OpenAI-compatible body
    takes them as top-level fields under its own names. If either mapping stopped
    carrying temperature, every sweep would quietly go back to sampling with nothing in
    the payload to show for it.
    """
    from src.llm.vllm_client import openai_sampling_params

    mapped, dropped = openai_sampling_params(sweep_options())
    assert mapped["temperature"] == 0.0, mapped
    assert "temperature" not in dropped

    # Ollama's own client passes `options` through verbatim; assert the shape it needs
    # rather than re-testing httpx.
    assert set(sweep_options()) <= {"temperature", "top_p", "seed"}
