"""One recursive secret-scrubber, shared by every payload that leaves the process.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Two divergent copies of this idea already existed (``src/api/diagnostics.py``'s
``_p0_scrub`` and ``src/llm/vllm_lifecycle.py``'s own), and the run journal added a
third caller. Two implementations of a safety property means one of them is the
weaker one and nobody knows which; this is the single definition they can converge
on.

It is DEFENCE IN DEPTH, never the primary guarantee. The backup/merge chain is
passphrase-free by construction (no raise site interpolates the value, no
subprocess is spawned, so nothing lands on a command line) -- this makes that
absence a PROPERTY of every payload rather than a convention each future author
has to remember.

HONEST LIMIT, stated because it is the interesting half: this matches KEYS, not
values. A secret pasted into a free-text field, or embedded in a filesystem path,
passes straight through -- the scrubber cannot recognise a string it was never
told. Callers must still not put secrets in values.
"""

from __future__ import annotations

from typing import Any

#: A key whose lowercased name CONTAINS any of these has its value redacted.
SECRET_KEY_FRAGMENTS: tuple[str, ...] = (
    "passphrase",
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "private_key",
)

REDACTED = "***redacted***"


def scrub(obj: Any, *, _depth: int = 0) -> Any:
    """Recursively redact any value under a secret-looking key.

    Depth-bounded (a self-referential structure would otherwise recurse forever;
    a scrubber that can hang the thing it protects is the sidecar-that-breaks-the-
    operation failure mode this project has a recorded lesson about). Beyond the
    bound the value is replaced with a marker naming WHY it is not there, never
    silently dropped.
    """
    if _depth > 12:
        return "***depth-limited***"
    if isinstance(obj, dict):
        out: dict = {}
        for k, v in obj.items():
            kl = k.lower() if isinstance(k, str) else ""
            if any(frag in kl for frag in SECRET_KEY_FRAGMENTS):
                out[k] = REDACTED
            else:
                out[k] = scrub(v, _depth=_depth + 1)
        return out
    if isinstance(obj, (list, tuple)):
        return [scrub(v, _depth=_depth + 1) for v in obj]
    return obj
