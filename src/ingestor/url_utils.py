"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com
"""

"""
URL Utilities for Open Omniscience

This module now redirects to the centralized URL utilities in src.utils.url_utils.
All URL utility functions have been moved to the centralized location for better
maintainability and to eliminate code duplication.

Please update your imports to use:
    from src.utils.url_utils import canonicalize_url, generate_content_hash, etc.

Author: Ideotion
"""

# Redirect all imports to the centralized URL utilities
from src.utils.url_utils import (
    canonicalize_url,
    generate_content_hash,
    get_base_url,
    get_domain_from_url,
    is_equivalent_domain,
    normalize_domain,
    resolve_redirects,
)

__all__ = [
    'normalize_domain',
    'is_equivalent_domain', 
    'canonicalize_url',
    'resolve_redirects',
    'generate_content_hash',
    'get_domain_from_url',
    'get_base_url',
]
