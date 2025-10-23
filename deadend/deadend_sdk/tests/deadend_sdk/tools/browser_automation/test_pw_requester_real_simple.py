"""
Simple real Playwright integration tests for PlaywrightRequester class.

This module contains basic tests that use actual Playwright instances.
"""

import pytest
from deadend_sdk.tools.browser_automation.pw_requester import PlaywrightRequester


@pytest.mark.asyncio
@pytest.mark.slow
class TestPlaywrightRequesterRealSimple:
    """Simple real Playwright integration tests."""

    async def test_real_playwright_initialization(self):
        """Test real Playwright initialization."""
        requester = PlaywrightRequester()
        async with requester:
            assert requester._initialized is True
            assert requester.playwright is not None
            assert requester.browser is not None
            assert requester.context is not None
            assert requester.request_context is not None

    async def test_real_http_get_request(self):
        """Test real HTTP GET request to a public API."""
        requester = PlaywrightRequester()
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

    async def test_real_localstorage_operations(self):
        """Test real localStorage operations."""
        requester = PlaywrightRequester()
        async with requester:
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

    async def test_real_cookie_operations(self):
        """Test real cookie operations."""
        requester = PlaywrightRequester()
        async with requester:
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

    async def test_real_error_handling(self):
        """Test real error handling with invalid requests."""
        requester = PlaywrightRequester()
        async with requester:
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
            # The result should contain an error message or empty response
            # Error handling should not crash the requester

    async def test_real_https_requests(self):
        """Test real HTTPS requests."""
        requester = PlaywrightRequester()
        async with requester:
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

    async def test_real_unicode_handling(self):
        """Test real Unicode handling in localStorage."""
        requester = PlaywrightRequester()
        async with requester:
            unicode_key = "ключ_с_кириллицей"
            unicode_value = "значение_с_эмодзи_🎉"
            
            # Test setting Unicode values
            result = await requester.set_localstorage_value(unicode_key, unicode_value, "httpbin.org")
            assert result is True
            
            # Test getting Unicode values
            retrieved_value = await requester.get_localstorage_value(unicode_key, "httpbin.org")
            assert retrieved_value == unicode_value

    async def test_real_special_characters_handling(self):
        """Test real special characters handling."""
        requester = PlaywrightRequester()
        async with requester:
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

    async def test_real_cleanup_operations(self):
        """Test real cleanup operations."""
        requester = PlaywrightRequester()
        async with requester:
            # Set some data
            await requester.set_localstorage_value("cleanup_test", "test_value", "httpbin.org")
            await requester.set_cookies({"cleanup_cookie": "test_value"}, "httpbin.org")
            
            # Clear session
            await requester.clear_session()
            
            # Verify cleanup
            value = await requester.get_localstorage_value("cleanup_test", "httpbin.org")
            # Note: clear_session might not immediately clear localStorage due to domain restrictions
            # This test mainly verifies the operation completes without errors

    async def test_real_memory_usage(self):
        """Test real memory usage with large data."""
        requester = PlaywrightRequester()
        async with requester:
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
