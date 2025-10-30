# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Memory management system for AI agent conversations and context.

This module provides memory management functionality for storing and
retrieving conversation history, context, and session data for AI agents
in the security research framework.
"""
import json
from pathlib import Path
from mem0 import MemoryClient


class MemoryHandler:
    memory: MemoryClient

    def __init__(self, session, target):
        self.session = session
        self.messages = []
        self.target = target
        self.base_cache = Path.home() / ".cache" / "deadend" / "memory" / "sessions" / self.session
        self.base_cache.mkdir(parents=True, exist_ok=True)


    def setup_memory_for_session(self, api_key: str):
        self.memory = MemoryClient(api_key=api_key)

    def add_agent_conversations(self, messages):
        self.memory.add(messages=messages, target_id=self.target)

    def save_tool_results(self, tool_name: str, **kwargs):
        cache_tool = self.base_cache / "tool_name"
        cache_tool.mkdir(parents=True, exist_ok=True)
        log_path = cache_tool / f"{tool_name}.jsonl"
        record = {}
        for key, value in kwargs:
            record[key] = value

        with open(log_path, 'a', encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
