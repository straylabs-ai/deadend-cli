"""Main DeadEnd agent orchestration module."""
from typing import Any, Dict
from deadend_agent.models.registry import AIModel
from .agents.factory import ADaPTAgent, AgentRunner, AgentExecutor, Planner, Validator, TaskNode
from .agents.recon_threatmodel_agent import ReconThreatModelAgent
from .agents.router import RouterAgent


class DeadEndAgent:
    """Main orchestrator for the DeadEnd security research framework."""

    def __init__(
        self,
        session_id: str,
        model: AIModel,
        available_agents: Dict[str, str],
        max_depth: int = 3
    ):
        self.session_id = session_id
        self.model = model
        self.available_agents = available_agents

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

        executor_runner = AgentRunner(
            name="executor",
            model=model,
            instructions="Execute security testing tasks.",
            deps_type=None,
            output_type=None,
            tools=[]
        )
        self.executor = AgentExecutor(runner=executor_runner)

        self.validator = Validator(model=model)

        # Initialize ADaPT agent
        self.adapt_agent = ADaPTAgent(
            session_id=session_id,
            executor=self.executor,
            planner=self.planner,
            validator=self.validator,
            max_depth=max_depth
        )

        # Initialize router agent
        self.router = RouterAgent(
            model=model,
            deps_type=None,
            tools=[],
            available_agents=available_agents
        )

    async def run(self, task: str, context: Dict[str, Any] | None = None) -> TaskNode:
        """Execute the threat modeling and orchestration workflow.

        Args:
            task: The security testing task to perform
            context: Optional context dictionary

        Returns:
            TaskNode with the execution plan and results
        """
        # Step 1: Use ADaPT to create a decomposed plan
        plan = await self.adapt_agent.run(task=task, context=context)

        # Step 2: Execute each task node using router to dispatch to appropriate agents
        await self._execute_plan(plan)

        return plan

    async def _execute_plan(self, node: TaskNode):
        """Recursively execute plan nodes using router for agent selection."""
        if node.status in ["completed", "failed", "failed-validation"]:
            return

        # Use router to determine which agent should handle this task
        router_result = await self.router.run(
            user_prompt=f"Which agent should handle: {node.task}",
            deps=None,
            message_history=[],
            usage=None,
            usage_limits=None,
            deferred_tool_results=None
        )

        # Execute with selected agent (generic agents would be called here)
        selected_agent = router_result.output.next_agent_name

        # Recursively process children
        for child in node.children:
            await self._execute_plan(child)