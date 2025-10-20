
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
        session_key: str,
        verify_ssl: bool = True,
        proxy_url: str | None = None
    ) -> 'PlaywrightRequester':
        """
        Get or create a PlaywrightRequester session.
        
        Args:
            session_key (str): Unique key for the session (e.g., target host)
            verify_ssl (bool): Whether to verify SSL certificates
            proxy_url (str, optional): Proxy URL for requests
            
        Returns:
            PlaywrightRequester: Session instance
        """
        async with cls._lock:
            if session_key not in cls._instances:
                cls._instances[session_key] = PlaywrightRequester(verify_ssl, proxy_url, session_id=session_key)
                await cls._instances[session_key]._initialize()
            return cls._instances[session_key]

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
