import json
import sys
import types
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "deadend_agent"

if "deadend_agent" not in sys.modules:
    package = types.ModuleType("deadend_agent")
    package.__path__ = [str(PACKAGE_ROOT)]
    sys.modules["deadend_agent"] = package

if "tenacity" not in sys.modules:
    tenacity_module = types.ModuleType("tenacity")

    def retry(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

    def retry_if_exception_type(*args, **kwargs):
        return None

    def stop_after_attempt(*args, **kwargs):
        return None

    def wait_exponential(*args, **kwargs):
        return None

    tenacity_module.retry = retry
    tenacity_module.retry_if_exception_type = retry_if_exception_type
    tenacity_module.stop_after_attempt = stop_after_attempt
    tenacity_module.wait_exponential = wait_exponential
    sys.modules["tenacity"] = tenacity_module

if "deadend_agent.rlm" not in sys.modules:
    rlm_package = types.ModuleType("deadend_agent.rlm")
    rlm_package.__path__ = [str(PACKAGE_ROOT / "rlm")]
    sys.modules["deadend_agent.rlm"] = rlm_package

if "deadend_agent.tools" not in sys.modules:
    tools_package = types.ModuleType("deadend_agent.tools")
    tools_package.__path__ = [str(PACKAGE_ROOT / "tools")]
    sys.modules["deadend_agent.tools"] = tools_package

if "deadend_agent.tools.python_interpreter" not in sys.modules:
    pyi_package = types.ModuleType("deadend_agent.tools.python_interpreter")
    pyi_package.__path__ = [str(PACKAGE_ROOT / "tools" / "python_interpreter")]
    sys.modules["deadend_agent.tools.python_interpreter"] = pyi_package

if "deadend_agent.tools.python_interpreter.python_interpreter" not in sys.modules:
    stub_python_interpreter = types.ModuleType("deadend_agent.tools.python_interpreter.python_interpreter")

    class PythonInterpreter:  # pragma: no cover - import stub only
        pass

    stub_python_interpreter.PythonInterpreter = PythonInterpreter
    sys.modules["deadend_agent.tools.python_interpreter.python_interpreter"] = stub_python_interpreter

if "deadend_agent.core_agent" not in sys.modules:
    core_agent_package = types.ModuleType("deadend_agent.core_agent")
    core_agent_package.__path__ = [str(PACKAGE_ROOT / "core_agent")]

    class LLMError(Exception):
        def __init__(self, message: str, original_error: Exception | None = None):
            self.message = message
            self.original_error = original_error
            super().__init__(message)

    class RateLimitError(LLMError):
        pass

    class QuotaExceededError(LLMError):
        pass

    class AuthenticationError(LLMError):
        pass

    class ConnectionError(LLMError):
        pass

    class ModelNotFoundError(LLMError):
        pass

    class InvalidRequestError(LLMError):
        pass

    core_agent_package.LLMError = LLMError
    core_agent_package.RateLimitError = RateLimitError
    core_agent_package.QuotaExceededError = QuotaExceededError
    core_agent_package.AuthenticationError = AuthenticationError
    core_agent_package.ConnectionError = ConnectionError
    core_agent_package.ModelNotFoundError = ModelNotFoundError
    core_agent_package.InvalidRequestError = InvalidRequestError
    sys.modules["deadend_agent.core_agent"] = core_agent_package

from deadend_agent.core_agent.rlm_runner import SandboxedRLMRunner


def _exec_script(script: str) -> None:
    globals_dict = {"__name__": "__main__"}
    exec(script, globals_dict, globals_dict)


def test_runner_extracts_python_blocks_and_direct_final(tmp_path):
    runner = SandboxedRLMRunner(root_model="openai/test", workspace_root=tmp_path)
    blocks = runner._extract_code_blocks(
        "before\n```python\nx = 1\n```\nafter\n```repl\nobserve(x)\n```"
    )

    assert blocks == ["x = 1", "observe(x)"]
    assert runner._parse_direct_final("FINAL('done')") == "done"


def test_runner_script_persists_state_and_reuses_subcall_results(tmp_path):
    runner = SandboxedRLMRunner(root_model="openai/test", workspace_root=tmp_path, session_id="session")
    runner._prepare_workspace(memory_root=None, context={"docs": ["alpha", "beta"]})

    first_script = runner._build_script(
        "x = 7\n"
        "observe('ready', x)\n"
        "token = llm_query('summarize', 'hello world')\n"
        "observe(token)\n"
    )
    _exec_script(first_script)

    observation = json.loads((runner.artifacts_dir / "observation.json").read_text(encoding="utf-8"))
    pending = json.loads((runner.artifacts_dir / "pending_subcalls.json").read_text(encoding="utf-8"))

    assert observation["observations"][0] == "ready 7"
    assert observation["state_keys"] == ["token", "x"]
    assert len(pending) == 1

    request_id = pending[0]["request_id"]
    (runner.artifacts_dir / "subcall_results.json").write_text(
        json.dumps(
            {
                request_id: {
                    "prompt": "summarize",
                    "content": "hello world",
                    "model": "openai/test",
                    "result": "summary-result",
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    second_script = runner._build_script(
        "observe('state', x)\n"
        "answer = llm_query('summarize', 'hello world')\n"
        "observe(answer)\n"
        "FINAL_VAR('answer')\n"
    )
    _exec_script(second_script)

    final_payload = json.loads((runner.artifacts_dir / "final.json").read_text(encoding="utf-8"))
    observation = json.loads((runner.artifacts_dir / "observation.json").read_text(encoding="utf-8"))

    assert final_payload["value"] == "summary-result"
    assert observation["observations"][-1] == "summary-result"


def test_runner_script_supports_mount_based_file_ops(tmp_path):
    runner = SandboxedRLMRunner(root_model="openai/test", workspace_root=tmp_path, session_id="session-avfs")
    runner._prepare_workspace(memory_root=None, context={"seed": "ok"})

    script = runner._build_script(
        "mounted = mount('.')\n"
        "observe('mounted', mounted)\n"
        "write_file('notes/a.txt', 'alpha\\nbeta\\n')\n"
        "files = list_files('notes')\n"
        "observe('files', files)\n"
        "snippet = read_lines('notes/a.txt', 2, 2)\n"
        "observe('line2', snippet)\n"
        "hits = grep('alpha', path='notes')\n"
        "observe('hits', hits[0]['path'], hits[0]['line_number'])\n"
    )
    _exec_script(script)

    observation = json.loads((runner.artifacts_dir / "observation.json").read_text(encoding="utf-8"))
    observed = "\n".join(observation["observations"])

    assert "mounted " in observed
    assert "notes/a.txt" in observed
    assert "line2 beta" in observed
    assert "hits notes/a.txt 1" in observed
