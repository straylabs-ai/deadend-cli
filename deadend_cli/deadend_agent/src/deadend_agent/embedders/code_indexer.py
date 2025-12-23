# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Source code indexing and embedding system for code analysis.

This module provides functionality to index, chunk, and embed source code
from web applications, enabling semantic search and analysis of codebases
for security research and vulnerability identification.
"""

import os
import re
import uuid
from uuid import uuid4
from pathlib import Path
from typing import List

from deadend_agent.rag.database import CodeSection
from deadend_agent.tools.web_resource_extractor import WebResourceExtractor
from deadend_agent.code_indexer.code_splitter import Chunker
from deadend_agent.embedders.embedders import batch_embed_chunks
from deadend_agent.models.registry import EmbedderClient

class SourceCodeIndexer:
    """
    The SourceCodeIndexer Object indexes a webpage source code 
    to be then able to extract the relevant information that 
    could be found inside the source code. 
    
    As it is related to webpages, the languages that will be 
    added to the tree sitter are : 
    - HTML and Javascript 
    """
    def __init__(self, target: str, session_id: uuid.UUID | None = None) -> None:
        """
        Initializes the SourceCodeIndexer object.
        
        Args:
            target (str): The URL of the web application to index.
            session_id (str, optional): Session ID for this indexing session. 
            If None, generates a new one.
        
        This constructor sets up the cache directory for storing crawled data and
        initializes the WebpageCrawler instance for crawling the target website.
        """
        self.target = target
        self.session_id = session_id if session_id else uuid4()
        self._add_session_to_cache()
        self._add_chunk_directory()
        self._load_patterns()
        self.crawler = WebResourceExtractor()
        self.url_data = {}


    async def crawl_target(self):
        """
        Crawl the target website and extract all web resources.
        
        This method uses the WebResourceExtractor to crawl the target URL,
        downloading HTML, JavaScript, CSS, and other web resources to the
        session-specific cache directory.
        
        Returns:
            dict: Dictionary containing information about extracted resources
        """
        self.resources = await self.crawler.extract_all_resources(
            url=self.target,
            wait_time=10,
            screenshot=False,
            download_resources=True,
            download_path=str(self.source_code_path)
        )
        return self.resources

    def _add_session_to_cache(self):
        """
        Create cache directory structure for the current session.
        
        Sets up the cache directory under ~/.cache/deadend/webpages/ and
        creates a session-specific subdirectory for storing downloaded resources.
        """
        home_dir = Path.home()
        self.cache_path = home_dir.joinpath('.cache/deadend/webpages/')
        if not os.path.exists(self.cache_path):
            Path(self.cache_path).mkdir(parents=True, exist_ok=True)

        self.source_code_path = self.cache_path.joinpath(str(self.session_id))
        Path(self.source_code_path).mkdir(parents=True, exist_ok=True)

    def _add_chunk_directory(self):
        """
        Create directory for storing code chunks.
        
        Sets up a _chunks subdirectory within the session cache directory
        for storing processed code chunks during the embedding process.
        """
        self.chunk_folder = "_chunks"
        self.chunk_path = self.source_code_path.joinpath(self.chunk_folder)
        self.chunk_path.mkdir(parents=True, exist_ok=True)

    async def serialized_embedded_code(self, embedder_client: EmbedderClient):
        """
        Generate serialized embedded code chunks for database storage.
        
        Processes all webpage code through embedding and returns a list of
        dictionaries containing session metadata, file paths, language info,
        code content, and embeddings for database persistence.
        
        Args:
            openai_api_key (str): OpenAI API key for embedding generation
            embedding_model (str): Name of the embedding model to use
            
        Returns:
            List[dict]: List of code chunk dictionaries ready for database storage
        """
        code_sections = await self.embed_webpage(
            embedder_client=embedder_client
        )
        code_chunks = []
        for code_section in code_sections:
            chunk = {
                    "session_id": self.session_id,
                    "file_path": code_section.url_path, 
                    "language": code_section.title, 
                    "code_content": str(code_section.content), 
                    "embedding": code_section.embeddings
                }
            code_chunks.append(chunk)
        return code_chunks
    async def embed_webpage(self, embedder_client: EmbedderClient) -> List[CodeSection]:
        """
        Process and embed all JavaScript and HTML files from the crawled webpage.
        
        Walks through the session directory, identifies JavaScript (.js, .jsx) and
        HTML files, chunks them into manageable pieces, and generates embeddings
        using the specified OpenAI model. Vendor-specific files are filtered out.
        
        Args:
            openai_api_key (str): OpenAI API key for embedding generation
            embedding_model (str): Name of the embedding model to use
            
        Returns:
            List[CodeSection]: List of embedded code sections ready for RAG queries
        """
        files_ignored = []
        code_sections = []

        for subdir, dirs, files in os.walk(self.source_code_path):
            for file in files:
                if not self.is_file_vendor_specific(file):
                    if file.endswith(".js") or file.endswith(".jsx"):
                        code_chunker = Chunker(
                            '/'.join([subdir, file]),
                            'javascript',
                            True,
                            tiktoken_model='gpt-4o-mini'
                        )
                        file_chunks = code_chunker.chunk_file(2000)
                        url_path = subdir.replace(str(self.source_code_path), "")
                        if file_chunks is not None:
                            new_cs = await self._embed_chunks(
                                embedding_client=embedder_client,
                                url_path=url_path,
                                title=file,
                                chunks=file_chunks
                            )
                            if new_cs is not None:
                                code_sections.extend(new_cs)

                    elif file.endswith("html"):
                        code_chunker = Chunker(
                            '/'.join([subdir, file]),
                            'html',
                            True,
                            tiktoken_model='gpt-4o-mini'
                        )
                        file_chunks = code_chunker.chunk_file(2000)
                        url_path = subdir.replace(str(self.source_code_path), "")
                        if file_chunks is not None:
                            new_cs = await self._embed_chunks(
                                embedding_client=embedder_client,
                                url_path=url_path,
                                title=file,
                                chunks=file_chunks
                            )
                            if new_cs is not None:
                                code_sections.extend(new_cs)
                    else:
                        files_ignored.append(file)
        return code_sections

    async def _embed_chunks(
        self,
        embedding_client: EmbedderClient,
        url_path: str,
        title: str,
        chunks: List[str]
    ) -> List[CodeSection]:
        """
        Generate embeddings for a list of code chunks using the generic batch embedding function.
        
        Takes raw code chunks, normalizes whitespace, creates CodeSection objects,
        and generates embeddings using the optimized batch embedding utility.
        
        Args:
            embedding_client : Configured embedder client instance
            embedding_model (str): Name of the embedding model to use
            url_path (str): URL path where the file was found
            title (str): Filename or title for the code section
            chunks (List[str]): List of code chunks to embed
            
        Returns:
            List[CodeSection]: List of successfully embedded code sections
        """
        if not chunks:
            return []

        # Create CodeSection objects for all chunks
        code_sections = []
        for chunk_number, chunk in enumerate(chunks):
            new_chunk = " ".join(chunk.split("\n"))
            code_section = CodeSection(
                url_path=url_path,
                title=title,
                content={chunk_number : new_chunk},
                embeddings=None
            )
            code_sections.append(code_section)

        # Use the generic batch embedding function
        return await batch_embed_chunks(
            embedder_client=embedding_client,
            embeddable_objects=code_sections,
            batch_name=f"{title} chunks"
        )

    def _load_patterns(self):
        """
        Load vendor-specific file patterns for filtering.
        
        Reads the vendor_specific_files.json file to load patterns used for
        identifying and filtering out vendor-specific files (like jQuery, Bootstrap)
        that should not be indexed for security analysis.
        """
        import json
        import importlib.resources

        # Get the path to the data file within the package
        data_file = importlib.resources.files('deadend_agent').joinpath('data/vendor_specific_files.json')

        with open(data_file, encoding="utf-8") as f:
            patterns_json = f.read()

        self.forbidden_patterns = json.loads(patterns_json)

    def is_file_vendor_specific(self, filename: str):
        """
        Check if a filename matches vendor-specific patterns.
        
        Uses regex patterns loaded from vendor_specific_files.json to determine
        if a file should be excluded from indexing because it's a known vendor
        library (jQuery, Bootstrap, etc.) rather than application-specific code.
        
        Args:
            filename (str): The filename to check
            
        Returns:
            bool: True if the file matches vendor patterns and should be excluded
        """
        common_patterns = self.forbidden_patterns["generic"]
        triggered_patterns = []
        for pattern in common_patterns:
            res = re.search(pattern=pattern, string=filename)
            if res != None:
                triggered_patterns.append(res.group())
        if len(triggered_patterns)>0:
            return True 
        else:
            return False