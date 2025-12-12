# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Knowledge base indexing and embedding system for security research.

This module provides functionality to index, chunk, and embed knowledge base
documents, enabling semantic search over security research information,
documentation, and best practices for AI agent assistance.
"""

import os
from typing import List
from dataclasses import dataclass
from openai import BadRequestError

from deadend_agent.code_indexer.code_splitter import Chunker
from deadend_agent.models.registry import EmbedderClient
from deadend_agent.embedders.embedders import batch_embed_chunks

@dataclass
class DocumentSection:
    """Represents a section of a document with its metadata and embeddings.
    
    Attributes:
        document_path: Path to the source document file
        title: Title or name of the document section
        content: Dictionary containing the section content
        embeddings: Vector embeddings for the document content
    """
    document_path: str
    title: str
    content: dict[str, str] | None
    embeddings: List[float] | None

    def get_embedding_content(self) -> str:
        """Get content formatted for embedding generation.
        
        This method implements the Embeddable protocol by providing
        a standardized way to get embedding content.
        
        Returns:
            Formatted string suitable for embedding generation.
        """
        return '\n\n'.join([
            f"document_path: {self.document_path}",
            f"title: {self.title}",
            f"{str(self.content)}"
        ])

    async def embed_content(
            self,
            embedder_client: EmbedderClient,
            # embedding_model: str
    ):
        """Generate embeddings for the document content using OpenAI API.
        
        Args:
            embedder_client: Embedder client instance
            
        Raises:
            BadRequestError: If the API request fails
        """
        try:
            # response = await openai.embeddings.create(
            #     input=self.get_embedding_content(),
            #     model=embedding_model
            # )
            self.embeddings = embedder_client(input=self.get_embedding_content())
            # assert len(response.data) == 1, (
            #     f'Expected 1 embedding, got {len(response.data)}, file : {self.title}'
            # )
            # self.embeddings = response.data[0].embedding
        except BadRequestError as e:
            print(f"Bad request while embedding {e}")
            self.embeddings = None

class KnowledgeBaseIndexer:
    """Indexes and embeds documents from a knowledge base for vector search.
    
    This class processes markdown documents from a specified directory,
    chunks them into sections, and generates embeddings for each section
    to enable semantic search capabilities.
    """
    def __init__(
            self,
            documents_path: str,
            files_ignored: list[str]
        ) -> None:
        """Initialize the Knowledge Base Indexer.

        Args: 
            documents_path: The path to the folder containing the documents to index
            files_ignored: List of file patterns to ignore during indexing
        """
        self.documents_path = documents_path
        self.files_ignored = files_ignored

    async def serialized_embedded_documents(
        self,
        embedder_client: EmbedderClient
    ):
        """Generate serialized document sections with embeddings for database storage.
        
        Args:
            openai_api_key: OpenAI API key for embedding generation
            embedding_model: Name of the embedding model to use
            
        Returns:
            List of dictionaries containing document metadata and embeddings
        """
        db_doc_sections = []
        documents_sections = await self.embed_documents(
            embedder_client=embedder_client
        )
        for doc_section in documents_sections:
            serialized_doc = {
                "file_path": doc_section.document_path,
                "content_metadata": doc_section.title,
                "content": doc_section.content,
                "embedding": doc_section.embeddings,
            }
            db_doc_sections.append(serialized_doc)
        return db_doc_sections

    async def embed_documents(
        self,
        embedder_client: EmbedderClient
    ) -> List[DocumentSection]:
        """Process and embed all markdown documents in the knowledge base.
        
        Args:
            openai_api_key: OpenAI API key for embedding generation
            embedding_model: Name of the embedding model to use
            
        Returns:
            List of DocumentSection objects with embeddings
        """
        documents_sections = []

        for subdir, dirs, files in os.walk(self.documents_path):
            for file in files:
                if file.endswith(".md"):
                    doc_chunker = Chunker('/'.join([subdir, file]), 'markdown', False, tiktoken_model='gpt-4o-mini')
                    doc_chunks = doc_chunker.chunk_file(2000)
                    if doc_chunks is not None:
                        doc_section = await self._embed_chunks(
                            embedder_client=embedder_client,
                            document_path=self.documents_path,
                            document_title=file,
                            chunks=doc_chunks
                        )
                        documents_sections.extend(doc_section)
        return documents_sections


    async def _embed_chunks(
            self,
            embedder_client: EmbedderClient,
            document_path: str,
            document_title: str,
            chunks: List[str]
            ):
        """Process document chunks and generate embeddings using
        the generic batch embedding function.

        Args:
            embedder_client: embedder client instance
            document_path: Path to the source document
            document_title: Title of the document
            chunks: List of text chunks to embed
            
        Returns:
            List of DocumentSection objects with embeddings
        """
        if not chunks:
            return []

        # Create DocumentSection objects for all chunks
        doc_sections = []
        for chunk_idx, chunk in enumerate(chunks):
            new_chunk = " ".join(chunk.split("\n"))
            doc_section = DocumentSection(
                document_path=document_path,
                title=document_title,
                content={str(chunk_idx) : new_chunk},
                embeddings=None
            )
            doc_sections.append(doc_section)

        # Use the generic batch embedding function
        return await batch_embed_chunks(
            embedder_client=embedder_client,
            embeddable_objects=doc_sections,
            batch_name=f"{document_title} chunks"
        )
