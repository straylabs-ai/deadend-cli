from typing import Dict, Any
import json
from pathlib import Path
from pydantic import BaseModel


class AuthInfo(BaseModel):
    """AuthInfo structure for agentic usage with playwright"""
    session_id: str
    username: str
    password: str
    token: str
    cookies: list[str]

    def save_session(self):
        pass

    def load_session(self):
        pass


def load_reusable_credentials() -> Dict[str, Any]:
    """
    Load reusable credentials from the JSON file.
    
    Returns:
        Dict[str, Any]: Dictionary containing credentials data
    """
    try:
        credentials_path = Path.home() / ".cache" /\
            "deadend" / "memory" / "reusable_credentials.json"
        with open(credentials_path, 'r', encoding='utf-8') as f:
            creds = f.read()
            return json.loads(creds)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Warning: Could not load reusable credentials: {e}")
        return {"accounts": []}

def replace_credential_placeholders(request_data: str, account_index: int = 0) -> str:
    """
    Replace credential placeholders in request data with actual values 
        from reusable_credentials.json.
    
    Args:
        request_data (str): Raw HTTP request string containing placeholders
        account_index (int): Index of the account to use from the credentials file (default: 0)
        
    Returns:
        str: Request data with placeholders replaced by actual credential values
    """
    credentials = load_reusable_credentials()
    accounts = credentials.get("accounts", [])

    if not accounts or account_index >= len(accounts):
        print(f"Warning: No account found at index {account_index}")
        return request_data

    account = accounts[account_index]
    replaced_data = request_data
    # replacing the dummy email with the email
    replaced_data = replaced_data.replace(
        account.get("dummy_email"),
        # "<dummy_email>",
        account.get("email")
    )
    # replacing the dummy username with the username
    replaced_data = replaced_data.replace(
        account.get("dummy_username"),
        # "<dummy_username>",
        account.get("username")
    )
    # replacing the dummy password with the password
    replaced_data = replaced_data.replace(
        account.get("dummy_password"),
        # "<dummy_password>",
        account.get("password")
    )
    return replaced_data
