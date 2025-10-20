
from .http_parser import is_valid_request_detailed, extract_host_port

from .auth_handler import replace_credential_placeholders

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
