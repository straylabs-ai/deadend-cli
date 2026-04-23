import json
import sys
import types
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "deadend_agent"

if "deadend_agent" not in sys.modules:
    package = types.ModuleType("deadend_agent")
    package.__path__ = [str(PACKAGE_ROOT)]
    sys.modules["deadend_agent"] = package

if "deadend_agent.context" not in sys.modules:
    context_package = types.ModuleType("deadend_agent.context")
    context_package.__path__ = [str(PACKAGE_ROOT / "context")]
    sys.modules["deadend_agent.context"] = context_package

if "deadend_agent.rlm" not in sys.modules:
    rlm_package = types.ModuleType("deadend_agent.rlm")
    rlm_package.__path__ = [str(PACKAGE_ROOT / "rlm")]
    sys.modules["deadend_agent.rlm"] = rlm_package

from deadend_agent.rlm.compat import assess_python_sandbox_compatibility
from deadend_agent.rlm.memory import RLMFileMemory


def test_rlm_file_memory_indexes_markdown_and_json(tmp_path):
    docs_dir = tmp_path / "session"
    docs_dir.mkdir()

    markdown_path = docs_dir / "notes.md"
    markdown_path.write_text(
        "# Overview\n"
        "System overview.\n\n"
        "## Findings\n"
        "- SQLi on /login\n"
        "- Stored XSS on /profile\n",
        encoding="utf-8",
    )

    json_path = docs_dir / "state.json"
    json_path.write_text(
        json.dumps(
            {
                "target": {"host": "example.com", "port": 443},
                "findings": [
                    {"type": "sqli", "endpoint": "/login"},
                    {"type": "xss", "endpoint": "/profile"},
                ],
            }
        ),
        encoding="utf-8",
    )

    memory = RLMFileMemory(root=docs_dir)
    files = memory.list_files()

    assert [item.path for item in files] == ["notes.md", "state.json"]
    assert memory.read_md_section("notes.md", "Findings").startswith("## Findings")
    assert memory.search_md_headings("find") == [
        {
            "path": "notes.md",
            "section_id": "findings",
            "heading": "Findings",
            "level": 2,
        }
    ]

    assert memory.json_get("state.json", "target.host") == "example.com"
    assert memory.json_sample_array("state.json", "findings", 0, 1) == [
        {"type": "sqli", "endpoint": "/login"}
    ]


def test_sandbox_compatibility_report_marks_current_backend_incompatible():
    report = assess_python_sandbox_compatibility()

    assert report.backend_name == "python-sandbox-tool"
    assert report.compatible_for_full_rlm_repl is False
    assert report.persistent_state is False
    assert report.inline_code_execution is False
    assert report.host_callback_support is False
    assert len(report.blockers) >= 3
