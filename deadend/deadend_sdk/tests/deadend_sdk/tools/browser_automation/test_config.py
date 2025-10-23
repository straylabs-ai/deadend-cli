"""
Test configuration for PlaywrightRequester integration tests.

This module provides test configuration and utilities for running
comprehensive integration tests.
"""

import pytest
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import MagicMock


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_test_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


@pytest.fixture
def mock_playwright_installation():
    """Mock Playwright installation for testing."""
    mp = pytest.MonkeyPatch()
    # Mock playwright imports to avoid requiring actual installation
    mp.setattr("playwright.async_api.async_playwright", MagicMock())
    yield mp
    mp.undo()


@pytest.fixture
def sample_storage_data():
    """Sample storage data for testing."""
    return {
        'origins': [
            {
                'origin': 'https://example.com',
                'localStorage': [
                    {'name': 'auth_token', 'value': 'token123'},
                    {'name': 'api_key', 'value': 'key456'},
                    {'name': 'user_id', 'value': '789'},
                    {'name': 'preferences', 'value': '{"theme": "dark", "lang": "en"}'}
                ]
            },
            {
                'origin': 'https://api.example.com',
                'localStorage': [
                    {'name': 'session_id', 'value': 'sess789'},
                    {'name': 'csrf_token', 'value': 'csrf123'},
                    {'name': 'refresh_token', 'value': 'refresh456'}
                ]
            }
        ]
    }


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
        'request_with_auth': """GET /api/protected HTTP/1.1\r
Host: example.com\r
Authorization: Bearer token123\r
User-Agent: TestAgent/1.0\r
\r
""",
        'request_with_cookies': """GET /api/session HTTP/1.1\r
Host: example.com\r
Cookie: session_id=abc123; user_pref=dark_mode\r
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
            'body': b'{"success": true, "data": {"id": 123, "access_token": "new_token_789"}}'
        },
        'html_response': {
            'status': 200,
            'status_text': 'OK',
            'headers': {'Content-Type': 'text/html'},
            'body': b'<html><head><meta name="csrf-token" content="csrf123"></head><body><h1>Hello World</h1></body></html>'
        },
        'error_response': {
            'status': 404,
            'status_text': 'Not Found',
            'headers': {'Content-Type': 'text/plain'},
            'body': b'Not Found'
        },
        'redirect_response': {
            'status': 302,
            'status_text': 'Found',
            'headers': {'Location': 'https://example.com/login'},
            'body': b''
        }
    }


@pytest.fixture
def malicious_inputs():
    """Malicious inputs for security testing."""
    return {
        'xss_key': "'; alert('xss'); //",
        'xss_value': "'; document.location='http://evil.com'; //",
        'sql_injection': "'; DROP TABLE users; --",
        'path_traversal': "../../../etc/passwd",
        'command_injection': "; rm -rf /",
        'unicode_attack': "🚀'; alert('xss'); //",
        'newline_injection': "value\n<script>alert('xss')</script>",
        'null_byte': "value\x00<script>alert('xss')</script>"
    }


@pytest.fixture
def edge_case_domains():
    """Edge case domains for testing."""
    return [
        "example.com",
        "https://example.com",
        "http://example.com",
        "subdomain.example.com",
        "localhost",
        "127.0.0.1",
        "[::1]",
        "example.com:8080",
        "user@example.com",
        "example.com/path",
        "example.com?query=value",
        "example.com#fragment",
        "",  # Empty domain
        "   ",  # Whitespace only
        "invalid..domain",  # Invalid format
        "domain with spaces",  # Spaces
        "domain\nwith\nnewlines",  # Newlines
        "domain\twith\ttabs",  # Tabs
    ]


@pytest.fixture
def large_data_samples():
    """Large data samples for testing."""
    return {
        'small_value': "x" * 100,
        'medium_value': "x" * 10000,
        'large_value': "x" * 1000000,  # 1MB
        'many_small_values': {f"key_{i}": f"value_{i}" for i in range(1000)},
        'unicode_large': "🚀" * 100000,
        'json_large': json.dumps({"data": ["item"] * 10000}),
    }


# Test markers for different test categories
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.integration,
]


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )
    config.addinivalue_line(
        "markers", "storage: mark test as storage-related test"
    )
    config.addinivalue_line(
        "markers", "security: mark test as security-related test"
    )
    config.addinivalue_line(
        "markers", "performance: mark test as performance-related test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running test"
    )


def pytest_collection_modifyitems(items):
    """Modify test collection to add markers based on test names."""
    for item in items:
        # Add storage marker to storage-related tests
        if "storage" in item.name.lower():
            item.add_marker(pytest.mark.storage)
        
        # Add security marker to security-related tests
        if any(keyword in item.name.lower() for keyword in ["injection", "malicious", "xss", "security"]):
            item.add_marker(pytest.mark.security)
        
        # Add performance marker to performance-related tests
        if any(keyword in item.name.lower() for keyword in ["large", "concurrent", "performance"]):
            item.add_marker(pytest.mark.performance)
        
        # Add slow marker to slow tests
        if any(keyword in item.name.lower() for keyword in ["integration", "comprehensive", "real_"]):
            item.add_marker(pytest.mark.slow)


# Import json for large_data_samples
import json
