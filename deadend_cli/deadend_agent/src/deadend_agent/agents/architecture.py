from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Any, Literal, AsyncGenerator, Tuple
from uuid import UUID
from deadend_agent.agents.exploit_web_agent import ExploitInfo, ExploitOutput
from deadend_agent.agents.recon_threatmodel_agent import GeneralInfoOutput, ThreatModelOutput
from pydantic import BaseModel, Field
from pydantic_ai import DeferredToolResults, RunContext
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.usage import RunUsage, UsageLimits
from deadend_agent.models.registry import AIModel
from deadend_agent.utils.structures import PlannerOutput, TaskPlanner
from deadend_agent.agents import (
    SupervisorAgent, SupervisorOutput,
    RequesterAgent,
    ShellAgent,
    PythonInterpreterAgent,
    AgentRunner
)
from deadend_agent.agents.factory import AgentOutput
from deadend_agent.utils.structures import WebappreconDeps, RequesterDeps, ShellDeps
from deadend_agent.context import ContextEngine
from deadend_prompts.template_renderer import render_agent_instructions
from rich import print


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

class TaskNode(BaseModel):
    """Represents a task node in the ADaPT decomposition tree.
    
    Each node represents a task or subtask with its execution status, confidence score,
    and hierarchical relationships to parent and child tasks.
    
    Attributes:
        task: Description of the task to be executed
        depth: Depth level in the task decomposition tree (0 for root)
        confidence_score: Confidence score (0.0-1.0) indicating execution success likelihood
        status: Current status of the task (e.g., "pending", "completed", "failed")
        parent: Reference to the parent task node, if this is a subtask
        children: List of child task nodes (subtasks)
    """
    task: str
    status: str
    confidence_score: float
    depth: int
    parent: TaskNode | None
    children: list[TaskNode] = Field(default_factory=list)

    def add_child(self, child: TaskNode) -> None:
        """Add a child task node to this node.
        
        Args:
            child: The child TaskNode to add. The child's parent will be set to this node.
        """
        child.parent = self
        self.children.append(child)

class Planner:
    """Planner component for breaking down tasks into subtasks.
    
    The planner uses an AI agent to decompose complex tasks into smaller,
    more manageable subtasks with associated confidence scores.
    """
    def __init__(self, planner_agent: AgentRunner, deps: RequesterDeps | str | Any) -> None:
        """Initialize the Planner.
        
        Args:
            planner_agent: The AgentRunner instance to use for task decomposition
            deps: Dependencies for the planner agent 
            (can be RequesterDeps, session_key string, or other types)
        """
        self.agent = planner_agent
        self.deps = deps

    async def expand(
        self,
        parent_task: TaskNode,
        context: str,
        usage: RunUsage,
        usage_limits: UsageLimits,
    ) -> tuple[list[TaskNode], GeneralInfoOutput]:
        """Expand a parent task into subtasks.
        
        Args:
            parent_task: The task node to decompose into subtasks
            context: Current execution context containing relevant information
            
        Returns:
            List of TaskNode instances representing the subtasks. Each subtask
            will have depth = parent_task.depth + 1 and parent = parent_task.
        """
        # Adding to the system prompt instructions about the subtasking
        planner_prompt=f"""
You need to understand the architecture, endpoints, authentication mechanisms, sinks and sources.
You can then move on to the next step.
Understand the task and what it encompasses: analyze the task goal, identify what components of the web application it involves, and determine what security vulnerabilities this task could lead to or help identify. 
Based on this reasoning, break down the task into logical subtasks that systematically address the task goal.
Break down this task into a maximum of 5 subtasks: {parent_task.task}. \n{str(context)}
"""
        result = await self.agent.run(
            prompt=planner_prompt,
            deps=self.deps,
            message_history="",
            usage=usage,
            usage_limits=usage_limits
        )
        # website info
        website_data_gathered = GeneralInfoOutput()
        exploit_info = ExploitInfo()

        # Populating task nodes
        nested_tasks = []
        # print(result.output)

        # Handle ExploitOutput (which extends both PlannerOutput and ExploitInfo)
        if result.output:
            if isinstance(result.output, ExploitOutput):
                # Extract tasks from PlannerOutput
                for task_plan in result.output.tasks:
                    new_task = TaskNode(
                        task=task_plan.task,
                        depth=parent_task.depth+1,
                        confidence_score=task_plan.confidence_score,
                        status="pending",
                        parent=parent_task,
                        children=[]
                    )
                    nested_tasks.append(new_task)
                # Extract exploit information
                exploit_info.reasoning = result.output.reasoning
                exploit_info.highly_possible_vulnerabilities = \
                    result.output.highly_possible_vulnerabilities
            elif isinstance(result.output, PlannerOutput):
                # Handle regular PlannerOutput (tasks only)
                for task_plan in result.output.tasks:
                    new_task = TaskNode(
                        task=task_plan.task,
                        depth=parent_task.depth+1,
                        confidence_score=task_plan.confidence_score,
                        status="pending",
                        parent=parent_task,
                        children=[]
                    )
                    nested_tasks.append(new_task)

            if isinstance(result.output, ThreatModelOutput):
                website_data_gathered.information_gathering = \
                    result.output.information_gathering
            # Handle standalone ExploitInfo (if not already handled via ExploitOutput)
            if isinstance(result.output, ExploitInfo) and not isinstance(result.output, ExploitOutput):
                exploit_info.reasoning = result.output.reasoning
                exploit_info.highly_possible_vulnerabilities = \
                    result.output.highly_possible_vulnerabilities

        return nested_tasks, website_data_gathered, exploit_info

    async def update_plan(
        self,
        task: TaskNode,
        context: str,
        usage: RunUsage,
        usage_limits: UsageLimits,
    ) -> tuple[list[TaskNode], GeneralInfoOutput | ExploitInfo]:
        """Update and refine the plan for all tasks that share the same parent.
        
        This function takes a task node, finds all tasks that share the same parent
        (siblings), and updates them all based on the provided context. It can modify
        existing tasks, add new ones, or remove obsolete ones depending on what the
        context reveals.
        
        Args:
            task: The task node whose siblings need to be updated
            context: Current execution context containing new information that may
                    require plan updates
            usage: Usage tracking object
            usage_limits: Limits for token usage
            
        Returns:
            Tuple of (updated_tasks, website_data_gathered) where:
            - updated_tasks: List of updated TaskNode instances representing the refined plan.
                            All tasks will have the same parent as the input task.
            - website_data_gathered: GeneralInfoOutput containing any new website information
        """
        # Get the parent task and all siblings (tasks with the same parent)
        parent_task = task.parent
        if parent_task is None:
            # If no parent, this is a root task - get all root-level tasks
            # We need to handle this case differently, but for now we'll treat it as updating just this task
            existing_tasks = [task]
            task_depth = task.depth
        else:
            # Get all siblings (children of the same parent)
            existing_tasks = parent_task.children.copy() if parent_task.children else []
            task_depth = parent_task.depth + 1

        # Format existing tasks for the prompt
        existing_tasks_summary = "\n".join([
            f"- {task.task} [Status: {task.status}, Confidence: {task.confidence_score:.2f}]"
            for task in existing_tasks
        ])

        # Prompt for updating the plan based on context
        parent_task_description = parent_task.task \
            if parent_task else f"Root level (task: {task.task})"
        planner_prompt = f"""
You need to update and refine an existing plan based on new context information.
Parent task: {parent_task_description}
Current subtasks (all tasks that share the same parent):
{existing_tasks_summary if existing_tasks_summary else "No existing subtasks"}
New context information:
{str(context)}
Analyze the new context and determine how the plan should be updated:
1. Review what has been accomplished (check task statuses)
2. Identify what still needs to be done
3. Consider if any tasks should be modified, removed, or if new tasks should be added
4. Update confidence scores based on progress and new information
5. Ensure the updated plan aligns with the parent task goal and the new context
6. if the flag is in the context the task is achieved

Provide an updated list of subtasks that reflects the current state and remaining work.
"""
        result = await self.agent.run(
            prompt=planner_prompt,
            deps=self.deps,
            message_history="",
            usage=usage,
            usage_limits=usage_limits
        )

        # website info
        website_data_gathered = GeneralInfoOutput()
        exploit_info = ExploitInfo()

        # Populating updated task nodes
        updated_tasks = []
        # print(result.output)

        # Handle ExploitOutput (which extends both PlannerOutput and ExploitInfo)
        if isinstance(result.output, ExploitOutput):
            # Extract tasks from PlannerOutput
            for task_plan in result.output.tasks:
                new_task = TaskNode(
                    task=task_plan.task,
                    depth=task_depth,
                    confidence_score=task_plan.confidence_score,
                    status=task_plan.status,
                    parent=parent_task,
                    children=[]
                )
                updated_tasks.append(new_task)
            # Extract exploit information
            exploit_info.reasoning = result.output.reasoning
            exploit_info.highly_possible_vulnerabilities = result.output.highly_possible_vulnerabilities
        elif isinstance(result.output, PlannerOutput):
            # Handle regular PlannerOutput (tasks only)
            for task_plan in result.output.tasks:
                new_task = TaskNode(
                    task=task_plan.task,
                    depth=task_depth,
                    confidence_score=task_plan.confidence_score,
                    status=task_plan.status,
                    parent=parent_task,
                    children=[]
                )
                updated_tasks.append(new_task)

        if isinstance(result.output, ThreatModelOutput):
            website_data_gathered.information_gathering = \
                result.output.information_gathering
        # Handle standalone ExploitInfo (if not already handled via ExploitOutput)
        if isinstance(result.output, ExploitInfo) and not isinstance(result.output, ExploitOutput):
            exploit_info.reasoning = result.output.reasoning
            exploit_info.highly_possible_vulnerabilities = \
                result.output.highly_possible_vulnerabilities

        return updated_tasks, website_data_gathered, exploit_info

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
            yield emit("Instantiating generic agents as tools for supervisor...\n")

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
                        category="agent_result",
                        key=f"{agent_name}_summary",
                        value=detailed_summary,
                        confidence=confidence_score,
                        source_task=agent_name,
                        actionable=True
                    )

                # Add proofs as discovered fact - FULL content
                if proofs:
                    context.add_discovered_fact(
                        category="agent_proofs",
                        key=f"{agent_name}_proofs",
                        value=proofs,
                        confidence=confidence_score,
                        source_task=agent_name,
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
                    _add_agent_output_to_context(ctx.deps.context, "requester", result.output)
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
                    _add_agent_output_to_context(ctx.deps.context, "shell", result.output)
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
                    _add_agent_output_to_context(ctx.deps.context, "python_interpreter", result.output)
                    return f"Python interpreter agent result: {result.output.model_dump()}"
                return str(result.output) if hasattr(result, 'output') else str(result)

            # Execute task with supervisor
            result = await supervisor.run(
                prompt=f"{agent_context}\n{task_node.task}",
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
                context["last_output"] = str(supervisor_output)

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
        except Exception as exc:
            yield emit(f"[SUPERVISOR] Error: {exc}")
            yield ResultEvent(
                confidence_score=confidence_score or 0.5,
                context=context,
            )
            return


class ValidatorOutput(BaseModel):
    """Output format for task validation results.
    
    Attributes:
        valid: Boolean indicating whether the task execution is valid
        confidence_score: Confidence score (0.0-1.0) for the validation decision
        critique: Explanation or critique of the validation decision
    """
    valid: bool
    confidence_score: float
    critique: str
    validation_token: str | None

class Validator:
    """Validator component that double-checks task execution results.
    
    The validator uses an LLM-based judge method to verify that task executions
    are coherent, valid, and meet the intended objectives. It provides validation
    decisions along with confidence scores and critiques.
    """

    def __init__(
        self,
        model: AIModel,
        validation_type: str | None,
        validation_format: str | None
    ) -> None:
        """Initialize the Validator.
        
        Args:
            model: The AI model to use for validation/judgment
        """
        if validation_type and validation_format:
            judge_instructions = render_agent_instructions(
                "judge", 
                tools={},
                validation_type=validation_type,
                validation_format=validation_format
            )
        else:
            judge_instructions = render_agent_instructions(
                "judge", 
                tools={},
                validation_type="flag",
                validation_format="FLAG{{}}"
            )
        self.agent = AgentRunner(
            name="validator",
            model=model,
            deps_type=None,
            instructions=judge_instructions,
            output_type=ValidatorOutput,
            tools=[]
        )

    async def verify(self, task: TaskNode, context: str) -> tuple[bool, float, str, str]:
        """Verify whether a task execution is valid and successful.
        
        Args:
            task: The TaskNode representing the task to validate
            context: Execution context containing logs and execution trace
            
        Returns:
            Tuple of (valid, confidence_score, critique) where:
            - valid: Boolean indicating if the task execution is valid
            - confidence_score: Float (0.0-1.0) indicating validation confidence
            - critique: String explanation of the validation decision
        """
        # Extract root goal from context (first line typically contains it)
        # Parse the goal from unified context format "Goal: ..."
        root_goal = ""
        for line in context.split("\n"):
            if line.startswith("Goal:"):
                root_goal = line.replace("Goal:", "").strip()
                break

        # If we found a root goal, validate against that. Otherwise use task.task
        validation_objective = root_goal if root_goal else task.task

        prompt = f"""\
# Objective
You are the Validator. Judge whether the following goal is satisfied based on the execution trace.
{validation_objective}

# Current Task Being Validated
{task.task}

# Execution trace
{context}

# Output results
- valid (true/false)
- confidence (float 0.00-1.00) - like a percentage
- critique (string)
- validation_token corresponding to the result if found (only return if found). Copy the exact FLAG{{...}} if present.
"""
        result = await self.agent.run(
            prompt=prompt,
            deps=None,
            message_history="",
            usage=None,
            usage_limits=None,
            deferred_tool_results=None
        )

        # returned variables initialization
        valid = False
        confidence_score = 0.0
        critique = ""
        validation_token = ""
        if isinstance(result.output, ValidatorOutput):
            valid = result.output.valid
            confidence_score = float(result.output.confidence_score)
            critique = result.output.critique
            validation_token = result.output.validation_token \
                if result.output.validation_token else ""

        # adding to context
        return (valid, confidence_score, critique, validation_token)

def _format_dict_for_context(data: dict[str, Any]) -> str:
    """Format a dictionary into a readable string for context storage.
    
    Args:
        data: Dictionary to format
        
    Returns:
        Formatted string with keys and values properly displayed
    """
    formatted_parts = []
    for key, value in data.items():
        if isinstance(value, dict):
            formatted_parts.append(f"{key}:\n{_format_dict_for_context(value)}")
        elif isinstance(value, list):
            formatted_parts.append(f"{key}:\n" + "\n".join(f"  - {item}" for item in value))
        else:
            formatted_parts.append(f"{key}: {value}")
    return "\n".join(formatted_parts)


class ADaPTAgent:
    """
    ADaPT Agent is a recursive agent from the paper
    ADaPT: As-Needed Decomposition and Planning with Language Models
    (https://arxiv.org/abs/2311.05772)

    This implementation follows the algorithm presented in the paper,
    by retaking the most relevant information:
    - Usage of 3 components Executors, Planner and Controller.
    """
    session_id: UUID
    task_node: TaskNode
    max_depth: int
    context: ContextEngine

    FAIL_THRESHOLD = 0.20
    REPLAN_THRESHOLD = 0.40
    EXPLORE_THRESHOLD = 0.60
    VALIDATE_THRESHOLD = 0.80

    # Maximum attempts per task to prevent infinite loops
    MAX_TASK_ATTEMPTS = 3

    def __init__(
        self,
        session_id: UUID,
        context: ContextEngine,
        executor: AgentExecutor,
        planner: Planner,
        validator: Validator,
        max_depth: int = 3
    ):
        """Initialize the ADaPT agent.

        Args:
            session_id: Unique identifier for this ADaPT session
            executor: AgentExecutor instance for executing tasks
            planner: Planner instance for decomposing tasks
            validator: Validator instance for validating task completion
            max_depth: Maximum depth for task decomposition (default: 3)
        """
        self.session = session_id
        self.max_depth = max_depth
        self.executor = executor
        self.planner = planner
        self.validator = validator
        self.context = context

        # Track attempted tasks to prevent redundant retries
        # Key: task hash, Value: dict with attempt count and best confidence
        self._attempted_tasks: dict[int, dict[str, Any]] = {}

    async def _solve(
        self,
        node: TaskNode,
        depth: int,
        exit_strategy: str,
        exit_loop: bool
    ) -> AsyncGenerator[str | dict[str, Any], None]:
        """Recursively solve a task node using the ADaPT algorithm.

        This is the core recursive method that implements the ADaPT algorithm:
        1. Execute the task and get confidence score
        2. Apply policy to determine next action (fail, expand, refine, validate)
        3. If expanding, decompose into subtasks and recursively solve each
        4. If validating, verify task completion

        Args:
            node: The TaskNode to solve
            depth: Current depth in the decomposition tree

        Note:
            Tasks that exceed max_depth will be marked as "aborted:max_depth".
            The method modifies the node's status and confidence_score in place.
            This is implemented as an async generator to stream intermediate log entries
            upstream while still performing recursive execution.
        """
        def emit(message: str) -> str:
            """Surface message to callers without adding to context (avoid duplication)."""
            return message

        # Check max depth
        if depth > self.max_depth:
            node.status = "aborted:max_depth"
            node.confidence_score = 0.5
            yield emit(f"[ADAPT] Aborted task '{node.task}' at depth {depth} (max_depth={self.max_depth})")
            return

        # Track attempts for this task to prevent infinite loops
        task_hash = hash(node.task)
        if task_hash not in self._attempted_tasks:
            self._attempted_tasks[task_hash] = {"attempts": 0, "best_confidence": 0.0}

        task_record = self._attempted_tasks[task_hash]

        # Check if task was already completed with high confidence
        if task_record["best_confidence"] >= self.VALIDATE_THRESHOLD:
            node.status = "completed"
            node.confidence_score = task_record["best_confidence"]
            yield emit(f"[SKIP] Task already completed with {task_record['best_confidence']:.2f} confidence")
            return

        # Check max attempts
        if task_record["attempts"] >= self.MAX_TASK_ATTEMPTS:
            node.status = "failed:max_attempts"
            node.confidence_score = task_record["best_confidence"]
            yield emit(f"[FAIL] Task exceeded max attempts ({self.MAX_TASK_ATTEMPTS}): '{node.task[:50]}...'")
            return

        # Increment attempt counter
        task_record["attempts"] += 1

        # Clear current task log for fresh context
        self.context.clear_current_task_log()

        # Use a local variable to track exit_loop since the parameter can't be modified
        should_exit = exit_loop
        while not should_exit:
            # Build UNIFIED context for executor (same as all other agents)
            # This ensures router, executor, validator all see the same information
            tasks_context = self.context.get_tasks(depth=0, include_goal=False)
            unified_context = self.context.get_unified_context(max_tokens=6000)
            agent_context = f"{unified_context}\n\n## Current Tasks\n{tasks_context}"

            executor_stream = self.executor.execute_supervisor(task_node=node, agent_context=agent_context)

            confidence_score: float | None = None
            task_achieved: bool = False
            detailed_summary: str = ""
            proofs: str = ""
            new_context: dict[str, Any] | None = None

            async for event in executor_stream:
                if isinstance(event, ResultEvent):
                    confidence_score = event.confidence_score
                    new_context = event.context

                    # Extract SupervisorOutput fields from context
                    task_achieved = new_context.get("task_achieved", False)
                    detailed_summary = new_context.get("detailed_summary", "")
                    proofs = new_context.get("proofs", "")

                    # Update node status based on task_achieved
                    if task_achieved:
                        node.status = "completed"
                        node.confidence_score = confidence_score
                        self.context.mark_task_completed(node.task, confidence_score)
                        yield emit(f"[SUPERVISOR] Task achieved: {node.task[:50]}...")

                    # Add detailed summary to context
                    if detailed_summary:
                        self.context.add_agent_response(
                            f"[Supervisor] {detailed_summary}",
                            skip_structured=False
                        )

                    # Add proofs to context as discovered facts
                    if proofs:
                        self.context.add_discovered_fact(
                            category="proof",
                            key=f"proof_{node.task[:30]}",
                            value=proofs,
                            confidence=confidence_score,
                            actionable=not task_achieved
                        )
                        # Check for FLAG in proofs
                        if "FLAG{" in proofs.upper():
                            flag_match = re.search(r'FLAG\{[^}]+\}', proofs, re.IGNORECASE)
                            if flag_match:
                                self.context.add_discovered_fact(
                                    category="validated_exploit",
                                    key="captured_flag",
                                    value=f"FLAG CAPTURED: {flag_match.group(0)}",
                                    confidence=1.0,
                                    details={
                                        "flag": flag_match.group(0),
                                        "source": "supervisor_proofs",
                                        "task": node.task[:100]
                                    },
                                    actionable=False
                                )

                    # Log task status
                    status_str = "ACHIEVED" if task_achieved else "IN PROGRESS"
                    self.context.structured.append_to_log(
                        f"[Supervisor] Task: {status_str} | Confidence: {confidence_score:.2f}"
                    )
                    break

                elif isinstance(event, LogEvent):
                    # Only add to structured log, not full workflow_context (reduces duplication)
                    self.context.structured.append_to_log(event.message)
                    yield emit(event.message)
                else:
                    yield emit(str(event))

            if confidence_score is None or new_context is None:
                raise RuntimeError("AgentExecutor did not produce a result.")

            # Update best confidence for this task
            if confidence_score > task_record["best_confidence"]:
                task_record["best_confidence"] = confidence_score

            # Emit summary for streaming output
            if detailed_summary:
                yield emit(f"[RESULT] {detailed_summary[:200]}")

            # If supervisor confirmed task achieved, check for flag and move on
            if task_achieved:
                yield emit(f"[SUPERVISOR] Task completed: {node.task[:50]}...")
                # Check if proofs contain a flag - if so, exit the loop
                if proofs and "FLAG{" in proofs.upper():
                    flag_match = re.search(r'FLAG\{[^}]+\}', proofs, re.IGNORECASE)
                    if flag_match:
                        yield {'validation_token': flag_match.group(0)}
                        yield {'exit_loop': True}
                return  # Task achieved, move to next task

            decision = self._policy(confidence_score)
            try:
                print(f"task: {node.task[:50]}... decision: {decision}, confidence: {confidence_score:.2f}")
            except (BlockingIOError, OSError):
                pass

            # If decision fails <20%
            if decision == "fail":
                node.status = "failed"
                self.context.update_task_status(node.task, "failed", confidence_score)
                yield emit(f"[POLICY] Task '{node.task[:50]}...' failed with confidence {confidence_score:.2f}")
                return

            # If the decision is validate >80%
            elif decision == "validate":
                node.status, validation_token = await self._validate(node)
                yield emit(f"[POLICY] Validation completed for '{node.task[:50]}...' with status {node.status}")
                # Update task status in context
                if node.status == "completed":
                    self.context.mark_task_completed(node.task, node.confidence_score)
                else:
                    self.context.update_task_status(node.task, node.status, node.confidence_score)
                if len(validation_token) > 1:
                    yield {'validation_token': validation_token}
                    yield {'exit_loop': True}
                return

            # If between 20%-60%
            elif decision == "expand" and depth < self.max_depth:
                # Use UNIFIED context for planner (same as executor/router)
                planner_context = f"""
{self.context.get_unified_context(max_tokens=5000)}

## Current Plan Status
{self.context.get_tasks(include_goal=False)}

## Instructions
Analyze what has been achieved and expand the plan with only what still needs to be done.
Update confidence_score based on progress. Reason step by step for the most logical plan.
"""
                subtasks, website_info, exploit_info = await self.planner.expand(
                    node,
                    context=planner_context,
                    usage=RunUsage(),
                    usage_limits=UsageLimits(request_limit=None)
                )
                formatted_website_info = _format_dict_for_context(website_info.model_dump())
                self.context.add_tool_response("website_info", formatted_website_info)
                if exploit_info.reasoning or exploit_info.highly_possible_vulnerabilities:
                    formatted_exploit_info = _format_dict_for_context(exploit_info.model_dump())
                    self.context.add_tool_response("exploit_info", formatted_exploit_info)
                planner_subtasks = []

                # Because it's not hashable
                for subtask in subtasks:
                    planner_subtask = TaskPlanner(
                        task=subtask.task,
                        confidence_score=subtask.confidence_score,
                        status=subtask.status
                    )
                    planner_subtasks.append(planner_subtask)
                parent_planner = TaskPlanner(
                    task=node.task,
                    confidence_score=node.confidence_score,
                    status=node.status
                )
                self.context.add_tasks(parent_task=parent_planner, tasks=planner_subtasks)
                if not subtasks:
                    node.status = "refine"
                    yield emit(f"[PLANNER] No subtasks generated for '{node.task}', requesting \
                        refinement")
                    if node.parent:
                        async for chunk in self._solve(node.parent, depth=node.depth, exit_strategy=exit_strategy, exit_loop=exit_loop):
                            # Check if child call signaled exit_loop
                            if isinstance(chunk, dict) and chunk.get('exit_loop'):
                                should_exit = True
                                yield chunk
                                break
                            yield chunk
                    break

                node.children = subtasks
                yield emit(f"[PLANNER] Generated {len(subtasks)} subtasks for '{node.task}'")
                for subtask in subtasks:
                    async for chunk in self._solve(subtask, depth + 1, exit_strategy=exit_strategy, exit_loop=exit_loop):
                        # Check if child call signaled exit_loop
                        if isinstance(chunk, dict) and chunk.get('exit_loop'):
                            should_exit = True
                            yield chunk
                            break
                        yield chunk
                    else:
                        # Continue to next subtask if no exit_loop was signaled
                        continue
                    # Break out of subtask loop if exit_loop was signaled
                    break
            # If refine
            else:
                # Use UNIFIED context for planner (same as executor/router)
                planner_context = f"""
{self.context.get_unified_context(max_tokens=5000)}

## Current Plan Status
{self.context.get_tasks(include_goal=False)}

## Instructions
Analyze what has been achieved and update the plan with only what still needs to be done.
Update confidence_score for completed items. Reason step by step for the most logical updated plan.
"""
                updated_tasks, website_info, exploit_info = await self.planner.update_plan(
                    node,
                    context=planner_context,
                    usage=RunUsage(),
                    usage_limits=UsageLimits(request_limit=None)
                )
                formatted_website_info = _format_dict_for_context(website_info.model_dump())
                self.context.add_tool_response("website_info", formatted_website_info)
                if exploit_info.reasoning or exploit_info.highly_possible_vulnerabilities:
                    formatted_exploit_info = _format_dict_for_context(exploit_info.model_dump())
                    self.context.add_tool_response("exploit_info", formatted_exploit_info)

                # Store parent reference before updating node
                parent_task = node.parent

                # Update the parent's children with the updated tasks
                if parent_task:
                    parent_task.children = updated_tasks
                    # Update the current node to the updated version
                    # Try to find the updated version by matching the task description first
                    # If not found, use the first updated task (assuming it's the same task refined)
                    updated_node = None
                    for updated_task in updated_tasks:
                        if updated_task.task == node.task:
                            updated_node = updated_task
                            break
                    # If exact match not found, use first task (task might have been refined/renamed)
                    node = updated_node if updated_node else updated_tasks[0] if updated_tasks else node
                else:
                    # If no parent, update the node itself
                    if updated_tasks:
                        node = updated_tasks[0]

                # Update context with updated tasks
                planner_subtasks = []
                for subtask in updated_tasks:
                    planner_subtask = TaskPlanner(
                        task=subtask.task,
                        confidence_score=subtask.confidence_score,
                        status=subtask.status
                    )
                    planner_subtasks.append(planner_subtask)

                if parent_task:
                    parent_planner = TaskPlanner(
                        task=parent_task.task,
                        confidence_score=parent_task.confidence_score,
                        status=parent_task.status
                    )
                    self.context.add_tasks(parent_task=parent_planner, tasks=planner_subtasks)
                else:
                    self.context.add_tasks(parent_task=None, tasks=planner_subtasks)

                yield emit(f"[PLANNER] Updated plan for tasks \
                    with parent '{parent_task.task if parent_task else 'root'}'")

                async for chunk in self._solve(node=node, depth=depth, exit_strategy=exit_strategy, exit_loop=exit_loop):
                    # Check if child call signaled exit_loop
                    if isinstance(chunk, dict) and chunk.get('exit_loop'):
                        should_exit = True
                        yield chunk
                        break
                    yield chunk


    def _policy(self, confidence_score: float) -> Literal["fail", "expand", "refine", "validate"]:
        """
        The policy is given a confidence score, and depending on the information given
        is capable to determine the next step for the task.
        - <20% : treated as unrecoverable. Even though the goal is well defined, we need 
        to propagate the failure and move on.
        - 20-60% : stays in exploration mode, this stage trigger more granular subtasks 
        or gather missing information.
        - 60%-80% : keep executing and reiterating. At this stage we can either make simple changes 
        to increase the confidence score or run the generic agents for executing and testing.
        - > 80% : move to validator/controller.
        the policy could be assertions, tool verification, or LLM judge
        and before the task is done.
        """
        if confidence_score < self.FAIL_THRESHOLD:
            return "fail"
        elif confidence_score < self.EXPLORE_THRESHOLD:
            return "expand"
        elif confidence_score >= self.VALIDATE_THRESHOLD:
            return "validate"
        return "refine"

    async def _validate(self, node: TaskNode) -> Tuple[str, str]:
        """Validate a task node's execution.

        Args:
            node: The TaskNode to validate

        Returns:
            Status string: "completed" if validation passes, "failed-validation" otherwise.
            If no validator is available, returns "completed" by default.

        Note:
            Updates the node's confidence_score with the validation confidence score.
        """
        if not self.validator:
            return ("completed", "")

        # Use UNIFIED context for validator (same as executor/router/planner)
        # This ensures validator sees the same discoveries and exploits as other agents
        validation_context_text = self.context.get_unified_context(max_tokens=5000)

        (ok, validation, critique, validation_token) = await self.validator.verify(
            task=node,
            context=validation_context_text
        )

        # Record validation result compactly
        validation_summary = f"Validation: {critique[:100]}, confidence: {validation:.2f}"
        if validation_token:
            validation_summary += f", token: {validation_token}"

        # Add to structured context only (avoid bloating workflow_context)
        self.context.structured.append_to_log(validation_summary)
        self.context.add_agent_response(validation_summary, skip_structured=True)

        node.confidence_score = validation

        # If validation passed, add validated result as high-confidence fact
        # This ensures the successful exploit details persist in context for next agents
        if ok:
            # Extract recent successful attempts to preserve as facts
            successful_attempts = [a for a in self.context.structured.attempts if a.result == "success"]
            for attempt in successful_attempts[-3:]:  # Last 3 successful
                self.context.structured.add_fact_simple(
                    category="validated_exploit",
                    key=f"{node.task[:50]}",
                    value=f"Payload: {attempt.payload[:200]}",
                    confidence=validation,
                    source_task=node.task[:100],
                    details={
                        "payload": attempt.payload,
                        "reason": attempt.reason,
                        "validation_token": validation_token,
                        "task": attempt.task
                    },
                    actionable=True
                )

        return ("completed", validation_token) if ok else ("failed-validation", validation_token)

    async def run(
        self,
        task: str,
        exit_strategy: str
    ) -> AsyncGenerator[str | dict[str, Any], None]:
        """Run the ADaPT agent on a given task.

        Creates a root task node and recursively solves it using the ADaPT algorithm,
        which includes execution, planning, and validation phases.

        Args:
            task: The main task description to execute
            exit_strategy: Strategy for determining when to exit

        Yields:
            Human-readable log strings describing progress followed by a final
            {"type": "result", "root": TaskNode} event containing the execution tree.
        """
        # Reset attempt tracking for new run
        self._attempted_tasks.clear()

        root = TaskNode(
            task=task,
            depth=0,
            confidence_score=0.7,
            status="pending",
            parent=None,
            children=[]
        )
        self.context.set_root_task(root.task)

        # Use UNIFIED context for initial planning (same as all other agents)
        initial_context = self.context.get_unified_context(max_tokens=4000)
        subtasks, website_info, exploit_info = await self.planner.expand(
            root,
            context=initial_context,
            usage=RunUsage(),
            usage_limits=UsageLimits(request_limit=None)
        )

        # Add website info to structured context as facts (not verbose dump)
        website_dict = website_info.model_dump()
        if website_dict.get("information_gathering"):
            info = website_dict["information_gathering"]
            if isinstance(info, dict):
                for key, value in info.items():
                    if value:
                        self.context.add_discovered_fact(
                            category="website_info",
                            key=key,
                            value=str(value)[:200],
                            confidence=0.8
                        )
            else:
                self.context.add_discovered_fact(
                    category="website_info",
                    key="general",
                    value=str(info)[:200],
                    confidence=0.8
                )

        # Add exploit info if available
        if exploit_info.reasoning or exploit_info.highly_possible_vulnerabilities:
            if exploit_info.highly_possible_vulnerabilities:
                for vuln in exploit_info.highly_possible_vulnerabilities[:5]:  # Limit to 5
                    self.context.add_discovered_fact(
                        category="vulnerability",
                        key=str(vuln)[:50],
                        value=str(vuln),
                        confidence=0.6
                    )
        planner_subtasks = []
        for subtask in subtasks:
            planner_subtask = TaskPlanner(
                task=subtask.task,
                confidence_score=subtask.confidence_score,
                status=subtask.status
            )
            planner_subtasks.append(planner_subtask)
        # TODO: handling the termination
        self.context.add_tasks(parent_task=None, tasks=planner_subtasks)
        # print(f"task context is \n {self.context.get_tasks(0)}")
        exit_loop_triggered = False
        for subtask in subtasks:
            async for chunk in self._solve(subtask, depth=1, exit_strategy=exit_strategy, exit_loop=False):
                # Check if exit_loop was signaled
                if isinstance(chunk, dict) and chunk.get('exit_loop'):
                    exit_loop_triggered = True
                    yield chunk
                    break
                yield chunk
            if exit_loop_triggered:
                break

        # Always yield the final result, even when exit_loop was triggered
        # Update root children to include all subtasks
        root.children = subtasks
        yield {"type": "result", "root": root}
        return
