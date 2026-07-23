"""
Router wiring for the API app — extracted from main.py (audit PR H).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``main.py`` had ~35 ``app.include_router(...)`` calls (plus their imports and the
optional-extra conditional) inline, which dominated the module. They live here now,
behind a single ``wire(app)`` called once from ``main.py`` AFTER the app + middleware
exist. Every router is imported INSIDE ``wire()`` (deferred to call time): this
matches — and generalises — the old "import jobs/unlock after the app exists"
pattern, so a router that needs ``main.app`` resolves cleanly and there is no
import cycle. The route order is preserved exactly; the resulting route set is
asserted identical in ``tests/test_api_wiring.py``.
"""

from __future__ import annotations

import logging

_LOG = logging.getLogger(__name__)


def wire(app) -> None:
    """Include every API router on ``app``, in the original order.

    Imports are local (call-time) on purpose — see the module docstring. The
    analysis-dependent routers are included only when the ``[analysis]`` extra is
    installed; a core-only install still boots with the spine.
    """
    # --- spine routers (always present) -------------------------------------- #
    from src.api.agenda_state import router as agenda_state_router
    from src.api.ai import router as ai_router
    from src.api.annotations import router as annotations_router
    from src.api.article_dates import router as article_dates_router
    from src.api.backup_v2 import router as backup_v2_router
    from src.api.briefing import router as briefing_router
    from src.api.custody import router as custody_router
    from src.api.database import router as database_router
    from src.api.diagnostics import router as diagnostics_router
    from src.api.events import router as events_router
    from src.api.files import router as files_router
    from src.api.geo import router as geo_router
    from src.api.governments import router as governments_router
    from src.api.hazards import router as hazards_router
    from src.api.ingestion import router as ingestion_router
    from src.api.insights import router as insights_router
    from src.api.integrity import router as integrity_router
    from src.api.jobs import router as jobs_router
    from src.api.law import router as law_router
    from src.api.legal import router as legal_router
    from src.api.library import router as library_router
    from src.api.link_analysis import router as link_analysis_router
    from src.api.link_preview import router as link_preview_router
    from src.api.llm import router as llm_router
    from src.api.markets import router as markets_router
    from src.api.monitoring import router as monitoring_router
    from src.api.personality import router as personality_router
    from src.api.quarantine import router as quarantine_router
    from src.api.reporting import router as reporting_router
    from src.api.safety import router as safety_router
    from src.api.scheduler import router as scheduler_router
    from src.api.search_omni import router as search_omni_router
    from src.api.settings import router as settings_router
    from src.api.signals import router as signals_router
    from src.api.source_io import router as source_io_router
    from src.api.source_management import router as source_management_router
    from src.api.stats import router as stats_router
    from src.api.system import router as system_router
    from src.api.timemap import router as timemap_router
    from src.api.unlock import router as unlock_router
    from src.api.verification import router as verification_router
    from src.api.watches import router as watches_router
    from src.api.weather import router as weather_router
    from src.api.wiki import router as wiki_router

    # Ordered exactly as main.py included them (path-based routing makes order
    # immaterial for dispatch, but the route set + order stay identical).
    spine = (
        source_management_router,
        quarantine_router,
        database_router,
        library_router,
        backup_v2_router,
        settings_router,
        scheduler_router,
        markets_router,
        source_io_router,
        insights_router,
        diagnostics_router,
        briefing_router,
        integrity_router,
        annotations_router,
        law_router,
        legal_router,
        link_analysis_router,
        link_preview_router,
        wiki_router,
        llm_router,
        ingestion_router,
        system_router,
        jobs_router,
        unlock_router,
        hazards_router,
        events_router,
        files_router,
        geo_router,
        stats_router,
        governments_router,
        watches_router,
        weather_router,
        search_omni_router,
        personality_router,
        timemap_router,
        article_dates_router,
        ai_router,
        signals_router,
        agenda_state_router,
    )
    for router in spine:
        app.include_router(router)

    # --- analysis-dependent routers (optional [analysis] extra) -------------- #
    try:
        from src.api.analysis import router as analysis_router
        from src.api.commodity import router as commodity_router
        from src.api.framing import router as framing_router
        from src.api.keyword_analysis import router as keyword_analysis_router
        from src.api.keyword_management import router as keyword_management_router
    except ImportError:
        _LOG.warning(
            "Commodity, statistical-analysis & keyword endpoints disabled: install the "
            "[analysis] extra (pip install -e '.[analysis]') to enable them."
        )
    else:
        for router in (
            commodity_router,
            analysis_router,
            keyword_management_router,
            keyword_analysis_router,
            framing_router,
        ):
            app.include_router(router)

    # --- trailing routers (kept after the analysis block, as in main.py) ----- #
    for router in (
        monitoring_router,
        reporting_router,
        custody_router,
        verification_router,
        safety_router,
    ):
        app.include_router(router)
