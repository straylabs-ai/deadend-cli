import json
import re
from typing import AsyncGenerator, Dict, Union, Any, List
from urllib.parse import urlparse, parse_qs
from anyio import Path
from playwright.async_api import APIRequestContext, async_playwright
from playwright._impl._api_structures import OriginState
from .http_parser import analyze_http_request_text


class HTTPRequestParseError(Exception):
    """Exception raised when HTTP request parsing fails.
    
    Attributes:
        message: Human-readable error message describing the parsing failure.
        error_type: Type of error that occurred (ValueError, IndexError, AttributeError).
        raw_request: The raw request string that failed to parse.
        context: Additional context about where parsing failed.
    """
    def __init__(self, message: str, error_type: str, raw_request: str, context: str = ""):
        self.message = message
        self.error_type = error_type
        self.raw_request = raw_request
        self.context = context
        super().__init__(self.message)
    
    def __str__(self) -> str:
        context_info = f" ({self.context})" if self.context else ""
        return f"{self.message}{context_info}"


class PlaywrightRequester:
    """
    Enhanced HTTP request handler using Playwright with headless browser.
    
    This class provides the same functionality as the raw socket Requester
    but with additional capabilities including automatic redirect handling,
    session management, cookie persistence, and improved error handling.
    """

    def __init__(
        self,
        verify_ssl: bool = True,
        proxy_url: str | None = None,
        session_id: str | None = None
    ):
        """
        Initialize the PlaywrightRequester.
        
        Args:
            verify_ssl (bool): Whether to verify SSL certificates
            proxy_url (str, optional): Proxy URL for requests
        """
        self.verify_ssl = verify_ssl
        self.proxy_url = proxy_url
        self.playwright = None
        self.browser = None
        self.context = None
        self.request_context: APIRequestContext | None = None
        self._initialized = False
        self.session_id = session_id
        # Fix: Add persistent page for localStorage operations
        self._persistent_page = None

    async def __aenter__(self):
        """Async context manager entry."""
        await self._initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self._cleanup()

    async def _initialize(self):
        """Initialize Playwright browser and context."""
        if self._initialized:
            return

        self.playwright = await async_playwright().start()

        # Configure browser launch options
        browser_options = {
            'headless': True,
                'args': [
                    '--disable-web-security', # Disable web security for cross-origin access
                    '--disable-features=VizDisplayCompositor',  # Disable some security features
                    '--allow-running-insecure-content', # Allow insecure content
                    '--disable-blink-features=AutomationControlled',  # Hide automation
                    '--no-sandbox',
                    '--disable-dev-shm-usage', 
                ]
        }
        self.browser = await self.playwright.chromium.launch(**browser_options)
        
        # Load existing storage state (including cookies) if session_id is provided
        storage_path = None
        if self.session_id:
            try:
                storage_path = await self._get_storage_path(self.session_id)
                # Check if storage file exists to load cookies
                storage_file = Path(storage_path)
                if not await storage_file.exists():
                    storage_path = None  # Don't use non-existent file
            except Exception as e:
                print(f"Warning: Could not prepare storage path: {e}")
                storage_path = None

        # Configure browser context options
        context_options = {
            'ignore_https_errors': not self.verify_ssl,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        }

        if self.proxy_url:
            context_options['proxy'] = {'server': self.proxy_url}
        
        # Load storage state (cookies + localStorage) if it exists
        if storage_path:
            try:
                context_options['storage_state'] = storage_path
            except Exception as e:
                print(f"Warning: Could not load storage state: {e}")

        self.context = await self.browser.new_context(**context_options)
        # Create request context from browser context - this automatically uses cookies
        # from the context. Cookies are loaded via storage_state option above.
        self.request_context = self.context.request
        self._initialized = True
        
        # Verify cookies are loaded (for debugging)
        if self.session_id and storage_path:
            try:
                cookies = await self.context.cookies()
                if cookies:
                    print(f"Loaded {len(cookies)} cookies from storage for session {self.session_id}")
            except Exception as e:
                print(f"Warning: Could not verify loaded cookies: {e}")

    async def _get_storage_path(self, session_id: str) -> str:
        """
        Get the storage file path for a given session_id.
        
        Args:
            session_id: Session identifier
            
        Returns:
            str: Path to storage.json file
        """
        path_storage = await Path.home() / ".cache" / "deadend" / "memory" / "sessions" / session_id
        await path_storage.mkdir(parents=True, exist_ok=True)
        storage_file = path_storage / "storage.json"
        # print(f"the storage file is : {storage_file}")
        return str(storage_file)

    async def _get_persistent_page(self, domain: str | None = None):
        """
        Get or create a persistent page for localStorage operations.
        
        Fix: Use a persistent page instead of creating new pages for each operation.
        """
        if not self._persistent_page:
            self._persistent_page = await self.context.new_page()

        if domain:
            # Fix: Use https consistently for all localStorage operations
            if not domain.startswith(('http://', 'https://')):
                domain = f"http://{domain}"

            # Navigate to domain if not already there
            current_url = self._persistent_page.url
            if not current_url.startswith(domain):
                try:
                    await self._persistent_page.goto(domain)
                except Exception as e:
                    print(f"Warning: Could not navigate to {domain}: {e}")
                    return None

        return self._persistent_page

    def _escape_js_string(self, value: str) -> str:
        """
        Properly escape a string for JavaScript evaluation.
        
        Fix: Escape special characters to prevent JavaScript syntax errors.
        """
        # Use JSON.stringify for proper escaping
        return json.dumps(value)

    async def _inject_auth_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        """Inject authentication headers if found in localstorage"""
        enhanced_headers = headers.copy()
        try:
            auth_token = await self.get_localstorage_value('auth_token')
            if auth_token:
                enhanced_headers["Authorization"] = f"Bearer {auth_token}"
            api_key = await self.get_localstorage_value('api_key')
            if api_key:
                enhanced_headers["X-API-Key"] = api_key
        except Exception as e:
            print(f"Warning: Could not inject auth headers from localStorage: {e}")
        return enhanced_headers

    def _inject_auth_headers_with_storage(self,storage, headers: Dict[str, str]) -> Dict[str, str]:
        """Inject authentication headers if found in localstorage"""
        enhanced_headers = headers.copy()

        try:
            for item in storage.get("localStorage", []):
                if item.get("name") == "auth_token" and item.get("value"):
                    enhanced_headers["Authorization"] = f"Bearer {item['value']}"
                elif item.get("name") == "api_key" and item.get("value"):
                    enhanced_headers["X-API-Key"] = item["value"]
        except Exception as e:
            print(f"Warning: Could not inject auth headers from localStorage: {e}")
        return enhanced_headers

    async def _cleanup(self):
        """Clean up Playwright resources."""
        if self._persistent_page:
            await self._persistent_page.close()
            self._persistent_page = None
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        self._initialized = False

    async def send_raw_data(self, host: str, port: int, target_host: str,
                          request_data: str, is_tls: bool = False,
                          via_proxy: bool = False) -> AsyncGenerator[Union[str, bytes], None]:
        """
        Send raw HTTP request data to a target host.
        
        This method provides the same interface as the original Requester.send_raw_data()
        but uses Playwright for enhanced functionality including automatic redirects
        and session management.
        
        Args:
            host (str): Host to connect to (proxy host if via_proxy=True)
            port (int): Port to connect to
            target_host (str): Target host for the actual request
            request_data (str): Raw HTTP request string
            is_tls (bool): Whether to use TLS encryption
            via_proxy (bool): Whether to route through a proxy
            
        Returns:
            Union[str, bytes]: Raw HTTP response or error message
        """
        if not self._initialized:
            await self._initialize()

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
            # yield error_message

        # Parse the raw HTTP request
        parsed_request = self._parse_raw_request(request_data)
        if 'error' in parsed_request:
            error_info = parsed_request['error']
            error_message = (
                f"HTTP Request Parse Error\n"
                f"Type: {error_info['type']}\n"
                f"Message: {error_info['message']}\n"
                f"Context: {error_info['context']}\n"
                f"Raw Request:\n{error_info['raw_request']}\n"
                f"Structured Error (JSON):\n{json.dumps({'error': error_info}, indent=2)}"
            )
            yield error_message
            return

        yield request_data


        protocol = "https" if is_tls else "http"
        # TODO: still not tested
        if via_proxy:
            target_url = f"{protocol}://{target_host}{parsed_request['path']}"
        else:
            target_url = f"{protocol}://{host}:{port}{parsed_request['path']}"
        # get local storage headers to see if there is any needed headers to be added
        # to the request
        if self.session_id:
            try:
                localstorage = await self.get_localstorage(session_id=self.session_id)
                if localstorage and len(localstorage) > 0:
                    new_headers = self._inject_auth_headers_with_storage(
                        storage=localstorage[0],
                        headers=parsed_request['headers']
                    )
                    # print(f"new headers return inject: {new_headers}")
                    parsed_request['headers'].update(new_headers)
                else:
                    # No localStorage data available, use original headers
                    new_headers = parsed_request['headers']
            except Exception as e:
                print(f"Warning: Could not access localStorage for session {self.session_id}: {e}")
                new_headers = parsed_request['headers']
        else:
            new_headers = parsed_request['headers']
        
        # Sanitize headers that Playwright should manage to avoid redirect issues/timeouts
        # Note: Do NOT strip 'Cookie' header - Playwright's request_context automatically
        # includes cookies from the browser context, but if a Cookie header is explicitly
        # provided, we should preserve it (though it's redundant since context cookies are used)
        headers_to_strip = {
            'host', 'content-length', 'connection', 'transfer-encoding', 'accept-encoding'
        }
        sanitized_headers = {
            k: v for k, v in parsed_request['headers'].items() if k.lower() not in headers_to_strip
        }
        
        # Verify cookies are available from context (for debugging)
        if self.session_id:
            try:
                context_cookies = await self.context.cookies()
                if context_cookies:
                    # Filter cookies for the current domain
                    parsed_url = urlparse(target_url)
                    domain_cookies = [
                        c for c in context_cookies 
                        if parsed_url.netloc in c.get('domain', '') or 
                           c.get('domain', '').lstrip('.') in parsed_url.netloc
                    ]
                    if domain_cookies:
                        print(f"Using {len(domain_cookies)} cookies from context for {parsed_url.netloc}")
            except Exception as e:
                print(f"Warning: Could not verify context cookies: {e}")
        
        try:
            # Two-step approach to ensure cookies are captured:
            # 1. First request without following redirects to capture Set-Cookie headers
            # 2. Second request with redirects enabled, now that we have the cookies

            # Step 1: Send request without following redirects to capture cookies
            initial_response = await self._send_request(
                method=parsed_request['method'],
                url=target_url,
                headers=sanitized_headers,
                body=parsed_request['body'],
                follow_redirects=False,  # Don't follow redirects yet
                max_redirects=0
            )
            print(f"initial response : {initial_response}")
            # Extract cookies and auth tokens from the initial response
            await self._extract_cookies_and_tokens_from_response(initial_response, target_url)

            # Check if this was a redirect response
            is_redirect = initial_response.status in (301, 302, 303, 307, 308)

            if is_redirect:
                # Step 2: Send the same request again, but now with redirects enabled
                # This time we have the cookies from step 1, so they'll be included
                response = await self._send_request(
                    method=parsed_request['method'],
                    url=target_url,
                    headers=sanitized_headers,
                    body=parsed_request['body'],
                    follow_redirects=True,
                    max_redirects=20
                )

                # Extract any additional cookies from the final response
                await self._extract_cookies_and_tokens_from_response(response, target_url)
            else:
                # Not a redirect, use the initial response
                response = initial_response

            # Detecting and storing access keys or important reusable tokens
            # from the request
            response_body = await response.body()
            if isinstance(response_body, bytes):
                try:
                    response_body_text = response_body.decode('utf-8', errors='replace')
                except UnicodeDecodeError:
                    response_body_text = str(response_body)
            else:
                response_body_text = str(response_body)

            # Tokens are already extracted in _extract_cookies_and_tokens_from_response
            # Only extract again if we didn't do it in the two-step process
            if not is_redirect:
                await self._detect_and_store_tokens(response_body=response_body_text, url=target_url)
            # Save storage state (cookies + localStorage) after request to persist session cookies
            if self.session_id:
                try:
                    await self._save_storage_state(session_id=self.session_id)
                except Exception as e:
                    print(
                        f"Warning: Could not save storage state for session {self.session_id}: {e}"
                    )

            # Format and return both responses
            # First, return the initial response (without redirects)
            formatted_initial_response = await self._format_response(initial_response)
            initial_response_bytes = formatted_initial_response.encode('utf-8') \
                if isinstance(formatted_initial_response, str) else formatted_initial_response

            # Add a separator to distinguish between responses
            separator = b"\r\n\r\n=== FOLLOWING REDIRECTS ===\r\n\r\n" if is_redirect else b""

            # Then return the final response (with redirects if applicable)
            formatted_final_response = await self._format_response(response)
            final_response_bytes = formatted_final_response.encode('utf-8') \
                if isinstance(formatted_final_response, str) else formatted_final_response

            # Combine both responses
            if is_redirect:
                combined_response = initial_response_bytes + separator + final_response_bytes
            else:
                # If no redirect, just return the initial response
                combined_response = initial_response_bytes

            yield combined_response

        except Exception as e:
            # Fix: Handle all exceptions gracefully, including network errors
            error_message = f"Request failed: {str(e)}"
            yield error_message.encode('utf-8')


    def _parse_raw_request(self, raw_request: str) -> Dict[str, Any]:
        """
        Parse raw HTTP request string into components.
        
        Args:
            raw_request (str): Raw HTTP request string
            
        Returns:
            Dict[str, Any]: On success, returns dict with keys: method, path, headers, body.
                           On error, returns dict with 'error' key containing error details:
                           {
                               'error': {
                                   'type': str,  # Error type (e.g., 'ValueError', 'InvalidRequestLine')
                                   'message': str,  # Human-readable error message
                                   'context': str,  # Additional context about where parsing failed
                                   'raw_request': str  # The original request that failed to parse
                               }
                           }
        """
        try:
            lines = raw_request.strip().split('\r\n')
            if not lines:
                return {
                    'error': {
                        'type': 'EmptyRequest',
                        'message': 'Empty request: No lines found in request',
                        'context': 'Request string is empty or contains only whitespace',
                        'raw_request': raw_request
                    }
                }

            # Parse request line
            request_line = lines[0]
            parts = request_line.split(' ', 2)
            if len(parts) < 2:
                return {
                    'error': {
                        'type': 'InvalidRequestLine',
                        'message': f"Invalid request line: Expected 'METHOD PATH [HTTP_VERSION]' format, got '{request_line}'",
                        'context': 'Request line must contain at least method and path separated by space',
                        'raw_request': raw_request
                    }
                }

            method = parts[0]
            path = parts[1]

            # Parse headers
            headers = {}
            body_start = 0

            for i, line in enumerate(lines[1:], 1):
                if line == '':
                    body_start = i + 1
                    break
                if ':' in line:
                    try:
                        key, value = line.split(':', 1)
                        headers[key.strip()] = value.strip()
                    except ValueError:
                        return {
                            'error': {
                                'type': 'InvalidHeader',
                                'message': f"Invalid header format: '{line}'",
                                'context': f"Header at line {i+1} is malformed. Expected 'Key: Value' format",
                                'raw_request': raw_request
                            }
                        }
            # Extract body
            body = '\r\n'.join(lines[body_start:]) if body_start < len(lines) else ''

            return {
                'method': method,
                'path': path,
                'headers': headers,
                'body': body
            }

        except ValueError as e:
            return {
                'error': {
                    'type': 'ValueError',
                    'message': f"Value error during parsing: {str(e)}",
                    'context': 'Failed to parse a value (e.g., splitting a string, converting a type)',
                    'raw_request': raw_request
                }
            }
        except IndexError as e:
            return {
                'error': {
                    'type': 'IndexError',
                    'message': f"Index error during parsing: {str(e)}",
                    'context': 'Attempted to access an index that doesn\'t exist (e.g., accessing parts[1] when parts has only 1 element)',
                    'raw_request': raw_request
                }
            }
        except AttributeError as e:
            return {
                'error': {
                    'type': 'AttributeError',
                    'message': f"Attribute error during parsing: {str(e)}",
                    'context': 'Attempted to access an attribute that doesn\'t exist on an object',
                    'raw_request': raw_request
                }
            }

    async def _send_request(self, method: str, url: str, headers: Dict[str, str],
                          body: str, follow_redirects: bool = True,
                          max_redirects: int = 20) -> Any:
        """
        Send HTTP request using Playwright's APIRequestContext.
        
        The request_context automatically uses cookies from the browser context.
        Cookies are loaded from storage on initialization and saved after each request.
        
        Args:
            method (str): HTTP method
            url (str): Target URL
            headers (Dict[str, str]): Request headers
            body (str): Request body
            follow_redirects (bool): Whether to follow redirects
            max_redirects (int): Maximum number of redirects to follow
            
        Returns:
            Any: Playwright response object
        """
        # Note: self.request_context is created from self.context.request
        # which automatically includes cookies from the browser context.
        # Cookies are loaded from storage on initialization via storage_state option.
        
        request_options = {
            'headers': headers,
            'max_redirects': max_redirects if follow_redirects else 0,
            'timeout': 120_000,  # ms; allow slow redirect chains
        }

        if body:
            request_options['data'] = body
        if isinstance(self.request_context, APIRequestContext):
            method_handlers = {
                'GET': self.request_context.get,
                'POST': self.request_context.post,
                'PUT': self.request_context.put,
                'DELETE': self.request_context.delete,
                'HEAD': self.request_context.head,
                'PATCH': self.request_context.patch
            }
            method_upper = method.upper()
            try:
                if method_upper in method_handlers:
                    return await method_handlers[method_upper](url, **request_options)
                else:
                    return await self.request_context.fetch(
                        url_or_request=url,
                        method=method_upper,
                        **request_options
                    )
            except Exception as e:
                print(f"HTTP {method_upper} request failed for {url}: {str(e)}")
                raise
        else:
            # Fallback for non-APIRequestContext
            method_upper = method.upper()
            try:
                return await self.request_context.fetch(
                    url_or_request=url,
                    method=method_upper,
                    **request_options
                )
            except Exception as e:
                print(f"HTTP {method_upper} request failed for {url}: {str(e)}")
                raise

    async def _format_response(self, response: Any) -> str:
        """
        Format Playwright response into HTTP response string.
        
        Args:
            response: Playwright response object
            
        Returns:
            str: Formatted HTTP response string
        """
        try:
            # Get response body
            body = await response.body()
            if isinstance(body, bytes):
                try:
                    body_text = body.decode('utf-8', errors='replace')
                except UnicodeDecodeError:
                    body_text = str(body)
            else:
                body_text = str(body)

            # Format response headers
            headers_text = ""
            for name, value in response.headers.items():
                headers_text += f"{name}: {value}\r\n"

            # Format status line
            status_line = f"HTTP/1.1 {response.status} {response.status_text or 'OK'}\r\n"

            # Combine all parts
            formatted_response = status_line + headers_text + "\r\n" + body_text

            return formatted_response

        except (UnicodeDecodeError, AttributeError, KeyError) as e:
            return f"Error formatting response: {str(e)}"

    async def _detect_and_store_tokens(self, response_body: str, url: str):
        try:
            domain = urlparse(url).netloc

            str_response_body =str(response_body)
            # JSON
            await self._detect_json_tokens(str_response_body, domain)
            # HTML parsing
            await self._detect_html_tokens(str_response_body, domain)
            # URL parameters
            await self._detect_url_tokens(url, domain)
            # Try text patterns
            await self._detect_text_tokens(str_response_body, domain)
            # Try XML parsing
            await self._detect_xml_tokens(str_response_body, domain)
        except Exception as e:
            print(f"Error detecting tokens: {e}")

    async def _detect_json_tokens(self, json_content: str, domain: str):
        try:
            data = json.loads(json_content)
            token_patterns = {
                'access_token': ['access_token', 'accessToken', 'access-token'],
                'refresh_token': ['refresh_token', 'refreshToken', 'refresh-token'],
                'id_token': ['id_token', 'idToken', 'id-token'],
                'auth_token': ['token', 'auth_token', 'authToken', 'auth-token']
            }
            for storage_key, field_names in token_patterns.items():
                for field_name in field_names:
                    if field_name in data:
                        token_value = data[field_name]
                        await self.set_localstorage_value(storage_key, token_value, domain)
                        print(f"Auto-stored {storage_key} from response")
        except (json.JSONDecodeError, KeyError):
            pass

    async def _detect_html_tokens(self, html_content: str, domain: str):
        """Detect tokens in HTML content.
        For example : 
            <meta name="csrf-token" content="abc123xyz">
            <meta name="auth-token" content="token_456def">
            <meta name="api-key" content="key_789ghi">
        """
        # Hidden input fields
        hidden_inputs = re.findall(
            r'<input[^>]*type=["\']hidden["\'][^>]*name=["\']([^"\']*)["\'][^>]*value=["\']([^"\']*)["\'][^>]*>',
            html_content
            )
        for name, value in hidden_inputs:
            if 'token' in name.lower() or 'csrf' in name.lower():
                await self.set_localstorage_value(name, value, domain)
        # Meta tags
        meta_tags = re.findall(
            r'<meta[^>]*name=["\']([^"\']*)["\'][^>]*content=["\']([^"\']*)["\'][^>]*>',
            html_content
            )
        for name, content in meta_tags:
            if 'token' in name.lower() or 'csrf' in name.lower():
                await self.set_localstorage_value(name, content, domain)
        # JavaScript variables
        js_vars = re.findall(r'window\.(\w*[Tt]oken\w*)\s*=\s*["\']([^"\']*)["\']', html_content)
        for var_name, value in js_vars:
            await self.set_localstorage_value(var_name, value, domain)

    async def _detect_url_tokens(self, url: str, domain: str):
        """Detect tokens in URL parameters.
        defines the case : 
        https://app.com/dashboard?token=abc123xyz&session_id=sess_456def
        https://api.com/callback?access_token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
        """

        parsed = urlparse(url)
        params = parse_qs(parsed.query)

        token_params = ['token', 'access_token', 'auth_token', 'session_id', 'csrf_token']
        for param in token_params:
            if param in params:
                value = params[param][0]
                await self.set_localstorage_value(param, value, domain)

    async def _detect_text_tokens(self, text_content: str, domain: str):
        """Detect tokens in plain text responses."""
        # Key-value pairs
        kv_patterns = [
            r'(\w*[Tt]oken\w*)\s*[:=]\s*([^\s\n]+)',
            r'(\w*[Tt]oken\w*)\s*=\s*([^\s\n]+)',
            r'(\w*[Tt]oken\w*)\s*:\s*([^\s\n]+)'
        ]
        for pattern in kv_patterns:
            matches = re.findall(pattern, text_content)
            for key, value in matches:
                await self.set_localstorage_value(key, value, domain)
        # Delimited formats
        delimited_patterns = [
            r'(\w*[Tt]oken\w*)[:|;]([^|;\n]+)',
            r'(\w*[Tt]oken\w*)\s*=\s*([^;\n]+)'
        ]

        for pattern in delimited_patterns:
            matches = re.findall(pattern, text_content)
            for key, value in matches:
                await self.set_localstorage_value(key, value.strip(), domain)

    async def _detect_xml_tokens(self, xml_content: str, domain: str):
        """Detect tokens in XML responses."""
        # XML tags containing tokens
        xml_patterns = [
            r'<(\w*[Tt]oken\w*)>([^<]+)</\1>',
            r'<(\w*[Tt]oken\w*)\s+value=["\']([^"\']*)["\']',
            r'<(\w*[Tt]oken\w*)\s+content=["\']([^"\']*)["\']'
        ]
        for pattern in xml_patterns:
            matches = re.findall(pattern, xml_content)
            for tag_name, value in matches:
                await self.set_localstorage_value(tag_name, value, domain)

    async def get_cookies(self) -> Dict[str, str]:
        """
        Get current session cookies.
        
        Returns:
            Dict[str, str]: Dictionary of cookie name-value pairs
        """
        if not self._initialized or not self.context:
            return {}

        cookies = await self.context.cookies()
        return {cookie['name']: cookie['value'] for cookie in cookies
                if 'name' in cookie and 'value' in cookie}

    async def set_cookies(self, cookies: Dict[str, str], domain: str | None = None):
        """
        Set session cookies.
        Args:
            cookies (Dict[str, str]): Dictionary of cookie name-value pairs
            domain (str, optional): Cookie domain
        """
        if not self._initialized or not self.context:
            return

        cookie_list = []
        for name, value in cookies.items():
            cookie_dict = {
                'name': name,
                'value': value,
                'domain': domain or '.example.com',
                'path': '/'
            }
            cookie_list.append(cookie_dict)

        await self.context.add_cookies(cookie_list)
        
        # Save storage state after setting cookies to persist them
        if self.session_id:
            try:
                await self._save_storage_state(session_id=self.session_id)
            except Exception as e:
                print(f"Warning: Could not save cookies to storage: {e}")

    async def _extract_cookies_and_tokens_from_response(self, response: Any, url: str):
        """
        Extract Set-Cookie headers and auth tokens from a response.
        
        This method extracts cookies from Set-Cookie headers and also detects
        auth tokens in response bodies/headers for storage in localStorage.
        
        Args:
            response: The response object from Playwright
            url: The URL of the response (for domain extraction)
        """
        if not self._initialized or not self.context:
            return
        
        try:
            # Get cookies that Playwright already stored in the context
            context_cookies_before = await self.context.cookies()
            cookie_names_before = {c['name'] for c in context_cookies_before}
            
            # Extract Set-Cookie headers directly from response
            try:
                all_headers = response.all_headers()
            except (AttributeError, TypeError):
                # Fallback to headers property
                all_headers = response.headers
            print(f"headers caught : {all_headers}")
            # Check for Set-Cookie header (case-insensitive)
            set_cookie_values = []
            for header_name, header_value in all_headers.items():
                if header_name.lower() == 'set-cookie':
                    # Set-Cookie can appear multiple times
                    if isinstance(header_value, list):
                        set_cookie_values.extend(header_value)
                    elif isinstance(header_value, str):
                        set_cookie_values.append(header_value)
            
            # Parse and add cookies to context
            cookies_extracted = 0
            if set_cookie_values:
                parsed_url = urlparse(url)
                domain = parsed_url.netloc
                
                for set_cookie in set_cookie_values:
                    # Parse Set-Cookie header: "name=value; Path=/; Domain=.example.com; HttpOnly"
                    cookie_parts = set_cookie.split(';')
                    if cookie_parts:
                        name_value = cookie_parts[0].strip()
                        if '=' in name_value:
                            cookie_name, cookie_value = name_value.split('=', 1)

                            # Skip if cookie already exists (Playwright might have added it)
                            if cookie_name.strip() in cookie_names_before:
                                continue

                            # Extract cookie attributes
                            cookie_attrs = {
                                'name': cookie_name.strip(),
                                'value': cookie_value.strip(),
                                'domain': domain,
                                'path': '/'
                            }

                            # Parse additional attributes
                            for part in cookie_parts[1:]:
                                part = part.strip()
                                if '=' in part:
                                    attr_name, attr_value = part.split('=', 1)
                                    attr_name = attr_name.lower()
                                    if attr_name == 'domain':
                                        cookie_attrs['domain'] = attr_value.strip()
                                    elif attr_name == 'path':
                                        cookie_attrs['path'] = attr_value.strip()
                                    elif attr_name == 'expires':
                                        cookie_attrs['expires'] = attr_value.strip()
                                    elif attr_name == 'max-age':
                                        try:
                                            cookie_attrs['maxAge'] = int(attr_value.strip())
                                        except ValueError:
                                            pass
                                else:
                                    # Boolean attributes
                                    part_lower = part.lower()
                                    if part_lower == 'httponly':
                                        cookie_attrs['httpOnly'] = True
                                    elif part_lower == 'secure':
                                        cookie_attrs['secure'] = True
                                    elif part_lower in ('samesite', 'samesite=lax', 'samesite=strict', 'samesite=none'):
                                        if '=' in part_lower:
                                            cookie_attrs['sameSite'] = part_lower.split('=')[1].capitalize()
                                        else:
                                            cookie_attrs['sameSite'] = 'Lax'
                            
                            # Add cookie to context
                            try:
                                await self.context.add_cookies([cookie_attrs])
                                cookies_extracted += 1
                            except Exception as e:
                                print(f"Warning: Could not add cookie {cookie_name}: {e}")
            
            # Also extract auth tokens from response body/headers
            try:
                response_body = await response.body()
                if isinstance(response_body, bytes):
                    try:
                        response_body_text = response_body.decode('utf-8', errors='replace')
                    except UnicodeDecodeError:
                        response_body_text = str(response_body)
                else:
                    response_body_text = str(response_body)
                
                # Detect and store tokens from response
                await self._detect_and_store_tokens(response_body=response_body_text, url=url)
            except Exception as e:
                print(f"Warning: Could not extract tokens from response: {e}")
            
            # Verify cookies were added
            if cookies_extracted > 0:
                context_cookies_after = await self.context.cookies()
                print(f"Extracted {cookies_extracted} cookies from response. Total cookies: {len(context_cookies_after)}")
                
        except Exception as e:
            print(f"Warning: Could not extract cookies and tokens from response: {e}")
            import traceback
            traceback.print_exc()

    async def _save_storage_state(self, session_id: str):
        """
        Save the current storage state (cookies + localStorage) to disk.
        
        This ensures cookies set by responses are persisted for future requests.
        When path is provided to storage_state(), it saves the state to that file.
        """
        if not self._initialized or not self.context:
            return

        try:
            storage_path = await self._get_storage_path(session_id)
            # Save storage state including cookies to file
            # When path is provided, storage_state() saves to that path
            await self.context.storage_state(path=storage_path)
            # Verify the file was created/updated
            storage_file = Path(storage_path)
            if await storage_file.exists():
                # Read back to verify cookies are saved
                content = await storage_file.read_text(encoding='utf-8')
                if content and content.strip():
                    storage_data = json.loads(content)
                    cookie_count = len(storage_data.get('cookies', []))
                    if cookie_count > 0:
                        print(f"Saved {cookie_count} cookies to storage for session {session_id}")
        except Exception as e:
            print(f"Error saving storage state: {e}")
            import traceback
            traceback.print_exc()

    async def get_localstorage(self, session_id: str) -> List[OriginState]:
        """
        Returns the localStorage in the browser's context.
        
        Note: This gets the current state from the context, not from disk.
        To get from disk, we would need to load the storage file separately.
        """
        if not self._initialized or not self.context:
            return []

        # Get current storage state from context (without saving)
        # When path is not provided, storage_state() returns the state dict
        localstorage = await self.context.storage_state()
        return localstorage.get('origins', [])

    async def set_localstorage_value(self, key: str, value: str, domain: str | None = None):
        """
        Set a localStorage value for a specific domain.
        
        Args:
            key (str): The localStorage key
            value (str): The value to store
            domain (str, optional): Domain to set the value for. If None, uses current page domain.
        """
        if not self._initialized or not self.context:
            return False

        try:
            # Fix: Use persistent page instead of creating new pages
            page = await self._get_persistent_page(domain)
            if not page:
                return False
            
            # Fix: Use proper escaping for JavaScript evaluation
            escaped_key = self._escape_js_string(key)
            escaped_value = self._escape_js_string(value)
            
            await page.evaluate(f"localStorage.setItem({escaped_key}, {escaped_value})")
            return True
        except Exception as e:
            print(f"Error setting localStorage: {e}")
            return False

    async def get_localstorage_value(self, key: str, domain: str | None = None):
        """
        Get a localStorage value for a specific domain.
        
        Args:
            key (str): The localStorage key
            domain (str, optional): Domain to get the value from. If None, uses current page domain.
            
        Returns:
            str: The localStorage value or None if not found
        """
        if not self._initialized or not self.context:
            return None

        try:
            # Fix: Use persistent page instead of creating new pages
            page = await self._get_persistent_page(domain)
            if not page:
                return None
            
            # Fix: Use proper escaping for JavaScript evaluation
            escaped_key = self._escape_js_string(key)
            
            value = await page.evaluate(f"localStorage.getItem({escaped_key})")
            return value
        except Exception as e:
            print(f"Error getting localStorage: {e}")
            return None

    async def remove_localstorage_value(self, key: str, domain: str | None = None):
        """
        Remove a localStorage value for a specific domain.
        
        Args:
            key (str): The localStorage key to remove
            domain (str, optional): Domain to remove the value from. 
                If None, uses current page domain.

        Returns:
            bool: True if successful, False otherwise
        """
        if not self._initialized or not self.context:
            return False

        try:
            # Fix: Use persistent page instead of creating new pages
            page = await self._get_persistent_page(domain)
            if not page:
                return False
            
            # Fix: Use proper escaping for JavaScript evaluation
            escaped_key = self._escape_js_string(key)
            
            await page.evaluate(f"localStorage.removeItem({escaped_key})")
            return True
        except Exception as e:
            print(f"Error removing localStorage: {e}")
            return False

    async def clear_localstorage(self, domain: str | None = None):
        """
        Clear all localStorage values for a specific domain.
        
        Args:
            domain (str, optional): Domain to clear localStorage for.
                If None, uses current page domain.
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self._initialized or not self.context:
            return False

        try:
            # Fix: Use persistent page instead of creating new pages
            page = await self._get_persistent_page(domain)
            if not page:
                return False
            
            await page.evaluate("localStorage.clear()")
            return True
        except Exception as e:
            print(f"Error clearing localStorage: {e}")
            return False

    async def get_all_localstorage(self, domain: str | None = None):
        """
        Get all localStorage key-value pairs for a specific domain.
        
        Args:
            domain (str, optional): Domain to get localStorage from.
            If None, uses current page domain.
            
        Returns:
            dict: Dictionary of all localStorage key-value pairs
        """
        if not self._initialized or not self.context:
            return {}

        try:
            # Fix: Use persistent page instead of creating new pages
            page = await self._get_persistent_page(domain)
            if not page:
                return {}
            
            storage = await page.evaluate("""
                () => {
                    const storage = {};
                    for (let i = 0; i < localStorage.length; i++) {
                        const key = localStorage.key(i);
                        storage[key] = localStorage.getItem(key);
                    }
                    return storage;
                }
            """)
            return storage
        except Exception as e:
            print(f"Error getting all localStorage: {e}")
            return {}

    async def set_multiple_localstorage(
        self,
        storage_dict: Dict[str, str],
        domain: str | None = None
    ):
        """
        Set multiple localStorage key-value pairs for a specific domain.
        
        Args:
            storage_dict (Dict[str, str]): Dictionary of key-value pairs to set
            domain (str, optional): Domain to set the values for. If None, uses current page domain.
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self._initialized or not self.context:
            return False

        try:
            # Fix: Use persistent page instead of creating new pages
            page = await self._get_persistent_page(domain)
            if not page:
                return False

            # Fix: Use proper escaping and batch operations
            escaped_items = []
            for key, value in storage_dict.items():
                escaped_key = self._escape_js_string(key)
                escaped_value = self._escape_js_string(value)
                escaped_items.append(f"localStorage.setItem({escaped_key}, {escaped_value})")

            # Execute all operations in one evaluate call
            await page.evaluate(";".join(escaped_items))
            return True
        except Exception as e:
            print(f"Error setting multiple localStorage values: {e}")
            return False

    async def clear_session(self):
        """Clear all session data (cookies, local storage, etc.)."""
        if not self._initialized or not self.context:
            return

        await self.context.clear_cookies()
        await self.context.clear_permissions()

        # Clear localStorage for all pages in the context
        try:
            pages = self.context.pages
            for page in pages:
                await page.evaluate("localStorage.clear()")
        except Exception as e:
            print(f"Warning: Could not clear localStorage: {e}")
