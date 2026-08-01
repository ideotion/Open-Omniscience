"""
The Bulletin — a periodic document generated from the corpus.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Design record: ``docs/design/BULLETIN_DESIGN_2026-07-31.md``.

Two layers, and the split is the point:

* **Layer A** (this package's ``period`` + ``facts``) is deterministic and
  model-free. It answers "what does the corpus say about this period" in exact,
  uncapped counts with the method beside every number.
* **Layer B** (later) is a local model narrating Layer A's bundles. Strip it and
  the document is still complete, just stiffer.

Nothing here calls a model, and nothing here touches the network.
"""

from __future__ import annotations
