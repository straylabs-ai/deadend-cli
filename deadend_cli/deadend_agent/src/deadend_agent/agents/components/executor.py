from dataclasses import dataclass
from typing import Any, Literal, AsyncGenerator
import asyncio
from pydantic import BaseModel
from pydantic_ai import DeferredToolResults, RunContext, UsageLimits, RunUsage, UsageLimitExceeded
from deadend_agent.agents import (
    SupervisorAgent, SupervisorOutput,
    RequesterAgent,
    ShellAgent,
    PythonInterpreterAgent, AgentOutput
)
from deadend_agent.agents.components.planner import TaskNode
from deadend_agent.context import ContextEngine
from deadend_agent.models import AIModel
from deadend_agent.utils.structures import WebappreconDeps, RequesterDeps, ShellDeps


class LogEvent(BaseModel):
    """Event representing a log message during execution."""
    type: Literal["log"] = "log"
    message: str


class ResultEvent(BaseModel):
    """Event representing the final execution result."""
    type: Literal["result"] = "result"
    confidence_score: float
    context: dict[str, Any]

# Union type for all possible executor events
ExecutorEvent = LogEvent | ResultEvent

@dataclass
class SupervisorDeps:
    """Dependencies for supervisor router containing all agents and their deps."""
    requester_agent: RequesterAgent | None
    requester_deps: RequesterDeps | None
    shell_agent: ShellAgent | None
    shell_deps: ShellDeps | None
    python_interpreter_agent: PythonInterpreterAgent
    session_id: str
    message_history: list | None
    usage_limits: UsageLimits
    deferred_tool_results: DeferredToolResults | None
    context: ContextEngine | None = None  # Context engine for storing agent outputs

class AgentExecutor:
    """Executor component that executes tasks using appropriate agents.
    
    The executor uses a router to determine which specialized agent should handle
    each task, then executes the task with that agent. If no specialized agent is
    available, it falls back to a generic runner.
    
    The executor integrates routing, agent selection, and execution in a single
    component that works within the ADaPT framework.
    """
    def __init__(
        self,
        context: ContextEngine,
        model: AIModel,
        available_agents: dict[str, str] | None = None,
        agent_factory: Any | None = None,
        requires_approval: bool = False,
        session_id: str | None = None
    ) -> None:
        """Initialize the AgentExecutor.
        
        Args:
            model: Optional AI model for creating specialized agents
            available_agents: Optional dictionary mapping agent names to descriptions
            agent_factory: Optional callback function(agent_name: str, context: dict) -> AgentRunner
            for custom agent creation. If provided, this takes precedence over 
                built-in agent creation.
        """
        self.model = model
        self.available_agents = available_agents or {}
        self.agent_factory = agent_factory
        self.requires_approval = requires_approval
        self.context = context
        self.session_id = session_id

        self.supervisor = SupervisorAgent(
            model=self.model,
            deps_type=None,
            tools=[],
            available_agents=self.available_agents
        )

        self.requester_deps: RequesterDeps | None = None
        self.shell_deps: ShellDeps | None = None
        self.webapprecon_deps: WebappreconDeps | None = None

    def set_dependencies(
        self,
        requester_deps: RequesterDeps | None = None,
        shell_deps: ShellDeps | None = None,
        webapprecon_deps: WebappreconDeps | None = None,
    ) -> None:
        """Register dependency containers for downstream agents."""
        if requester_deps is not None:
            self.requester_deps = requester_deps
        if shell_deps is not None:
            self.shell_deps = shell_deps
        if webapprecon_deps is not None:
            self.webapprecon_deps = webapprecon_deps

    def _executor_message_yield(self, message) -> SupervisorOutput | AgentOutput | LogEvent | ResultEvent:
        pass

    # async def execute(
    #     self,
    #     task_node: TaskNode,
    #     agent_context: str = "",
    #     usage: RunUsage = RunUsage(),
    #     usage_limits: UsageLimits = UsageLimits(request_limit=None, tool_calls_limit=None),
    #     deferred_tool_results: DeferredToolResults | None = None,
    #     message_history: list | None = None
    # ) -> AsyncGenerator[ExecutorEvent, None]:
    #     """Execute a task node using the appropriate agent.
        
    #     The execution process:
    #     1. Uses the router (if available) to determine which agent should handle the task
    #     2. Attempts to get or create the selected specialized agent
    #     3. Executes the task with the specialized agent or falls back to the generic runner
    #     4. Extracts confidence score and updates context with execution results
        
    #     Args:
    #         task_node: The TaskNode containing the task to execute
    #         context: Current execution context (will be copied and updated)
    #         deps: Optional dependencies to pass to the agent
    #         usage: Usage tracking object
    #         usage_limits: Limits for token usage
    #         deferred_tool_results: Optional deferred tool results from previous runs
    #         message_history: Previous conversation messages for context
            
    #     Yields:
    #         LogEvent instances for streaming updates.
    #         The final event is a ResultEvent instance.
            
    #     Note:
    #         If routing fails or the selected agent cannot be created, execution falls back
    #         to the generic runner. All routing and execution information is logged in the context.
    #     """
    #     context: dict[str, Any] = {"log": ""}
    #     confidence_score: float | None = None

    #     def emit(message: str) -> LogEvent:
    #         """Append a log entry to the context and return it for streaming."""
    #         context["log"] += f"\n{message}"
    #         return LogEvent(message=message)

    #     try:
    #         yield emit(f"Current task: {task_node.task}\n")

    #         routing_info = None
    #         selected_agent: AgentRunner | None = None
    #         if self.router:
    #             try:
    #                 router_result = await self.router.run(
    #                     prompt=f"{agent_context}\nWhich agent should handle: {task_node.task}",
    #                     deps=None,
    #                     message_history=message_history or "",
    #                     usage=usage,
    #                     usage_limits=usage_limits,
    #                     deferred_tool_results=None
    #                 )
    #                 routing_info = router_result.output
    #                 if isinstance(routing_info, RouterOutput):
    #                     yield emit(
    #                         "Selected agent: "
    #                         f"{routing_info.next_agent_name}\nReasoning: {routing_info.reasoning}"
    #                     )
    #                     selected_agent = self._get_agent(routing_info.next_agent_name)
    #                     if selected_agent:
    #                         yield emit(f"Using specialized agent: {routing_info.next_agent_name}")
    #             except Exception as exc:
    #                 yield emit(f"Routing failed: {exc}, using generic executor")

    #         if isinstance(selected_agent, AgentRunner):
    #             result = await self._run_agent(
    #                 agent=selected_agent,
    #                 prompt=agent_context+task_node.task,
    #                 message_history=message_history,
    #                 usage=usage,
    #                 usage_limits=usage_limits,
    #                 deferred_tool_results=deferred_tool_results
    #             )
    #             output = result.output
    #             # print(f"test output : {output}")
    #         else:
    #             output = f"[AGENT RESPONSE] Error in agent running {selected_agent}"

    #         notes = ""
    #         updated_state = {}
    #         if isinstance(output, AgentOutput):
    #             confidence_score = output.confidence_score
    #             notes = output.notes
    #             updated_state = output.updated_state or {}
    #         else:
    #             # Default confidence score when output is not an AgentOutput
    #             confidence_score = 0.5

    #         # yield emit(f"[EXECUTOR] Task: {task_node.task}\nNotes: {notes}\n{output}")
    #         context.update(updated_state)
    #         context["last_output"] = output.model_dump() if isinstance(output, AgentOutput) else str(output)
    #         yield ResultEvent(
    #             confidence_score=confidence_score,
    #             context=context,
    #         )
    #         return
    #     except UsageLimitExceeded as exc:
    #         yield emit(f"[EXECUTOR] Usage limit reached: {exc}")
    #         yield ResultEvent(
    #             confidence_score=confidence_score or 0.5,
    #             context=context,
    #         )
    #         return
    #     except Exception as exc:
    #         yield emit(f"[EXECUTOR] Error: {exc}")
    #         yield ResultEvent(
    #             confidence_score=confidence_score or 0.5,
    #             context=context,
    #         )
    #         return

    async def execute_supervisor(
        self,
        task_node: TaskNode,
        agent_context: str = "",
        usage: RunUsage = RunUsage(),
        usage_limits: UsageLimits = UsageLimits(request_limit=None, tool_calls_limit=None),
        deferred_tool_results: DeferredToolResults | None = None,
        message_history: list | None = None
    ) -> AsyncGenerator[ExecutorEvent, None]:
        """Execute a task using supervisor pattern where router has access to all agents as tools.
        
        This method instantiates all generic agents and makes them available as tools
        to the router agent using agent delegation pattern with RunContext, allowing the 
        router to directly invoke specialized agents as needed.
        
        The execution process:
        1. Instantiates all generic agents (requester, shell, python_interpreter)
        2. Creates a supervisor dependencies dataclass holding all agents and their deps
        3. Creates tool functions using RunContext to delegate to agents
        4. Executes the task with the router, which can now directly call agents
        
        Args:
            task_node: The TaskNode containing the task to execute
            agent_context: Additional context for the agent
            usage: Usage tracking object
            usage_limits: Limits for token usage
            deferred_tool_results: Optional deferred tool results from previous runs
            message_history: Previous conversation messages for context
            
        Yields:
            LogEvent instances for streaming updates.
            The final event is a ResultEvent instance.
        """

        context: dict[str, Any] = {"log": ""}
        confidence_score: float | None = None

        def emit(message: str) -> LogEvent:
            """Append a log entry to the context and return it for streaming."""
            context["log"] += f"\n{message}"
            return LogEvent(message=message)

        try:
            yield emit(f"Current task: {task_node.task}\n")
            # Instantiate all generic agents
            requester_agent = RequesterAgent(
                model=self.model,
                deps_type=RequesterDeps,
                target_information=self.context.target,
                requires_approval=self.requires_approval
            ) if self.requester_deps is not None else None

            shell_agent = ShellAgent(
                model=self.model,
                deps_type=WebappreconDeps,
                target_information=self.context.target,
                requires_approval=self.requires_approval
            ) if self.shell_deps is not None else None

            python_interpreter_agent = PythonInterpreterAgent(
                model=self.model,
                deps_type=str,
            )

            # Create supervisor dependencies
            supervisor_deps = SupervisorDeps(
                requester_agent=requester_agent,
                requester_deps=self.requester_deps,
                shell_agent=shell_agent,
                shell_deps=self.shell_deps,
                python_interpreter_agent=python_interpreter_agent,
                session_id=self.session_id or "",
                message_history=message_history,
                usage_limits=usage_limits,
                deferred_tool_results=deferred_tool_results,
                context=self.context  # Pass context for storing agent outputs
            )

            # Create new router with agent tools and supervisor deps
            supervisor = SupervisorAgent(
                model=self.model,
                deps_type=SupervisorDeps,
                tools=[],
                available_agents=self.available_agents
            )     
            # Build list of tools for router

            # Helper function to add agent output to context
            def _add_agent_output_to_context(
                task: str,
                context: ContextEngine | None,
                agent_name: str,
                output: AgentOutput
            ) -> None:
                """Add agent output to context for future reference.

                IMPORTANT: No truncation - full content is preserved for supervisor.
                """
                if context is None:
                    return

                output_dict = output.model_dump()

                # Get the simplified fields - NO TRUNCATION
                detailed_summary = output_dict.get("detailed_summary", "")
                proofs = output_dict.get("proofs", "")
                confidence_score = output_dict.get("confidence_score", 0.5)
                thoughts = output_dict.get("thoughts", "")

                # Add detailed summary as discovered fact - FULL content
                if detailed_summary:
                    context.add_discovered_fact(
                        source_task=task,
                        category="agent_result",
                        key=f"{agent_name}_summary",
                        value=detailed_summary,
                        confidence=confidence_score,
                        actionable=True
                    )

                # Add proofs as discovered fact - FULL content
                if proofs:
                    context.add_discovered_fact(
                        source_task=task,
                        category="agent_proofs",
                        key=f"{agent_name}_proofs",
                        value=proofs,
                        confidence=confidence_score,
                        actionable=True
                    )

                # Add thoughts - FULL content (summary auto-generated if empty)
                if thoughts:
                    context.add_thought(
                        agent_name=agent_name,
                        thought=thoughts,
                        summary="",  # Let context auto-generate summary
                        relevance=0.9
                    )

                # Log the full agent response - NO TRUNCATION
                full_response = f"[{agent_name}]\nSummary: {detailed_summary}\nProofs: {proofs}\nThoughts: {thoughts}"
                context.add_agent_response(
                    full_response,
                    agent_name=agent_name,
                    skip_structured=False
                )

            # Create tool functions using RunContext for agent delegation
            @supervisor.agent.tool
            async def call_requester_agent(ctx: RunContext[SupervisorDeps], prompt: str) -> str:
                """Call the requester agent to perform HTTP request testing."""
                if ctx.deps.requester_agent is None or ctx.deps.requester_deps is None:
                    return "Requester agent dependencies not configured."
                result = await ctx.deps.requester_agent.run(
                    prompt,
                    deps=ctx.deps.requester_deps,
                    message_history=ctx.deps.message_history,
                    usage=ctx.usage,
                    usage_limits=ctx.deps.usage_limits,
                    deferred_tool_results=ctx.deps.deferred_tool_results
                )
                if hasattr(result, 'output') and isinstance(result.output, AgentOutput):
                    # Add output to context for future reference
                    _add_agent_output_to_context(
                        task=task_node.task,
                        context=ctx.deps.context,
                        agent_name="requester",
                        output=result.output
                    )
                    return f"Requester agent result: {result.output.model_dump()}"
                return str(result.output) if hasattr(result, 'output') else str(result)

            @supervisor.agent.tool
            async def call_shell_agent(ctx: RunContext[SupervisorDeps], prompt: str) -> str:
                """Call the shell agent to execute shell commands."""
                if ctx.deps.shell_agent is None or ctx.deps.shell_deps is None:
                    return "Shell agent dependencies not configured."
                result = await ctx.deps.shell_agent.run(
                    prompt,
                    deps=ctx.deps.shell_deps,
                    message_history=ctx.deps.message_history,
                    usage=ctx.usage,
                    usage_limits=ctx.deps.usage_limits,
                    deferred_tool_results=ctx.deps.deferred_tool_results
                )
                if hasattr(result, 'output') and isinstance(result.output, AgentOutput):
                    # Add output to context for future reference
                    _add_agent_output_to_context(
                        task=task_node.task,
                        context=ctx.deps.context,
                        agent_name="shell",
                        output=result.output
                    )
                    return f"Shell agent result: {result.output.model_dump()}"
                return str(result.output) if hasattr(result, 'output') else str(result)

            @supervisor.agent.tool
            async def call_python_interpreter_agent(ctx: RunContext[SupervisorDeps], prompt: str) -> str:
                """Call the python interpreter agent to execute Python scripts."""
                result = await ctx.deps.python_interpreter_agent.run(
                    prompt,
                    deps=ctx.deps.session_id,
                    session_key=ctx.deps.session_id,
                    message_history=ctx.deps.message_history,
                    usage=ctx.usage,
                    usage_limits=ctx.deps.usage_limits,
                    deferred_tool_results=ctx.deps.deferred_tool_results
                )
                if hasattr(result, 'output') and isinstance(result.output, AgentOutput):
                    # Add output to context for future reference
                    _add_agent_output_to_context(
                        task=task_node.task,
                        context=ctx.deps.context,
                        agent_name="python_interpreter",
                        output=result.output
                    )                    
                    return f"Python interpreter agent result: {result.output.model_dump()}"
                return str(result.output) if hasattr(result, 'output') else str(result)

            # Execute task with supervisor
            supervisor_prompt = f"Your task is : {task_node.task}\n"
            if agent_context:
                supervisor_prompt += f"## Traces: \n{agent_context}\n"

            result = await supervisor.run(
                prompt=supervisor_prompt,
                deps=supervisor_deps,
                message_history=message_history,
                usage=usage,
                usage_limits=usage_limits,
                deferred_tool_results=deferred_tool_results
            )

            # Extract SupervisorOutput fields
            supervisor_output = result.output
            if isinstance(supervisor_output, SupervisorOutput):
                confidence_score = supervisor_output.confidence_score
                context["task_achieved"] = supervisor_output.task_achieved
                context["detailed_summary"] = supervisor_output.detailed_summary
                context["proofs"] = supervisor_output.proofs
                context["last_output"] = supervisor_output.model_dump()
            else:
                confidence_score = 0.5
                # Ensure detailed_summary is set even for non-SupervisorOutput results
                output_str = str(supervisor_output)
                context["last_output"] = output_str
                context["detailed_summary"] = output_str
                context["task_achieved"] = False
                context["proofs"] = ""

            yield ResultEvent(
                confidence_score=confidence_score,
                context=context,
            )
            return

        except UsageLimitExceeded as exc:
            yield emit(f"[SUPERVISOR] Usage limit reached: {exc}")
            yield ResultEvent(
                confidence_score=confidence_score or 0.5,
                context=context,
            )
            return
        except (GeneratorExit, asyncio.CancelledError):
            # These exceptions must not be caught - re-raise to allow proper cleanup
            raise
        except Exception as exc:
            # Store error info in context before yielding
            # This prevents "generator didn't stop after throw()" if the generator
            # is being closed due to the exception
            context["last_output"] = f"detailed_summary=\"Agent error: {exc}. Agent: supervisor\""
            context["detailed_summary"] = f"Agent error: {exc}. Agent: supervisor"
            try:
                yield emit(f"[SUPERVISOR] Error: {exc}")
                yield ResultEvent(
                    confidence_score=confidence_score or 0.5,
                    context=context,
                )
            except GeneratorExit:
                # If generator is being closed, don't try to yield more
                pass
            return
