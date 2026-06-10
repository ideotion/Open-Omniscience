"""
Offline source discovery -- the first two channels of RM-19 (0.0.8 part 2, WP5).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Discovery that NEVER touches the network: candidates are computed purely from
what the corpus already knows. Transparency is non-negotiable (maintainer
direction): every candidate carries its channel + evidence, lands in a staging
state the operator reviews (promote => a DISABLED Source the operator must
still enable; dismiss => remembered, never re-suggested), every run is capped
by the operator's budget and recorded in the scheduler run log.

Channels here:
  * citation  -- external domains your stored articles repeatedly cite
                 (from article_links; counts are the evidence).
  * catalog   -- packaged-catalog entries for countries where your coverage
                 is thin (the coverage report is the evidence).

The DuckDuckGo search channel deliberately does NOT exist here -- it ships
only behind the external-lookup gate (RM-03) once this staging UX has proven
itself, per the RM-19 dependency.
"""

from src.discovery.channels import run_discovery  # noqa: F401
