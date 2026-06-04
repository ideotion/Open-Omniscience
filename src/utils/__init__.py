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
Utilities package for Open Omniscience

This package contains utility modules for:
- Security (input validation, sanitization, etc.)
- Logging configuration
- Common helpers and utilities

Author: Ideotion
"""

from .security import (
    SecurityError,
    sanitize_html,
    escape_html,
    validate_and_sanitize_filename,
    safe_path_join,
    sanitize_url,
    validate_email,
    validate_and_sanitize_search_query,
    generate_secure_token,
    hash_password,
    verify_password,
    get_security_headers,
    SECURITY_HEADERS,
)

from .url_utils import (
    normalize_domain,
    is_equivalent_domain,
    canonicalize_url,
    resolve_redirects,
    generate_content_hash,
    get_domain_from_url,
    get_base_url,
)

__all__ = [
    # Security utilities
    'SecurityError',
    'sanitize_html',
    'escape_html',
    'validate_and_sanitize_filename',
    'safe_path_join',
    'sanitize_url',
    'validate_email',
    'validate_and_sanitize_search_query',
    'generate_secure_token',
    'hash_password',
    'verify_password',
    'get_security_headers',
    'SECURITY_HEADERS',
    # URL utilities
    'normalize_domain',
    'is_equivalent_domain',
    'canonicalize_url',
    'resolve_redirects',
    'generate_content_hash',
    'get_domain_from_url',
    'get_base_url',
]