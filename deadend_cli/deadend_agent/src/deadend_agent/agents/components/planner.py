from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from pydantic_ai.usage import RunUsage, UsageLimits
from deadend_agent.utils.structures import PlannerOutput
from deadend_agent.agents import AgentRunner
from deadend_agent.agents.exploit_web_agent import ExploitInfo, ExploitOutput
from deadend_agent.agents.recon_threatmodel_agent import GeneralInfoOutput, ThreatModelOutput
from deadend_agent.utils.structures import RequesterDeps

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
Break down this task into a maximum of 5 subtasks.{parent_task.task}. The goal is to find a flag in the following format FLAG{{}}. \n{str(context)}
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

        # Debug: show what output type we got
        print(f"[Planner Debug] result.output type: {type(result.output)}")
        print(f"[Planner Debug] result.output: {result.output}")

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
