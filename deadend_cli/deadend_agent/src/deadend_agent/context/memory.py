# # Copyright (C) 2025 Yassine Bargach
# # Licensed under the GNU Affero General Public License v3
# # See LICENSE file for full license information.

# """Memory management system for AI agent conversations and context.

# This module provides memory management functionality for storing and
# retrieving conversation history, context, and session data for AI agents
# in the security research framework.
# """
# import json
# from pathlib import Path
# from attr import filters
# from mem0 import MemoryClient


# class MemoryHandler:
#     """Manages memory storage and retrieval for AI agent conversations and context.

#     This class handles both persistent storage (via mem0 MemoryClient) and local
#     file-based caching of agent conversations, tool results, and session data.

#     Attributes:
#         memory: MemoryClient instance for persistent memory storage.
#         session: Session identifier for the current execution session.
#         messages: List of messages in the current conversation.
#         target: Target identifier for memory operations.
#         base_cache: Path to the base cache directory for this session.
#     """
#     memory: MemoryClient

#     def __init__(self, session, target):
#         """Initialize the MemoryHandler for a given session and target.

#         Args:
#             session: Unique session identifier for this execution session.
#             target: Target identifier used for grouping related memories.
#         """
#         self.session = session
#         self.messages = []
#         self.target = target
#         self.base_cache = Path.home() / ".cache" / "deadend" / "memory" / "sessions" / str(self.session)
#         self.base_cache.mkdir(parents=True, exist_ok=True)

#     def setup_memory_for_session(self, api_key: str):
#         """Initialize the MemoryClient with the provided API key.

#         Args:
#             api_key: API key for authenticating with the mem0 memory service.
#         """
#         self.memory = MemoryClient(api_key=api_key)

#     def add_agent_conversations(self, messages):
#         """Add agent conversation messages to persistent memory storage.

#         Args:
#             messages: List of message objects or dictionaries to store in memory.
#                 Messages are associated with the current target ID.
#         """
#         self.memory.add(messages=messages, target_id=self.target)

#     def save_tool_results(self, tool_name: str, **kwargs):
#         """Save tool execution results to a local JSONL cache file.

#         Creates a directory structure for the tool and appends results to a
#         JSONL file for later retrieval and analysis.

#         Args:
#             tool_name: Name of the tool whose results are being saved.
#             **kwargs: Additional keyword arguments representing tool-specific
#                 result data to be saved.
#         """
#         tool_cache = self.base_cache / f"{tool_name}"
#         tool_cache.mkdir(parents=True, exist_ok=True)
#         log_path = tool_cache / f"{tool_name}.jsonl"
#         record = {}
#         for key, value in kwargs.items():
#             record[key] = value

#         with open(log_path, 'a', encoding="utf-8") as f:
#             f.write(json.dumps(record, ensure_ascii=False) + "\n")

#     def add_agent_result_to_memory(self, agent_name: str, **kwargs):
#         """Add agent execution results to both persistent memory and local cache.

#         Stores agent results in two locations:
#         1. Persistent memory via MemoryClient (for retrieval by AI)
#         2. Local JSONL file cache (for debugging and analysis)

#         Args:
#             agent_name: Name of the agent whose results are being stored.
#             **kwargs: Additional keyword arguments representing agent-specific
#                 result data to be stored.
#         """
#         records = {}
#         records["agent_name"] = agent_name
#         for key, value in kwargs.items():
#             records[key] = value
#         self.memory.add(messages=records, target_id=self.target)
#         agent_cache = self.base_cache / f"{agent_name}"
#         agent_cache.mkdir(parents=True, exist_ok=True)
#         log_path = agent_cache / f"{agent_name}.jsonl"
#         with open(log_path, 'a', encoding="utf-8") as f:
#             f.write(json.dumps(records, ensure_ascii=False) + "\n")

#     def search(self, query: str):
#         """Search in memory
#         Searches query in memory corresponding to the target in place.
#         """
#         result = self.memory.search(query=query, filters={"target_id": self.target})
#         return result
