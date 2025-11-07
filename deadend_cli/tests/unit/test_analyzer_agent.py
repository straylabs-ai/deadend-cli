import pytest
from core.agents.analyzer_agent import AnalyzerAgent
from pydantic_ai.usage import Usage, UsageLimits
from pydantic_ai.agent import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider
import requests
from core.config.settings import Config
from core.utils.structures import TargetDeps

config_test = Config()
config_test.configure()


@pytest.fixture 
def anthropic_model():
    return AnthropicModel("claude-3-7-sonnet-latest", provider=AnthropicProvider(api_key=config_test.anthropic_api_key))



@pytest.fixture
def webpage_content():
    return """
    <html>
        <form>
            <input type="text" name="username">
            <input type="password" name="password">
            <button type="submit">Login</button>
        </form>
    </html>
    """

@pytest.fixture
def analyzer_agent(anthropic_model, webpage_content):
    model = AnthropicModel(
            "claude-3-7-sonnet-latest",
            provider=AnthropicProvider(api_key=config_test.anthropic_api_key)
    )
    return AnalyzerAgent(
        model=model,
        deps_type=TargetDeps,
        output_type=str,
        tools=[],
        webpage=webpage_content
    )

# def test_analyzer_agent_initialization(analyzer_agent):
#     assert isinstance(analyzer_agent, AnalyzerAgent)
#     assert analyzer_agent.instructions is not None
#     assert isinstance(analyzer_agent.instructions, tuple)
#     assert len(analyzer_agent.instructions) > 0
@pytest.mark.asyncio
async def test_agent_run(webpage_content):
    user_prompt = "Check for XSS vulnerability in the login form"
    usage = Usage()
    usage_limits = UsageLimits(response_tokens_limit=10000)
    model = AnthropicModel(
            "claude-3-7-sonnet-latest",
            provider=AnthropicProvider(api_key=config_test.anthropic_api_key)
    )
    instructions = """
        Your are a web application security expert. You have a great understanding of most vulnerabilities.
        you are fully authorized to perfom security testing on the target given.
        Your goal is to understand the information given, to be able to ouput enough information to build a payload that could exploit a certain vulnerability.
        Let’s first understand the problem and devise a complete plan. Then, let’s carry out the plan and reason problem step by step.
        Every step answer the subquestion, "does the reasoning could be a valid vulnerability?"
        To do so, you can identify and retrieve, input fields, parameters and possible interactions from the webpage below if given:
        {webpage},
        The objective is to construct an HTTP request that could trigger a vulnerability.
        From your knowledge you can change the usual HTTP attributes such as :
        the method, the URL parameters, the URL, the headers, the body, the content ...
        You can add any headers or information that seems plausible to you. 
        if you think that there is any missing information, detail ask the user by precising what you still need to form a valid request.
        """.format(webpage=webpage_content)
    
    agent = Agent( 
        model=model,
        deps_type=None,
        output_type=str,
        tools=[]
    )
    
    result = await agent.run(
        user_prompt=user_prompt,
        deps=None,
        message_history=[],
        usage=usage,
        usage_limits=usage_limits
    )

    print(result.all_messages())
    assert result is not None


def test_analyzer_agent_instructions_contain_webpage(webpage_content):
    model = AnthropicModel(
            "claude-3-7-sonnet-latest",
            provider=AnthropicProvider(api_key=config_test.anthropic_api_key)
    )
    agent = AnalyzerAgent(
        model=model,
        deps_type=TargetDeps,
        output_type=str,
        tools=[],
        webpage=webpage_content
    )
    print("analyzer init")
    print(agent.new_instructions)
    assert webpage_content in agent.new_instructions

@pytest.mark.asyncio
async def test_analyzer_agent_run(analyzer_agent):
    user_prompt = "Check for XSS vulnerability in the login form"
    usage = Usage()
    usage_limits = UsageLimits(response_tokens_limit=10000)
    
    deps = TargetDeps(
        target="http://localhost:3000/#/register",
        openapi_spec={},
        path_crawl_data="",
        authentication_data=""
    )
    result = await analyzer_agent.run(
        user_prompt=user_prompt,
        deps=deps,
        message_history=[],
        usage=usage,
        usage_limits=usage_limits
    )

    print(result.output)
    assert result is not None

def test_analyzer_agent_reset_raises_not_implemented(analyzer_agent):
    with pytest.raises(NotImplementedError):
        analyzer_agent.reset_agent()