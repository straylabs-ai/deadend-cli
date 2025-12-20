from __future__ import annotations
from typing import Any, Literal, AsyncGenerator, Tuple
from uuid import UUID
from deadend_agent.agents.exploit_web_agent import ExploitInfo, ExploitOutput
from deadend_agent.agents.recon_threatmodel_agent import GeneralInfoOutput, ThreatModelOutput
from pydantic import BaseModel, Field
from pydantic_ai import DeferredToolResults
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.usage import RunUsage, UsageLimits
from deadend_agent.models.registry import AIModel
from deadend_agent.utils.structures import PlannerOutput, TaskPlanner
from deadend_agent.agents import (
    RouterAgent, RouterOutput,
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


def yield_formatted_response(message) -> RouterOutput | ExploitOutput | ThreatModelOutput:
    pass


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
Break down this task into a maximum of 5 subtasks: {parent_task.task}. The context is : \n{str(context)}
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

        self.router = RouterAgent(
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

    def _executor_message_yield(self, message) -> RouterOutput | AgentOutput | LogEvent | ResultEvent:
        pass

    async def execute(
        self,
        task_node: TaskNode,
        agent_context: str = "",
        usage: RunUsage = RunUsage(),
        usage_limits: UsageLimits = UsageLimits(request_limit=None, tool_calls_limit=None),
        deferred_tool_results: DeferredToolResults | None = None,
        message_history: list | None = None
    ) -> AsyncGenerator[ExecutorEvent, None]:
        """Execute a task node using the appropriate agent.
        
        The execution process:
        1. Uses the router (if available) to determine which agent should handle the task
        2. Attempts to get or create the selected specialized agent
        3. Executes the task with the specialized agent or falls back to the generic runner
        4. Extracts confidence score and updates context with execution results
        
        Args:
            task_node: The TaskNode containing the task to execute
            context: Current execution context (will be copied and updated)
            deps: Optional dependencies to pass to the agent
            usage: Usage tracking object
            usage_limits: Limits for token usage
            deferred_tool_results: Optional deferred tool results from previous runs
            message_history: Previous conversation messages for context
            
        Yields:
            LogEvent instances for streaming updates.
            The final event is a ResultEvent instance.
            
        Note:
            If routing fails or the selected agent cannot be created, execution falls back
            to the generic runner. All routing and execution information is logged in the context.
        """
        context: dict[str, Any] = {"log": ""}
        confidence_score: float | None = None

        def emit(message: str) -> LogEvent:
            """Append a log entry to the context and return it for streaming."""
            context["log"] += f"\n{message}"
            return LogEvent(message=message)

        try:
            yield emit(f"Current task: {task_node.task}\n")

            routing_info = None
            selected_agent: AgentRunner | None = None
            if self.router:
                try:
                    router_result = await self.router.run(
                        prompt=f"{agent_context}\nWhich agent should handle: {task_node.task}",
                        deps=None,
                        message_history=message_history or "",
                        usage=usage,
                        usage_limits=usage_limits,
                        deferred_tool_results=None
                    )
                    routing_info = router_result.output
                    if isinstance(routing_info, RouterOutput):
                        yield emit(
                            "Selected agent: "
                            f"{routing_info.next_agent_name}\nReasoning: {routing_info.reasoning}"
                        )
                        selected_agent = self._get_agent(routing_info.next_agent_name)
                        if selected_agent:
                            yield emit(f"Using specialized agent: {routing_info.next_agent_name}")
                except Exception as exc:
                    yield emit(f"Routing failed: {exc}, using generic executor")

            if isinstance(selected_agent, AgentRunner):
                result = await self._run_agent(
                    agent=selected_agent,
                    prompt=agent_context+task_node.task,
                    message_history=message_history,
                    usage=usage,
                    usage_limits=usage_limits,
                    deferred_tool_results=deferred_tool_results
                )
                output = result.output
                # print(f"test output : {output}")
            else:
                output = f"[AGENT RESPONSE] Error in agent running {selected_agent}"

            notes = ""
            updated_state = {}
            if isinstance(output, AgentOutput):
                confidence_score = output.confidence_score
                notes = output.notes
                updated_state = output.updated_state or {}
            else:
                # Default confidence score when output is not an AgentOutput
                confidence_score = 0.5

            # yield emit(f"[EXECUTOR] Task: {task_node.task}\nNotes: {notes}\n{output}")
            context.update(updated_state)
            context["last_output"] = output.model_dump() if isinstance(output, AgentOutput) else str(output)
            yield ResultEvent(
                confidence_score=confidence_score,
                context=context,
            )
            return
        except UsageLimitExceeded as exc:
            yield emit(f"[EXECUTOR] Usage limit reached: {exc}")
            yield ResultEvent(
                confidence_score=confidence_score or 0.5,
                context=context,
            )
            return
        except Exception as exc:
            yield emit(f"[EXECUTOR] Error: {exc}")
            yield ResultEvent(
                confidence_score=confidence_score or 0.5,
                context=context,
            )
            return

    def _get_agent(self, agent_name: str) -> AgentRunner:
        """Get an agent instance by name.
        
        Args:
            agent_name: Name of the agent to retrieve
            
        Returns:
            AgentRunner instance for the specified agent
        """
        # Determine if approval is required based on mode

        match agent_name:
            case "requester":
                return RequesterAgent(
                    model=self.model,
                    deps_type=RequesterDeps,
                    target_information=self.context.target,
                    requires_approval=self.requires_approval
                )
            case "shell":
                return ShellAgent(
                    model=self.model,
                    deps_type=WebappreconDeps,
                    target_information=self.context.target,
                    requires_approval=self.requires_approval
                )
            case "python_interpreter":
                return PythonInterpreterAgent(
                    model=self.model,
                    deps_type=str,
                )
            case _:
                self.context.add_not_found_agent(agent_name=agent_name)
                return RouterAgent(
                    model=self.model,
                    deps_type=None,
                    tools=[],
                    available_agents=self.available_agents
                )

    async def _run_agent(
        self,
        agent: AgentRunner,
        prompt: str,
        message_history,
        usage: RunUsage,
        usage_limits: UsageLimits,
        deferred_tool_results: DeferredToolResults,

    ):
    # Adding a try/ except block is the deps are not formally
    # built or if anything is missing
        results = None
        webapprecon_deps = self.webapprecon_deps
        prompt = f"If you think the result is found, \
            always return confidence score of 1. Execute the following : {prompt}"
        print(prompt)
        if isinstance(agent, RequesterAgent):
            # TODO: add interruptions
            # if self.interrupted:
            #     raise InterruptedError("Workflow interrupted before webapp recon execution")
            if self.requester_deps is None:
                raise RuntimeError("RequesterAgent dependencies are not configured.")
            results = await agent.run(
                prompt=prompt,
                message_history=message_history,
                usage=usage,
                usage_limits=usage_limits,
                deps=self.requester_deps,
                deferred_tool_results=deferred_tool_results
            )
        elif isinstance(agent, PythonInterpreterAgent):
            results = await agent.run(
                prompt=prompt,
                message_history=message_history,
                usage=usage,
                usage_limits=usage_limits,
                deps=self.session_id,
                session_key=self.session_id,
                deferred_tool_results=deferred_tool_results
            )
        elif isinstance(agent, RouterAgent):
            results = await agent.run(
                prompt=prompt,
                message_history=message_history,
                usage=usage,
                usage_limits=usage_limits,
                deps=None,
                deferred_tool_results=deferred_tool_results
            )
        elif isinstance(agent, ShellAgent):
            shell_agent_deps = self.shell_deps
            if shell_agent_deps is None:
                raise RuntimeError("ShellAgent dependencies are not configured.")
            results = await agent.run(
                prompt=prompt,
                message_history=message_history,
                usage=usage,
                usage_limits=usage_limits,
                deps=shell_agent_deps,
                deferred_tool_results=deferred_tool_results
            )
        else:
            generic_deps = self.webapprecon_deps or self.requester_deps or self.shell_deps
            results = await agent.run(
                prompt=prompt,
                message_history=message_history,
                usage=usage,
                usage_limits=usage_limits,
                deps=generic_deps,
                deferred_tool_results=deferred_tool_results
            )
        if results is None:
            raise RuntimeError(
                f"Agent {agent.__class__.__name__} could not run with provided deps."
            )
        return results

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
        prompt = f"""\
# Objective
You are the Validator. Judge whether the task the following task is satisfied depending on the execution trace.
{task.task}

# Execution trace
{context}

# Output results
- valid (true/false)
- confidence (float 0.00-1.00) - like a percentage
- critique (string)
- validation_token corresponding to the result if found (only return if found)
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

    def _extract_agent_output_to_context(
        self,
        last_output: dict[str, Any],
        confidence_score: float,
        task: str
    ) -> None:
        """Extract structured output from any agent type and add to context.

        Handles all agent output types:
        - RequesterOutput: payload, request, response, vulnerability_category
        - ShellOutput: objective, stdin, stdout, stderr
        - PythonInterpreterOutput: filename, goal, reasoning, script_stdout, script_stderr
        - WebappReconOutput: reasoning, state, raw_response

        Args:
            last_output: The agent's output dictionary (from model_dump())
            confidence_score: The agent's confidence score
            task: The task description
        """
        # === Extract fields from all agent types ===

        # RequesterOutput / RequesterSecOutput fields
        payload = last_output.get("payload", "")
        request = last_output.get("request", "")
        response = last_output.get("response", "")
        vuln_category = last_output.get("vulnerability_category", "")
        attempt_desc = last_output.get("attempt", "")

        # ShellOutput fields
        objective = last_output.get("objective", "")
        stdin = last_output.get("stdin", "")
        stdout = last_output.get("stdout", "")
        stderr = last_output.get("stderr", "")

        # PythonInterpreterOutput fields
        filename = last_output.get("filename", "")
        goal = last_output.get("goal", "")
        script_stdout = last_output.get("script_stdout", "")
        script_stderr = last_output.get("script_stderr", "")

        # WebappReconOutput / common fields
        reasoning = last_output.get("reasoning", "")
        state = last_output.get("state", "")
        raw_response = last_output.get("raw_response", "")
        notes = last_output.get("notes", "")

        # === Build comprehensive log for structured context ===
        output_log_parts = [f"[Agent Result - confidence: {confidence_score:.2f}]"]

        # Requester-type output
        if payload:
            output_log_parts.append(f"Payload: {payload[:400]}")
        if request:
            output_log_parts.append(f"Request: {request[:600]}")
        if response:
            output_log_parts.append(f"Response: {response[:1200]}")

        # Shell-type output
        if objective:
            output_log_parts.append(f"Objective: {objective[:200]}")
        if stdin:
            output_log_parts.append(f"Command: {stdin[:300]}")
        if stdout:
            output_log_parts.append(f"Output: {stdout[:800]}")
        if stderr:
            output_log_parts.append(f"Errors: {stderr[:300]}")

        # Python interpreter output
        if filename:
            output_log_parts.append(f"Script: {filename}")
        if goal:
            output_log_parts.append(f"Goal: {goal[:200]}")
        if script_stdout:
            output_log_parts.append(f"Script Output: {script_stdout[:800]}")
        if script_stderr:
            output_log_parts.append(f"Script Errors: {script_stderr[:300]}")

        # Webapp recon output
        if raw_response:
            output_log_parts.append(f"Raw Response: {raw_response[:800]}")
        if state:
            output_log_parts.append(f"State: {state[:200]}")

        # Common fields
        if reasoning:
            output_log_parts.append(f"Reasoning: {reasoning[:400]}")
        if notes:
            output_log_parts.append(f"Notes: {notes[:300]}")
        if attempt_desc and isinstance(attempt_desc, str):
            output_log_parts.append(f"Attempt: {attempt_desc[:200]}")

        # Add to structured context log (only if we have meaningful content)
        if len(output_log_parts) > 1:
            full_output_log = "\n".join(output_log_parts)
            self.context.structured.append_to_log(full_output_log)

        # === Record attempt for deduplication and learning ===
        # Determine the primary "action" that was taken
        attempt_action = payload or request or stdin or script_stdout or raw_response or ""

        if attempt_action:
            # Determine result based on confidence
            if confidence_score >= self.VALIDATE_THRESHOLD:
                result = "success"
            elif confidence_score >= self.EXPLORE_THRESHOLD:
                result = "partial"
            else:
                result = "failed"

            # Build reason with key indicators
            reason_parts = [f"confidence: {confidence_score:.2f}"]

            if vuln_category:
                reason_parts.append(f"category: {vuln_category}")

            # Check all output sources for key indicators
            all_output = f"{response} {stdout} {script_stdout} {raw_response}"
            if "FLAG{" in all_output or "flag{" in all_output.lower():
                reason_parts.append("FLAG FOUND")
                result = "success"  # Override to success if flag found
            elif "error" in all_output.lower() and "success" not in all_output.lower():
                reason_parts.append("error in output")
            elif "fail" in all_output.lower() and "success" not in all_output.lower():
                reason_parts.append("fail indicator in output")
            elif "success" in all_output.lower() or "completed" in all_output.lower():
                reason_parts.append("success indicator in output")

            if stderr or script_stderr:
                reason_parts.append("stderr present")

            self.context.record_attempt(
                task=task,
                payload=str(attempt_action)[:400],
                result=result,
                reason="; ".join(reason_parts)
            )

        # === Add discovered facts from agent output ===

        # Add vulnerability facts
        if vuln_category and confidence_score >= 0.5:
            details = {}
            if payload:
                details["payload"] = payload[:150]
            if request:
                details["request"] = request[:150]
            if response:
                details["response_excerpt"] = response[:250]
            if stdout or script_stdout:
                details["output_excerpt"] = (stdout or script_stdout)[:250]

            self.context.add_discovered_fact(
                category="vulnerability",
                key=vuln_category,
                value=f"Tested: {payload[:100] or stdin[:100] or 'via agent'}",
                confidence=confidence_score,
                details=details,
                actionable=confidence_score < self.VALIDATE_THRESHOLD
            )

        # Add endpoint facts from shell discoveries
        if objective and stdout and confidence_score >= 0.6:
            # Shell agent often discovers endpoints/services
            self.context.add_discovered_fact(
                category="discovery",
                key=objective[:50],
                value=stdout[:200],
                confidence=confidence_score,
                details={"command": stdin[:100] if stdin else ""},
                actionable=False
            )

        # Add technology/state facts from webapp recon
        if state and confidence_score >= 0.6:
            self.context.add_discovered_fact(
                category="state",
                key="webapp_state",
                value=state[:200],
                confidence=confidence_score,
                details={"reasoning": reasoning[:150] if reasoning else ""},
                actionable=False
            )

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
            # Build optimized context for executor
            tasks_context = self.context.get_tasks(depth=0)
            execution_context = await self.context.get_all_context(max_tokens=6000)
            agent_context = f"{tasks_context}\n{execution_context}"

            executor_stream = self.executor.execute(task_node=node, agent_context=agent_context)

            confidence_score: float | None = None
            new_context: dict[str, Any] | None = None
            async for event in executor_stream:
                if isinstance(event, ResultEvent):
                    confidence_score = event.confidence_score
                    new_context = event.context
                    # Add result to context (single point of logging)
                    formatted_context = f"Task: {node.task[:80]}\nConfidence: {event.confidence_score:.2f}"
                    self.context.add_agent_response(formatted_context, skip_structured=True)
                    # Update structured context with result summary only
                    self.context.structured.append_to_log(formatted_context)
                    break
                elif isinstance(event, LogEvent):
                    # Only add to structured log, not full workflow_context (reduces duplication)
                    self.context.structured.append_to_log(event.message)
                    yield emit(event.message)

            if confidence_score is None or new_context is None:
                raise RuntimeError("AgentExecutor did not produce a result.")

            # Update best confidence for this task
            if confidence_score > task_record["best_confidence"]:
                task_record["best_confidence"] = confidence_score

            # Extract and store agent's structured output to context
            last_output = new_context.get("last_output", {})
            if isinstance(last_output, dict):
                self._extract_agent_output_to_context(
                    last_output=last_output,
                    confidence_score=confidence_score,
                    task=node.task
                )

            # Emit summary for streaming output
            context_summary = new_context.get("log", "")[:200] if new_context.get("log") else ""
            if context_summary:
                yield emit(f"[RESULT] {context_summary}")

            decision = self._policy(confidence_score)
            print(f"task: {node.task[:50]}... decision: {decision}, confidence: {confidence_score:.2f}")

            # If decision fails <20%
            if decision == "fail":
                node.status = "failed"
                yield emit(f"[POLICY] Task '{node.task[:50]}...' failed with confidence {confidence_score:.2f}")
                return

            # If the decision is validate >80%
            elif decision == "validate":
                node.status, validation_token = await self._validate(node)
                yield emit(f"[POLICY] Validation completed for '{node.task[:50]}...' with status {node.status}")
                # Mark task as completed in structured context
                if node.status == "completed":
                    self.context.mark_task_completed(node.task)
                if len(validation_token) > 1:
                    yield {'validation_token': validation_token}
                    yield {'exit_loop': True}
                return

            # If between 20%-60%
            elif decision == "expand" and depth < self.max_depth:
                # Use optimized planning context instead of full context
                planner_context = f"""
## Current Plan Status
{self.context.get_tasks()}

## Context Summary
{self.context.get_planning_context()}

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
                # Use optimized planning context for refinement
                planner_context = f"""
## Current Plan Status
{self.context.get_tasks()}

## Context Summary
{self.context.get_planning_context()}

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

        # Use scoped validation context instead of full context (reduces token waste)
        validation_context_text = self.context.get_validation_context()

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

        # Use optimized context for initial planning
        initial_context = await self.context.get_all_context(max_tokens=4000)
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
