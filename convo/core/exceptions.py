"""Errors the UI and backend use to communicate expected failure states."""


class BackendNotConnected(RuntimeError):
    """The selected backend operation needs credentials or setup."""
