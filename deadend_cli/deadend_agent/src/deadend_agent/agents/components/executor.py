from dataclasses import dataclass
import json
from typing import Any, Literal, AsyncGenerator
import asyncio
from pydantic import BaseModel
from pydantic_ai import DeferredToolResults, RunContext, UsageLimits, RunUsage, UsageLimitExceeded
from deadend_agent.agents import (
    SupervisorAgent, SupervisorOutput,
    RequesterAgent,
    ShellAgent,
    PythonInterpreterAgent, AgentOutput,
    WebAppAnalyzerAgent,
    MemoryAgent,
    AuthenticatorAgent,
)
from deadend_agent.auth_resolver import AuthContextHandler
from deadend_agent.agents.components.planner import TaskNode
from deadend_agent.agents.components.validation_strategies import ValidationGate, ValidationInput
from deadend_agent.agents.reporter import ReporterAgent
from deadend_agent.context import ContextEngine
from deadend_agent.config.settings import ModelSpec
from deadend_agent.tools.avfs.write import write_text
from deadend_agent.utils.structures import MemoryWorkspaceDeps, WebappreconDeps, RequesterDeps, ShellDeps


class LogEvent(BaseModel):
    """Event representing a log message during execution."""
    type: Literal["log"] = "log"
    message: str


class ResultEvent(BaseModel):
    """Event representing the final execution result."""
    type: Literal["result"] = "result"
    confidence_score: float
    context: dict[str, Any]


class ValidationStopEvent(BaseModel):
    """Event emitted when validation confirms the root objective is solved."""

    type: Literal["validation_stop"] = "validation_stop"
    validation_token: str = ""
    confidence_score: float
    critique: str = ""
    reporter_output: str = ""

# Union type for all possible executor events
ExecutorEvent = LogEvent | ResultEvent | ValidationStopEvent


def _memory_prompt_prefix(memory_context: str) -> str:
    """Render persistent memory context as a prompt prefix for downstream agents."""
    if not memory_context.strip():
        return ""
    return f"## Persistent Memory Context\n{memory_context.strip()}\n\n"


def _build_memory_summary(agent_name: str, task: str, output: AgentOutput) -> str:
    """Create a deterministic memory entry from structured agent output."""
    summary = output.detailed_summary.strip() or "None"
    proofs = output.proofs.strip() or "None"
    thoughts = output.thoughts.strip() or "None"
    return (
        "## Task Summary\n"
        f"- Agent: {agent_name}\n"
        f"- Task: {task.strip()}\n"
        f"- Confidence: {output.confidence_score:.2f}\n"
        f"- Summary: {summary}\n"
        f"- Proofs: {proofs}\n"
        f"- Thoughts: {thoughts}\n\n"
    )


def _format_tool_result_for_supervisor(agent_name: str, output: Any) -> str:
    """Render tool/agent output in a stable format that preserves key details for downstream reasoning."""
    if isinstance(output, AgentOutput):
        return (
            f"{agent_name} agent result\n"
            f"confidence_score: {output.confidence_score:.2f}\n"
            f"detailed_summary:\n{output.detailed_summary or 'None'}\n\n"
            f"proofs:\n{output.proofs or 'None'}\n\n"
            f"thoughts:\n{output.thoughts or 'None'}"
        )

    if isinstance(output, BaseModel):
        return (
            f"{agent_name} agent result\n"
            f"{json.dumps(output.model_dump(), indent=2, ensure_ascii=False)}"
        )

    return f"{agent_name} agent result\n{str(output)}"

@dataclass
class SupervisorDeps:
    """Dependencies for supervisor router containing all agents and their deps."""
    requester_agent: RequesterAgent | None
    requester_deps: RequesterDeps | None
    shell_agent: ShellAgent | None
    shell_deps: ShellDeps | None
    python_interpreter_agent: PythonInterpreterAgent
    webapp_analyzer_agent: WebAppAnalyzerAgent
    memory_agent: MemoryAgent
    memory_deps: MemoryWorkspaceDeps
    session_id: str
    message_history: list | None
    usage_limits: UsageLimits
    deferred_tool_results: DeferredToolResults | None
    authenticator_agent: AuthenticatorAgent | None = None
    memory_context: str = ""
    auth_session_key: str = ""
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
        model: ModelSpec,
        available_agents: dict[str, str] | None = None,
        agent_factory: Any | None = None,
        requires_approval: bool = False,
        session_id: str | None = None,
        validation_gate: ValidationGate | None = None,
        reporter: ReporterAgent | None = None,
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
        self.validation_gate = validation_gate
        self.reporter = reporter
        self.memory_context = ""
        self.auth_session_key = ""

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

    def set_memory_context(self, memory_context: str) -> None:
        """Register startup memory context for downstream agents."""
        self.memory_context = memory_context

    def set_auth_session_key(self, auth_session_key: str) -> None:
        """Register the auth storage session key used by the python interpreter agent."""
        self.auth_session_key = auth_session_key

    def _build_validation_input(
        self,
        confidence_score: float,
        result_context: dict[str, Any],
    ) -> ValidationInput:
        """Convert the latest supervisor result into structured validation input."""
        return ValidationInput(
            task_achieved=result_context.get("task_achieved", False),
            detailed_summary=result_context.get("detailed_summary", ""),
            proofs=result_context.get("proofs", ""),
            confidence_score=confidence_score,
            latest_response=str(result_context.get("supervisor_response", result_context.get("last_output", ""))),
            subagent_log=result_context.get("log", ""),
            supervisor_history=result_context.get("supervisor_history", ""),
        )

    def _build_validation_context(
        self,
        validation_input: ValidationInput,
        max_tokens: int,
    ) -> str:
        """Build a reporter/validator context that preserves the latest iteration details."""
        unified_context = self.context.get_unified_context(max_tokens=max_tokens)
        sections = [unified_context]

        latest_supervisor_response = validation_input.latest_response.strip()
        if latest_supervisor_response:
            sections.append(
                "## Latest Supervisor Response\n"
                f"{latest_supervisor_response}"
            )

        latest_subagent_log = validation_input.subagent_log.strip()
        if latest_subagent_log:
            sections.append(
                "## Latest Subagent Execution Log\n"
                f"{latest_subagent_log}"
            )

        supervisor_history = validation_input.supervisor_history.strip()
        if supervisor_history:
            sections.append(
                "## Supervisor Input Context\n"
                f"{supervisor_history}"
            )

        return "\n\n".join(section for section in sections if section.strip())

    def _record_supervisor_result_for_validation_stop(
        self,
        task: str,
        validation_input: ValidationInput,
    ) -> None:
        """Persist the latest supervisor synthesis before a validation-triggered exit."""
        if validation_input.detailed_summary:
            self.context.add_agent_response(
                f"[Supervisor] {validation_input.detailed_summary}",
                skip_structured=False,
            )

        if validation_input.proofs:
            self.context.add_discovered_fact(
                source_task=task,
                category="proof",
                key=f"proof_{task[:30]}",
                value=validation_input.proofs,
                confidence=validation_input.confidence_score,
                actionable=not validation_input.task_achieved,
            )

        status_str = "ACHIEVED" if validation_input.task_achieved else "IN PROGRESS"
        self.context.structured.append_to_log(
            f"[Supervisor] Task: {status_str} | Confidence: {validation_input.confidence_score:.2f}"
        )

    async def _run_validation_and_report(
        self,
        validation_input: ValidationInput,
        validation_context: str,
        report_context: str,
    ) -> ValidationStopEvent | None:
        """Validate the root goal and write the success report when solved.

        Validation is executed at the executor boundary so every supervisor
        result is checked consistently, regardless of whether the caller is the
        ADaPT planner or a direct top-level workflow entrypoint.
        """
        if self.validation_gate is None or self.reporter is None:
            return None
        if not self.context.final_goal:
            return None

        verdict = await self.validation_gate.check(
            output=validation_input,
            root_goal=self.context.final_goal,
            context=validation_context,
        )
        if not verdict.stop:
            return None

        reporter_output = await self.reporter.summarize_and_write(
            root_goal=self.context.final_goal,
            verdict=verdict,
            context=report_context,
            session_id=str(self.session_id),
        )
        return ValidationStopEvent(
            validation_token=verdict.token,
            confidence_score=verdict.confidence,
            critique=verdict.critique,
            reporter_output=reporter_output,
        )

    async def _refresh_memory_context_for_task(self, task_query: str) -> str:
        """Retrieve task-specific memory immediately before supervisor execution."""
        memory_workspace_root = (
            self.requester_deps.memory_workspace_root
            if self.requester_deps is not None
            else (self.shell_deps.memory_workspace_root if self.shell_deps is not None else None)
        )
        if memory_workspace_root is None or self.session_id is None:
            self.memory_context = ""
            return self.memory_context

        memory_agent = MemoryAgent(
            model=self.model,
            deps_type=MemoryWorkspaceDeps,
        )
        memory_deps = MemoryWorkspaceDeps(
            session_id=self.session_id,
            memory_workspace_root=memory_workspace_root,
        )
        result = await memory_agent.run(
            prompt=(
                f"Current task:\n{task_query}\n\n"
                "Inspect the persistent memory workspace using AVFS tools with workspace=\"memory\". "
                "Return only a concise task-relevant memory summary as plain text for the supervisor. "
                "If memory is empty or not useful for this task, return a short plain-text statement saying that no relevant persisted memory is available."
            ),
            deps=memory_deps,
            message_history=[],
            usage=RunUsage(),
            usage_limits=UsageLimits(request_limit=None, tool_calls_limit=None),
            deferred_tool_results=None,
        )

        output = getattr(result, "output", None)
        self.memory_context = str(output).strip() if output is not None else ""
        if self.shell_deps is not None:
            self.shell_deps.memory_context = self.memory_context
        if self.requester_deps is not None:
            self.requester_deps.memory_context = self.memory_context
        if self.webapprecon_deps is not None:
            self.webapprecon_deps.memory_context = self.memory_context
        return self.memory_context

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
            The final event is either a ResultEvent for continued execution or
            a ValidationStopEvent when the root task has been solved.
        """

        context: dict[str, Any] = {"log": ""}
        confidence_score: float | None = None

        def emit(message: str) -> LogEvent:
            """Append a log entry to the context and return it for streaming."""
            context["log"] += f"\n{message}"
            return LogEvent(message=message)

        try:
            # await self._refresh_memory_context_for_task(task_node.task)
            yield emit(f"Current task: {task_node.task}\n")
            # Instantiate all generic agents
            requester_agent = RequesterAgent(
                model=self.model,
                deps_type=RequesterDeps,
                target_information=self.context.target,
                requires_approval=self.requires_approval
            ) if self.requester_deps is not None else None

            authenticator_agent = AuthenticatorAgent(
                model=self.model,
                deps_type=RequesterDeps,
                target_information=self.context.target,
                requires_approval=self.requires_approval,
            ) if self.requester_deps is not None else None

            shell_agent = ShellAgent(
                model=self.model,
                deps_type=WebappreconDeps,
                target_information=self.context.target,
                requires_approval=self.requires_approval,
            ) if self.shell_deps is not None else None

            python_interpreter_agent = PythonInterpreterAgent(
                model=self.model,
                deps_type=MemoryWorkspaceDeps,
            )

            webapp_analyzer_agent = WebAppAnalyzerAgent(
                model=self.model,
                deps_type=RequesterDeps,

            )
            memory_deps = MemoryWorkspaceDeps(
                session_id=self.session_id or "",
                memory_workspace_root=(
                    self.requester_deps.memory_workspace_root
                    if self.requester_deps is not None
                    else (self.shell_deps.memory_workspace_root if self.shell_deps is not None else None)
                ),
                memory_context=self.memory_context,
            )
            memory_agent = MemoryAgent(
                model=self.model,
                deps_type=MemoryWorkspaceDeps,
            )

            # Create supervisor dependencies
            supervisor_deps = SupervisorDeps(
                requester_agent=requester_agent,
                requester_deps=self.requester_deps,
                shell_agent=shell_agent,
                shell_deps=self.shell_deps,
                python_interpreter_agent=python_interpreter_agent,
                webapp_analyzer_agent=webapp_analyzer_agent,
                memory_agent=memory_agent,
                memory_deps=memory_deps,
                session_id=self.session_id or "",
                message_history=message_history,
                usage_limits=usage_limits,
                deferred_tool_results=deferred_tool_results,
                authenticator_agent=authenticator_agent,
                memory_context=self.memory_context,
                auth_session_key=self.auth_session_key,
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
                task: str,
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
                        source_task=task,
                        category="agent_result",
                        key=f"{agent_name}_summary",
                        value=detailed_summary,
                        confidence=confidence_score,
                        actionable=True
                    )

                # Add proofs as discovered fact - FULL content
                if proofs:
                    context.add_discovered_fact(
                        source_task=task,
                        category="agent_proofs",
                        key=f"{agent_name}_proofs",
                        value=proofs,
                        confidence=confidence_score,
                        actionable=True
                    )

                # Add thoughts - FULL content (summary auto-generated if empty)
                if thoughts:
                    context.add_thought(
                        agent_name=agent_name,
                        thought=thoughts,
                        summary="",  # Let context auto-generate summary
                    )

                # Log the full agent response - NO TRUNCATION
                full_response = f"[{agent_name}]\nSummary: {detailed_summary}\nProofs: {proofs}\nThoughts: {thoughts}"
                context.add_agent_response(
                    full_response,
                    agent_name=agent_name,
                    skip_structured=False
                )

            def _persist_agent_summary(agent_name: str, task: str, output: AgentOutput) -> None:
                """Persist a deterministic summary into the memory workspace."""
                write_text(
                    f"summaries/{agent_name}.md",
                    _build_memory_summary(agent_name, task, output),
                    session_id=self.session_id,
                    workspace="memory",
                    append=True,
                )

            def _register_auth_facts_in_context(
                task: str,
                context: ContextEngine | None,
                requester_deps: RequesterDeps | None,
            ) -> None:
                """After the AuthenticatorAgent runs, surface saved auth profiles as
                structured ``authentication`` facts in the shared context so other
                agents can reason about which ``auth_profile`` they may use.

                Only secret-free metadata is registered (cookie *names*, storage
                *key names*, header *names*, profile, target slug).
                """
                if context is None or requester_deps is None:
                    return
                target = getattr(requester_deps, "target", None)
                agent_id = getattr(requester_deps, "agent_id", None)
                session_id = getattr(requester_deps, "session_id", None)
                if not target or agent_id is None or session_id is None:
                    return
                try:
                    handler = AuthContextHandler(
                        target=target,
                        agent_id=agent_id,
                        session_id=session_id,
                    )
                    summaries = handler.list_context_summaries()
                except Exception:
                    return
                for profile, summary in summaries.items():
                    if not summary.get("available"):
                        continue
                    target_slug = summary.get("target_slug", "")
                    context.add_discovered_fact(
                        source_task=task,
                        category="authentication",
                        key=f"auth:{target_slug}:{profile}",
                        value="authenticated session available",
                        confidence=1.0,
                        actionable=True,
                        details={
                            "target": summary.get("target"),
                            "target_slug": target_slug,
                            "agent_id": summary.get("agent_id"),
                            "session_id": summary.get("session_id"),
                            "profile": profile,
                            "auth_flow": summary.get("auth_flow"),
                            "auth_type": summary.get("auth_type"),
                            "final_url": summary.get("final_url"),
                            "cookies_count": summary.get("cookies_count"),
                            "cookie_names": summary.get("cookie_names"),
                            "storage_keys": summary.get("storage_keys"),
                            "headers_available": summary.get("headers_available"),
                        },
                    )

            # Create tool functions using RunContext for agent delegation
            @supervisor.agent.tool
            async def call_authenticator_agent(ctx: RunContext[SupervisorDeps], prompt: str) -> str:
                """Call the authenticator agent to log in and persist a reusable auth context.

                Use this BEFORE running authenticated tests. After it succeeds,
                downstream agents can pass ``auth_profile="<profile>"`` to
                ``browser_run_steps`` / ``pw_send_payload`` to reuse the session.
                """
                if ctx.deps.authenticator_agent is None or ctx.deps.requester_deps is None:
                    return "Authenticator agent dependencies not configured."
                memory_prefix = _memory_prompt_prefix(ctx.deps.memory_context)
                result = await ctx.deps.authenticator_agent.run(
                    f"{memory_prefix}{prompt}",
                    deps=ctx.deps.requester_deps,
                    message_history=ctx.deps.message_history,
                    usage=ctx.usage,
                    usage_limits=ctx.deps.usage_limits,
                    deferred_tool_results=ctx.deps.deferred_tool_results,
                )
                if hasattr(result, "output") and isinstance(result.output, AgentOutput):
                    _add_agent_output_to_context(
                        task=task_node.task,
                        context=ctx.deps.context,
                        agent_name="authenticator",
                        output=result.output,
                    )
                    _persist_agent_summary("authenticator", prompt, result.output)
                    _register_auth_facts_in_context(
                        task=task_node.task,
                        context=ctx.deps.context,
                        requester_deps=ctx.deps.requester_deps,
                    )
                    result_str = _format_tool_result_for_supervisor("authenticator", result.output)
                else:
                    result_output = result.output if hasattr(result, "output") else result
                    result_str = _format_tool_result_for_supervisor("authenticator", result_output)
                emit(f"[authenticator] prompt={prompt[:200]} | result={result_str[:300]}")
                return result_str

            @supervisor.agent.tool
            async def call_requester_agent(ctx: RunContext[SupervisorDeps], prompt: str) -> str:
                """Call the requester agent to perform HTTP request testing."""
                if ctx.deps.requester_agent is None or ctx.deps.requester_deps is None:
                    return "Requester agent dependencies not configured."
                memory_prefix = _memory_prompt_prefix(ctx.deps.memory_context)
                result = await ctx.deps.requester_agent.run(
                    f"{memory_prefix}{prompt}",
                    deps=ctx.deps.requester_deps,
                    message_history=ctx.deps.message_history,
                    usage=ctx.usage,
                    usage_limits=ctx.deps.usage_limits,
                    deferred_tool_results=ctx.deps.deferred_tool_results
                )
                if hasattr(result, 'output') and isinstance(result.output, AgentOutput):
                    _add_agent_output_to_context(
                        task=task_node.task,
                        context=ctx.deps.context,
                        agent_name="requester",
                        output=result.output
                    )
                    _persist_agent_summary("requester", prompt, result.output)
                    result_str = _format_tool_result_for_supervisor("requester", result.output)
                else:
                    result_output = result.output if hasattr(result, "output") else result
                    result_str = _format_tool_result_for_supervisor("requester", result_output)
                emit(f"[requester] prompt={prompt[:200]} | result={result_str[:300]}")
                return result_str

            @supervisor.agent.tool
            async def call_shell_agent(ctx: RunContext[SupervisorDeps], prompt: str) -> str:
                """Call the shell agent to execute shell commands."""
                if ctx.deps.shell_agent is None or ctx.deps.shell_deps is None:
                    return "Shell agent dependencies not configured."
                memory_prefix = _memory_prompt_prefix(ctx.deps.memory_context)
                result = await ctx.deps.shell_agent.run(
                    f"{memory_prefix}{prompt}",
                    deps=ctx.deps.shell_deps,
                    message_history=ctx.deps.message_history,
                    usage=ctx.usage,
                    usage_limits=ctx.deps.usage_limits,
                    deferred_tool_results=ctx.deps.deferred_tool_results
                )
                if hasattr(result, 'output') and isinstance(result.output, AgentOutput):
                    _add_agent_output_to_context(
                        task=task_node.task,
                        context=ctx.deps.context,
                        agent_name="shell",
                        output=result.output
                    )
                    _persist_agent_summary("shell", prompt, result.output)
                    result_str = _format_tool_result_for_supervisor("shell", result.output)
                else:
                    result_output = result.output if hasattr(result, "output") else result
                    result_str = _format_tool_result_for_supervisor("shell", result_output)
                emit(f"[shell] prompt={prompt[:200]} | result={result_str[:300]}")
                return result_str
            
            @supervisor.agent.tool
            async def call_webapp_analyzer_agent(ctx: RunContext[SupervisorDeps], prompt: str) -> str:
                """Call the webapp analyzer agent to analyze web application structure and behavior."""
                memory_prefix = _memory_prompt_prefix(ctx.deps.memory_context)
                result = await ctx.deps.webapp_analyzer_agent.run(
                    f"{memory_prefix}{prompt}",
                    deps=ctx.deps.requester_deps,
                    message_history=ctx.deps.message_history,
                    usage=ctx.usage,
                    usage_limits=ctx.deps.usage_limits,
                    deferred_tool_results=ctx.deps.deferred_tool_results
                )
                result_output = result.output if hasattr(result, "output") else result
                result_str = _format_tool_result_for_supervisor("webapp_analyzer", result_output)
                emit(f"[webapp_analyzer] prompt={prompt[:200]} | result={result_str[:300]}")
                return result_str

            @supervisor.agent.tool
            async def call_python_interpreter_agent(ctx: RunContext[SupervisorDeps], prompt: str) -> str:
                """Call the python interpreter agent to execute Python scripts."""
                memory_prefix = _memory_prompt_prefix(ctx.deps.memory_context)
                result = await ctx.deps.python_interpreter_agent.run(
                    f"{memory_prefix}{prompt}",
                    deps=ctx.deps.memory_deps,
                    session_key=ctx.deps.auth_session_key,
                    message_history=ctx.deps.message_history,
                    usage=ctx.usage,
                    usage_limits=ctx.deps.usage_limits,
                    deferred_tool_results=ctx.deps.deferred_tool_results
                )
                if hasattr(result, 'output') and isinstance(result.output, AgentOutput):
                    _add_agent_output_to_context(
                        task=task_node.task,
                        context=ctx.deps.context,
                        agent_name="python_interpreter",
                        output=result.output
                    )
                    _persist_agent_summary("python_interpreter", prompt, result.output)
                    result_str = _format_tool_result_for_supervisor("python_interpreter", result.output)
                else:
                    result_output = result.output if hasattr(result, "output") else result
                    result_str = _format_tool_result_for_supervisor("python_interpreter", result_output)
                emit(f"[python_interpreter] prompt={prompt[:200]} | result={result_str[:300]}")
                return result_str

            @supervisor.agent.tool
            async def call_memory_agent(ctx: RunContext[SupervisorDeps], prompt: str) -> str:
                """Call the memory agent to inspect or update persistent notes."""
                result = await ctx.deps.memory_agent.run(
                    prompt,
                    deps=ctx.deps.memory_deps,
                    message_history=ctx.deps.message_history,
                    usage=ctx.usage,
                    usage_limits=ctx.deps.usage_limits,
                    deferred_tool_results=ctx.deps.deferred_tool_results,
                )
                if not hasattr(result, "output"):
                    return str(result)
                output = result.output
                if isinstance(output, BaseModel):
                    return str(output.model_dump())
                return str(output)

            # Execute task with supervisor
            supervisor_prompt = f"Your task is : {task_node.task}\n"
            if supervisor_deps.memory_context:
                supervisor_prompt += f"## Persistent Memory Context:\n{supervisor_deps.memory_context}\n"
            if agent_context:
                supervisor_prompt += f"## Traces: \n{agent_context}\n"

            result = await supervisor.run(
                prompt=supervisor_prompt,
                deps=supervisor_deps,
                message_history=message_history,
                usage=usage,
                usage_limits=usage_limits,
                deferred_tool_results=deferred_tool_results
            )

            # Extract SupervisorOutput fields
            supervisor_output = result.output
            context["supervisor_history"] = agent_context
            if isinstance(supervisor_output, SupervisorOutput):
                confidence_score = supervisor_output.confidence_score
                context["task_achieved"] = supervisor_output.task_achieved
                context["detailed_summary"] = supervisor_output.detailed_summary
                context["proofs"] = supervisor_output.proofs
                context["last_output"] = supervisor_output.model_dump()
                context["supervisor_response"] = (
                    "Task achieved: "
                    f"{supervisor_output.task_achieved}\n"
                    f"Confidence: {supervisor_output.confidence_score:.2f}\n"
                    f"Detailed summary:\n{supervisor_output.detailed_summary}\n\n"
                    f"Proofs:\n{supervisor_output.proofs or 'None'}"
                )
            else:
                confidence_score = 0.5
                # Ensure detailed_summary is set even for non-SupervisorOutput results
                output_str = str(supervisor_output)
                context["last_output"] = output_str
                context["detailed_summary"] = output_str
                context["task_achieved"] = False
                context["proofs"] = ""
                context["supervisor_response"] = output_str

            validation_input = self._build_validation_input(
                confidence_score=confidence_score,
                result_context=context,
            )
            validation_context = self._build_validation_context(
                validation_input,
                max_tokens=12_000,
            )
            report_context = self._build_validation_context(
                validation_input,
                max_tokens=100_000,
            )
            validation_event = await self._run_validation_and_report(
                validation_input,
                validation_context,
                report_context,
            )
            if validation_event is not None:
                self._record_supervisor_result_for_validation_stop(
                    task=task_node.task,
                    validation_input=validation_input,
                )
                yield validation_event
                return

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
        except (GeneratorExit, asyncio.CancelledError):
            # These exceptions must not be caught - re-raise to allow proper cleanup
            raise
        except Exception as exc:
            # Store error info in context before yielding
            # This prevents "generator didn't stop after throw()" if the generator
            # is being closed due to the exception
            context["last_output"] = f"detailed_summary=\"Agent error: {exc}. Agent: supervisor\""
            context["detailed_summary"] = f"Agent error: {exc}. Agent: supervisor"
            try:
                yield emit(f"[SUPERVISOR] Error: {exc}")
                yield ResultEvent(
                    confidence_score=confidence_score or 0.5,
                    context=context,
                )
            except GeneratorExit:
                # If generator is being closed, don't try to yield more
                pass
            return
