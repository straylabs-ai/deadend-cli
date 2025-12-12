# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Web page insertion and processing for the RAG system.

This module provides functionality to insert and process web page content
into the RAG database, including content extraction, embedding generation,
and storage for semantic search capabilities in security research.
"""

import asyncio
import asyncpg
import httpx
import pydantic_core
from pydantic import TypeAdapter
from openai import AsyncOpenAI

from .database import CodeSection

section_ta = TypeAdapter(CodeSection)

async def insert_webpage(
        sem: asyncio.Semaphore,
        openai: AsyncOpenAI,
        pool: asyncpg.Pool,
        code_section: CodeSection
) -> None:
    async with sem:
        exists = await pool.fetchval('SELECT 1 FROM code_sections WHERE url=$1', code_section.url_path)
        if exists:
            print("code source already in db.")
            return 
        
        # creating embeddings 
        embedding = await openai.embeddings.create(
            input=code_section._embedding_content(),
            model="text-embedding-3-small",
        )

        assert len(embedding.data) == 1, (
            f'Expected 1 embedding, got {len(embedding.data)}, doc section: {code_section}'
        )
        embedding = embedding.data[0].embedding
        embedding_json = pydantic_core.to_json(embedding).decode()
        await pool.execute(
            'INSERT INTO doc_sections (url, title, content, embedding) VALUES ($1, $2, $3, $4)',
            code_section.url_path,
            code_section.title,
            code_section.content,
            embedding_json,
        )
