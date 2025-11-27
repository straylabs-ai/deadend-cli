from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Awaitable, Callable, TypeVar

from pydantic_ai.usage import RunUsage


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
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = perf_counter()
            result = await func(*args, **kwargs)
            elapsed = perf_counter() - start

            usage = getattr(result, "usage", None)
            metrics.add_usage(usage, elapsed)
            return result

        # type: ignore[return-value]
        return wrapper  # type: ignore[misc]

    return decorator


def _wrap_run(cls, metrics: DeadendMetricEval) -> None:
    """Apply the usage decorator to cls.run if it is defined on that class."""
    func = cls.__dict__.get("run")
    if func is None or getattr(func, "_deadend_instrumented", False):
        return
    decorated = usage_tracking_decorator(metrics)(func)
    setattr(decorated, "_deadend_instrumented", True)
    setattr(cls, "run", decorated)


def instrument_agent_runner(metrics: DeadendMetricEval | None = None) -> None:
    """Ensure AgentRunner.run (and overriding subclasses) emit metrics."""
    from deadend_agent.agents.factory import AgentRunner

    metrics = metrics or global_metrics

    _wrap_run(AgentRunner, metrics)
    for subclass in AgentRunner.__subclasses__():
        _wrap_run(subclass, metrics)


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
