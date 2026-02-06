# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Web application code retrieval-augmented generation (RAG) tool.

This module provides a tool for performing semantic search over indexed
web application source code, enabling AI agents to retrieve relevant
code snippets and documentation for security analysis and research.
"""
from typing import Union
from pydantic_ai import RunContext
from deadend_agent.utils.structures import RagDeps, WebappreconDeps, RequesterDeps

async def webapp_analyzer(
        context: RunContext[Union[RagDeps, WebappreconDeps, RequesterDeps]],
        search_query: str
    ) -> str:
    """Web application static analyzer using RAG for semantic code retrieval.

    This tool performs static analysis on web applications by leveraging
    Retrieval-Augmented Generation (RAG) to semantically search through
    indexed source code. It enables AI agents to fetch relevant code snippets
    based on natural-language queries, facilitating security analysis and
    vulnerability research.

    Args:
        context: Execution context providing dependencies such as RAG client,
            embeddings API, and target metadata.
        search_query: Natural-language prompt describing the desired code or
            functionality to analyze.

    Returns:
        Aggregated code chunks concatenated as a plain-text string, containing
        the most semantically relevant code snippets matching the query.
    """
    res = ""
    if len(context.deps.target) > 1:
        search_query += '\n The target supplied is: ' + context.deps.target

    embedding = await context.deps.embedder_client.batch_embed(
        input_texts=[search_query],
    )

    assert len(embedding) == 1, (
        f'Expected 1 embedding, got {len(embedding)}, doc query: {search_query!r}'
    )
    embedding = embedding[0]['embedding']

    session_id = getattr(context.deps, "embedding_session_id", None) or context.deps.session_id
    results = await context.deps.rag.similarity_search_code_chunk(
        query_embedding=embedding,
        session_id=session_id,
        limit=5
    )
    for chunk, similarity in results:
        res = res + '\n' + chunk.code_content

    return res
