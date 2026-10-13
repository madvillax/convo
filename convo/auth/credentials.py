"""Keep OAuth tokens in the operating-system credential store."""

from typing import Protocol


class CredentialStore(Protocol):
    """Small seam around secure local token storage."""

    def save(self, key: str, value: str) -> None: ...

    def load(self, key: str) -> str | None: ...

    def delete(self, key: str) -> None: ...


class KeyringCredentialStore:
    """Store OAuth secrets in the operating system's credential manager."""

    def save(self, key: str, value: str) -> None:
        import keyring

        keyring.set_password("convo", key, value)

    def load(self, key: str) -> str | None:
        import keyring

        return keyring.get_password("convo", key)

    def delete(self, key: str) -> None:
        import keyring
        from keyring.errors import PasswordDeleteError

        try:
            keyring.delete_password("convo", key)
        except PasswordDeleteError:
            pass
