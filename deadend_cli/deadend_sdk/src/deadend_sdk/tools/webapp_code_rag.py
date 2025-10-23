# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Web application code retrieval-augmented generation (RAG) tool.

This module provides a tool for performing semantic search over indexed
web application source code, enabling AI agents to retrieve relevant
code snippets and documentation for security analysis and research.
"""

from pydantic_ai import RunContext
from deadend_sdk.utils.structures import RagDeps, WebappreconDeps
from typing import Union

async def webapp_code_rag(
        context: RunContext[Union[RagDeps, WebappreconDeps]],
        search_query: str
    ) -> str:
    res = ""
    if len(context.deps.target) > 1:
        search_query += '\n The target supplied is: ' + context.deps.target

    embedding = await context.deps.openai.embeddings.create(
        input=search_query, 
        model='text-embedding-3-small'
    ) 

    assert len(embedding.data) == 1, (
        f'Expected 1 embedding, got {len(embedding.data)}, doc query: {search_query!r}'
    )
    embedding = embedding.data[0].embedding

    results = await context.deps.rag.similarity_search_code_chunk(
        query_embedding=embedding, 
        session_id=context.deps.session_id,
        limit=5
    )
    for chunk, similarity in results: 
        res = res + '\n' + chunk.code_content
    
    return res