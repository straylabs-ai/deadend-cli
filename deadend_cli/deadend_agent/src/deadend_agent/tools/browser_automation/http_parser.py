# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

from urllib.parse import urlparse
from typing import Tuple
import httptools

from pydantic_ai import RunContext


def is_valid_request(ctx: RunContext[str], raw_request: str) -> bool:
    """
    Check if raw HTTP request string is valid.
    
    Simple boolean validation check for backwards compatibility.
    Use is_valid_request_detailed() for comprehensive validation report.
    
    Args:
        ctx (RunContext[str]): Pydantic AI run context
        raw_request (str): Raw HTTP request string to validate
        
    Returns:
        bool: True if request is valid, False otherwise
    """
    valid, _report = analyze_http_request_text(raw_request)
    return bool(valid)


def is_valid_request_detailed(ctx: RunContext[str], raw_request: str) -> dict:
    """
    Generate detailed validation report for HTTP request.
    
    Provides comprehensive validation including parsed components,
    identified issues, and structured metadata about the request.
    
    Args:
        ctx (RunContext[str]): run context
        raw_request (str): Raw HTTP request string to validate
        
    Returns:
        dict: Detailed validation report with keys:
            - 'is_valid': Boolean validity status
            - 'issues': List of validation issues found
            - 'method': HTTP method (if parseable)
            - 'url': Request URL path (if parseable)
            - 'headers': Parsed headers dictionary
            - 'raw_request': Original request string
    """
    valid, report = analyze_http_request_text(raw_request)
    return {
        'is_valid': bool(valid),
        'issues': report.get('issues', []),
        'method': report.get('method'),
        'url': report.get('url'),
        'headers': report.get('headers', {}),
        'raw_request': raw_request,
    }


def parse_http_request(raw_data):
    """
    Parse raw HTTP request data into structured components.
    
    Uses httptools to parse HTTP request bytes into URL, headers, body,
    and method components. Validates the request structure and completeness.
    
    Args:
        raw_data (bytes): Raw HTTP request bytes
        
    Returns:
        RequestParser or None: Parsed request object if valid, None if invalid
    """
    class RequestParser:
        """
        Internal parser class for HTTP request components.
        
        Handles parsing of HTTP request components including URL, headers,
        body, and completion status using httptools callbacks.
        """
        def __init__(self):
            """Initialize empty parser state."""
            self.url = None
            self.headers = {}
            self.body = b''
            self.complete = False
            self.method = None

        def on_url(self, url):
            """Callback for URL parsing."""
            self.url = url.decode('utf-8')

        def on_header(self, name, value):
            """Callback for header parsing."""
            self.headers[name.decode('utf-8').lower()] = value.decode('utf-8')

        def on_body(self, body):
            """Callback for body parsing."""
            self.body += body

        def on_message_complete(self):
            """Callback for request completion."""
            self.complete = True

    def _is_valid_request(parser):
        """
        Validate parsed HTTP request structure.
        
        Checks if the parsed request has required components like URL path,
        Host header, and proper Content-Length/Transfer-Encoding usage.
        Validates that POST/PUT/PATCH methods have appropriate body content.
        
        Args:
            parser (RequestParser): Parsed request object to validate
            
        Returns:
            bool: True if request is valid, False otherwise
        """

        if not parser.url or not parser.url.startswith('/'):
            return False

        required_headers = ["host"]
        for header in required_headers:
            if header not in parser.headers:
                return False

        # if 'content-length' in parser.headers:
        #     try:
        #         content_length = int(parser.headers['content-length'])
        #         if content_length < 0:
        #             return False
        #         if len(parser.body) != content_length:
        #             return False
        #     except ValueError:
        #         return False

        if 'content-length' in parser.headers and 'transfer-encoding' in parser.headers:
            if 'chunked' in parser.headers['transfer-encoding']:
                return False  # Can't have both Content-Length and chunked encoding

        method = parser.method if hasattr(parser, 'method') else None
        if method in ['POST', 'PUT', 'PATCH']:
            # These methods should have content-type for body data
            if not parser.body and len(parser.body)==0:
                return False
        return True

    try:
        request_parser = RequestParser()
        parser = httptools.HttpRequestParser(request_parser)
        parser.feed_data(raw_data)
        if not request_parser.complete:
            return None
        # capture method name if available
        try:
            method_bytes = parser.get_method()
            if method_bytes is not None:
                request_parser.method = method_bytes.decode('utf-8')
        except Exception:
            pass
        if not _is_valid_request(request_parser):
            return None
        return request_parser
    except httptools.HttpParserError:
        # print("HTTPParserError : Malformed HTTP request.")
        return None



def analyze_http_request_text(raw_request_text: str) -> tuple[bool, dict]:
    """
    Analyze a raw HTTP request string and return (is_valid, report_dict).
    report_dict contains: {'issues': [str], 'method': str|None, 'url': str|None, 'headers': dict}
    """
    issues: list[str] = []
    method: str | None = None
    url: str | None = None
    headers: dict[str, str] = {}
    body = b""

    if not raw_request_text or raw_request_text.strip() == "":
        return False, { 'issues': ["Empty request"], 'method': None, 'url': None, 'headers': {} }

    try:
        raw_bytes = raw_request_text.encode('utf-8')
    except Exception:
        return False, { 'issues': ["Request is not UTF-8 encodable"], 'method': None, 'url': None, 'headers': {} }

    parsed = parse_http_request(raw_bytes)
    if parsed is None:
        issues.append("Malformed HTTP request: could not parse line/headers/body correctly")
        return False, { 'issues': issues, 'method': None, 'url': None, 'headers': {} }

    method = getattr(parsed, 'method', None)
    url = getattr(parsed, 'url', None)
    headers = getattr(parsed, 'headers', {}) or {}
    body = getattr(parsed, 'body', b"") or b""

    if not url or not url.startswith('/'):
        issues.append("Request line contains invalid or missing path (URL must start with '/')")

    if 'host' not in headers:
        issues.append("Missing required 'Host' header")

    if 'content-length' in headers and 'transfer-encoding' in headers and 'chunked' in headers.get('transfer-encoding', '').lower():
        issues.append("Both Content-Length and Transfer-Encoding: chunked present (invalid)")

    if method in ['POST', 'PUT', 'PATCH']:
        # If body is empty, warn; not always invalid but usually a mistake
        if len(body) == 0:
            issues.append(f"Method {method} usually carries a body but none was provided")

    return (len(issues) == 0), { 'issues': issues, 'method': method, 'url': url, 'headers': headers }

def extract_host_port(target_host: str) -> Tuple[str, int]:
    """Extract host and port from a URL string using urllib.parse.urlparse"""
    if target_host.startswith("http://"):
        default_port = 80
    elif target_host.startswith("https://"):
        default_port = 443
    else:
        default_port = 80

    parts = target_host.split(":")
    if len(parts) >= 2:
        try:
            port_int = int(parts[-1])
            host = ":".join(parts[:-1])
            return host, port_int
        except ValueError:
            host = target_host
            return host, default_port
    else:
        host = target_host
        return host, default_port


import re


def autocorrect_http_request(
    raw_request: str,
    target_host: str | None = None,
) -> tuple[str, list[str]]:
    """
    Auto-correct common HTTP request malformations.

    Args:
        raw_request: The raw HTTP request string (potentially malformed)
        target_host: Optional target host to derive Host header if missing

    Returns:
        tuple[str, list[str]]: (corrected_request, list_of_corrections_made)

    Raises:
        ValueError: If request is empty or cannot be corrected
    """
    corrections: list[str] = []

    if not raw_request or raw_request.strip() == "":
        raise ValueError("Empty request cannot be auto-corrected")

    # Step 1: Fix line endings (\n -> \r\n)
    corrected, line_ending_fixed = _fix_line_endings(raw_request)
    if line_ending_fixed:
        corrections.append("Fixed line endings: \\n -> \\r\\n")

    # Step 2: Split into lines for processing
    lines = corrected.split('\r\n')

    # Step 3: Fix request line
    if not lines:
        raise ValueError("No request line found")

    request_line = lines[0]
    fixed_request_line, request_line_corrections = _fix_request_line(request_line)
    corrections.extend(request_line_corrections)
    lines[0] = fixed_request_line

    # Step 4: Parse and fix headers
    header_end_idx = None
    headers: dict[str, str] = {}
    fixed_header_lines: list[str] = []

    for i, line in enumerate(lines[1:], start=1):
        if line == '':
            header_end_idx = i
            break
        if ':' in line:
            fixed_line, header_fixed = _fix_header_format(line)
            if header_fixed:
                corrections.append(f"Fixed header format: '{line}' -> '{fixed_line}'")
            fixed_header_lines.append(fixed_line)
            # Parse header into dict
            key, value = fixed_line.split(':', 1)
            headers[key.strip().lower()] = value.strip()
        elif line.strip():
            # Line without colon - might be continuation or malformed
            corrections.append(f"Removed malformed header line: '{line}'")

    # Step 5: Add missing Host header
    if 'host' not in headers and target_host:
        host_value = _derive_host_from_target(target_host)
        headers['host'] = host_value
        fixed_header_lines.insert(0, f"Host: {host_value}")
        corrections.append(f"Added missing Host header: {host_value}")

    # Step 6: Extract body (everything after blank line)
    body = ''
    if header_end_idx is not None and header_end_idx + 1 < len(lines):
        body = '\r\n'.join(lines[header_end_idx + 1:])
    elif header_end_idx is None:
        # No blank line found - everything after headers might be body
        if len(lines) > 1 + len(fixed_header_lines):
            remaining = lines[1 + len(fixed_header_lines):]
            if remaining and any(r.strip() for r in remaining):
                body = '\r\n'.join(remaining)
                corrections.append("Fixed missing header-body separator")

    # Step 7: Reconstruct the request
    corrected_request = _reconstruct_request(
        request_line=fixed_request_line,
        headers=fixed_header_lines,
        body=body
    )

    return corrected_request, corrections


def _fix_line_endings(raw_request: str) -> tuple[str, bool]:
    """
    Convert Unix line endings (\\n) to HTTP-compliant CRLF (\\r\\n).
    Also handles old Mac-style (\\r only) line endings.

    Returns:
        tuple[str, bool]: (corrected_string, was_fixed)
    """
    # Check if already using proper CRLF
    if '\r\n' in raw_request and '\n' not in raw_request.replace('\r\n', ''):
        return raw_request, False

    # First, normalize any existing \r\n to a placeholder
    temp = raw_request.replace('\r\n', '\x00CRLF\x00')
    # Convert standalone \r (old Mac) to \n
    temp = temp.replace('\r', '\n')
    # Convert all \n to \r\n
    temp = temp.replace('\n', '\r\n')
    # Restore original \r\n
    corrected = temp.replace('\x00CRLF\x00', '\r\n')

    return corrected, corrected != raw_request


def _fix_request_line(request_line: str) -> tuple[str, list[str]]:
    """
    Fix malformed request line to 'METHOD /path HTTP/1.1' format.

    Returns:
        tuple[str, list[str]]: (fixed_line, list_of_corrections)
    """
    corrections: list[str] = []
    parts = request_line.split()

    if len(parts) == 0:
        # Empty request line - default to GET /
        return "GET / HTTP/1.1", ["Added default request line: GET / HTTP/1.1"]

    method = parts[0]
    path = '/'
    version = 'HTTP/1.1'

    # Fix lowercase method
    if method != method.upper():
        corrections.append(f"Uppercased method: {method} -> {method.upper()}")
        method = method.upper()

    # Validate method (basic check for common HTTP methods)
    valid_methods = {'GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS', 'TRACE', 'CONNECT'}
    if method not in valid_methods:
        # Try to recover - might be path without method
        original_first_part = parts[0]  # Keep original case for path
        if original_first_part.startswith('/'):
            corrections.append(f"Added missing method: GET (path was: {original_first_part})")
            path = original_first_part
            method = 'GET'
            if len(parts) > 1:
                version = parts[1] if parts[1].startswith('HTTP/') else 'HTTP/1.1'
        # else keep it as-is, might be a custom method

    if len(parts) >= 2:
        # Check if second part is path or version
        if parts[1].startswith('HTTP/'):
            # No path, only version
            corrections.append(f"Added missing path: /")
            version = parts[1]
        elif parts[1].startswith('/') or not parts[1].startswith('HTTP'):
            path = parts[1]

    if len(parts) >= 3:
        if parts[2].startswith('HTTP/'):
            version = parts[2]
        else:
            corrections.append(f"Fixed HTTP version: {parts[2]} -> HTTP/1.1")
    elif len(parts) < 3:
        corrections.append("Added missing HTTP version: HTTP/1.1")

    # Validate and fix HTTP version format
    if not re.match(r'^HTTP/\d\.\d$', version):
        corrections.append(f"Fixed invalid HTTP version: {version} -> HTTP/1.1")
        version = 'HTTP/1.1'

    return f"{method} {path} {version}", corrections


def _fix_header_format(header_line: str) -> tuple[str, bool]:
    """
    Fix malformed header lines.

    Returns:
        tuple[str, bool]: (fixed_line, was_fixed)
    """
    if ':' not in header_line:
        return header_line, False

    # Split on first colon
    key, value = header_line.split(':', 1)

    # Trim whitespace from key and value
    original_key = key
    original_value = value
    key = key.strip()
    value = value.strip()

    # Check if there was extra whitespace
    was_fixed = key != original_key or value != original_value.lstrip()

    return f"{key}: {value}", was_fixed


def _derive_host_from_target(target_host: str) -> str:
    """
    Derive Host header value from target_host URL.

    Args:
        target_host: URL like "http://example.com:8080" or "example.com"

    Returns:
        str: Host header value (e.g., "example.com:8080" or "example.com")
    """
    # Remove protocol
    host = target_host
    if '://' in host:
        host = host.split('://', 1)[1]

    # Remove path
    if '/' in host:
        host = host.split('/', 1)[0]

    return host


def _reconstruct_request(
    request_line: str,
    headers: list[str],
    body: str
) -> str:
    """
    Reconstruct a properly formatted HTTP request.

    Args:
        request_line: The HTTP request line (e.g., "GET / HTTP/1.1")
        headers: List of header lines (e.g., ["Host: example.com", "Content-Type: text/html"])
        body: Request body content

    Returns:
        str: Properly formatted HTTP request with CRLF line endings
    """
    parts = [request_line]
    parts.extend(headers)

    # Join parts and add the header-body separator
    result = '\r\n'.join(parts) + '\r\n\r\n'

    if body:
        result += body

    return result
