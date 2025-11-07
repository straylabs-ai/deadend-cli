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
