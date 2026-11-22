"""The one shape a folder backup writes in its ``hf_models`` category (R777).

Kept in its own small module so the import scan (which stays crypto-free and import-light) and the
restore read the SAME rule: what the preview counts is what the restore places.
"""

from __future__ import annotations


def hf_member_allowed(rel: str) -> bool:
    """Whether ``rel`` (relative to the ``hf_models`` category folder) has the one shape the backup
    writes there: ``hub/models--<repo>/refs/...`` or ``hub/models--<repo>/snapshots/...`` (see
    ``folder_backup.collect_hf_model_items``) (R777). A hidden name INSIDE a snapshot (a model repo's own
    ``.gitattributes``) is part of the model and stays inside the cache, so it is allowed there.

    The restore destination is the Hugging Face home, which can be a person's own home folder when
    ``HF_HUB_CACHE`` is set; without this a backup carrying ``hf_models/.bash_profile`` would have
    placed it there. Anything else in the folder is refused, counted and said, never placed."""
    parts = rel.split("/")
    if len(parts) < 4 or parts[0] != "hub" or not parts[1].startswith("models--") or parts[2] not in ("refs", "snapshots"):
        return False
    return all(x and x not in (".", "..") for x in parts)
