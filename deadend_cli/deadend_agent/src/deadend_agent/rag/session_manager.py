# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Session-scoped RAG database manager.

Manages the directory layout::

    {storage_root}/
    └── {agent_id}/
        └── {deterministic_session_id}/
            ├── {target_slug}.db       # code chunks + vectors
            ├── .manifest.json         # embedding change tracker
            └── ...

Each ``(agent_id, session_id)`` pair gets its own SQLite database file,
eliminating the need for a shared PostgreSQL instance.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from deadend_agent.logging import get_module_logger
from deadend_agent.utils.network import slugify_target

from .blob import BlobBackend
from .sqlite_connector import SqliteRagConnector

logger = get_module_logger(__name__)


class RagSessionManager:
    """Creates and caches per-session ``SqliteRagConnector`` instances."""

    def __init__(
        self,
        storage_root: Path,
        blob_backend: BlobBackend | None = None,
    ) -> None:
        self._root = storage_root
        self._blob = blob_backend
        self._open: dict[str, SqliteRagConnector] = {}

    def session_dir(
        self, agent_id: UUID | str, embedding_session_id: UUID | str
    ) -> Path:
        return self._root / str(agent_id) / str(embedding_session_id)

    async def get_connector(
        self,
        agent_id: UUID | str,
        embedding_session_id: UUID | str,
        target: str,
    ) -> SqliteRagConnector:
        """Return (and cache) a connector for a specific session.

        Creates the directory layout and downloads from blob storage
        if available and the local file doesn't exist yet.
        """
        cache_key = f"{agent_id}/{embedding_session_id}"
        if cache_key in self._open:
            return self._open[cache_key]

        session_dir = self.session_dir(agent_id, embedding_session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        db_path = session_dir / f"{slugify_target(target)}.db"

        # SDK mode: pull from blob storage if not present locally
        if not db_path.exists() and self._blob:
            blob_key = f"agents/{agent_id}/{embedding_session_id}/{db_path.name}"
            try:
                if await self._blob.exists(blob_key):
                    await self._blob.download(key=blob_key, dest=db_path)
            except Exception:
                logger.warning(
                    "Failed to download session db from blob storage: %s",
                    blob_key,
                )

        connector = SqliteRagConnector(db_path)
        await connector.initialize_database()
        self._open[cache_key] = connector
        logger.info("Opened RAG session db: %s", db_path)
        return connector


    async def upload_session(
        self,
        agent_id: UUID | str,
        embedding_session_id: UUID | str,
        target: str,
    ) -> None:
        """Push the session ``.db`` to blob storage after embedding."""
        if not self._blob:
            return
        session_dir = self.session_dir(agent_id, embedding_session_id)
        db_path = session_dir / f"{slugify_target(target)}.db"
        if db_path.exists():
            blob_key = f"agents/{agent_id}/{embedding_session_id}/{db_path.name}"
            await self._blob.upload(src=db_path, key=blob_key)

    async def close_all(self) -> None:
        """Dispose all open connectors."""
        for connector in self._open.values():
            await connector.close()
        self._open.clear()
