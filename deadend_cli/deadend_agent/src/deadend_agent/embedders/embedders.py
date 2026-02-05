# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Generic embedding utilities for batch processing.

This module provides reusable functions for efficient batch embedding generation
using OpenAI's API, with fallback to parallel individual calls for robustness.
"""

from typing import List, TypeVar, Protocol
import asyncio

import tiktoken
from deadend_agent.models.registry import EmbedderClient

# Generic type for objects that can be embedded
T = TypeVar('T', bound='Embeddable')

class Embeddable(Protocol):
    """Protocol for objects that can be embedded.
    
    Objects implementing this protocol must have:
    - embeddings: List[float] | None attribute
    - A method to get embedding content as string
    """
    embeddings: List[float] | None
    
    def get_embedding_content(self) -> str:
        """Return the content to be embedded as a string."""
        ...

async def batch_embed_chunks(
    embedder_client: EmbedderClient,
    embeddable_objects: List[T],
    batch_name: str = "chunks",
    max_batch_tokens: int = 250_000,
) -> List[T]:
    """Generate embeddings for a list of embeddable objects using batch API calls.
    
    This function optimizes embedding generation by:
    1. First attempting a single batch API call for all objects
    2. Falling back to parallel individual calls if batch fails
    
    Args:
        embedder_client: Embedding client instance
        embedding_model: Name of the embedding model to use
        embeddable_objects: List of objects implementing the Embeddable protocol
        batch_name: Name for logging purposes (e.g., "file chunks", "documents")
        
    Returns:
        List of successfully embedded objects (with embeddings populated)
    """
    if not embeddable_objects:
        return []
    encoder = _get_token_encoder(getattr(embedder_client, "model", None))

    results: List[T] = []
    batch_texts: List[str] = []
    batch_objs: List[T] = []
    batch_tokens = 0
    batch_index = 1

    async def flush_batch() -> None:
        nonlocal batch_texts, batch_objs, batch_tokens, batch_index, results
        if not batch_objs:
            return
        label = f"{batch_name} batch {batch_index}"
        try:
            response = await embedder_client.batch_embed(input=batch_texts)
            for i, embedding_data in enumerate(response):
                if i < len(batch_objs):
                    batch_objs[i].embeddings = embedding_data["embedding"]
            results.extend(batch_objs)
        except Exception as e:
            print(f"Batch embedding failed for {label}, falling back to single calls: {e}")
            for obj, text in zip(batch_objs, batch_texts):
                try:
                    single_response = await embedder_client.batch_embed(input=[text])
                    if single_response and len(single_response) > 0:
                        obj.embeddings = single_response[0]["embedding"]
                        results.append(obj)
                except Exception as single_e:
                    print(f"Failed to embed individual chunk: {single_e}")
        batch_texts = []
        batch_objs = []
        batch_tokens = 0
        batch_index += 1

    for obj in embeddable_objects:
        text = obj.get_embedding_content()
        tokens = len(encoder.encode(text))
        if tokens > max_batch_tokens:
            print(
                f"Warning: single {batch_name} item exceeds max tokens "
                f"({tokens} > {max_batch_tokens}). Truncating."
            )
            text = encoder.decode(encoder.encode(text)[:max_batch_tokens])
            tokens = max_batch_tokens

        if batch_objs and (batch_tokens + tokens > max_batch_tokens):
            await flush_batch()

        batch_texts.append(text)
        batch_objs.append(obj)
        batch_tokens += tokens

    await flush_batch()

    return [obj for obj in results if obj.embeddings is not None]


def _get_token_encoder(model_name: str | None):
    try:
        if model_name:
            return tiktoken.encoding_for_model(model_name)
    except Exception:
        pass
    return tiktoken.get_encoding("cl100k_base")
