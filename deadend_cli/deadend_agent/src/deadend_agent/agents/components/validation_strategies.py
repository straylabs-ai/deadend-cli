# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Validation strategies for the ADaPT agent architecture.

This module defines a composable validation system that determines whether
the root goal of a security assessment has been achieved. Strategies are
chained in a ValidationGate — the gate iterates each strategy in order
and short-circuits on the first definitive stop signal.

Configuration is loaded from a YAML file (default:
``~/.cache/deadend/validation.yaml``).  See ``ValidationConfig`` for the
schema and ``load_validation_config`` for the loader.

Adding a new strategy:
    1. Create a class that implements the ValidationStrategy protocol.
    2. Register it in STRATEGY_REGISTRY at the bottom of this file.
    3. Reference it by name in the YAML ``strategies`` list.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol, runtime_checkable

import yaml
from pydantic import BaseModel, Field

from deadend_agent.config.settings import ModelSpec
from deadend_agent.logging import logger
from deadend_prompts import render_agent_instructions


# ---------------------------------------------------------------------------
# Default config path
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_PATH = Path.home() / ".cache" / "deadend" / "validation.yaml"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class ValidationVerdict(BaseModel):
    """Result of a validation strategy check.

    Attributes:
        stop: True if the root goal is satisfied — the agent should exit.
        confidence: How confident the strategy is in this verdict (0.0–1.0).
        token: Captured validation token (flag, proof string, etc.).
        critique: Human-readable explanation of the verdict.
        report: Markdown report content ready to be written to disk.
    """
    stop: bool = False
    confidence: float = 0.0
    token: str = ""
    critique: str = ""
    report: str = ""


# ---------------------------------------------------------------------------
# YAML-driven configuration
# ---------------------------------------------------------------------------

class StrategyConfig(BaseModel):
    """Per-strategy configuration block in the YAML file.

    Example YAML::

        strategies:
          - name: flag
            pattern: "FLAG\\{[^}]+\\}"
          - name: judge
            validation_type: flag
            validation_format: "FLAG{}"
    """
    name: str
    pattern: str | None = None
    validation_type: str | None = None
    validation_format: str | None = None


class ValidationConfig(BaseModel):
    """Top-level validation configuration loaded from YAML.

    Attributes:
        strategies: Ordered list of strategy configs to chain.
        validation_format: Global format string injected into agent prompts.
            Individual strategy-level ``validation_format`` overrides this.
        validation_type: Global type string injected into agent prompts.
    """
    strategies: list[StrategyConfig] = Field(
        default_factory=lambda: [
            StrategyConfig(name="flag"),
            StrategyConfig(name="judge"),
        ]
    )
    validation_format: str | None = None
    validation_type: str | None = None


def load_validation_config(
    path: str | Path | None = None,
) -> ValidationConfig:
    """Load a ``ValidationConfig`` from a YAML file.

    If *path* is ``None``, falls back to ``DEFAULT_CONFIG_PATH``.
    If the file does not exist, returns the default config (flag + judge).

    Args:
        path: Filesystem path to the YAML file.

    Returns:
        A parsed and validated ``ValidationConfig``.
    """
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH

    if not config_path.exists():
        logger.debug(
            "Validation config not found at %s — using defaults.", config_path,
        )
        return ValidationConfig()

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as exc:
        logger.warning(
            "Failed to parse validation config at %s: %s — using defaults.",
            config_path, exc,
        )
        return ValidationConfig()

    if not isinstance(raw, dict):
        logger.warning("Validation config is not a YAML mapping — using defaults.")
        return ValidationConfig()

    return ValidationConfig(**raw)


# ---------------------------------------------------------------------------
# Strategy protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class ValidationStrategy(Protocol):
    """Interface that every validation strategy must implement."""

    async def check(
        self,
        output: dict,
        root_goal: str,
        context: str,
    ) -> ValidationVerdict:
        """Evaluate whether *root_goal* is satisfied.

        Args:
            output: The supervisor output dict (keys: task_achieved,
                    detailed_summary, proofs, confidence_score).
            root_goal: The top-level goal of the entire assessment.
            context: Accumulated execution context (unified context string).

        Returns:
            A ValidationVerdict indicating whether to stop.
        """
        ...


# ---------------------------------------------------------------------------
# FlagStrategy — deterministic regex, zero LLM cost
# ---------------------------------------------------------------------------

class FlagStrategy:
    """Scan supervisor output and context for a flag matching a regex pattern.

    This is a pure string-search strategy — no LLM call, no network call.
    It is always safe to run on every supervisor return.
    """

    def __init__(self, pattern: str = r"FLAG\{[^}]+\}"):
        self.pattern = re.compile(pattern, re.IGNORECASE)

    async def check(
        self,
        output: dict,
        root_goal: str,
        context: str,
    ) -> ValidationVerdict:
        # Search in order: proofs first (most likely), then summary, then full context.
        searchable_fields = [
            output.get("proofs", ""),
            output.get("detailed_summary", ""),
            context,
        ]
        for field in searchable_fields:
            match = self.pattern.search(field)
            if match:
                token = match.group(0)
                logger.debug("FlagStrategy: matched token '%s'", token)
                return ValidationVerdict(
                    stop=True,
                    confidence=1.0,
                    token=token,
                    critique=f"Flag found via pattern match: {token}",
                    report=self._build_report(output, token, root_goal),
                )

        return ValidationVerdict(stop=False, confidence=0.0)

    @staticmethod
    def _build_report(output: dict, token: str, root_goal: str) -> str:
        return (
            "# Validation Report — Flag Captured\n\n"
            f"**Goal:** {root_goal}\n\n"
            f"**Token:** `{token}`\n\n"
            "## Evidence\n\n"
            f"```\n{output.get('proofs', 'N/A')}\n```\n\n"
            "## Summary\n\n"
            f"{output.get('detailed_summary', 'N/A')}\n"
        )


# ---------------------------------------------------------------------------
# JudgeAgentStrategy — LLM agent that can re-verify findings
# ---------------------------------------------------------------------------

class JudgeAgentStrategy:
    """LLM-based judge that evaluates whether the root goal is satisfied.

    Unlike a passive judge, this is backed by an AgentRunner and can be
    extended with tools (requester, shell, memory) to actively re-verify
    findings.  It self-throttles: if no new evidence has appeared since the
    last check it returns a non-stop verdict immediately.
    """

    def __init__(
        self,
        model: ModelSpec,
        validation_type: str | None = None,
        validation_format: str | None = None,
    ):
        from deadend_agent.agents.factory import AgentRunner

        judge_instructions = render_agent_instructions(
            "judge",
            tools={},
            validation_type=validation_type or "flag",
            validation_format=validation_format or "FLAG{{}}",
        )

        self._output_model = _JudgeOutput
        self._agent = AgentRunner(
            name="judge_validator",
            model=model,
            instructions=judge_instructions,
            deps_type=None,
            output_type=_JudgeOutput,
            tools=[],
        )

        # Self-throttle: track context hash to avoid redundant calls.
        self._last_context_hash: int = 0

    async def check(
        self,
        output: dict,
        root_goal: str,
        context: str,
    ) -> ValidationVerdict:
        # Self-throttle: skip if context hasn't changed since last check.
        current_hash = hash(context)
        if current_hash == self._last_context_hash:
            logger.debug("JudgeAgentStrategy: no new evidence, skipping.")
            return ValidationVerdict(stop=False, confidence=0.0)
        self._last_context_hash = current_hash

        prompt = (
            "# Objective\n"
            "You are the Validator. Judge whether the following goal is "
            "satisfied based on the execution trace.\n\n"
            f"## Goal\n{root_goal}\n\n"
            f"## Latest Supervisor Output\n"
            f"Summary: {output.get('detailed_summary', '')}\n"
            f"Proofs: {output.get('proofs', '')}\n"
            f"Confidence: {output.get('confidence_score', 0.0)}\n\n"
            "# Execution Trace\n"
            f"{context}\n\n"
            "# Instructions\n"
            "- valid (true/false)\n"
            "- confidence (float 0.00–1.00)\n"
            "- critique (string)\n"
            "- validation_token — copy the exact FLAG{...} if present, "
            "otherwise empty string\n"
        )

        result = await self._agent.run(
            prompt=prompt,
            deps=None,
            message_history="",
            usage=None,
            usage_limits=None,
            deferred_tool_results=None,
        )

        judge_output = result.output
        if not isinstance(judge_output, _JudgeOutput):
            logger.debug("JudgeAgentStrategy: unexpected output type %s", type(judge_output))
            return ValidationVerdict(stop=False, confidence=0.0)
        # print(judge_output)
        return ValidationVerdict(
            stop=judge_output.valid,
            confidence=judge_output.confidence_score,
            token=judge_output.validation_token or "",
            critique=judge_output.critique,
            report=self._build_report(judge_output, root_goal) if judge_output.valid else "",
        )

    @staticmethod
    def _build_report(judge: _JudgeOutput, root_goal: str) -> str:
        token_line = f"**Token:** `{judge.validation_token}`\n\n" if judge.validation_token else ""
        return (
            "# Validation Report — Judge Verdict\n\n"
            f"**Goal:** {root_goal}\n\n"
            f"**Verdict:** {'ACHIEVED' if judge.valid else 'NOT ACHIEVED'}\n"
            f"**Confidence:** {judge.confidence_score:.2f}\n\n"
            f"{token_line}"
            "## Critique\n\n"
            f"{judge.critique}\n"
        )


class _JudgeOutput(BaseModel):
    """Structured output expected from the judge LLM call."""
    valid: bool
    confidence_score: float
    critique: str
    validation_token: str | None = None


# ---------------------------------------------------------------------------
# ValidationGate — composite that chains strategies
# ---------------------------------------------------------------------------

class ValidationGate:
    """Runs a chain of validation strategies and short-circuits on the first stop.

    Usage::

        gate = ValidationGate([FlagStrategy(), JudgeAgentStrategy(model)])
        verdict = await gate.check(output, root_goal, context)
        if verdict.stop:
            ...  # write report, exit loop
    """

    def __init__(self, strategies: list[ValidationStrategy]):
        if not strategies:
            raise ValueError("ValidationGate requires at least one strategy.")
        self.strategies = strategies

    async def check(
        self,
        output: dict,
        root_goal: str,
        context: str,
    ) -> ValidationVerdict:
        """Iterate strategies in order; return first stop=True verdict."""
        last_verdict = ValidationVerdict(stop=False, confidence=0.0)

        for strategy in self.strategies:
            verdict = await strategy.check(output, root_goal, context)
            if verdict.stop:
                logger.debug(
                    "ValidationGate: stop signalled by %s (confidence=%.2f)",
                    type(strategy).__name__,
                    verdict.confidence,
                )
                return verdict
            # Keep the highest-confidence non-stop verdict for callers.
            if verdict.confidence > last_verdict.confidence:
                last_verdict = verdict

        return last_verdict


# ---------------------------------------------------------------------------
# Strategy registry & factory
# ---------------------------------------------------------------------------

STRATEGY_REGISTRY: dict[str, type] = {
    "flag": FlagStrategy,
    "judge": JudgeAgentStrategy,
}

# Presets: ordered lists of strategy names.
PRESETS: dict[str, list[str]] = {
    "flag": ["flag"],
    "judge": ["judge"],
    "ctf": ["flag", "judge"],
    "recon": ["judge"],
}


def build_validation_gate(
    *,
    config: ValidationConfig | None = None,
    model: ModelSpec | None = None,
) -> ValidationGate:
    """Build a ValidationGate from a ``ValidationConfig``.

    The config is typically loaded from ``validation.yaml`` via
    ``load_validation_config()``.  If *config* is ``None`` the default
    config is used (flag + judge).

    Args:
        config: Parsed YAML config.  ``None`` → default.
        model: Required when any LLM-based strategy is in the chain.

    Returns:
        A configured ``ValidationGate`` ready for use.
    """
    cfg = config or ValidationConfig()

    instances: list[ValidationStrategy] = []
    for strategy_cfg in cfg.strategies:
        name = strategy_cfg.name

        if name == "flag":
            pattern = strategy_cfg.pattern or r"FLAG\{[^}]+\}"
            instances.append(FlagStrategy(pattern=pattern))

        elif name == "judge":
            if model is None:
                raise ValueError("JudgeAgentStrategy requires a model.")
            instances.append(JudgeAgentStrategy(
                model=model,
                validation_type=(
                    strategy_cfg.validation_type or cfg.validation_type
                ),
                validation_format=(
                    strategy_cfg.validation_format or cfg.validation_format
                ),
            ))

        elif name in STRATEGY_REGISTRY:
            instances.append(STRATEGY_REGISTRY[name]())  # type: ignore[call-arg]

        else:
            raise ValueError(
                f"Unknown strategy '{name}'. "
                f"Available: {list(STRATEGY_REGISTRY.keys())}"
            )

    return ValidationGate(instances)
