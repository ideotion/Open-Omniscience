"""
Chain of custody: honest, tamper-evident provenance for legal defensibility.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

This package turns the project's "legal admissibility" promise into something
real and honest (PRODUCT_SYNTHESIS §3.5: *chain-of-custody must be real -- signed,
tamper-evident -- not a plain log file*), without security theatre:

- ``signing``   -- hybrid Ed25519 + post-quantum ML-DSA signatures (AND semantics,
                   honest labels, no silent downgrade).
- ``timestamp`` -- "existed no later than T" proofs (self-asserted local clock,
                   plus optional OpenTimestamps anchoring to Bitcoin). Never
                   fabricates a third-party time.
- ``log``       -- an append-only, hash-chained, signed custody log of actions on
                   an item, independently verifiable offline.
- ``anchor``    -- pluggable anchoring providers (offline local + OpenTimestamps;
                   public-chain providers are opt-in and carry a privacy warning).
"""

from __future__ import annotations
