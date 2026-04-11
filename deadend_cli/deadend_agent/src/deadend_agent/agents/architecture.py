from __future__ import annotations

from typing import Any, Literal, AsyncGenerator

from pydantic_ai.usage import RunUsage, UsageLimits

from deadend_agent.agents.components.executor import (
    AgentExecutor,
    LogEvent,
    ResultEvent,
    ValidationStopEvent,
)
from deadend_agent.agents.components.planner import Planner, TaskNode
from deadend_agent.context import ContextEngine
from deadend_agent.hooks import get_event_hooks
from deadend_agent.logging import logger
from deadend_agent.utils.structures import TaskPlanner


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
    - Usage of execution and planning components, with root-goal validation
      handled centrally by the shared executor.
    """
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
        context: ContextEngine,
        executor: AgentExecutor,
        planner: Planner,
        max_depth: int = 3,
    ):
        """Initialize the ADaPT agent.

        Args:
            context: Shared context engine across all agents.
            executor: AgentExecutor instance for executing tasks.
            planner: Planner instance for decomposing tasks.
            max_depth: Maximum depth for task decomposition (default: 3).
        """
        self.max_depth = max_depth
        self.executor = executor
        self.planner = planner
        self.context = context

        # Track attempted tasks to prevent redundant retries.
        # Key: task hash, Value: dict with attempt count and best confidence.
        self._attempted_tasks: dict[int, dict[str, Any]] = {}

    def _session_id(self) -> str:
        return str(getattr(self.context, "session_id", "unknown"))

    def _emit_task_created(self, node: TaskNode) -> None:
        get_event_hooks().emit_task_created(
            session_id=self._session_id(),
            task=node.task,
            task_id=node.task_id,
            depth=node.depth,
            parent_task_id=node.parent_task_id,
            initial_confidence=node.confidence_score,
        )

    def _emit_task_expanded(self, parent: TaskNode, subtasks: list[TaskNode]) -> None:
        get_event_hooks().emit_task_expanded(
            session_id=self._session_id(),
            parent_task=parent.task,
            parent_task_id=parent.task_id,
            subtasks=[
                {
                    "task": subtask.task,
                    "task_id": subtask.task_id,
                    "depth": subtask.depth,
                    "status": subtask.status,
                    "confidence_score": subtask.confidence_score,
                    "parent_task_id": subtask.parent_task_id,
                }
                for subtask in subtasks
            ],
        )

    def _set_task_status(
        self,
        node: TaskNode,
        new_status: str,
        confidence_score: float | None = None,
    ) -> None:
        old_status = node.status
        old_confidence = node.confidence_score
        if confidence_score is not None:
            node.confidence_score = confidence_score
        node.status = new_status
        if old_status == new_status and node.confidence_score == old_confidence:
            return
        get_event_hooks().emit_task_status_changed(
            session_id=self._session_id(),
            task=node.task,
            task_id=node.task_id,
            old_status=old_status,
            new_status=new_status,
            confidence_score=node.confidence_score,
        )

    async def _solve(
        self,
        node: TaskNode,
        depth: int,
        exit_loop: bool,
    ) -> AsyncGenerator[str | dict[str, Any], None]:
        """Recursively solve a task node using the ADaPT algorithm.

        Each supervisor run is executed through the shared executor. The
        executor owns root-goal validation and can emit a stop event when the
        objective has been solved. ADaPT only reacts to that event and then
        falls through to the normal policy (fail / expand / refine) when the
        root goal is still unresolved.

        Args:
            node: The TaskNode to solve.
            depth: Current depth in the decomposition tree.
            exit_loop: Whether an ancestor already requested termination.
        """
        def emit(message: str) -> str:
            return message

        # --- Guard: max depth ---
        if depth > self.max_depth:
            self._set_task_status(node, "aborted:max_depth", 0.5)
            yield emit(f"[ADAPT] Aborted task '{node.task}' at depth {depth} (max_depth={self.max_depth})")
            return

        # --- Guard: duplicate / exhausted tasks ---
        task_hash = hash(node.task)
        if task_hash not in self._attempted_tasks:
            self._attempted_tasks[task_hash] = {"attempts": 0, "best_confidence": 0.0}

        task_record = self._attempted_tasks[task_hash]

        if task_record["best_confidence"] >= self.VALIDATE_THRESHOLD:
            self._set_task_status(node, "completed", task_record["best_confidence"])
            yield emit(f"[SKIP] Task already completed with {task_record['best_confidence']:.2f} confidence")
            return

        if task_record["attempts"] >= self.MAX_TASK_ATTEMPTS:
            self._set_task_status(node, "failed:max_attempts", task_record["best_confidence"])
            yield emit(f"[FAIL] Task exceeded max attempts ({self.MAX_TASK_ATTEMPTS}): '{node.task[:50]}...'")
            return

        task_record["attempts"] += 1
        self.context.clear_current_task_log()
        self._set_task_status(node, "in_progress")

        should_exit = exit_loop

        # Accumulate a log of supervisor ↔ subagent interactions across
        # iterations so the next supervisor call knows what was already tried.
        interaction_history: list[str] = []

        while not should_exit or node.status != "completed":
            # ----- 1. Execute supervisor -----
            tasks_context = self.context.get_tasks(depth=0, include_goal=False)
            unified_context = self.context.get_unified_context(max_tokens=6000)

            if interaction_history:
                history_block = (
                    "## Previous Supervisor Iterations (DO NOT repeat these actions)\n"
                    + "\n".join(interaction_history)
                )
                agent_context = f"{unified_context}\n\n{history_block}\n\n{tasks_context}"
            else:
                agent_context = f"{unified_context}\n\n{tasks_context}"

            executor_stream = self.executor.execute_supervisor(
                task_node=node, agent_context=agent_context,
            )

            confidence_score: float | None = None
            task_achieved: bool = False
            detailed_summary: str = ""
            proofs: str = ""
            new_context: dict[str, Any] | None = None

            async for event in executor_stream:
                if isinstance(event, ResultEvent):
                    confidence_score = event.confidence_score
                    new_context = event.context

                    task_achieved = new_context.get("task_achieved", False)
                    detailed_summary = new_context.get("detailed_summary", "")
                    proofs = new_context.get("proofs", "")

                    if task_achieved:
                        self._set_task_status(node, "completed", confidence_score)
                        self.context.mark_task_completed(node.task, confidence_score)
                        yield emit(f"[SUPERVISOR] Task achieved: {node.task[:50]}...")

                    if detailed_summary:
                        self.context.add_agent_response(
                            f"[Supervisor] {detailed_summary}",
                            skip_structured=False,
                        )

                    if proofs:
                        self.context.add_discovered_fact(
                            category="proof",
                            key=f"proof_{node.task[:30]}",
                            value=proofs,
                            confidence=confidence_score,
                            actionable=not task_achieved,
                        )

                    status_str = "ACHIEVED" if task_achieved else "IN PROGRESS"
                    self.context.structured.append_to_log(
                        f"[Supervisor] Task: {status_str} | Confidence: {confidence_score:.2f}"
                    )
                    break

                elif isinstance(event, ValidationStopEvent):
                    self._set_task_status(node, "completed", event.confidence_score)
                    self.context.mark_task_completed(node.task, event.confidence_score)
                    yield emit(
                        f"[VALIDATION] Root goal achieved (confidence={event.confidence_score:.2f})"
                    )
                    yield event
                    yield {"exit_loop": True}
                    return

                elif isinstance(event, LogEvent):
                    self.context.structured.append_to_log(event.message)
                    yield emit(event.message)
                else:
                    yield emit(str(event))

            if confidence_score is None or new_context is None:
                raise RuntimeError("AgentExecutor did not produce a result.")

            if confidence_score > task_record["best_confidence"]:
                task_record["best_confidence"] = confidence_score

            # Record this iteration so the next supervisor call knows what
            # was already attempted and does not repeat the same actions.
            iteration_entry = (
                f"--- Iteration {len(interaction_history) + 1} ---\n"
                f"Task: {node.task}\n"
                f"Result: {'achieved' if task_achieved else 'not achieved'} "
                f"| confidence={confidence_score:.2f}\n"
                f"Summary: {detailed_summary}\n"
            )
            if proofs:
                iteration_entry += f"Evidence: {proofs}\n"
            # Include the subagent interaction log captured by emit() inside
            # execute_supervisor tool calls (stored in context["log"]).
            exec_log = new_context.get("log", "")
            if exec_log:
                iteration_entry += f"Subagent calls:\n{exec_log}\n"
            interaction_history.append(iteration_entry)

            if detailed_summary:
                yield emit(f"[RESULT] {detailed_summary[:200]}")

            # ----- 2. If subtask done but root goal not yet, continue -----
            if task_achieved:
                yield emit(f"[SUPERVISOR] Subtask completed: {node.task[:50]}...")
                return

            # ----- 3. ADaPT policy (expand / refine / fail) -----
            decision = self._policy(confidence_score)
            logger.debug(
                "task: %s decision: %s confidence: %.2f",
                node.task[:50], decision, confidence_score,
            )

            if decision == "fail":
                self._set_task_status(node, "failed", confidence_score)
                self.context.update_task_status(node.task, "failed", confidence_score)
                yield emit(f"[POLICY] Task '{node.task[:50]}...' failed with confidence {confidence_score:.2f}")
                return

            elif decision == "validate":
                # High subtask confidence — mark subtask done, loop will
                # re-check root goal on next iteration if there's more work.
                self._set_task_status(node, "completed", confidence_score)
                self.context.mark_task_completed(node.task, confidence_score)
                yield emit(f"[POLICY] Subtask validated: '{node.task[:50]}...'")
                return

            elif decision == "expand" and depth < self.max_depth:
                planner_context = (
                    f"{self.context.get_unified_context(max_tokens=5000)}\n\n"
                    f"## Current Plan Status\n{self.context.get_tasks(include_goal=False)}\n\n"
                    "## Instructions\n"
                    "Analyze what has been achieved and expand the plan with only what still needs to be done.\n"
                    "Update confidence_score based on progress. Reason step by step for the most logical plan.\n"
                )
                subtasks, website_info, exploit_info = await self.planner.expand(
                    node,
                    context=planner_context,
                    usage=RunUsage(),
                    usage_limits=UsageLimits(request_limit=None),
                )
                formatted_website_info = _format_dict_for_context(website_info.model_dump())
                self.context.add_tool_response("website_info", formatted_website_info)
                if exploit_info.reasoning or exploit_info.highly_possible_vulnerabilities:
                    formatted_exploit_info = _format_dict_for_context(exploit_info.model_dump())
                    self.context.add_tool_response("exploit_info", formatted_exploit_info)

                planner_subtasks = [
                    TaskPlanner(task=s.task, confidence_score=s.confidence_score, status=s.status)
                    for s in subtasks
                ]
                parent_planner = TaskPlanner(
                    task=node.task,
                    confidence_score=node.confidence_score,
                    status=node.status,
                )
                self.context.add_tasks(parent_task=parent_planner, tasks=planner_subtasks)
                for subtask in subtasks:
                    self._emit_task_created(subtask)
                self._emit_task_expanded(node, subtasks)

                if not subtasks:
                    self._set_task_status(node, "refine")
                    yield emit(f"[PLANNER] No subtasks generated for '{node.task}', requesting refinement")
                    if node.parent:
                        async for chunk in self._solve(node.parent, depth=node.depth, exit_loop=exit_loop):
                            if isinstance(chunk, dict) and chunk.get("exit_loop"):
                                should_exit = True
                                yield chunk
                                break
                            yield chunk
                    break

                node.children = subtasks
                yield emit(f"[PLANNER] Generated {len(subtasks)} subtasks for '{node.task}'")
                for subtask in subtasks:
                    async for chunk in self._solve(subtask, depth + 1, exit_loop=exit_loop):
                        if isinstance(chunk, dict) and chunk.get("exit_loop"):
                            should_exit = True
                            yield chunk
                            break
                        yield chunk
                    else:
                        continue
                    break

            # refine (60-80% or expand at max depth)
            else:
                planner_context = (
                    f"{self.context.get_unified_context(max_tokens=5000)}\n\n"
                    f"## Current Plan Status\n{self.context.get_tasks(include_goal=False)}\n\n"
                    "## Instructions\n"
                    "Analyze what has been achieved and update the plan with only what still needs to be done.\n"
                    "Update confidence_score for completed items. Reason step by step for the most logical updated plan.\n"
                )
                updated_tasks, website_info, exploit_info = await self.planner.update_plan(
                    node,
                    context=planner_context,
                    usage=RunUsage(),
                    usage_limits=UsageLimits(request_limit=None),
                )
                formatted_website_info = _format_dict_for_context(website_info.model_dump())
                self.context.add_tool_response("website_info", formatted_website_info)
                if exploit_info.reasoning or exploit_info.highly_possible_vulnerabilities:
                    formatted_exploit_info = _format_dict_for_context(exploit_info.model_dump())
                    self.context.add_tool_response("exploit_info", formatted_exploit_info)

                parent_task = node.parent

                if parent_task:
                    parent_task.children = updated_tasks
                    updated_node = None
                    for updated_task in updated_tasks:
                        if updated_task.task == node.task:
                            updated_node = updated_task
                            break
                    node = updated_node if updated_node else updated_tasks[0] if updated_tasks else node
                else:
                    if updated_tasks:
                        node = updated_tasks[0]

                planner_subtasks = [
                    TaskPlanner(task=s.task, confidence_score=s.confidence_score, status=s.status)
                    for s in updated_tasks
                ]

                if parent_task:
                    parent_planner = TaskPlanner(
                        task=parent_task.task,
                        confidence_score=parent_task.confidence_score,
                        status=parent_task.status,
                    )
                    self.context.add_tasks(parent_task=parent_planner, tasks=planner_subtasks)
                else:
                    self.context.add_tasks(parent_task=None, tasks=planner_subtasks)
                for updated_task in updated_tasks:
                    self._emit_task_created(updated_task)
                if parent_task:
                    self._emit_task_expanded(parent_task, updated_tasks)

                yield emit(
                    f"[PLANNER] Updated plan for tasks "
                    f"with parent '{parent_task.task if parent_task else 'root'}'"
                )

                async for chunk in self._solve(node=node, depth=depth, exit_loop=exit_loop):
                    if isinstance(chunk, dict) and chunk.get("exit_loop"):
                        should_exit = True
                        yield chunk
                        break
                    yield chunk


    def _policy(self, confidence_score: float) -> Literal["fail", "expand", "refine", "validate"]:
        """Determine the next action for a subtask based on its confidence score.

        - <20%  : fail — unrecoverable, propagate failure.
        - 20-60%: expand — decompose into finer-grained subtasks.
        - 60-80%: refine — iterate on the same task.
        - >=80% : validate — subtask confidence is high, mark done.

        Note: root-goal validation is handled by the ValidationGate,
        not by this policy.  'validate' here only means the *subtask*
        has high enough confidence to be considered complete.
        """
        if confidence_score < self.FAIL_THRESHOLD:
            return "fail"
        elif confidence_score < self.EXPLORE_THRESHOLD:
            return "expand"
        elif confidence_score >= self.VALIDATE_THRESHOLD:
            return "validate"
        return "refine"

    async def run(
        self,
        task: str,
        context: str | None = None,
    ) -> AsyncGenerator[str | dict[str, Any], None]:
        """Run the ADaPT agent on a given task.

        Creates a root task node and recursively solves it using the ADaPT
        algorithm, which includes execution, planning, and validation phases.

        Args:
            task: The main task description to execute.
            context: Optional initial context string for the planner.

        Yields:
            Human-readable log strings describing progress followed by a
            final {"type": "result", "root": TaskNode} event.
        """
        self._attempted_tasks.clear()

        root = TaskNode(
            task=task,
            depth=0,
            confidence_score=0.7,
            status="pending",
            parent=None,
            children=[],
        )
        self._emit_task_created(root)

        subtasks, website_info, exploit_info = await self.planner.expand(
            root,
            context=context if context else "",
            usage=RunUsage(),
            usage_limits=UsageLimits(request_limit=None),
        )

        # Store website info as discovered facts.
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
                            confidence=0.8,
                        )
            else:
                self.context.add_discovered_fact(
                    category="website_info",
                    key="general",
                    value=str(info)[:200],
                    confidence=0.8,
                )

        # Store exploit info as discovered facts.
        if exploit_info.reasoning or exploit_info.highly_possible_vulnerabilities:
            if exploit_info.highly_possible_vulnerabilities:
                vulns_raw = exploit_info.highly_possible_vulnerabilities
                if isinstance(vulns_raw, str):
                    if "," in vulns_raw:
                        vulns = [v.strip() for v in vulns_raw.split(",") if v.strip()]
                    elif "\n" in vulns_raw:
                        vulns = [v.strip() for v in vulns_raw.split("\n") if v.strip()]
                    else:
                        vulns = [vulns_raw.strip()] if vulns_raw.strip() else []
                else:
                    vulns = list(vulns_raw) if vulns_raw else []

                for vuln in vulns[:5]:
                    self.context.add_discovered_fact(
                        category="vulnerability",
                        key=str(vuln)[:50],
                        value=str(vuln),
                        confidence=0.6,
                    )

        planner_subtasks = [
            TaskPlanner(task=s.task, confidence_score=s.confidence_score, status=s.status)
            for s in subtasks
        ]
        self.context.add_tasks(parent_task=None, tasks=planner_subtasks)
        for subtask in subtasks:
            self._emit_task_created(subtask)
        self._emit_task_expanded(root, subtasks)

        exit_loop_triggered = False
        for subtask in subtasks:
            async for chunk in self._solve(subtask, depth=1, exit_loop=False):
                if isinstance(chunk, dict) and chunk.get("exit_loop"):
                    exit_loop_triggered = True
                    yield chunk
                    break
                yield chunk
            if exit_loop_triggered:
                break

        root.children = subtasks
        yield {"type": "result", "root": root}
