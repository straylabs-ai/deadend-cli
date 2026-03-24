# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Protocol defining the RAG connector interface.

Both the legacy PostgreSQL ``RetrievalDatabaseConnector`` and the new
``SqliteRagConnector`` satisfy this protocol, allowing call-sites to
be backend-agnostic.
"""

from __future__ import annotations
from typing import Any, List, Dict, Optional, Protocol, runtime_checkable


@runtime_checkable
class RagConnector(Protocol):
    """Minimal interface shared by all RAG storage backends."""

    async def batch_insert_code_chunks(
        self, code_chunks_data: List[Dict[str, Any]]
    ) -> list: ...

    async def delete_code_chunks_for_files(
        self, files: List[Dict[str, str]]
    ) -> int: ...

    async def similarity_search_code_chunk(
        self,
        query_embedding: List[float],
        vector_dim: int,
        limit: int = 10,
        language: Optional[str] = None,
        similarity_threshold: Optional[float] = None,
    ) -> List[tuple]: ...

    async def close(self) -> None: ...
