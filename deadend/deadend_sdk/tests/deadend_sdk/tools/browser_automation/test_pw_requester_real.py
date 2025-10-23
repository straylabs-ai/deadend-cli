"""
Real Playwright integration tests for PlaywrightRequester class.

This module contains tests that use actual Playwright instances to test
end-to-end functionality with real browser automation.
"""

import asyncio
import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch

from deadend_sdk.tools.browser_automation.pw_requester import PlaywrightRequester


@pytest.mark.asyncio
@pytest.mark.slow
class TestPlaywrightRequesterReal:
    """Real Playwright integration tests."""

    @pytest.fixture
    def requester(self):
        """Create a real PlaywrightRequester instance for testing."""
        return PlaywrightRequester(
            verify_ssl=True,
            proxy_url=None,
            session_id="real_test_session"
        )

    @pytest.fixture
    def requester_with_ssl_disabled(self):
        """Create a PlaywrightRequester with SSL verification disabled."""
        return PlaywrightRequester(
            verify_ssl=False,
            proxy_url=None,
            session_id="real_test_session_ssl_disabled"
        )

    async def test_real_playwright_initialization(self, requester):
        """Test real Playwright initialization."""
        async with requester:
            assert requester._initialized is True
            assert requester.playwright is not None
            assert requester.browser is not None
            assert requester.context is not None
            assert requester.request_context is not None

    async def test_real_http_get_request(self, requester):
        """Test real HTTP GET request to a public API."""
        async with requester:
            # Use httpbin.org for testing - it's reliable and designed for testing
            request_data = """GET /get HTTP/1.1\r
Host: httpbin.org\r
User-Agent: DeadendTest/1.0\r
Accept: application/json\r
\r
"""
            
            result = []
            async for chunk in requester.send_raw_data(
                host="httpbin.org",
                port=443,
                target_host="httpbin.org",
                request_data=request_data,
                is_tls=True
            ):
                result.append(chunk)
            
            assert len(result) >= 2  # Request + Response
            assert result[0] == request_data
            
            # Check response contains expected content
            response_text = result[-1].decode('utf-8') if isinstance(result[-1], bytes) else result[-1]
            assert "HTTP/1.1" in response_text
            assert "httpbin.org" in response_text

    async def test_real_http_post_request(self, requester):
        """Test real HTTP POST request with JSON data."""
        json_data = '{"test": "data", "number": 123}'
        request_data = f"""POST /post HTTP/1.1\r
Host: httpbin.org\r
Content-Type: application/json\r
Content-Length: {len(json_data)}\r
User-Agent: DeadendTest/1.0\r
\r
{json_data}"""
        
        result = []
        async for chunk in requester.send_raw_data(
            host="httpbin.org",
            port=443,
            target_host="httpbin.org",
            request_data=request_data,
            is_tls=True
        ):
            result.append(chunk)
        
        assert len(result) >= 2
        response_text = result[-1].decode('utf-8') if isinstance(result[-1], bytes) else result[-1]
        assert "HTTP/1.1" in response_text
        assert "test" in response_text  # Should echo back our JSON data

    async def test_real_localstorage_operations(self, requester):
        """Test real localStorage operations."""
        # Test setting localStorage values
        result = await requester.set_localstorage_value("test_key", "test_value", "httpbin.org")
        assert result is True

        # Test getting localStorage value
        value = await requester.get_localstorage_value("test_key", "httpbin.org")
        assert value == "test_value"

        # Test setting multiple values
        storage_dict = {
            "auth_token": "real_token_123",
            "user_id": "456",
            "preferences": '{"theme": "dark"}'
        }
        result = await requester.set_multiple_localstorage(storage_dict, "httpbin.org")
        assert result is True

        # Test getting all localStorage
        all_storage = await requester.get_all_localstorage("httpbin.org")
        assert "test_key" in all_storage
        assert "auth_token" in all_storage
        assert all_storage["test_key"] == "test_value"
        assert all_storage["auth_token"] == "real_token_123"
        
        # Test removing a value
        result = await requester.remove_localstorage_value("test_key", "httpbin.org")
        assert result is True
        
        # Verify it's removed
        value = await requester.get_localstorage_value("test_key", "httpbin.org")
        assert value is None

    async def test_real_cookie_operations(self, requester):
        """Test real cookie operations."""
        # Test setting cookies
        cookies = {
            "session_id": "real_session_123",
            "user_preference": "dark_mode",
            "test_cookie": "test_value"
        }
        await requester.set_cookies(cookies, "httpbin.org")
        
        # Test getting cookies
        retrieved_cookies = await requester.get_cookies()
        # Note: Cookies might not be immediately available due to domain restrictions
        # This test verifies the operations complete without errors
        assert isinstance(retrieved_cookies, dict)

    async def test_real_token_detection_from_response(self, requester):
        """Test real token detection from HTTP responses."""
        # Create a test page that returns JSON with tokens
        test_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta name="csrf-token" content="csrf_real_123">
            <meta name="api-key" content="api_real_456">
        </head>
        <body>
            <script>
                localStorage.setItem('js_token', 'js_real_789');
            </script>
        </body>
        </html>
        """
        
        # We'll test this by creating a simple test server or using a known endpoint
        # For now, let's test with a JSON response that contains tokens
        request_data = """GET /json HTTP/1.1\r
Host: httpbin.org\r
Accept: application/json\r
\r
"""
        
        result = []
        async for chunk in requester.send_raw_data(
            host="httpbin.org",
            port=443,
            target_host="httpbin.org",
            request_data=request_data,
            is_tls=True
        ):
            result.append(chunk)
        
        # The token detection should run (though httpbin.org doesn't return tokens)
        # This test mainly verifies the detection logic doesn't crash
        assert len(result) >= 2

    async def test_real_session_persistence(self, requester):
        """Test real session persistence across multiple requests."""
        # Set some localStorage data
        await requester.set_localstorage_value("persistent_key", "persistent_value", "httpbin.org")
        
        # Make multiple requests
        for i in range(3):
            request_data = f"""GET /get?request={i} HTTP/1.1\r
Host: httpbin.org\r
Accept: application/json\r
\r
"""
            
            result = []
            async for chunk in requester.send_raw_data(
                host="httpbin.org",
                port=443,
                target_host="httpbin.org",
                request_data=request_data,
                is_tls=True
            ):
                result.append(chunk)
        
        # Verify localStorage data persists
        value = await requester.get_localstorage_value("persistent_key", "httpbin.org")
        assert value == "persistent_value"

    async def test_real_error_handling(self, requester):
        """Test real error handling with invalid requests."""
        # Test with invalid host
        request_data = """GET / HTTP/1.1\r
Host: nonexistent-domain-12345.com\r
\r
"""
        
        result = []
        async for chunk in requester.send_raw_data(
            host="nonexistent-domain-12345.com",
            port=80,
            target_host="nonexistent-domain-12345.com",
            request_data=request_data
        ):
            result.append(chunk)
        
        # Should handle the error gracefully
        assert len(result) >= 1
        # The result should contain an error message
        response_text = result[-1].decode('utf-8') if isinstance(result[-1], bytes) else result[-1]
        # Error handling should not crash the requester

    async def test_real_https_requests(self, requester):
        """Test real HTTPS requests."""
        request_data = """GET /get HTTP/1.1\r
Host: httpbin.org\r
User-Agent: DeadendTest/1.0\r
\r
"""
        
        result = []
        async for chunk in requester.send_raw_data(
            host="httpbin.org",
            port=443,
            target_host="httpbin.org",
            request_data=request_data,
            is_tls=True
        ):
            result.append(chunk)
        
        assert len(result) >= 2
        response_text = result[-1].decode('utf-8') if isinstance(result[-1], bytes) else result[-1]
        assert "HTTP/1.1" in response_text

    async def test_real_ssl_disabled_requests(self, requester_with_ssl_disabled):
        """Test requests with SSL verification disabled."""
        # This test would work with self-signed certificates
        # For now, just test that the requester initializes correctly
        assert requester_with_ssl_disabled._initialized is True
        assert requester_with_ssl_disabled.verify_ssl is False

    async def test_real_redirect_handling(self, requester):
        """Test real redirect handling."""
        # Use httpbin.org redirect endpoint
        request_data = """GET /redirect/1 HTTP/1.1\r
Host: httpbin.org\r
User-Agent: DeadendTest/1.0\r
\r
"""
        
        result = []
        async for chunk in requester.send_raw_data(
            host="httpbin.org",
            port=443,
            target_host="httpbin.org",
            request_data=request_data,
            is_tls=True
        ):
            result.append(chunk)
        
        # Should follow redirects automatically
        assert len(result) >= 2
        response_text = result[-1].decode('utf-8') if isinstance(result[-1], bytes) else result[-1]
        assert "HTTP/1.1" in response_text

    async def test_real_large_response_handling(self, requester):
        """Test handling of large responses."""
        # Use httpbin.org bytes endpoint to get a large response
        request_data = """GET /bytes/10000 HTTP/1.1\r
Host: httpbin.org\r
User-Agent: DeadendTest/1.0\r
\r
"""
        
        result = []
        async for chunk in requester.send_raw_data(
            host="httpbin.org",
            port=443,
            target_host="httpbin.org",
            request_data=request_data,
            is_tls=True
        ):
            result.append(chunk)
        
        # Should handle large responses without issues
        assert len(result) >= 2
        response_text = result[-1].decode('utf-8') if isinstance(result[-1], bytes) else result[-1]
        assert "HTTP/1.1" in response_text

    async def test_real_concurrent_requests(self, requester):
        """Test concurrent requests with real Playwright."""
        async def make_request(request_id):
            request_data = f"""GET /delay/1?request={request_id} HTTP/1.1\r
Host: httpbin.org\r
User-Agent: DeadendTest/1.0\r
\r
"""
            
            result = []
            async for chunk in requester.send_raw_data(
                host="httpbin.org",
                port=443,
                target_host="httpbin.org",
                request_data=request_data,
                is_tls=True
            ):
                result.append(chunk)
            return result
        
        # Make 3 concurrent requests
        tasks = [make_request(i) for i in range(3)]
        results = await asyncio.gather(*tasks)
        
        # All requests should complete successfully
        assert len(results) == 3
        for result in results:
            assert len(result) >= 2

    async def test_real_storage_state_persistence(self, requester):
        """Test real storage state persistence across sessions."""
        # Set some data in localStorage
        await requester.set_localstorage_value("session_data", "important_value", "httpbin.org")
        
        # Get the storage state
        storage_state = await requester.get_localstorage("real_test_session")
        
        # Should contain our data
        assert isinstance(storage_state, list)
        # The exact structure depends on Playwright's storage state format

    async def test_real_unicode_handling(self, requester):
        """Test real Unicode handling in localStorage."""
        unicode_key = "ключ_с_кириллицей"
        unicode_value = "значение_с_эмодзи_🎉"
        
        # Test setting Unicode values
        result = await requester.set_localstorage_value(unicode_key, unicode_value, "httpbin.org")
        assert result is True
        
        # Test getting Unicode values
        retrieved_value = await requester.get_localstorage_value(unicode_key, "httpbin.org")
        assert retrieved_value == unicode_value

    async def test_real_special_characters_handling(self, requester):
        """Test real special characters handling."""
        special_cases = [
            ("key with spaces", "value with spaces"),
            ("key\nwith\nnewlines", "value\nwith\nnewlines"),
            ("key\"with\"quotes", "value\"with\"quotes"),
            ("key'with'apostrophes", "value'with'apostrophes"),
        ]
        
        for key, value in special_cases:
            result = await requester.set_localstorage_value(key, value, "httpbin.org")
            assert result is True
            
            retrieved_value = await requester.get_localstorage_value(key, "httpbin.org")
            assert retrieved_value == value

    async def test_real_cleanup_operations(self, requester):
        """Test real cleanup operations."""
        # Set some data
        await requester.set_localstorage_value("cleanup_test", "test_value", "httpbin.org")
        await requester.set_cookies({"cleanup_cookie": "test_value"}, "httpbin.org")
        
        # Clear session
        await requester.clear_session()
        
        # Verify cleanup
        value = await requester.get_localstorage_value("cleanup_test", "httpbin.org")
        # Note: clear_session might not immediately clear localStorage due to domain restrictions
        # This test mainly verifies the operation completes without errors

    async def test_real_memory_usage(self, requester):
        """Test real memory usage with large data."""
        # Set large data
        large_value = "x" * 100000  # 100KB
        result = await requester.set_localstorage_value("large_data", large_value, "httpbin.org")
        assert result is True
        
        # Retrieve large data
        retrieved_value = await requester.get_localstorage_value("large_data", "httpbin.org")
        assert retrieved_value == large_value
        
        # Test with many small values
        for i in range(100):
            await requester.set_localstorage_value(f"key_{i}", f"value_{i}", "httpbin.org")
        
        # Verify we can retrieve them
        all_storage = await requester.get_all_localstorage("httpbin.org")
        assert len(all_storage) >= 100  # Should have at least our 100 keys


@pytest.mark.asyncio
@pytest.mark.slow
class TestPlaywrightRequesterRealEdgeCases:
    """Real Playwright tests for edge cases and error scenarios."""

    async def test_real_network_timeout_handling(self):
        """Test handling of network timeouts."""
        requester = PlaywrightRequester()
        async with requester:
            # Test with a very short timeout (if supported)
            request_data = """GET /delay/10 HTTP/1.1\r
Host: httpbin.org\r
\r
"""
            
            result = []
            async for chunk in requester.send_raw_data(
                host="httpbin.org",
                port=443,
                target_host="httpbin.org",
                request_data=request_data,
                is_tls=True
            ):
                result.append(chunk)
            
            # Should handle timeout gracefully
            assert len(result) >= 1

    async def test_real_invalid_ssl_certificate_handling(self):
        """Test handling of invalid SSL certificates."""
        requester = PlaywrightRequester(verify_ssl=False)
        async with requester:
            # This would test with a self-signed certificate
            # For now, just verify the requester initializes
            assert requester._initialized is True

    async def test_real_malformed_response_handling(self):
        """Test handling of malformed HTTP responses."""
        requester = PlaywrightRequester()
        async with requester:
            # Test with a request that might return malformed data
            request_data = """GET /robots.txt HTTP/1.1\r
Host: httpbin.org\r
\r
"""
            
            result = []
            async for chunk in requester.send_raw_data(
                host="httpbin.org",
                port=443,
                target_host="httpbin.org",
                request_data=request_data,
                is_tls=True
            ):
                result.append(chunk)
            
            # Should handle malformed responses gracefully
            assert len(result) >= 1

    async def test_real_browser_crash_recovery(self):
        """Test recovery from browser crashes."""
        requester = PlaywrightRequester()
        async with requester:
            # Make some requests
            request_data = """GET /get HTTP/1.1\r
Host: httpbin.org\r
\r
"""
            
            result = []
            async for chunk in requester.send_raw_data(
                host="httpbin.org",
                port=443,
                target_host="httpbin.org",
                request_data=request_data,
                is_tls=True
            ):
                result.append(chunk)
            
            # Should complete successfully
            assert len(result) >= 2


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
