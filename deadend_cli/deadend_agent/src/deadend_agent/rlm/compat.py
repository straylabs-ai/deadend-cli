# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Compatibility checks for running RLM flows against current execution backends."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RLMSandboxCompatibilityReport:
    """Concrete capability report for the current Python sandbox integration."""

    backend_name: str
    persistent_state: bool
    inline_code_execution: bool
    host_callback_support: bool
    raw_llm_calls_required_inside_sandbox: bool
    compatible_for_full_rlm_repl: bool
    blockers: list[str] = field(default_factory=list)
    recommendation: str = ""


def assess_python_sandbox_compatibility() -> RLMSandboxCompatibilityReport:
    """Assess whether the current sandbox can host a faithful RLM REPL.

    The answer is currently no. The existing wrapper starts a fresh sandbox per
    tool invocation, executes a file, then shuts the sandbox down. There is no
    persistent Python state across turns, no inline REPL API, and no mechanism
    for code running inside the sandbox to call a host-managed ``llm_query``.
    """
    blockers = [
        "The sandbox wrapper only exposes run-file semantics, not incremental REPL execution.",
        "Each tool invocation starts a new interpreter process and shuts it down afterwards.",
        "There is no host callback channel for llm_query(prompt, content) from sandboxed code.",
        "Using raw provider calls inside sandboxed scripts would bypass CoreAgent and duplicate auth/routing logic.",
    ]
    return RLMSandboxCompatibilityReport(
        backend_name="python-sandbox-tool",
        persistent_state=False,
        inline_code_execution=False,
        host_callback_support=False,
        raw_llm_calls_required_inside_sandbox=False,
        compatible_for_full_rlm_repl=False,
        blockers=blockers,
        recommendation=(
            "Keep RLM orchestration and LLM calls on the host side. Use the sandbox only as a "
            "bounded execution backend after adding either persistent REPL support or an explicit "
            "host-mediated llm_query callback protocol."
        ),
    )
