# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Context engine for managing workflow state and task coordination.

This module provides context management functionality for security research
workflows, including task tracking, workflow state management, and agent
routing based on current context and progress.
"""
import json
import uuid
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Any, TYPE_CHECKING

from deadend_agent.models import AIModel
from deadend_agent.utils.structures import Task, TaskPlanner
from deadend_agent.utils.functions import num_tokens_from_string

if TYPE_CHECKING:
    from deadend_agent.agents import RouterOutput
    from deadend_agent.agents.reporter import ReporterAgent



@dataclass
class DiscoveredFact:
    """Discovered information about the target with actionable details.

    Attributes:
        category: Type of discovery (endpoint, parameter, auth_method, filter, technology, vulnerability)
        key: Unique identifier within category (e.g., "/page", "name")
        value: Description or details of the discovery
        details: Additional structured details (e.g., {"method": "GET", "filters": ["<", "/"]})
        source_task: Task that discovered this fact
        confidence: Confidence score (0.0-1.0)
        actionable: Whether this fact suggests a next action
    """
    category: str
    key: str
    value: str
    details: Dict[str, Any] = field(default_factory=dict)
    source_task: str = ""
    confidence: float = 0.5
    actionable: bool = False


@dataclass
class AttemptRecord:
    """Record of an exploitation or testing attempt.

    Attributes:
        task: Task description that triggered this attempt
        payload: The payload or action attempted
        result: Outcome (success, failed, blocked, partial)
        reason: Explanation of the result
        timestamp: Unix timestamp of the attempt
    """
    task: str
    payload: str
    result: str  # "success", "failed", "blocked", "partial"
    reason: str
    timestamp: float = field(default_factory=time.time)

    def get_hash(self) -> str:
        """Generate hash for deduplication based on payload and task."""
        return f"{hash(self.payload)}:{hash(self.task[:50])}"


@dataclass
class ExecutionRecord:
    """Structured record of an agent execution with clear semantics.

    Captures what was done in a way that's easy for subsequent agents to understand.

    Attributes:
        action: What action was taken (e.g., "HTTP Request", "Script Execution")
        target_endpoint: The specific endpoint/resource targeted
        technique: The technique/approach used (e.g., "XSS injection", "SQLi UNION")
        parameters: Key parameters used in the attempt
        result_status: Clear status (success, failed, blocked, partial, error)
        key_finding: The most important finding from this execution
        response_summary: Brief summary of the response received
        agent_name: Which agent performed this action
        timestamp: When this was executed
    """
    action: str
    target_endpoint: str
    technique: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    result_status: str = "unknown"
    key_finding: str = ""
    response_summary: str = ""
    agent_name: str = ""
    timestamp: float = field(default_factory=time.time)

    def get_hash(self) -> str:
        """Generate hash for deduplication."""
        return f"{hash(self.action)}:{hash(self.target_endpoint)}:{hash(self.technique)}"

    def format_for_context(self) -> str:
        """Format this record for inclusion in agent context."""
        lines = [f"• {self.action} → {self.target_endpoint}"]
        if self.technique:
            lines.append(f"  Technique: {self.technique}")
        if self.parameters:
            param_str = ", ".join(f"{k}={v}" for k, v in list(self.parameters.items())[:3])
            lines.append(f"  Parameters: {param_str}")
        lines.append(f"  Result: {self.result_status}")
        if self.key_finding:
            lines.append(f"  Finding: {self.key_finding}")
        return "\n".join(lines)


@dataclass
class AgentThought:
    """Captured reasoning/thought from an agent execution.

    Attributes:
        agent_name: Which agent produced this thought
        thought: The raw thought/reasoning text
        summary: A concise summary of the key insight
        relevance: How relevant this is for future actions (0.0-1.0)
        timestamp: When this was recorded
    """
    agent_name: str
    thought: str
    summary: str = ""
    relevance: float = 0.5
    timestamp: float = field(default_factory=time.time)

    def format_for_context(self) -> str:
        """Format for context output."""
        if self.summary:
            return f"[{self.agent_name}] {self.summary}"
        # Truncate raw thought if no summary
        truncated = self.thought[:150] + "..." if len(self.thought) > 150 else self.thought
        return f"[{self.agent_name}] {truncated}"


class StructuredContext:
    """Segmented context for efficient LLM consumption.

    Separates context into:
    - target: The target URL/host being tested (ALWAYS included in context)
    - facts: Deduplicated discovered information
    - attempts: History of exploitation attempts (legacy)
    - executions: Structured execution records (new, preferred)
    - thoughts: Agent reasoning/insights
    - failed_approaches: Set of failed attempt hashes to prevent retries
    - tested_techniques: Set of (endpoint, technique) pairs already tested
    """

    def __init__(self, goal: str = "", target: str = ""):
        self.goal: str = goal
        self.target: str = target  # Target URL/host - ALWAYS included in context
        self.facts: Dict[str, DiscoveredFact] = {}
        self.attempts: List[AttemptRecord] = []  # Legacy, kept for compatibility
        self.executions: List[ExecutionRecord] = []  # Structured execution history
        self.thoughts: List[AgentThought] = []  # Agent reasoning
        self.failed_approaches: Set[str] = set()
        self.tested_techniques: Set[str] = set()  # (endpoint:technique) pairs
        self.current_task_log: str = ""
        self.completed_tasks: List[str] = []
        self._max_log_chars: int = 50000  # Limit current log size
        self._max_executions: int = 50  # Keep last N executions
        self._max_thoughts: int = 20  # Keep last N thoughts

    def set_goal(self, goal: str) -> None:
        """Set the primary goal for context."""
        self.goal = goal

    def set_target(self, target: str) -> None:
        """Set the target URL/host for context."""
        self.target = target

    def add_fact(self, fact: DiscoveredFact) -> bool:
        """Add a discovered fact, deduplicating by category:key.

        Returns:
            True if fact was added/updated, False if duplicate with lower confidence.
        """
        key = f"{fact.category}:{fact.key}"
        if key in self.facts:
            # Update only if higher confidence
            if fact.confidence > self.facts[key].confidence:
                self.facts[key] = fact
                return True
            return False
        self.facts[key] = fact
        return True

    def add_fact_simple(
        self,
        category: str,
        key: str,
        value: str,
        confidence: float = 0.7,
        source_task: str = "",
        details: Dict[str, Any] | None = None,
        actionable: bool = False
    ) -> bool:
        """Convenience method to add a fact without creating DiscoveredFact manually.

        Args:
            category: Type of discovery (endpoint, parameter, filter, vulnerability, etc.)
            key: Unique identifier (e.g., "/page", "name")
            value: Description of the discovery
            confidence: Confidence score (0.0-1.0)
            source_task: Task that discovered this
            details: Additional structured details for agent understanding
            actionable: Whether this suggests a next action
        """
        return self.add_fact(DiscoveredFact(
            category=category,
            key=key,
            value=value,
            details=details or {},
            confidence=confidence,
            source_task=source_task,
            actionable=actionable
        ))

    def record_attempt(self, attempt: AttemptRecord) -> bool:
        """Record an exploitation attempt.

        Returns:
            False if this exact attempt was already tried and failed.
        """
        attempt_hash = attempt.get_hash()
        if attempt_hash in self.failed_approaches:
            return False  # Already tried and failed

        self.attempts.append(attempt)
        if attempt.result in ("failed", "blocked"):
            self.failed_approaches.add(attempt_hash)
        return True

    def record_attempt_simple(
        self,
        task: str,
        payload: str,
        result: str,
        reason: str
    ) -> bool:
        """Convenience method to record an attempt."""
        return self.record_attempt(AttemptRecord(
            task=task,
            payload=payload,
            result=result,
            reason=reason
        ))

    def was_already_attempted(self, payload: str, task: str) -> bool:
        """Check if a similar attempt was already made and failed."""
        test_hash = f"{hash(payload)}:{hash(task[:50])}"
        return test_hash in self.failed_approaches

    def mark_task_completed(self, task: str) -> None:
        """Mark a task as completed."""
        if task not in self.completed_tasks:
            self.completed_tasks.append(task)

    def append_to_log(self, message: str) -> None:
        """Append to current task log with size management."""
        self.current_task_log += f"\n{message}"
        # Truncate from beginning if too long
        if len(self.current_task_log) > self._max_log_chars:
            self.current_task_log = self.current_task_log[-self._max_log_chars:]

    def clear_current_log(self) -> None:
        """Clear current task log (call when moving to new task)."""
        self.current_task_log = ""

    def add_execution(self, record: ExecutionRecord) -> bool:
        """Add a structured execution record.

        Returns:
            False if this technique was already tested on this endpoint.
        """
        technique_key = f"{record.target_endpoint}:{record.technique}"

        # Check for duplicate technique on same endpoint
        if technique_key in self.tested_techniques and record.result_status != "success":
            return False  # Already tested this

        self.executions.append(record)
        self.tested_techniques.add(technique_key)

        # Keep list bounded
        if len(self.executions) > self._max_executions:
            self.executions = self.executions[-self._max_executions:]

        # Also track as failed approach if failed
        if record.result_status in ("failed", "blocked"):
            self.failed_approaches.add(record.get_hash())

        return True

    def add_execution_simple(
        self,
        action: str,
        target_endpoint: str,
        technique: str,
        result_status: str,
        key_finding: str = "",
        parameters: Dict[str, Any] | None = None,
        response_summary: str = "",
        agent_name: str = ""
    ) -> bool:
        """Convenience method to add an execution record."""
        return self.add_execution(ExecutionRecord(
            action=action,
            target_endpoint=target_endpoint,
            technique=technique,
            parameters=parameters or {},
            result_status=result_status,
            key_finding=key_finding,
            response_summary=response_summary,
            agent_name=agent_name
        ))

    def add_thought(self, thought: AgentThought) -> None:
        """Add an agent thought/reasoning to context."""
        self.thoughts.append(thought)
        # Keep list bounded
        if len(self.thoughts) > self._max_thoughts:
            self.thoughts = self.thoughts[-self._max_thoughts:]

    def add_thought_simple(
        self,
        agent_name: str,
        thought: str,
        summary: str = "",
        relevance: float = 0.5
    ) -> None:
        """Convenience method to add an agent thought."""
        self.add_thought(AgentThought(
            agent_name=agent_name,
            thought=thought,
            summary=summary,
            relevance=relevance
        ))

    def was_technique_tested(self, endpoint: str, technique: str) -> bool:
        """Check if a specific technique was already tested on an endpoint."""
        return f"{endpoint}:{technique}" in self.tested_techniques

    def get_tested_techniques_for_endpoint(self, endpoint: str) -> List[str]:
        """Get all techniques that were tested on a specific endpoint."""
        result = []
        for key in self.tested_techniques:
            if key.startswith(f"{endpoint}:"):
                result.append(key.split(":", 1)[1])
        return result

    def get_facts_summary(self) -> str:
        """Get actionable summary of discovered facts for LLM context.

        Format is optimized for agent understanding with:
        - Clear categorization
        - Actionable details when available
        - Confidence indicators for uncertain facts
        """
        if not self.facts:
            return ""

        lines = ["## Discovered Information"]

        # Group by category for readability
        by_category: Dict[str, List[DiscoveredFact]] = {}
        for fact in self.facts.values():
            if fact.category not in by_category:
                by_category[fact.category] = []
            by_category[fact.category].append(fact)

        # Priority order: validated exploits first, then vulnerabilities, endpoints, others
        priority_order = ["validated_exploit", "vulnerability", "endpoint", "parameter", "filter", "auth_method", "technology"]
        sorted_categories = sorted(
            by_category.keys(),
            key=lambda c: priority_order.index(c) if c in priority_order else len(priority_order)
        )

        for category in sorted_categories:
            facts = by_category[category]
            lines.append(f"\n### {category.title()}s")

            for fact in sorted(facts, key=lambda f: -f.confidence):
                # Build fact line with key info
                confidence_marker = "✓" if fact.confidence >= 0.8 else "?" if fact.confidence < 0.5 else ""
                fact_line = f"- {confidence_marker} {fact.key}: {fact.value}"

                # Add actionable details if present
                if fact.details:
                    detail_parts = []
                    for k, v in fact.details.items():
                        if isinstance(v, list):
                            detail_parts.append(f"{k}=[{', '.join(str(x) for x in v[:5])}]")
                        elif v:
                            detail_parts.append(f"{k}={v}")
                    if detail_parts:
                        fact_line += f" ({'; '.join(detail_parts)})"

                # Mark actionable facts
                if fact.actionable:
                    fact_line += " [ACTION NEEDED]"

                lines.append(fact_line)

        return "\n".join(lines)

    def get_failed_approaches_summary(self) -> str:
        """Get summary of failed approaches with learnings for the agent.

        Format helps the agent understand:
        - What was tried
        - Why it failed
        - What to try differently
        """
        failed = [a for a in self.attempts if a.result in ("failed", "blocked")]
        if not failed:
            return ""

        # Group by failure reason pattern to identify systematic issues
        lines = ["## Failed Approaches (Learn From These)"]
        lines.append("Do NOT retry these exact approaches. Analyze why they failed.\n")

        # Show recent failures with context
        recent_failures = failed[-8:]  # Last 8 failures
        for i, attempt in enumerate(recent_failures, 1):
            payload_preview = attempt.payload[:100] + "..." if len(attempt.payload) > 100 else attempt.payload
            lines.append(f"{i}. **Tried**: {payload_preview}")
            lines.append(f"   **Result**: {attempt.result}")
            lines.append(f"   **Why**: {attempt.reason[:150]}")
            lines.append("")

        # Add guidance based on failure patterns
        blocked_count = sum(1 for a in failed if a.result == "blocked")
        if blocked_count > 2:
            lines.append("⚠️ Multiple blocked attempts suggest filters/WAF. Try encoding or alternative vectors.")

        return "\n".join(lines)

    def get_successful_attempts(self) -> str:
        """Get summary of successful attempts."""
        successful = [a for a in self.attempts if a.result == "success"]
        if not successful:
            return ""

        lines = ["## Successful Actions"]
        for attempt in successful[-5:]:  # Last 5 successes
            lines.append(f"- {attempt.task[:50]}: {attempt.reason[:100]}")

        return "\n".join(lines)

    def get_executor_context(self, max_tokens: int = 6000) -> str:
        """Get optimized context for task execution.

        Prioritizes: goal > successful attempts > facts > failed approaches > current log
        Respects token budget.
        """
        parts = []
        remaining = max_tokens

        # 1. Goal (always include)
        if self.goal:
            goal_text = f"## Primary Goal\n{self.goal}"
            goal_tokens = num_tokens_from_string(goal_text)
            parts.append(goal_text)
            remaining -= goal_tokens

        # 2. Successful attempts (CRITICAL - must not lose working exploits)
        successful = [a for a in self.attempts if a.result == "success"]
        if successful:
            success_lines = ["## Successful Exploits (IMPORTANT - use these as reference)"]
            for attempt in successful[-10:]:  # Last 10 successful
                success_lines.append(f"- Task: {attempt.task[:80]}")
                success_lines.append(f"  Payload: {attempt.payload[:200]}")
                success_lines.append(f"  Result: {attempt.reason[:150]}")
            success_text = "\n".join(success_lines)
            success_tokens = num_tokens_from_string(success_text)
            if success_tokens < remaining:
                parts.append(success_text)
                remaining -= success_tokens

        # 3. Facts (high priority)
        facts_text = self.get_facts_summary()
        if facts_text:
            facts_tokens = num_tokens_from_string(facts_text)
            if facts_tokens < remaining:
                parts.append(facts_text)
                remaining -= facts_tokens

        # 4. Failed approaches (important to avoid loops)
        failed_text = self.get_failed_approaches_summary()
        if failed_text:
            failed_tokens = num_tokens_from_string(failed_text)
            if failed_tokens < remaining:
                parts.append(failed_text)
                remaining -= failed_tokens

        # 5. Current log (truncate if needed)
        if self.current_task_log:
            log_text = f"## Current Execution\n{self.current_task_log}"
            log_tokens = num_tokens_from_string(log_text)
            if log_tokens > remaining:
                # Truncate from beginning, keep recent
                available_chars = int(remaining * 3.5)  # ~3.5 chars per token estimate
                truncated_log = self.current_task_log[-available_chars:]
                log_text = f"## Current Execution (truncated)\n...{truncated_log}"
            parts.append(log_text)

        return "\n\n".join(parts)

    def get_validation_context(self) -> str:
        """Get focused context for validation with execution evidence.

        Provides the validator with:
        - The goal being validated
        - Recent execution attempts and outcomes (all tool calls)
        - Evidence from execution log
        - Key discovered facts
        """
        parts = []

        # Include goal for reference
        if self.goal:
            parts.append(f"## Goal Being Validated\n{self.goal}")

        # Show all recent attempts for comprehensive validation (not just the last one)
        if self.attempts:
            parts.append("\n## Execution Attempts (All Tool Calls)")

            # Group attempts by result for clarity
            successful = [a for a in self.attempts if a.result == "success"]
            partial = [a for a in self.attempts if a.result == "partial"]
            failed = [a for a in self.attempts if a.result in ("failed", "blocked")]

            if successful:
                parts.append(f"\n### Successful ({len(successful)})")
                for attempt in successful[-5:]:  # Last 5 successful
                    parts.append(f"- Task: {attempt.task[:80]}")
                    parts.append(f"  Payload: {attempt.payload[:120]}")
                    parts.append(f"  Why: {attempt.reason[:150]}")

            if partial:
                parts.append(f"\n### Partial Success ({len(partial)})")
                for attempt in partial[-3:]:
                    parts.append(f"- Task: {attempt.task[:80]}")
                    parts.append(f"  Payload: {attempt.payload[:120]}")
                    parts.append(f"  Why: {attempt.reason[:150]}")

            if failed:
                parts.append(f"\n### Failed/Blocked ({len(failed)})")
                for attempt in failed[-5:]:  # Last 5 failed
                    parts.append(f"- Task: {attempt.task[:80]}")
                    parts.append(f"  Payload: {attempt.payload[:100]}")
                    parts.append(f"  Why: {attempt.reason[:100]}")

        # Include relevant log evidence
        if self.current_task_log:
            # Extract key evidence from log (look for responses, flags, errors)
            log_excerpt = self.current_task_log[-3000:]
            parts.append(f"\n## Execution Evidence\n{log_excerpt}")
        else:
            parts.append("\n## Execution Evidence\nNo execution log available.")

        # Include any high-confidence facts that might be relevant
        high_confidence_facts = [f for f in self.facts.values() if f.confidence >= 0.8]
        if high_confidence_facts:
            parts.append("\n## Confirmed Discoveries")
            for fact in high_confidence_facts[:5]:
                parts.append(f"- {fact.category}: {fact.key} = {fact.value}")

        return "\n".join(parts)

    def get_planning_context(self) -> str:
        """Get strategic context for planner decisions.

        Provides the planner with:
        - Clear goal statement
        - Progress summary (what's done, what's not)
        - Key discoveries that inform next steps
        - Failed approaches to avoid
        """
        parts = []

        # Goal with emphasis
        if self.goal:
            parts.append(f"## Primary Goal\n{self.goal}")

        # Progress summary
        total_attempts = len(self.attempts)
        successful = sum(1 for a in self.attempts if a.result == "success")
        failed = sum(1 for a in self.attempts if a.result in ("failed", "blocked"))

        if total_attempts > 0:
            parts.append("\n## Progress Summary")
            parts.append(f"- Total attempts: {total_attempts}")
            parts.append(f"- Successful: {successful}")
            parts.append(f"- Failed/Blocked: {failed}")

        # Completed tasks
        if self.completed_tasks:
            parts.append("\n## Completed Tasks")
            for t in self.completed_tasks[-8:]:
                parts.append(f"✓ {t[:100]}")

        # Key discoveries (actionable ones first)
        facts = self.get_facts_summary()
        if facts:
            parts.append(f"\n{facts}")

        # What to avoid
        failed_summary = self.get_failed_approaches_summary()
        if failed_summary:
            parts.append(f"\n{failed_summary}")

        # Suggest next direction based on state
        if self.facts:
            actionable = [f for f in self.facts.values() if f.actionable]
            if actionable:
                parts.append("\n## Suggested Focus")
                parts.append("The following discoveries suggest next actions:")
                for fact in actionable[:3]:
                    parts.append(f"- {fact.category}: {fact.key} - {fact.value[:80]}")

        return "\n\n".join(parts)

    def get_unified_context(self, max_tokens: int = 6000) -> str:
        """Get UNIFIED context for ALL agents.

        Single source of truth with NO duplication, NO truncation of critical info.
        """
        sections = []

        # SECTION 1: TARGET + GOAL (once only)
        header = f"Target: {self.target}\n" if self.target else ""
        if self.goal:
            goal_clean = self.goal.replace(self.target, "").strip() if self.target else self.goal
            header += f"{goal_clean}"  # Full goal, no truncation
        if header:
            sections.append(header)

        # SECTION 2: FLAG FOUND (if any) - with FULL reproduction steps
        flag_facts = [f for f in self.facts.values()
                      if f.category == "validated_exploit" or "flag" in f.key.lower()]
        flag_execs = [e for e in self.executions
                      if "flag" in e.key_finding.lower() or e.result_status == "success"]

        if flag_facts or flag_execs:
            lines = ["## ⚑ FLAG/EXPLOIT FOUND - REPRODUCTION STEPS"]
            for fact in flag_facts:
                lines.append(f"Target: {fact.key}")
                lines.append(f"Method: {fact.value}")
                if fact.details:
                    if fact.details.get("payload"):
                        lines.append(f"Payload: {fact.details['payload']}")
                    if fact.details.get("endpoint"):
                        lines.append(f"Endpoint: {fact.details['endpoint']}")
                    if fact.details.get("validation_token"):
                        lines.append(f"Flag: {fact.details['validation_token']}")
            for exec_rec in flag_execs:
                lines.append(f"Action: {exec_rec.action}")
                lines.append(f"Endpoint: {exec_rec.target_endpoint}")
                lines.append(f"Technique: {exec_rec.technique}")
                if exec_rec.parameters:
                    lines.append(f"Parameters: {exec_rec.parameters}")
                lines.append(f"Result: {exec_rec.key_finding}")
            sections.append("\n".join(lines))

        # SECTION 3: COMPLETE TEST HISTORY (exhaustive, no truncation)
        if self.executions:
            by_endpoint: Dict[str, List[ExecutionRecord]] = {}
            for ex in self.executions:
                ep = ex.target_endpoint
                if ep not in by_endpoint:
                    by_endpoint[ep] = []
                by_endpoint[ep].append(ex)

            lines = ["## COMPLETE TEST HISTORY"]
            lines.append("Every technique tested per endpoint:")

            for endpoint, execs in sorted(by_endpoint.items()):
                successes = [e for e in execs if e.result_status == "success"]
                failures = [e for e in execs if e.result_status != "success"]

                lines.append(f"\n### {endpoint}")
                if successes:
                    lines.append("✓ WORKED:")
                    for ex in successes:
                        lines.append(f"  - {ex.technique}")
                        if ex.key_finding:
                            lines.append(f"    → {ex.key_finding}")
                if failures:
                    lines.append("✗ FAILED:")
                    for ex in failures:
                        reason = ex.key_finding or ex.result_status
                        lines.append(f"  - {ex.technique} [{reason}]")

            sections.append("\n".join(lines))

        # SECTION 4: KEY DISCOVERIES (full text, no truncation)
        findings = [f for f in self.facts.values()
                    if f.category in ("finding", "technology", "attack_vector", "feature")]
        if findings:
            lines = ["## KEY DISCOVERIES"]
            for fact in sorted(findings, key=lambda f: -f.confidence):
                lines.append(f"[{fact.category}] {fact.key}: {fact.value}")
                if fact.details:
                    for k, v in fact.details.items():
                        if v and k not in ("source",):
                            lines.append(f"  {k}: {v}")
            sections.append("\n".join(lines))

        # SECTION 5: IDENTIFIED ENDPOINTS
        endpoints = [f for f in self.facts.values() if f.category == "endpoint"]
        if endpoints:
            lines = ["## ENDPOINTS"]
            for ep in endpoints:
                details = ep.details or {}
                params = details.get("parameters", [])
                auth = "🔒" if details.get("auth_required") else "🔓"
                techs = ", ".join(details.get("technologies", [])) or ""
                notes = details.get("notes", "")
                line = f"{auth} {ep.key}"
                if params:
                    line += f" params={params}"
                if techs:
                    line += f" [{techs}]"
                if notes:
                    line += f" - {notes}"
                lines.append(line)
            sections.append("\n".join(lines))

        # SECTION 6: VULNERABILITIES STATUS
        vulns = [f for f in self.facts.values() if f.category == "vulnerability"]
        if vulns:
            lines = ["## VULNERABILITIES"]
            for v in vulns:
                status = "CONFIRMED" if v.confidence >= 0.8 else "SUSPECTED" if v.confidence >= 0.5 else "POSSIBLE"
                lines.append(f"[{status}] {v.key}: {v.value}")
                if v.details:
                    if v.details.get("payload"):
                        lines.append(f"  Payload: {v.details['payload']}")
                    if v.details.get("response_excerpt"):
                        lines.append(f"  Response: {v.details['response_excerpt'][:200]}")
            sections.append("\n".join(lines))

        # SECTION 6.5: AUTHENTICATION STATE (for authenticated testing)
        auth_facts = [f for f in self.facts.values() if f.category in ("authentication", "credential")]
        if auth_facts:
            lines = ["## AUTHENTICATION"]
            for af in auth_facts:
                if af.category == "authentication":
                    lines.append(f"Session: {af.value}")
                    if af.details:
                        if af.details.get("session_cookie"):
                            lines.append(f"  Cookie: {af.details['session_cookie']}")
                        if af.details.get("auth_token"):
                            lines.append(f"  Token: {af.details['auth_token']}")
                        if af.details.get("registered_user"):
                            user = af.details["registered_user"]
                            lines.append(f"  Registered: {user.get('username', 'N/A')}")
                elif af.category == "credential":
                    if af.details:
                        lines.append(f"Credential: {af.details.get('username', 'N/A')} / {af.details.get('password', 'N/A')}")
            sections.append("\n".join(lines))

        # SECTION 7: AGENT INSIGHTS (summarized learnings)
        if self.thoughts:
            high_relevance = [t for t in self.thoughts if t.relevance >= 0.6]
            if high_relevance:
                lines = ["## INSIGHTS"]
                for t in high_relevance[-5:]:
                    summary = t.summary or t.thought[:150]
                    lines.append(f"[{t.agent_name}] {summary}")
                sections.append("\n".join(lines))

        # SECTION 8: NEXT STEPS (from recent executions)
        recent_with_next = [e for e in self.executions[-5:]
                           if hasattr(e, 'parameters') and e.parameters.get('next_steps')]
        if not recent_with_next:
            next_steps_facts = [f for f in self.facts.values()
                               if "next" in f.key.lower() or f.category == "finding"]

        return "\n\n".join(sections)

    def reset(self) -> None:
        """Reset all structured context."""
        self.goal = ""
        self.facts.clear()
        self.attempts.clear()
        self.executions.clear()
        self.thoughts.clear()
        self.failed_approaches.clear()
        self.tested_techniques.clear()
        self.current_task_log = ""
        self.completed_tasks.clear()

class ContextEngine:
    """Context engine for managing workflow state and task coordination.
    
    This class provides context management functionality for security research
    workflows, including task tracking, workflow state management, and agent
    routing based on current context and progress. It also persists context
    to text files for session management and recovery.
    
    Attributes:
        workflow_context (str): The complete context from the start of the workflow.
        tasks (Dict[int, Task]): Dictionary mapping task indices to Task objects.
        next_agent (str): Name of the next agent to be executed.
        target (str): Information about the current target being analyzed.
        assets (Dict[str, str]): Dictionary mapping asset names to their content.
        session_id (uuid.UUID): Unique identifier for this workflow session.
        context_file_path (Path): Path to the text context file for this session.
    """
    workflow_context: str = ""
    # Defines the whole context from the start of the workflow
    tasks: Dict[TaskPlanner, list]
    # Defines the new last tasks set
    next_agent: str
    # Name of the next agent
    target: str
    # Information about the target
    assets: Dict[str, str]
    # Assets information
    session_id: uuid.UUID | None
    # Unique session identifier
    context_file_path: Path
    # Path to the text context file
    model: AIModel
    # Adding AI model for summarization if input tokens too long
    def __init__(self, model: AIModel, session_id: uuid.UUID | None = None) -> None:
        """Initialize the ContextEngine with empty state.

        Args:
            session_id: Optional UUID for the session. If not provided, a new one is generated.

        Sets up the context engine with empty dictionaries for tasks and assets,
        initializes the next_agent to an empty string, and creates the context file path.
        """
        self.session_id = session_id
        self.root_goal = ""
        self.tasks = {}
        self.next_agent = ""
        self.assets = {}
        self.target = ""
        self.workflow_context = ""
        self.final_goal = ""
        self.model = model

        # Initialize structured context for optimized LLM consumption
        self.structured = StructuredContext()

        # Create context directory if it doesn't exist
        context_dir = Path.home() / ".cache" / "deadend" / "sessions" / str(self.session_id)
        context_dir.mkdir(parents=True, exist_ok=True)

        # Set context file path
        self.context_file_path = context_dir / "context.txt"

        # Initialize context file with empty structure
        self._initialize_context_file()

    def set_root_task(self, root: str) -> None:
        """Set the root task or final goal for the workflow.

        Args:
            root: The root task description or final goal string that represents
                 the primary objective of the workflow.

        Sets the final_goal attribute which is used to display the primary
        objective in task summaries and context.
        """
        self.final_goal = root
        # Also update structured context goal
        self.structured.set_goal(root)

    def add_tasks(self, parent_task: TaskPlanner | None,  tasks: List[TaskPlanner]) -> None:
        """Add tasks to the context engine, either as root tasks or nested subtasks.
        
        Args:
            parent_task: Optional parent TaskPlanner. If None, tasks are added
                        as root-level tasks. If provided, tasks are added as
                        nested subtasks under the parent.
            tasks: List of TaskPlanner objects to add to the context engine.
        
        If parent_task is None, each task is added as a root-level task with
        an empty list of children. If parent_task is provided, all tasks are
        added as nested subtasks under the parent, organized in a nested
        dictionary structure.
        """
        if parent_task is None:
            for task in tasks:
                self.tasks[task] = []

        else:
            nested_tasks = {}
            for task in tasks:
                nested_tasks[task] = {}
            self.tasks[parent_task] = nested_tasks

    def get_tasks(self, depth: int = 0, include_goal: bool = False) -> str:
        """Return a concise textual summary of all planner tasks with their status.

        The summary includes all tasks at the requested depth with their actual
        status and recursively nests any available child depths. This string is
        later injected into prompts, so it favors short, high-signal lines.

        Args:
            depth: The depth level for task retrieval (default 0)
            include_goal: If True, includes the primary goal. Set to False when
                         goal is already provided via unified context. Default False.
        """
        tasks_context = ""

        # Only include goal if explicitly requested (avoids stale duplication)
        if include_goal and self.final_goal:
            tasks_context = f"## Primary objective\n{self.final_goal}\n"  # Full goal, no truncation

        if not self.tasks:
            return tasks_context if tasks_context else "## Tasks\nNo tasks defined yet."

        tasks_lines = "\n## All Tasks:\n"

        for idx, (task_planner, children) in enumerate(self.tasks.items(), 1):
            task_desc = task_planner.task.strip()  # Full task, no truncation

            # Status indicator for quick scanning
            status_icon = {
                'pending': '○',
                'in_progress': '◐',
                'completed': '✓',
                'success': '✓',
                'validated': '✓',
                'failed': '✗',
                'failed-validation': '✗',
                'aborted:max_depth': '⊘',
                'failed:max_attempts': '⊘',
            }.get(task_planner.status, '?')

            tasks_lines += f"{idx}. {status_icon} {task_desc}\n"
            tasks_lines += f"   Status: {task_planner.status} | Confidence: {task_planner.confidence_score:.2f}\n"

            # Show subtasks if nested
            if children:
                if isinstance(children, dict) and children:
                    tasks_lines += f"   Subtasks ({len(children)}):\n"
                    for sub_idx, (child_planner, _) in enumerate(children.items(), 1):
                        child_desc = child_planner.task.strip()  # Full task, no truncation
                        child_icon = {
                            'pending': '○',
                            'in_progress': '◐',
                            'completed': '✓',
                            'success': '✓',
                            'validated': '✓',
                            'failed': '✗',
                            'failed-validation': '✗',
                        }.get(child_planner.status, '?')
                        tasks_lines += f"      {sub_idx}. {child_icon} {child_desc} [{child_planner.status}]\n"
                elif isinstance(children, list) and children:
                    tasks_lines += f"   Subtasks ({len(children)}):\n"
                    for sub_idx, child_planner in enumerate(children, 1):
                        child_desc = child_planner.task.strip()  # Full task, no truncation
                        child_icon = {
                            'pending': '○',
                            'in_progress': '◐',
                            'completed': '✓',
                            'success': '✓',
                            'validated': '✓',
                            'failed': '✗',
                            'failed-validation': '✗',
                        }.get(child_planner.status, '?')
                        tasks_lines += f"      {sub_idx}. {child_icon} {child_desc} [{child_planner.status}]\n"
            tasks_lines += "\n"

        tasks_context += tasks_lines
        return tasks_context


    def set_tasks(self, tasks: List[Task]) -> None:
        """Set the current tasks and update workflow context.
        
        Args:
            tasks (List[Task]): List of Task objects to be set as current tasks.
        
        Updates the workflow context with the new tasks and stores them
        in the tasks dictionary with enumerated indices. Also saves to text file.
        """
        self.workflow_context += f"""\n
[planner tasks]
{str(tasks)}
"""
        self.tasks = dict(enumerate(task for task in tasks))
        self._append_to_context_file("[ai agent]", f"Planner agent new tasks:\n{str(tasks)}")

    def set_target(self, target: str) -> None:
        """Set the current target and update workflow context.

        Args:
            target (str): Information about the new target to be analyzed.

        Updates the workflow context with the new target information
        and stores it in the target attribute. Also syncs to structured
        context so all agents receive the target. Also saves to text file.
        """
        self.target = target
        # Sync target to structured context so unified context includes it
        self.structured.set_target(target)
        self._append_to_context_file("[user input]", f"Target: {target}")

    async def get_all_context(self, max_tokens: int = 8000) -> str:
        """Get optimized workflow context for LLM consumption.

        Returns context optimized for LLM usage, combining structured facts
        with relevant workflow history. Respects token budget.

        Args:
            max_tokens: Maximum token budget for the context (default 8000)

        Returns:
            str: Optimized context string containing discovered facts,
                 failed approaches, and relevant execution history.
        """
        # Get structured context (optimized)
        structured_context = self.structured.get_executor_context(max_tokens=max_tokens)

        # If structured context is empty, fall back to workflow_context (backward compat)
        if not structured_context or len(structured_context) < 50:
            # Optionally summarize if context is too large before returning it.
            tokens = await self.maybe_summarize_context()
            if tokens > 10000:
                print(f"[Context] Using workflow_context ({tokens} tokens)")
            return self.workflow_context

        return structured_context

    async def get_full_context(self) -> str:
        """Get the complete raw workflow context (for debugging/logging).

        Returns:
            str: The complete workflow context string without optimization.
        """
        tokens = await self.maybe_summarize_context()
        print(f"[Context] Full context: {tokens} tokens")
        return self.workflow_context

    def get_validation_context(self) -> str:
        """Get minimal context optimized for validation.

        Returns only the most recent execution results needed for validation,
        avoiding token waste on historical data.

        Returns:
            str: Compact context for validator agent.
        """
        return self.structured.get_validation_context()

    def get_planning_context(self) -> str:
        """Get compact context optimized for planning decisions.

        Returns:
            str: Context with completed tasks, facts, and failed approaches.
        """
        return self.structured.get_planning_context()

    def get_unified_context(self, max_tokens: int = 6000) -> str:
        """Get UNIFIED context for ALL agents.

        This is THE SINGLE SOURCE OF TRUTH for context. ALL agents
        (executor, router, validator, planner) should use this method
        to ensure they receive the SAME information.

        The unified context combines:
        - Target (ALWAYS included first)
        - Concise goal statement
        - Confirmed/successful exploits (highest priority)
        - Discovered facts
        - Failed approaches
        - Recent execution log

        Args:
            max_tokens: Maximum token budget

        Returns:
            str: Unified context string
        """
        # Ensure target is synced to structured context before generating unified context
        if self.target and not self.structured.target:
            self.structured.set_target(self.target)
        return self.structured.get_unified_context(max_tokens=max_tokens)

    async def maybe_summarize_context(
        self,
        token_threshold: int = 200_000,
        encoding_name: str = "o200k_base",
    ) -> int:
        """Summarize workflow context with the reporter agent if token count is high.

        This helper estimates the token count of ``workflow_context`` using tiktoken
        with the specified encoding. When the count exceeds ``token_threshold``, it
        creates a ReporterAgent instance and uses it to summarize and overwrite the
        current context.

        Args:
            token_threshold: Maximum allowed token count before summarization is
                triggered. Defaults to 200,000.
            encoding_name: The tiktoken encoding name to use for token counting.
                          Defaults to "o200k_base".

        Returns:
            int: The estimated token count before any summarization took place.
        """
        # Use tiktoken to estimate token count for the current context.
        current_context = self.workflow_context
        token_count = num_tokens_from_string(current_context, encoding_name)

        if token_count > token_threshold:
            # Import here to avoid a hard import cycle at module import time.
            from deadend_agent.agents.reporter import ReporterAgent

            reporter_agent = ReporterAgent(
                model=self.model,
                deps_type=None,
                tools=[],
                validation_format="New context with the relevant information",
                validation_type="Summarize context",
            )
            # ReporterAgent.summarize_context will update workflow_context via
            # ContextEngine.set_new_workflow, so no direct assignment is needed.
            result = await reporter_agent.summarize_context(self)
            self.workflow_context = result.output
        return token_count

    def add_next_agent(self, router_output: "RouterOutput") -> None:
        """Add router output information and set the next agent.
        
        Args:
            router_output (RouterOutput): The output from the router agent
                                         containing the next agent name and
                                         routing information.
        
        Updates the next_agent attribute and adds the router output
        to the workflow context. Also saves to text file.
        """
        self.next_agent = router_output.next_agent_name
        self.workflow_context  += f"""\n
[router agent]
{str(router_output)}
"""
        self._append_to_context_file("[ai agent]", f"Router agent: {str(router_output)}")
    def add_not_found_agent(self, agent_name: str) -> None:
        """Add information about a not found agent to the workflow context.
        
        Args:
            agent_name (str): The name of the agent that was not found.
        
        Adds a message to the workflow context indicating that the
        specified agent was not found. Also saves to text file.
        """
        self.workflow_context += f"""
[agent not found {agent_name}]\n
"""
        self._append_to_context_file("[ai agent]", f"Not found agent name: {agent_name}")
    def add_agent_response(
        self,
        response: str,
        agent_name: str = "",
        skip_structured: bool = False
    ) -> None:
        """Add an agent response to the workflow context.

        Args:
            response: The response from an agent to be added to the workflow context.
            agent_name: Optional name of the agent that generated the response.
                       Defaults to empty string if not provided.
            skip_structured: If True, only adds to workflow_context (avoid double-logging)

        Appends the agent response to the workflow context with
        appropriate formatting. Also saves to text file.
        """
        self.workflow_context += f"\n{response}\n"

        # Update structured context log (unless skipped to avoid duplicates)
        if not skip_structured:
            self.structured.append_to_log(response)

        self._append_to_context_file("[ai agent]", f"Agent response:\n{response}")
    def add_asset_file(self, file_name: str, file_content: str) -> None:
        """Add an asset file to the assets dictionary.
        
        Args:
            file_name (str): The name of the asset file.
            file_content (str): The content of the asset file.
        
        Stores the asset file in the assets dictionary for later
        inclusion in the workflow context. Also saves to text file.
        """
        self.assets[file_name] = file_content
        self._append_to_context_file("[Tool use: file_asset]", f"Added asset file: {file_name}")

    def add_assets_to_context(self) -> None:
        """Add all stored assets to the workflow context.
        
        Iterates through all assets in the assets dictionary and
        adds them to the workflow context with appropriate formatting.
        Each asset is added with a filename header followed by its content.
        Also saves to text file.
        """
        for asset_name, asset_content in self.assets.items():
            self.workflow_context += f"""
[filename {asset_name}]
{asset_content}
"""
            self._append_to_context_file("[Tool use: file_asset]", f"Asset file: {asset_name}\n{asset_content}")

    def _initialize_context_file(self) -> None:
        """Initialize the context file with session information.
        
        Checks if a context file already exists and loads its content into
        workflow_context. If no file exists, creates a new text file with
        session metadata and initial structure.
        
        Raises:
            OSError: If the file cannot be written.
        """
        # Check if context file already exists
        if self.context_file_path.exists():
            # Load existing context into workflow_context
            if self.load_context_from_file():
                return  # Successfully loaded existing context

        # If no existing file or loading failed, create new file
        try:
            with open(self.context_file_path, 'w', encoding='utf-8') as f:
                f.write("\n")

        except OSError as e:
            # Log error but don't raise to avoid breaking workflow
            print(f"Warning: Could not initialize context file: {e}")

    def _append_to_context_file(self, section: str, content: str) -> None:
        """Append content to the context file with proper formatting.
        
        Args:
            section: The section header (e.g., "[user input]", "[ai agent]")
            content: The content to append
        
        Raises:
            OSError: If the file cannot be written.
        """
        try:
            with open(self.context_file_path, 'a', encoding='utf-8') as f:
                f.write(f"{section}\n")
                f.write(f"{content}\n\n")

        except OSError as e:
            # Log error but don't raise to avoid breaking workflow
            print(f"Warning: Could not append to context file: {e}")

    def load_context_from_file(self) -> bool:
        """Load context from the text file.
        
        Returns:
            bool: True if context was successfully loaded, False otherwise.
        
        Raises:
            OSError: If the file cannot be read.
        """
        try:
            if not self.context_file_path.exists():
                return False

            with open(self.context_file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Extract session information from the file
            lines = content.split('\n')
            for line in lines:
                if line.startswith('Target:'):
                    self.target = line.replace('Target:', '').strip()
                elif line.startswith('='):
                    # End of header section
                    break

            # Store the full content as workflow context
            self.workflow_context = content

            return True

        except OSError as e:
            print(f"Warning: Could not load context from file: {e}")
            return False

    def add_tool_response(self, tool_name: str = "", response: str = "") -> None:
        """Add a tool response to the context file.

        Args:
            tool_name (str): The name of the tool that was used.
            response (str): The response from the tool.

        Appends the tool response to the context file with proper formatting.
        """
        self.workflow_context += f"\n[Tool response {tool_name}]\n{response}\n"
        self.structured.append_to_log(f"[{tool_name}] {response}")  # Full response, no truncation
        self._append_to_context_file(f"[Tool use: {tool_name}]", response)

    def record_attempt(
        self,
        task: str,
        payload: str,
        result: str,
        reason: str
    ) -> bool:
        """Record an exploitation attempt to prevent redundant retries.

        Args:
            task: Task description that triggered this attempt
            payload: The payload or action attempted
            result: Outcome (success, failed, blocked, partial)
            reason: Explanation of the result

        Returns:
            False if this exact attempt was already tried and failed.
        """
        return self.structured.record_attempt_simple(task, payload, result, reason)

    def add_discovered_fact(
        self,
        category: str,
        key: str,
        value: str,
        confidence: float = 0.5,
        source_task: str = "",
        details: Dict[str, Any] | None = None,
        actionable: bool = False
    ) -> bool:
        """Add a discovered fact about the target.

        Args:
            category: Type of discovery (endpoint, parameter, auth_method, filter, technology, vulnerability)
            key: Unique identifier (e.g., "/page", "name")
            value: Description of the discovery
            confidence: Confidence score (0.0-1.0)
            source_task: Task that discovered this fact
            details: Additional structured details (e.g., {"method": "GET", "filters": ["<"]})
            actionable: Whether this fact suggests a next action the agent should take

        Returns:
            True if fact was added/updated, False if duplicate with lower confidence.

        Example:
            context.add_discovered_fact(
                category="endpoint",
                key="/page",
                value="XSS injection point with input filtering",
                confidence=0.85,
                details={"parameter": "name", "filters": ["<", "/", "XSS"], "bypass": "double-encoding"},
                actionable=True
            )
        """
        return self.structured.add_fact_simple(
            category, key, value, confidence, source_task, details, actionable
        )

    def was_already_attempted(self, payload: str, task: str) -> bool:
        """Check if a similar attempt was already made and failed.

        Args:
            payload: The payload to check
            task: The task context

        Returns:
            True if this payload+task combo was already tried and failed.
        """
        return self.structured.was_already_attempted(payload, task)

    def mark_task_completed(self, task: str, confidence_score: float = 1.0) -> None:
        """Mark a task as completed in structured context and update task status.

        Args:
            task: The task description to mark as completed
            confidence_score: The confidence score for the completed task
        """
        self.structured.mark_task_completed(task)

        # Also update the task status in the tasks dictionary
        # TaskPlanner is frozen, so we need to replace the key with a new instance
        for task_planner in list(self.tasks.keys()):
            if task_planner.task == task or task in task_planner.task:
                # Get the subtasks for this task
                subtasks = self.tasks.pop(task_planner)
                # Create a new TaskPlanner with updated status
                updated_planner = TaskPlanner(
                    task=task_planner.task,
                    confidence_score=confidence_score,
                    status="completed"
                )
                self.tasks[updated_planner] = subtasks
                break

    def update_task_status(
        self,
        task: str,
        status: str,
        confidence_score: float | None = None
    ) -> bool:
        """Update a task's status in the tasks dictionary.

        Args:
            task: The task description to update
            status: The new status (pending, in_progress, completed, failed, etc.)
            confidence_score: Optional confidence score to update

        Returns:
            True if task was found and updated, False otherwise.
        """
        # TaskPlanner is frozen, so we need to replace the key with a new instance
        for task_planner in list(self.tasks.keys()):
            if task_planner.task == task or task in task_planner.task:
                # Get the subtasks for this task
                subtasks = self.tasks.pop(task_planner)
                # Create a new TaskPlanner with updated status
                updated_planner = TaskPlanner(
                    task=task_planner.task,
                    confidence_score=confidence_score if confidence_score is not None else task_planner.confidence_score,
                    status=status
                )
                self.tasks[updated_planner] = subtasks
                return True
        return False

    def clear_current_task_log(self) -> None:
        """Clear the current task log (call when starting a new task)."""
        self.structured.clear_current_log()

    def add_execution(
        self,
        action: str,
        target_endpoint: str,
        technique: str,
        result_status: str,
        key_finding: str = "",
        parameters: Dict[str, Any] | None = None,
        response_summary: str = "",
        agent_name: str = ""
    ) -> bool:
        """Record a structured execution for clear history tracking.

        This is the preferred way to record what was tested, as it creates
        clear (endpoint, technique) pairs that subsequent agents can understand.

        Args:
            action: What action was taken (e.g., "HTTP Request", "Script Execution")
            target_endpoint: The specific endpoint/resource targeted
            technique: The technique/approach used (e.g., "XSS injection", "SQLi UNION")
            result_status: Clear status (success, failed, blocked, partial, error)
            key_finding: The most important finding from this execution
            parameters: Key parameters used in the attempt
            response_summary: Brief summary of the response received
            agent_name: Which agent performed this action

        Returns:
            False if this technique was already tested on this endpoint.

        Example:
            context.add_execution(
                action="HTTP POST",
                target_endpoint="/login",
                technique="SQL injection UNION",
                result_status="blocked",
                key_finding="WAF detected and blocked the request",
                parameters={"username": "admin' UNION SELECT--"},
                agent_name="requester"
            )
        """
        return self.structured.add_execution_simple(
            action=action,
            target_endpoint=target_endpoint,
            technique=technique,
            result_status=result_status,
            key_finding=key_finding,
            parameters=parameters,
            response_summary=response_summary,
            agent_name=agent_name
        )

    def add_thought(
        self,
        agent_name: str,
        thought: str,
        summary: str = "",
        relevance: float = 0.5
    ) -> None:
        """Record an agent's reasoning/insight for context.

        Thoughts with higher relevance (>= 0.6) are shown to subsequent agents.

        Args:
            agent_name: Which agent produced this thought
            thought: The raw thought/reasoning text
            summary: A concise summary of the key insight (auto-generated if empty)
            relevance: How relevant this is for future actions (0.0-1.0)

        Example:
            context.add_thought(
                agent_name="shell",
                thought="The application uses Jinja2 templates based on the error message format.",
                summary="Application uses Jinja2 templates",
                relevance=0.8
            )
        """
        self.structured.add_thought_simple(agent_name, thought, summary, relevance)

    def was_technique_tested(self, endpoint: str, technique: str) -> bool:
        """Check if a specific technique was already tested on an endpoint.

        Args:
            endpoint: The endpoint to check
            technique: The technique to check

        Returns:
            True if this combination was already tested.
        """
        return self.structured.was_technique_tested(endpoint, technique)

    def get_tested_techniques(self, endpoint: str) -> List[str]:
        """Get all techniques that were tested on a specific endpoint.

        Args:
            endpoint: The endpoint to query

        Returns:
            List of technique names that were tested on this endpoint.
        """
        return self.structured.get_tested_techniques_for_endpoint(endpoint)

    def set_new_workflow(self, new_context: str) -> None:
        """Set a new workflow with the provided context string.
        
        Args:
            new_context (str): The new context string for the workflow.
        
        Replaces the current workflow context with the new context string.
        """
        self.workflow_context = new_context

    def get_context_file_path(self) -> Path:
        """Get the path to the context file.
        
        Returns:
            Path: The path to the text context file for this session.
        """
        return self.context_file_path

    def reset(self, clear_file: bool = False, preserve_target: bool = True) -> None:
        """Reset the context engine to its initial empty state.

        Args:
            clear_file: If True, also clears the context file. If False (default),
                       only resets in-memory state, preserving the file.
            preserve_target: If True (default), preserves the target across reset.
                            The target should persist throughout the session.

        Resets all workflow state including:
        - workflow_context: Cleared to empty string
        - tasks: Cleared to empty dictionary
        - next_agent: Cleared to empty string
        - target: Preserved by default (cleared only if preserve_target=False)
        - assets: Cleared to empty dictionary
        - root_goal: Cleared to empty string
        - final_goal: Cleared to empty string
        - structured: Reset structured context (preserves target)
        """
        # Preserve target before reset if requested
        saved_target = self.target if preserve_target else ""

        self.workflow_context = ""
        self.tasks = {}
        self.next_agent = ""
        self.assets = {}
        self.root_goal = ""
        self.final_goal = ""

        # Reset structured context
        self.structured.reset()

        # Restore target (persists across phases)
        if preserve_target and saved_target:
            self.target = saved_target
            self.structured.set_target(saved_target)
        else:
            self.target = ""

        if clear_file:
            # Clear the context file
            try:
                with open(self.context_file_path, 'w', encoding='utf-8') as f:
                    f.write("\n")
            except OSError as e:
                print(f"Warning: Could not clear context file: {e}")

    def _read_last_lines_from_jsonl(self, file_path: Path, num_lines: int = 200) -> List[dict]:
        """Read the last N lines from a JSONL file.
        
        Handles both single-line and pretty-printed (multi-line) JSON entries.
        
        Args:
            file_path: Path to the JSONL file
            num_lines: Number of lines to read from the end (default: 200)
            
        Returns:
            List[dict]: List of parsed JSON objects from the last N lines
        """
        if not file_path.exists():
            return []

        try:
            # Read all lines
            with open(file_path, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()

            # Read more lines than requested to ensure we get complete entries
            # (pretty-printed JSON may span multiple lines)
            # Then we'll take the last N complete entries
            lines_to_read = min(num_lines * 2, len(all_lines))
            last_lines = all_lines[-lines_to_read:] if len(all_lines) > lines_to_read else all_lines

            # Parse JSON entries (handling both single-line and multi-line pretty-printed JSON)
            parsed_entries = []
            current_entry = []
            brace_count = 0

            for line in last_lines:
                stripped = line.strip()
                if not stripped:
                    continue
                
                # Count braces to detect complete JSON objects
                brace_count += stripped.count('{') - stripped.count('}')
                current_entry.append(stripped)
                
                # When braces are balanced, we have a complete JSON object
                if brace_count == 0 and current_entry:
                    try:
                        entry_text = '\n'.join(current_entry)
                        parsed = json.loads(entry_text)
                        parsed_entries.append(parsed)
                    except json.JSONDecodeError as e:
                        # If parsing fails, try to extract just the content part
                        # This handles cases where pretty-printed JSON might have extra whitespace
                        try:
                            # Try to find the JSON object boundaries
                            entry_text = '\n'.join(current_entry)
                            # Remove any leading/trailing whitespace and try again
                            entry_text = entry_text.strip()
                            parsed = json.loads(entry_text)
                            parsed_entries.append(parsed)
                        except json.JSONDecodeError:
                            # Skip this entry if we can't parse it
                            print(e)
                    current_entry = []
                    brace_count = 0

            # Handle any remaining entry (incomplete at end of file)
            if current_entry and brace_count == 0:
                try:
                    entry_text = '\n'.join(current_entry)
                    parsed = json.loads(entry_text)
                    parsed_entries.append(parsed)
                except json.JSONDecodeError:
                    pass

            # Return the last N entries (or all if we have fewer)
            return parsed_entries[-num_lines:] if len(parsed_entries) > num_lines else parsed_entries

        except Exception as e:
            print(f"Warning: Could not read JSONL file {file_path}: {e}")
            return []

    def _get_session_directory(self, session_key: str | None = None) -> Path | None:
        """Determine the session directory path.
        
        Args:
            session_key: Optional session key (e.g., "host_port"). If not provided,
                        will try to extract from target or use session_id.
        
        Returns:
            Path to the session directory, or None if it cannot be determined.
        """
        if session_key:
            return Path.home() / ".cache" / "deadend" / "memory" / "sessions" / session_key
        elif self.target:
            # Try to extract host and port from target
            try:
                from deadend_agent.tools.browser_automation.http_parser import extract_host_port
                host, port = extract_host_port(target_host=self.target)
                session_key = f"{host}_{port}"
                return Path.home() / ".cache" / "deadend" / "memory" / "sessions" / session_key
            except Exception:
                # Fallback to using session_id if target parsing fails
                if self.session_id:
                    return Path.home() / ".cache" / "deadend" / "memory" / "sessions" / str(self.session_id)
                else:
                    return None
        elif self.session_id:
            return Path.home() / ".cache" / "deadend" / "memory" / "sessions" / str(self.session_id)
        else:
            return None

