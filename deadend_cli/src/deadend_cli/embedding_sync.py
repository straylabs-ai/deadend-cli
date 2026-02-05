"""Helpers for embedding diff handling."""

from __future__ import annotations

from typing import Any, Dict
import uuid

from deadend_agent.rag.db_cruds import RetrievalDatabaseConnector


EmbedDiff = Dict[str, Any]


def summarize_embed_diff(embed_diff: EmbedDiff | None) -> tuple[int, int]:
    """Return counts of changed and removed files from an embed diff."""
    if not embed_diff:
        return 0, 0
    changed = len(embed_diff.get("changed_files", []))
    removed = len(embed_diff.get("removed_files", []))
    return changed, removed


async def delete_stale_embeddings(
    rag_db: RetrievalDatabaseConnector | None,
    session_id: uuid.UUID,
    embed_diff: EmbedDiff | None,
) -> int:
    """Delete stale embeddings based on an embed diff.

    Returns the number of deleted rows.
    """
    if rag_db is None or not embed_diff:
        return 0
    delete_files = embed_diff.get("changed_files", []) + embed_diff.get("removed_files", [])
    if not delete_files:
        return 0
    return await rag_db.delete_code_chunks_for_files(
        session_id=session_id,
        files=delete_files,
    )
