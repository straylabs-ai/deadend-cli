# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""RLM-oriented file memory primitives.

This module implements the first layer needed for RLM-style memory:
long-lived memory remains outside the prompt as files on disk, and the
agent gets structure-aware operations to inspect that memory selectively.

The current implementation focuses on the memory substrate itself:
- markdown files are indexed by headings
- JSON files are navigated by path
- JSONL files are exposed as arrays of JSON objects
- callers can build prompt metadata without reading the full corpus
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from pathlib import Path
from typing import Any, Iterable


MARKDOWN_EXTENSIONS = {".md", ".markdown"}
JSON_EXTENSIONS = {".json"}
JSONL_EXTENSIONS = {".jsonl"}
TEXT_EXTENSIONS = {".txt", ".log"}
SUPPORTED_EXTENSIONS = MARKDOWN_EXTENSIONS | JSON_EXTENSIONS | JSONL_EXTENSIONS | TEXT_EXTENSIONS


@dataclass(frozen=True)
class MemoryFileMetadata:
    """Metadata for a memory file."""

    path: str
    absolute_path: str
    file_type: str
    size_bytes: int
    line_count: int
    section_count: int = 0


@dataclass(frozen=True)
class MarkdownSection:
    """Indexed markdown section."""

    section_id: str
    heading: str
    level: int
    start_line: int
    end_line: int
    char_start: int
    char_end: int
    content: str


@dataclass(frozen=True)
class MemorySearchResult:
    """Structured grep-like match."""

    path: str
    line_number: int
    match: str
    context: str


class RLMFileMemory:
    """Structure-aware external memory for long markdown and JSON corpora."""

    def __init__(self, root: str | Path, files: Iterable[str | Path] | None = None) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._files: dict[str, Path] = {}

        selected_files = files if files is not None else self._discover_files()
        for file_path in selected_files:
            path = Path(file_path).expanduser().resolve()
            if not path.exists() or not path.is_file():
                continue
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            key = self._normalize_key(path)
            self._files[key] = path

    def _discover_files(self) -> list[Path]:
        discovered: list[Path] = []
        for path in self.root.rglob("*"):
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                discovered.append(path.resolve())
        return sorted(discovered)

    def _normalize_key(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return path.name

    def _resolve_file(self, path: str) -> Path:
        candidate = self._files.get(path)
        if candidate:
            return candidate

        fallback = (self.root / path).resolve()
        if fallback.exists() and fallback.is_file():
            return fallback

        raise FileNotFoundError(f"Memory file not found: {path}")

    def _read_text(self, path: str) -> str:
        file_path = self._resolve_file(path)
        return file_path.read_text(encoding="utf-8")

    def list_files(self, file_type: str | None = None) -> list[MemoryFileMetadata]:
        """Return indexed files with lightweight metadata."""
        items: list[MemoryFileMetadata] = []
        for key, path in sorted(self._files.items()):
            kind = self._detect_file_type(path)
            if file_type and kind != file_type:
                continue
            text = path.read_text(encoding="utf-8")
            section_count = len(self._split_markdown_sections(text)) if kind == "markdown" else 0
            items.append(
                MemoryFileMetadata(
                    path=key,
                    absolute_path=str(path),
                    file_type=kind,
                    size_bytes=len(text.encode("utf-8")),
                    line_count=text.count("\n") + (1 if text else 0),
                    section_count=section_count,
                )
            )
        return items

    def get_file_metadata(self, path: str) -> MemoryFileMetadata:
        """Return metadata for one file."""
        matches = self.list_files()
        for metadata in matches:
            if metadata.path == path:
                return metadata
        raise FileNotFoundError(f"Memory file not found: {path}")

    def grep_memory(
        self,
        pattern: str,
        path: str | None = None,
        max_results: int = 50,
    ) -> list[MemorySearchResult]:
        """Search memory files with a regex pattern."""
        compiled = re.compile(pattern, re.MULTILINE)
        targets = [path] if path else [metadata.path for metadata in self.list_files()]
        results: list[MemorySearchResult] = []

        for target in targets:
            text = self._read_text(target)
            for line_number, line in enumerate(text.splitlines(), start=1):
                match = compiled.search(line)
                if not match:
                    continue
                results.append(
                    MemorySearchResult(
                        path=target,
                        line_number=line_number,
                        match=match.group(0),
                        context=line[:240],
                    )
                )
                if len(results) >= max_results:
                    return results
        return results

    def read_chars(self, path: str, start: int = 0, end: int | None = None) -> str:
        """Read a character slice from a file."""
        text = self._read_text(path)
        return text[start:end]

    def read_lines(self, path: str, start: int = 1, end: int | None = None) -> str:
        """Read a line slice from a file using 1-based indexing."""
        lines = self._read_text(path).splitlines()
        start_index = max(0, start - 1)
        end_index = len(lines) if end is None else max(start_index, end)
        return "\n".join(lines[start_index:end_index])

    def list_md_sections(self, path: str) -> list[MarkdownSection]:
        """Return markdown sections indexed by heading."""
        file_path = self._resolve_file(path)
        if file_path.suffix.lower() not in MARKDOWN_EXTENSIONS:
            raise ValueError(f"Not a markdown file: {path}")
        return self._split_markdown_sections(self._read_text(path))

    def read_md_section(self, path: str, heading_or_id: str) -> str:
        """Read a markdown section by heading text or section id."""
        for section in self.list_md_sections(path):
            if section.section_id == heading_or_id or section.heading == heading_or_id:
                return section.content
        raise KeyError(f"Markdown section not found: {heading_or_id}")

    def read_md_outline(self, path: str) -> list[dict[str, Any]]:
        """Return a condensed outline for a markdown file."""
        return [
            {
                "section_id": section.section_id,
                "heading": section.heading,
                "level": section.level,
                "start_line": section.start_line,
                "end_line": section.end_line,
            }
            for section in self.list_md_sections(path)
        ]

    def search_md_headings(self, query: str) -> list[dict[str, Any]]:
        """Search markdown headings across indexed files."""
        query_lower = query.lower()
        matches: list[dict[str, Any]] = []
        for metadata in self.list_files(file_type="markdown"):
            for section in self.list_md_sections(metadata.path):
                if query_lower in section.heading.lower():
                    matches.append(
                        {
                            "path": metadata.path,
                            "section_id": section.section_id,
                            "heading": section.heading,
                            "level": section.level,
                        }
                    )
        return matches

    def json_keys(self, path: str, json_path: str | None = None) -> list[str]:
        """List keys available at a JSON path."""
        node = self._resolve_json_node(path, json_path)
        if isinstance(node, dict):
            return list(node.keys())
        if isinstance(node, list):
            return [str(index) for index in range(len(node))]
        return []

    def json_get(self, path: str, json_path: str | None = None) -> Any:
        """Read a JSON value at a path."""
        return self._resolve_json_node(path, json_path)

    def json_search(
        self,
        path: str,
        key: str | None = None,
        value_contains: str | None = None,
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        """Search a JSON structure recursively."""
        data = self._load_json_payload(path)
        results: list[dict[str, Any]] = []
        needle = value_contains.lower() if value_contains else None

        def walk(node: Any, current_path: str) -> None:
            if len(results) >= max_results:
                return
            if isinstance(node, dict):
                for child_key, child_value in node.items():
                    child_path = f"{current_path}.{child_key}" if current_path else child_key
                    key_match = key is None or child_key == key
                    value_match = (
                        needle is None
                        or (isinstance(child_value, (str, int, float, bool)) and needle in str(child_value).lower())
                    )
                    if key_match and value_match:
                        results.append({"path": child_path, "key": child_key, "value": child_value})
                    walk(child_value, child_path)
            elif isinstance(node, list):
                for index, child_value in enumerate(node):
                    child_path = f"{current_path}[{index}]" if current_path else f"[{index}]"
                    if needle is not None and isinstance(child_value, (str, int, float, bool)):
                        if needle in str(child_value).lower():
                            results.append({"path": child_path, "key": None, "value": child_value})
                    walk(child_value, child_path)

        walk(data, "")
        return results[:max_results]

    def json_sample_array(self, path: str, json_path: str, start: int = 0, end: int = 10) -> list[Any]:
        """Return a slice from a JSON array."""
        node = self._resolve_json_node(path, json_path)
        if not isinstance(node, list):
            raise ValueError(f"JSON path does not resolve to an array: {json_path}")
        return node[start:end]

    def json_schema(self, path: str, json_path: str | None = None, max_depth: int = 5) -> Any:
        """Return a lightweight structural schema for a JSON value."""
        node = self._resolve_json_node(path, json_path)
        return self._infer_schema(node, depth=0, max_depth=max_depth)

    def describe_context(self) -> dict[str, Any]:
        """Return prompt-friendly metadata for the external memory corpus."""
        files = self.list_files()
        return {
            "context_type": "RLMFileMemory",
            "context_total_length": sum(item.size_bytes for item in files),
            "context_lengths": [item.size_bytes for item in files],
            "files": [
                {
                    "path": item.path,
                    "file_type": item.file_type,
                    "size_bytes": item.size_bytes,
                    "line_count": item.line_count,
                    "section_count": item.section_count,
                }
                for item in files
            ],
        }

    def build_navigation_context(self) -> str:
        """Return a compact index that an LLM can inspect before reading content."""
        description = self.describe_context()
        lines = [
            f"context_type={description['context_type']}",
            f"context_total_length={description['context_total_length']}",
            "files:",
        ]
        for item in description["files"]:
            lines.append(
                f"- {item['path']} [{item['file_type']}] "
                f"size={item['size_bytes']} lines={item['line_count']} sections={item['section_count']}"
            )
        return "\n".join(lines)

    def _detect_file_type(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in MARKDOWN_EXTENSIONS:
            return "markdown"
        if suffix in JSON_EXTENSIONS:
            return "json"
        if suffix in JSONL_EXTENSIONS:
            return "jsonl"
        return "text"

    def _split_markdown_sections(self, text: str) -> list[MarkdownSection]:
        if not text:
            return []

        lines = text.splitlines()
        sections: list[MarkdownSection] = []
        heading_pattern = re.compile(r"^(#{1,6})\s+(.*)$")
        current_heading = "ROOT"
        current_level = 0
        current_start_line = 1
        current_lines: list[str] = []

        def flush(end_line: int) -> None:
            if not current_lines and current_heading == "ROOT":
                return
            content = "\n".join(current_lines).strip()
            char_start = len("\n".join(lines[: current_start_line - 1]))
            if current_start_line > 1:
                char_start += 1
            char_end = char_start + len(content)
            sections.append(
                MarkdownSection(
                    section_id=self._slugify_heading(current_heading, len(sections) + 1),
                    heading=current_heading,
                    level=current_level,
                    start_line=current_start_line,
                    end_line=end_line,
                    char_start=char_start,
                    char_end=char_end,
                    content=content,
                )
            )

        for line_number, line in enumerate(lines, start=1):
            match = heading_pattern.match(line)
            if match:
                flush(line_number - 1)
                current_heading = match.group(2).strip()
                current_level = len(match.group(1))
                current_start_line = line_number
                current_lines = [line]
                continue

            current_lines.append(line)

        flush(len(lines))
        return sections

    def _slugify_heading(self, heading: str, index: int) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")
        return slug or f"section-{index}"

    def _load_json_payload(self, path: str) -> Any:
        file_path = self._resolve_file(path)
        text = file_path.read_text(encoding="utf-8")
        if file_path.suffix.lower() in JSONL_EXTENSIONS:
            return [json.loads(line) for line in text.splitlines() if line.strip()]
        return json.loads(text)

    def _resolve_json_node(self, path: str, json_path: str | None) -> Any:
        node = self._load_json_payload(path)
        if not json_path or json_path in {".", "$"}:
            return node

        segments = self._parse_json_path(json_path)
        for segment in segments:
            if isinstance(segment, int):
                if not isinstance(node, list):
                    raise KeyError(f"Expected list while resolving index {segment} in {json_path}")
                node = node[segment]
                continue
            if not isinstance(node, dict):
                raise KeyError(f"Expected object while resolving key '{segment}' in {json_path}")
            node = node[segment]
        return node

    def _parse_json_path(self, json_path: str) -> list[str | int]:
        normalized = json_path.strip()
        if normalized.startswith("$"):
            normalized = normalized[1:]
        normalized = normalized.lstrip(".")

        if not normalized:
            return []

        segments: list[str | int] = []
        token = ""
        index_token = ""
        in_index = False

        for char in normalized:
            if char == "." and not in_index:
                if token:
                    segments.append(token)
                    token = ""
                continue
            if char == "[":
                if token:
                    segments.append(token)
                    token = ""
                in_index = True
                index_token = ""
                continue
            if char == "]" and in_index:
                segments.append(int(index_token))
                index_token = ""
                in_index = False
                continue
            if in_index:
                index_token += char
            else:
                token += char

        if token:
            segments.append(token)

        return segments

    def _infer_schema(self, node: Any, depth: int, max_depth: int) -> Any:
        if depth >= max_depth:
            return {"type": type(node).__name__}
        if isinstance(node, dict):
            return {
                "type": "object",
                "properties": {
                    key: self._infer_schema(value, depth + 1, max_depth)
                    for key, value in node.items()
                },
            }
        if isinstance(node, list):
            item_schema = self._infer_schema(node[0], depth + 1, max_depth) if node else {"type": "unknown"}
            return {
                "type": "array",
                "length": len(node),
                "items": item_schema,
            }
        if node is None:
            return {"type": "null"}
        return {"type": type(node).__name__}
