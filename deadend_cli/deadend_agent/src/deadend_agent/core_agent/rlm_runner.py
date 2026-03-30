# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Sandbox-backed Recursive Language Model runner.

This module implements a practical RLM scaffold for DeadEnd:
- the root LM runs on the host
- the root LM emits Python code blocks
- those code blocks are executed in the existing Python sandbox backend
- sub-LLM calls are orchestrated by the host and exposed to sandboxed code
  through a queued ``llm_query(...)`` interface

The current sandbox backend does not support host callbacks or an in-process
interactive REPL, so this runner emulates a persistent REPL by reusing a
workspace directory and snapshotting picklable globals between iterations.
"""
from __future__ import annotations

import json
import pickle
import re
import shutil
import textwrap
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from deadend_agent.core_agent import (
    AuthenticationError,
    ConnectionError,
    InvalidRequestError,
    LLMError,
    ModelNotFoundError,
    QuotaExceededError,
    RateLimitError,
)
from deadend_agent.rlm.memory import RLMFileMemory, SUPPORTED_EXTENSIONS
from deadend_agent.tools.python_interpreter.python_interpreter import PythonInterpreter

try:
    from litellm import acompletion
    from litellm.exceptions import (
        APIConnectionError as LiteLLMConnectionError,
        ContentPolicyViolationError,
        RateLimitError as LiteLLMRateLimitError,
        ServiceUnavailableError,
        Timeout as LiteLLMTimeout,
    )
    LITELLM_AVAILABLE = True
except ImportError:
    acompletion = None

    class LiteLLMConnectionError(Exception):
        pass

    class ContentPolicyViolationError(Exception):
        pass

    class LiteLLMRateLimitError(Exception):
        pass

    class ServiceUnavailableError(Exception):
        pass

    class LiteLLMTimeout(Exception):
        pass

    LITELLM_AVAILABLE = False


PYTHON_BLOCK_RE = re.compile(r"```(?:python|repl)\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
FINAL_TEXT_RE = re.compile(r"FINAL\((.*)\)", re.DOTALL)
FINAL_VAR_RE = re.compile(r"FINAL_VAR\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)")


@dataclass
class SubcallRequest:
    """A queued sub-LLM request emitted from sandbox code."""

    request_id: str
    prompt: str
    content: str = ""
    model: str | None = None


@dataclass
class SandboxExecutionResult:
    """Result of executing one root-LM cell in the sandbox."""

    stdout: str = ""
    observations: list[str] = field(default_factory=list)
    state_keys: list[str] = field(default_factory=list)
    pending_subcalls: list[SubcallRequest] = field(default_factory=list)
    final_answer: str | None = None
    final_var: str | None = None
    errors: list[str] = field(default_factory=list)


@dataclass
class RLMRunResult:
    """Final output and metrics for an RLM run."""

    answer: str
    root_iterations: int
    root_requests: int
    subcall_requests: int
    workspace_dir: str


class SandboxedRLMRunner:
    """Run an RLM loop using host-side LLM calls and sandbox-side Python cells."""

    def __init__(
        self,
        root_model: str,
        sub_model: str | None = None,
        *,
        api_key: str | None = None,
        api_base: str | None = None,
        sub_api_key: str | None = None,
        sub_api_base: str | None = None,
        session_id: str | None = None,
        workspace_root: str | Path | None = None,
    ) -> None:
        self.root_model = root_model
        self.sub_model = sub_model or root_model
        self.api_key = api_key
        self.api_base = api_base
        self.sub_api_key = sub_api_key or api_key
        self.sub_api_base = sub_api_base or api_base
        self.session_id = session_id or str(uuid.uuid4())
        base = Path(workspace_root) if workspace_root else Path.home() / ".cache" / "deadend" / "python" / "rlm"
        self.workspace_dir = base / self.session_id
        self.memory_dir = self.workspace_dir / "memory"
        self.scripts_dir = self.workspace_dir / "scripts"
        self.artifacts_dir = self.workspace_dir / "artifacts"
        self.root_request_count = 0
        self.subcall_request_count = 0

    async def run(
        self,
        query: str,
        *,
        memory_root: str | Path | None = None,
        context: Any | None = None,
        max_iterations: int = 20,
    ) -> RLMRunResult:
        """Run the root/sub-call RLM loop.

        Args:
            query: User query/task for the RLM.
            memory_root: Optional existing memory directory to expose.
            context: Optional raw context to materialize into memory files.
            max_iterations: Safety limit for root iterations.
        """
        self._prepare_workspace(memory_root=memory_root, context=context)
        memory = RLMFileMemory(self.memory_dir)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self._build_system_prompt(memory)},
            {"role": "user", "content": query},
        ]

        interpreter = PythonInterpreter(session_id=self.session_id, directory=str(self.workspace_dir))
        await interpreter.initialize()

        try:
            for iteration in range(1, max_iterations + 1):
                assistant_text = await self._call_model(
                    model=self.root_model,
                    messages=messages,
                    api_key=self.api_key,
                    api_base=self.api_base,
                )
                self.root_request_count += 1

                direct_final = self._parse_direct_final(assistant_text)
                if direct_final is not None:
                    return RLMRunResult(
                        answer=direct_final,
                        root_iterations=iteration,
                        root_requests=self.root_request_count,
                        subcall_requests=self.subcall_request_count,
                        workspace_dir=str(self.workspace_dir),
                    )

                code_blocks = self._extract_code_blocks(assistant_text)
                messages.append({"role": "assistant", "content": assistant_text})

                if not code_blocks:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "No Python code block was produced. Continue by sending a ```python``` block "
                                "for the sandbox, or return FINAL(...)."
                            ),
                        }
                    )
                    continue

                execution_summaries: list[str] = []
                for cell_index, code in enumerate(code_blocks, start=1):
                    execution = await self._execute_cell(
                        interpreter=interpreter,
                        code=code,
                        iteration=iteration,
                        cell_index=cell_index,
                    )
                    await self._resolve_subcalls(execution.pending_subcalls)
                    execution_summaries.append(self._format_execution_feedback(execution))

                    if execution.final_answer is not None:
                        return RLMRunResult(
                            answer=execution.final_answer,
                            root_iterations=iteration,
                            root_requests=self.root_request_count,
                            subcall_requests=self.subcall_request_count,
                            workspace_dir=str(self.workspace_dir),
                        )

                messages.append({"role": "user", "content": "\n\n".join(execution_summaries)})

        finally:
            await interpreter.shutdown()

        raise RuntimeError(f"RLM did not terminate after {max_iterations} root iterations")

    def _prepare_workspace(self, *, memory_root: str | Path | None, context: Any | None) -> None:
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.scripts_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

        if memory_root:
            source = Path(memory_root).expanduser().resolve()
            if not source.exists():
                raise FileNotFoundError(f"Memory root does not exist: {source}")
            self._copy_supported_files(source, self.memory_dir)

        if context is not None:
            self._materialize_context(context)

    def _copy_supported_files(self, source: Path, destination: Path) -> None:
        for path in source.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            relative = path.relative_to(source)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)

    def _materialize_context(self, context: Any) -> None:
        if isinstance(context, str):
            (self.memory_dir / "context.txt").write_text(context, encoding="utf-8")
            return
        if isinstance(context, (dict, list)):
            (self.memory_dir / "context.json").write_text(
                json.dumps(context, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return
        (self.memory_dir / "context.txt").write_text(str(context), encoding="utf-8")

    def _build_system_prompt(self, memory: RLMFileMemory) -> str:
        manifest = memory.build_navigation_context()
        return textwrap.dedent(
            f"""\
            You are operating as a Recursive Language Model with a sandboxed Python workspace.

            Your job is to answer the user query by inspecting external memory through Python code.
            Do not paste long memory contents into the model output. Use the sandbox helpers instead.

            Memory manifest:
            {manifest}

            The sandbox runs Python scripts in a persistent workspace. Picklable top-level variables
            survive across turns.

            Available helpers inside the sandbox:
            - `list_files()`
            - `read_file(path)`
            - `read_chars(path, start=0, end=None)`
            - `read_lines(path, start=1, end=None)`
            - `grep_memory(pattern, path=None, max_results=20)`
            - `observe(*args)` to emit information back to you
            - `subcall_results` containing completed sub-LLM answers by request id
            - `llm_query(prompt, content="", model=None)`
            - `FINAL(text)`
            - `FINAL_VAR(var_name)`

            Important constraints:
            - `llm_query(...)` is host-mediated. If the exact request was already completed, it returns the result.
            - Otherwise it queues the request and returns a token like `__RLM_PENDING__:...`.
            - When a request is pending, stop that line of reasoning and continue on the next turn after inspecting the returned observations.
            - Always send Python in fenced blocks: ```python ... ```
            - Return `FINAL(...)` directly only if you do not need the sandbox anymore.
            """
        ).strip()

    def _extract_code_blocks(self, text: str) -> list[str]:
        return [match.group(1).strip() for match in PYTHON_BLOCK_RE.finditer(text) if match.group(1).strip()]

    def _parse_direct_final(self, text: str) -> str | None:
        match = FINAL_VAR_RE.search(text)
        if match:
            return self._resolve_state_var(match.group(1))

        match = FINAL_TEXT_RE.search(text)
        if not match:
            return None
        content = match.group(1).strip()
        if (content.startswith('"') and content.endswith('"')) or (content.startswith("'") and content.endswith("'")):
            return content[1:-1]
        return content

    def _resolve_state_var(self, var_name: str) -> str | None:
        state_path = self.artifacts_dir / "globals.pkl"
        if not state_path.exists():
            return None
        try:
            with open(state_path, "rb") as file_obj:
                state = pickle.load(file_obj)
        except Exception:
            return None
        if not isinstance(state, dict) or var_name not in state:
            return None
        value = state[var_name]
        return value if isinstance(value, str) else repr(value)

    async def _execute_cell(
        self,
        *,
        interpreter: PythonInterpreter,
        code: str,
        iteration: int,
        cell_index: int,
    ) -> SandboxExecutionResult:
        script_name = f"rlm_iter_{iteration:02d}_cell_{cell_index:02d}.py"
        script_path = self.scripts_dir / script_name
        script_path.write_text(self._build_script(code), encoding="utf-8")

        raw_result = await interpreter.run_file(str(Path("scripts") / script_name))
        observation = self._read_json_artifact("observation.json", default={})
        pending = self._read_json_artifact("pending_subcalls.json", default=[])
        final_payload = self._read_json_artifact("final.json", default=None)

        final_answer: str | None = None
        final_var: str | None = None
        if isinstance(final_payload, dict):
            final_answer = final_payload.get("value")
            final_var = final_payload.get("var_name")

        return SandboxExecutionResult(
            stdout=str(raw_result),
            observations=list(observation.get("observations", [])),
            state_keys=list(observation.get("state_keys", [])),
            pending_subcalls=[
                SubcallRequest(
                    request_id=item["request_id"],
                    prompt=item["prompt"],
                    content=item.get("content", ""),
                    model=item.get("model"),
                )
                for item in pending
            ],
            final_answer=final_answer,
            final_var=final_var,
            errors=list(observation.get("errors", [])),
        )

    def _build_script(self, user_code: str) -> str:
        workspace = str(self.workspace_dir)
        memory_dir = str(self.memory_dir)
        artifacts_dir = str(self.artifacts_dir)
        indented_code = textwrap.indent(user_code.rstrip() + "\n", "    ").rstrip()
        template = textwrap.dedent(
            f"""\
            import hashlib
            import json
            import os
            import pickle
            import re
            import traceback
            from pathlib import Path

            WORKSPACE_DIR = Path(r"{workspace}")
            MEMORY_DIR = Path(r"{memory_dir}")
            ARTIFACTS_DIR = Path(r"{artifacts_dir}")
            STATE_PATH = ARTIFACTS_DIR / "globals.pkl"
            SUBCALL_RESULTS_PATH = ARTIFACTS_DIR / "subcall_results.json"
            PENDING_SUBCALLS_PATH = ARTIFACTS_DIR / "pending_subcalls.json"
            OBSERVATION_PATH = ARTIFACTS_DIR / "observation.json"
            FINAL_PATH = ARTIFACTS_DIR / "final.json"

            for _directory in (WORKSPACE_DIR, MEMORY_DIR, ARTIFACTS_DIR):
                _directory.mkdir(parents=True, exist_ok=True)

            _BOOTSTRAP_NAMES = {{
                "hashlib", "json", "os", "pickle", "re", "traceback", "Path",
                "WORKSPACE_DIR", "MEMORY_DIR", "ARTIFACTS_DIR", "STATE_PATH",
                "SUBCALL_RESULTS_PATH", "PENDING_SUBCALLS_PATH", "OBSERVATION_PATH",
                "FINAL_PATH", "_BOOTSTRAP_NAMES", "_load_json", "_write_json",
                "_runtime", "_stable_subcall_id", "_resolve_memory_path", "_save_state",
                "_load_state", "subcall_results", "observe", "llm_query", "FINAL",
                "FINAL_VAR", "list_files", "read_file", "read_chars", "read_lines",
                "grep_memory", "_supported_suffixes"
            }}

            _supported_suffixes = {sorted(SUPPORTED_EXTENSIONS)!r}

            def _load_json(path, default):
                if not path.exists():
                    return default
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    return default

            def _write_json(path, payload):
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

            subcall_results = _load_json(SUBCALL_RESULTS_PATH, {{}})
            _runtime = {{
                "observations": [],
                "pending_subcalls": [],
                "errors": [],
                "final": None,
            }}

            def _stable_subcall_id(prompt, content="", model=None):
                payload = json.dumps(
                    {{"prompt": prompt, "content": content, "model": model or ""}},
                    sort_keys=True,
                    ensure_ascii=False,
                )
                return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]

            def _resolve_memory_path(path):
                candidate = (MEMORY_DIR / path).resolve()
                if not str(candidate).startswith(str(MEMORY_DIR.resolve())):
                    raise ValueError(f"Path escapes memory directory: {{path}}")
                if not candidate.exists():
                    raise FileNotFoundError(f"Memory file not found: {{path}}")
                return candidate

            def list_files():
                output = []
                for file_path in sorted(MEMORY_DIR.rglob("*")):
                    if file_path.is_file() and file_path.suffix.lower() in _supported_suffixes:
                        rel = file_path.relative_to(MEMORY_DIR)
                        output.append(str(rel))
                return output

            def read_file(path):
                return _resolve_memory_path(path).read_text(encoding="utf-8")

            def read_chars(path, start=0, end=None):
                text = read_file(path)
                return text[start:end]

            def read_lines(path, start=1, end=None):
                lines = read_file(path).splitlines()
                start_index = max(0, int(start) - 1)
                end_index = len(lines) if end is None else max(start_index, int(end))
                return "\\n".join(lines[start_index:end_index])

            def grep_memory(pattern, path=None, max_results=20):
                compiled = re.compile(pattern, re.MULTILINE)
                targets = [path] if path else list_files()
                matches = []
                for target in targets:
                    for line_number, line in enumerate(read_file(target).splitlines(), start=1):
                        match = compiled.search(line)
                        if not match:
                            continue
                        matches.append({{
                            "path": target,
                            "line_number": line_number,
                            "match": match.group(0),
                            "context": line[:240],
                        }})
                        if len(matches) >= max_results:
                            return matches
                return matches

            def observe(*args):
                text = " ".join(str(arg) for arg in args)
                _runtime["observations"].append(text)
                print(text)
                return text

            def llm_query(prompt, content="", model=None):
                request_id = _stable_subcall_id(prompt, content=content, model=model)
                if request_id in subcall_results:
                    return subcall_results[request_id]["result"]
                _runtime["pending_subcalls"].append({{
                    "request_id": request_id,
                    "prompt": prompt,
                    "content": content,
                    "model": model,
                }})
                token = f"__RLM_PENDING__:{{request_id}}"
                observe("queued_subcall", request_id)
                return token

            def FINAL(text):
                payload = {{"type": "text", "value": str(text)}}
                _runtime["final"] = payload
                _write_json(FINAL_PATH, payload)
                return text

            def FINAL_VAR(var_name):
                if var_name not in globals():
                    raise KeyError(f"Variable not found for FINAL_VAR: {{var_name}}")
                value = globals()[var_name]
                payload = {{
                    "type": "var",
                    "var_name": var_name,
                    "value": value if isinstance(value, str) else repr(value),
                }}
                _runtime["final"] = payload
                _write_json(FINAL_PATH, payload)
                return value

            def _load_state():
                if not STATE_PATH.exists():
                    return
                try:
                    with open(STATE_PATH, "rb") as file_obj:
                        state = pickle.load(file_obj)
                    if isinstance(state, dict):
                        for key, value in state.items():
                            globals()[key] = value
                except Exception as exc:
                    _runtime["errors"].append(f"state_load_error: {{exc!r}}")

            def _save_state():
                state = {{}}
                for key, value in list(globals().items()):
                    if key.startswith("_") or key in _BOOTSTRAP_NAMES:
                        continue
                    if callable(value):
                        continue
                    if getattr(value, "__class__", None).__name__ == "module":
                        continue
                    try:
                        pickle.dumps(value)
                    except Exception:
                        continue
                    state[key] = value
                with open(STATE_PATH, "wb") as file_obj:
                    pickle.dump(state, file_obj)
                return sorted(state.keys())

            _load_state()
            FINAL_PATH.unlink(missing_ok=True)
            PENDING_SUBCALLS_PATH.unlink(missing_ok=True)

            try:
            __USER_CODE__
            except Exception:
                _runtime["errors"].append(traceback.format_exc())
            finally:
                state_keys = _save_state()
                _write_json(PENDING_SUBCALLS_PATH, _runtime["pending_subcalls"])
                _write_json(
                    OBSERVATION_PATH,
                    {{
                        "observations": _runtime["observations"],
                        "errors": _runtime["errors"],
                        "state_keys": state_keys,
                        "final": _runtime["final"],
                    }},
                )
            """
        ).lstrip()
        return template.replace("__USER_CODE__", indented_code)

    async def _resolve_subcalls(self, requests: list[SubcallRequest]) -> None:
        if not requests:
            return

        results = self._read_json_artifact("subcall_results.json", default={})
        for request in requests:
            if request.request_id in results:
                continue
            result = await self._call_model(
                model=request.model or self.sub_model,
                messages=self._build_subcall_messages(request),
                api_key=self.sub_api_key,
                api_base=self.sub_api_base,
            )
            self.subcall_request_count += 1
            results[request.request_id] = {
                "prompt": request.prompt,
                "content": request.content,
                "model": request.model or self.sub_model,
                "result": result,
            }

        self._write_json_artifact("subcall_results.json", results)

    def _build_subcall_messages(self, request: SubcallRequest) -> list[dict[str, str]]:
        content = request.prompt
        if request.content:
            content += f"\n\nContext:\n{request.content}"
        return [{"role": "user", "content": content}]

    def _format_execution_feedback(self, execution: SandboxExecutionResult) -> str:
        parts = []
        if execution.observations:
            parts.append("Sandbox observations:\n" + "\n".join(f"- {item}" for item in execution.observations[-20:]))
        if execution.pending_subcalls:
            parts.append(
                "Queued subcalls:\n"
                + "\n".join(f"- {item.request_id}" for item in execution.pending_subcalls)
            )
            sub_results = self._read_json_artifact("subcall_results.json", default={})
            completed = [
                f"- {item.request_id}: {sub_results[item.request_id]['result'][:500]}"
                for item in execution.pending_subcalls
                if item.request_id in sub_results
            ]
            if completed:
                parts.append("Completed subcall results:\n" + "\n".join(completed))
        if execution.errors:
            parts.append("Sandbox errors:\n" + "\n".join(execution.errors))
        if execution.state_keys:
            parts.append("Persisted state keys:\n" + ", ".join(execution.state_keys))
        stdout = execution.stdout.strip()
        if stdout:
            parts.append("Sandbox backend response:\n" + stdout[:2000])
        return "\n\n".join(parts) if parts else "Sandbox cell executed with no observations."

    def _read_json_artifact(self, filename: str, default: Any) -> Any:
        path = self.artifacts_dir / filename
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    def _write_json_artifact(self, filename: str, payload: Any) -> None:
        path = self.artifacts_dir / filename
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type(
            (
                LiteLLMRateLimitError,
                ServiceUnavailableError,
                LiteLLMTimeout,
                LiteLLMConnectionError,
            )
        ),
        reraise=True,
    )
    async def _call_model(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        api_key: str | None,
        api_base: str | None,
    ) -> str:
        if not LITELLM_AVAILABLE or acompletion is None:
            raise RuntimeError("litellm is required to run SandboxedRLMRunner model calls")

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if api_base:
            kwargs["api_base"] = api_base
        if api_key:
            kwargs["api_key"] = api_key
        elif api_base and model.startswith("openai/"):
            kwargs["api_key"] = "sk-dummy-key-for-local-model"

        try:
            response = await acompletion(**kwargs)
        except ContentPolicyViolationError as exc:
            raise InvalidRequestError(
                "Request blocked by provider content policy.",
                original_error=exc,
            ) from exc
        except Exception as exc:
            self._raise_llm_error(model=model, error=exc)

        content = response.choices[0].message.content
        return content or ""

    def _raise_llm_error(self, *, model: str, error: Exception) -> None:
        error_str = str(error).lower()
        if "insufficient_quota" in error_str or "exceeded your current quota" in error_str:
            raise QuotaExceededError(f"API quota exceeded for {model}: {error}", original_error=error) from error
        if "rate_limit" in error_str or "rate limit" in error_str or "429" in error_str:
            raise RateLimitError(f"Rate limit exceeded for {model}: {error}", original_error=error) from error
        if "auth" in error_str or "api_key" in error_str or "401" in error_str:
            raise AuthenticationError(f"API authentication failed for {model}: {error}", original_error=error) from error
        if "model" in error_str and ("not found" in error_str or "404" in error_str or "does not exist" in error_str):
            raise ModelNotFoundError(f"Model '{model}' not found: {error}", original_error=error) from error
        if "connection" in error_str or "connect" in error_str or "timeout" in error_str or "unreachable" in error_str:
            raise ConnectionError(f"Failed to connect for {model}: {error}", original_error=error) from error
        if "bad request" in error_str or "invalid" in error_str or "400" in error_str:
            raise InvalidRequestError(f"Invalid request for {model}: {error}", original_error=error) from error
        raise LLMError(f"LLM request failed for {model}: {error}", original_error=error) from error
