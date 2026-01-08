"""
Unit tests for HTTP request auto-correction functionality.
"""
import pytest
from deadend_agent.tools.browser_automation.http_parser import (
    autocorrect_http_request,
    _fix_line_endings,
    _fix_request_line,
    _fix_header_format,
    _derive_host_from_target,
    _reconstruct_request,
)


class TestFixLineEndings:
    """Tests for _fix_line_endings helper function."""

    def test_unix_line_endings_converted(self):
        """Unix \\n should be converted to \\r\\n."""
        malformed = "GET / HTTP/1.1\nHost: example.com\n\n"
        corrected, was_fixed = _fix_line_endings(malformed)
        assert "\r\n" in corrected
        assert "\n\n" not in corrected
        assert was_fixed is True

    def test_crlf_preserved(self):
        """Proper \\r\\n should remain unchanged."""
        valid = "GET / HTTP/1.1\r\nHost: example.com\r\n\r\n"
        corrected, was_fixed = _fix_line_endings(valid)
        assert corrected == valid
        assert was_fixed is False

    def test_mixed_line_endings(self):
        """Mixed line endings should all be normalized to \\r\\n."""
        mixed = "GET / HTTP/1.1\r\nHost: example.com\nContent-Type: text/html\r\n\r\n"
        corrected, was_fixed = _fix_line_endings(mixed)
        assert was_fixed is True
        assert corrected.count('\r\n') >= 4

    def test_old_mac_line_endings(self):
        """Old Mac-style \\r should be converted to \\r\\n."""
        old_mac = "GET / HTTP/1.1\rHost: example.com\r\r"
        corrected, was_fixed = _fix_line_endings(old_mac)
        assert "\r\n" in corrected
        assert was_fixed is True


class TestFixRequestLine:
    """Tests for _fix_request_line helper function."""

    def test_lowercase_method_uppercased(self):
        """Lowercase methods should be uppercased."""
        fixed, corrections = _fix_request_line("get / HTTP/1.1")
        assert fixed == "GET / HTTP/1.1"
        assert any("Uppercased" in c for c in corrections)

    def test_missing_http_version_added(self):
        """Missing HTTP version should be added."""
        fixed, corrections = _fix_request_line("GET /path")
        assert fixed == "GET /path HTTP/1.1"
        assert any("HTTP version" in c for c in corrections)

    def test_missing_path_defaults_to_root(self):
        """Missing path should default to /."""
        fixed, corrections = _fix_request_line("GET HTTP/1.1")
        assert "GET /" in fixed
        assert "HTTP/1.1" in fixed

    def test_empty_request_line_defaults(self):
        """Empty request line should default to GET / HTTP/1.1."""
        fixed, corrections = _fix_request_line("")
        assert fixed == "GET / HTTP/1.1"
        assert len(corrections) > 0

    def test_valid_request_line_unchanged(self):
        """Valid request line should remain unchanged."""
        fixed, corrections = _fix_request_line("POST /api/test HTTP/1.1")
        assert fixed == "POST /api/test HTTP/1.1"
        assert len(corrections) == 0

    def test_path_only_gets_method(self):
        """Request starting with path gets GET method added."""
        fixed, corrections = _fix_request_line("/path/to/resource")
        assert "GET" in fixed
        assert "/path/to/resource" in fixed


class TestFixHeaderFormat:
    """Tests for _fix_header_format helper function."""

    def test_extra_whitespace_trimmed(self):
        """Extra whitespace in headers should be trimmed."""
        fixed, was_fixed = _fix_header_format("  Content-Type  :   application/json  ")
        assert fixed == "Content-Type: application/json"
        assert was_fixed is True

    def test_valid_header_unchanged(self):
        """Valid header should remain unchanged."""
        fixed, was_fixed = _fix_header_format("Content-Type: application/json")
        assert fixed == "Content-Type: application/json"
        assert was_fixed is False

    def test_header_without_colon(self):
        """Header without colon should be returned as-is."""
        fixed, was_fixed = _fix_header_format("Invalid header line")
        assert fixed == "Invalid header line"
        assert was_fixed is False


class TestDeriveHostFromTarget:
    """Tests for _derive_host_from_target helper function."""

    def test_http_url(self):
        """HTTP URL should extract host correctly."""
        host = _derive_host_from_target("http://example.com")
        assert host == "example.com"

    def test_https_url_with_port(self):
        """HTTPS URL with port should preserve port."""
        host = _derive_host_from_target("https://example.com:8443")
        assert host == "example.com:8443"

    def test_url_with_path(self):
        """URL with path should only extract host."""
        host = _derive_host_from_target("http://example.com:8080/api/v1")
        assert host == "example.com:8080"

    def test_bare_host(self):
        """Bare hostname should be returned as-is."""
        host = _derive_host_from_target("example.com")
        assert host == "example.com"


class TestReconstructRequest:
    """Tests for _reconstruct_request helper function."""

    def test_basic_reconstruction(self):
        """Basic request should be reconstructed correctly."""
        result = _reconstruct_request(
            request_line="GET / HTTP/1.1",
            headers=["Host: example.com"],
            body=""
        )
        assert result == "GET / HTTP/1.1\r\nHost: example.com\r\n\r\n"

    def test_with_body(self):
        """Request with body should have proper separator."""
        result = _reconstruct_request(
            request_line="POST /api HTTP/1.1",
            headers=["Host: example.com", "Content-Type: application/json"],
            body='{"key": "value"}'
        )
        assert "POST /api HTTP/1.1\r\n" in result
        assert "Host: example.com\r\n" in result
        assert '\r\n\r\n{"key": "value"}' in result
        # Body should be at the end without trailing CRLF added
        assert result.endswith('{"key": "value"}')


class TestAutocorrectHttpRequest:
    """Tests for the main autocorrect_http_request function."""

    def test_fix_unix_line_endings(self):
        """Test conversion of \\n to \\r\\n."""
        malformed = "GET / HTTP/1.1\nHost: example.com\n\n"
        corrected, corrections = autocorrect_http_request(malformed)
        assert "\r\n" in corrected
        assert "\n\n" not in corrected
        assert any("line endings" in c.lower() for c in corrections)

    def test_add_missing_host_header(self):
        """Test addition of Host header from target."""
        malformed = "GET / HTTP/1.1\r\n\r\n"
        corrected, corrections = autocorrect_http_request(
            malformed,
            target_host="http://example.com:8080"
        )
        assert "Host: example.com:8080" in corrected
        assert any("Host header" in c for c in corrections)

    def test_fix_missing_http_version(self):
        """Test addition of HTTP version."""
        malformed = "GET /path\r\nHost: example.com\r\n\r\n"
        corrected, corrections = autocorrect_http_request(malformed)
        assert "HTTP/1.1" in corrected
        assert any("HTTP version" in c for c in corrections)

    def test_uppercase_method(self):
        """Test method normalization to uppercase."""
        malformed = "get / HTTP/1.1\r\nHost: example.com\r\n\r\n"
        corrected, corrections = autocorrect_http_request(malformed)
        assert corrected.startswith("GET ")
        assert any("Uppercased" in c for c in corrections)

    def test_fix_body_separator(self):
        """Test proper header-body separation."""
        # Request with body but no proper separator
        malformed = "POST / HTTP/1.1\r\nHost: example.com\r\nContent-Type: text/plain\r\nbody content"
        corrected, corrections = autocorrect_http_request(malformed)
        # Should have proper \r\n\r\n separator
        assert "\r\n\r\n" in corrected

    def test_preserve_valid_request(self):
        """Test that valid requests are unchanged."""
        valid = "GET / HTTP/1.1\r\nHost: example.com\r\n\r\n"
        corrected, corrections = autocorrect_http_request(valid)
        assert corrected == valid
        assert len(corrections) == 0

    def test_empty_request_raises_error(self):
        """Test that empty requests raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            autocorrect_http_request("")
        assert "Empty request" in str(exc_info.value)

    def test_whitespace_only_raises_error(self):
        """Test that whitespace-only requests raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            autocorrect_http_request("   \n  \t  ")
        assert "Empty request" in str(exc_info.value)

    def test_complex_malformed_request(self):
        """Test correction of request with multiple issues."""
        malformed = "post /api/test\nHost:example.com\n\n{\"data\": 1}"
        corrected, corrections = autocorrect_http_request(
            malformed,
            target_host="http://example.com"
        )
        # Should fix multiple issues
        assert corrected.startswith("POST /api/test HTTP/1.1\r\n")
        assert "Host: example.com\r\n" in corrected
        assert '{"data": 1}' in corrected
        assert len(corrections) >= 2  # At least line endings and method uppercasing

    def test_post_with_body_preserved(self):
        """Test that POST request body is preserved."""
        malformed = "POST /api HTTP/1.1\nHost: example.com\nContent-Type: application/json\n\n{\"key\": \"value\"}"
        corrected, corrections = autocorrect_http_request(malformed)
        assert '{"key": "value"}' in corrected
        assert "\r\n\r\n" in corrected

    def test_multiple_headers_preserved(self):
        """Test that multiple headers are preserved in order."""
        malformed = "GET / HTTP/1.1\nHost: example.com\nAccept: */*\nUser-Agent: Test\n\n"
        corrected, corrections = autocorrect_http_request(malformed)
        assert "Host: example.com" in corrected
        assert "Accept: */*" in corrected
        assert "User-Agent: Test" in corrected

    def test_query_string_preserved(self):
        """Test that query strings are preserved."""
        malformed = "GET /search?q=test&page=1 HTTP/1.1\nHost: example.com\n\n"
        corrected, corrections = autocorrect_http_request(malformed)
        assert "/search?q=test&page=1" in corrected

    def test_custom_http_methods(self):
        """Test that custom HTTP methods are preserved."""
        malformed = "PROPFIND /resource HTTP/1.1\nHost: example.com\n\n"
        corrected, corrections = autocorrect_http_request(malformed)
        assert "PROPFIND" in corrected
