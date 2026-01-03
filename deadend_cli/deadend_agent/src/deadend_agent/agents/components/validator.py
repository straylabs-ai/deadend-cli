from pydantic import BaseModel
from deadend_agent.agents.components.planner import TaskNode
from deadend_agent.models import AIModel
from deadend_agent.agents import AgentRunner
from deadend_prompts import render_agent_instructions


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
