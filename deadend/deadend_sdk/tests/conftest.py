"""
Pytest configuration and shared fixtures for deadend_sdk tests.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_playwright():
    """Mock Playwright instance for testing."""
    mock_playwright = AsyncMock()
    mock_browser = AsyncMock()
    mock_context = AsyncMock()
    mock_request_context = AsyncMock()
    
    mock_context.request = mock_request_context
    mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    
    return mock_playwright, mock_browser, mock_context, mock_request_context


@pytest.fixture
def sample_http_requests():
    """Sample HTTP requests for testing."""
    return {
        'valid_get': """GET /api/test HTTP/1.1\r
Host: example.com\r
User-Agent: TestAgent/1.0\r
Accept: application/json\r
\r
""",
        'valid_post': """POST /api/data HTTP/1.1\r
Host: example.com\r
Content-Type: application/json\r
Content-Length: 17\r
\r
{"key": "value"}""",
        'invalid_request': """INVALID REQUEST\r
Missing proper headers\r
\r
""",
        'empty_request': "",
        'request_with_auth': """GET /api/protected HTTP/1.1\r
Host: example.com\r
Authorization: Bearer token123\r
User-Agent: TestAgent/1.0\r
\r
"""
    }


@pytest.fixture
def sample_responses():
    """Sample HTTP responses for testing."""
    return {
        'json_response': {
            'status': 200,
            'status_text': 'OK',
            'headers': {'Content-Type': 'application/json'},
            'body': b'{"success": true, "data": {"id": 123}}'
        },
        'html_response': {
            'status': 200,
            'status_text': 'OK',
            'headers': {'Content-Type': 'text/html'},
            'body': b'<html><body><h1>Hello World</h1></body></html>'
        },
        'error_response': {
            'status': 404,
            'status_text': 'Not Found',
            'headers': {'Content-Type': 'text/plain'},
            'body': b'Not Found'
        }
    }


@pytest.fixture
def mock_storage_data():
    """Mock localStorage data for testing."""
    return {
        'origins': [
            {
                'origin': 'https://example.com',
                'localStorage': [
                    {'name': 'auth_token', 'value': 'token123'},
                    {'name': 'api_key', 'value': 'key456'},
                    {'name': 'user_id', 'value': '789'}
                ]
            }
        ]
    }
