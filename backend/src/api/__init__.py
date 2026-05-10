"""
API package for Open-Omniscience
"""

from .articles import router as articles_router
from .keywords import router as keywords_router
from .sources import router as sources_router
from .similarity import router as similarity_router
from .dashboard import router as dashboard_router
from .export import router as export_router

__all__ = [
    'articles_router',
    'keywords_router',
    'sources_router',
    'similarity_router',
    'dashboard_router',
    'export_router',
]
