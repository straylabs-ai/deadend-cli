
import re
from typing import Any, Literal, AsyncGenerator, Tuple
from uuid import UUID
from uuid import UUID, uuid4
from deadend_agent.agents.exploit_web_agent import ExploitInfo, ExploitOutput
from deadend_agent.agents.recon_threatmodel_agent import GeneralInfoOutput, ThreatModelOutput
from pydantic import BaseModel, Field
from pydantic_ai import DeferredToolResults, RunContext
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.usage import RunUsage, UsageLimits
from deadend_agent.agents.components.planner import TaskNode
from deadend_agent.utils.structures import TaskPlanner
from deadend_agent.agents.components.executor import AgentExecutor, ResultEvent, LogEvent
from deadend_agent.agents.components.planner import Planner
from deadend_agent.agents.components.validator import Validator
from deadend_agent.context import ContextEngine


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
    - Usage of 3 components Executors, Planner and Validator.
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

        while not should_exit or node.status != 'completed':
        # We need to add that this loop should run while we still have the task running
        # and not comple otherwise we should exit_loop too.
            # Build UNIFIED context for executor (same as all other agents)
            # This ensures router, executor, validator all see the same information
            tasks_context = self.context.get_tasks(depth=0, include_goal=False)
            unified_context = self.context.get_unified_context(max_tokens=6000)
            agent_context = f"{unified_context}\n\n{tasks_context}"
            # First here, we should give the executor the right task. which means the right
            # task with the right context to achieve this task.the supervisor is actually
            # more of a subagent.
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
                        # if "FLAG{" in proofs.upper():
                        #     flag_match = re.search(r'FLAG\{[^}]+\}', proofs, re.IGNORECASE)
                        #     if flag_match:
                        #         self.context.add_discovered_fact(
                        #             category="validated_exploit",
                        #             key="captured_flag",
                        #             value=f"FLAG CAPTURED: {flag_match.group(0)}",
                        #             confidence=1.0,
                        #             details={
                        #                 "flag": flag_match.group(0),
                        #                 "source": "supervisor_proofs",
                        #                 "task": node.task[:100]
                        #             },
                        #             actionable=False
                        #         )

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
                print(f"task: {node.task[:50]}... decision: {decision}, \
                    confidence: {confidence_score:.2f}")
            except (BlockingIOError, OSError):
                pass

            # If decision fails <20%
            if decision == "fail":
                node.status = "failed"
                self.context.update_task_status(node.task, "failed", confidence_score)
                yield emit(f"[POLICY] Task '{node.task[:50]}...' \
                    failed with confidence {confidence_score:.2f}")
                return

            # If the decision is validate >80%
            elif decision == "validate":
                node.status, validation_token = await self._validate(node)
                yield emit(f"[POLICY] Validation completed for \
                    '{node.task[:50]}...' with status {node.status}")
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

        (valid, confidence_score, critique, validation_token) = await self.validator.verify(
            task=node,
            context=validation_context_text
        )

        # Record validation result compactly
        validation_summary = f"Validation: {critique[:100]}, confidence: {confidence_score:.2f}"
        if validation_token:
            validation_summary += f", token: {validation_token}"

        # Add to structured context only (avoid bloating workflow_context)
        self.context.structured.append_to_log(validation_summary)
        self.context.add_agent_response(validation_summary, skip_structured=True)

        node.confidence_score = confidence_score

        # If validation passed, add validated result as high-confidence fact
        # This ensures the successful exploit details persist in context for next agents
        if valid:
            # Extract recent successful attempts to preserve as facts
            successful_attempts = [a for a in self.context.structured.attempts if a.result == "success"]
            for attempt in successful_attempts[-3:]:  # Last 3 successful
                self.context.structured.add_fact_simple(
                    category="validated_exploit",
                    key=f"{node.task[:50]}",
                    value=f"Payload: {attempt.payload}",
                    confidence=confidence_score,
                    source_task=node.task,
                    details={
                        "payload": attempt.payload,
                        "reason": attempt.reason,
                        "validation_token": validation_token,
                        "task": attempt.task
                    },
                    actionable=True
                )

        return ("completed", validation_token) if valid else ("failed-validation", validation_token)

    async def run(
        self,
        task: str,
        exit_strategy: str,
        context: str | None = None,
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

        # # Use UNIFIED context for initial planning (same as all other agents)
        # initial_context = self.context.get_unified_context(max_tokens=4000)
        subtasks, website_info, exploit_info = await self.planner.expand(
            root,
            context=context,
            usage=RunUsage(),
            usage_limits=UsageLimits(request_limit=None)
        )
        print(f"subtasks: {subtasks}")
        print(f"website info: {website_info}")

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
                # Handle both string and list formats
                vulns_raw = exploit_info.highly_possible_vulnerabilities
                if isinstance(vulns_raw, str):
                    # Split by comma or newline if it's a string
                    if ',' in vulns_raw:
                        vulns = [v.strip() for v in vulns_raw.split(',') if v.strip()]
                    elif '\n' in vulns_raw:
                        vulns = [v.strip() for v in vulns_raw.split('\n') if v.strip()]
                    else:
                        # Single vulnerability as string
                        vulns = [vulns_raw.strip()] if vulns_raw.strip() else []
                else:
                    vulns = list(vulns_raw) if vulns_raw else []

                for vuln in vulns[:5]:  # Limit to 5
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
