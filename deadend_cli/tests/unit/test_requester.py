import pytest
from core.tools.requester import Requester
from core.config.settings import Config
import ssl

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# ssl_context.load_verify_locations("./zap_root_ca.cer")

config_test = Config()
config_test.configure()


@pytest.mark.asyncio
async def test_send_raw_http_request():
    raw_request = 'GET /#/register HTTP/1.1\r\nhost: localhost:3000\r\nUser-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36\r\nAccept: */*\r\nConnection: keep-alive\r\n\r\n'
    requester = Requester(api_key=config_test.zap_api_key, verify_ssl=ssl_context)
    response = await requester.send_raw_data("localhost", 8080, request_data=raw_request)
    print("raw data request:")
    print(response)
    assert len(response) >0

@pytest.mark.asyncio
async def test_open_url_success():
    url = "http://example.com"
    
    requester = Requester(api_key=config_test.zap_api_key, verify_ssl=False)

    response = await requester.open_url(url)

    print(response)
    assert response != None



# @pytest.mark.asyncio
# async def test_send_req_failure():
#     # Arrange
#     request_data = {"url": "http://example.com", "method": "GET"}
#     print(config_test.zap_api_key)
#     requester = Requester(api_key=config_test.zap_api_key)
#     requester._zap_send_req = AsyncMock(side_effect=Exception("Request failed"))

#     # Act
#     await requester.send_req(request_data)

#     # Assert
#     requester._zap_send_req.assert_awaited_once_with(request_data=request_data)
#     assert requester.response is None