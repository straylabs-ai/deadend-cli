# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Grep tool for searching patterns in session log files.

This module provides functionality to search for regular expression patterns
in session log files (requester.jsonl and python_interpreter.jsonl) stored
in the cache directory.
"""
import re
from pathlib import Path
from typing import List, Dict, Any
from pydantic_ai import RunContext


async def grep_session_logs(
    ctx: RunContext[str],
    pattern: str
) -> str:
    """Search for a regular expression pattern in session log files.

    Searches for the given regex pattern in both requester.jsonl and
    python_interpreter.jsonl files in the session directory. Returns
    all matches with file context, line numbers, and matched content.

    This function handles errors gracefully, returning informative messages
    instead of raising exceptions to allow the agent to continue execution.

    Args:
        ctx: RunContext containing the session_key as deps
        pattern: Regular expression pattern to search for

    Returns:
        str: Formatted string containing all matches with file context,
             line numbers, and matched content. Returns informative message
             if no matches found, files don't exist, or an error occurs.
    """
    # Handle missing session_key gracefully
    if not ctx.deps or not isinstance(ctx.deps, str):
        return (
            "No session_key provided in context. "
            "Cannot search session logs without a valid session identifier. "
            "Ensure the agent is run with a session context."
        )

    session_key = ctx.deps

    # Validate regex pattern
    try:
        compiled_pattern = re.compile(pattern)
    except re.error as e:
        return (
            f"Invalid regular expression pattern '{pattern}': {e}\n"
            "Please provide a valid regex pattern. Examples:\n"
            "- 'FLAG\\{.*?\\}' to find flags\n"
            "- 'error|exception' to find errors\n"
            "- '\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}' to find IP addresses"
        )

    # Build session directory path
    session_dir = (
        Path.home()
        / ".cache"
        / "deadend"
        / "memory"
        / "sessions"
        / session_key
    )

    # Check if session directory exists
    if not session_dir.exists():
        return (
            f"Session directory not found for session_key '{session_key}'.\n"
            f"Expected path: {session_dir}\n"
            "This session may not have any logged activity yet. "
            "Run some tools first to generate session logs."
        )

    # Files to search
    files_to_search = [
        ("requester.jsonl", session_dir / "requester.jsonl"),
        ("python_interpreter.jsonl", session_dir / "python_interpreter.jsonl"),
        ("shell.jsonl", session_dir / "shell.jsonl"),  # Also check shell logs
    ]

    matches: List[Dict[str, Any]] = []
    files_checked = 0
    files_found = 0

    # Search in each file if it exists
    for file_name, file_path in files_to_search:
        files_checked += 1
        if not file_path.exists():
            continue

        files_found += 1
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, start=1):
                    # Search for pattern in the line
                    line_matches = compiled_pattern.finditer(line)
                    for match in line_matches:
                        matches.append({
                            "file": file_name,
                            "line": line_num,
                            "match": match.group(0),
                            "start": match.start(),
                            "end": match.end(),
                            "context": line.strip()[:200]  # First 200 chars of line
                        })
        except (IOError, OSError) as e:
            # Log error but continue with other files
            matches.append({
                "file": file_name,
                "line": 0,
                "match": f"[ERROR] Could not read file: {str(e)}",
                "start": 0,
                "end": 0,
                "context": ""
            })
        except UnicodeDecodeError as e:
            # Handle encoding issues
            matches.append({
                "file": file_name,
                "line": 0,
                "match": f"[ERROR] Encoding error reading file: {str(e)}",
                "start": 0,
                "end": 0,
                "context": ""
            })

    # Format results
    if files_found == 0:
        return (
            f"No log files found in session '{session_key}'.\n"
            f"Checked for: {', '.join(f[0] for f in files_to_search)}\n"
            "Session logs are created when tools are executed. "
            "Try running some requester or shell commands first."
        )

    if not matches:
        return (
            f"No matches found for pattern '{pattern}' in session logs.\n"
            f"Searched {files_found} file(s) in session '{session_key}'.\n"
            "Try a broader pattern or check if the expected content exists."
        )

    total_matches = len(matches)
    # Only keep the last 10 matches to avoid overwhelming output
    last_matches = matches[-10:]

    header = (
        f"Found {total_matches} match(es) for pattern '{pattern}' "
        f"in session '{session_key}'. "
        f"Showing the last {len(last_matches)} match(es):\n"
    )
    result_lines = [header]

    for match in last_matches:
        result_lines.append(
            f"[{match['file']}:{match['line']}] "
            f"Match: '{match['match']}' "
            f"(position {match['start']}-{match['end']})"
        )
        if match['context']:
            result_lines.append(f"  Context: {match['context']}")
        result_lines.append("")

    return "\n".join(result_lines)

