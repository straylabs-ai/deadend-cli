import json
from anyio import Path
from pydantic_ai import RunContext
from deadend_agent.utils.structures import RequesterDeps
from deadend_agent.utils.functions import truncate_string

from .http_parser import is_valid_request_detailed, extract_host_port, autocorrect_http_request
from .auth_handler import replace_credential_placeholders
from .pw_requester import PlaywrightRequester
from .pw_session_manager import PlaywrightSessionManager
# from deadend_agent.context import MemoryHandler
from deadend_agent.tools.tool_wrappers import with_tool_events

__all__ = ["is_valid_request_detailed"]


@with_tool_events("pw_send_payload")
async def pw_send_payload(
    ctx: RunContext[RequesterDeps],
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

    Auto-corrects common HTTP request malformations before sending:
    - Line endings (\\n -> \\r\\n)
    - Missing Host header (derived from target)
    - Malformed request line
    - Missing HTTP version

    Args:
        target_host (str): Target host in format "host:port" or URL
        raw_request (str): Raw HTTP request string
        proxy (bool): Whether to route through localhost:8080 proxy
        verify_ssl (bool): Whether to verify SSL certificates

    Returns:
        Union[str, bytes]: HTTP response or error message
    """
    host, port = extract_host_port(target_host=ctx.deps.target)

    # Auto-correct malformed HTTP requests before processing
    try:
        corrected_request, corrections = autocorrect_http_request(
            raw_request=raw_request,
            target_host=ctx.deps.target
        )
        if corrections:
            print(f"Auto-corrected HTTP request: {', '.join(corrections)}")
        raw_request = corrected_request
    except ValueError as e:
        return f"Error: Cannot auto-correct request - {str(e)}"

    # Anonymisation process
    # the function detects the dummy credentials given and replaces them with the right one
    # So that the LLM will never see the true credentials
    raw_request_anon = replace_credential_placeholders(raw_request)
    is_tls = port == 443 or ctx.deps.target.startswith('https://')
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
            target_host=ctx.deps.target,
            request_data=raw_request_anon,
            is_tls=is_tls,
            via_proxy=proxy
        ):
            responses.append(response)

        # Save responses to requester.jsonl file
        await _save_responses_to_file(session_key, responses)

        # Convert bytes responses to strings before truncation
        string_responses = []
        for response in responses:
            if isinstance(response, bytes):
                try:
                    response_str = response.decode('utf-8', errors='replace')
                except Exception:
                    response_str = str(response)
            else:
                response_str = str(response)
            string_responses.append(response_str)

        truncated_responses = [truncate_string(resp) for resp in string_responses]
        return str(truncated_responses)

    except Exception as e:
        return f"Error when sending payload: {str(e)}"


async def cleanup_playwright_sessions():
    """
    Clean up all Playwright sessions.
    
    This function should be called when the application exits or when
    you want to clear all session data (cookies, etc.).
    """
    await PlaywrightSessionManager.cleanup_all_sessions()

async def _save_responses_to_file(session_key: str, responses: list):
    """
    Save responses to requester.jsonl file in the session directory.
    
    Args:
        session_key (str): Session identifier
        responses (list): List of response objects to save
    """
    try:
        # Create the directory path
        cache_dir = await Path.home() / ".cache" / "deadend" / "memory" / "sessions" / session_key
        await cache_dir.mkdir(parents=True, exist_ok=True)

        # Create the file path (convert to string for regular open())
        file_path_str = str(cache_dir / "requester.jsonl")

        # Convert responses to JSON-serializable format and append to file
        with open(file_path_str, "a", encoding="utf-8") as f:
            for response in responses:
                # Handle bytes responses
                if isinstance(response, bytes):
                    try:
                        response_str = response.decode('utf-8', errors='replace')
                    except Exception:
                        response_str = str(response)
                else:
                    response_str = str(response)

                # Create JSON object for this response
                response_data = {
                    "response": response_str
                }

                # Append to file with pretty-printed JSON (indented for readability)
                json_line = json.dumps(response_data, ensure_ascii=False, indent=2)
                f.write(json_line + "\n")
    except Exception as e:
        print(f"Warning: Could not save responses to file: {e}")


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
