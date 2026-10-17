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


def load_safe_yaml(text: str):
    """``yaml.safe_load``'s own body with the loader chosen above: the document's single value, ``None`` for an empty one."""
    loader = YAML_LOADER(text)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()
