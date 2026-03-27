import asyncio
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4


PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "deadend_agent"

if "deadend_agent" not in sys.modules:
    package = types.ModuleType("deadend_agent")
    package.__path__ = [str(PACKAGE_ROOT)]
    sys.modules["deadend_agent"] = package

if "deadend_agent.tools" not in sys.modules:
    tools_package = types.ModuleType("deadend_agent.tools")
    tools_package.__path__ = [str(PACKAGE_ROOT / "tools")]
    sys.modules["deadend_agent.tools"] = tools_package

for module_name in [
    "deadend_agent.tools.avfs",
    "deadend_agent.tools.avfs.avfs",
    "deadend_agent.tools.avfs.list",
    "deadend_agent.tools.avfs.read",
    "deadend_agent.tools.avfs.write",
]:
    sys.modules.pop(module_name, None)

if "deadend_agent.agents" not in sys.modules:
    agents_package = types.ModuleType("deadend_agent.agents")
    agents_package.__path__ = [str(PACKAGE_ROOT / "agents")]
    sys.modules["deadend_agent.agents"] = agents_package

if "deadend_agent.agents.generic_agents" not in sys.modules:
    generic_agents_package = types.ModuleType("deadend_agent.agents.generic_agents")
    generic_agents_package.__path__ = [str(PACKAGE_ROOT / "agents" / "generic_agents")]
    sys.modules["deadend_agent.agents.generic_agents"] = generic_agents_package

pydantic_ai_module = sys.modules.get("pydantic_ai")
if pydantic_ai_module is None:
    pydantic_ai_module = types.ModuleType("pydantic_ai")
    sys.modules["pydantic_ai"] = pydantic_ai_module


class Tool:
    def __init__(self, function, **_kwargs):
        self.function = function


class DeferredToolRequests:
    pass


class DeferredToolResults:
    pass


class RunContext:
    def __init__(self, deps=None):
        self.deps = deps

    def __class_getitem__(cls, _item):
        return cls


class RunUsage:
    pass


class UsageLimits:
    def __init__(self, *args, **kwargs):
        pass


pydantic_ai_module.Tool = getattr(pydantic_ai_module, "Tool", Tool)
pydantic_ai_module.DeferredToolRequests = getattr(pydantic_ai_module, "DeferredToolRequests", DeferredToolRequests)
pydantic_ai_module.DeferredToolResults = getattr(pydantic_ai_module, "DeferredToolResults", DeferredToolResults)
pydantic_ai_module.RunContext = getattr(pydantic_ai_module, "RunContext", RunContext)
pydantic_ai_module.RunUsage = getattr(pydantic_ai_module, "RunUsage", RunUsage)
pydantic_ai_module.UsageLimits = getattr(pydantic_ai_module, "UsageLimits", UsageLimits)

if "pydantic_ai.usage" not in sys.modules:
    usage_module = types.ModuleType("pydantic_ai.usage")

    class RunUsage:
        pass

    class UsageLimits:
        def __init__(self, *args, **kwargs):
            pass

    usage_module.RunUsage = RunUsage
    usage_module.UsageLimits = UsageLimits
    sys.modules["pydantic_ai.usage"] = usage_module

if "pydantic" not in sys.modules:
    pydantic_module = types.ModuleType("pydantic")

    class BaseModel:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    def Field(*, default=None, default_factory=None, description=None):
        if default_factory is not None:
            return default_factory()
        return default

    pydantic_module.BaseModel = BaseModel
    pydantic_module.Field = Field
    sys.modules["pydantic"] = pydantic_module

if "deadend_agent.logging" not in sys.modules:
    logging_module = types.ModuleType("deadend_agent.logging")
    logging_module.logger = object()
    sys.modules["deadend_agent.logging"] = logging_module

if "deadend_agent.config.settings" not in sys.modules:
    settings_module = types.ModuleType("deadend_agent.config.settings")

    class ModelSpec:
        pass

    class Config:
        agents_storage_root = str(Path("/tmp") / "deadend-agent-tests")

        @classmethod
        def get_local_agent_id(cls):
            return uuid4()

    settings_module.Config = Config
    settings_module.ModelSpec = ModelSpec
    sys.modules["deadend_agent.config.settings"] = settings_module

if "deadend_agent.models.registry" not in sys.modules:
    registry_module = types.ModuleType("deadend_agent.models.registry")

    class EmbedderClient:
        pass

    registry_module.EmbedderClient = EmbedderClient
    sys.modules["deadend_agent.models.registry"] = registry_module

if "deadend_agent.embedders.code_indexer" not in sys.modules:
    code_indexer_module = types.ModuleType("deadend_agent.embedders.code_indexer")

    class SourceCodeIndexer:
        def __init__(self, *args, **kwargs):
            pass

    code_indexer_module.SourceCodeIndexer = SourceCodeIndexer
    sys.modules["deadend_agent.embedders.code_indexer"] = code_indexer_module

if "deadend_agent.context" not in sys.modules:
    context_module = types.ModuleType("deadend_agent.context")

    class ContextEngine:
        def __init__(self, *args, **kwargs):
            self.target = None

        def set_target(self, target):
            self.target = target

    context_module.ContextEngine = ContextEngine
    sys.modules["deadend_agent.context"] = context_module

if "deadend_agent.rag.sqlite_connector" not in sys.modules:
    rag_module = types.ModuleType("deadend_agent.rag.sqlite_connector")

    class SqliteRagConnector:
        pass

    rag_module.SqliteRagConnector = SqliteRagConnector
    sys.modules["deadend_agent.rag.sqlite_connector"] = rag_module

if "deadend_agent.sandbox.sandbox" not in sys.modules:
    sandbox_module = types.ModuleType("deadend_agent.sandbox.sandbox")

    class Sandbox:
        pass

    sandbox_module.Sandbox = Sandbox
    sys.modules["deadend_agent.sandbox.sandbox"] = sandbox_module

for module_name, class_name in [
    ("deadend_agent.agents.reporter", "ReporterAgent"),
    ("deadend_agent.agents.architecture", "ADaPTAgent"),
    ("deadend_agent.agents.recon_threatmodel_agent", "ReconThreatModelAgent"),
    ("deadend_agent.agents.exploit_web_agent", "PlannerExploitAgent"),
]:
    if module_name not in sys.modules:
        module = types.ModuleType(module_name)
        module.__dict__[class_name] = type(class_name, (), {})
        sys.modules[module_name] = module

if "deadend_agent.agents.components.executor" not in sys.modules:
    executor_module = types.ModuleType("deadend_agent.agents.components.executor")

    class ResultEvent:
        pass

    class AgentExecutor:
        def __init__(self, *args, **kwargs):
            self.dependencies = {}
            self.memory_context = ""
            self.auth_session_key = ""

        def set_dependencies(self, **kwargs):
            self.dependencies = kwargs

        def set_memory_context(self, memory_context: str):
            self.memory_context = memory_context

        def set_auth_session_key(self, auth_session_key: str):
            self.auth_session_key = auth_session_key

    executor_module.ResultEvent = ResultEvent
    executor_module.AgentExecutor = AgentExecutor
    sys.modules["deadend_agent.agents.components.executor"] = executor_module

if "deadend_agent.agents.components.planner" not in sys.modules:
    planner_module = types.ModuleType("deadend_agent.agents.components.planner")
    planner_module.Planner = type("Planner", (), {})
    planner_module.TaskNode = type("TaskNode", (), {})
    sys.modules["deadend_agent.agents.components.planner"] = planner_module

if "deadend_agent.agents.components.validator" not in sys.modules:
    validator_module = types.ModuleType("deadend_agent.agents.components.validator")

    class Validator:
        def __init__(self, *args, **kwargs):
            pass

    validator_module.Validator = Validator
    sys.modules["deadend_agent.agents.components.validator"] = validator_module

if "deadend_agent.utils.structures" not in sys.modules:
    structures_module = types.ModuleType("deadend_agent.utils.structures")

    class ShellRunner:
        def __init__(self, session: str, sandbox):
            self.session = session
            self.sandbox = sandbox

    @dataclass
    class ShellDeps:
        shell_runner: ShellRunner
        session_id: str
        workspace_root: str | None = None
        memory_workspace_root: str | None = None
        memory_context: str = ""

    @dataclass
    class RequesterDeps:
        embedder_client: object
        rag: object
        target: str
        session_id: object
        embedding_session_id: object | None = None
        memory_workspace_root: str | None = None
        memory_context: str = ""

    @dataclass
    class WebappreconDeps:
        embedder_client: object
        rag: object
        target: str
        shell_runner: ShellRunner
        session_id: object
        embedding_session_id: object | None = None
        memory_workspace_root: str | None = None
        memory_context: str = ""

    @dataclass
    class MemoryWorkspaceDeps:
        session_id: str
        memory_workspace_root: str | None = None
        memory_context: str = ""

    structures_module.MemoryWorkspaceDeps = MemoryWorkspaceDeps
    structures_module.RequesterDeps = RequesterDeps
    structures_module.ShellDeps = ShellDeps
    structures_module.ShellRunner = ShellRunner
    structures_module.WebappreconDeps = WebappreconDeps
    sys.modules["deadend_agent.utils.structures"] = structures_module

if "deadend_agent.tools.browser_automation.http_parser" not in sys.modules:
    http_parser_module = types.ModuleType("deadend_agent.tools.browser_automation.http_parser")

    def extract_host_port(target_host: str):
        return "example.com", 443

    http_parser_module.extract_host_port = extract_host_port
    sys.modules["deadend_agent.tools.browser_automation.http_parser"] = http_parser_module

if "deadend_prompts" not in sys.modules:
    prompts_module = types.ModuleType("deadend_prompts")

    def render_agent_instructions(*args, **kwargs):
        return "instructions"

    def render_tool_description(tool_name: str, **kwargs):
        return tool_name

    prompts_module.render_agent_instructions = render_agent_instructions
    prompts_module.render_tool_description = render_tool_description
    sys.modules["deadend_prompts"] = prompts_module

if "deadend_agent.agents.factory" not in sys.modules:
    factory_module = types.ModuleType("deadend_agent.agents.factory")

    class AgentOutput:
        pass

    class AgentRunner:
        def __init__(self, name, model, instructions, deps_type, output_type, tools):
            self.name = name
            self.model = model
            self.instructions = instructions
            self.deps_type = deps_type
            self.output_type = output_type
            self.tools = tools
            self.agent = types.SimpleNamespace(tools=tools)

    factory_module.AgentOutput = AgentOutput
    factory_module.AgentRunner = AgentRunner
    sys.modules["deadend_agent.agents.factory"] = factory_module

if "deadend_agent.tools" in sys.modules:
    tools_module = sys.modules["deadend_agent.tools"]

    async def sandboxed_shell_tool(*args, **kwargs):
        return "ok"

    async def avfs_list(*args, **kwargs):
        return []

    async def avfs_read(*args, **kwargs):
        return ""

    async def avfs_write(*args, **kwargs):
        return ""

    async def avfs_grep(*args, **kwargs):
        return []

    tools_module.sandboxed_shell_tool = sandboxed_shell_tool
    tools_module.avfs_list = avfs_list
    tools_module.avfs_read = avfs_read
    tools_module.avfs_write = avfs_write
    tools_module.avfs_grep = avfs_grep

from deadend_agent.deadend_agent import DeadEndAgent
from deadend_agent.tools.avfs import avfs
from deadend_agent.agents.generic_agents.shell_agent import ShellAgent


def test_deadend_agent_mounts_workspace_root_for_session(tmp_path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    storage_root = tmp_path / "agents"
    embedding_session_id = uuid4()

    agent = DeadEndAgent(
        session_id=uuid4(),
        embedding_session_id=embedding_session_id,
        model=object(),
        available_agents={},
        workspace_root=str(workspace_root),
        agents_storage_root=str(storage_root),
        local_agent_id=UUID("11111111-1111-1111-1111-111111111111"),
    )
    agent.target = "https://example.com"
    agent.prepare_dependencies(
        embedder_client=object(),
        rag_connector=object(),
        sandbox=object(),
        target="https://example.com",
    )

    assert avfs.current_workspace_root(session_id=str(agent.agent_id)) == workspace_root.resolve()
    assert avfs.current_workspace_root(session_id=str(agent.agent_id), workspace="memory") == (
        storage_root / "11111111-1111-1111-1111-111111111111" / str(embedding_session_id) / "memory"
    ).resolve()
    assert agent.shell_deps is not None
    assert str(agent.agent_id) == "11111111-1111-1111-1111-111111111111"
    assert str(agent.shell_deps.session_id) == str(agent.agent_id)
    assert agent.shell_deps.workspace_root == str(workspace_root.resolve())
    assert agent.memory_workspace_root == str((storage_root / "11111111-1111-1111-1111-111111111111" / str(embedding_session_id) / "memory").resolve())
    assert agent.shell_deps.memory_workspace_root == str((storage_root / "11111111-1111-1111-1111-111111111111" / str(embedding_session_id) / "memory").resolve())


def test_shell_agent_exposes_only_shell_tool():
    agent = ShellAgent(
        model=object(),
        deps_type=None,
        target_information="target",
        requires_approval=False,
    )

    tool_names = [tool.function.__name__ for tool in agent.tools]
    assert tool_names == [
        "sandboxed_shell_tool",
    ]


def test_deadend_agent_loads_memory_context_into_dependencies(tmp_path, monkeypatch):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    storage_root = tmp_path / "agents"
    embedding_session_id = uuid4()

    agent = DeadEndAgent(
        session_id=uuid4(),
        embedding_session_id=embedding_session_id,
        model=object(),
        available_agents={},
        workspace_root=str(workspace_root),
        agents_storage_root=str(storage_root),
        local_agent_id=UUID("11111111-1111-1111-1111-111111111111"),
    )
    agent.target = "https://example.com"
    agent.prepare_dependencies(
        embedder_client=object(),
        rag_connector=object(),
        sandbox=object(),
        target="https://example.com",
    )

    memory_module = sys.modules["deadend_agent.deadend_agent"]

    class FakeMemoryAgent:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, *args, **kwargs):
            return types.SimpleNamespace(output="previous exploit worked")

    monkeypatch.setattr(memory_module, "MemoryAgent", FakeMemoryAgent)

    asyncio.run(agent._populate_memory_context("test objective"))

    assert agent.memory_context == "previous exploit worked"
    assert agent.shell_deps is not None
    assert agent.requester_deps is not None
    assert agent.webapprecon_deps is not None
    assert agent.shell_deps.memory_context == "previous exploit worked"
    assert agent.requester_deps.memory_context == "previous exploit worked"
    assert agent.webapprecon_deps.memory_context == "previous exploit worked"
