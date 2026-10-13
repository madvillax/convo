"""Load non-ChatGPT settings; keep ChatGPT OAuth credentials in the OS keyring."""

from dataclasses import dataclass, field

EMBEDDING_DIMENSIONS = 1024


@dataclass(frozen=True)
class Settings:
    """Runtime settings shared by the backend services."""

    database_url: str = field(repr=False)
    embedding_model: str


def load_settings() -> Settings:
    """Replace this stub with the environment loader in backend.md step 2."""
    raise NotImplementedError("Implement settings loading following backend.md step 2")
