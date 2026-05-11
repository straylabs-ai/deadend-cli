
import asyncio
from typing import Dict

from .pw_requester import PlaywrightRequester

class PlaywrightSessionManager:
    """
    Singleton session manager to maintain PlaywrightRequester instances across tool calls.
    
    This ensures that cookies and session data persist between multiple requests
    within the same application session.
    """
    _instances: Dict[str, 'PlaywrightRequester'] = {}
    _lock = asyncio.Lock()

    @classmethod
    async def get_session(
        cls,
        agent_id: str | None,
        session_key: str,
        verify_ssl: bool = True,
        proxy_url: str | None = None,
        auth_storage_state_path: str | None = None,
        auth_profile: str | None = None,
    ) -> 'PlaywrightRequester':
        """
        Get or create a PlaywrightRequester session.

        Args:
            session_key (str): Unique key for the session (e.g., target host)
            verify_ssl (bool): Whether to verify SSL certificates
            proxy_url (str, optional): Proxy URL for requests
            auth_storage_state_path: Optional path to a Playwright storage state
                file produced from a saved DeadEnd ``AuthContext`` for this profile.
            auth_profile: Optional profile label; when set the cache key is
                segmented per profile so authenticated and unauthenticated
                sessions do not pollute each other.

        Returns:
            PlaywrightRequester: Session instance
        """
        cache_key = f"{session_key}::auth={auth_profile}" if auth_profile else session_key
        async with cls._lock:
            if cache_key not in cls._instances:
                cls._instances[cache_key] = PlaywrightRequester(
                    verify_ssl,
                    proxy_url,
                    session_id=session_key,
                    agent_id=agent_id,
                    auth_storage_state_path=auth_storage_state_path,
                    auth_profile=auth_profile,
                )
                await cls._instances[cache_key]._initialize()
            return cls._instances[cache_key]

    @classmethod
    async def cleanup_session(cls, session_key: str):
        """Clean up a specific session."""
        async with cls._lock:
            if session_key in cls._instances:
                await cls._instances[session_key]._cleanup()
                del cls._instances[session_key]

    @classmethod
    async def cleanup_all_sessions(cls):
        """Clean up all sessions."""
        async with cls._lock:
            for session_key in list(cls._instances.keys()):
                await cls._instances[session_key]._cleanup()
            cls._instances.clear()
