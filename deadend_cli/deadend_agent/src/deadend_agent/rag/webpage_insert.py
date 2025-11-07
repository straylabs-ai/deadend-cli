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

from .database import database_connect, CodeSection, DB_SCHEMA

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



# async def build_search_db(zap_api_key: str, url: str):
#     # adding crawler call 
#     crawler = WebpageCrawler(zap_api_key) 
#     urls = await crawler.async_start_spider(url)
#     code_sections = list()
#     for url in urls:
#         async with httpx.AsyncClient() as client:
#             try:
#                 response = await client.get(url)
#                 response.raise_for_status()
#                 section_json = {
#                     'url_path': url,
#                     'title': url.split('/')[-1],
#                     'content': response.content.decode(), 
#                 }
#                 print(section_json)
#                 code_section = CodeSection(url_path=url, title=url.split('/')[-1], content=response.content.decode(), embeddings=None)
#                 code_sections.append(code_section)
#             except Exception as e:
#                 print(e)
    # openai = AsyncOpenAI()
    # # create schema
    # async with database_connect(True) as pool:
    #     async with pool.acquire() as conn:
    #         async with conn.transaction():
    #             await conn.execute(DB_SCHEMA)
    #     sem = asyncio.Semaphore(10)
    #     async with asyncio.TaskGroup() as tg:
    #         for code_section in code_sections:
    #             tg.create_task(insert_webpage(sem=sem, openai=openai, pool=pool, code_section=code_section))
    # return 1