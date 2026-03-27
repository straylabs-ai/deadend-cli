import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace


PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "deadend_agent"

if "deadend_agent" not in sys.modules:
    package = types.ModuleType("deadend_agent")
    package.__path__ = [str(PACKAGE_ROOT)]
    sys.modules["deadend_agent"] = package

if "deadend_agent.tools" not in sys.modules:
    tools_package = types.ModuleType("deadend_agent.tools")
    tools_package.__path__ = [str(PACKAGE_ROOT / "tools")]
    sys.modules["deadend_agent.tools"] = tools_package

if "pydantic_ai" not in sys.modules:
    pydantic_ai_module = types.ModuleType("pydantic_ai")

    class RunContext:
        def __init__(self, deps=None):
            self.deps = deps

        def __class_getitem__(cls, _item):
            return cls

    pydantic_ai_module.RunContext = RunContext
    sys.modules["pydantic_ai"] = pydantic_ai_module

from deadend_agent.tools.avfs.list import avfs_mount, avfs_umount
from deadend_agent.tools.avfs.read import avfs_read
from deadend_agent.tools.avfs.write import avfs_write


def test_avfs_write_updates_named_memory_workspace(tmp_path):
    memory_root = tmp_path / "agents" / "local-agent" / "memory"
    memory_root.mkdir(parents=True)
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            session_id="memory-session",
            memory_workspace_root=str(memory_root),
        )
    )

    async def run_test() -> None:
        await avfs_mount(ctx, workspace_root=str(memory_root), workspace="memory")
        try:
            result = await avfs_write(
                ctx,
                "summaries/requester.md",
                "alpha",
                append=False,
                workspace="memory",
            )
            assert "Wrote" in result
            assert (memory_root / "summaries" / "requester.md").read_text(encoding="utf-8") == "alpha"

            await avfs_write(
                ctx,
                "summaries/requester.md",
                "\nbeta",
                append=True,
                workspace="memory",
            )
            assert await avfs_read(ctx, "summaries/requester.md", workspace="memory") == "alpha\nbeta"
        finally:
            await avfs_umount(ctx, workspace="memory")

    asyncio.run(run_test())
