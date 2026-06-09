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
Security Utilities for Open Omniscience

This module provides security-related utilities including:
- Input validation and sanitization
- SQL injection prevention
- XSS prevention
- CSRF protection
- Session security
- Path traversal prevention

Author: Ideotion
"""

import html
import logging
import re
from pathlib import Path

# Configure logging
logger = logging.getLogger(__name__)

# bleach is a required dependency (see pyproject). HTML sanitization must use a
# real allowlist sanitizer; we deliberately do NOT silently fall back to escaping
# everything, which would corrupt content while appearing to work.
import bleach


class SecurityError(Exception):
    """Custom exception for security-related errors."""
    pass


def sanitize_html(content: str) -> str:
    """
    Sanitize HTML content to prevent XSS attacks.
    
    Args:
        content: The HTML content to sanitize.
        
    Returns:
        Sanitized HTML with dangerous tags and attributes removed.
    """
    if not content:
        return content
    
    # List of allowed HTML tags
    ALLOWED_TAGS = [
        'p', 'br', 'b', 'i', 'u', 'em', 'strong', 'a', 'ul', 'ol', 'li',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'code', 'pre',
        'hr', 'img', 'table', 'tr', 'td', 'th', 'thead', 'tbody', 'tfoot'
    ]
    
    # Allowed attributes per tag. 'style' is intentionally NOT allowed (inline
    # CSS is an XSS vector and would require a separate CSS sanitizer).
    ALLOWED_ATTRIBUTES = {
        'a': ['href', 'title', 'rel'],
        'img': ['src', 'alt', 'width', 'height'],
        '*': ['class', 'id'],
    }

    return bleach.clean(
        content,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        strip=True,
        strip_comments=True,
    )


def escape_html(content: str) -> str:
    """
    Escape HTML special characters to prevent XSS.
    
    Args:
        content: The content to escape.
        
    Returns:
        HTML-escaped content.
    """
    if not content:
        return content
    return html.escape(content)


# NOTE (P0-8): the former ``sanitize_sql_input`` was removed in v0.4. It was a
# regex keyword blocklist that silently corrupted legitimate input -- e.g. it
# turned the search "oil prices DROP" into "oil prices" and mangled "AT&T" -- and
# gave a false sense of security. SQL safety comes from parameterized queries
# (SQLAlchemy binds every value), which the codebase now uses throughout. Likewise
# ``sanitize_dict_input`` was removed: destructively rewriting stored values is
# not injection defense.


def validate_and_sanitize_filename(filename: str) -> str:
    """
    Validate and sanitize a filename to prevent path traversal.
    
    Args:
        filename: The filename to validate and sanitize.
        
    Returns:
        Sanitized filename.
        
    Raises:
        SecurityError: If the filename contains dangerous characters or patterns.
    """
    if not filename:
        raise SecurityError("Filename cannot be empty")
    
    # Check for path traversal attempts
    if '..' in filename or filename.startswith('/') or filename.startswith('\\'):
        raise SecurityError(f"Invalid filename: potential path traversal detected: {filename}")
    
    # Remove dangerous characters
    dangerous_chars = ['<', '>', ':', '"', '|', '?', '*', '\x00', '\x1f']
    for char in dangerous_chars:
        if char in filename:
            raise SecurityError(f"Invalid filename: contains dangerous character '{char}'")
    
    # Only allow alphanumeric, underscores, hyphens, dots, and spaces
    if not re.match(r'^[a-zA-Z0-9_\-\.\s]+$', filename):
        raise SecurityError(f"Invalid filename: contains invalid characters: {filename}")
    
    # Normalize the filename
    filename = filename.strip().replace(' ', '_')
    
    return filename


def safe_path_join(base_path: str | Path, *parts: str) -> Path:
    """
    Safely join path components to prevent path traversal.
    
    Args:
        base_path: The base directory path.
        *parts: Additional path components to join.
        
    Returns:
        A safe Path object.
        
    Raises:
        SecurityError: If any path component attempts to traverse outside the base path.
    """
    base_path = Path(base_path).resolve()
    
    # Validate each part
    for part in parts:
        if not part:
            continue
        if '..' in part or part.startswith('/') or part.startswith('\\'):
            raise SecurityError(f"Path traversal attempt detected in: {part}")
    
    # Join and resolve the path
    result_path = base_path.joinpath(*parts).resolve()
    
    # Ensure the result is within the base path
    try:
        result_path.relative_to(base_path)
    except ValueError:
        raise SecurityError(f"Path {result_path} is outside base directory {base_path}")
    
    return result_path


def sanitize_url(url: str) -> str:
    """
    Sanitize a URL to prevent injection attacks.
    
    Args:
        url: The URL to sanitize.
        
    Returns:
        Sanitized URL.
    """
    if not url:
        return url

    # Strip leading/trailing whitespace and control chars BEFORE the scheme check:
    # browsers ignore leading whitespace, so " javascript:alert(1)" would otherwise
    # bypass the check and still execute.
    url = re.sub(r'[\x00-\x20\x7f]+', '', url)

    # Remove dangerous schemes
    if url.lower().startswith(('javascript:', 'data:', 'vbscript:', 'file:')):
        return ""
    
    # Validate URL structure
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            # If no scheme or netloc, assume it's a relative URL
            return url
    except Exception:
        return ""
    
    return url


# Characters that make a spreadsheet treat a cell as a formula / command (CWE-1236).
_CSV_FORMULA_LEADERS = ("=", "+", "-", "@", "\t", "\r", "\n")


def csv_safe_cell(value: object) -> str:
    """Neutralize spreadsheet formula injection in an exported CSV cell (S-004).

    Ingested article titles/content are attacker-controlled; a cell beginning with
    ``= + - @`` (or a control char) executes as a formula/DDE when the export is opened
    in Excel/LibreOffice. Prefixing a single quote forces the spreadsheet to treat it as
    text. The value is otherwise unchanged (CSV quoting handles commas/quotes/newlines).
    """
    if value is None:
        return ""
    text = str(value)
    if text and text[0] in _CSV_FORMULA_LEADERS:
        return "'" + text
    return text


def safe_href(url: str | None) -> str:
    """Return ``url`` only if it is a plain ``http(s)`` link, else ``""`` (S-005).

    A strict scheme allowlist for ingested URLs rendered as ``href``: a malicious feed
    ``<link>javascript:…`` survives HTML-escaping (which doesn't touch the scheme), so a
    click would run script in the app's origin. Anything that is not http/https — and any
    URL carrying control characters browsers would strip — is dropped.
    """
    if not url:
        return ""
    cleaned = re.sub(r"[\x00-\x20\x7f]+", "", url)
    from urllib.parse import urlparse
    try:
        scheme = urlparse(cleaned).scheme.lower()
    except Exception:
        return ""
    return cleaned if scheme in ("http", "https") else ""


def validate_email(email: str) -> bool:
    """
    Validate an email address format.
    
    Args:
        email: The email address to validate.
        
    Returns:
        True if the email is valid, False otherwise.
    """
    if not email:
        return False
    
    # Simple email validation regex - more strict
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    # Additional check for consecutive dots
    if '..' in email:
        return False
    return bool(re.match(pattern, email))


def validate_and_sanitize_search_query(query: str, max_length: int = 500) -> str:
    """
    Validate and sanitize a search query.
    
    Args:
        query: The search query to validate and sanitize.
        max_length: Maximum allowed length of the query.
        
    Returns:
        Sanitized search query.
        
    Raises:
        SecurityError: If the query contains dangerous content.
    """
    if not query:
        return query

    if len(query) > max_length:
        raise SecurityError(f"Search query exceeds maximum length of {max_length} characters")

    # Non-destructive: only strip control characters and surrounding whitespace.
    # The query is NOT keyword-filtered or HTML-escaped -- doing so corrupted
    # legitimate searches (e.g. "AT&T", "oil prices DROP"). Safety against SQL
    # injection comes from parameterized queries / FTS5 MATCH binding, and the
    # Boolean parser in src/database/fts.py validates structure.
    query = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', query)

    return query.strip()


def generate_secure_token(length: int = 32) -> str:
    """
    Generate a secure random token.
    
    Args:
        length: Length of the token in bytes.
        
    Returns:
        Secure random token as a hexadecimal string.
    """
    import secrets
    return secrets.token_hex(length)


def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt.
    
    Args:
        password: The password to hash.
        
    Returns:
        Bcrypt hash of the password.
    """
    # bcrypt is required (see pyproject). We do NOT silently fall back to a
    # single-round SHA-256 (P0-9): that produced an insecure hash that *looked*
    # like a password hash, and the fallback verifier did not even match it.
    import bcrypt

    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """
    Verify a password against its hash.
    
    Args:
        password: The password to verify.
        hashed: The hashed password to verify against.
        
    Returns:
        True if the password matches, False otherwise.
    """
    import bcrypt

    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # Malformed/old non-bcrypt hash -> not a valid match (never a silent pass).
        return False


# Security headers for HTTP responses
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-src 'none'; object-src 'none'",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()"
}


def get_security_headers() -> dict[str, str]:
    """
    Get security headers for HTTP responses.
    
    Returns:
        Dictionary of security headers.
    """
    return SECURITY_HEADERS.copy()