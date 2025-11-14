from __future__ import annotations
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, Field
from pydantic_ai import DeferredToolResults
from pydantic_ai.usage import RunUsage, UsageLimits
from deadend_agent.context.memory import MemoryHandler
from deadend_agent.models.registry import AIModel
from deadend_agent.utils.structures import PlannerOutput
from deadend_prompts.template_renderer import render_agent_instructions
from deadend_agent.agents import (
    RouterAgent, RouterOutput,
    RequesterAgent,
    ShellAgent,
    PythonInterpreterAgent,
    AgentRunner
)
from deadend_agent.agents.factory import AgentOutput
from deadend_agent.utils.structures import WebappreconDeps
from deadend_agent.context import ContextEngine


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
    depth: int
    confidence_score: float
    status: str
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
    def __init__(self, planner_agent: AgentRunner) -> None:
        """Initialize the Planner.
        
        Args:
            planner_agent: The AgentRunner instance to use for task decomposition
        """
        self.agent = planner_agent

    async def expand(
        self,
        parent_task: TaskNode,
        context: str

    ) -> list[TaskNode]:
        """Expand a parent task into subtasks.
        
        Args:
            parent_task: The task node to decompose into subtasks
            context: Current execution context containing relevant information
            
        Returns:
            List of TaskNode instances representing the subtasks. Each subtask
            will have depth = parent_task.depth + 1 and parent = parent_task.
        """
        # Adding to the system prompt instructions about the subtasking
        result = await self.agent.run(
            prompt=f"Break down this task into subtasks: {parent_task.task}",
            deps=None,
            message_history=context,
            usage=None,
            usage_limits=None
        )

        # Populating task nodes
        nested_tasks = []
        if isinstance(result.output, PlannerOutput):
            for _, (task, confidence_score) in enumerate(result.output.tasks.items()):
                new_task = TaskNode(
                    task=task,
                    depth=parent_task.depth+1,
                    confidence_score=confidence_score,
                    status="pending",
                    parent=parent_task,
                    children=[]
                )
                nested_tasks.append(new_task)
        return nested_tasks

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

        self.router = RouterAgent(
                    model=self.model,
                    deps_type=None,
                    tools=[],
                    available_agents=self.available_agents
        )

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
                    deps_type=WebappreconDeps,
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
                    deps_type=None,
                )
            case _:
                self.context.add_not_found_agent(agent_name=agent_name)
                return RouterAgent(
                    model=self.model,
                    deps_type=None,
                    tools=[],
                    available_agents=self.available_agents
                )


    async def execute(
        self,
        task_node: TaskNode,
        deps: Any | None = None,
        usage: RunUsage = RunUsage(),
        usage_limits: UsageLimits = UsageLimits(),
        deferred_tool_results: DeferredToolResults | None = None,
        message_history: list | None = None
    ) -> tuple[float, dict[str, Any]]:
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
            
        Returns:
            Tuple of (confidence_score, updated_context) where:
            - confidence_score: Float between 0.0 and 1.0 indicating execution confidence
            - updated_context: Dictionary with updated context including execution log and state
            
        Note:
            If routing fails or the selected agent cannot be created, execution falls back
            to the generic runner. All routing and execution information is logged in the context.
        """
        context = {}
        try:
            # Ensure context is a copy to avoid mutating the original

            context.setdefault("log", "")

            # Use router to determine which agent should handle this task if router is available
            routing_info = None
            selected_agent = None
            if self.router:
                try:
                    router_result = await self.router.run(
                        prompt=f"{self.context.get_all_context()}\nWhich agent should handle: {task_node.task}",
                        deps=None,
                        message_history=message_history or "",
                        usage=usage,
                        usage_limits=usage_limits,
                        deferred_tool_results=None
                    )
                    routing_info = router_result.output
                    if isinstance(routing_info, RouterOutput):
                        # Add routing information to context
                        context["log"] += f"\n[ROUTER] Selected agent: \
                            {routing_info.next_agent_name}\nReasoning: {routing_info.reasoning}"

                        # Try to get or create the selected agent
                        selected_agent = self._get_agent(routing_info.next_agent_name)
                        if selected_agent:
                            context["log"] += f"\n[EXECUTOR] Using specialized agent: \
                                {routing_info.next_agent_name}"
                        else:
                            context["log"] += f"\n[EXECUTOR] Specialized agent \
                                '{routing_info.next_agent_name}' not available, using generic executor"
                except Exception as e:
                    # If routing fails, continue with generic executor
                    context["log"] += f"\n[ROUTER] Routing failed: {str(e)}, using generic executor"

            # Use selected agent if available, otherwise use generic runner
            agent_to_use = selected_agent
            if isinstance(agent_to_use, AgentRunner):
                result = await agent_to_use.run(
                    prompt=task_node.task,
                    deps=deps,
                    message_history=message_history,
                    usage=usage,
                    usage_limits=usage_limits,
                    deferred_tool_results=deferred_tool_results
                )
                output = result.output
            else:
                output = f"[AGENT RESPONSE] Error in agent running {agent_to_use}"

            if isinstance(output, AgentOutput):
                confidence_score = output.confidence_score
                notes = output.notes or ""
                updated_state = output.updated_state or {}
            else:
                confidence_score = getattr(output, 'confidence_score', 0.3)
                notes = getattr(output, 'notes', str(output))
                updated_state = getattr(output, 'updated_state', {})

            # Context already copied and log initialized at the start
            context["log"] += f"\n[EXECUTOR] Task: {task_node.task}\nNotes: {notes}"
            context.update(updated_state)
            context["last_output"] = output.model_dump() \
                if isinstance(output, AgentOutput) else str(output)
            return confidence_score, context
        except Exception as e:
            # On error, return low confidence failure
            # Context already copied and log initialized at the start
            context["log"] += f"\n[EXECUTOR] Error: {str(e)}"
            return 0.0, context

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
            validation_format="CTF format"
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

        if isinstance(result.output, ValidatorOutput):
            valid = result.output.valid
            confidence_score = float(result.output.confidence_score)
            critique = result.output.critique
        else:
            valid = getattr(result.output, "valid", False)
            confidence_score = getattr(result.output, "confidence_score", 0.0)
            critique = str(result.output)

        # adding to context
        return (valid, confidence_score, critique)

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

    async def _solve(self, node: TaskNode, depth: int) -> None:
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
        """
        if depth > self.max_depth:
            node.status = "aborted:max_depth"
            node.confidence_score = 0.0
            return

        confidence_score, new_context = await self.executor.execute(
            task_node=node
        )

        self.context.add_agent_response(str(new_context))

        decision = self._policy(confidence_score)
        if decision == "fail":
            node.status = "failed"
            return

        if decision == "validate":
            # Validate the task
            node.status = await self._validate(node)
            return

        subtasks = await self.planner.expand(
            node,
            context = self.context.get_all_context()
        )
        if not subtasks or len(subtasks) <1:
            node.status = "refine"
            if node.parent:
                await self._solve(node.parent, depth=node.depth)

        node.status = "expand"
        node.children = subtasks
        for subtask in subtasks:
            await self._solve(subtask, depth+1)

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
        validation_context["log"] += f"\nVALIDATOR: {validation} : {critique}"
        self.context.add_agent_response(str(validation_context))
        node.confidence_score = validation

        return "completed" if ok else "failed-validation"

    async def run(self, task: str) -> TaskNode:
        """Run the ADaPT agent on a given task.
        
        Creates a root task node and recursively solves it using the ADaPT algorithm,
        which includes execution, planning, and validation phases.
        
        Args:
            task: The main task description to execute
            context: Optional initial context dictionary. If not provided, an empty
                dictionary will be created with an empty "log" entry.
                
        Returns:
            TaskNode representing the root of the execution tree. The tree contains
            all subtasks, their execution statuses, and confidence scores.
        """
        # self.context = context or {}
        # self.context.setdefault("log", "")

        root = TaskNode(
            task=task,
            depth=0,
            confidence_score=0.0,
            status="pending",
            parent=None,
            children=[]
        )

        await self._solve(root, depth=0)
        return root
