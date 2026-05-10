import json
import hashlib
from pydantic_ai import RunContext
from deadend_agent.utils.structures import RequesterDeps
from deadend_agent.utils.functions import truncate_string
from deadend_agent.logging import logger
from deadend_agent.constants import CACHE_DEADEND_LOGS

from .http_parser import is_valid_request_detailed, extract_host_port, autocorrect_http_request
from .auth_handler import replace_credential_placeholders
from .pw_requester import PlaywrightRequester
from .pw_session_manager import PlaywrightSessionManager
from deadend_agent.tools.tool_wrappers import with_tool_events

__all__ = ["is_valid_request_detailed", "PlaywrightRequester"]


@with_tool_events("pw_send_payload")
async def pw_send_payload(
    ctx: RunContext[RequesterDeps],
    target_host: str,
    raw_request: str,
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
        verify_ssl (bool): Whether to verify SSL certificates

    Returns:
        Union[str, bytes]: HTTP response or error message
    """
    # Use the target_host parameter passed by the LLM, fallback to ctx.deps.target if empty
    effective_target = target_host if target_host and target_host.strip() else ctx.deps.target
    if not effective_target:
        return "Error: target_host must be provided either as parameter or in context"
    
    host, port = extract_host_port(target_host=effective_target)

    # Auto-correct malformed HTTP requests before processing
    try:
        corrected_request, corrections = autocorrect_http_request(
            raw_request=raw_request,
            target_host=effective_target
        )
        if corrections:
            logger.debug("Auto-corrected HTTP request: %s", ', '.join(corrections))
        raw_request = corrected_request
    except ValueError as e:
        return f"Error: Cannot auto-correct request - {str(e)}"

    # Anonymisation process
    # the function detects the dummy credentials given and replaces them with the right one
    # So that the LLM will never see the true credentials
    raw_request_anon = replace_credential_placeholders(raw_request)
    is_tls = port == 443 or effective_target.startswith('https://')
    proxy_url = ctx.deps.proxy_url
    # session_key = _build_session_key(
    #     host=host,
    #     port=port,
    #     proxy_url=proxy_url,
    #     verify_ssl=verify_ssl,
    # )

    # pw_requester session
    pw_session = await PlaywrightSessionManager.get_session(
        session_key=str(ctx.deps.session_id),
        agent_id=str(ctx.deps.agent_id),
        verify_ssl=verify_ssl,
        proxy_url=proxy_url
    )
    responses = []
    try:
        async for response in pw_session.send_raw_data(
            host=host,
            port=port,
            request_data=raw_request_anon,
            is_tls=is_tls,
        ):
            responses.append(response)

        # Save responses to requester.jsonl file
        await _save_responses_to_file(
            agent_id=str(ctx.deps.agent_id), 
            session_key=str(ctx.deps.session_id), 
            responses=responses)

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

async def _save_responses_to_file(agent_id: str, session_key: str, responses: list):
    """
    Save responses to requester.jsonl file in the session directory.
    
    Args:
        session_key (str): Session identifier
        responses (list): List of response objects to save
    """
    try:
        # Create the directory path
        cache_dir = CACHE_DEADEND_LOGS / agent_id / session_key
        cache_dir.mkdir(parents=True, exist_ok=True)

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
        logger.warning("Could not save responses to file: %s", e)


async def cleanup_playwright_session_for_target(
    target_host: str,
    proxy_url: str | None = None,
    verify_ssl: bool = False,
):
    """
    Clean up a specific Playwright session for a target.
    
    Args:
        target_host (str): Target host to clean up session for
        proxy_url (str | None): Proxy URL used for the session
        verify_ssl (bool): Whether SSL verification was used
    """
    host, port = extract_host_port(target_host)
    session_key = _build_session_key(
        host=host,
        port=port,
        proxy_url=proxy_url,
        verify_ssl=verify_ssl,
    )
    await PlaywrightSessionManager.cleanup_session(session_key)


def _build_session_key(host: str, port: int, proxy_url: str | None, verify_ssl: bool) -> str:
    proxy_digest = hashlib.sha256((proxy_url or "").encode("utf-8")).hexdigest()[:12]
    tls_mode = "verify" if verify_ssl else "insecure"
    return f"{host}_{port}_{tls_mode}_{proxy_digest}"
