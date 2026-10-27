"""The one place that chooses which SAFE YAML loader class the project parses with.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

libyaml's loader when the wheel carries it, the pure-Python one when it does not. SAFE either way: this is a speed
choice, never a safety one (measured 2026-09-11 on configs/sources.yml, 5,580 entries: 3,148 ms pure-Python against
411 ms with libyaml). PyYAML exposes no C-loader variant of ``safe_load``, so the class is fixed HERE, at module level,
as one of the two safe classes and nothing else, with no per-call-site loader argument for a later edit to get wrong.

It has no import beyond ``yaml``, and that is the reason it is its own module. The catalogue seeder (``src.ingest.seed_sources``)
and the keyword rings reader (``src.analytics.equivalence``) both parse with this class; the rings reader is part of
the index engine's identity, and importing the seeder from it would have pulled the seed chain (the catalogue,
the ingest layer, the database identity helpers) into every index pass and into the engine closure test.
Which class parses the ring file decides how it parses, so this file is hashed into the engine identity
(``src.analytics.engine_identity.ENGINE_MODULES``).
"""
from __future__ import annotations

import yaml

SAFE_YAML_LOADERS = tuple(
    c for c in (getattr(yaml, "CSafeLoader", None), yaml.SafeLoader) if c is not None
)
YAML_LOADER = SAFE_YAML_LOADERS[0]


# THE DEPTH BOUND, and what it protects: libyaml's COMPOSER recurses on the C stack, once per nesting level, with no limit of
# its own. Measured 2026-10-27 on an 8 MiB stack (main thread and a worker thread alike, CPython 3.13, PyYAML 6.0.3): block
# and flow mappings parse to 23,681 levels and crash the process at 23,925; sequences parse to 25,876 and crash at 26,364. That is
# at most 8 MiB / 23,925 = 351 B of C stack per level. INFERRED, NOT MEASURED: a 512 KB stack (macOS secondary threads) crashes
# near 1,490 levels and a 1 MB one (Windows) near 2,990, so the headroom below depends on the stack being at least 512 KB (the
# app sets no ``threading.stack_size``). The pure-Python loader is not exposed: it raises RecursionError at about 500 levels
# (400 parse, 500 raise, measured). The deepest real file under ``configs/`` nests 5 levels. 256 is 51x above that, 5.8x below the
# inferred 512 KB crash depth and 93x below the measured 8 MiB one. A document past it is refused, never parsed.
MAX_NESTING = 256


# What the pure path says for a RecursionError. INFERRED, not known: a RecursionError carries no depth, so it can be this document or a
# caller whose stack was already deep, and the message names both rather than claiming the first.
PURE_RECURSION_MESSAGE = (
    "the document nests too deeply, or the caller's stack was already deep "
    "(inferred: the pure loader reports both as RecursionError)"
)


class YAMLDepthError(yaml.YAMLError):
    """A document nests deeper than :data:`MAX_NESTING`. A ``yaml.YAMLError``, so every caller that already refuses a malformed
    document refuses this one the same way. The message carries no text of the document."""


_OPENERS = (yaml.MappingStartEvent, yaml.SequenceStartEvent)
_CLOSERS = (yaml.MappingEndEvent, yaml.SequenceEndEvent)


def _uses_libyaml() -> bool:
    c_loader = getattr(yaml, "CSafeLoader", None)
    return c_loader is not None and issubclass(YAML_LOADER, c_loader)


def _require_within_bound(depth: int) -> None:
    if depth > MAX_NESTING:
        raise YAMLDepthError(f"the document nests deeper than {MAX_NESTING} levels")


def refuse_if_too_deep(text: str) -> None:
    """Count nesting from libyaml's EVENT stream before anything is composed (the parser is a heap-allocated state machine and
    does not recurse); raise as soon as the bound is passed, so a 100,000-deep document costs 257 events. A no-op on the pure
    path, which cannot crash the process (see :func:`load_safe_yaml`). Public for the one caller that keeps its own loader
    wrapper (``seed_sources``, whose GC pause surrounds the parse)."""
    if not _uses_libyaml():
        return
    loader = YAML_LOADER(text)
    try:
        depth = 0
        # the guard-clause loop form (src/utils/interrupts.py): the last statement is a call, not a bare ``if``, so the back-edge stays
        # inside the ``try``/``finally``. The bound is checked right after each opener, so a document whose 257th opener is also the
        # last thing the parser can read is still refused as too deep, not as malformed
        while True:
            if not loader.check_event():
                break
            event = loader.get_event()
            depth += int(isinstance(event, _OPENERS)) - int(isinstance(event, _CLOSERS))
            _require_within_bound(depth)
    finally:
        loader.dispose()


def load_safe_yaml(text: str):
    """``yaml.safe_load``'s own body with the loader chosen above: the document's single value, ``None`` for an empty one.

    Raises :class:`YAMLDepthError` for a too-deep document on BOTH paths: libyaml's is refused past :data:`MAX_NESTING` before it
    is composed (it would crash the process); the pure loader gets no pre-pass (measured: it would add 78% to its parse) and its
    own RecursionError, at about 500 levels, is turned into the same error."""
    refuse_if_too_deep(text)
    loader = YAML_LOADER(text)
    try:
        return loader.get_single_data()
    except RecursionError:
        # the pure loader's own limit (about 500 levels), not the bound above: said without a number
        raise YAMLDepthError(PURE_RECURSION_MESSAGE) from None
    finally:
        loader.dispose()
