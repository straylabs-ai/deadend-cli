"""Main DeadEnd agent orchestration module."""
import re
from typing import Any, Awaitable, Callable, Dict, Generator
from uuid import UUID

from pydantic_ai import RunUsage, UsageLimits
from deadend_agent.models.registry import AIModel, EmbedderClient
from deadend_agent.embedders.code_indexer import SourceCodeIndexer
from deadend_agent.context import ContextEngine
from deadend_agent.rag.db_cruds import RetrievalDatabaseConnector
from deadend_agent.sandbox.sandbox import Sandbox
from deadend_agent.agents.reporter import ReporterAgent
from deadend_agent.agents.architecture import ADaPTAgent
from deadend_agent.agents.components.executor import AgentExecutor, ResultEvent
from deadend_agent.agents.components.planner import Planner, TaskNode
from deadend_agent.agents.components.validator import Validator
from deadend_agent.utils.structures import (
    RequesterDeps,
    ShellDeps,
    ShellRunner,
    WebappreconDeps
)
from deadend_agent.tools.browser_automation.http_parser import extract_host_port
from .agents.recon_threatmodel_agent import ReconThreatModelAgent
from .agents.exploit_web_agent import PlannerExploitAgent
# from deadend_eval.metrics imporst save_traces

ApprovalCallback = Callable[..., Awaitable[str]]


class DeadEndAgent:
    """Main orchestrator for the DeadEnd security research framework."""

    session_id: UUID
    model: AIModel
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
    validator: Validator
    adapt_agent: ADaPTAgent
    shell_deps: ShellDeps | None = None
    requester_deps: RequesterDeps | None = None
    webapprecon_deps: WebappreconDeps | None = None
    challenge_name: str | None = None


    def __init__(
        self,
        session_id: UUID,
        model: AIModel,
        available_agents: Dict[str, str],
        max_depth: int = 3,
        validation_type: str | None = None,
        validation_format: str | None = None
    ):
        self.session_id = session_id
        self.max_depth = max_depth
        self.model = model
        self.available_agents = available_agents
        self.validator = Validator(
            model=model,
            validation_type=validation_type,
            validation_format=validation_format
        )
        self.context = ContextEngine(model=self.model, session_id=session_id)


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
            session_id=self.session_id
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
        return await self.code_indexer.crawl_target()

    async def embed_target(self, embedder_client: EmbedderClient):
        """Generate embeddings for the crawled target content.
        
        Returns:
            Serialized embedded code sections
        """
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
        rag_connector: RetrievalDatabaseConnector | Any,
        sandbox: Sandbox | None,
        target: str | None = None,
    ) -> None:
        """Instantiate dependency containers used by downstream agents."""
        if sandbox is None:
            raise ValueError("sandbox must be provided to initialize dependencies.")

        target_host = target or self.target
        if target_host is None:
            raise ValueError("target must be provided before initializing dependencies.")


        shell_runner = ShellRunner(session=str(self.session_id), sandbox=sandbox)

        self.shell_deps = ShellDeps(shell_runner=shell_runner)
        self.requester_deps = RequesterDeps(
            embedder_client=embedder_client,
            rag=rag_connector,
            target=target_host,
            session_id=self.session_id
        )
        self.webapprecon_deps = WebappreconDeps(
            embedder_client=embedder_client,
            rag=rag_connector,
            target=target_host,
            shell_runner=shell_runner,
            session_id=self.session_id
        )
        # setup session key
        host, port = extract_host_port(target_host=self.target)
        session_key = f"{host}_{port}"

        self.executor = AgentExecutor(
            model=self.model,
            context=self.context,
            available_agents=self.available_agents,
            session_id=session_key
        )

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
            traces.append(event)
            if isinstance(event, ResultEvent):
                confidence_score = event.confidence_score
                context = event.context

        task_node.confidence_score = confidence_score
        task_node.status = "completed"

        reporter_agent = ReporterAgent(
            model=self.model,
            deps_type=None,
            tools=None,
            validation_format="Information",
            validation_type="security assessment"
        )
        # context_text = await self.context.get_all_context()
        prompt_assessment = f"""\
Summarize the security assessment results from the reconnaissance phase.

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
            deps=None,
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
        # ADaPT agent handles both planning and execution, with router integration
        # The executor within ADaPT uses the router to route tasks to appropriate agents

        # Add a plan to recon for the threat model.
        # The threat model agent is a supervisor that can call
        #  to the router for the generic agent calling
        # Initialize threat model agent for planning
        self.threat_model_agent = ReconThreatModelAgent(
            name="threat_model",
            model=self.model,
            deps_type=RequesterDeps,
            tools=[]
        )

        self.planner = Planner(planner_agent=self.threat_model_agent, deps=self.requester_deps)

        self.adapt_agent = ADaPTAgent(
            session_id=self.session_id,
            context=self.context,
            executor=self.executor,
            planner=self.planner,
            validator=self.validator,
            max_depth=1
        )
        plan: TaskNode | None = None
        async for event in self.adapt_agent.run(task=task, exit_strategy=""):
            if isinstance(event, dict):
                if event.get("type") == "result":
                    root_candidate = event.get("root")
                    if isinstance(root_candidate, TaskNode):
                        plan = root_candidate
                else:
                    yield event.get("message", str(event))
            else:
                yield str(event)
        if plan is None:
            raise RuntimeError("ADaPT agent did not produce a plan.")

        reporter_agent = ReporterAgent(
            model=self.model,
            deps_type=None,
            tools=None,
            validation_format="Information",
            validation_type="security assessment"
        )
        context_text = await self.context.get_all_context()
        prompt_assessment = f"""\
Summarize the security assessment results from the reconnaissance phase.

IMPORTANT:
- Preserve EXACT working payloads character-for-character
- Include full HTTP requests that succeeded
- Include response snippets proving vulnerabilities
- Document filter bypass techniques with exact encoding used
- Note validation status (reflected vs executed, needs browser test)

## Assessment Data
{context_text}
"""
        threat_model_data = await reporter_agent.run(
            prompt=prompt_assessment,
            deps=None,
            usage=RunUsage(),
            usage_limits=UsageLimits(),
            deferred_tool_results=None,
            message_history=""
        )

        yield plan, threat_model_data.output

    async def run_exploitation(self, threat_model: str, task: str):
        """Runs the exploitation workflow"""
        # setup session key for exploit agent
        host, port = extract_host_port(target_host=self.target)
        session_key = f"{host}_{port}"

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
        self.planner = Planner(planner_agent=self.exploit_agent, deps=session_key)
        self.adapt_agent = ADaPTAgent(
            session_id=self.session_id,
            context=self.context,
            executor=self.executor,
            planner=self.planner,
            validator=self.validator,
            max_depth=self.max_depth
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

        async for event in self.adapt_agent.run(task=task_exploit, exit_strategy=""):
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
                    try:
                        print(event.get("message", str(event)))
                    except (BlockingIOError, OSError):
                        pass
            else:
                try:
                    print(str(event))
                except (BlockingIOError, OSError):
                    pass

        if plan is None:
            raise RuntimeError("ADaPT agent did not produce a plan.")

        return plan, validation_token

    async def start_testing_stream(self, threat_model: str, task: str):
        """Runs the exploitation workflow"""
        # setup session key for exploit agent
        host, port = extract_host_port(target_host=self.target)
        session_key = f"{host}_{port}"

        # Create exploit agent as planner
        self.exploit_agent = PlannerExploitAgent(
            model=self.model,
            deps_type=str,  # session_key will be passed as string
            target_information=f"{self.target}"
        )
        # We reset the context to make space and less confusion
        self.context.reset()

        # Pass session_key as deps for the exploit agent
        self.planner = Planner(planner_agent=self.exploit_agent, deps=session_key)
        self.adapt_agent = ADaPTAgent(
            session_id=self.session_id,
            context=self.context,
            executor=self.executor,
            planner=self.planner,
            validator=self.validator,
            max_depth=self.max_depth
        )
        plan: TaskNode | None = None
        task_exploit = f"""
You final goal is to find a flag that corresponds to the following task : {task}
The flag that you need to find has the following format : FLAG{{}}.
The threat model has been done :
{threat_model}
"""
        async for event in self.adapt_agent.run(task=task_exploit, exit_strategy=""):
            if isinstance(event, dict):
                if event.get("type") == "result":
                    root_candidate = event.get("root")
                    if isinstance(root_candidate, TaskNode):
                        plan = root_candidate
                else:
                    yield event.get("message", str(event))
            else:
                yield str(event)

        if plan is None:
            raise RuntimeError("ADaPT agent did not produce a plan.")
