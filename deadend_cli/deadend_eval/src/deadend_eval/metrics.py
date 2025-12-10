from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
from time import perf_counter
from typing import Any, Awaitable, Callable, TypeVar, TYPE_CHECKING

from pydantic_ai.usage import RunUsage

if TYPE_CHECKING:
    from deadend_agent.agents.factory import AgentRunner


@dataclass
class DeadendMetricEval:
    """Accumulates usage metrics across multiple agent runs."""

    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    time: float = 0.0

    def reset(self) -> None:
        """Reset all counters to zero."""
        self.tool_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost = 0.0
        self.time = 0.0

    def add_usage(self, usage: RunUsage | None, elapsed: float) -> None:
        """Accumulate metrics from a single RunUsage instance."""

        # Always track wall-clock time.
        self.time += float(elapsed or 0.0)
        if usage is None:
            return

        # Tool calls (best-effort across possible shapes)
        tool_calls = 0
        if hasattr(usage, "tool_calls"):
            value = getattr(usage, "tool_calls")
            if isinstance(value, int):
                tool_calls = value
            elif isinstance(value, list):
                tool_calls = len(value)
        self.tool_calls += tool_calls

        # Input tokens
        for attr in ("input_tokens", "prompt_tokens", "total_input_tokens"):
            if hasattr(usage, attr):
                self.input_tokens += int(getattr(usage, attr) or 0)
                break

        # Output tokens
        for attr in ("output_tokens", "completion_tokens", "total_output_tokens"):
            if hasattr(usage, attr):
                self.output_tokens += int(getattr(usage, attr) or 0)
                break

        # Cost
        for attr in ("cost", "total_cost"):
            if hasattr(usage, attr):
                self.cost += float(getattr(usage, attr) or 0.0)
                break


# Global accumulator used by default.
global_metrics = DeadendMetricEval()

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def usage_tracking_decorator(
    metrics: DeadendMetricEval | None = None,
) -> Callable[[F], F]:
    """Return a decorator that tracks usage on async AgentRunner.run-style methods."""

    metrics = metrics or global_metrics

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = perf_counter()
            result = await func(*args, **kwargs)
            elapsed = perf_counter() - start

            # Handle usage as either a property or method
            # pydantic_ai's AgentRunResult.usage can be a method or property
            usage = None
            if hasattr(result, "usage"):
                usage_attr = getattr(result, "usage", None)
                # If it's callable (a method), call it; otherwise use it directly (property)
                if callable(usage_attr) and not isinstance(usage_attr, type):
                    # It's a method, call it to get the actual RunUsage object
                    try:
                        usage = usage_attr()
                    except (AttributeError, TypeError, ValueError):
                        # If calling fails, usage remains None
                        usage = None
                else:
                    # It's a property or attribute, use directly
                    usage = usage_attr
            
            metrics.add_usage(usage, elapsed)
            print(_format_metrics_snapshot(metrics, elapsed, usage))
            return result

        # type: ignore[return-value]
        return wrapper  # type: ignore[misc]

    return decorator


def _wrap_run(cls: type, metrics: DeadendMetricEval) -> None:
    """Apply the usage decorator to cls.run if defined directly on that class."""
    func = cls.__dict__.get("run")
    if func is None or getattr(func, "_deadend_instrumented", False):
        return

    decorated = usage_tracking_decorator(metrics)(func)
    setattr(decorated, "_deadend_instrumented", True)
    setattr(cls, "run", decorated)


def _wrap_hierarchy(root: type, metrics: DeadendMetricEval) -> None:
    """Wrap root and all known subclasses."""
    queue = [root]
    while queue:
        cls = queue.pop()
        _wrap_run(cls, metrics)
        queue.extend(cls.__subclasses__())


def instrument_agent_runner(
    metrics: DeadendMetricEval | None = None,
    runner_cls: type["AgentRunner"] | None = None,
) -> type["AgentRunner"] | None:
    """Ensure AgentRunner.run (and every subclass run) emits metrics.

    Args:
        metrics: Metrics accumulator to use (defaults to global_metrics).
        runner_cls: Optional specific AgentRunner subclass to instrument. If omitted,
            instruments the base AgentRunner and all current/future subclasses.

    Returns:
        The runner_cls that was instrumented (if provided), otherwise None.
    """
    from deadend_agent.agents.factory import AgentRunner

    metrics = metrics or global_metrics
    target_cls: type["AgentRunner"] = runner_cls or AgentRunner

    _wrap_hierarchy(target_cls, metrics)

    if runner_cls is not None:
        return runner_cls

    if getattr(AgentRunner, "_deadend_original_init_subclass", None):
        return None

    original_init_subclass = AgentRunner.__init_subclass__

    def _instrumenting_init_subclass(cls, *args, **kwargs):
        if original_init_subclass:
            original_init_subclass(*args, **kwargs)
        _wrap_run(cls, metrics)

    setattr(AgentRunner, "_deadend_original_init_subclass", original_init_subclass)
    AgentRunner.__init_subclass__ = classmethod(_instrumenting_init_subclass)
    return None


def _format_metrics_snapshot(
    metrics: DeadendMetricEval,
    elapsed: float,
    usage: RunUsage | None,
) -> str:
    """Render a concise line summarizing the latest run + totals."""
    usage_bits: list[str] = []
    if usage:
        for attr in ("tool_calls", "input_tokens", "output_tokens", "cost"):
            if hasattr(usage, attr):
                usage_bits.append(f"{attr}={getattr(usage, attr)}")
        if not usage_bits:
            usage_bits.append(f"usage={usage}")

    usage_summary = ", ".join(usage_bits) if usage_bits else "usage=unknown"
    return (
        "[DeadendMetrics] "
        f"elapsed={elapsed:.3f}s | {usage_summary} | "
        f"totals -> tool_calls={metrics.tool_calls}, "
        f"input_tokens={metrics.input_tokens}, "
        f"output_tokens={metrics.output_tokens}, "
        f"cost=${metrics.cost:.6f}, "
        f"time={metrics.time:.3f}s"
    )


def metrics_to_markdown(
    metrics: DeadendMetricEval,
    eval_metadata: dict[str, Any] | None = None,
) -> str:
    """Render the metrics (and optional evaluation metadata) as markdown."""

    sections: list[str] = ["# Deadend Evaluation Report"]

    if eval_metadata:
        name = eval_metadata.get("name", "Unnamed Challenge")
        difficulty = eval_metadata.get("difficulty", "N/A")
        categories = ", ".join(eval_metadata.get("categories", [])) or "N/A"
        target_host = eval_metadata.get("target_host", "N/A")
        validation_type = eval_metadata.get("validation_type", "N/A")

        sections.extend(
            [
                "",
                "## Challenge",
                f"- **Name:** {name}",
                f"- **Difficulty:** {difficulty}",
                f"- **Categories:** {categories}",
                f"- **Target Host:** {target_host}",
                f"- **Validation:** {validation_type}",
            ]
        )

    sections.extend(
        [
            "",
            "## Usage Summary",
            "",
            "| Metric | Value |",
            "| --- | --- |",
            f"| Tool calls | {metrics.tool_calls} |",
            f"| Input tokens | {metrics.input_tokens} |",
            f"| Output tokens | {metrics.output_tokens} |",
            f"| Cost (USD) | ${metrics.cost:.6f} |",
            f"| Time (s) | {metrics.time:.3f} |",
        ]
    )

    return "\n".join(sections)
