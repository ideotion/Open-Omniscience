"""The one shape a folder backup writes in its ``hf_models`` category (R777).

Kept in its own small module so the import scan (which stays crypto-free and import-light) and the
restore read the SAME rule: what the preview counts is what the restore places.
"""

from __future__ import annotations

#: R784: what a backup's ``hub/`` folder in its ``hf_models`` category stands for. Recorded in the
#: manifest of every backup that writes it: ``hub/`` is the Hugging Face hub cache folder ITSELF
#: (``HF_HUB_CACHE`` when set, whatever that folder is named), and a restore places it in the hub
#: cache folder of the computer it runs on. A backup made before this marker read
#: ``<parent of HF_HUB_CACHE>/hub``, so when that computer's cache folder was not named ``hub`` its
#: models are not in the backup at all; what it does hold still has the hub cache's own shape, so it
#: restores to the same place.
HF_LAYOUT = "hub-cache-1"


def hf_member_allowed(rel: str) -> bool:
    """Whether ``rel`` (relative to the ``hf_models`` category folder) has the one shape the backup
    writes there: ``hub/models--<repo>/refs/...`` or ``hub/models--<repo>/snapshots/...`` (see
    ``folder_backup.collect_hf_model_items``) (R777). A hidden name INSIDE a snapshot (a model repo's own
    ``.gitattributes``) is part of the model and stays inside the cache, so it is allowed there.

    The restore destination is the Hugging Face hub cache folder (R784), which ``HF_HUB_CACHE`` can
    point anywhere, a person's own home folder included; without this a backup carrying
    ``hf_models/hub/.bash_profile`` would have placed it there. Anything else in the folder is refused, counted and said, never placed."""
    parts = rel.split("/")
    if len(parts) < 4 or parts[0] != "hub" or not parts[1].startswith("models--") or parts[2] not in ("refs", "snapshots"):
        return False
    return all(x and x not in (".", "..") for x in parts)


def hf_live_rel(rel: str) -> str | None:
    """Where ``rel`` (relative to the ``hf_models`` category) goes inside the live hub cache folder
    (R784): the leading ``hub/`` is the cache folder itself, so it is dropped. ``None`` for anything
    outside the one shape :func:`hf_member_allowed` accepts -- never placed."""
    if not hf_member_allowed(rel):
        return None
    return rel.split("/", 1)[1]
