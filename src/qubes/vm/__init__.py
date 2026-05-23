"""
VM-specific modules for Open-Omniscience in Qubes OS.

This package contains modules for different types of VMs in the Qubes deployment.
"""

from .api_vm import APIVM
from .db_vm import DBVM
from .scraper_vm import ScraperVM

__all__ = ['APIVM', 'DBVM', 'ScraperVM']
