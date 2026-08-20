"""The catalogue resolves ONE model to the build each backend can use.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

RULED 2026-08-12 (maintainer): Ministral 3 3B throughout the app, drop all others. This
file used to check eight models, their per-backend absences and the drift reporting that
kept a renamed tag from vanishing silently. What survives is the property that still
matters with one model: the two identifiers are DIFFERENT artifacts, both come from the
dated source rather than being re-typed here, and asking for anything else is refused
with a reason that points somewhere useful.
"""

from __future__ import annotations

import pytest

from src.llm.model_catalog import DEFAULT_KEY, catalog_for, identifiers_for


@pytest.mark.parametrize("backend", ["ollama", "vllm"])
def test_the_one_model_resolves_for_either_backend(backend):
    c = catalog_for(backend)
    assert c["backend"] == backend
    assert len(c["models"]) == 1, "one model app-wide; a second row means the ruling drifted"
    m = c["models"][0]
    assert m["key"] == DEFAULT_KEY
    assert m["is_default"] is True
    assert m["available"] is True and m["artifact"]


def test_the_two_backends_get_DIFFERENT_artifacts():
    """The whole reason this module exists. An Ollama image and a Hugging Face repo are
    not interchangeable and neither identifier is derivable from the other, so a
    catalogue that handed both backends the same string would be worse than no
    catalogue: the download would 404 on one of them."""
    oll = catalog_for("ollama")["models"][0]
    vll = catalog_for("vllm")["models"][0]
    assert oll["artifact"] != vll["artifact"]
    # And each row names the OTHER one, so switching backend visibly means a different
    # download rather than the same file again.
    assert oll["other_artifact"] == vll["artifact"]
    assert vll["other_artifact"] == oll["artifact"]


def test_nothing_here_is_re_typed_from_the_dated_source():
    """Both identifiers must be the ones under MINISTRAL_AS_OF, not copies. A copy
    drifts from the registry entry governing it, and the point of that entry is that a
    stale identifier is caught by a freshness test rather than by a failed download."""
    from src.llm.ollama import MINISTRAL_HF, MINISTRAL_SUGGESTION

    assert catalog_for("ollama")["models"][0]["artifact"] == MINISTRAL_SUGGESTION["tag"]
    assert catalog_for("vllm")["models"][0]["artifact"] == MINISTRAL_HF["repo"]


def test_the_catalogue_states_the_date_its_identifiers_were_verified():
    from src.llm.ollama import MINISTRAL_AS_OF

    assert catalog_for("ollama")["as_of"] == MINISTRAL_AS_OF


def test_the_module_does_not_hard_code_either_identifier():
    """A source guard, because the import above would still pass if someone ALSO pasted
    a literal in beside it and the two later diverged."""
    from pathlib import Path

    src = Path("src/llm/model_catalog.py").read_text(encoding="utf-8")
    for literal in ("ministral-3:", "mistralai/"):
        assert literal not in src, f"{literal!r} is re-typed here instead of imported"


def test_no_surface_an_operator_copies_from_re_types_an_identifier():
    """The same rule, applied where it actually costs something.

    The catalogue was clean and three OTHER places were not: two placeholder examples
    in ``app.js`` and the examples inside the vLLM refusals and the request schema. All
    three are read at the exact moment an operator is copying a string, so a drifted
    example teaches the wrong one — and unlike the catalogue's own identifiers, nothing
    would have caught it: the registry's freshness check governs the dated block, not a
    copy of it somewhere else.

    Comment-stripped, because the recorded trap is that a "must be absent" guard trips
    on the comment explaining the absence — and both fixes carry exactly such a comment.
    """
    import re
    from pathlib import Path

    from tests.js_source_helper import app_js, strip_comments

    def _no_comments(text: str, *, python: bool) -> str:
        if python:
            # Whole-line `#` only: a `#` inside a string is not a comment, and the
            # docstrings that QUOTE the historical error message are handled by
            # scoping below rather than by trying to parse them out here.
            return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
        return strip_comments(text)

    js = _no_comments(app_js(), python=False)
    for literal in ("ministral-3:", "mistralai/"):
        assert literal not in js, (
            f"{literal!r} is typed into app.js. The example belongs to /default-model's "
            "`artifact`, which resolves through the dated source."
        )

    # The API module's own docstrings quote a real historical error message verbatim
    # ("Model 'mistralai/…' is not installed. Run: ollama pull …"), which is a RECORD of
    # a bug and must not be reworded — so the scope here is the live code: the request
    # schema and the refusal builder, sliced by `ast` rather than by a guessed anchor.
    import ast

    api = Path("src/api/llm.py").read_text(encoding="utf-8")
    tree = ast.parse(api)
    lines = api.splitlines()
    checked = 0
    for node in ast.walk(tree):
        name = getattr(node, "name", None)
        if name not in ("CustomModelRequest", "_custom_identifier_refusal"):
            continue
        checked += 1
        body = "\n".join(lines[node.lineno - 1 : (node.end_lineno or node.lineno)])
        doc = ast.get_docstring(node) or ""
        body = body.replace(doc, "") if doc else body
        body = _no_comments(body, python=True)
        for literal in ("ministral-3:", "mistralai/"):
            assert literal not in body, (
                f"{literal!r} is re-typed in {name}; read it from MINISTRAL_SUGGESTION "
                "/ MINISTRAL_HF so the registry's dated check governs it"
            )
    assert checked == 2, f"expected to slice both surfaces, sliced {checked}"

    # And the positive half: the live code must actually REACH the dated source, or the
    # absence above is satisfied by a surface that shows no example at all.
    assert re.search(r"MINISTRAL_SUGGESTION\['tag'\]", api)
    assert re.search(r"MINISTRAL_HF\['repo'\]", api)


def test_an_unknown_backend_falls_back_to_ollama_rather_than_raising():
    """The UI passes whatever the server told it; an unexpected string should degrade to
    the CPU-capable backend, never blow up a settings panel."""
    assert catalog_for("something-else")["backend"] == "ollama"


def test_identifiers_for_resolves_the_shipped_key():
    ok, refused = identifiers_for("ollama", [DEFAULT_KEY])
    assert refused == []
    assert ok[0]["identifier"] == catalog_for("ollama")["models"][0]["artifact"]


def test_asking_for_anything_else_is_refused_with_somewhere_to_go():
    """A refusal that just says no is a dead end. With one model, "not in the catalogue"
    now means "that is not the model this app ships" — and the honest next step is the
    custom-model field, so the reason says so."""
    ok, refused = identifiers_for("vllm", ["qwen35-0-8b"])
    assert ok == []
    assert len(refused) == 1
    assert "custom model field" in refused[0]["reason"]


def test_the_method_string_points_at_the_custom_field_too():
    """The panel renders this verbatim, so it is where a reader learns the app is not
    hiding a longer list from them."""
    assert "custom model field" in catalog_for("ollama")["method"]
