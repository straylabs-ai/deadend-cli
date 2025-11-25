from __future__ import annotations
from typing import Any, Literal, AsyncGenerator
from uuid import UUID
from deadend_agent.agents.exploit_web_agent import ExploitInfo, ExploitOutput
from deadend_agent.agents.recon_threatmodel_agent import GeneralInfoOutput, ThreatModelOutput
from pydantic import BaseModel, Field
from pydantic_ai import DeferredToolResults
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.usage import RunUsage, UsageLimits
from deadend_agent.context.memory import MemoryHandler
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
            deps: Dependencies for the planner agent (can be RequesterDeps, session_key string, or other types)
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
        print(result.output)
        
        # Handle ExploitOutput (which extends both PlannerOutput and ExploitInfo)
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
            exploit_info.highly_possible_vulnerabilities = result.output.highly_possible_vulnerabilities
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
            website_data_gathered.website_general_information = result.output.website_general_information
            website_data_gathered.endpoints = result.output.endpoints
            website_data_gathered.technology_stack = result.output.technology_stack
        
        # Handle standalone ExploitInfo (if not already handled via ExploitOutput)
        if isinstance(result.output, ExploitInfo) and not isinstance(result.output, ExploitOutput):
            exploit_info.reasoning = result.output.reasoning
            exploit_info.highly_possible_vulnerabilities = result.output.highly_possible_vulnerabilities
        
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
        parent_task_description = parent_task.task if parent_task else f"Root level (task: {task.task})"
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
        print(result.output)
        
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
            website_data_gathered.website_general_information = result.output.website_general_information
            website_data_gathered.endpoints = result.output.endpoints
            website_data_gathered.technology_stack = result.output.technology_stack
        
        # Handle standalone ExploitInfo (if not already handled via ExploitOutput)
        if isinstance(result.output, ExploitInfo) and not isinstance(result.output, ExploitOutput):
            exploit_info.reasoning = result.output.reasoning
            exploit_info.highly_possible_vulnerabilities = result.output.highly_possible_vulnerabilities
        
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
            for custom agent creation. If provided, this takes precedence over built-in agent creation.
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
            yield emit(f"[EXECUTOR] Starting task: {task_node.task}\n")

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
                            "[ROUTER] Selected agent: "
                            f"{routing_info.next_agent_name}\nReasoning: {routing_info.reasoning}"
                        )
                        selected_agent = self._get_agent(routing_info.next_agent_name)
                        if selected_agent:
                            yield emit(f"[EXECUTOR] Using specialized agent: {routing_info.next_agent_name}")
                except Exception as exc:
                    yield emit(f"[ROUTER] Routing failed: {exc}, using generic executor")

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
                print(f"test output : {output}")
            else:
                output = f"[AGENT RESPONSE] Error in agent running {selected_agent}"

            notes = ""
            updated_state = {}
            if isinstance(output, AgentOutput):
                confidence_score = output.confidence_score
                notes = output.notes or ""
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
        requester_deps = self.requester_deps
        shell_deps = self.shell_deps
        webapprecon_deps = self.webapprecon_deps

        if isinstance(agent, RequesterAgent):
            # TODO: add interruptions
            # if self.interrupted:
            #     raise InterruptedError("Workflow interrupted before webapp recon execution")
            if requester_deps is None:
                raise RuntimeError("RequesterAgent dependencies are not configured.")
            results = await agent.run(
                prompt=prompt,
                message_history=message_history,
                usage=usage,
                usage_limits=usage_limits,
                deps=requester_deps,
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
            shell_agent_deps = shell_deps
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

class Validator:
    """Validator component that double-checks task execution results.
    
    The validator uses an LLM-based judge method to verify that task executions
    are coherent, valid, and meet the intended objectives. It provides validation
    decisions along with confidence scores and critiques.
    """

    def __init__(self, model: AIModel) -> None:
        """Initialize the Validator.
        
        Args:
            model: The AI model to use for validation/judgment
        """
        judge_instructions = render_agent_instructions(
            "judge", 
            tools={},
            validation_type="flag",
            validation_format="flag"
        )
        self.agent = AgentRunner(
            name="validator",
            model=model,
            deps_type=None,
            instructions=judge_instructions,
            output_type=ValidatorOutput,
            tools=[]
        )

    async def verify(self, task: TaskNode, context: str) -> tuple[bool, float, str]:
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
        prompt = f"""
You are the Validator. Judge whether the task is satisfied.

Task: {task.task}
confidence task : {task.confidence_score}
Execution trace:
{context}

- valid (true/false)
- confidence (float 0-1)
- critique (string)
"""
        result = await self.agent.run(
            prompt=prompt,
            deps=None,
            message_history="",
            usage=None,
            usage_limits=None,
            deferred_tool_results=None
        )
        print(f"validator output : {result.output}")
        valid = False
        confidence_score = 0.0
        critique = ""
        if isinstance(result.output, ValidatorOutput):
            valid = result.output.valid
            confidence_score = float(result.output.confidence_score)
            critique = result.output.critique

        # adding to context
        return (valid, confidence_score, critique)

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
    memory: MemoryHandler
    context: ContextEngine

    FAIL_THRESHOLD = 0.20
    REPLAN_THRESHOLD = 0.40
    EXPLORE_THRESHOLD = 0.60
    VALIDATE_THRESHOLD = 0.80

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

    async def _solve(self, node: TaskNode, depth: int) -> AsyncGenerator[str, None]:
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
            """Record an agent response and surface it to callers."""
            return message

        if depth > self.max_depth:
            node.status = "aborted:max_depth"
            node.confidence_score = 0.5
            yield emit(f"[ADAPT] Aborted task '{node.task}' at depth {depth} (max_depth={self.max_depth})")
            return
        # Starts executing the agent
        executor_stream = self.executor.execute(task_node=node, agent_context=self.context.get_tasks(depth=0)+self.context.get_all_context())

        confidence_score: float | None = None
        new_context: dict[str, Any] | None = None
        async for event in executor_stream:
            if isinstance(event, ResultEvent):
                confidence_score = event.confidence_score
                new_context = event.context
                formatted_context = f"Confidence Score for the following task: {event.confidence_score}\n"
                formatted_context += _format_dict_for_context(event.context)
                self.context.add_agent_response(formatted_context)
                break
            elif isinstance(event, LogEvent):
                self.context.add_agent_response(event.message)
                yield emit(event.message)

        if confidence_score is None or new_context is None:
            raise RuntimeError("AgentExecutor did not produce a result.")

        formatted_new_context = _format_dict_for_context(new_context)
        yield emit(formatted_new_context)

        decision = self._policy(confidence_score)
        print(f"task : {node.task} decision: {decision}, confidence_score : {confidence_score}")
        # If decision fails <20%
        if decision == "fail":
            node.status = "failed"
            yield emit(f"[POLICY] Task '{node.task}' failed with confidence_score \
                {confidence_score:.2f}")
            return
        # If the decision is validate >80%
        elif decision == "validate":
            node.status = await self._validate(node)
            yield emit(f"[POLICY] Validation completed for '{node.task}' with status \
                {node.status}")
            return
        # If between 20%-60%
        elif decision == "expand":
            planner_context =f"""
The precedent plan is:
{self.context.get_tasks()}
The previous context is :
{self.context.get_all_context()}
Understand the Plan and what have been achieved to expand the plan with only what still need to be done.
Change the confidence_score with have been done. Reason step by step to retrieve the most logical plan.
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
                    async for chunk in self._solve(node.parent, depth=node.depth):
                        yield chunk
                return

            node.children = subtasks
            yield emit(f"[PLANNER] Generated {len(subtasks)} subtasks for '{node.task}'")
            for subtask in subtasks:
                async for chunk in self._solve(subtask, depth + 1):
                    yield chunk
        # If refine
        else:
            planner_context = f"""
The precedent plan is:
{self.context.get_tasks()}
The previous context is:
{self.context.get_all_context()}
Understand the Plan and what have been achieved to update the plan with only what still needs to be done.
Update the confidence_score for what have been done. Reason step by step to retrieve the most logical updated plan.
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

            yield emit(f"[PLANNER] Updated plan for tasks with parent '{parent_task.task if parent_task else 'root'}'")
            
            async for chunk in self._solve(node=node, depth=depth):
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

    async def _validate(self, node: TaskNode) -> str:
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
            return "completed"

        (ok, validation, critique) = await self.validator.verify(task=node, context=self.context.get_all_context())
        validation_context = {}
        validation_context["log"] = f"\nVALIDATOR: {validation} : {critique}"
        formatted_validation = _format_dict_for_context(validation_context)
        self.context.add_agent_response(formatted_validation)
        node.confidence_score = validation

        return "completed" if ok else "failed-validation"

    async def run(
        self,
        task: str
    ) -> AsyncGenerator[str | dict[str, Any], None]:
        """Run the ADaPT agent on a given task.
        
        Creates a root task node and recursively solves it using the ADaPT algorithm,
        which includes execution, planning, and validation phases.
        
        Args:
            task: The main task description to execute
            context: Optional initial context dictionary. If not provided, an empty
                dictionary will be created with an empty "log" entry.
                
        Yields:
            Human-readable log strings describing progress followed by a final
            {"type": "result", "root": TaskNode} event containing the execution tree.
        """


        root = TaskNode(
            task=task,
            depth=0,
            confidence_score=0.7,
            status="pending",
            parent=None,
            children=[]
        )
        self.context.set_root_task(root.task)
        subtasks, website_info, exploit_info = await self.planner.expand(
            root,
            context=self.context.get_all_context(),
            usage=RunUsage(),
            usage_limits=UsageLimits(request_limit=None)
        )
        formatted_website_info = _format_dict_for_context(website_info.model_dump())
        self.context.add_agent_response(formatted_website_info)
        if exploit_info.reasoning or exploit_info.highly_possible_vulnerabilities:
            formatted_exploit_info = _format_dict_for_context(exploit_info.model_dump())
            self.context.add_agent_response(formatted_exploit_info)
        planner_subtasks = []
        for subtask in subtasks:
            planner_subtask = TaskPlanner(
                task=subtask.task,
                confidence_score=subtask.confidence_score,
                status=subtask.status
            )
            planner_subtasks.append(planner_subtask)

        self.context.add_tasks(parent_task=None, tasks=planner_subtasks)
        print(f"task context is \n {self.context.get_tasks(0)}")
        for subtask in subtasks:
            async for chunk in self._solve(subtask, depth=1):
                yield chunk

        yield {"type": "result", "root": root}
        return