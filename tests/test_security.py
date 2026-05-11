"""
Tests for the Open Omniscience security utilities module.

Tests cover:
- Input validation and sanitization
- SQL injection prevention
- XSS prevention
- Path traversal prevention
- URL sanitization
- Email validation
- Search query validation
- Password hashing
- Security headers

Author: Ideotion
"""

import pytest
import sys
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent / "src"))

from utils.security import (
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


class TestSanitizeHtml:
    """Tests for HTML sanitization functions."""

    def test_sanitize_html_removes_script_tags(self):
        """Test that script tags are removed from HTML."""
        html = "<p>Hello</p><script>alert('xss')</script><p>World</p>"
        sanitized = sanitize_html(html)
        assert "<script>" not in sanitized
        assert "</script>" not in sanitized
        assert "<p>Hello</p>" in sanitized
        assert "<p>World</p>" in sanitized

    def test_sanitize_html_removes_event_handlers(self):
        """Test that event handlers are removed from HTML."""
        html = '<img src="test.jpg" onerror="alert(\'xss\')">'
        sanitized = sanitize_html(html)
        assert "onerror" not in sanitized
        assert 'src="test.jpg"' in sanitized

    def test_sanitize_html_removes_javascript_urls(self):
        """Test that javascript: URLs are removed from HTML."""
        html = '<a href="javascript:alert(\'xss\')">Click me</a>'
        sanitized = sanitize_html(html)
        assert "javascript:" not in sanitized
        assert "Click me" in sanitized

    def test_sanitize_html_preserves_safe_tags(self):
        """Test that safe HTML tags are preserved."""
        html = "<p><strong>Bold</strong> and <em>italic</em> text</p>"
        sanitized = sanitize_html(html)
        assert "<p>" in sanitized
        assert "<strong>" in sanitized
        assert "<em>" in sanitized
        assert "Bold" in sanitized
        assert "italic" in sanitized

    def test_sanitize_html_empty_string(self):
        """Test that empty strings are handled correctly."""
        assert sanitize_html("") == ""
        assert sanitize_html(None) is None

    def test_escape_html_special_characters(self):
        """Test that HTML special characters are escaped."""
        text = "<script>alert('xss')</script>"
        escaped = escape_html(text)
        assert "<" not in escaped
        assert ">" not in escaped
        assert "&lt;" in escaped
        assert "&gt;" in escaped


class TestSanitizeSqlInput:
    """Tests for SQL injection prevention."""

    def test_sanitize_sql_input_removes_sql_comments(self):
        """Test that SQL comments are removed."""
        input_text = "test--comment\nSELECT * FROM users"
        sanitized = sanitize_sql_input(input_text)
        assert "--" not in sanitized
        assert "SELECT" not in sanitized

    def test_sanitize_sql_input_removes_sql_keywords(self):
        """Test that SQL keywords are removed."""
        input_text = "test OR 1=1"
        sanitized = sanitize_sql_input(input_text)
        assert "OR 1=1" not in sanitized

    def test_sanitize_sql_input_removes_semicolons(self):
        """Test that semicolons are removed."""
        input_text = "test; DROP TABLE users"
        sanitized = sanitize_sql_input(input_text)
        assert ";" not in sanitized
        assert "DROP" not in sanitized

    def test_sanitize_sql_input_preserves_normal_text(self):
        """Test that normal text is preserved."""
        input_text = "Hello World 123"
        sanitized = sanitize_sql_input(input_text)
        assert sanitized == "Hello World 123"

    def test_sanitize_sql_input_handles_none(self):
        """Test that None is handled correctly."""
        assert sanitize_sql_input(None) == ""

    def test_sanitize_sql_input_handles_numbers(self):
        """Test that numbers are handled correctly."""
        assert sanitize_sql_input(123) == "123"
        assert sanitize_sql_input(12.34) == "12.34"


class TestFilenameValidation:
    """Tests for filename validation and sanitization."""

    def test_validate_filename_rejects_path_traversal(self):
        """Test that path traversal attempts are rejected."""
        with pytest.raises(SecurityError):
            validate_and_sanitize_filename("../test.txt")
        
        with pytest.raises(SecurityError):
            validate_and_sanitize_filename("/etc/passwd")
        
        with pytest.raises(SecurityError):
            validate_and_sanitize_filename("test/../file.txt")

    def test_validate_filename_rejects_dangerous_characters(self):
        """Test that dangerous characters are rejected."""
        dangerous_chars = ['<', '>', ':', '"', '|', '?', '*']
        for char in dangerous_chars:
            with pytest.raises(SecurityError):
                validate_and_sanitize_filename(f"test{char}file.txt")

    def test_validate_filename_accepts_safe_filenames(self):
        """Test that safe filenames are accepted."""
        safe_filenames = [
            "test.txt",
            "my_file.csv",
            "data-backup.json",
            "file with spaces.txt",
            "file_with_underscores.log",
            "file-with-hyphens.db",
            "12345.dat"
        ]
        for filename in safe_filenames:
            result = validate_and_sanitize_filename(filename)
            assert isinstance(result, str)
            assert len(result) > 0

    def test_validate_filename_empty_rejected(self):
        """Test that empty filenames are rejected."""
        with pytest.raises(SecurityError):
            validate_and_sanitize_filename("")
        
        with pytest.raises(SecurityError):
            validate_and_sanitize_filename(None)


class TestSafePathJoin:
    """Tests for safe path joining."""

    def test_safe_path_join_normal_paths(self):
        """Test that normal path joining works."""
        base = "/tmp/base"
        result = safe_path_join(base, "subdir", "file.txt")
        assert result == Path("/tmp/base/subdir/file.txt")

    def test_safe_path_join_rejects_path_traversal(self):
        """Test that path traversal attempts are rejected."""
        base = "/tmp/base"
        
        with pytest.raises(SecurityError):
            safe_path_join(base, "../escape")
        
        with pytest.raises(SecurityError):
            safe_path_join(base, "/absolute/path")
        
        with pytest.raises(SecurityError):
            safe_path_join(base, "subdir", "../escape")

    def test_safe_path_join_rejects_absolute_paths(self):
        """Test that absolute paths in parts are rejected."""
        base = "/tmp/base"
        
        with pytest.raises(SecurityError):
            safe_path_join(base, "/etc/passwd")

    def test_safe_path_join_returns_path_object(self):
        """Test that the result is a Path object."""
        base = "/tmp/base"
        result = safe_path_join(base, "file.txt")
        assert isinstance(result, Path)


class TestUrlSanitization:
    """Tests for URL sanitization."""

    def test_sanitize_url_removes_javascript_scheme(self):
        """Test that javascript: URLs are removed."""
        url = "javascript:alert('xss')"
        sanitized = sanitize_url(url)
        assert sanitized == ""

    def test_sanitize_url_removes_data_scheme(self):
        """Test that data: URLs are removed."""
        url = "data:text/html,<script>alert('xss')</script>"
        sanitized = sanitize_url(url)
        assert sanitized == ""

    def test_sanitize_url_removes_null_bytes(self):
        """Test that null bytes are removed."""
        url = "http://example.com\x00/test"
        sanitized = sanitize_url(url)
        assert "\x00" not in sanitized

    def test_sanitize_url_preserves_normal_urls(self):
        """Test that normal URLs are preserved."""
        urls = [
            "https://example.com/path",
            "http://example.com:8080/path?query=value",
            "ftp://files.example.com/file.txt",
            "/relative/path",
            "relative/path"
        ]
        for url in urls:
            sanitized = sanitize_url(url)
            assert sanitized == url

    def test_sanitize_url_empty_string(self):
        """Test that empty strings are handled correctly."""
        assert sanitize_url("") == ""
        assert sanitize_url(None) is None


class TestEmailValidation:
    """Tests for email validation."""

    def test_validate_email_valid_emails(self):
        """Test that valid emails are accepted."""
        valid_emails = [
            "user@example.com",
            "first.last@sub.domain.com",
            "user+tag@example.co.uk",
            "user123@example.org",
            "user_name@example.net"
        ]
        for email in valid_emails:
            assert validate_email(email) is True

    def test_validate_email_invalid_emails(self):
        """Test that invalid emails are rejected."""
        invalid_emails = [
            "user@example",  # Missing TLD
            "user@.com",     # Missing domain
            "@example.com",  # Missing username
            "user@example..com",  # Double dot
            "user example@example.com",  # Space in username
            "user@example.com.",  # Trailing dot
            "",  # Empty
            None
        ]
        for email in invalid_emails:
            assert validate_email(email) is False


class TestSearchQueryValidation:
    """Tests for search query validation."""

    def test_validate_search_query_normal_queries(self):
        """Test that normal search queries are accepted."""
        queries = [
            "test query",
            "hello world",
            "term1 AND term2",
            "term1 OR term2",
            '"exact phrase"',
            "test*",
            "(term1 OR term2) AND term3"
        ]
        for query in queries:
            result = validate_and_sanitize_search_query(query)
            assert isinstance(result, str)
            assert len(result) > 0

    def test_validate_search_query_rejects_long_queries(self):
        """Test that queries exceeding max length are rejected."""
        long_query = "a" * 501  # Exceeds default max_length of 500
        with pytest.raises(SecurityError):
            validate_and_sanitize_search_query(long_query)

    def test_validate_search_query_sanitizes_sql_injection(self):
        """Test that SQL injection attempts are sanitized."""
        query = "test'; DROP TABLE users;--"
        result = validate_and_sanitize_search_query(query)
        assert "DROP" not in result
        assert "--" not in result
        # Note: Single quotes are HTML-escaped to &#x27; which contains a semicolon
        # The original SQL injection semicolons are removed, but HTML entities may contain semicolons
        assert "TABLE" in result  # The word TABLE should remain
        assert "test" in result  # The word test should remain

    def test_validate_search_query_empty_query(self):
        """Test that empty queries are handled correctly."""
        assert validate_and_sanitize_search_query("") == ""
        assert validate_and_sanitize_search_query(None) is None


class TestDictSanitization:
    """Tests for dictionary input sanitization."""

    def test_sanitize_dict_input_normal_dict(self):
        """Test that normal dictionaries are sanitized correctly."""
        data = {
            "name": "test",
            "value": "hello world",
            "count": 42
        }
        result = sanitize_dict_input(data)
        assert result["name"] == "test"
        assert result["value"] == "hello world"
        assert result["count"] == 42

    def test_sanitize_dict_input_nested_dicts(self):
        """Test that nested dictionaries are sanitized recursively."""
        data = {
            "user": {
                "name": "test",
                "email": "user@example.com"
            },
            "settings": {
                "theme": "dark"
            }
        }
        result = sanitize_dict_input(data)
        assert result["user"]["name"] == "test"
        assert result["user"]["email"] == "user@example.com"
        assert result["settings"]["theme"] == "dark"

    def test_sanitize_dict_input_lists(self):
        """Test that lists within dictionaries are sanitized."""
        data = {
            "tags": ["tag1", "tag2", "tag3"]
        }
        result = sanitize_dict_input(data)
        assert result["tags"] == ["tag1", "tag2", "tag3"]

    def test_sanitize_dict_input_sql_injection(self):
        """Test that SQL injection in dictionary values is sanitized."""
        data = {
            "query": "test'; DROP TABLE users;--"
        }
        result = sanitize_dict_input(data)
        assert "DROP" not in result["query"]
        assert ";" not in result["query"]


class TestTokenGeneration:
    """Tests for secure token generation."""

    def test_generate_secure_token_returns_hex_string(self):
        """Test that generated tokens are hexadecimal strings."""
        token = generate_secure_token()
        assert isinstance(token, str)
        # Hex strings should only contain 0-9, a-f
        assert all(c in '0123456789abcdef' for c in token)

    def test_generate_secure_token_unique(self):
        """Test that generated tokens are unique."""
        token1 = generate_secure_token()
        token2 = generate_secure_token()
        assert token1 != token2

    def test_generate_secure_token_length(self):
        """Test that generated tokens have the correct length."""
        token = generate_secure_token(16)  # 16 bytes = 32 hex chars
        assert len(token) == 32


class TestPasswordHashing:
    """Tests for password hashing."""

    def test_hash_password_returns_string(self):
        """Test that password hashing returns a string."""
        password = "test_password_123"
        hashed = hash_password(password)
        assert isinstance(hashed, str)
        assert len(hashed) > 0

    def test_hash_password_different_passwords(self):
        """Test that different passwords produce different hashes."""
        hash1 = hash_password("password1")
        hash2 = hash_password("password2")
        assert hash1 != hash2

    def test_verify_password_correct(self):
        """Test that password verification works for correct passwords."""
        password = "test_password_123"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """Test that password verification fails for incorrect passwords."""
        password = "test_password_123"
        wrong_password = "wrong_password_456"
        hashed = hash_password(password)
        assert verify_password(wrong_password, hashed) is False


class TestSecurityHeaders:
    """Tests for security headers."""

    def test_get_security_headers_returns_dict(self):
        """Test that security headers are returned as a dictionary."""
        headers = get_security_headers()
        assert isinstance(headers, dict)
        assert len(headers) > 0

    def test_security_headers_contain_essential_headers(self):
        """Test that essential security headers are included."""
        headers = get_security_headers()
        essential_headers = [
            "X-Content-Type-Options",
            "X-Frame-Options",
            "X-XSS-Protection",
            "Content-Security-Policy",
            "Referrer-Policy",
            "Strict-Transport-Security",
            "Permissions-Policy"
        ]
        for header in essential_headers:
            assert header in headers

    def test_security_headers_are_valid(self):
        """Test that security header values are valid."""
        headers = get_security_headers()
        for header_name, header_value in headers.items():
            assert isinstance(header_name, str)
            assert isinstance(header_value, str)
            assert len(header_value) > 0

    def test_security_headers_copy(self):
        """Test that get_security_headers returns a copy."""
        headers1 = get_security_headers()
        headers2 = get_security_headers()
        # Modify one
        headers1["Test-Header"] = "test"
        # The other should not be affected
        assert "Test-Header" not in headers2


class TestSecurityConstants:
    """Tests for security constants."""

    def test_security_headers_constant_exists(self):
        """Test that SECURITY_HEADERS constant exists."""
        assert hasattr(SECURITY_HEADERS, '__iter__')
        assert len(SECURITY_HEADERS) > 0

    def test_security_error_exception(self):
        """Test that SecurityError is a proper exception."""
        assert issubclass(SecurityError, Exception)
        
        # Test that it can be raised and caught
        with pytest.raises(SecurityError):
            raise SecurityError("Test error")
        
        try:
            raise SecurityError("Test error")
        except SecurityError as e:
            assert str(e) == "Test error"
        except Exception:
            assert False, "Should have caught SecurityError"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])