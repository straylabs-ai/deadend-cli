import pytest
from core.task_processor import TaskProcessor, PayloadResponse
from pydantic_ai.usage import Usage, UsageLimits
import requests
import asyncio

from core.config.settings import Config
from core.utils.structures import Task, AIModel, TargetDeps

"""
The following functions test the TestingGrounds setup. 
The objective here is to achieve unit testing for the different methods 
of the TestingGrounds object. It also if the tests the AI workflow works
correctly. 

These tests are run with the OWASP Juice Shop vulnerable app on the register
page : http://localhost:3000/#/register.

The goal will be a concise one as the one that should be expected from the 
planner. For example : 
`Check is the page is vulnerable to XSS payloads by sending requests 
containing the information in the form.` 

- This test does not have to be successful but it has to run to the end. 
"""

config_test = Config()
config_test.configure()

@pytest.fixture
def testing_grounds():
    # task = Task(goal="Test goal", status="pending", output="")
    target_info = TargetDeps(
        target="http://localhost:3000/#/register",
        openapi_spec={},
        path_crawl_data="",
        authentication_data=""
    )
    zap_api_key = config_test.zap_api_key
    return TestingGrounds(target_info, zap_api_key)

@pytest.fixture 
def anthropic_model():
    return AIModel(model_name="claude-3-7-sonnet-latest", api_key=config_test.anthropic_api_key)

@pytest.fixture 
def openai_model():
    return AIModel(model_name="o4-mini-2025-04-16", api_key=config_test.openai_api_key)

# @pytest.fixture
# def mock_usage():
#     return Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0)

@pytest.fixture
def mock_usage_limits():
    return UsageLimits(max_tokens=10000)

@pytest.fixture
def webpage_register_example():
    return str(requests.get("http://localhost:3000/#/register").content)


@pytest.fixture
def mock_task():
    goal ="""
task goal is : 
Check is the page is vulnerable to a SQL injection by building requests containing the exploit payload 
"""

    return Task(
        id=1, 
        goal=goal,
        status='pending',
        output=''
    )

@pytest.mark.asyncio
async def test_run_example_task(testing_grounds, mock_task, openai_model, webpage_register_example):
    result = await testing_grounds.run(model=openai_model, task=mock_task,info_to_analyze=webpage_register_example, usage_a=Usage(), usage_limits=UsageLimits())
    assert result is None

# @pytest.mark.asyncio 
# async def test_run_processed_task(testing_grounds, mock_model, mock_usage, mock_usage_limits):
#     task = Task(goal="Test goal", status="completed", output="Test output")
#     result = await testing_grounds.run(mock_model, task, mock_usage, mock_usage_limits)
#     assert result is None

# @pytest.mark.asyncio
# async def test_loop_plan_max_iterations(testing_grounds, mock_model):
#     task_plan = "Test plan"
#     result = await testing_grounds._loop_plan(mock_model, task_plan)
#     assert result is None

# def test_payload_response_model():
#     payload = PayloadResponse(
#         state="achieved",
#         analysis="Test analysis",
#         response="Test response"
#     )
#     assert payload.state == "achieved"
#     assert payload.analysis == "Test analysis" 
#     assert payload.response == "Test response"