"""
Unit tests for extract_host_port functionality.
"""
import pytest
from deadend_agent.tools.browser_automation.http_parser import extract_host_port


class TestExtractHostPort:
    """Tests for extract_host_port function."""

    def test_http_url_with_port(self):
        """HTTP URL with port should extract host and port correctly."""
        host, port = extract_host_port("http://localhost:3000")
        assert host == "localhost"
        assert port == 3000

    def test_https_url_with_port(self):
        """HTTPS URL with port should extract host and port correctly."""
        host, port = extract_host_port("https://localhost:3000")
        assert host == "localhost"
        assert port == 3000

    def test_host_with_port_no_protocol(self):
        """Host:port without protocol should extract correctly."""
        host, port = extract_host_port("localhost:3000")
        assert host == "localhost"
        assert port == 3000

    def test_http_url_with_custom_port(self):
        """HTTP URL with custom port should extract correctly."""
        host, port = extract_host_port("http://example.com:8080")
        assert host == "example.com"
        assert port == 8080

    def test_https_url_with_standard_port(self):
        """HTTPS URL with standard port 443 should extract correctly."""
        host, port = extract_host_port("https://example.com:443")
        assert host == "example.com"
        assert port == 443

    def test_http_url_no_port(self):
        """HTTP URL without port should default to 80."""
        host, port = extract_host_port("http://example.com")
        assert host == "example.com"
        assert port == 80

    def test_https_url_no_port(self):
        """HTTPS URL without port should default to 443."""
        host, port = extract_host_port("https://example.com")
        assert host == "example.com"
        assert port == 443

    def test_bare_hostname(self):
        """Bare hostname without protocol should default to port 80."""
        host, port = extract_host_port("example.com")
        assert host == "example.com"
        assert port == 80

    def test_bare_localhost(self):
        """Bare localhost without port should default to port 80."""
        host, port = extract_host_port("localhost")
        assert host == "localhost"
        assert port == 80

    def test_ip_address_with_port(self):
        """IP address with port should extract correctly."""
        host, port = extract_host_port("127.0.0.1:8000")
        assert host == "127.0.0.1"
        assert port == 8000

    def test_http_ip_address_with_port(self):
        """HTTP URL with IP address and port should extract correctly."""
        host, port = extract_host_port("http://127.0.0.1:8000")
        assert host == "127.0.0.1"
        assert port == 8000

    def test_url_with_path_ignored(self):
        """URL with path should ignore the path and extract host:port."""
        host, port = extract_host_port("http://example.com:8080/api/v1")
        assert host == "example.com"
        assert port == 8080

    def test_url_with_query_ignored(self):
        """URL with query params should ignore them and extract host:port."""
        host, port = extract_host_port("http://example.com:8080?param=value")
        assert host == "example.com"
        assert port == 8080

    def test_url_reconstruction_no_duplicate_protocol(self):
        """
        Test that extract_host_port prevents protocol duplication in URL construction.
        This is the bug we're fixing: http://http://localhost:3000 should not happen.
        """
        # Input with protocol
        host, port = extract_host_port("http://localhost:3000")
        # Reconstruct URL (simulating pw_requester.py behavior)
        reconstructed_url = f"http://{host}:{port}/path"

        # Should NOT have duplicate protocol
        assert reconstructed_url == "http://localhost:3000/path"
        assert "http://http://" not in reconstructed_url

    def test_https_url_reconstruction_no_duplicate_protocol(self):
        """Test HTTPS URL reconstruction doesn't duplicate protocol."""
        host, port = extract_host_port("https://example.com:443")
        reconstructed_url = f"https://{host}:{port}/api"

        assert reconstructed_url == "https://example.com:443/api"
        assert "https://https://" not in reconstructed_url
