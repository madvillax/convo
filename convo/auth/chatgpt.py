"""ChatGPT OAuth login and token refresh; storage is delegated to credentials.py."""

from convo.auth.credentials import CredentialStore


class ChatGPTAuth:
    """Own the loopback callback and locally stored Sign in with ChatGPT profile."""

    def __init__(self, credentials: CredentialStore) -> None:
        self.credentials = credentials

    async def login(self) -> str:
        raise NotImplementedError("Implement the SIWC flow described in backend.md step 8")

    async def access_token(self) -> str:
        raise NotImplementedError("Refresh and return a valid, scope-checked SIWC token")
