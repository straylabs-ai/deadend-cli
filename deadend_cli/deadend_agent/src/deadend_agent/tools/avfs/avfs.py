from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import threading


@dataclass(frozen=True)
class _AVFSState:
    """Mounted filesystem view for one session."""

    root: Path
    cwd: PurePosixPath


class AVFS:
    """Session-scoped virtual filesystem rooted in a host workspace directory."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._global_states: dict[str, _AVFSState] = {}
        self._session_states: dict[str, dict[str, _AVFSState]] = {}

    def mount(
        self,
        workspace_root: str | Path,
        *,
        directory: str = ".",
        session_id: str | None = None,
        workspace: str = "workspace",
    ) -> Path:
        """Register a host workspace directory and initialize the virtual working directory."""
        root = Path(workspace_root).expanduser().resolve()
        if not root.exists():
            raise FileNotFoundError(f"Workspace root does not exist: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"Workspace root is not a directory: {root}")

        cwd = self._normalize_virtual_path(directory)
        cwd_path = self._host_path_from_virtual(root, cwd)
        if not cwd_path.exists():
            raise FileNotFoundError(f"Initial AVFS directory does not exist: {self.format_virtual_path(cwd)}")
        if not cwd_path.is_dir():
            raise NotADirectoryError(f"Initial AVFS directory is not a directory: {self.format_virtual_path(cwd)}")

        state = _AVFSState(root=root, cwd=cwd)
        with self._lock:
            if session_id:
                self._session_states.setdefault(session_id, {})[workspace] = state
            else:
                self._global_states[workspace] = state
        return root

    def umount(self, session_id: str | None = None, *, workspace: str = "workspace") -> None:
        """Unmount a session workspace or the global workspace."""
        with self._lock:
            if session_id:
                states = self._session_states.get(session_id)
                if states is None:
                    return
                states.pop(workspace, None)
                if not states:
                    self._session_states.pop(session_id, None)
            else:
                self._global_states.pop(workspace, None)

    def current_mount(self, session_id: str | None = None, *, workspace: str = "workspace") -> Path | None:
        """Backward-compatible alias for the active workspace root."""
        return self.current_workspace_root(session_id=session_id, workspace=workspace)

    def current_workspace_root(self, session_id: str | None = None, *, workspace: str = "workspace") -> Path | None:
        """Return the active workspace root for a session."""
        state = self._current_state(session_id=session_id, workspace=workspace)
        return None if state is None else state.root

    def current_directory(self, session_id: str | None = None, *, workspace: str = "workspace") -> str:
        """Return the current virtual working directory."""
        state = self._require_state(session_id=session_id, workspace=workspace)
        return self.format_virtual_path(state.cwd)

    def chdir(self, path: str, session_id: str | None = None, *, workspace: str = "workspace") -> str:
        """Change the virtual working directory for a mounted session."""
        with self._lock:
            state = self._require_state(session_id=session_id, workspace=workspace)
            target = self._resolve_virtual_path(path, cwd=state.cwd)
            target_path = self._host_path_from_virtual(state.root, target)
            if not target_path.exists():
                raise FileNotFoundError(f"Directory does not exist: {self.format_virtual_path(target)}")
            if not target_path.is_dir():
                raise NotADirectoryError(f"Path is not a directory: {self.format_virtual_path(target)}")

            next_state = _AVFSState(root=state.root, cwd=target)
            if session_id:
                self._session_states.setdefault(session_id, {})[workspace] = next_state
            else:
                self._global_states[workspace] = next_state
        return self.format_virtual_path(target)

    def resolve_virtual_path(
        self,
        path: str = ".",
        *,
        session_id: str | None = None,
        workspace: str = "workspace",
    ) -> PurePosixPath:
        """Resolve a user path inside the mounted virtual namespace."""
        state = self._require_state(session_id=session_id, workspace=workspace)
        return self._resolve_virtual_path(path, cwd=state.cwd)

    def resolve(self, path: str = ".", session_id: str | None = None, *, workspace: str = "workspace") -> Path:
        """Resolve a path inside the workspace root using virtual cwd semantics."""
        state = self._require_state(session_id=session_id, workspace=workspace)
        virtual_path = self._resolve_virtual_path(path, cwd=state.cwd)
        return self._host_path_from_virtual(state.root, virtual_path)

    def to_virtual_path(
        self,
        host_path: str | Path,
        session_id: str | None = None,
        *,
        workspace: str = "workspace",
    ) -> PurePosixPath:
        """Convert a resolved host path back into a virtual path."""
        state = self._require_state(session_id=session_id, workspace=workspace)
        resolved = Path(host_path).resolve(strict=False)
        try:
            relative = resolved.relative_to(state.root)
        except ValueError as exc:
            raise ValueError(f"Path is outside workspace root: {host_path}") from exc
        return PurePosixPath(*relative.parts) if relative.parts else PurePosixPath(".")

    @staticmethod
    def format_virtual_path(path: PurePosixPath) -> str:
        """Render a virtual path with a stable root-relative representation."""
        return "/" if path == PurePosixPath(".") else f"/{path.as_posix()}"

    def _current_state(self, session_id: str | None = None, *, workspace: str = "workspace") -> _AVFSState | None:
        with self._lock:
            if session_id and session_id in self._session_states:
                return self._session_states[session_id].get(workspace)
            return self._global_states.get(workspace)

    def _require_state(self, session_id: str | None = None, *, workspace: str = "workspace") -> _AVFSState:
        state = self._current_state(session_id=session_id, workspace=workspace)
        if state is None:
            raise RuntimeError(f"AVFS workspace '{workspace}' is not mounted. Call avfs_mount first.")
        return state

    def _resolve_virtual_path(self, path: str, *, cwd: PurePosixPath) -> PurePosixPath:
        requested = path or "."
        requested_path = PurePosixPath(requested)
        if requested_path.is_absolute():
            return self._normalize_virtual_path(requested)
        return self._normalize_virtual_path(str(cwd / requested_path))

    def _normalize_virtual_path(self, path: str) -> PurePosixPath:
        pure_path = PurePosixPath(path or ".")
        parts = pure_path.parts[1:] if pure_path.is_absolute() else pure_path.parts

        normalized_parts: list[str] = []
        for part in parts:
            if part in ("", "."):
                continue
            if part == "..":
                if not normalized_parts:
                    raise ValueError(f"Path escapes workspace root: {path}")
                normalized_parts.pop()
                continue
            normalized_parts.append(part)

        return PurePosixPath(*normalized_parts) if normalized_parts else PurePosixPath(".")

    def _host_path_from_virtual(self, root: Path, virtual_path: PurePosixPath) -> Path:
        candidate = root if virtual_path == PurePosixPath(".") else root.joinpath(*virtual_path.parts)
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Path escapes workspace root: {self.format_virtual_path(virtual_path)}") from exc
        return resolved


avfs = AVFS()
