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

class AuthType(str, Enum):
    """
    Depending on the return, or prelude information from the user, the 
    AuthType is defined to store the information in a certain way.
    """
    SESSION_COOKIE = "session_cookie"
    BEARER_TOKEN = "bearer_token"
    API_KEY = "api_key"
    OAUTH2 = "oauth2"

class AuthContext(BaseModel):
    auth_session_id: UUID
    auth_url: str | None
    target_origin: str | None
    auth_flow: AuthFlow | None
    auth_type: AuthType | None
    credential_ref: CredentialsRefs | None

class AuthHandler:
    browser: Any 
    # Browser used
    auth_contexts: dict[UUID, AuthContext]
    # defines the context authentication, can be multiple accounts
    auth_path: Path
    # Path where auth will be saved / loaded 

    def __init__(self) -> None:
        pass

    def list_authenticated(self) -> None:
        """
        Here we list the authenticated accounts
        """
        pass

    def load_auth_session(self) -> None:
        """
        
        """
        pass

    def save_auth_session(self) -> None:
        pass

    def authenticate(self, auth_context: AuthContext) -> None:
        if not auth_context.auth_session_id in self.auth_contexts.keys():
            # which means the auth_session_id is already in the auth_con
            pass