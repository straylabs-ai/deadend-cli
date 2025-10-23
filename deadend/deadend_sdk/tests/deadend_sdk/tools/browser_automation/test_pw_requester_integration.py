"""
Integration tests for PlaywrightRequester class.

This module contains comprehensive integration tests focusing on storage functions
and edge cases that might cause issues in production.
"""

import asyncio
import json
import pytest
import tempfile
from unittest.mock import AsyncMock, patch

from deadend_sdk.tools.browser_automation.pw_requester import PlaywrightRequester


class TestPlaywrightRequesterStorageIntegration:
    """Integration tests focusing on storage functions and potential issues."""

    @pytest.fixture
    def requester(self):
        """Create a PlaywrightRequester instance for testing."""
        return PlaywrightRequester(
            verify_ssl=True,
            proxy_url=None,
            session_id="integration_test_session"
        )

    @pytest.fixture
    def mock_context_with_pages(self):
        """Create a mock context with multiple pages for testing."""
        mock_page1 = AsyncMock()
        mock_page1.evaluate = AsyncMock()
        mock_page1.goto = AsyncMock()
        mock_page1.close = AsyncMock()
        
        mock_page2 = AsyncMock()
        mock_page2.evaluate = AsyncMock()
        mock_page2.goto = AsyncMock()
        mock_page2.close = AsyncMock()
        
        mock_context = AsyncMock()
        mock_context.pages = [mock_page1, mock_page2]
        mock_context.new_page = AsyncMock(side_effect=[mock_page1, mock_page2])
        mock_context.cookies = AsyncMock(return_value=[])
        mock_context.add_cookies = AsyncMock()
        mock_context.clear_cookies = AsyncMock()
        mock_context.clear_permissions = AsyncMock()
        mock_context.storage_state = AsyncMock()
        
        mock_request_context = AsyncMock()
        mock_context.request = mock_request_context
        
        return mock_context, [mock_page1, mock_page2]

    @pytest.fixture
    def temp_session_dir(self):
        """Create a temporary directory for session storage testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield temp_dir

    @pytest.mark.asyncio
    async def test_localstorage_value_operations_edge_cases(self, requester, mock_context_with_pages):
        """Test localStorage operations with edge cases that might cause issues."""
        mock_context, mock_pages = mock_context_with_pages
        requester.context = mock_context
        requester._initialized = True
        
        # Test 1: Empty key
        result = await requester.set_localstorage_value("", "value123", "example.com")
        assert result is True
        mock_pages[0].evaluate.assert_called_with("localStorage.setItem('', 'value123')")
        
        # Test 2: Special characters in key/value
        special_key = "key with spaces & symbols!@#$%"
        special_value = "value with\nnewlines\tand\ttabs"
        result = await requester.set_localstorage_value(special_key, special_value, "example.com")
        assert result is True
        
        # Test 3: Very long values
        long_value = "x" * 10000  # 10KB value
        result = await requester.set_localstorage_value("long_key", long_value, "example.com")
        assert result is True
        
        # Test 4: Unicode characters
        unicode_key = "ключ_с_кириллицей"
        unicode_value = "значение_с_эмодзи_🎉"
        result = await requester.set_localstorage_value(unicode_key, unicode_value, "example.com")
        assert result is True

    @pytest.mark.asyncio
    async def test_localstorage_domain_handling_edge_cases(self, requester, mock_context_with_pages):
        """Test localStorage domain handling with various domain formats."""
        mock_context, mock_pages = mock_context_with_pages
        requester.context = mock_context
        requester._initialized = True
        
        test_cases = [
            # (domain, expected_protocol)
            ("example.com", "http://example.com"),
            ("https://example.com", "https://example.com"),
            ("http://example.com", "http://example.com"),
            ("subdomain.example.com", "http://subdomain.example.com"),
            ("localhost", "http://localhost"),
            ("127.0.0.1", "http://127.0.0.1"),
            ("[::1]", "http://[::1]"),  # IPv6
        ]
        
        for domain, expected_url in test_cases:
            await requester.set_localstorage_value("test_key", "test_value", domain)
            mock_pages[0].goto.assert_called_with(expected_url)

    @pytest.mark.asyncio
    async def test_localstorage_error_handling(self, requester, mock_context_with_pages):
        """Test localStorage error handling scenarios."""
        mock_context, mock_pages = mock_context_with_pages
        requester.context = mock_context
        requester._initialized = True
        
        # Test 1: Page.goto failure
        mock_pages[0].goto.side_effect = Exception("Navigation failed")
        result = await requester.set_localstorage_value("key", "value", "example.com")
        assert result is False
        
        # Test 2: Page.evaluate failure
        mock_pages[0].goto.side_effect = None  # Reset
        mock_pages[0].evaluate.side_effect = Exception("JavaScript execution failed")
        result = await requester.set_localstorage_value("key", "value", "example.com")
        assert result is False
        
        # Test 3: Page.close failure
        mock_pages[0].evaluate.side_effect = None  # Reset
        mock_pages[0].close.side_effect = Exception("Page close failed")
        result = await requester.set_localstorage_value("key", "value", "example.com")
        # Should still return True as the main operation succeeded
        assert result is True

    @pytest.mark.asyncio
    async def test_localstorage_without_context(self, requester):
        """Test localStorage operations when context is not initialized."""
        requester._initialized = False
        requester.context = None
        
        # All operations should return False/None/{} when not initialized
        assert await requester.set_localstorage_value("key", "value", "example.com") is False
        assert await requester.get_localstorage_value("key", "example.com") is None
        assert await requester.remove_localstorage_value("key", "example.com") is False
        assert await requester.clear_localstorage("example.com") is False
        assert await requester.get_all_localstorage("example.com") == {}
        assert await requester.set_multiple_localstorage({"key": "value"}, "example.com") is False

    @pytest.mark.asyncio
    async def test_localstorage_existing_pages_usage(self, requester, mock_context_with_pages):
        """Test localStorage operations using existing pages instead of creating new ones."""
        mock_context, mock_pages = mock_context_with_pages
        requester.context = mock_context
        requester._initialized = True
        
        # Test without domain - should use existing page
        await requester.set_localstorage_value("key", "value")
        
        # Should not create new page, should use existing one
        mock_context.new_page.assert_not_called()
        mock_pages[0].goto.assert_called_with("data:text/html,<html></html>")
        mock_pages[0].evaluate.assert_called_with("localStorage.setItem('key', 'value')")

    @pytest.mark.asyncio
    async def test_localstorage_empty_pages_context(self, requester):
        """Test localStorage operations when context has no pages."""
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.close = AsyncMock()
        
        mock_context.pages = []  # No existing pages
        mock_context.new_page = AsyncMock(return_value=mock_page)
        
        requester.context = mock_context
        requester._initialized = True
        
        # Should create new page when no pages exist
        await requester.set_localstorage_value("key", "value")
        
        mock_context.new_page.assert_called_once()
        mock_page.goto.assert_called_with("data:text/html,<html></html>")
        mock_page.evaluate.assert_called_with("localStorage.setItem('key', 'value')")

    @pytest.mark.asyncio
    async def test_get_localstorage_session_persistence(self, requester, mock_context_with_pages):
        """Test localStorage session persistence and retrieval."""
        mock_context, mock_pages = mock_context_with_pages
        requester.context = mock_context
        requester._initialized = True
        
        # Mock storage state with complex data
        mock_storage = {
            'origins': [
                {
                    'origin': 'https://example.com',
                    'localStorage': [
                        {'name': 'auth_token', 'value': 'token123'},
                        {'name': 'api_key', 'value': 'key456'},
                        {'name': 'user_preferences', 'value': '{"theme": "dark"}'}
                    ]
                },
                {
                    'origin': 'https://api.example.com',
                    'localStorage': [
                        {'name': 'session_id', 'value': 'sess789'},
                        {'name': 'csrf_token', 'value': 'csrf123'}
                    ]
                }
            ]
        }
        mock_context.storage_state = AsyncMock(return_value=mock_storage)
        
        with patch('anyio.Path.mkdir', new_callable=AsyncMock):
            result = await requester.get_localstorage("test_session")
            
            assert len(result) == 2
            assert result[0]['origin'] == 'https://example.com'
            assert len(result[0]['localStorage']) == 3
            assert result[1]['origin'] == 'https://api.example.com'
            assert len(result[1]['localStorage']) == 2

    @pytest.mark.asyncio
    async def test_token_detection_comprehensive_scenarios(self, requester):
        """Test comprehensive token detection scenarios."""
        requester.set_localstorage_value = AsyncMock()
        
        # Test 1: Complex JSON response with nested tokens
        complex_json = {
            "data": {
                "user": {
                    "access_token": "nested_token_123",
                    "profile": {
                        "refresh_token": "nested_refresh_456"
                    }
                }
            },
            "meta": {
                "api_token": "meta_token_789"
            }
        }
        
        await requester._detect_and_store_tokens(json.dumps(complex_json), "https://api.example.com")
        
        # Should detect nested tokens
        assert requester.set_localstorage_value.call_count >= 3
        
        # Test 2: HTML with multiple token formats
        complex_html = '''
        <html>
            <head>
                <meta name="csrf-token" content="csrf123">
                <meta name="auth-token" content="auth456">
                <meta name="api-key" content="api789">
            </head>
            <body>
                <form>
                    <input type="hidden" name="session_token" value="sess123">
                    <input type="hidden" name="csrf_token" value="csrf456">
                </form>
                <script>
                    window.authToken = "js_token_123";
                    window.apiKey = "js_key_456";
                    var sessionId = "js_sess_789";
                </script>
            </body>
        </html>
        '''
        
        requester.set_localstorage_value.reset_mock()
        await requester._detect_and_store_tokens(complex_html, "https://example.com")
        
        # Should detect tokens in meta tags, hidden inputs, and JS variables
        assert requester.set_localstorage_value.call_count >= 7
        
        # Test 3: URL with encoded parameters
        complex_url = "https://example.com/callback?access_token=token123&session_id=sess456&csrf_token=csrf789&redirect_url=https%3A//other.com"
        
        requester.set_localstorage_value.reset_mock()
        await requester._detect_and_store_tokens("", complex_url)
        
        # Should detect URL parameters
        assert requester.set_localstorage_value.call_count >= 3

    @pytest.mark.asyncio
    async def test_token_detection_error_handling(self, requester):
        """Test token detection error handling."""
        requester.set_localstorage_value = AsyncMock(side_effect=Exception("Storage failed"))
        
        # Should not raise exception even if storage fails
        json_response = '{"access_token": "abc123"}'
        await requester._detect_and_store_tokens(json_response, "https://api.example.com")
        
        # Should handle malformed JSON gracefully
        malformed_json = '{"access_token": "abc123"'  # Missing closing brace
        await requester._detect_and_store_tokens(malformed_json, "https://api.example.com")
        
        # Should handle empty responses
        await requester._detect_and_store_tokens("", "https://api.example.com")

    @pytest.mark.asyncio
    async def test_auth_header_injection_edge_cases(self, requester):
        """Test auth header injection with edge cases."""
        # Test 1: Storage with missing or malformed data
        malformed_storage = {
            "localStorage": [
                {"name": "auth_token", "value": None},  # None value
                {"name": "api_key"},  # Missing value
                {"name": "", "value": "empty_key"},  # Empty name
                {"name": "valid_token", "value": "valid_value"}
            ]
        }
        
        headers = {'Content-Type': 'application/json'}
        result = requester._inject_auth_headers_with_storage(malformed_storage, headers)
        
        # Should only inject valid tokens
        assert 'Authorization' not in result  # None value should be skipped
        assert 'X-API-Key' not in result  # Missing value should be skipped
        assert 'Content-Type' in result
        assert result['Content-Type'] == 'application/json'
        
        # Test 2: Empty storage
        empty_storage = {"localStorage": []}
        result = requester._inject_auth_headers_with_storage(empty_storage, headers)
        assert result == headers
        
        # Test 3: Missing localStorage key
        no_localstorage = {}
        result = requester._inject_auth_headers_with_storage(no_localstorage, headers)
        assert result == headers

    @pytest.mark.asyncio
    async def test_multiple_localstorage_operations(self, requester, mock_context_with_pages):
        """Test multiple localStorage operations in sequence."""
        mock_context, mock_pages = mock_context_with_pages
        requester.context = mock_context
        requester._initialized = True
        
        # Test setting multiple values
        storage_dict = {
            'auth_token': 'token123',
            'api_key': 'key456',
            'user_id': '789',
            'preferences': '{"theme": "dark"}'
        }
        
        result = await requester.set_multiple_localstorage(storage_dict, "example.com")
        assert result is True
        
        # Should call evaluate for each key-value pair
        assert mock_pages[0].evaluate.call_count == 4
        
        # Test getting all values
        mock_storage = {
            'auth_token': 'token123',
            'api_key': 'key456',
            'user_id': '789',
            'preferences': '{"theme": "dark"}'
        }
        mock_pages[1].evaluate = AsyncMock(return_value=mock_storage)
        
        result = await requester.get_all_localstorage("example.com")
        assert result == mock_storage
        
        # Test clearing all values
        result = await requester.clear_localstorage("example.com")
        assert result is True
        mock_pages[1].evaluate.assert_called_with("localStorage.clear()")

    @pytest.mark.asyncio
    async def test_session_clear_comprehensive(self, requester, mock_context_with_pages):
        """Test comprehensive session clearing."""
        mock_context, mock_pages = mock_context_with_pages
        requester.context = mock_context
        requester._initialized = True
        
        # Add some localStorage data to pages
        mock_pages[0].evaluate = AsyncMock()
        mock_pages[1].evaluate = AsyncMock()
        
        await requester.clear_session()
        
        # Should clear cookies and permissions
        mock_context.clear_cookies.assert_called_once()
        mock_context.clear_permissions.assert_called_once()
        
        # Should clear localStorage on all pages
        mock_pages[0].evaluate.assert_called_with("localStorage.clear()")
        mock_pages[1].evaluate.assert_called_with("localStorage.clear()")

    @pytest.mark.asyncio
    async def test_cookie_operations_edge_cases(self, requester, mock_context_with_pages):
        """Test cookie operations with edge cases."""
        mock_context, mock_pages = mock_context_with_pages
        requester.context = mock_context
        requester._initialized = True
        
        # Test 1: Empty cookies
        mock_context.cookies = AsyncMock(return_value=[])
        result = await requester.get_cookies()
        assert result == {}
        
        # Test 2: Cookies with missing fields
        malformed_cookies = [
            {'name': 'valid_cookie', 'value': 'valid_value'},
            {'name': 'missing_value'},  # Missing value
            {'value': 'missing_name'},  # Missing name
            {'name': '', 'value': 'empty_name'},  # Empty name
        ]
        mock_context.cookies = AsyncMock(return_value=malformed_cookies)
        result = await requester.get_cookies()
        
        # Should only return valid cookies
        assert 'valid_cookie' in result
        assert result['valid_cookie'] == 'valid_value'
        assert len(result) == 1
        
        # Test 3: Setting cookies with special characters
        special_cookies = {
            'cookie with spaces': 'value with spaces',
            'cookie;with;semicolons': 'value,with,commas',
            'unicode_cookie_🎉': 'unicode_value_🚀'
        }
        
        await requester.set_cookies(special_cookies, "example.com")
        mock_context.add_cookies.assert_called_once()
        
        # Verify cookie structure
        call_args = mock_context.add_cookies.call_args[0][0]
        assert len(call_args) == 3
        for cookie in call_args:
            assert 'name' in cookie
            assert 'value' in cookie
            assert 'domain' in cookie
            assert 'path' in cookie

    @pytest.mark.asyncio
    async def test_http_request_flow_with_storage_integration(self, requester, mock_context_with_pages):
        """Test complete HTTP request flow with storage integration."""
        mock_context, mock_pages = mock_context_with_pages
        requester.context = mock_context
        requester.request_context = mock_request_context
        requester._initialized = True
        
        # Mock localStorage data
        mock_localstorage = [{
            'localStorage': [
                {'name': 'auth_token', 'value': 'token123'},
                {'name': 'api_key', 'value': 'key456'}
            ]
        }]
        
        # Mock response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.status_text = "OK"
        mock_response.headers = {'Content-Type': 'application/json'}
        mock_response.body = AsyncMock(return_value=b'{"access_token": "new_token_789"}')
        
        mock_request_context.get = AsyncMock(return_value=mock_response)
        
        # Mock storage operations
        with patch.object(requester, 'get_localstorage', return_value=mock_localstorage) as mock_get_storage, \
             patch.object(requester, '_detect_and_store_tokens', new_callable=AsyncMock) as mock_detect:
            
            valid_request = """GET /api/test HTTP/1.1\r
Host: example.com\r
User-Agent: TestAgent/1.0\r
Accept: application/json\r
\r
"""
            
            result = []
            async for chunk in requester.send_raw_data(
                host="example.com",
                port=80,
                target_host="example.com",
                request_data=valid_request
            ):
                result.append(chunk)
            
            # Should call get_localstorage for session management
            assert mock_get_storage.call_count >= 1
            
            # Should detect and store tokens from response
            mock_detect.assert_called_once()
            
            # Should have original request and response
            assert len(result) >= 2
            assert result[0] == valid_request

    @pytest.mark.asyncio
    async def test_storage_operations_with_concurrent_access(self, requester, mock_context_with_pages):
        """Test storage operations with concurrent access scenarios."""
        mock_context, mock_pages = mock_context_with_pages
        requester.context = mock_context
        requester._initialized = True
        
        # Simulate concurrent localStorage operations
        async def set_value(key, value, domain):
            return await requester.set_localstorage_value(key, value, domain)
        
        async def get_value(key, domain):
            return await requester.get_localstorage_value(key, domain)
        
        # Run concurrent operations
        tasks = [
            set_value("key1", "value1", "example.com"),
            set_value("key2", "value2", "example.com"),
            get_value("key1", "example.com"),
            get_value("key2", "example.com"),
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # All operations should complete without exceptions
        for result in results:
            assert not isinstance(result, Exception)

    @pytest.mark.asyncio
    async def test_storage_persistence_across_requests(self, requester, mock_context_with_pages):
        """Test storage persistence across multiple requests."""
        mock_context, mock_pages = mock_context_with_pages
        requester.context = mock_context
        requester.request_context = mock_request_context
        requester._initialized = True
        
        # Mock localStorage that persists across requests
        persistent_storage = [{
            'localStorage': [
                {'name': 'persistent_token', 'value': 'persistent_value'},
                {'name': 'session_id', 'value': 'session_123'}
            ]
        }]
        
        with patch.object(requester, 'get_localstorage', return_value=persistent_storage) as mock_get_storage:
            # First request
            valid_request1 = """GET /api/first HTTP/1.1\r
Host: example.com\r
\r
"""
            
            result1 = []
            async for chunk in requester.send_raw_data(
                host="example.com",
                port=80,
                target_host="example.com",
                request_data=valid_request1
            ):
                result1.append(chunk)
            
            # Second request
            valid_request2 = """GET /api/second HTTP/1.1\r
Host: example.com\r
\r
"""
            
            result2 = []
            async for chunk in requester.send_raw_data(
                host="example.com",
                port=80,
                target_host="example.com",
                request_data=valid_request2
            ):
                result2.append(chunk)
            
            # Should call get_localstorage for both requests
            assert mock_get_storage.call_count >= 2
            
            # Both requests should complete successfully
            assert len(result1) >= 1
            assert len(result2) >= 1


class TestPlaywrightRequesterErrorScenarios:
    """Test error scenarios and edge cases that might cause issues."""

    @pytest.fixture
    def requester(self):
        """Create a PlaywrightRequester instance for testing."""
        return PlaywrightRequester(session_id="error_test_session")

    @pytest.mark.asyncio
    async def test_initialization_failure_recovery(self, requester):
        """Test recovery from initialization failures."""
        # Mock playwright start failure
        with patch('playwright.async_api.async_playwright') as mock_async_playwright:
            mock_async_playwright.return_value.start.side_effect = Exception("Playwright start failed")
            
            # Should handle initialization failure gracefully
            try:
                await requester._initialize()
            except Exception as e:
                assert "Playwright start failed" in str(e)
            
            assert requester._initialized is False

    @pytest.mark.asyncio
    async def test_browser_launch_failure(self, requester):
        """Test browser launch failure scenarios."""
        mock_playwright = AsyncMock()
        mock_playwright.chromium.launch.side_effect = Exception("Browser launch failed")
        
        with patch('playwright.async_api.async_playwright') as mock_async_playwright:
            mock_async_playwright.return_value.start = AsyncMock(return_value=mock_playwright)
            
            try:
                await requester._initialize()
            except Exception as e:
                assert "Browser launch failed" in str(e)
            
            assert requester._initialized is False

    @pytest.mark.asyncio
    async def test_context_creation_failure(self, requester):
        """Test context creation failure scenarios."""
        mock_playwright = AsyncMock()
        mock_browser = AsyncMock()
        mock_browser.new_context.side_effect = Exception("Context creation failed")
        
        with patch('playwright.async_api.async_playwright') as mock_async_playwright:
            mock_async_playwright.return_value.start = AsyncMock(return_value=mock_playwright)
            mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
            
            try:
                await requester._initialize()
            except Exception as e:
                assert "Context creation failed" in str(e)
            
            assert requester._initialized is False

    @pytest.mark.asyncio
    async def test_cleanup_with_partial_initialization(self, requester):
        """Test cleanup when only partial initialization occurred."""
        # Partial initialization - only playwright started
        mock_playwright = AsyncMock()
        requester.playwright = mock_playwright
        requester._initialized = True
        
        # Should handle cleanup gracefully even with partial initialization
        await requester._cleanup()
        
        mock_playwright.stop.assert_called_once()
        assert requester._initialized is False

    @pytest.mark.asyncio
    async def test_storage_operations_with_corrupted_data(self, requester):
        """Test storage operations with corrupted or invalid data."""
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.close = AsyncMock()
        
        mock_context.pages = [mock_page]
        mock_context.new_page = AsyncMock(return_value=mock_page)
        
        requester.context = mock_context
        requester._initialized = True
        
        # Test with corrupted storage state
        mock_context.storage_state = AsyncMock(side_effect=Exception("Storage corruption"))
        
        with patch('anyio.Path.mkdir', new_callable=AsyncMock):
            result = await requester.get_localstorage("test_session")
            assert result == []  # Should return empty list on error

    @pytest.mark.asyncio
    async def test_http_request_with_malformed_response(self, requester):
        """Test HTTP request handling with malformed responses."""
        mock_context = AsyncMock()
        mock_request_context = AsyncMock()
        mock_context.request = mock_request_context
        
        requester.context = mock_context
        requester.request_context = mock_request_context
        requester._initialized = True
        
        # Mock response with missing attributes
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.status_text = None  # Missing status_text
        mock_response.headers = None  # Missing headers
        mock_response.body = AsyncMock(side_effect=Exception("Body read failed"))
        
        mock_request_context.get = AsyncMock(return_value=mock_response)
        
        valid_request = """GET /api/test HTTP/1.1\r
Host: example.com\r
\r
"""
        
        result = []
        async for chunk in requester.send_raw_data(
            host="example.com",
            port=80,
            target_host="example.com",
            request_data=valid_request
        ):
            result.append(chunk)
        
        # Should handle malformed response gracefully
        assert len(result) >= 1
        # Response formatting should handle missing attributes
        response_text = result[-1].decode('utf-8') if isinstance(result[-1], bytes) else result[-1]
        assert "HTTP/1.1" in response_text


if __name__ == "__main__":
    pytest.main([__file__])
