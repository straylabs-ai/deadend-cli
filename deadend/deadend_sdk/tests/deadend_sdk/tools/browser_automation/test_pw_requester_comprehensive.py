"""
Comprehensive test suite for PlaywrightRequester.

This module provides a complete test suite that includes both mocked unit tests
and real Playwright integration tests, with proper test categorization.
"""

import pytest
from unittest.mock import AsyncMock, patch

from deadend_sdk.tools.browser_automation.pw_requester import PlaywrightRequester


class TestPlaywrightRequesterComprehensive:
    """Comprehensive test suite combining mocked and real tests."""

    @pytest.mark.unit
    def test_basic_initialization(self):
        """Test basic initialization (unit test)."""
        requester = PlaywrightRequester()
        assert requester.verify_ssl is True
        assert requester.proxy_url is None
        assert requester.session_id is None
        assert requester._initialized is False

    @pytest.mark.unit
    def test_initialization_with_params(self):
        """Test initialization with parameters (unit test)."""
        requester = PlaywrightRequester(
            verify_ssl=False,
            proxy_url="http://proxy:8080",
            session_id="test_session"
        )
        assert requester.verify_ssl is False
        assert requester.proxy_url == "http://proxy:8080"
        assert requester.session_id == "test_session"

    @pytest.mark.unit
    def test_parse_raw_request(self):
        """Test request parsing (unit test)."""
        requester = PlaywrightRequester()
        
        valid_request = """GET /api/test HTTP/1.1\r
Host: example.com\r
User-Agent: TestAgent/1.0\r
\r
"""
        result = requester._parse_raw_request(valid_request)
        
        assert result is not None
        assert result['method'] == 'GET'
        assert result['path'] == '/api/test'
        assert result['headers']['Host'] == 'example.com'

    @pytest.mark.unit
    def test_inject_auth_headers_with_storage(self):
        """Test auth header injection (unit test)."""
        requester = PlaywrightRequester()
        
        storage = {
            "localStorage": [
                {"name": "auth_token", "value": "token123"},
                {"name": "api_key", "value": "key456"}
            ]
        }
        
        headers = {'Content-Type': 'application/json'}
        result = requester._inject_auth_headers_with_storage(storage, headers)
        
        assert 'Authorization' in result
        assert result['Authorization'] == 'Bearer token123'
        assert 'X-API-Key' in result
        assert result['X-API-Key'] == 'key456'

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_mocked_localstorage_operations(self):
        """Test localStorage operations with mocks (integration test)."""
        requester = PlaywrightRequester()
        
        # Mock the context and page
        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.close = AsyncMock()
        
        mock_context = AsyncMock()
        mock_context.pages = [mock_page]
        mock_context.new_page = AsyncMock(return_value=mock_page)
        
        requester.context = mock_context
        requester._initialized = True
        
        # Test localStorage operations
        result = await requester.set_localstorage_value("key", "value", "example.com")
        assert result is True
        
        mock_page.goto.assert_called_with("http://example.com")
        mock_page.evaluate.assert_called_with("localStorage.setItem('key', 'value')")
        mock_page.close.assert_called_once()

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_mocked_http_request_flow(self):
        """Test HTTP request flow with mocks (integration test)."""
        requester = PlaywrightRequester()
        
        # Mock all the components
        mock_page = AsyncMock()
        mock_context = AsyncMock()
        mock_request_context = AsyncMock()
        mock_response = AsyncMock()
        
        mock_context.pages = [mock_page]
        mock_context.request = mock_request_context
        mock_response.status = 200
        mock_response.status_text = "OK"
        mock_response.headers = {'Content-Type': 'application/json'}
        mock_response.body = AsyncMock(return_value=b'{"success": true}')
        
        mock_request_context.get = AsyncMock(return_value=mock_response)
        
        requester.context = mock_context
        requester.request_context = mock_request_context
        requester._initialized = True
        
        # Test HTTP request
        request_data = """GET /api/test HTTP/1.1\r
Host: example.com\r
\r
"""
        
        result = []
        async for chunk in requester.send_raw_data(
            host="example.com",
            port=80,
            target_host="example.com",
            request_data=request_data
        ):
            result.append(chunk)
        
        assert len(result) >= 2
        assert result[0] == request_data

    @pytest.mark.real
    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_real_playwright_initialization(self):
        """Test real Playwright initialization (real test)."""
        requester = PlaywrightRequester()
        async with requester:
            assert requester._initialized is True
            assert requester.playwright is not None
            assert requester.browser is not None
            assert requester.context is not None
            assert requester.request_context is not None

    @pytest.mark.real
    @pytest.mark.slow
    @pytest.mark.network
    @pytest.mark.asyncio
    async def test_real_http_request(self):
        """Test real HTTP request (real test)."""
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

    @pytest.mark.real
    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_real_localstorage_operations(self):
        """Test real localStorage operations (real test)."""
        requester = PlaywrightRequester()
        async with requester:
            # Test setting and getting localStorage
            result = await requester.set_localstorage_value("test_key", "test_value", "httpbin.org")
            assert result is True
            
            value = await requester.get_localstorage_value("test_key", "httpbin.org")
            assert value == "test_value"
            
            # Test multiple values
            storage_dict = {
                "auth_token": "real_token_123",
                "user_id": "456"
            }
            result = await requester.set_multiple_localstorage(storage_dict, "httpbin.org")
            assert result is True
            
            # Test getting all values
            all_storage = await requester.get_all_localstorage("httpbin.org")
            assert "test_key" in all_storage
            assert "auth_token" in all_storage

    @pytest.mark.real
    @pytest.mark.slow
    @pytest.mark.network
    @pytest.mark.asyncio
    async def test_real_error_handling(self):
        """Test real error handling (real test)."""
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
            
            # Should handle error gracefully
            assert len(result) >= 1

    @pytest.mark.storage
    @pytest.mark.asyncio
    async def test_storage_protocol_inconsistency(self):
        """Test storage protocol inconsistency (storage test)."""
        requester = PlaywrightRequester()
        
        # Mock context and pages
        mock_page = AsyncMock()
        mock_context = AsyncMock()
        mock_context.pages = [mock_page]
        mock_context.new_page = AsyncMock(return_value=mock_page)
        
        requester.context = mock_context
        requester._initialized = True
        
        # Test set_localstorage_value (uses http://)
        await requester.set_localstorage_value("key", "value", "example.com")
        mock_page.goto.assert_called_with("http://example.com")
        
        # Reset mock
        mock_page.goto.reset_mock()
        
        # Test remove_localstorage_value (uses https://)
        await requester.remove_localstorage_value("key", "example.com")
        mock_page.goto.assert_called_with("https://example.com")
        
        # This reveals the inconsistency

    @pytest.mark.security
    @pytest.mark.asyncio
    async def test_xss_injection_vulnerability(self):
        """Test XSS injection vulnerability (security test)."""
        requester = PlaywrightRequester()
        
        # Mock context and pages
        mock_page = AsyncMock()
        mock_context = AsyncMock()
        mock_context.pages = [mock_page]
        mock_context.new_page = AsyncMock(return_value=mock_page)
        
        requester.context = mock_context
        requester._initialized = True
        
        # Test with potentially malicious input
        malicious_key = "'; alert('xss'); //"
        malicious_value = "'; document.location='http://evil.com'; //"
        
        await requester.set_localstorage_value(malicious_key, malicious_value, "example.com")
        
        # Check if the evaluate call contains the malicious content
        call_args = mock_page.evaluate.call_args[0][0]
        assert malicious_key in call_args
        assert malicious_value in call_args
        
        # This reveals a potential XSS vulnerability

    @pytest.mark.performance
    @pytest.mark.asyncio
    async def test_large_data_handling(self):
        """Test large data handling (performance test)."""
        requester = PlaywrightRequester()
        
        # Mock context and pages
        mock_page = AsyncMock()
        mock_context = AsyncMock()
        mock_context.pages = [mock_page]
        mock_context.new_page = AsyncMock(return_value=mock_page)
        
        requester.context = mock_context
        requester._initialized = True
        
        # Test with large data
        large_value = "x" * 100000  # 100KB
        result = await requester.set_localstorage_value("large_key", large_value, "example.com")
        assert result is True
        
        # Test with many small values
        many_values = {f"key_{i}": f"value_{i}" for i in range(1000)}
        result = await requester.set_multiple_localstorage(many_values, "example.com")
        assert result is True
        
        # Should call evaluate for each key-value pair
        assert mock_page.evaluate.call_count == 1001  # 1 large + 1000 small


# Test markers configuration
pytestmark = [
    pytest.mark.asyncio,
]


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "integration: Integration tests with mocks")
    config.addinivalue_line("markers", "real: Real Playwright tests")
    config.addinivalue_line("markers", "storage: Storage-related tests")
    config.addinivalue_line("markers", "security: Security-related tests")
    config.addinivalue_line("markers", "performance: Performance-related tests")
    config.addinivalue_line("markers", "network: Tests requiring network access")
    config.addinivalue_line("markers", "slow: Slow-running tests")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
