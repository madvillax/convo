"""Secure token storage and owner-only account metadata for local sign-in."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from convo.core.contracts import REASONING_EFFORTS, ReasoningEffort


class CredentialStore(Protocol):
    """Small seam around secure local token storage."""

    def save(self, key: str, value: str) -> None: ...

    def load(self, key: str) -> str | None: ...

    def delete(self, key: str) -> None: ...


class KeyringCredentialStore:
    """Store OAuth secrets in the operating system's credential manager."""

    service_name = "convo"

    def save(self, key: str, value: str) -> None:
        import keyring

        keyring.set_password(self.service_name, key, value)

    def load(self, key: str) -> str | None:
        import keyring

        return keyring.get_password(self.service_name, key)

    def delete(self, key: str) -> None:
        import keyring
        from keyring.errors import PasswordDeleteError

        try:
            keyring.delete_password(self.service_name, key)
        except PasswordDeleteError:
            pass


@dataclass(frozen=True)
class AccountProfile:
    """Non-secret metadata for the one ChatGPT account connected to this CLI."""

    client_id: str
    subject: str
    email: str | None
    name: str | None
    issuer: str
    scopes: tuple[str, ...]
    expires_at: float
    selected_model: str | None = None
    selected_model_name: str | None = None
    selected_reasoning_effort: ReasoningEffort | None = None

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> AccountProfile:
        scopes = value.get("scopes")
        if not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes):
            raise ValueError("Invalid scopes in saved ChatGPT profile")
        client_id = value.get("client_id")
        subject = value.get("subject")
        issuer = value.get("issuer")
        expires_at = value.get("expires_at")
        email = value.get("email")
        name = value.get("name")
        selected_model = value.get("selected_model")
        selected_model_name = value.get("selected_model_name")
        selected_effort = value.get("selected_reasoning_effort")
        if not isinstance(client_id, str) or not client_id:
            raise ValueError("Invalid identity in saved ChatGPT profile")
        if not isinstance(subject, str) or not subject:
            raise ValueError("Invalid identity in saved ChatGPT profile")
        if not isinstance(issuer, str) or not issuer:
            raise ValueError("Invalid identity in saved ChatGPT profile")
        if not isinstance(expires_at, (float, int)):
            raise ValueError("Invalid expiry in saved ChatGPT profile")
        if email is not None and not isinstance(email, str):
            raise ValueError("Invalid email in saved ChatGPT profile")
        if name is not None and not isinstance(name, str):
            raise ValueError("Invalid name in saved ChatGPT profile")
        if selected_model is not None and not isinstance(selected_model, str):
            raise ValueError("Invalid selected model in saved ChatGPT profile")
        return cls(
            client_id=client_id,
            subject=subject,
            email=email,
            name=name,
            issuer=issuer,
            scopes=tuple(scopes),
            expires_at=float(expires_at),
            selected_model=selected_model,
            selected_model_name=selected_model_name
            if isinstance(selected_model_name, str)
            else None,
            selected_reasoning_effort=(
                selected_effort
                if isinstance(selected_effort, str) and selected_effort in REASONING_EFFORTS
                else None
            ),
        )


def default_config_dir() -> Path:
    """Return the per-user config directory; allow a test/developer override."""
    override = os.environ.get("CONVO_CONFIG_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "convo"
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "convo"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "convo"


class AccountProfileStore:
    """Persist a stable host ID and non-secret account details outside the repo."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = (directory or default_config_dir()).expanduser()
        self.profile_path = self.directory / "chatgpt-profile.json"
        self.host_id_path = self.directory / "host-id"

    def _ensure_private_directory(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            self.directory.chmod(0o700)

    def host_id(self) -> str:
        self._ensure_private_directory()
        try:
            value = self.host_id_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            value = ""
        if value.startswith("urn:uuid:") and len(value) == len("urn:uuid:") + 36:
            return value

        from uuid import uuid4

        value = f"urn:uuid:{uuid4()}"
        self._write_private(self.host_id_path, value.encode("utf-8"))
        return value

    def load(self) -> AccountProfile | None:
        try:
            raw = self.profile_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("Saved ChatGPT profile must be a JSON object")
            return AccountProfile.from_dict(value)
        except (json.JSONDecodeError, ValueError) as error:
            raise ValueError("Saved ChatGPT profile is invalid; sign in again") from error

    def save(self, profile: AccountProfile) -> None:
        self._ensure_private_directory()
        content = json.dumps(asdict(profile), indent=2, sort_keys=True).encode("utf-8")
        self._write_private(self.profile_path, content)

    @staticmethod
    def _write_private(path: Path, content: bytes) -> None:
        """Atomically replace a file and keep it owner-readable on Unix."""
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary_path = Path(temporary_name)
        try:
            if os.name != "nt":
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, path)
            if os.name != "nt":
                path.chmod(0o600)
        finally:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
