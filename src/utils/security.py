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

import re
import html
import bleach
from typing import Any, Dict, List, Optional, Union
from pathlib import Path
import logging

# Configure logging
logger = logging.getLogger(__name__)


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
    
    # List of allowed attributes for each tag
    ALLOWED_ATTRIBUTES = {
        'a': ['href', 'title', 'rel'],
        'img': ['src', 'alt', 'width', 'height'],
        '*': ['class', 'id', 'style']  # Allow class, id, style on any tag
    }
    
    try:
        # Use bleach to sanitize HTML
        cleaned = bleach.clean(
            content,
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRIBUTES,
            strip=True,
            strip_comments=True
        )
        return cleaned
    except Exception as e:
        logger.error(f"Error sanitizing HTML: {e}")
        # Fallback: escape all HTML
        return html.escape(content)


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


def sanitize_sql_input(value: Any) -> str:
    """
    Sanitize input to prevent SQL injection.
    This is a defense-in-depth measure - parameterized queries should still be used.
    
    Args:
        value: The value to sanitize.
        
    Returns:
        Sanitized string safe for SQL queries.
    """
    if value is None:
        return ""
    
    if isinstance(value, (int, float, bool)):
        return str(value)
    
    if not isinstance(value, str):
        value = str(value)
    
    # Remove SQL comments
    value = re.sub(r'--.*?$', '', value, flags=re.MULTILINE)
    value = re.sub(r'/\*.*?\*/', '', value, flags=re.DOTALL)
    
    # Remove SQL keywords that could be used in injection
    sql_keywords = [
        r'\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|EXEC|EXECUTE)\b',
        r'\b(UNION|JOIN|WHERE|FROM|GROUP BY|HAVING|ORDER BY)\b',
        r'\b(OR\s+1=1|AND\s+1=1|OR\s+\"\"=\"\")\b',
        r'[;]',  # Remove all semicolons
        r'--.*?$',  # Remove SQL comments (already handled above but included for completeness)
        r'/\*.*?\*/',  # Remove multi-line comments
        r'\b(DROP\s+TABLE|DROP\s+DATABASE)\b',
        r'\b(LOAD_FILE|INTO\s+OUTFILE|INTO\s+DUMPFILE)\b'
    ]
    
    for pattern in sql_keywords:
        value = re.sub(pattern, '', value, flags=re.IGNORECASE)
    
    # Remove extra whitespace
    value = ' '.join(value.split())
    
    return value


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


def safe_path_join(base_path: Union[str, Path], *parts: str) -> Path:
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
    
    # Remove javascript: and data: schemes
    if url.lower().startswith(('javascript:', 'data:', 'vbscript:', 'file:')):
        return ""
    
    # Remove any null bytes
    url = url.replace('\x00', '')
    
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
    
    # Remove SQL-like patterns
    query = sanitize_sql_input(query)
    
    # Remove potential XSS patterns
    query = escape_html(query)
    
    # Remove control characters
    query = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', query)
    
    return query.strip()


def sanitize_dict_input(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively sanitize dictionary input to prevent injection attacks.
    
    Args:
        data: The dictionary to sanitize.
        
    Returns:
        Sanitized dictionary.
    """
    if not isinstance(data, dict):
        return data
    
    sanitized = {}
    for key, value in data.items():
        # Sanitize the key
        if not isinstance(key, str):
            continue
        sanitized_key = sanitize_sql_input(key)
        
        # Sanitize the value based on its type
        if isinstance(value, str):
            sanitized_value = sanitize_sql_input(value)
        elif isinstance(value, dict):
            sanitized_value = sanitize_dict_input(value)
        elif isinstance(value, list):
            sanitized_value = [
                sanitize_sql_input(item) if isinstance(item, str) else item
                for item in value
            ]
        else:
            sanitized_value = value
        
        sanitized[sanitized_key] = sanitized_value
    
    return sanitized


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
    try:
        import bcrypt
        # Generate salt and hash the password
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')
    except ImportError:
        logger.warning("bcrypt not available, using fallback hashing")
        # Fallback: use SHA-256 with salt (less secure)
        import hashlib
        import secrets
        salt = secrets.token_hex(16)
        return hashlib.sha256((password + salt).encode('utf-8')).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    """
    Verify a password against its hash.
    
    Args:
        password: The password to verify.
        hashed: The hashed password to verify against.
        
    Returns:
        True if the password matches, False otherwise.
    """
    try:
        import bcrypt
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    except ImportError:
        logger.warning("bcrypt not available, using fallback verification")
        # Fallback: use SHA-256 with salt
        import hashlib
        # Extract salt from the hash (last 32 characters)
        salt = hashed[-32:]
        expected_hash = hashed[:-32]
        actual_hash = hashlib.sha256((password + salt).encode('utf-8')).hexdigest()
        return actual_hash == expected_hash


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


def get_security_headers() -> Dict[str, str]:
    """
    Get security headers for HTTP responses.
    
    Returns:
        Dictionary of security headers.
    """
    return SECURITY_HEADERS.copy()