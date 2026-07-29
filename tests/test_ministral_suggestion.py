"""The one-click Ministral install, and why it is NOT in the verified catalog.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer request 2026-07-29: "automate the ministral installation with a dedicated
button, the version adapted to below 8Gb Vram hardware."

The button ships. The catalog ENTRY deliberately does not, and these tests pin that
distinction, because it is the whole honesty of the feature:

  * ``MODEL_CATALOG`` carries a stated contract — "verified against
    https://ollama.com/library this cycle" — and this cycle already REMOVED two entries
    (gemma4:e4b, translategemma:4b) rather than ship them on faith.
  * ``docs/design/AI_LAYER_STRATEGY_2026-07-29.md`` §2.4 records this tag as
    SEARCH-VERIFIED ONLY and sets an explicit gate: "one page fetch of the model card
    settles it and must happen before any catalog entry." That fetch could not be
    performed (ollama.com and huggingface.co both 403 through this environment's egress
    allowlist), so promoting it would assert a verification nobody performed.

A wrong tag cannot pass silently — Ollama 404s an unknown model — so the failure mode
is loud by construction, which is what makes shipping the button acceptable while the
licence remains unconfirmed.
"""

from __future__ import annotations

import ast
from pathlib import Path

from src.llm.ollama import MINISTRAL_SUGGESTION, MODEL_CATALOG

_OLLAMA_PY = Path(__file__).resolve().parents[1] / "src" / "llm" / "ollama.py"
# The pull endpoint's own validation regex — a suggestion the UI offers with a button
# MUST satisfy it, or the button could only ever 400.
_PULL_RE = r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$"


def test_the_tag_is_the_long_search_verified_form_never_the_short_one():
    """§2.4: the researcher could not verify ``ministral-3:3b`` and correctly refused to
    invent it. The standing project rule is that a model tag is verified or it is not
    used — never a close-looking neighbour."""
    assert MINISTRAL_SUGGESTION["tag"] == "ministral-3:3b-instruct-2512-q4_K_M"
    assert MINISTRAL_SUGGESTION["tag"] != "ministral-3:3b"


def test_the_tag_would_actually_be_pullable():
    import re

    assert re.match(_PULL_RE, MINISTRAL_SUGGESTION["tag"]), (
        "a one-click button whose tag fails the endpoint's own validation is a dead button"
    )


def test_it_is_NOT_in_the_verified_catalog():
    """The load-bearing separation. Merging it into MODEL_CATALOG would launder an
    unverified entry into a list that advertises itself as verified."""
    tags = {m["tag"] for m in MODEL_CATALOG}
    assert MINISTRAL_SUGGESTION["tag"] not in tags
    assert not any("ministral" in t.lower() for t in tags)


def test_the_licence_is_stated_as_reported_never_as_established():
    """Saying plain 'Apache-2.0' would manufacture an assurance: the finding was
    single-sourced, never read from a model card, against a family with a documented
    licence flip (Ministral 8B-2410 shipped research-only)."""
    lic = MINISTRAL_SUGGESTION["license"]
    assert "UNCONFIRMED" in lic
    assert lic != "Apache-2.0", "the bare claim is exactly what must not be made"
    assert MINISTRAL_SUGGESTION["verification"], "the status must travel with the entry"


def test_the_caveats_name_every_known_unknown():
    """Caveats visible by default: a user must be able to read what is NOT known before
    clicking, not after."""
    blob = " ".join(MINISTRAL_SUGGESTION["caveats"]).lower()
    assert "licence" in blob or "license" in blob
    assert "language" in blob, "the ar/zh/ja/ko-only enumeration is a real limitation"
    assert "ollama" in blob, "the version gate is unresolved and must be stated"


def test_it_fits_the_stated_vram_budget():
    """The maintainer asked for the variant suited to sub-8 GB VRAM. ~3.0 GB of weights
    leaves real headroom for context where mistral:7b (~4.4 GB) does not."""
    assert MINISTRAL_SUGGESTION["max_vram_gb"] == 8
    assert MINISTRAL_SUGGESTION["size"] == "~3.0 GB"


def test_the_catalog_contract_comment_still_stands():
    """If someone later deletes the 'verified against ollama.com/library' contract from
    the catalog, the reason this entry is held out disappears with it — so the contract
    itself is pinned."""
    src = _OLLAMA_PY.read_text(encoding="utf-8")
    assert "ollama.com/library this" in src
    assert "rather than shipped on faith" in src


def test_the_catalog_ast_invariant_is_unaffected():
    """The repo invariant parses MODEL_CATALOG via AST. A sibling module-level constant
    must not leak into it (that test asserts over the catalog list only)."""
    tree = ast.parse(_OLLAMA_PY.read_text(encoding="utf-8"))
    found = {}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            found[node.target.id] = node.value
    assert "MODEL_CATALOG" in found and isinstance(found["MODEL_CATALOG"], ast.List)
    assert "MINISTRAL_SUGGESTION" in found and isinstance(found["MINISTRAL_SUGGESTION"], ast.Dict)
