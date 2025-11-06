import pytest
import asyncio
from core.rag.webpage_insert import build_search_db
from core.config.settings import Config

config_test = Config()
config_test.configure()



# @pytest.fixture
# def build

@pytest.mark.asyncio
async def test_build_search_db():
    res = await build_search_db(config_test.zap_api_key, "https://example.com")

    assert res == 1