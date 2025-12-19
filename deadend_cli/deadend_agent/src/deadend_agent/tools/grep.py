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
    
    Args:
        ctx: RunContext containing the session_key as deps
        pattern: Regular expression pattern to search for
        
    Returns:
        str: Formatted string containing all matches with file context,
             line numbers, and matched content. Returns empty string if
             no matches found or files don't exist.
             
    Raises:
        ValueError: If session_key is not provided in context or pattern
                   is invalid regex
    """
    if not ctx.deps or not isinstance(ctx.deps, str):
        raise ValueError("session_key is required in context deps to search session logs.")
    
    session_key = ctx.deps
    
    # Validate regex pattern
    try:
        compiled_pattern = re.compile(pattern)
    except re.error as e:
        raise ValueError(f"Invalid regular expression pattern: {e}") from e
    
    # Build session directory path
    session_dir = (
        Path.home()
        / ".cache"
        / "deadend"
        / "memory"
        / "sessions"
        / session_key
    )
    
    # Files to search
    files_to_search = [
        ("requester.jsonl", session_dir / "requester.jsonl"),
        ("python_interpreter.jsonl", session_dir / "python_interpreter.jsonl")
    ]
    
    matches: List[Dict[str, Any]] = []
    
    # Search in each file if it exists
    for file_name, file_path in files_to_search:
        if not file_path.exists():
            continue
            
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
        except (IOError, OSError, UnicodeDecodeError) as e:
            # Continue with other files if one fails
            matches.append({
                "file": file_name,
                "line": 0,
                "match": f"ERROR: Could not read file - {str(e)}",
                "start": 0,
                "end": 0,
                "context": ""
            })
    
    # Format results
    if not matches:
        return f"No matches found for pattern '{pattern}' in session logs for session_key: {session_key}"

    total_matches = len(matches)
    # Only keep the last 10 matches to avoid overwhelming output
    last_matches = matches[-10:]

    header = (
        f"Found {total_matches} match(es) for pattern '{pattern}'. "
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

