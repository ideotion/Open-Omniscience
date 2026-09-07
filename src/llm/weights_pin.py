"""The model-weights integrity pin (D6) -- the one downloaded artifact that had none.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

HOUSE DOCTRINE, AND THE HOLE IN IT. Everything else this app downloads is checked
before it is used: the DuckDB ``httpfs`` extension is SHA-pinned and re-verified
before every ``LOAD``; the Ollama installer verifies the binary against GitHub's own
attested ``digest: sha256:...`` and REFUSES when no digest is attested; and
``configs/external_artifacts.yml`` exists so that anything externally sourced gets an
entry in the same commit. Model weights escaped all three -- ``snapshot_download(repo)``
took whatever ``main`` pointed at, and ``ollama pull tag`` took whatever the tag pointed
at, so the bytes could change under an operator between two installs with nothing to say
so. (Recorded 2026-08-05 from the operator's own provisioning scripts, which fetch at a
full 40-char commit SHA and write a manifest every later run verifies.)

WHAT THIS MODULE IS. The pin, its three honest states, and the refusal. It is
deliberately NOT a checksum of the weight files: a Hugging Face revision IS a content
commitment (the repo's git commit), ``huggingface_hub`` accepts ``revision=``, and the
cache lays the bytes down under ``snapshots/<commit sha>/`` -- so the resolved revision
is readable from the download's own return value and needs no second hashing pass over
several gigabytes.

THREE STATES, NEVER TWO. "pinned and it matched", "pinned and it did NOT match" and
"not pinned at all" are three different facts, and the third is the one a two-state
design fabricates: an unpinned download that reports nothing reads exactly like a
verified one. So every caller gets a basis string, and the UI states it.

THE PINS SHIP BLANK, AND THAT IS THE HONEST STATE, not an oversight. Resolving the
real commit SHA needs ``huggingface.co``; resolving Ollama's manifest digest needs
``ollama.com``. Both answer the build sandbox's proxy with ``CONNECT ... 403``
(re-probed 2026-09-07, ``pypi.org`` 200 as the control), so the session that writes
this file cannot verify a value to write into it -- and a digest nobody fetched, typed
into the repository, is precisely the fabricated checksum the non-negotiables forbid.
This is the shape ``offline-bundle-python-runtime`` and the ``httpfs`` binaries already
use in the registry: a blank pin, recorded, with the operator's route to filling it.

A PIN IS PER MODEL AND IS NEVER INHERITED. A pin recorded for the model this app chose
says nothing about a model an operator typed into Settings, so a custom model is
reported ``unpinned`` with that as its reason -- never quietly checked against, or
excused by, the roster model's pin.
"""

from __future__ import annotations

import os
import re
from typing import NamedTuple

# src.llm.ollama has NO module-level `src.*` imports of its own, so this edge cannot
# close a cycle (checked against the import-graph probe rather than assumed).
from src.llm.ollama import MINISTRAL_TAG, MINISTRAL_VLLM_MODEL

#: A Hugging Face revision that can be VERIFIED after the fact: a full 40-hex commit
#: SHA. A branch or tag name is refused as a pin -- ``main`` is exactly the moving
#: target this exists to close, and a tag can be re-pointed, so accepting one would
#: publish "pinned" for something that still moves.
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

#: Ollama reports a manifest digest as ``sha256:<64 hex>``; the bare hex is accepted
#: too, since that is how the library page prints the short form's parent.
_OLLAMA_DIGEST_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")


class Pin(NamedTuple):
    """What is pinned for one model, and where the pin came from.

    ``value`` is empty when nothing is pinned; ``basis`` always says why, because
    "no pin" and "a pin that matched" must never be readable as the same answer.
    """

    value: str
    basis: str

    @property
    def pinned(self) -> bool:
        return bool(self.value)


class PinMismatch(RuntimeError):
    """The bytes that arrived are not the bytes that were pinned. Never downgraded to
    a warning: a mismatch means the artifact changed under the operator, which is the
    single thing the pin exists to detect."""


#: The in-repo pins, registered as ``model-weights-revision`` in
#: ``configs/external_artifacts.yml``. BLANK BY DESIGN -- see the module docstring. A value here is a
#: claim this project verified against the publisher, and no session that could not
#: reach the publisher may write one. The operator's route is the env override below,
#: which is also what a "re-pin deliberately" looks like after a genuine model bump.
#:
#: Keyed by the identifier each backend actually consumes, because the two are not
#: derivable from one another (the standing reason both live in ollama.py).
HF_REVISION_PINS: dict[str, str] = {}
OLLAMA_DIGEST_PINS: dict[str, str] = {}

#: Operator overrides. Scoped to the model the app itself chose: an operator pinning
#: "the model" means the one the app serves, and a value typed for that model must not
#: silently become a claim about a different one they download later.
_HF_ENV = "OO_MODEL_REVISION"
_OLLAMA_ENV = "OO_OLLAMA_MODEL_DIGEST"


def hf_revision_pin(model: str) -> Pin:
    """The pinned Hugging Face revision for ``model``, or an unpinned :class:`Pin`.

    An operator value wins over the (blank) in-repo one -- that IS the re-pin route --
    but only for the model this app chose. A malformed override is REFUSED rather than
    used: a 7-character short SHA or a branch name would make ``revision=`` resolve to
    something that still moves while the payload said "pinned", which is worse than
    being honestly unpinned.
    """
    model = (model or "").strip()
    if not model:
        return Pin("", "no model named")
    if model == MINISTRAL_VLLM_MODEL:
        env = (os.getenv(_HF_ENV) or "").strip().lower()
        if env:
            if _SHA_RE.match(env):
                return Pin(env, f"operator pin ({_HF_ENV})")
            return Pin(
                "",
                f"{_HF_ENV} is not a full 40-character commit SHA, so it was refused as "
                "a pin -- a branch or short SHA still moves",
            )
        recorded = (HF_REVISION_PINS.get(model) or "").strip().lower()
        if recorded and _SHA_RE.match(recorded):
            return Pin(recorded, "recorded in src/llm/weights_pin.py")
        return Pin(
            "",
            "no revision is pinned for this app's model: huggingface.co cannot be "
            f"reached from the build sandbox, so the pin ships blank -- set {_HF_ENV} "
            "to a full commit SHA to pin it",
        )
    return Pin(
        "",
        "no revision is pinned for a model this app did not choose -- the pin recorded "
        "for the shipped model says nothing about these bytes",
    )


def ollama_digest_pin(tag: str) -> Pin:
    """The pinned Ollama manifest digest for ``tag``, or an unpinned :class:`Pin`.

    Same three states and the same never-inherited rule as :func:`hf_revision_pin`.
    """
    tag = (tag or "").strip()
    if not tag:
        return Pin("", "no model named")
    if tag == MINISTRAL_TAG:
        env = (os.getenv(_OLLAMA_ENV) or "").strip().lower()
        if env:
            if _OLLAMA_DIGEST_RE.match(env):
                return Pin(_normalise_digest(env), f"operator pin ({_OLLAMA_ENV})")
            return Pin(
                "",
                f"{_OLLAMA_ENV} is not a sha256 digest, so it was refused as a pin",
            )
        recorded = (OLLAMA_DIGEST_PINS.get(tag) or "").strip().lower()
        if recorded and _OLLAMA_DIGEST_RE.match(recorded):
            return Pin(_normalise_digest(recorded), "recorded in src/llm/weights_pin.py")
        return Pin(
            "",
            "no digest is pinned for this app's model: ollama.com cannot be reached "
            f"from the build sandbox, so the pin ships blank -- set {_OLLAMA_ENV} to the "
            "manifest digest to pin it",
        )
    return Pin(
        "",
        "no digest is pinned for a model this app did not choose -- the pin recorded "
        "for the shipped model says nothing about these bytes",
    )


def _normalise_digest(value: str) -> str:
    v = value.strip().lower()
    return v if v.startswith("sha256:") else f"sha256:{v}"


def revision_of_snapshot_path(path: str) -> str:
    """The commit SHA ``huggingface_hub`` laid the download down under.

    ``snapshot_download`` returns ``.../snapshots/<commit sha>``, so the resolved
    revision is a fact the download itself reports -- no second pass over several
    gigabytes, and nothing re-derived from a name we chose. Returns "" when the path
    is not that shape rather than guessing, because a guessed revision compared
    against a pin is the fabricated verification this module exists to prevent.
    """
    tail = (path or "").rstrip("/\\").replace("\\", "/").rsplit("/", 1)[-1].strip().lower()
    return tail if _SHA_RE.match(tail) else ""


def check_downloaded_revision(model: str, snapshot_path: str) -> dict:
    """Compare what ARRIVED against what was PINNED. Raises :class:`PinMismatch` on a
    genuine mismatch; returns the three-state record otherwise.

    THE REFUSAL IS HERE AND NOT AT SERVE TIME, deliberately. A download is where new
    bytes enter, so it is the chokepoint a pin can defend without cost. Refusing to
    SERVE a cache that predates the pin would convert a working install into a failed
    one for every operator who downloaded before pinning -- the recorded
    "a floor that overrides a working value turns a working start into a failed one"
    hazard -- so the serve side DISCLOSES (``model_cache_state``) and never refuses.
    """
    pin = hf_revision_pin(model)
    got = revision_of_snapshot_path(snapshot_path)
    if not pin.pinned:
        return {"pinned": False, "basis": pin.basis, "revision": got or None, "verified": False}
    if not got:
        raise PinMismatch(
            f"{model} is pinned to revision {pin.value} but the download did not report "
            "which revision it wrote, so the bytes could not be verified. Nothing was "
            "deleted; re-run the download, or clear the pin to proceed unverified."
        )
    if got != pin.value:
        raise PinMismatch(
            f"{model} is pinned to revision {pin.value} but revision {got} arrived. The "
            "published weights are not the bytes this install was pinned to. Nothing was "
            f"deleted. Re-pin deliberately ({_HF_ENV}) once you have checked the change, "
            "or clear the pin to proceed unverified."
        )
    return {"pinned": True, "basis": pin.basis, "revision": got, "verified": True}


def check_pulled_digest(tag: str, digest: str | None) -> dict:
    """The Ollama half: compare the manifest digest a pull left behind against the pin.

    ``digest`` is what Ollama itself reports for the installed tag (``/api/tags``); a
    ``None`` means we could not read one, which is NOT a match and NOT a mismatch --
    a third state, reported as such, because reading an unanswered question as "fine"
    is the ``.get(key, 0)`` fabrication one level up.
    """
    pin = ollama_digest_pin(tag)
    got = _normalise_digest(digest) if digest else ""
    if not pin.pinned:
        return {"pinned": False, "basis": pin.basis, "digest": got or None, "verified": False}
    if not got:
        return {
            "pinned": True,
            "basis": pin.basis,
            "digest": None,
            "verified": False,
            "reason": "Ollama reported no digest for this tag, so the pin could not be checked",
        }
    if got != pin.value:
        raise PinMismatch(
            f"{tag} is pinned to {pin.value} but {got} is installed. The published image "
            "is not the bytes this install was pinned to. Nothing was deleted. Re-pin "
            f"deliberately ({_OLLAMA_ENV}) once you have checked the change, or clear the "
            "pin to proceed unverified."
        )
    return {"pinned": True, "basis": pin.basis, "digest": got, "verified": True}


__all__ = [
    "HF_REVISION_PINS",
    "OLLAMA_DIGEST_PINS",
    "Pin",
    "PinMismatch",
    "check_downloaded_revision",
    "check_pulled_digest",
    "hf_revision_pin",
    "ollama_digest_pin",
    "revision_of_snapshot_path",
]
