# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""HTTP request handling and raw socket communication utilities."""

import socket
import ssl
from asgiref.sync import sync_to_async
import httptools

from pydantic_ai import RunContext
from rich.panel import Panel
from rich import box
from rich import print as console_printer


class Requester:
    """
    Low-level HTTP request handler with raw socket communication capabilities.
    
    This class provides methods for sending raw HTTP requests through direct
    socket connections or proxy tunnels, with support for TLS/SSL connections
    and certificate verification control.
    """
    def __init__(self, verify_ssl, proxy_url='http://localhost:8080'):
        """
        Initialize the Requester with SSL verification settings.
        
        Args:
            verify_ssl (bool): Whether to verify SSL certificates
            proxy_url (str): Proxy URL for requests (currently unused but kept for compatibility)
        """
        # Configure SSL context based on verification preference
        context = ssl.create_default_context()
        if not verify_ssl:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            context.verify_flags = ssl.VERIFY_DEFAULT
        self.ssl_context = context

    @sync_to_async
    def send_raw_data(self, host, port, target_host, request_data, is_tls=False, via_proxy=False):
        """
        Send raw HTTP request data to a target host.
        
        Validates the HTTP request format, sends it via raw socket connection,
        and displays the response in a formatted panel. Supports both direct
        connections and proxy tunneling with TLS support.
        
        Args:
            host (str): Host to connect to (proxy host if via_proxy=True)
            port (int): Port to connect to
            target_host (str): Target host for the actual request
            request_data (str): Raw HTTP request string
            is_tls (bool): Whether to use TLS encryption
            via_proxy (bool): Whether to route through a proxy
            
        Returns:
            bytes or str: Raw HTTP response or error message
        """
        bytes_request=request_data.encode('utf-8')
        # Validate the HTTP request and report issues before sending
        valid, report = analyze_http_request_text(request_data)
        if not valid:
            issues = report.get('issues', [])
            reason = "\n".join(
                [f"- {msg}" for msg in issues]) if issues else "- Unknown validation error"
            error_message = (
                "Invalid HTTP request. The following issues were found:\n"
                f"{reason}\n\n--- Raw Request ---\n{request_data}"
            )
            # console_printer.print(error_message)
            return error_message

        console_printer.print(request_data)
        response = send_raw_request(
            host=host,
            port=port,
            target_host=target_host,
            request=bytes_request,
            is_tls=is_tls,
            via_proxy=via_proxy,
            ssl_context=self.ssl_context,
        )

        # Decode and format the response for readability in a panel
        if isinstance(response, bytes):
            try:
                decoded_response = response.decode('utf-8', errors='replace')
                response_panel = Panel(
                    decoded_response,
                    title="[bold green]HTTP Response[/bold green]",
                    border_style="green",
                    box=box.ROUNDED
                )
                console_printer.print(response_panel)
            except Exception as e:
                error_panel = Panel(
                    f"[red]Error decoding response: {e}[/red]\n\n \
                    [yellow]Raw response (first 200 chars):[/yellow]\n{str(response)[:200]}",
                    title="[bold red]Decode Error[/bold red]",
                    border_style="red",
                    box=box.ROUNDED
                )
                console_printer.print(error_panel)
        else:
            response_panel = Panel(
                str(response),
                title="[bold green]HTTP Response[/bold green]",
                border_style="green",
                box=box.ROUNDED
            )
            console_printer.print(response_panel)
        return response


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


def _proxy_connect_tunnel(sock: socket.socket, target_host: str) -> bytes | None:
    """
    Establish a CONNECT tunnel through a proxy to the target host.
    
    Sends a CONNECT request to establish a tunnel through an HTTP proxy
    to the target host. Used for HTTPS requests through proxies.
    
    Args:
        sock (socket.socket): Connected socket to the proxy
        target_host (str): Target host in format "host:port"
        
    Returns:
        bytes | None: Proxy response bytes if non-200 status, None if tunnel established
    """
    def _recv_headers(s: socket.socket) -> bytes:
        chunks = []
        while True:
            data = s.recv(4096)
            if not data:
                break
            chunks.append(data)
            if b"\r\n\r\n" in b"".join(chunks):
                break
        return b"".join(chunks)

    connect_req = (
        f"CONNECT {target_host} HTTP/1.1\r\n"
        f"Host: {target_host}\r\n"
        f"Connection: keep-alive\r\n\r\n"
    ).encode("utf-8")
    sock.sendall(connect_req)
    proxy_resp = _recv_headers(sock)
    status_line = proxy_resp.split(b"\r\n", 1)[0]
    if b" 200 " not in status_line:
        return proxy_resp or b"Proxy CONNECT failed"
    return None


def _attempt_tls_handshake(sock: socket.socket, server_name: str, *, verify: bool) -> tuple[bool, bool, bool, str | None, ssl.SSLSocket | None]:
    """
    Attempt TLS handshake on a TCP socket.
    
    Performs TLS handshake with optional certificate verification.
    Detects various TLS-related errors and categorizes them appropriately.
    
    Args:
        sock (socket.socket): Connected TCP socket
        server_name (str): Server hostname for SNI
        verify (bool): Whether to verify SSL certificates
        
    Returns:
        tuple: (tls_supported, verification_ok, client_cert_required, error_message, tls_socket)
            - tls_supported: Whether TLS is supported by the server
            - verification_ok: Whether certificate verification passed
            - client_cert_required: Whether server requires client certificate
            - error_message: Error message if handshake failed
            - tls_socket: SSL socket if handshake succeeded, None otherwise
    """
    try:
        if verify:
            ctx = ssl.create_default_context()
        else:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            ctx.verify_flags = ssl.VERIFY_DEFAULT
        tls_sock = ctx.wrap_socket(sock, server_hostname=server_name, do_handshake_on_connect=True)
        return True, verify, False, None, tls_sock
    except ssl.SSLError as e:
        msg = str(e).lower()
        # Detects if TLS is speaking but cert verification failed
        if "certificate" in msg and ("verify" in msg or "self signed" in msg or "unknown ca" in msg or "hostname" in msg):
            return True, False, False, str(e), None
        # Detect client cert requirement alerts
        if "certificate required" in msg or "tlsv1 alert certificate required" in msg:
            return True, True, True, str(e), None
        # Handshake failure but likely TLS (e.g., protocol version)
        if "handshake failure" in msg or "protocol version" in msg or "wrong signature type" in msg:
            return True, False, False, str(e), None
        # Wrong version number/unknown protocol usually indicates plaintext HTTP, not TLS
        if "wrong version number" in msg or "unknown protocol" in msg or "http request" in msg:
            return False, False, False, str(e), None
        return False, False, False, str(e), None
    except Exception as e:
        return False, False, False, str(e), None


def detect_tls_support(host: str, port: int, *, via_proxy: bool, proxy_addr: tuple[str, int] | None = None, timeout: float = 5.0) -> dict:
    """
    Detect TLS support and certificate requirements for a target host.
    
    Probes the target host to determine TLS support, certificate verification
    status, and whether client certificates are required. Handles both direct
    connections and proxy-tunneled connections.
    
    Args:
        host (str): Target hostname or IP address
        port (int): Target port number
        via_proxy (bool): Whether to connect through a proxy
        proxy_addr (tuple[str, int] | None): Proxy address (host, port) if via_proxy=True
        timeout (float): Connection timeout in seconds
        
    Returns:
        dict: Detection results with keys:
            - 'is_tls': Whether TLS is supported
            - 'verification_ok': Whether certificate verification passes
            - 'client_cert_required': Whether client certificate is required
            - 'error': Error message if connection failed
    """
    # Validate inputs
    if not host or not isinstance(host, str):
        return {'is_tls': False, 'verification_ok': None, 'client_cert_required': None, 'error': f'Invalid host: {host}'}
    
    if not port or not isinstance(port, int) or port < 1 or port > 65535:
        return {'is_tls': False, 'verification_ok': None, 'client_cert_required': None, 'error': f'Invalid port: {port}'}
    
    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp.settimeout(timeout)
    
    try:
        if via_proxy:
            if not proxy_addr:
                proxy_addr = ("localhost", 8080)
            # print(f"[DEBUG] Connecting to proxy: {proxy_addr}")
            tcp.connect(proxy_addr)
            err = _proxy_connect_tunnel(tcp, f"{host}:{port}")
            if err is not None:
                return {'is_tls': False, 'verification_ok': None, 'client_cert_required': None, 'error': err.decode('utf-8', 'ignore')}
        else:
            # print(f"[DEBUG] Connecting to: {host}:{port}")
            tcp.connect((host, port))
            
    except socket.timeout:
        return {'is_tls': False, 'verification_ok': None, 'client_cert_required': None, 'error': f'Connection timeout to {host}:{port}'}
    except ConnectionRefusedError:
        return {'is_tls': False, 'verification_ok': None, 'client_cert_required': None, 'error': f'Connection refused to {host}:{port}'}
    except socket.gaierror as e:
        error_msg = f'DNS resolution failed for {host}: {str(e)}'
        if e.errno == -2:
            error_msg += f'\n   Possible causes: Invalid hostname, DNS server issues, or host not accessible'
        return {'is_tls': False, 'verification_ok': None, 'client_cert_required': None, 'error': error_msg}
    except OSError as e:
        return {'is_tls': False, 'verification_ok': None, 'client_cert_required': None, 'error': f'Network error to {host}:{port}: {str(e)}'}
    except Exception as e:
        return {'is_tls': False, 'verification_ok': None, 'client_cert_required': None, 'error': f'Unexpected error connecting to {host}:{port}: {str(e)}'}

    try:
        # First try strict verification
        is_tls, verification_ok, cert_required, err_msg, tls_sock = _attempt_tls_handshake(tcp, host, verify=True)
        if is_tls and tls_sock is not None:
            try:
                tls_sock.close()
            except Exception:
                pass
            return { 'is_tls': True, 'verification_ok': True, 'client_cert_required': False, 'error': None }

        if is_tls and not verification_ok and not cert_required:
            # retry without verification to confirm TLS works
            try:
                # need a fresh TCP connection
                tcp2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                tcp2.settimeout(timeout)
                try:
                    if via_proxy:
                        proxy = proxy_addr or ("localhost", 8080)
                        # print(f"[DEBUG] Retry connecting to proxy: {proxy}")
                        tcp2.connect(proxy)
                        err2 = _proxy_connect_tunnel(tcp2, f"{host}:{port}")
                        if err2 is not None:
                            return {'is_tls': False, 'verification_ok': None, 'client_cert_required': None, 'error': err2.decode('utf-8', 'ignore')}
                    else:
                        # print(f"[DEBUG] Retry connecting to: {host}:{port}")
                        tcp2.connect((host, port))
                except socket.timeout:
                    return {'is_tls': True, 'verification_ok': False, 'client_cert_required': False, 'error': f'Retry connection timeout to {host}:{port}'}
                except ConnectionRefusedError:
                    return {'is_tls': True, 'verification_ok': False, 'client_cert_required': False, 'error': f'Retry connection refused to {host}:{port}'}
                except socket.gaierror as e:
                    error_msg = f'Retry DNS resolution failed for {host}: {str(e)}'
                    if e.errno == -2:
                        error_msg += '\n   Possible causes: Invalid hostname, DNS server issues, or host not accessible'
                    return {'is_tls': True, 'verification_ok': False, 'client_cert_required': False, 'error': error_msg}
                except OSError as e:
                    return {'is_tls': True, 'verification_ok': False, 'client_cert_required': False, 'error': f'Retry network error to {host}:{port}: {str(e)}'}

                is_tls2, verification_ok2, cert_required2, err_msg2, tls_sock2 = _attempt_tls_handshake(tcp2, host, verify=False)
                if is_tls2 and tls_sock2 is not None:
                    try:
                        tls_sock2.close()
                    except Exception:
                        pass
                    return { 'is_tls': True, 'verification_ok': False, 'client_cert_required': False, 'error': err_msg }
                return { 'is_tls': is_tls2, 'verification_ok': False, 'client_cert_required': cert_required2, 'error': err_msg2 or err_msg }
            except Exception as e:
                return { 'is_tls': True, 'verification_ok': False, 'client_cert_required': False, 'error': str(e) }
            finally:
                try:
                    tcp2.close()
                except Exception:
                    pass

        if cert_required:
            return { 'is_tls': True, 'verification_ok': True, 'client_cert_required': True, 'error': err_msg }

        # Not TLS or unknown
        return { 'is_tls': False, 'verification_ok': None, 'client_cert_required': None, 'error': err_msg }
    finally:
        try:
            tcp.close()
        except Exception:
            pass


def send_raw_request(host, port, target_host, request, is_tls=False, via_proxy=False, ssl_context: ssl.SSLContext | None = None):
    """
    Send raw HTTP request via socket connection.
    
    Establishes a socket connection (direct or via proxy), optionally upgrades
    to TLS, sends the raw HTTP request, and returns the complete response.
    
    Args:
        host (str): Host to connect to
        port (int): Port to connect to
        target_host (str): Target host for the request
        request (bytes): Raw HTTP request bytes
        is_tls (bool): Whether to use TLS encryption
        via_proxy (bool): Whether to route through proxy
        ssl_context (ssl.SSLContext | None): SSL context for TLS connections
        
    Returns:
        bytes: Raw HTTP response or error message
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5.0)

    def _recv_all(sock: socket.socket, header_only: bool = False) -> bytes:
        chunks = []
        while True:
            try:
                data = sock.recv(4096)
                if not data:
                    break
                chunks.append(data)
                if header_only and b"\r\n\r\n" in b"".join(chunks):
                    break
            except socket.timeout:
                break
        return b"".join(chunks)

    try:
        s.connect((host, port))

        conn: socket.socket | ssl.SSLSocket = s

        # If going through a proxy with TLS target, create a CONNECT tunnel first
        if via_proxy and is_tls:
            err = _proxy_connect_tunnel(conn, target_host)
            if err is not None:
                return err
            # Upgrade to TLS over the tunnel
            if ssl_context is None:
                ssl_context = ssl.create_default_context()
            server_name = target_host.split(":")[0]
            conn = ssl_context.wrap_socket(conn, server_hostname=server_name)

        # If direct TLS (no proxy)
        elif (not via_proxy) and is_tls:
            if ssl_context is None:
                ssl_context = ssl.create_default_context()
            server_name = target_host.split(":")[0]
            conn = ssl_context.wrap_socket(conn, server_hostname=server_name)

        # Now send the raw HTTP request bytes
        conn.sendall(request)

        # Read the full response
        response_bytes = _recv_all(conn)

        try:
            conn.close()
        finally:
            if conn is not s:
                try:
                    s.close()
                except Exception:
                    pass

        return response_bytes
    except socket.error as err:
        print(f"An error has occured when sending request. :{err}".format(err))
        return f"Request not send. Please retry. The error is : {err}".encode("utf-8")

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
        ctx (RunContext[str]): Pydantic AI run context
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

async def send_payload(
    ctx: RunContext[str],
    target_host: str,
    raw_request:str,
    proxy: bool
    ) -> str | bytes:
    """
    Send HTTP payload to target host with automatic TLS detection.
    
    High-level function for sending raw HTTP requests with automatic
    TLS detection and proxy support. Parses target host, detects TLS
    capabilities, and routes through proxy if requested.
    
    Args:
        ctx (RunContext[str]): Pydantic AI run context
        target_host (str): Target host in format "host:port" or URL
        raw_request (str): Raw HTTP request string
        proxy (bool): Whether to route through localhost:8080 proxy
        
    Returns:
        str | bytes: HTTP response or error message
    """
    requester = Requester(verify_ssl=False)
    def _parse_target(th: str):
        parts = th.split(":")
        if len(parts) >= 2:
            host = ":".join(parts[:-1])
            port = parts[-1]
        else:
            host, port = th, "80"

        # Handle URLs like "http://host:port" by removing protocol prefix
        if host.startswith("http://"):
            host = host[7:] 
        elif host.startswith("https://"):
            host = host[8:]
        try:
            port_int = int(port)
        except ValueError:
            port_int = 80
        return host, port_int

    host, port = _parse_target(target_host)

    # Auto-detect TLS and certificate requirements
    detection = detect_tls_support(
        host=host,
        port=port,
        via_proxy=proxy,
        proxy_addr=("localhost", 8080) if proxy else None,
    )
    is_tls = bool(detection.get('is_tls'))

    if proxy:
        response = await requester.send_raw_data(
            host='localhost',
            port=8080,
            target_host=target_host,
            request_data=raw_request,
            is_tls=is_tls,
            via_proxy=True,
        )
    else:
        response = await requester.send_raw_data(
            host=host,
            port=port,
            target_host=target_host,
            request_data=raw_request,
            is_tls=is_tls,
            via_proxy=False,
        )
    return response
