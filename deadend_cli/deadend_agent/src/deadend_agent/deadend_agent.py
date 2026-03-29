"""Main DeadEnd agent orchestration module."""
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Generator
from uuid import UUID

from deadend_agent.logging import logger

from pydantic_ai import RunUsage, UsageLimits
from deadend_agent.config.settings import Config, ModelSpec
from deadend_agent.models.registry import EmbedderClient
from deadend_agent.embedders.code_indexer import SourceCodeIndexer
from deadend_agent.context import ContextEngine
from deadend_agent.rag.sqlite_connector import SqliteRagConnector
from deadend_agent.sandbox.sandbox import Sandbox
from deadend_agent.agents.reporter import ReporterAgent, ReporterDeps
from deadend_agent.agents.architecture import ADaPTAgent
from deadend_agent.agents.generic_agents.memory_agent import MemoryAgent
from deadend_agent.agents.components.executor import AgentExecutor, ResultEvent
from deadend_agent.agents.components.planner import Planner, TaskNode
from deadend_agent.agents.components.validation_strategies import (
    ValidationConfig,
    ValidationGate,
    build_validation_gate,
    load_validation_config,
)
from deadend_agent.utils.structures import (
    MemoryWorkspaceDeps,
    RequesterDeps,
    ShellDeps,
    ShellRunner,
    WebappreconDeps
)
from deadend_agent.tools.browser_automation.http_parser import extract_host_port
from deadend_agent.tools.avfs import avfs
from .agents.recon_threatmodel_agent import ReconThreatModelAgent
from .agents.exploit_web_agent import PlannerExploitAgent

ApprovalCallback = Callable[..., Awaitable[str]]


class DeadEndAgent:
    """Main orchestrator for the DeadEnd security research framework."""

    agent_id: UUID
    session_id: UUID
    embedding_session_id: UUID
    model: ModelSpec
    embedder_model: EmbedderClient | None = None
    available_agents: Dict[str, str]
    context: ContextEngine
    goal_achieved: bool = False
    interrupted: bool = False
    approval_callback: ApprovalCallback | None = None
    target: str | None = None
    code_indexer: SourceCodeIndexer | None = None
    threat_model_agent: ReconThreatModelAgent
    exploit_agent: PlannerExploitAgent | None = None
    planner: Planner
    executor: AgentExecutor
    validation_gate: ValidationGate
    reporter: ReporterAgent
    adapt_agent: ADaPTAgent
    shell_deps: ShellDeps | None = None
    requester_deps: RequesterDeps | None = None
    webapprecon_deps: WebappreconDeps | None = None
    challenge_name: str | None = None
    local_agent_id: UUID


    def __init__(
        self,
        session_id: UUID,
        model: ModelSpec,
        available_agents: Dict[str, str],
        max_depth: int = 3,
        validation_config_path: str | None = None,
        embedding_session_id: UUID | None = None,
        workspace_root: str | None = None,
        agents_storage_root: str | None = None,
        local_agent_id: UUID | None = None,
    ):
        self.session_id = session_id
        self.embedding_session_id = embedding_session_id or session_id
        self.max_depth = max_depth
        self.model = model
        self.available_agents = available_agents

        # Load validation config from YAML (falls back to defaults).
        self.validation_config = load_validation_config(validation_config_path)

        # Build composable validation gate from the loaded config.
        self.validation_gate = build_validation_gate(
            config=self.validation_config,
            model=model,
        )

        # Reporter agent for writing assessment reports on validation stop.
        self.reporter = ReporterAgent(
            model=model,
            validation_type=self.validation_config.validation_type,
            validation_format=self.validation_config.validation_format,
        )

        self.context = ContextEngine(model=self.model, session_id=session_id)
        self.workspace_root: str | None = None
        self.local_agent_id = local_agent_id or Config.get_local_agent_id()
        self.agent_id = self.local_agent_id
        self.agents_storage_root = agents_storage_root or Config.agents_storage_root
        self.memory_workspace_root = self._prepare_memory_workspace()
        self.memory_context = ""
        avfs.mount(
            workspace_root=self.memory_workspace_root,
            session_id=str(self.agent_id),
            workspace="memory",
        )
        if workspace_root is not None:
            self.set_workspace_root(workspace_root)


################################################################################
#### Interruptions handling
################################################################################
    def interrupt_workflow(self) -> Generator[str, None, None]:
        """Interrupt the workflow execution.
        
        This method sets the interrupted flag to True, which will cause
        the workflow to stop at the next check point.
        """
        self.interrupted = True
        yield "[yellow]Workflow interruption requested...[/yellow]"

    def reset_workflow_state(self) -> Generator[str, None, None]:
        """Reset the workflow state for a new execution.
        
        This method resets the goal_achieved flag and interrupted flag
        to allow for a fresh workflow execution. Also creates a new context
        engine with a new session ID.
        """
        self.goal_achieved = False
        self.interrupted = False

        yield "[green]Workflow state reset for new execution[/green]"

    def set_approval_callback(self, callback):
        """Set a callback function for user approval input.
        
        Args:
            callback: Async function that returns user input for approval
        """
        self.approval_callback = callback

    def set_workspace_root(self, workspace_root: str | None) -> None:
        """Configure the AVFS workspace for this agent session."""
        if workspace_root is None:
            self.workspace_root = None
            avfs.umount(session_id=str(self.agent_id), workspace="workspace")
            return

        avfs.mount(workspace_root=workspace_root, session_id=str(self.agent_id), workspace="workspace")
        mounted_root = avfs.current_workspace_root(session_id=str(self.agent_id), workspace="workspace")
        self.workspace_root = None if mounted_root is None else str(mounted_root)

    def _prepare_memory_workspace(self) -> str:
        """Ensure the persistent memory workspace exists for this local agent."""
        memory_root = (
            Path(self.agents_storage_root).expanduser().resolve()
            / str(self.local_agent_id)
            / str(self.embedding_session_id)
            / "memory"
        )
        memory_root.mkdir(parents=True, exist_ok=True)
        return str(memory_root)

    async def _populate_memory_context(self, task_query: str) -> str:
        """Refresh task-specific memory context right before supervisor execution."""
        memory_agent = MemoryAgent(
            model=self.model,
            deps_type=MemoryWorkspaceDeps,
        )
        memory_deps = MemoryWorkspaceDeps(
            session_id=str(self.agent_id),
            memory_workspace_root=self.memory_workspace_root,
        )
        result = await memory_agent.run(
            prompt=(
                f"Current task:\n{task_query}\n\n"
                "Inspect the persistent memory workspace using AVFS tools with workspace=\"memory\". "
                "Return only a concise task-relevant memory summary as plain text for the supervisor. "
                "If memory is empty or not useful for this task, return a short plain-text statement saying that no relevant persisted memory is available."
            ),
            deps=memory_deps,
            message_history=[],
            usage=RunUsage(),
            usage_limits=UsageLimits(request_limit=None, tool_calls_limit=None),
            deferred_tool_results=None,
        )

        output = getattr(result, "output", None)
        self.memory_context = str(output).strip() if output is not None else ""
        if hasattr(self, "executor"):
            self.executor.set_memory_context(self.memory_context)
        if self.shell_deps is not None:
            self.shell_deps.memory_context = self.memory_context
        if self.requester_deps is not None:
            self.requester_deps.memory_context = self.memory_context
        if self.webapprecon_deps is not None:
            self.webapprecon_deps.memory_context = self.memory_context
        return self.memory_context
##################################################################################

##################################################################################
################ Initialization of resources
##################################################################################
    def init_webtarget_indexer(self, target: str) -> None:
        """Initialize the web target indexer for the given target.
        
        Sets up the source code indexer to crawl and analyze a web target.
        This enables the agent to understand the target's structure and retrieve
        relevant code sections during conversation.
        
        Args:
            target: URL of the web target to index (e.g., "https://example.com")
            
        Note:
            Must be called before crawl_target() and embed_target() methods.
        """
        self.target = target
        self.context.set_target(target)
        self.code_indexer = SourceCodeIndexer(
            target=self.target,
            session_id=self.embedding_session_id
        )


    async def crawl_target(self):
        """Crawl the web target to gather resources.
        
        Asynchronously crawls the configured web target to extract discoverable
        resources including pages, endpoints, and other web assets.
        
        Returns:
            Crawled web resources suitable for embedding and analysis
            
        Raises:
            Various web crawling exceptions if the target is unreachable
            
        Note:
            Requires init_webtarget_indexer() to be called first.
        """
        if self.code_indexer is None:
            raise ValueError(
                "Web target indexer is not initialized. "
                "Call init_webtarget_indexer() before crawl_target()."
            )
        return await self.code_indexer.crawl_target()

    async def embed_target(self, embedder_client: EmbedderClient):
        """Generate embeddings for the crawled target content.
        
        Returns:
            Serialized embedded code sections
        """
        if self.code_indexer is None:
            raise ValueError(
                "Web target indexer is not initialized. "
                "Call init_webtarget_indexer() before serialized_embedded_code()."
            )
        return await self.code_indexer.serialized_embedded_code(
            embedder_client=embedder_client
        )

##################################################################################

##################################################################################
########## Agentic Ops
##################################################################################

    def register_agents(self, agents: dict[str, str]) -> None:
        """Register available agents for the workflow.
        
        Args:
            agents: List of agent names to register
        """
        self.available_agents = agents

    def prepare_dependencies(
        self,
        *,
        embedder_client: EmbedderClient,
        rag_connector: SqliteRagConnector | Any,
        sandbox: Sandbox | None,
        target: str | None = None,
    ) -> None:
        """Instantiate dependency containers used by downstream agents."""
        if sandbox is None:
            raise ValueError("sandbox must be provided to initialize dependencies.")

        target_host = target or self.target
        if target_host is None:
            raise ValueError("target must be provided before initializing dependencies.")


        shell_runner = ShellRunner(session=str(self.agent_id), sandbox=sandbox)

        self.shell_deps = ShellDeps(
            shell_runner=shell_runner,
            session_id=self.agent_id,
            workspace_root=self.workspace_root,
            memory_workspace_root=self.memory_workspace_root,
            memory_context=self.memory_context,
        )
        self.requester_deps = RequesterDeps(
            embedder_client=embedder_client,
            rag=rag_connector,
            target=target_host,
            session_id=self.session_id,
            embedding_session_id=self.embedding_session_id,
            memory_workspace_root=self.memory_workspace_root,
            memory_context=self.memory_context,
        )
        self.webapprecon_deps = WebappreconDeps(
            embedder_client=embedder_client,
            rag=rag_connector,
            target=target_host,
            shell_runner=shell_runner,
            session_id=self.session_id,
            embedding_session_id=self.embedding_session_id,
            memory_workspace_root=self.memory_workspace_root,
            memory_context=self.memory_context,
        )
        self.executor = AgentExecutor(
            model=self.model,
            context=self.context,
            available_agents=self.available_agents,
            session_id=str(self.agent_id)
        )
        self.executor.set_auth_session_key(self._target_session_key())
        self.executor.set_memory_context(self.memory_context)

        self.executor.set_dependencies(
            requester_deps=self.requester_deps,
            shell_deps=self.shell_deps,
            webapprecon_deps=self.webapprecon_deps
        )
#################################################################################
########### ThreatModel
#################################################################################
    async def threat_model(self, task: str):
        """Execute the threat modeling and orchestration workflow.

        Args:
            task: The security testing task to perform
            context: Optional context dictionary

        Returns:
            TaskNode with the execution plan and results
        """
        # Simplified: directly use the executor's supervisor pattern
        # instead of going through the full ADaPT agent loop

        validation_token: str = ""
        traces: list[str | dict[str, Any]] = []

        prompt_task = f"""
Prepare the necessary information (reconnaissance) to achieve the following task: {task}

Focus on gathering ONLY the information needed for this specific task. Be precise - every piece of information must be retrieved from tooling responses, nothing should be invented or assumed.

What to discover:
- Endpoints relevant to the task and how to use them
- What data/parameters each endpoint needs
- Authentication requirements (which endpoints need auth, which don't)
- Session management and authentication mechanisms
- Any suspicious or interesting behavior related to the task

Critical rules:
- Do NOT use nmap or similar scanning on localhost (127.0.0.1)
- Make requests to the target and analyze responses
- Follow forms, links, and endpoints to discover relevant information
- Extract endpoints, authentication info, and secrets from actual tool responses
- Do NOT invent or guess endpoints - only use what is discovered
- Return when you have gathered sufficient information to proceed with the task
"""

        # Create a simple task node for the threat model
        task_node = TaskNode(
            task=prompt_task,
            depth=0,
            confidence_score=0.7,
            status="pending",
            parent=None,
            children=[]
        )

        # Set root task in context
        self.context.set_root_task(task)

        # Get unified context for the executor
        unified_context = self.context.get_unified_context(max_tokens=6000)
        target_context =f"Target : {self.context.target}"
        context = {}
        confidence_score = 0.0
        # Run the supervisor directly
        async for event in self.executor.execute_supervisor(
            task_node=task_node,
            agent_context=target_context,
            usage=RunUsage(),
            usage_limits=UsageLimits(request_limit=None, tool_calls_limit=None)
        ):
            traces.append(event.model_dump())
            if isinstance(event, ResultEvent):
                confidence_score = event.confidence_score
                context = event.context

        task_node.confidence_score = confidence_score
        task_node.status = "completed"

        reporter_agent = ReporterAgent(
            model=self.model,
            validation_format="Information",
            validation_type="security assessment",
        )
        # context_text = await self.context.get_all_context()
        prompt_assessment = f"""\
Summarize the security assessment results from the reconnaissance phase.
Write the report to `reports/recon_report.md` using the write_workspace_file tool.

IMPORTANT:
- Preserve EXACT working payloads character-for-character
- Include full HTTP requests that succeeded
- Include response snippets proving vulnerabilities
- Document filter bypass techniques with exact encoding used
- Note validation status (reflected vs executed, needs browser test)

## Assessment Data
{context}
"""
        threat_model_data = await reporter_agent.run(
            prompt=prompt_assessment,
            deps=ReporterDeps(session_id=str(self.agent_id)),
            usage=RunUsage(),
            usage_limits=UsageLimits(),
            deferred_tool_results=None,
            message_history=""
        )

        return task_node, context, validation_token

    async def threat_model_stream(self, task: str):
        """Execute the threat modeling and orchestration workflow.

        Args:
            task: The security testing task to perform
            context: Optional context dictionary

        Returns:
            TaskNode with the execution plan and results
        """
        prompt_task = f"""
Prepare the necessary information (reconnaissance) to achieve the following task: {task}

Focus on gathering ONLY the information needed for this specific task. Be precise - every piece of information must be retrieved from tooling responses, nothing should be invented or assumed.

What to discover:
- Endpoints relevant to the task and how to use them
- What data/parameters each endpoint needs
- Authentication requirements (which endpoints need auth, which don't)
- Session management and authentication mechanisms
- Any suspicious or interesting behavior related to the task

Critical rules:
- Do NOT use nmap or similar scanning on localhost (127.0.0.1)
- Make requests to the target and analyze responses
- Follow forms, links, and endpoints to discover relevant information
- Extract endpoints, authentication info, and secrets from actual tool responses
- Do NOT invent or guess endpoints - only use what is discovered
- Return when you have gathered sufficient information to proceed with the task
"""
        validation_token: str = ""
        task_root = TaskNode(
            task=prompt_task,
            depth=0,
            confidence_score=0.7,
            status="pending",
            parent=None,
            children=[]
        )

        self.context.set_root_task(task_root.task)

        target_context =f"Target : {self.context.target}"
        context = {}
        confidence_score = 0.0 
         # Run the supervisor directly
        async for event in self.executor.execute_supervisor(
            task_node=task_root,
            agent_context=target_context,
            usage=RunUsage(),
            usage_limits=UsageLimits(request_limit=None, tool_calls_limit=None)
        ):
            # interrupt signal
            if self.interrupted:
                return
            # traces.append(event)
            if isinstance(event, ResultEvent):
                confidence_score = event.confidence_score
                context = event.context
                yield event.context

        task_root.confidence_score = confidence_score
        task_root.status = "completed"

        reporter_agent = ReporterAgent(
            model=self.model,
            validation_format="Information",
            validation_type="security assessment",
        )
        # context_text = await self.context.get_all_context()
        prompt_assessment = f"""\
Summarize the security assessment results from the reconnaissance phase.
Write the report to `reports/recon_report.md` using the write_workspace_file tool.

IMPORTANT:
- Preserve EXACT working payloads character-for-character
- Include full HTTP requests that succeeded
- Include response snippets proving vulnerabilities
- Document filter bypass techniques with exact encoding used
- Note validation status (reflected vs executed, needs browser test)

## Assessment Data
{context}
"""
        threat_model_data = await reporter_agent.run(
            prompt=prompt_assessment,
            deps=ReporterDeps(session_id=str(self.agent_id)),
            usage=RunUsage(),
            usage_limits=UsageLimits(),
            deferred_tool_results=None,
            message_history=""
        )

        yield threat_model_data

    async def run_exploitation(self, threat_model: str, task: str):
        """Runs the exploitation workflow"""
        # Create exploit agent as planner
        self.exploit_agent = PlannerExploitAgent(
            model=self.model,
            deps_type=str,  # session_key will be passed as string
            target_information=f"{self.target}"
        )

        # IMPORTANT: Preserve previous context (discoveries, exploits) before clearing log
        # Get unified context which contains confirmed exploits and discoveries
        previous_context = self.context.get_unified_context(max_tokens=4000)

        # Clear only the execution log, but keep facts and successful attempts
        # This preserves what worked in reconnaissance for exploitation
        self.context.structured.clear_current_log()

        # Pass session_key as deps for the exploit agent
        self.planner = Planner(planner_agent=self.exploit_agent, deps=self._target_session_key())
        self.adapt_agent = ADaPTAgent(
            session_id=self.session_id,
            agent_id=self.agent_id,
            context=self.context,
            executor=self.executor,
            planner=self.planner,
            validation_gate=self.validation_gate,
            reporter=self.reporter,
            max_depth=self.max_depth,
        )
        plan: TaskNode | None = None

        # Build task with unified context from reconnaissance
        # The previous_context contains confirmed exploits and discoveries that should inform exploitation
        task_exploit = f"""
### Primary objective
{task}

### Success validation
The flag that you need to find has the following format : FLAG{{}}.

## Previous Reconnaissance Results
{previous_context}

## Recon/ Threat model assessment Summary
{threat_model}
"""
        traces: list[str | dict[str, Any]] = []
        validation_token = ""

        async for event in self.adapt_agent.run(task=task_exploit):
            # interrupt signal
            if self.interrupted:
                return
            # Collect all events for trace saving
            traces.append(event)

            if isinstance(event, dict):
                if event.get("type") == "result":
                    root_candidate = event.get("root")
                    if isinstance(root_candidate, TaskNode):
                        plan = root_candidate
                elif event.get("validation_token"):
                    validation_token = event.get("validation_token")
                else:
                    logger.debug("Event: %s", event.get("message", str(event)))
            else:
                logger.debug("Event: %s", str(event))

        if plan is None:
            raise RuntimeError("ADaPT agent did not produce a plan.")

        return plan, validation_token

    async def start_testing_stream(self, threat_model: str, task: str):
        """Runs the exploitation workflow"""
        # Create exploit agent as planner
        self.exploit_agent = PlannerExploitAgent(
            model=self.model,
            deps_type=str,  # session_key will be passed as string
            target_information=f"{self.target}"
        )
        # We reset the context to make space and less confusion
        self.context.reset()

        # Pass session_key as deps for the exploit agent
        self.planner = Planner(planner_agent=self.exploit_agent, deps=self._target_session_key())
        self.adapt_agent = ADaPTAgent(
            session_id=self.session_id,
            agent_id=self.agent_id,
            context=self.context,
            executor=self.executor,
            planner=self.planner,
            validation_gate=self.validation_gate,
            reporter=self.reporter,
            max_depth=self.max_depth,
        )
        plan: TaskNode | None = None
        task_exploit = f"""
You final goal is to find a flag that corresponds to the following task : {task}
The flag that you need to find has the following format : FLAG{{}}.
The threat model has been done :
{threat_model}
"""
        async for event in self.adapt_agent.run(task=task_exploit):
            # interrupt signal
            if self.interrupted:
                return
            if isinstance(event, dict):
                if event.get("type") == "result":
                    root_candidate = event.get("root")
                    if isinstance(root_candidate, TaskNode):
                        plan = root_candidate
                else:
                    yield event.get("message", str(event))
            else:
                yield str(event)

        reporter_agent = ReporterAgent(
            model=self.model,
            validation_format="Information",
            validation_type="security assessment",
        )
        # context_text = await self.context.get_all_context()
        prompt_assessment = f"""\
Summarize the security assessment results from the exploitation phase.
Return all the vulnerabilities found, what have been tried, and what have not, and also what you suspect
with the path to reproduce.
Write the report to `reports/exploit_report.md` using the write_workspace_file tool.

IMPORTANT:
- Preserve EXACT working payloads character-for-character
- Include full HTTP requests that succeeded
- Include response snippets proving vulnerabilities
- Document filter bypass techniques with exact encoding used
- Note validation status (reflected vs executed, needs browser test)

## Assessment Data
{self.context.get_unified_context(max_tokens=100000)}
"""
        security_report = await reporter_agent.run(
            prompt=prompt_assessment,
            deps=ReporterDeps(session_id=str(self.agent_id)),
            usage=RunUsage(),
            usage_limits=UsageLimits(),
            deferred_tool_results=None,
            message_history=""
        )

        yield security_report

        if plan is None:
            raise RuntimeError("ADaPT agent did not produce a plan.")

    def _target_session_key(self) -> str:
        """Build a normalized session key from the current target host and port.

        Raises:
            ValueError: If `self.target` has not been set.
        """
        if self.target is None:
            raise ValueError("target must be provided before initializing dependencies.")

        host, port = extract_host_port(target_host=self.target)
        return f"{host}_{port}"


    async def start_supervisor(self, task: str):
        """Execute the threat modeling and orchestration workflow.

        Args:
            task: The security testing task to perform
            context: Optional context dictionary

        Returns:
            TaskNode with the execution plan and results
        """
        prompt_task = f"""
Your goal is to achieve the following task: {task}

## Approach
1. **Gather necessary information**: Use the tools at hand to collect information needed to understand the target and identify potential vulnerabilities
2. **Precisely define the vulnerability**: Based on the gathered information, refine and precisely define what specific vulnerability you need to find to achieve the task
3. **Find the vulnerability**: Systematically search for and identify the vulnerability using the available tools

## Actions to take:
- Discover and map endpoints relevant to the task, understanding how to use them
- Identify what data/parameters each endpoint requires
- Determine authentication requirements (which endpoints need auth, which don't)
- Understand session management and authentication mechanisms
- Analyze application behavior, error messages, and response patterns
- Test for vulnerabilities systematically using the available tools
- **If vulnerability is found**: Document it clearly with proof of concept, payloads, and impact
- **If vulnerability is NOT found**: Explain all tasks performed, testing approaches tried, and provide possible hints or next steps that could lead to finding the vulnerability

## Critical rules:
- Do NOT use nmap or similar scanning on localhost (127.0.0.1)
- Make requests to the target and analyze responses
- Follow forms, links, and endpoints to discover relevant information
- Extract endpoints, authentication info, and secrets from actual tool responses
- Do NOT invent or guess endpoints - only use what is discovered
- Use gathered information to precisely define the vulnerability type you're looking for
- Systematically test and verify the vulnerability once identified
- Return when you have either: (1) successfully found and documented the vulnerability with proof, or (2) exhausted reasonable testing approaches and can explain what was done along with possible hints for finding the vulnerability

## The previous context if available is :
{self.context.get_unified_context()}
"""
        validation_token: str = ""
        task_root = TaskNode(
            task=prompt_task,
            depth=0,
            confidence_score=0.7,
            status="pending",
            parent=None,
            children=[]
        )

        self.context.set_root_task(task_root.task)

        target_context =f"Target : {self.context.target}"
        context = {}
        confidence_score = 0.0 
         # Run the supervisor directly
        async for event in self.executor.execute_supervisor(
            task_node=task_root,
            agent_context=target_context,
            usage=RunUsage(),
            usage_limits=UsageLimits(request_limit=None, tool_calls_limit=None)
        ):
            if isinstance(event, ResultEvent):
                confidence_score = event.confidence_score
                context = event.context
                yield event.context

        task_root.confidence_score = confidence_score
        task_root.status = "completed"

        reporter_agent = ReporterAgent(
            model=self.model,
            validation_format="Information",
            validation_type="security assessment",
        )
        # context_text = await self.context.get_all_context()
        prompt_assessment = f"""\
Summarize the security assessment results from the reconnaissance phase.
Write the report to `reports/recon_report.md` using the write_workspace_file tool.

IMPORTANT:
- Preserve EXACT working payloads character-for-character
- Include full HTTP requests that succeeded
- Include response snippets proving vulnerabilities
- Document filter bypass techniques with exact encoding used
- Note validation status (reflected vs executed, needs browser test)

## Assessment Data
{context}
"""
        threat_model_data = await reporter_agent.run(
            prompt=prompt_assessment,
            deps=ReporterDeps(session_id=str(self.agent_id)),
            usage=RunUsage(),
            usage_limits=UsageLimits(),
            deferred_tool_results=None,
            message_history=""
        )

        yield threat_model_data
