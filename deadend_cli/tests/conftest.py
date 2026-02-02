import pytest
import json
from pathlib import Path

# Import sandbox fixtures (optional - only if they exist and can be imported)
try:
    from tests.fixtures.sandbox_fixtures import *
except (ImportError, ModuleNotFoundError):
    # Sandbox fixtures may not be available in all test environments
    # This is fine for RPC server tests that don't need them
    pass

@pytest.fixture
def sample_data():
    """Load sample test data."""
    fixtures_path = Path(__file__).parent / "fixtures" / "sample_data.json"
    if fixtures_path.exists():
        with open(fixtures_path, encoding="utf-8") as f:
            return json.load(f)
    return {}

@pytest.fixture
def temp_file(tmp_path):
    """Create a temporary file for testing."""
    file_path = tmp_path / "test_file.txt"
    file_path.write_text("test content")
    return file_path

@pytest.fixture(scope="session")
def database_url():
    """Database URL for integration tests."""
    return "sqlite:///:memory:"

# Custom markers for sandbox tests
def pytest_configure(config):
    """Configure custom pytest markers."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
    config.addinivalue_line(
        "markers", "docker: mark test as requiring Docker"
    )
    config.addinivalue_line(
        "markers", "sandbox: mark test as sandbox-related"
    )
    config.addinivalue_line(
        "markers", "asyncio: mark test as async (deselect with '-m \"not asyncio\"')"
    )
