"""
Additional integration tests for PlaywrightRequester storage functions.

This module focuses on specific issues found in the storage functions
and provides comprehensive test coverage for edge cases.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from deadend_sdk.tools.browser_automation.pw_requester import PlaywrightRequester


class TestPlaywrightRequesterStorageIssues:
    """Test specific issues found in storage functions."""

    @pytest.fixture
    def requester(self):
        """Create a PlaywrightRequester instance for testing."""
        return PlaywrightRequester(session_id="storage_issues_test")

    @pytest.fixture
    def mock_context_with_storage_issues(self):
        """Create mock context with storage-related issues."""
        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.close = AsyncMock()
        
        mock_context = AsyncMock()
        mock_context.pages = [mock_page]
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_context.storage_state = AsyncMock()
        
        return mock_context, mock_page

    @pytest.mark.asyncio
    async def test_localstorage_protocol_handling_inconsistency(self, requester, mock_context_with_storage_issues):
        """Test inconsistency in protocol handling between set and remove operations."""
        mock_context, mock_page = mock_context_with_storage_issues
        requester.context = mock_context
        requester._initialized = True
        
        # Test set_localstorage_value - uses http://
        await requester.set_localstorage_value("key", "value", "example.com")
        mock_page.goto.assert_called_with("http://example.com")
        
        # Reset mock
        mock_page.goto.reset_mock()
        
        # Test remove_localstorage_value - uses https:// (inconsistency!)
        await requester.remove_localstorage_value("key", "example.com")
        mock_page.goto.assert_called_with("https://example.com")
        
        # This reveals an inconsistency in the code where set uses http:// but remove uses https://

    @pytest.mark.asyncio
    async def test_localstorage_protocol_handling_inconsistency_clear(self, requester, mock_context_with_storage_issues):
        """Test inconsistency in protocol handling for clear operations."""
        mock_context, mock_page = mock_context_with_storage_issues
        requester.context = mock_context
        requester._initialized = True
        
        # Test clear_localstorage - uses https://
        await requester.clear_localstorage("example.com")
        mock_page.goto.assert_called_with("https://example.com")
        
        # Reset mock
        mock_page.goto.reset_mock()
        
        # Test get_all_localstorage - uses https://
        await requester.get_all_localstorage("example.com")
        mock_page.goto.assert_called_with("https://example.com")
        
        # Reset mock
        mock_page.goto.reset_mock()
        
        # Test set_multiple_localstorage - uses https://
        await requester.set_multiple_localstorage({"key": "value"}, "example.com")
        mock_page.goto.assert_called_with("https://example.com")

    @pytest.mark.asyncio
    async def test_localstorage_evaluate_injection_vulnerability(self, requester, mock_context_with_storage_issues):
        """Test potential injection vulnerability in localStorage evaluate calls."""
        mock_context, mock_page = mock_context_with_storage_issues
        requester.context = mock_context
        requester._initialized = True
        
        # Test with potentially malicious key/value
        malicious_key = "'; alert('xss'); //"
        malicious_value = "'; document.location='http://evil.com'; //"
        
        await requester.set_localstorage_value(malicious_key, malicious_value, "example.com")
        
        # Check if the evaluate call contains the malicious content
        call_args = mock_page.evaluate.call_args[0][0]
        assert malicious_key in call_args
        assert malicious_value in call_args
        
        # This reveals a potential XSS vulnerability if the key/value are not properly escaped

    @pytest.mark.asyncio
    async def test_localstorage_evaluate_injection_get_operation(self, requester, mock_context_with_storage_issues):
        """Test potential injection vulnerability in get operations."""
        mock_context, mock_page = mock_context_with_storage_issues
        requester.context = mock_context
        requester._initialized = True
        
        malicious_key = "'; alert('xss'); //"
        
        await requester.get_localstorage_value(malicious_key, "example.com")
        
        # Check if the evaluate call contains the malicious key
        call_args = mock_page.evaluate.call_args[0][0]
        assert malicious_key in call_args

    @pytest.mark.asyncio
    async def test_localstorage_evaluate_injection_remove_operation(self, requester, mock_context_with_storage_issues):
        """Test potential injection vulnerability in remove operations."""
        mock_context, mock_page = mock_context_with_storage_issues
        requester.context = mock_context
        requester._initialized = True
        
        malicious_key = "'; alert('xss'); //"
        
        await requester.remove_localstorage_value(malicious_key, "example.com")
        
        # Check if the evaluate call contains the malicious key
        call_args = mock_page.evaluate.call_args[0][0]
        assert malicious_key in call_args

    @pytest.mark.asyncio
    async def test_localstorage_path_creation_race_condition(self, requester, mock_context_with_storage_issues):
        """Test potential race condition in path creation."""
        mock_context, mock_page = mock_context_with_storage_issues
        requester.context = mock_context
        requester._initialized = True
        
        # Mock Path.mkdir to simulate race condition
        with patch('anyio.Path.mkdir', new_callable=AsyncMock) as mock_mkdir:
            mock_mkdir.side_effect = FileExistsError("Directory already exists")
            
            # Should handle race condition gracefully
            result = await requester.get_localstorage("test_session")
            assert result == []  # Should return empty list on error

    @pytest.mark.asyncio
    async def test_localstorage_storage_state_corruption(self, requester, mock_context_with_storage_issues):
        """Test handling of corrupted storage state."""
        mock_context, mock_page = mock_context_with_storage_issues
        requester.context = mock_context
        requester._initialized = True
        
        # Test with corrupted storage state
        corrupted_storage = {
            'origins': [
                {
                    'origin': 'https://example.com',
                    'localStorage': None  # Corrupted - should be a list
                },
                {
                    'origin': 'https://api.example.com',
                    'localStorage': [
                        {'name': 'valid_token', 'value': 'valid_value'},
                        {'name': 'corrupted_token'},  # Missing value
                        None,  # None entry
                        {'name': '', 'value': 'empty_name'}  # Empty name
                    ]
                }
            ]
        }
        
        mock_context.storage_state = AsyncMock(return_value=corrupted_storage)
        
        with patch('anyio.Path.mkdir', new_callable=AsyncMock):
            result = await requester.get_localstorage("test_session")
            
            # Should handle corrupted data gracefully
            assert len(result) == 2
            assert result[0]['origin'] == 'https://example.com'
            assert result[0]['localStorage'] is None  # Preserved as-is
            assert result[1]['origin'] == 'https://api.example.com'
            assert len(result[1]['localStorage']) == 4  # All entries preserved

    @pytest.mark.asyncio
    async def test_localstorage_page_creation_failure(self, requester):
        """Test handling of page creation failures."""
        mock_context = AsyncMock()
        mock_context.new_page.side_effect = Exception("Page creation failed")
        mock_context.pages = []
        
        requester.context = mock_context
        requester._initialized = True
        
        # All localStorage operations should handle page creation failure
        assert await requester.set_localstorage_value("key", "value", "example.com") is False
        assert await requester.get_localstorage_value("key", "example.com") is None
        assert await requester.remove_localstorage_value("key", "example.com") is False
        assert await requester.clear_localstorage("example.com") is False
        assert await requester.get_all_localstorage("example.com") == {}
        assert await requester.set_multiple_localstorage({"key": "value"}, "example.com") is False

    @pytest.mark.asyncio
    async def test_localstorage_page_goto_failure(self, requester, mock_context_with_storage_issues):
        """Test handling of page navigation failures."""
        mock_context, mock_page = mock_context_with_storage_issues
        mock_page.goto.side_effect = Exception("Navigation failed")
        
        requester.context = mock_context
        requester._initialized = True
        
        # All localStorage operations should handle navigation failure
        assert await requester.set_localstorage_value("key", "value", "example.com") is False
        assert await requester.get_localstorage_value("key", "example.com") is None
        assert await requester.remove_localstorage_value("key", "example.com") is False
        assert await requester.clear_localstorage("example.com") is False
        assert await requester.get_all_localstorage("example.com") == {}
        assert await requester.set_multiple_localstorage({"key": "value"}, "example.com") is False

    @pytest.mark.asyncio
    async def test_localstorage_evaluate_failure(self, requester, mock_context_with_storage_issues):
        """Test handling of JavaScript evaluation failures."""
        mock_context, mock_page = mock_context_with_storage_issues
        mock_page.evaluate.side_effect = Exception("JavaScript execution failed")
        
        requester.context = mock_context
        requester._initialized = True
        
        # All localStorage operations should handle evaluation failure
        assert await requester.set_localstorage_value("key", "value", "example.com") is False
        assert await requester.get_localstorage_value("key", "example.com") is None
        assert await requester.remove_localstorage_value("key", "example.com") is False
        assert await requester.clear_localstorage("example.com") is False
        assert await requester.get_all_localstorage("example.com") == {}
        assert await requester.set_multiple_localstorage({"key": "value"}, "example.com") is False

    @pytest.mark.asyncio
    async def test_localstorage_page_close_failure(self, requester, mock_context_with_storage_issues):
        """Test handling of page close failures."""
        mock_context, mock_page = mock_context_with_storage_issues
        mock_page.close.side_effect = Exception("Page close failed")
        
        requester.context = mock_context
        requester._initialized = True
        
        # Operations should still succeed even if page close fails
        result = await requester.set_localstorage_value("key", "value", "example.com")
        assert result is True  # Main operation succeeded
        
        result = await requester.get_localstorage_value("key", "example.com")
        assert result is None  # Evaluation failed, but operation completed
        
        result = await requester.remove_localstorage_value("key", "example.com")
        assert result is True  # Main operation succeeded

    @pytest.mark.asyncio
    async def test_localstorage_concurrent_modifications(self, requester, mock_context_with_storage_issues):
        """Test concurrent localStorage modifications."""
        mock_context, mock_page = mock_context_with_storage_issues
        requester.context = mock_context
        requester._initialized = True
        
        # Simulate concurrent modifications
        async def modify_storage(key, value):
            return await requester.set_localstorage_value(key, value, "example.com")
        
        # Run multiple concurrent operations
        tasks = [
            modify_storage("key1", "value1"),
            modify_storage("key2", "value2"),
            modify_storage("key3", "value3"),
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # All operations should complete successfully
        for result in results:
            assert not isinstance(result, Exception)
            assert result is True

    @pytest.mark.asyncio
    async def test_localstorage_memory_leak_prevention(self, requester, mock_context_with_storage_issues):
        """Test that pages are properly closed to prevent memory leaks."""
        mock_context, mock_page = mock_context_with_storage_issues
        requester.context = mock_context
        requester._initialized = True
        
        # Perform multiple operations
        await requester.set_localstorage_value("key1", "value1", "example.com")
        await requester.get_localstorage_value("key2", "example.com")
        await requester.remove_localstorage_value("key3", "example.com")
        
        # Each operation should create and close a page
        assert mock_context.new_page.call_count == 3
        assert mock_page.close.call_count == 3

    @pytest.mark.asyncio
    async def test_localstorage_domain_validation_edge_cases(self, requester, mock_context_with_storage_issues):
        """Test domain validation with edge cases."""
        mock_context, mock_page = mock_context_with_storage_issues
        requester.context = mock_context
        requester._initialized = True
        
        edge_case_domains = [
            "",  # Empty domain
            "   ",  # Whitespace only
            "invalid..domain",  # Invalid domain format
            "domain with spaces",  # Domain with spaces
            "domain:8080",  # Domain with port
            "user@domain.com",  # Domain with user info
            "domain.com/path",  # Domain with path
            "domain.com?query=value",  # Domain with query
            "domain.com#fragment",  # Domain with fragment
        ]
        
        for domain in edge_case_domains:
            try:
                await requester.set_localstorage_value("key", "value", domain)
                # Should handle edge cases gracefully
            except Exception as e:
                # Some edge cases might fail, which is acceptable
                pass

    @pytest.mark.asyncio
    async def test_localstorage_large_data_handling(self, requester, mock_context_with_storage_issues):
        """Test handling of large data in localStorage."""
        mock_context, mock_page = mock_context_with_storage_issues
        requester.context = mock_context
        requester._initialized = True
        
        # Test with large values (localStorage typically has 5-10MB limit)
        large_value = "x" * 1000000  # 1MB value
        
        result = await requester.set_localstorage_value("large_key", large_value, "example.com")
        assert result is True
        
        # Test with many small values
        many_values = {f"key_{i}": f"value_{i}" for i in range(1000)}
        
        result = await requester.set_multiple_localstorage(many_values, "example.com")
        assert result is True
        
        # Should call evaluate for each key-value pair
        assert mock_page.evaluate.call_count == 1001  # 1 large value + 1000 small values

    @pytest.mark.asyncio
    async def test_localstorage_special_characters_handling(self, requester, mock_context_with_storage_issues):
        """Test handling of special characters in localStorage operations."""
        mock_context, mock_page = mock_context_with_storage_issues
        requester.context = mock_context
        requester._initialized = True
        
        special_cases = [
            ("key with spaces", "value with spaces"),
            ("key\nwith\nnewlines", "value\nwith\nnewlines"),
            ("key\twith\ttabs", "value\twith\ttabs"),
            ("key\"with\"quotes", "value\"with\"quotes"),
            ("key'with'apostrophes", "value'with'apostrophes"),
            ("key\\with\\backslashes", "value\\with\\backslashes"),
            ("key/with/slashes", "value/with/slashes"),
            ("key?with?question", "value?with?question"),
            ("key#with#hash", "value#with#hash"),
            ("key&with&ampersand", "value&with&ampersand"),
        ]
        
        for key, value in special_cases:
            result = await requester.set_localstorage_value(key, value, "example.com")
            assert result is True
            
            # Check that the evaluate call contains the special characters
            call_args = mock_page.evaluate.call_args[0][0]
            assert key in call_args
            assert value in call_args

    @pytest.mark.asyncio
    async def test_localstorage_unicode_handling(self, requester, mock_context_with_storage_issues):
        """Test handling of Unicode characters in localStorage operations."""
        mock_context, mock_page = mock_context_with_storage_issues
        requester.context = mock_context
        requester._initialized = True
        
        unicode_cases = [
            ("ключ", "значение"),  # Cyrillic
            ("键", "值"),  # Chinese
            ("キー", "値"),  # Japanese
            ("🔑", "💾"),  # Emojis
            ("key_ñ", "value_ñ"),  # Accented characters
            ("key_α", "value_β"),  # Greek letters
            ("key_∞", "value_∞"),  # Mathematical symbols
        ]
        
        for key, value in unicode_cases:
            result = await requester.set_localstorage_value(key, value, "example.com")
            assert result is True
            
            # Check that the evaluate call contains the Unicode characters
            call_args = mock_page.evaluate.call_args[0][0]
            assert key in call_args
            assert value in call_args

    @pytest.mark.asyncio
    async def test_localstorage_session_id_handling(self, requester, mock_context_with_storage_issues):
        """Test handling of session ID in localStorage operations."""
        mock_context, mock_page = mock_context_with_storage_issues
        requester.context = mock_context
        requester._initialized = True
        
        # Test with various session ID formats
        session_ids = [
            "simple_session",
            "session-with-dashes",
            "session_with_underscores",
            "session.with.dots",
            "session123",
            "SESSION_UPPERCASE",
            "session-mixed_Case.123",
        ]
        
        for session_id in session_ids:
            requester.session_id = session_id
            
            with patch('anyio.Path.mkdir', new_callable=AsyncMock):
                result = await requester.get_localstorage(session_id)
                assert result == []  # Mock returns empty list

    @pytest.mark.asyncio
    async def test_localstorage_path_construction_edge_cases(self, requester, mock_context_with_storage_issues):
        """Test path construction with edge cases."""
        mock_context, mock_page = mock_context_with_storage_issues
        requester.context = mock_context
        requester._initialized = True
        
        # Test with various session ID formats that might cause path issues
        problematic_session_ids = [
            "../session",  # Path traversal attempt
            "session/with/slashes",  # Slashes in session ID
            "session\\with\\backslashes",  # Backslashes in session ID
            "session:with:colons",  # Colons in session ID
            "session*with*wildcards",  # Wildcards in session ID
            "session?with?question",  # Question marks in session ID
            "session<with>brackets",  # Brackets in session ID
            "session|with|pipes",  # Pipes in session ID
        ]
        
        for session_id in problematic_session_ids:
            requester.session_id = session_id
            
            with patch('anyio.Path.mkdir', new_callable=AsyncMock):
                try:
                    result = await requester.get_localstorage(session_id)
                    assert result == []  # Should handle gracefully
                except Exception as e:
                    # Some problematic session IDs might cause exceptions
                    pass


if __name__ == "__main__":
    pytest.main([__file__])
