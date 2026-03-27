import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "deadend_agent"

if "deadend_agent" not in sys.modules:
    package = types.ModuleType("deadend_agent")
    package.__path__ = [str(PACKAGE_ROOT)]
    sys.modules["deadend_agent"] = package

if "deadend_agent.tools" not in sys.modules:
    tools_package = types.ModuleType("deadend_agent.tools")
    tools_package.__path__ = [str(PACKAGE_ROOT / "tools")]
    sys.modules["deadend_agent.tools"] = tools_package

if "deadend_agent.tools.avfs" not in sys.modules:
    avfs_package = types.ModuleType("deadend_agent.tools.avfs")
    avfs_package.__path__ = [str(PACKAGE_ROOT / "tools" / "avfs")]
    sys.modules["deadend_agent.tools.avfs"] = avfs_package

if "pydantic_ai" not in sys.modules:
    pydantic_ai_module = types.ModuleType("pydantic_ai")

    class RunContext:
        def __init__(self, deps=None):
            self.deps = deps

        def __class_getitem__(cls, _item):
            return cls

    pydantic_ai_module.RunContext = RunContext
    sys.modules["pydantic_ai"] = pydantic_ai_module

from deadend_agent.tools.avfs.avfs import AVFS, avfs
from deadend_agent.tools.avfs.list import avfs_mount, avfs_umount
from deadend_agent.tools.avfs.read import avfs_grep
from deadend_agent.tools.avfs.write import avfs_write, write_text


def test_avfs_mount_and_resolve(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "notes.txt").write_text("hello", encoding="utf-8")

    fs = AVFS()
    fs.mount(root)

    resolved = fs.resolve("notes.txt")
    assert resolved == (root / "notes.txt").resolve()
    assert fs.current_directory() == "/"


def test_avfs_blocks_path_escape(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    fs = AVFS()
    fs.mount(root)

    with pytest.raises(ValueError):
        fs.resolve("../secret.txt")


def test_avfs_resolves_relative_to_virtual_directory(tmp_path):
    root = tmp_path / "workspace"
    nested = root / "src" / "pkg"
    nested.mkdir(parents=True)
    target = nested / "module.py"
    target.write_text("print('ok')\n", encoding="utf-8")

    fs = AVFS()
    fs.mount(root, directory="src")

    assert fs.current_directory() == "/src"
    assert fs.resolve("pkg/module.py") == target.resolve()
    assert fs.resolve("./pkg/../pkg/module.py") == target.resolve()


def test_avfs_mount_rejects_symlink_escape(tmp_path):
    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "jump").symlink_to(outside, target_is_directory=True)

    fs = AVFS()
    fs.mount(root)

    with pytest.raises(ValueError):
        fs.resolve("jump/secret.txt")


def test_avfs_can_change_virtual_directory(tmp_path):
    root = tmp_path / "workspace"
    nested = root / "docs"
    nested.mkdir(parents=True)

    fs = AVFS()
    fs.mount(root)

    changed = fs.chdir("docs")

    assert changed == "/docs"
    assert fs.current_directory() == "/docs"


def test_avfs_tracks_session_specific_state(tmp_path):
    root = tmp_path / "workspace"
    (root / "alpha").mkdir(parents=True)
    (root / "beta").mkdir(parents=True)

    fs = AVFS()
    fs.mount(root, directory="alpha", session_id="session-a")
    fs.mount(root, directory="beta", session_id="session-b")

    assert fs.current_directory(session_id="session-a") == "/alpha"
    assert fs.current_directory(session_id="session-b") == "/beta"


def test_avfs_write_updates_host_file(tmp_path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    ctx = SimpleNamespace(deps=SimpleNamespace(session_id="session-write"))

    async def run_test() -> None:
        await avfs_mount(ctx, workspace_root=str(workspace_root))
        try:
            result = await avfs_write(ctx, "notes.txt", "alpha")
            assert "Wrote" in result
            assert (workspace_root / "notes.txt").read_text(encoding="utf-8") == "alpha"

            await avfs_write(ctx, "notes.txt", "\nbeta", append=True)
            assert (workspace_root / "notes.txt").read_text(encoding="utf-8") == "alpha\nbeta"
        finally:
            await avfs_umount(ctx)

    asyncio.run(run_test())


def test_write_text_updates_named_memory_workspace(tmp_path):
    memory_root = tmp_path / "agents" / "local-agent" / "memory"
    memory_root.mkdir(parents=True)

    avfs.mount(memory_root, session_id="session-memory", workspace="memory")
    try:
        result = write_text(
            "summaries/requester.md",
            "alpha",
            session_id="session-memory",
            workspace="memory",
        )

        assert "Wrote" in result
        assert (memory_root / "summaries" / "requester.md").read_text(encoding="utf-8") == "alpha"
    finally:
        avfs.umount(session_id="session-memory", workspace="memory")


def test_avfs_grep_uses_ripgrepy_and_returns_virtual_paths(tmp_path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    target = workspace_root / "notes.txt"
    target.write_text("alpha\n", encoding="utf-8")
    ctx = SimpleNamespace(deps=SimpleNamespace(session_id="session-grep"))

    class FakeRunResult:
        @property
        def as_dict(self):
            return [
                {
                    "type": "match",
                    "data": {
                        "path": {"text": str(target)},
                        "line_number": 1,
                        "lines": {"text": "alpha\n"},
                        "submatches": [{"match": {"text": "alpha"}}],
                    },
                }
            ]

    class FakeRipgrepy:
        calls: list[tuple[str, object]] = []

        def __init__(self, pattern: str, path: str) -> None:
            self.calls.append(("init", (pattern, path)))

        def json(self):
            self.calls.append(("json", None))
            return self

        def no_config(self):
            self.calls.append(("no_config", None))
            return self

        def no_messages(self):
            self.calls.append(("no_messages", None))
            return self

        def no_ignore(self):
            self.calls.append(("no_ignore", None))
            return self

        def ignore_case(self):
            self.calls.append(("ignore_case", None))
            return self

        def hidden(self):
            self.calls.append(("hidden", None))
            return self

        def m(self, max_results):
            self.calls.append(("m", max_results))
            return self

        def run(self):
            self.calls.append(("run", None))
            return FakeRunResult()

    async def run_test() -> None:
        await avfs_mount(ctx, workspace_root=str(workspace_root))
        try:
            import sys

            sys.modules["ripgrepy"] = SimpleNamespace(Ripgrepy=FakeRipgrepy)
            matches = await avfs_grep(ctx, "alpha", include_hidden=True)

            assert matches == [
                {
                    "path": "notes.txt",
                    "line_number": 1,
                    "match": "alpha",
                    "context": "alpha",
                }
            ]
            assert FakeRipgrepy.calls == [
                ("init", ("alpha", str(workspace_root))),
                ("json", None),
                ("no_config", None),
                ("no_messages", None),
                ("no_ignore", None),
                ("m", 50),
                ("ignore_case", None),
                ("hidden", None),
                ("run", None),
            ]
        finally:
            sys.modules.pop("ripgrepy", None)
            await avfs_umount(ctx)

    asyncio.run(run_test())
