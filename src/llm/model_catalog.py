"""The ONE model this app ships, resolved to the build each backend can use.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

RULED 2026-08-12 (maintainer): *"record the decision to use mistral's 3b model
throughout the entire app. Drop all others. Keep in the UI the option for users to use
their own models (as a buried advanced settings option)."*

So this module no longer offers a LIST. It resolves ONE logical model — Ministral 3 3B
— to the artifact the active backend can actually download, which is the job the eight-
model catalogue was doing for the default row anyway. The other seven rows, the bench
roster they were compared with, and the comparative bench itself all went with the same
ruling; what survives is the part an operator actually presses.

ONE LOGICAL MODEL, TWO ARTIFACTS, and that is why this module still exists at all.
"Ministral 3B" is a ``q4_K_M`` image on Ollama and a safetensors repo on Hugging Face.
They are not interchangeable, neither identifier is derivable from the other, and their
quantisation vocabularies do not translate — so pressing one button and getting whichever
one your backend can use is a real resolution step, not a lookup.

**NOTHING HERE IS RE-TYPED.** Both identifiers are IMPORTED from :mod:`src.llm.ollama`,
where they sit under the dated ``MINISTRAL_AS_OF`` pin that :mod:`src.maintenance.registry`
governs. Re-typing one would create a second source of truth that drifts from the dated
entry, and the whole point of that entry is that a stale identifier is caught by a
freshness test rather than by a user's failed download.

THE CUSTOM-MODEL FIELD IS THE OTHER HALF of the same ruling and deliberately does NOT
come through here: an operator naming their own tag or repo is not choosing from a
catalogue, and passing them through a resolver that knows one model would only be able to
refuse them. That path validates and pulls what it is given
(:func:`src.api.llm.pull_any_model`), which is what "use your own model" has to mean.
"""

from __future__ import annotations

from typing import Any

#: The model the one-click setup downloads, and the only key this catalogue resolves.
#: The 3B rather than the 8B: it is the one that fits an 8 GB card in either backend's
#: build, which is the machine class the hardware gate admits.
DEFAULT_KEY = "ministral-3-3b-instruct-2512"


def _entry() -> dict:
    """The single catalogue row, assembled from the dated identifiers.

    Built per call rather than at import time so a test that patches a source sees the
    patched value.
    """
    from src.llm.ollama import (
        MINISTRAL_HF,
        MINISTRAL_SUGGESTION,
    )

    return {
        "key": DEFAULT_KEY,
        "label": "Ministral 3 · 3B Instruct",
        "summary": "The model this app runs on. Fits an 8 GB card on either backend.",
        "licence": MINISTRAL_SUGGESTION.get("license"),
        "ollama": {
            "artifact": MINISTRAL_SUGGESTION["tag"],
            "size": MINISTRAL_SUGGESTION.get("size"),
            "verification": "fetched",
        },
        "vllm": {
            "artifact": MINISTRAL_HF["repo"],
            "size": MINISTRAL_HF.get("size"),
            "verification": MINISTRAL_HF.get("verification"),
            "gated": MINISTRAL_HF.get("gated"),
        },
        "caveats": list(MINISTRAL_SUGGESTION.get("caveats") or []),
    }


def catalog_for(backend: str) -> dict:
    """The model resolved for ONE backend.

    ``artifact`` is the thing that would actually be downloaded. It is never None here —
    both builds of this model are verified — but the field and its ``absent_reason``
    companion are kept because the caller's contract is unchanged and a future model
    added without a build for one backend must be able to say so rather than 404.
    """
    backend = "vllm" if str(backend).strip().lower() == "vllm" else "ollama"
    from src.llm.ollama import MINISTRAL_AS_OF

    e = _entry()
    side = e.get(backend) or {}
    models = [
        {
            "key": e["key"],
            "label": e["label"],
            "summary": e.get("summary"),
            "licence": e.get("licence"),
            "caveats": e.get("caveats") or [],
            "is_default": True,
            "artifact": side.get("artifact"),
            "size": side.get("size"),
            "verification": side.get("verification"),
            "gated": side.get("gated"),
            "absent_reason": side.get("absent_reason"),
            "available": bool(side.get("artifact")),
            # The identifier the OTHER backend would use. Kept so a reader can see that
            # switching backend means a different download, not the same file again.
            "other_artifact": (
                (e.get("vllm") if backend == "ollama" else e.get("ollama")) or {}
            ).get("artifact"),
        }
    ]
    return {
        "backend": backend,
        "default_key": DEFAULT_KEY,
        "models": models,
        "as_of": MINISTRAL_AS_OF,
        "method": (
            "This app runs on one model, downloaded as the build your backend can "
            "actually use — an Ollama image or a Hugging Face repo. Both identifiers "
            "are the ones verified in this app's dated catalogue, never guessed. To "
            "run something else, use the custom model field in the advanced section."
        ),
    }


def identifiers_for(backend: str, keys: list[str]) -> tuple[list[dict], list[dict]]:
    """Resolve ``keys`` to downloadable artifacts for ``backend``.

    Returns ``(ok, refused)``, because refusals must travel WITH the result: an operator
    who asked for something this catalogue does not carry is owed an account of it, not
    a silent no-op. With one model, a refusal now also means "that is not the model this
    app ships" — which points at the custom-model field rather than at a dead end.
    """
    resolved = {m["key"]: m for m in catalog_for(backend)["models"]}
    ok: list[dict] = []
    refused: list[dict] = []
    for key in keys or []:
        entry: dict[str, Any] | None = resolved.get(str(key))
        if entry is None:
            refused.append(
                {
                    "key": key,
                    "reason": (
                        "not the model this app ships — use the custom model field to "
                        "run something else"
                    ),
                }
            )
            continue
        if not entry["available"]:
            refused.append(
                {
                    "key": key,
                    "label": entry["label"],
                    "reason": entry.get("absent_reason") or "no verified build for this backend",
                }
            )
            continue
        ok.append({"key": key, "label": entry["label"], "identifier": entry["artifact"]})
    return ok, refused
