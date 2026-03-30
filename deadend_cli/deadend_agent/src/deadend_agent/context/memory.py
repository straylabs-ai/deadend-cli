# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""High-level memory access built on top of RLM file memory."""
from __future__ import annotations

from pathlib import Path
from uuid import UUID

from deadend_agent.rlm.compat import (
    RLMSandboxCompatibilityReport,
    assess_python_sandbox_compatibility,
)
from deadend_agent.rlm.memory import RLMFileMemory, MemoryFileMetadata


class MemoryHandler:
    """Session-backed memory handler for RLM-style external memory access."""

    def __init__(self, memory_root: str | Path) -> None:
        self.memory_root = Path(memory_root).expanduser().resolve()
        self.memory_root.mkdir(parents=True, exist_ok=True)
        self._memory = RLMFileMemory(root=self.memory_root)

    @classmethod
    def for_session(
        cls,
        session_key: str | None = None,
        session_id: str | UUID | None = None,
        base_dir: str | Path | None = None,
    ) -> "MemoryHandler":
        """Create a handler for a session-backed memory directory."""
        if session_key:
            leaf = session_key
        elif session_id is not None:
            leaf = str(session_id)
        else:
            raise ValueError("session_key or session_id must be provided")

        root = Path(base_dir) if base_dir else Path.home() / ".cache" / "deadend" / "memory" / "sessions"
        return cls(root / leaf)

    def refresh(self) -> None:
        """Reload file discovery from disk."""
        self._memory = RLMFileMemory(root=self.memory_root)

    def list_files(self, file_type: str | None = None) -> list[MemoryFileMetadata]:
        """Return memory file metadata."""
        return self._memory.list_files(file_type=file_type)

    def describe_memory(self) -> str:
        """Return a prompt-friendly navigation summary."""
        return self._memory.build_navigation_context()

    def describe_context(self) -> dict:
        """Return prompt metadata for the indexed memory."""
        return self._memory.describe_context()

    def get_rlm_memory(self) -> RLMFileMemory:
        """Expose the underlying RLM file memory implementation."""
        return self._memory

    def sandbox_compatibility(self) -> RLMSandboxCompatibilityReport:
        """Return compatibility information for the current sandbox backend."""
        return assess_python_sandbox_compatibility()
