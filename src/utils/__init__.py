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
    sanitize_sql_input,
    validate_and_sanitize_filename,
    safe_path_join,
    sanitize_url,
    validate_email,
    validate_and_sanitize_search_query,
    sanitize_dict_input,
    generate_secure_token,
    hash_password,
    verify_password,
    get_security_headers,
    SECURITY_HEADERS,
)

__all__ = [
    'SecurityError',
    'sanitize_html',
    'escape_html',
    'sanitize_sql_input',
    'validate_and_sanitize_filename',
    'safe_path_join',
    'sanitize_url',
    'validate_email',
    'validate_and_sanitize_search_query',
    'sanitize_dict_input',
    'generate_secure_token',
    'hash_password',
    'verify_password',
    'get_security_headers',
    'SECURITY_HEADERS',
]