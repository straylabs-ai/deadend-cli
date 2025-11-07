import pytest
from core.tools.crawler import WebpageCrawler
from core.config.settings import Config

config_test = Config()
config_test.configure()



@pytest.fixture
def crawler():
    return WebpageCrawler(config_test.zap_api_key)


def test_start_spider(crawler):
    urls = crawler._start_spider("https://example.com")
    print(urls)
    assert urls != None 

@pytest.mark.asyncio
async def test_async_start_spider(crawler):
    urls = await crawler.async_start_spider("https://example.com")
    assert urls != None

# def test_get_alerts(mock_zap, crawler):
#     # Setup mock
#     mock_alerts = [{"alert": "XSS"}, {"alert": "SQL Injection"}]
#     mock_zap.core.alerts.return_value = mock_alerts
    
#     # Call method
#     alerts = crawler.get_alerts()
    
#     # Assertions
#     mock_zap.core.alerts.assert_called_once()
#     assert alerts == mock_alerts