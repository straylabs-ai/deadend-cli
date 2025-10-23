# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Network utilities for target validation and connectivity testing.

This module provides network utility functions for checking target availability,
connectivity, and response validation for security research and web application
testing workflows.
"""

from playwright.async_api import async_playwright


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


def _get_target_variations(target: str) -> list[str]:
    """
    Get different URL variations to try for a target.
    
    Args:
        target: Target URL or host:port
        
    Returns:
        List of URL variations to try
    """
    target = target.strip()
    variations = []
    
    # If it already has a protocol, just return it
    if target.startswith(('http://', 'https://')):
        variations.append(target)
        # Also try without trailing slash
        if target.endswith('/'):
            variations.append(target.rstrip('/'))
        return variations
    
    # Extract host and port if present
    if ':' in target and not target.startswith('/'):
        host_port = target.rstrip('/')
        variations.extend([
            f"http://{host_port}",
            f"https://{host_port}",
            f"http://{host_port}/",
            f"https://{host_port}/",
        ])
    else:
        # Just hostname
        hostname = target.rstrip('/')
        variations.extend([
            f"http://{hostname}",
            f"https://{hostname}",
            f"http://{hostname}/",
            f"https://{hostname}/",
        ])
    
    return variations


async def check_target_alive(target: str, timeout_seconds: float = 5.0) -> tuple[bool, int | None, str | None]:
    """
    Check whether a web target is reachable and responds to HTTP requests.

    Returns (alive, status_code, error_message).
    """
    try:
        # Get URL variations to try
        url_variations = _get_target_variations(target)
        
        async with async_playwright() as p:
            # Launch headless browser
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                ignore_https_errors=True
            )
            
            last_status: int | None = None
            last_error: str | None = None
            
            # Try each URL variation with GET requests only
            for url in url_variations:
                try:
                    response = await context.request.get(url, timeout=timeout_seconds * 1000)
                    last_status = response.status
                    
                    # Accept any response status as "alive" - even 400/500 means the server is responding
                    if last_status is not None:
                        await browser.close()
                        return True, last_status, None
                        
                except (ConnectionError, TimeoutError, ValueError) as e:
                    last_error = str(e)
                    continue
            
            await browser.close()
            return False, last_status, last_error
            
    except (RuntimeError, ConnectionError, TimeoutError) as e:
        return False, None, str(e)


async def get_target_info(target: str, timeout_seconds: float = 10.0) -> dict:
    """
    Get comprehensive information about a target including headers, redirects, and TLS info.
    
    Returns a dictionary with target information.
    """
    try:
        # Normalize the target URL
        normalized_target = _normalize_target_url(target)
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                ignore_https_errors=True
            )
            
            info = {
                'target': target,
                'normalized_target': normalized_target,
                'alive': False,
                'status_code': None,
                'headers': {},
                'redirects': [],
                'final_url': None,
                'error': None
            }
            
            try:
                response = await context.request.get(normalized_target, timeout=timeout_seconds * 1000)
                info['alive'] = True
                info['status_code'] = response.status
                info['headers'] = dict(response.headers)
                info['final_url'] = response.url
                
                # Get redirect chain
                request = response.request
                redirects = []
                while request.redirected_from():
                    redirects.append({
                        'from': request.redirected_from().url,
                        'to': request.url,
                        'status': response.status
                    })
                    request = request.redirected_from()
                info['redirects'] = redirects

            except (ConnectionError, TimeoutError, ValueError) as e:
                info['error'] = str(e)

            await browser.close()
            return info

    except (RuntimeError, ConnectionError, TimeoutError) as e:
        return {
            'target': target,
            'normalized_target': _normalize_target_url(target),
            'alive': False,
            'status_code': None,
            'headers': {},
            'redirects': [],
            'final_url': None,
            'error': str(e)
        }