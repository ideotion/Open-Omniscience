"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Link analysis services.

STATUS (v0.4): only the honest link *extractor* remains here. The classifier,
credibility scorer, source scraper, network analyzer, source identifier,
relationship tracker, and temporal analyzer were QUARANTINED
(``quarantine/link_analyzer/``) because they produced fabricated or misleading
outputs -- e.g. the credibility scorer returned ~100 for every input, the source
scraper claimed to respect robots.txt while the robots code was dead and its
content cleaner destroyed any article mentioning a year. The ``link_analysis``
router that exposed them was removed too. See docs/HISTORY.md.
"""

from .extractor import LinkExtractor

__all__ = ["LinkExtractor"]
