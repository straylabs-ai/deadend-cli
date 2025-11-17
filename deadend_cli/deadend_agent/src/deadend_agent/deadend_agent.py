"""Main DeadEnd agent orchestration module."""
from typing import Any, Awaitable, Callable, Dict, Generator
from uuid import UUID
from deadend_agent.models.registry import AIModel
from deadend_agent.embedders.code_indexer import SourceCodeIndexer
from deadend_agent.context import ContextEngine
# from deadend_agent.embedders.knowledge_base_indexer import KnowledgeBaseIndexer
from deadend_agent.agents.architecture import (
    ADaPTAgent,
    AgentRunner,
    AgentExecutor,
    Planner,
    Validator
)
from deadend_agent.utils.structures import RequesterDeps
from .agents.factory import AgentRunner

from .agents.recon_threatmodel_agent import ReconThreatModelAgent

ApprovalCallback = Callable[..., Awaitable[str]]


class DeadEndAgent:
    """Main orchestrator for the DeadEnd security research framework."""

    session_id: UUID
    model: AIModel
    available_agents: Dict[str, str]
    context: ContextEngine
    goal_achieved: bool = False
    interrupted: bool = False
    approval_callback: ApprovalCallback | None = None
    target: str | None = None
    code_indexer: SourceCodeIndexer | None = None
    threat_model_agent: ReconThreatModelAgent
    planner: Planner
    executor: AgentExecutor
    validator: Validator
    adapt_agent: ADaPTAgent

    def __init__(
        self,
        session_id: UUID,
        model: AIModel,
        available_agents: Dict[str, str],
        max_depth: int = 3
    ):
        self.session_id = session_id
        self.model = model
        self.available_agents = available_agents
        self.context = ContextEngine(session_id=session_id)

        # Initialize threat model agent for planning
        self.threat_model_agent = ReconThreatModelAgent(
            name="threat_model",
            model=model,
            deps_type=None,
            output_type=str,
            tools=[]
        )

        # Initialize ADaPT components
        planner_runner = AgentRunner(
            name="planner",
            model=model,
            instructions="Break down security testing tasks into subtasks.",
            deps_type=None,
            output_type=list,
            tools=[]
        )
        self.planner = Planner(planner_agent=planner_runner)

        # executor_runner = ExecutorAgent(
        #     name="executor",
        #     model=model,
        #     instructions="Execute security testing tasks.",
        #     deps_type=None,
        #     output_type=None,
        #     tools=[]
        # )
        # Pass router, model, and available_agents to executor so it can route and execute with specialized agents
        self.executor = AgentExecutor(
            model=self.model,
            context=self.context,
            available_agents=available_agents
        )

        self.validator = Validator(model=model)

        self.context = ContextEngine(session_id=session_id)
        # Initialize ADaPT agent with router-aware executor
        self.adapt_agent = ADaPTAgent(
            session_id=session_id,
            context=self.context,
            executor=self.executor,
            planner=self.planner,
            validator=self.validator,
            max_depth=max_depth
        )

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
        self.code_indexer = SourceCodeIndexer(target=self.target, session_id=self.session_id)


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

    async def embed_target(self, api_key, embedding_model):
        """Generate embeddings for the crawled target content.
        
        Returns:
            Serialized embedded code sections
        """
        return await self.code_indexer.serialized_embedded_code(
            openai_api_key=api_key,
            embedding_model=embedding_model
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
        # ADaPT agent handles both planning and execution, with router integration
        # The executor within ADaPT uses the router to route tasks to appropriate agents

        # Add a plan to recon for the threat model.
        # The threat model agent is a supervisor that can call
        #  to the router for the generic agent calling
        plan = await self.adapt_agent.run(task=task)
        return plan
