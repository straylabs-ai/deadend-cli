from typing import Any
from enum import Enum
from uuid import UUID
from pydantic import BaseModel
from pathlib import Path


# adding credentials refs
class CredentialsRefs(BaseModel):
    username: str | None
    # username that will be used for the login
    password: str | None
    # possible password that will be used
    login_url: str | None
    # Login url to make it easier to reproduce the auth phase
    # metadata: dict[str, str] # Possible metadata and headers related to the task
    # sometimes we can have scopes that include a specific header to show that it it 
    # a bug bounty hunter for example
    refresh_url: str | None
    # refresh url 

class AuthFlow(str, Enum):
    """
    AuthFlow defines the flow given to the agent so that he knows 
    what would be the authentication flow
    """
    HTTP_LOGIN = "http"
    FORM = "form"
    JSON = "json"
    OAUTH = "oauth"
    AUTHORIZATION_CODE = "authorization_code"
    CALLBACK = "callback"

class AuthType(str, Enum):
    """
    Depending on the return, or prelude information from the user, the 
    AuthType is defined to store the information in a certain way.
    """
    SESSION_COOKIE = "session_cookie"
    BEARER_TOKEN = "bearer_token"
    API_KEY = "api_key"
    OAUTH2 = "oauth2"

class AuthCredentials(BaseModel):
    auth_url: str | None
    target_origin: str | None
    auth_flow: AuthFlow | None
    auth_type: AuthType | None
    credential_ref: CredentialsRefs | None

class AuthContext(BaseModel):
    profile: str
    # Name of the profile
    cookies: dict[Any, Any]
    # Session cookies
    headers: dict[Any, Any]
    # Session Headers
    browser_storage: dict[Any, Any]
    # contains localStorage, sessionStorage
    metadata: dict[Any, Any]
    # contains the remaining information, update time, auth type, auth flow...

class AuthContextHandler:
    browser: Any 
    # Browser used
    auth_contexts: dict[str, AuthContext]
    # defines the context authentication, can be multiple accounts
    auth_path: Path
    # Path where auth will be saved / loaded 

    def __init__(self, target: str, agent_id: UUID) -> None:
        self.target = target
        self.agent_id = agent_id

    def list_authenticated(self) -> None:
        """
        Here we list the authenticated accounts
        """
        pass

    def load_context(self) -> None:
        """
        Loads a new profile name 
        """
        pass

    def save_auth_session(self) -> None:
        pass

    def update_auth_session(self) -> None:
        pass

    def get_context

    def authenticate(self, credential_ref: CredentialsRefs) -> None:
        pass