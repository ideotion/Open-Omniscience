"""The models the AI tab offers, as ONE list that works for either backend.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer, 2026-08-04: "a list of dual use buttons for additional models
(Ministral, Granite, Qwen3.5-0.8B, Gemma-3n-E2B-IT, Phi-4-mini-instruct,
LFM2.5-1.2B, etc.) also simplifying the download of local models (also dynamically
choosing the proper version for either ollama or vLLM). Let's remove the list of
suggested models."

ONE LOGICAL MODEL, TWO ARTIFACTS. "Ministral 3B" is a q4_K_M image on Ollama and a
safetensors repo on Hugging Face; they are not interchangeable and their
quantisation vocabularies do not translate. The operator should press one button
and get whichever one their backend can actually use -- which is what this resolves.

**NOT A NEW LIST OF IDENTIFIERS.** Every tag and repo id here is IMPORTED from where
it was verified, never re-typed:

  * ``bench_roster.BENCH_ROSTER`` -- dual identifiers, per-row ``verification``
    ("fetched" | "search-verified"), dated ``BENCH_ROSTER_AS_OF``;
  * ``ollama.MINISTRAL_SUGGESTION`` -- the default, dual;
  * ``ollama.MODEL_CATALOG`` -- Ollama tags read from ollama.com/library,
    dated ``CATALOG_AS_OF``.

Re-typing one would create a second source of truth that drifts from the dated
registry entry governing it, and the whole point of those entries is that a stale
identifier is caught by a freshness test rather than by a user's failed download.
It also means this module introduces no ``*_AS_OF`` constant of its own and owes no
registry entry: it has no facts, only an arrangement of other modules' facts.

A MISSING BUILD IS STATED, NEVER INVENTED. Granite has verified Ollama tags and no
recorded Hugging Face repo; LFM2.5-1.2B-Instruct has a repo and no Ollama tag. The
tempting move is to guess the obvious-looking name -- ``ibm-granite/granite-4.1-3b``
reads perfectly plausible -- and that is exactly the fabrication the roster's own
verification field exists to prevent. An entry with no artifact for the active
backend comes back with ``artifact: None`` and a reason, so the button is disabled
with an explanation instead of queueing a download that 404s.

THE BENCH ROSTER OUTLIVES THE BENCH. The comparison UI is scheduled for removal once
it has been exercised on both backends (maintainer, same message); these identifiers
are not, because they are what the download buttons resolve against. That is why the
catalog reads the roster rather than the other way round.
"""

from __future__ import annotations

from typing import Any

#: Display order. The setup default leads; the rest are the maintainer's list.
#: A key that resolves to no artifact for the active backend still appears -- with
#: its absence explained -- because silently dropping it would make the catalog
#: look different on different machines for no visible reason.
CATALOG_ORDER: tuple[str, ...] = (
    "ministral-3-3b-instruct-2512",
    "ministral-3-8b-instruct-2512",
    "granite-4-1-3b",
    "granite-4-1-8b",
    "qwen35-0-8b",
    "gemma-3n-e2b-it",
    "phi-4-mini-instruct",
    "lfm25-1-2b-instruct",
)

#: The model the one-click setup downloads. The 3B rather than the 8B: it is the one
#: that fits an 8 GB card in either backend's build, which is the machine class the
#: hardware gate admits.
DEFAULT_KEY = "ministral-3-3b-instruct-2512"


def _from_suggestions(tag: str) -> dict:
    """The catalogue row for an Ollama tag, read from the dated suggestion list.

    THE TAG IS THE JOIN KEY, because ``MODEL_CATALOG`` rows have no other identity --
    which means a rename upstream (``granite4.1:3b`` -> ``granite4.2:3b``) leaves this
    reference dangling. That is a real possibility on a dated catalogue, and the
    dangerous outcome is not the rename: it is a model quietly disappearing from the
    operator's list with nothing anywhere saying why.

    So a miss is REPORTED, never returned as an empty row. The entry then renders as
    unavailable with a drift reason, which is both honest and the fastest possible
    signal that the two catalogues have diverged.
    """
    from src.llm.ollama import MODEL_CATALOG

    for s in MODEL_CATALOG:
        if s.get("tag") == tag:
            return s
    return {
        "_missing": (
            f"'{tag}' is no longer in this app's dated Ollama catalogue — the two have "
            "drifted apart. Nothing is guessed in its place."
        )
    }


def _ollama_side(row: dict) -> dict:
    """The Ollama half of an entry built from a ``MODEL_CATALOG`` row, honouring a
    dangling join."""
    if row.get("_missing"):
        return {"artifact": None, "absent_reason": row["_missing"]}
    return {
        "artifact": row.get("tag"),
        "size": row.get("size"),
        "verification": "fetched",
    }


def _entries() -> dict[str, dict]:
    """Assemble the catalogue from the verified sources. Built per call rather than at
    import time so a test that patches a source sees the patched value."""
    from src.llm.bench_roster import BENCH_ROSTER
    from src.llm.ollama import (
        MINISTRAL_SUGGESTION,
        MINISTRAL_VLLM_MODEL,
    )

    roster = {e["key"]: e for e in BENCH_ROSTER}
    out: dict[str, dict] = {}

    # --- Ministral 3B: the default, dual, from MINISTRAL_SUGGESTION ---------- #
    mini_roster = roster.get("ministral-3-3b-instruct-2512", {})
    out["ministral-3-3b-instruct-2512"] = {
        "key": "ministral-3-3b-instruct-2512",
        "label": "Ministral 3 · 3B Instruct",
        "summary": "The default. Fits an 8 GB card on either backend.",
        "licence": MINISTRAL_SUGGESTION.get("license"),
        "ollama": {
            "artifact": MINISTRAL_SUGGESTION["tag"],
            "size": MINISTRAL_SUGGESTION.get("size"),
            "verification": (mini_roster.get("ollama") or {}).get("verification") or "fetched",
        },
        "vllm": {
            "artifact": MINISTRAL_VLLM_MODEL,
            "size": (mini_roster.get("hf") or {}).get("size") or "~8 GB (FP8 weights)",
            "verification": (mini_roster.get("hf") or {}).get("verification") or "fetched",
        },
        "caveats": list(MINISTRAL_SUGGESTION.get("caveats") or []),
    }

    # --- Ministral 8B: Ollama-only here ------------------------------------- #
    # The 8B image's tag, size and licence are verified in MODEL_CATALOG. Its
    # Hugging Face repo is NOT recorded anywhere in this tree, so vLLM gets an honest
    # absence rather than the plausible-looking name.
    eight = _from_suggestions("ministral-3:8b-instruct-2512-q4_K_M")
    out["ministral-3-8b-instruct-2512"] = {
        "key": "ministral-3-8b-instruct-2512",
        "label": "Ministral 3 · 8B Instruct",
        "summary": "Larger sibling of the default; wants ~16 GB RAM.",
        "licence": eight.get("license"),
        "ollama": _ollama_side(eight),
        "vllm": {
            "artifact": None,
            "absent_reason": (
                "No Hugging Face repo id for this build has been verified in this "
                "app, and it never guesses one."
            ),
        },
        "caveats": [],
    }

    # --- Granite: Ollama tags verified, no recorded HF repo ------------------ #
    for key, tag, summary in (
        ("granite-4-1-3b", "granite4.1:3b", "IBM Granite 4.1, multilingual, small."),
        ("granite-4-1-8b", "granite4.1:8b", "IBM Granite 4.1, multilingual, RAG/tools."),
    ):
        row = _from_suggestions(tag)
        out[key] = {
            "key": key,
            "label": f"Granite 4.1 · {tag.split(':')[1]}",
            "summary": summary,
            "licence": row.get("license"),
            "ollama": _ollama_side(row),
            "vllm": {
                "artifact": None,
                "absent_reason": (
                    "Granite's Hugging Face repo id is not recorded in this app, and it "
                    "never guesses one — the obvious-looking name is exactly the kind "
                    "that 404s."
                ),
            },
            "caveats": [],
        }

    # --- The roster models: dual where the roster verified both -------------- #
    for key, label, summary in (
        ("qwen35-0-8b", "Qwen3.5 · 0.8B", "Very small; long context."),
        ("gemma-3n-e2b-it", "Gemma 3n · E2B-IT", "Google's small instruct build."),
        ("phi-4-mini-instruct", "Phi-4 · mini instruct", "Microsoft, 3.8B class."),
        ("lfm25-1-2b-instruct", "LFM2.5 · 1.2B Instruct", "Liquid AI, very small."),
    ):
        e = roster.get(key)
        if not e:
            continue
        hf = e.get("hf") or {}
        oll = e.get("ollama") or {}
        out[key] = {
            "key": key,
            "label": label,
            "summary": summary,
            "licence": hf.get("licence"),
            "flags": list(e.get("flags") or []),
            "ollama": (
                {
                    "artifact": oll.get("tag"),
                    "size": oll.get("size"),
                    "verification": oll.get("verification"),
                }
                if oll.get("tag")
                else {
                    "artifact": None,
                    "absent_reason": (
                        "Not published on ollama.com/library under a first-party name, "
                        "and this app does not substitute a community re-upload."
                    ),
                }
            ),
            "vllm": (
                {
                    "artifact": hf.get("repo"),
                    "size": hf.get("size"),
                    "verification": hf.get("verification"),
                    "gated": hf.get("gated"),
                }
                if hf.get("repo")
                else {
                    "artifact": None,
                    "absent_reason": "No verified Hugging Face repo id is recorded.",
                }
            ),
            "caveats": [],
        }
    return out


def catalog_for(backend: str) -> dict:
    """The catalogue resolved for ONE backend.

    Every entry appears, in ``CATALOG_ORDER``. ``artifact`` is the thing that would
    actually be downloaded, or None with ``absent_reason`` when this backend has no
    verified build -- so the UI can disable a button WITH a reason rather than hide a
    model and leave the operator wondering why their list is short.
    """
    backend = "vllm" if str(backend).strip().lower() == "vllm" else "ollama"
    from src.llm.bench_roster import BENCH_ROSTER_AS_OF
    from src.llm.ollama import CATALOG_AS_OF

    built = _entries()
    models: list[dict] = []
    for key in CATALOG_ORDER:
        e = built.get(key)
        if not e:
            continue
        side = e.get(backend) or {}
        models.append(
            {
                "key": e["key"],
                "label": e["label"],
                "summary": e.get("summary"),
                "licence": e.get("licence"),
                "flags": e.get("flags") or [],
                "caveats": e.get("caveats") or [],
                "is_default": e["key"] == DEFAULT_KEY,
                "artifact": side.get("artifact"),
                "size": side.get("size"),
                "verification": side.get("verification"),
                "gated": side.get("gated"),
                "absent_reason": side.get("absent_reason"),
                "available": bool(side.get("artifact")),
            }
        )
    return {
        "backend": backend,
        "default_key": DEFAULT_KEY,
        "models": models,
        # Both dates, because the rows come from both registries and a single "as of"
        # would be true of only half the list.
        "as_of": {"roster": BENCH_ROSTER_AS_OF, "ollama_catalog": CATALOG_AS_OF},
        "method": (
            "Each model resolves to the artifact this backend can actually use — an "
            "Ollama image or a Hugging Face repo. Identifiers are the ones verified in "
            "this app's dated catalogues; where a build has not been verified for a "
            "backend, it is listed as unavailable with the reason, never guessed."
        ),
    }


def identifiers_for(backend: str, keys: list[str]) -> tuple[list[dict], list[dict]]:
    """Resolve ``keys`` to downloadable artifacts for ``backend``.

    Returns ``(ok, refused)`` -- the same contract as ``bench_roster.identifiers_for``,
    because refusals must travel WITH the result: an operator who asked for four models
    and can have two is owed an account of four, not a silent download of two.
    """
    resolved = {m["key"]: m for m in catalog_for(backend)["models"]}
    ok: list[dict] = []
    refused: list[dict] = []
    for key in keys or []:
        entry: dict[str, Any] | None = resolved.get(str(key))
        if entry is None:
            refused.append({"key": key, "reason": "not in the model catalogue"})
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
        ok.append(
            {"key": key, "label": entry["label"], "identifier": entry["artifact"]}
        )
    return ok, refused
