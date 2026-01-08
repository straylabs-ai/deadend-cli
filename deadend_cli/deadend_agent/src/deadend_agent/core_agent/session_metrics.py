# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Per-session metrics tracking for agent usage.

Tracks and persists metrics for each agent session:
- Token usage (input/output)
- Tool call counts
- Agent call counts by type
- Error counts by type
- Session duration

Metrics are saved to ~/.cache/deadend/sessions/{session_id}/metrics.json
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict

from pydantic import BaseModel, Field


class TokenUsage(BaseModel):
    """Token usage tracking."""
    input: int = Field(default=0, description="Input/prompt tokens")
    output: int = Field(default=0, description="Output/completion tokens")

    @property
    def total(self) -> int:
        """Total tokens used."""
        return self.input + self.output


class SessionMetrics(BaseModel):
    """Metrics tracked for an agent session.

    Provides comprehensive tracking of agent usage, tokens, tools, and errors
    for a single session. Automatically persists to disk when saved.
    """

    session_id: str = Field(..., description="Unique session identifier")
    total_tokens: TokenUsage = Field(default_factory=TokenUsage, description="Total token usage")
    tool_calls: int = Field(default=0, description="Total tool calls made")
    agent_calls: Dict[str, int] = Field(default_factory=dict, description="Calls per agent type")
    errors: Dict[str, int] = Field(default_factory=dict, description="Errors by type")
    start_time: float = Field(default_factory=time.time, description="Session start timestamp")
    duration_seconds: float = Field(default=0.0, description="Session duration")

    class Config:
        """Pydantic config."""
        arbitrary_types_allowed = True

    def record_completion(self, agent_name: str, prompt_tokens: int, completion_tokens: int):
        """Record an agent completion with token usage.

        Args:
            agent_name: Name of the agent that ran
            prompt_tokens: Number of input/prompt tokens used
            completion_tokens: Number of output/completion tokens used
        """
        # Access as TokenUsage instance (Pydantic handles this at runtime)
        tokens: TokenUsage = self.total_tokens  # type: ignore[assignment]
        tokens.input += prompt_tokens
        tokens.output += completion_tokens

        if agent_name not in self.agent_calls:
            self.agent_calls[agent_name] = 0
        self.agent_calls[agent_name] += 1

    def record_tool_call(self, count: int = 1):
        """Record one or more tool calls.

        Args:
            count: Number of tool calls to record (default: 1)
        """
        self.tool_calls += count

    def record_error(self, error_type: str):
        """Record an error occurrence.

        Args:
            error_type: Type/category of error (e.g., "rate_limit", "timeout")
        """
        if error_type not in self.errors:
            self.errors[error_type] = 0
        self.errors[error_type] += 1

    def update_duration(self):
        """Update session duration based on current time."""
        self.duration_seconds = time.time() - self.start_time

    def save(self):
        """Persist metrics to disk.

        Saves to: ~/.cache/deadend/sessions/{session_id}/metrics.json
        Updates duration before saving.
        """
        self.update_duration()

        # Create session directory
        cache_dir = Path.home() / ".cache" / "deadend" / "sessions" / self.session_id
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Write metrics to JSON file
        metrics_path = cache_dir / "metrics.json"
        with open(metrics_path, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(), f, indent=2)

    @classmethod
    def load(cls, session_id: str) -> SessionMetrics:
        """Load existing session metrics from disk.

        Args:
            session_id: Session identifier

        Returns:
            SessionMetrics instance loaded from file, or new instance if not found

        Raises:
            FileNotFoundError: If metrics file doesn't exist
        """
        cache_dir = Path.home() / ".cache" / "deadend" / "sessions" / session_id
        metrics_path = cache_dir / "metrics.json"

        if not metrics_path.exists():
            raise FileNotFoundError(f"No metrics found for session: {session_id}")

        with open(metrics_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return cls(**data)


# Global session registry
_session_registry: Dict[str, SessionMetrics] = {}


def get_session_metrics(session_id: str) -> SessionMetrics:
    """Get or create session metrics for a session ID.

    Uses a global registry to ensure single instance per session.

    Args:
        session_id: Unique session identifier

    Returns:
        SessionMetrics instance for the session
    """
    if session_id not in _session_registry:
        # Try to load existing metrics first
        try:
            _session_registry[session_id] = SessionMetrics.load(session_id)
        except FileNotFoundError:
            # Create new metrics if none exist
            _session_registry[session_id] = SessionMetrics(session_id=session_id)

    return _session_registry[session_id]


def clear_session_registry():
    """Clear the global session registry.

    Useful for testing or when starting fresh.
    """
    _session_registry.clear()
