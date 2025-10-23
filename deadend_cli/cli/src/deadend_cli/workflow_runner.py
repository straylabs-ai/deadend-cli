# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Workflow execution engine for orchestrating security research tasks.

This module provides the main workflow runner that coordinates AI agents,
manages task execution, handles file operations, and integrates with various
security tools and databases for comprehensive security assessments.
"""

import os
import mimetypes
import uuid
import json
from pydantic_ai import DeferredToolRequests, DeferredToolResults
from pydantic_ai.usage import RunUsage, UsageLimits
from openai import AsyncOpenAI
import docker

from deadend_cli.console import console_printer
from deadend_sdk.core import Config
from deadend_sdk.models.registry import AIModel
from deadend_sdk.sandbox.sandbox import Sandbox
from deadend_sdk.rag.db_cruds import RetrievalDatabaseConnector
from deadend_sdk.embedders.code_indexer import SourceCodeIndexer
from deadend_sdk.embedders.knowledge_base_indexer import KnowledgeBaseIndexer
from deadend_sdk.context.context_engine import ContextEngine
from deadend_sdk.utils.structures import ShellRunner, WebappreconDeps
from deadend_sdk.agents import (
    AgentRunner,
    Planner, RagDeps, PlannerOutput,
    RouterAgent, RouterOutput,
    JudgeAgent,
    WebappReconAgent,
    ReconShellAgent
)
from deadend_sdk.agents.reporter import ReporterAgent

# TODO: Handling message history to be able to use it in a better way
MAX_ITERATION = 3

def is_binary_file(file_path: str) -> bool:
    """Check if a file is binary based on its MIME type.
    
    Args:
        file_path: Path to the file to check
        
    Returns:
        True if the file is considered binary, False otherwise
    """
    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type is not None and (mime_type.startswith('application/') or mime_type == 'image/svg+xml'):
        return True
    return False

class WorkflowRunner:
    """Main workflow orchestrator for AI agent tasks.
    
    This class manages the execution of AI agents, handles target indexing,
    knowledge base processing, and coordinates the overall workflow execution.
    
    Attributes:
        config: Configuration object containing API keys and settings
        model: AI model instance for agent execution
        code_indexer_db: Database connector for code indexing and retrieval
        sandbox: Sandbox environment for secure code execution
        context: Context engine for managing workflow state
        goal_achieved: Flag indicating if the workflow goal has been completed
        assets_folder: Path to the assets folder
        session_id: Unique identifier for this workflow session
        interrupted: Flag indicating if the workflow has been interrupted
    """
    config: Config
    model: AIModel
    code_indexer_db: RetrievalDatabaseConnector
    sandbox: Sandbox
    context: ContextEngine
    goal_achieved: bool = False
    assets_folder: str
    session_id: uuid.UUID
    interrupted: bool = False
    
    def __init__(
            self,
            model: AIModel,
            config: Config,
            code_indexer_db: RetrievalDatabaseConnector,
            sandbox: Sandbox | None,
            mode: str = "hacker",
        ):
        """Initialize the WorkflowRunner.
        
        Args:
            model: AI model instance for agent execution
            config: Configuration object with API keys and settings
            code_indexer_db: Database connector for code indexing
            sandbox: Optional sandbox environment for secure execution
            mode: Mode for approval requirements ("hacker" requires approval, "yolo" doesn't)
        """
        self.config = config
        self.model = model
        self.code_indexer_db = code_indexer_db
        self.sandbox = sandbox
        self.mode = mode
        self.session_id = uuid.uuid4()
        self.interrupted = False
        self.approval_callback = None  # Callback function for user approval

        # Initialize context engine with session ID
        self.context = ContextEngine(session_id=self.session_id)

    def interrupt_workflow(self) -> None:
        """Interrupt the workflow execution.
        
        This method sets the interrupted flag to True, which will cause
        the workflow to stop at the next check point.
        """
        self.interrupted = True
        console_printer.print("[yellow]Workflow interruption requested...[/yellow]")

    def reset_workflow_state(self) -> None:
        """Reset the workflow state for a new execution.
        
        This method resets the goal_achieved flag and interrupted flag
        to allow for a fresh workflow execution. Also creates a new context
        engine with a new session ID.
        """
        self.goal_achieved = False
        self.interrupted = False

        console_printer.print("[green]Workflow state reset for new execution[/green]")

    def set_approval_callback(self, callback):
        """Set a callback function for user approval input.
        
        Args:
            callback: Async function that returns user input for approval
        """
        self.approval_callback = callback

    async def summarize_workflow_context(self) -> None:
        """Summarize the workflow context using the reporter agent to stay under token limits.
        
        This method creates a reporter agent and uses it to summarize the current
        workflow context, ensuring it remains under 150,000 tokens while preserving
        all critical security information and findings.
        """
        try:
            # Create reporter agent
            reporter_agent = ReporterAgent(
                model=self.model,
                deps_type=None,
                tools=[],
                validation_type=None,
                validation_format=None
            )

            # Summarize the context
            await reporter_agent.summarize_context(self.context)
            console_printer.print("[green]Workflow context summarized successfully[/green]")
        except Exception as e:
            console_printer.print(f"[red]Error summarizing workflow context: {e}[/red]")

    def _set_assets(self, assets_folder: str) -> None:
        """Set the assets folder path.
        
        Args:
            assets_folder: Path to the assets folder
        """
        self.assets_folder = assets_folder

    def add_assets_to_context(self, assets_folder: str) -> None:
        """Add all non-binary files from the assets folder to the context.
        
        Args:
            assets_folder: Path to the folder containing assets to add
        """
        self._set_assets(assets_folder=assets_folder)
        for root, dirs, files in os.walk(self.assets_folder):
            for file in files:
                file_path = os.path.join(root, file)
                if not is_binary_file(file_path):
                    try:
                        with open(file_path, encoding='utf-8') as file_asset:
                            file_content = file_asset.read()
                            self.context.add_asset_file(file_path, file_content)
                    except (OSError, UnicodeDecodeError) as e:
                        # Skip files that can't be read or decoded
                        console_printer.print(
                            f"[yellow]Warning: Could not read {file_path}: {e}[/yellow]"
                        )

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

    async def embed_target(self):
        """Generate embeddings for the crawled target content.
        
        Returns:
            Serialized embedded code sections
        """
        return await self.code_indexer.serialized_embedded_code(
            openai_api_key=self.config.openai_api_key,
            embedding_model=self.config.embedding_model
        )

    def knowledge_base_init(self, folder_path: str) -> None:
        """Initialize the knowledge base indexer.
        
        Args:
            folder_path: Path to the knowledge base documents folder
        """
        self.knowledge_base_path = folder_path
        self.knowledge_base_indexer = KnowledgeBaseIndexer(
            documents_path=self.knowledge_base_path,
            files_ignored=[]
        )

    async def knowledge_base_index(self):
        """Generate embeddings for knowledge base documents.
        
        Returns:
            Serialized embedded document sections
        """
        return await self.knowledge_base_indexer.serialized_embedded_documents(
            openai_api_key=self.config.openai_api_key,
            embedding_model=self.config.embedding_model
        )

    def register_agents(self, agents: list[str]) -> None:
        """Register available agents for the workflow.
        
        Args:
            agents: List of agent names to register
        """
        self.available_agents = agents

    def register_sandbox_runner(self, network_name: str = "host") -> None:
        """Initialize and start the Docker sandbox environment.
        
        Args:
            network_name: Docker network name for the container (default: "host")
        
        Raises:
            docker.errors.DockerException: If Docker is not available or container fails to start
        """
        docker_client = docker.from_env()
        sandbox = Sandbox(docker_client=docker_client)
        sandbox.start(container_image="xoxruns/sandboxed_kali:latest", network_name=network_name)
        console_printer.print(f"[green]Sandbox started: {sandbox}[/green]")
        self.sandbox = sandbox

    async def plan_tasks(self, goal: str, target: str) -> PlannerOutput:
        """Plan tasks for achieving the given goal on the target.
        
        Args:
            goal: The objective to achieve
            target: The target system or URL
            
        Returns:
            String representation of the planned tasks
            
        Raises:
            InterruptedError: If the workflow is interrupted during planning
        """
        # Check for interruption before planning
        if self.interrupted:
            raise InterruptedError("Workflow interrupted before planning")
            
        openai_embedder = AsyncOpenAI(api_key=self.config.openai_api_key)
        self.context.set_target(target=target)
        self.planner = Planner(
            model=self.model,
            target=target,
            api_spec="",
        )
        usage_planner = RunUsage()
        usage_limits_planner = UsageLimits()

        try:
            resp = await self.planner.run(
                user_prompt=goal,
                message_history="",
                usage=usage_planner,
                usage_limits=usage_limits_planner,
                rag=self.code_indexer_db,
                openai=openai_embedder,
                session_id=self.session_id
            )

            # Check for interruption after planning
            if self.interrupted:
                raise InterruptedError("Workflow interrupted after planning")

            self.context.set_tasks(resp.output.tasks)
            return resp.output.tasks

        except InterruptedError:
            # Re-raise interruption errors
            raise
        except Exception as e:
            # Check if interrupted during exception handling
            if self.interrupted:
                raise InterruptedError("Workflow interrupted during planning") from e
            raise

    async def route_task(self, prompt: str) -> RouterOutput:
        """Route a task to the appropriate agent.
        
        Args:
            prompt: The task prompt to route
            
        Returns:
            Router output containing the selected agent
            
        Raises:
            InterruptedError: If the workflow is interrupted during routing
        """
        # Check for interruption before routing
        if self.interrupted:
            raise InterruptedError("Workflow interrupted before routing")

        self.router = RouterAgent(
            model=self.model,
            deps_type=None,
            available_agents=self.available_agents,
            tools=[]
        )

        usage_router = RunUsage()
        usage_limits_router = UsageLimits()

        try:
            resp = await self.router.run(
                user_prompt=prompt + self.context.get_all_context(),
                deps=None,
                message_history="",
                usage=usage_router,
                usage_limits=usage_limits_router,
                deferred_tool_results=None
            )

            # Check for interruption after routing
            if self.interrupted:
                raise InterruptedError("Workflow interrupted after routing")

            self.context.add_next_agent(resp.output)
            return resp.output

        except InterruptedError:
            # Re-raise interruption errors
            raise
        except Exception as e:
            # Check if interrupted during exception handling
            if self.interrupted:
                raise InterruptedError("Workflow interrupted during routing") from e
            raise

    def _get_agent(self, agent_name: str) -> AgentRunner:
        """Get an agent instance by name.
        
        Args:
            agent_name: Name of the agent to retrieve
            
        Returns:
            AgentRunner instance for the specified agent
        """
        # Determine if approval is required based on mode
        requires_approval = self.mode == "hacker"
        
        match agent_name:
            case "webapp_recon":
                return WebappReconAgent(
                    model=self.model,
                    deps_type=WebappreconDeps,
                    target_information=self.context.target,
                    requires_approval=requires_approval
                )
            case "recon_shell":
                return ReconShellAgent(
                    model=self.model,
                    deps_type=WebappreconDeps,
                    target_information=self.context.target,
                    requires_approval=requires_approval
                )
            case _:
                self.context.add_not_found_agent(agent_name=agent_name)
                return RouterAgent(
                    model=self.model,
                    deps_type=None,
                    tools=[],
                    available_agents=self.available_agents
                )

    async def run_agent(
        self,
        agent_name: str,
        prompt: str | None,
        message_history: str,
        deferred_tool_results: DeferredToolResults | None = None
    ):
        """Execute an agent with the given prompt.
        
        Args:
            agent_name: Name of the agent to run
            prompt: The prompt to send to the agent
            
        Returns:
            Agent response output
            
        Raises:
            InterruptedError: If the workflow is interrupted during execution
        """
        # Check for interruption before starting agent execution
        if self.interrupted:
            raise InterruptedError("Workflow interrupted before agent execution")

        agent = self._get_agent(agent_name=agent_name)
        usage_agent = RunUsage()
        usage_limits_agent = UsageLimits()
        if prompt is None :
            user_prompt = None
        else:
            user_prompt = prompt + self.context.get_all_context()

        try:
            if agent.name == "planner_agent":
                # Check for interruption before planner execution
                if self.interrupted:
                    raise InterruptedError("Workflow interrupted before planner execution")

                openai_embedder = AsyncOpenAI(api_key=self.config.openai_api_key)
                rag_deps = RagDeps(
                    openai=openai_embedder,
                    rag=self.code_indexer_db,
                    target=self.target,
                    session_id=self.session_id
                )
                resp = await agent.run(
                    user_prompt=user_prompt,
                    message_history=message_history,
                    usage=usage_agent,
                    deps=rag_deps,
                    usage_limits=usage_limits_agent,
                    deferred_tool_results=None,
                )
            elif agent_name == "webapp_recon":
                # Check for interruption before webapp recon execution
                if self.interrupted:
                    raise InterruptedError("Workflow interrupted before webapp recon execution")

                openai_embedder = AsyncOpenAI(api_key=self.config.openai_api_key)
                shell_runner = ShellRunner("session_agent", self.sandbox)

                webapprecon_deps = WebappreconDeps(
                    openai=openai_embedder,
                    rag=self.code_indexer_db,
                    target=self.target,
                    shell_runner=shell_runner,
                    session_id=self.session_id
                )
                resp = await agent.run(
                    user_prompt=user_prompt,
                    message_history=message_history,
                    usage=usage_agent,
                    deps=webapprecon_deps,
                    usage_limits=usage_limits_agent,
                    deferred_tool_results=deferred_tool_results
                )
            elif agent_name == "recon_shell":
                # Check for interruption before recon shell execution
                if self.interrupted:
                    raise InterruptedError("Workflow interrupted before recon shell execution")

                openai_embedder = AsyncOpenAI(api_key=self.config.openai_api_key)
                shell_runner = ShellRunner("session_agent", self.sandbox)

                webapprecon_deps = WebappreconDeps(
                    openai=openai_embedder,
                    rag=self.code_indexer_db,
                    target=self.target,
                    shell_runner=shell_runner,
                    session_id=self.session_id
                )
                resp = await agent.run(
                    user_prompt=user_prompt,
                    message_history=message_history,
                    usage=usage_agent,
                    deps=webapprecon_deps,
                    usage_limits=usage_limits_agent,
                    deferred_tool_results=deferred_tool_results
                )
            else:
                # Check for interruption before other agent execution
                if self.interrupted:
                    raise InterruptedError("Workflow interrupted before agent execution")

                resp = await agent.run(
                    user_prompt=user_prompt,
                    deps=None,
                    message_history=message_history,
                    usage=usage_agent,
                    usage_limits=usage_limits_agent,
                    deferred_tool_results=deferred_tool_results
                )

            # Check for interruption after agent execution
            if self.interrupted:
                raise InterruptedError("Workflow interrupted after agent execution")
            if isinstance(resp.output, DeferredToolRequests):
                return resp

            self.context.add_agent_response(resp.output)
            return resp
        except InterruptedError:
            # Re-raise interruption errors
            raise
        except Exception as e:
            # Check if interrupted during exception handling
            if self.interrupted:
                raise InterruptedError("Workflow interrupted during agent execution") from e
            raise

    async def start_workflow(
        self,
        prompt: str,
        target: str,
        validation_type: str | None,
        validation_format: str | None
        ):
        """Start the main workflow execution.
        
        Args:
            prompt: The goal or objective for the workflow
            target: The target system or URL
            validation_type: Type of validation to perform
            validation_format: Format for validation results
            
        Yields:
            str: Messages to be printed by the chat interface
            
        Returns:
            Final judge output from the workflow execution
        """
        # Plan the tasks
        try:
            tasks = await self.plan_tasks(goal=prompt, target=target)
            yield tasks
        except InterruptedError as e:
            console_printer.print(f"[yellow]Workflow interrupted during planning: {e}[/yellow]")
            return

        if validation_type is None:
            validation_type = "canary"

        if validation_format is None:
            validation_format = "What looks more likely a vulnerability or undefined behavior\
                 that is verified with a tool."

        judge_agent = JudgeAgent(
            self.model, None, [],
            validation_type=validation_type,
            validation_format=validation_format
        )
        usage_judge = RunUsage()
        usage_limits_judge = UsageLimits()
        judge_output = ""
        iteration = 0
        while not self.goal_achieved and iteration < MAX_ITERATION and not self.interrupted:
            # Check for interruption before each major step
            if self.interrupted:
                console_printer.print("[yellow]Workflow interrupted by user[/yellow]")
                break

            # Route task to appropriate agent
            try:
                agent_router = await self.route_task(prompt=prompt)
                yield agent_router
            except InterruptedError as e:
                console_printer.print(f"[yellow]Workflow interrupted during routing: {e}[/yellow]")
                break

            # Check for interruption after routing
            if self.interrupted:
                console_printer.print("[yellow]Workflow interrupted by user[/yellow]")
                break

            # Execute the selected agent
            try:
                agent_response = await self.run_agent(
                    agent_name=self.context.next_agent,
                    prompt=prompt + self.context.get_all_context(),
                    message_history=""
                )
                if isinstance(agent_response.output, DeferredToolRequests):
                    messages = [self.context.get_all_context()]
                    messages.extend(agent_response.all_messages())
                    approval =  await self._get_user_approval_for_tool_requests(
                        agent_response,
                        self.context.next_agent
                    )
                    if approval:
                        results = DeferredToolResults()
                        for call in agent_response.output.approvals:
                            result = False
                            if call.tool_name == "send_payload":
                                result = True
                            results.approvals[call.tool_call_id] = result
                        agent_response = await self.run_agent(
                            self.context.next_agent,
                            prompt=None,
                            message_history=messages,
                            deferred_tool_results=results
                        )
                self.context.add_agent_response(agent_response.all_messages_json())
                yield agent_response

            except InterruptedError as e:
                console_printer.print(f"[yellow]Workflow interrupted during agent execution: \
                    {e}[/yellow]")
                break

            # Check for interruption after agent execution
            if self.interrupted:
                console_printer.print("[yellow]Workflow interrupted by user[/yellow]")
                break
                   # Summarize workflow context after completion to manage token limits
            try:
                console_printer.print("\n[bold blue]Summarizing workflow context...[/bold blue]")
                await self.summarize_workflow_context()
            except Exception as e:
                console_printer.print(f"[yellow]Warning: Could not summarize context: {e}[/yellow]")

            iteration += 1

            # Check for interruption before judge execution
            if self.interrupted:
                console_printer.print("[yellow]Workflow interrupted before \
                    judge execution[/yellow]")
                break

            try:
                judge_output = await judge_agent.run(
                    user_prompt=self.context.get_all_context(),
                    deps=None,
                    message_history="",
                    usage=usage_judge,
                    usage_limits=usage_limits_judge
                )
            except InterruptedError as e:
                console_printer.print(f"[yellow]Workflow interrupted during \
                    judge execution: {e}[/yellow]")
                break

            judge_str = str(judge_output)
            self.context.add_agent_response(judge_str)

            if judge_output.output.goal_achieved:
                self.goal_achieved = True


    async def _get_user_approval_for_tool_requests(
        self,
        deferred_requests: DeferredToolRequests,
        agent_name: str
    ) -> bool:
        """Prompt the user for approval on tool requests that require permission.
        
        Args:
            deferred_requests: The deferred tool requests requiring approval
            agent_name: Name of the agent requesting tool execution
            
        Returns:
            bool: True if user approves all requests, False otherwise
        """
        console_printer.print(f"[bold yellow]Agent '{agent_name}' is requesting tool execution that requires approval.[/bold yellow]")

        # Display the tool requests to the user
        for i, tool_request in enumerate(deferred_requests.output.approvals):
            console_printer.print(f"[bold cyan]Tool Request {tool_request.tool_name}:[/bold cyan]")
            console_printer.print(f"[cyan]Arguments:[/cyan] {json.loads(tool_request.args)['raw_request']}")
            console_printer.print("")  # Empty line for separation

        # Use the approval callback if provided, otherwise fall back to basic input
        if hasattr(self, 'approval_callback') and self.approval_callback:
            try:
                user_input = await self.approval_callback()
                if isinstance(user_input, str):
                    approval = user_input.strip().lower() in ['y', 'yes']
                else:
                    approval = bool(user_input)
                return approval
            except Exception as e:
                console_printer.print(f"[red]Error in approval callback: {e}[/red]")
                return False
        else:
            # Fallback to basic input (for backwards compatibility)
            console_printer.print("[bold yellow]Do you approve these tool executions? (y/N): [/bold yellow]", end="")
            try:
                user_input = input().strip().lower()
                approval = user_input in ['y', 'yes']
                return approval
            except (KeyboardInterrupt, EOFError):
                console_printer.print("\n[yellow]Approval cancelled.[/yellow]")
                return False
