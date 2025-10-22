"""
Test fixes for PlaywrightRequester storage issues.

This module demonstrates the fixes for the storage issues found in real Playwright tests.
"""

import pytest
from unittest.mock import AsyncMock, patch
from deadend_sdk.tools.browser_automation.pw_requester import PlaywrightRequester


class TestStorageFixes:
    """Test the fixes for storage issues."""

    @pytest.mark.asyncio
    async def test_protocol_consistency_fix(self):
        """Test that localStorage operations use consistent protocols."""
        requester = PlaywrightRequester()
        
        # Mock context and pages
        mock_page = AsyncMock()
        mock_context = AsyncMock()
        mock_context.pages = [mock_page]
        mock_context.new_page = AsyncMock(return_value=mock_page)
        
        requester.context = mock_context
        requester._initialized = True
        
        # Test set_localstorage_value - should use https://
        await requester.set_localstorage_value("key", "value", "example.com")
        mock_page.goto.assert_called_with("https://example.com")
        
        # Reset mock
        mock_page.goto.reset_mock()
        
        # Test get_all_localstorage - should also use https://
        await requester.get_all_localstorage("example.com")
        mock_page.goto.assert_called_with("https://example.com")

    @pytest.mark.asyncio
    async def test_page_persistence_fix(self):
        """Test that localStorage operations use the same page for persistence."""
        requester = PlaywrightRequester()
        
        # Mock context with persistent page
        mock_page = AsyncMock()
        mock_context = AsyncMock()
        mock_context.pages = [mock_page]
        mock_context.new_page = AsyncMock(return_value=mock_page)
        
        requester.context = mock_context
        requester._initialized = True
        
        # Mock localStorage to simulate persistence
        storage_data = {}
        
        def mock_evaluate(script):
            if "localStorage.setItem" in script:
                # Extract key and value from script
                import re
                match = re.search(r"localStorage\.setItem\('([^']+)', '([^']+)'\)", script)
                if match:
                    key, value = match.groups()
                    storage_data[key] = value
            elif "localStorage.getItem" in script:
                # Extract key from script
                import re
                match = re.search(r"localStorage\.getItem\('([^']+)'\)", script)
                if match:
                    key = match.group(1)
                    return storage_data.get(key)
            elif "localStorage.length" in script:
                return len(storage_data)
            elif "localStorage.key" in script:
                # Return all keys
                return list(storage_data.keys())
            return {}
        
        mock_page.evaluate = AsyncMock(side_effect=mock_evaluate)
        
        # Test setting and getting from same page
        result = await requester.set_localstorage_value("test_key", "test_value", "example.com")
        assert result is True
        
        # Should use the same page, not create a new one
        assert mock_context.new_page.call_count == 1
        
        # Test getting the value
        value = await requester.get_localstorage_value("test_key", "example.com")
        assert value == "test_value"

    @pytest.mark.asyncio
    async def test_special_character_escaping_fix(self):
        """Test that special characters are properly escaped."""
        requester = PlaywrightRequester()
        
        # Mock context and pages
        mock_page = AsyncMock()
        mock_context = AsyncMock()
        mock_context.pages = [mock_page]
        mock_context.new_page = AsyncMock(return_value=mock_page)
        
        requester.context = mock_context
        requester._initialized = True
        
        # Test with special characters
        special_key = "key\"with\"quotes"
        special_value = "value\nwith\nnewlines"
        
        await requester.set_localstorage_value(special_key, special_value, "example.com")
        
        # Check that the evaluate call properly escapes the characters
        call_args = mock_page.evaluate.call_args[0][0]
        # Should use JSON.stringify or proper escaping
        assert "JSON.stringify" in call_args or "\\\"" in call_args

    @pytest.mark.asyncio
    async def test_error_handling_fix(self):
        """Test that errors are handled gracefully."""
        requester = PlaywrightRequester()
        
        # Mock context and pages
        mock_page = AsyncMock()
        mock_context = AsyncMock()
        mock_context.pages = [mock_page]
        mock_context.new_page = AsyncMock(return_value=mock_page)
        
        requester.context = mock_context
        requester._initialized = True
        
        # Test with page.goto failure
        mock_page.goto.side_effect = Exception("Navigation failed")
        
        result = await requester.set_localstorage_value("key", "value", "example.com")
        assert result is False  # Should return False on error, not raise exception

    @pytest.mark.asyncio
    async def test_concurrent_operations_fix(self):
        """Test that concurrent localStorage operations work correctly."""
        requester = PlaywrightRequester()
        
        # Mock context with shared storage
        mock_page = AsyncMock()
        mock_context = AsyncMock()
        mock_context.pages = [mock_page]
        mock_context.new_page = AsyncMock(return_value=mock_page)
        
        requester.context = mock_context
        requester._initialized = True
        
        # Mock shared storage
        storage_data = {}
        
        def mock_evaluate(script):
            if "localStorage.setItem" in script:
                import re
                match = re.search(r"localStorage\.setItem\('([^']+)', '([^']+)'\)", script)
                if match:
                    key, value = match.groups()
                    storage_data[key] = value
            elif "localStorage.getItem" in script:
                import re
                match = re.search(r"localStorage\.getItem\('([^']+)'\)", script)
                if match:
                    key = match.group(1)
                    return storage_data.get(key)
            return {}
        
        mock_page.evaluate = AsyncMock(side_effect=mock_evaluate)
        
        # Test concurrent operations
        import asyncio
        
        async def set_value(key, value):
            return await requester.set_localstorage_value(key, value, "example.com")
        
        async def get_value(key):
            return await requester.get_localstorage_value(key, "example.com")
        
        # Run concurrent operations
        tasks = [
            set_value("key1", "value1"),
            set_value("key2", "value2"),
            get_value("key1"),
            get_value("key2")
        ]
        
        results = await asyncio.gather(*tasks)
        
        # All operations should complete successfully
        assert all(result is True for result in results[:2])  # Set operations
        assert results[2] == "value1"  # Get operations
        assert results[3] == "value2"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
