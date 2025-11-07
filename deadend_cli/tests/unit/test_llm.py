import pytest
from unittest.mock import patch, MagicMock
from src.utils.llm import llm_call

@pytest.fixture
def test_data():
    return {
        'prompt': "test prompt",
        'system_prompt': "test system prompt",
        'model': "claude-3-opus-20240229",
        'api_key': "test_key",
        'tools': []
    }

# @patch('anthropic.Anthropic')
# def test_llm_call_with_string_prompt(mock_anthropic, test_data):
#     # Setup mock
#     mock_client = MagicMock()
#     mock_anthropic.return_value = mock_client
#     mock_stream = MagicMock()
#     mock_stream.text_stream = ["test", "response"]
#     mock_client.messages.stream.return_value = mock_stream

#     # Call function
#     result = llm_call(
#         test_data['prompt'],
#         test_data['system_prompt'],
#         test_data['model'],
#         test_data['tools'],
#         test_data['api_key']
#     )

#     # Assertions
#     mock_anthropic.assert_called_once_with(api_key=test_data['api_key'])
#     mock_client.messages.stream.assert_called_once_with(
#         max_tokens=4096,
#         system=test_data['system_prompt'],
#         messages=[{"role": "user", "content": test_data['prompt']}],
#         model=test_data['model'],
#         tools=test_data['tools'],
#         temperature=0.5
#     )
#     assert result == "testresponse"

# @patch('anthropic.Anthropic')
# def test_llm_call_with_message_list(mock_anthropic, test_data):
#     # Setup test data
#     test_messages = [
#         {"role": "user", "content": "message 1"},
#         {"role": "assistant", "content": "message 2"}
#     ]
    
#     # Setup mock
#     mock_client = MagicMock()
#     mock_anthropic.return_value = mock_client
#     mock_stream = MagicMock()
#     mock_stream.text_stream = ["test", "response"]
#     mock_client.messages.stream.return_value = mock_stream

#     # Call function
#     result = llm_call(
#         test_messages,
#         test_data['system_prompt'],
#         test_data['model'],
#         test_data['tools'],
#         test_data['api_key']
#     )

#     # Assertions
#     mock_anthropic.assert_called_once_with(api_key=test_data['api_key'])
#     mock_client.messages.stream.assert_called_once_with(
#         max_tokens=4096,
#         system=test_data['system_prompt'],
#         messages=test_messages,
#         model=test_data['model'],
#         tools=test_data['tools'],
#         temperature=0.5
#     )
#     assert result == "testresponse"
