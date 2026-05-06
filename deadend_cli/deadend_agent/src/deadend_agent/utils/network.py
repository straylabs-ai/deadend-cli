# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Network utilities for target validation and connectivity testing.

This module provides network utility functions for checking target availability,
connectivity, and response validation for security research and web application
testing workflows.
"""

import uuid
from urllib.parse import urlparse
from playwright.async_api import async_playwright


def slugify_target(target: str) -> str:
    """Convert a target URL to a filesystem-safe slug.

    Uses the same convention as ``WebResourceExtractor`` where downloaded
    resources are stored under ``{netloc.replace(':', '_')}``.

    Examples::

        >>> slugify_target("http://example.com:3000/app")
        'example.com_3000'
        >>> slugify_target("https://localhost:8080")
        'localhost_8080'
        >>> slugify_target("example.com")
        'example.com'
    """
    normalized = _normalize_target_url(target)
    parsed = urlparse(normalized)
    return parsed.netloc.replace(":", "_")


def _normalize_target_url(target: str) -> str:
    """
    Normalize target URL to ensure it has a proper protocol scheme.
    
    Args:
        target: Target URL or host:port
        
    Returns:
        Normalized URL with protocol scheme
    """
    target = target.strip()
    
    # If it already has a protocol, return as is
    if target.startswith(('http://', 'https://')):
        return target
    
    # If it looks like host:port, add http://
    if ':' in target and not target.startswith('/'):
        # Remove trailing slash if present to avoid double slashes
        if target.endswith('/'):
            target = target[:-1]
        return f"http://{target}"
    
    # If it's just a hostname, add http://
    if not target.startswith('/'):
        return f"http://{target}"
    
    # If it starts with /, assume it's a path and needs a base URL
    return f"http://localhost{target}"


def normalize_target_key(target: str) -> str:
    """
    Normalize a target into a stable key used for caching.

    The key is based on scheme + host + port (no path/query).
    """
    normalized = _normalize_target_url(target)
    parsed = urlparse(normalized)
    scheme = (parsed.scheme or "http").lower()
    netloc = parsed.netloc.lower()
    return f"{scheme}://{netloc}"


def deterministic_session_id(target: str) -> uuid.UUID:
    """Derive a stable UUID for a target to enable reuse across runs."""
    return uuid.uuid5(uuid.NAMESPACE_URL, normalize_target_key(target))
