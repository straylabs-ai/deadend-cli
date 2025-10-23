
from .http_parser import is_valid_request_detailed, extract_host_port

from .auth_handler import replace_credential_placeholders
from .pw_requester import PlaywrightRequester
from .pw_session_manager import PlaywrightSessionManager

__all__ = ["is_valid_request_detailed"]

async def pw_send_payload(
    target_host: str,
    raw_request: str,
    proxy: bool = False,
    verify_ssl: bool = False,
):
    """
    Send HTTP payload using Playwright with enhanced capabilities and session persistence.
    
    This function provides the same interface as the original send_payload()
    but uses Playwright for improved functionality with persistent sessions
    that maintain cookies between requests.
    
    Args:
        target_host (str): Target host in format "host:port" or URL
        raw_request (str): Raw HTTP request string
        proxy (bool): Whether to route through localhost:8080 proxy
        verify_ssl (bool): Whether to verify SSL certificates
        
    Returns:
        Union[str, bytes]: HTTP response or error message
    """
    host, port = extract_host_port(target_host=target_host)

    raw_request = replace_credential_placeholders(raw_request)
    is_tls = port == 443 or target_host.startswith('https://')
    session_key = f"{host}_{port}"
    proxy_url = "http://localhost:8080" if proxy else None

    # pw_requester session
    pw_session = await PlaywrightSessionManager.get_session(
        session_key=session_key,
        verify_ssl=verify_ssl,
        proxy_url=proxy_url
    )
    responses = []
    try:
        async for response in pw_session.send_raw_data(
            host=host,
            port=port,
            target_host=target_host,
            request_data=raw_request,
            is_tls=is_tls,
            via_proxy=proxy
        ):
            responses.append(response)
        return str(responses)

    except Exception as e:
        return f"Error when sending payload: {str(e)}"

async def cleanup_playwright_sessions():
    """
    Clean up all Playwright sessions.
    
    This function should be called when the application exits or when
    you want to clear all session data (cookies, etc.).
    """
    await PlaywrightSessionManager.cleanup_all_sessions()


async def cleanup_playwright_session_for_target(target_host: str, proxy: bool = False, verify_ssl: bool = False):
    """
    Clean up a specific Playwright session for a target.
    
    Args:
        target_host (str): Target host to clean up session for
        proxy (bool): Whether proxy was used
        verify_ssl (bool): Whether SSL verification was used
    """
    host, port = extract_host_port(target_host)
    session_key = f"{host}_{port}"
    await PlaywrightSessionManager.cleanup_session(session_key)
