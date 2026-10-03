"""Credential and environment handling.

Keys are read from the environment, optionally populated from a `.env` file that
is never committed. Nothing in this package accepts a key as a function
argument: a key passed around as a value ends up in a traceback, a notebook
output, or a log line eventually.
"""

from __future__ import annotations

import os
from typing import Final

from dotenv import load_dotenv

__all__ = ["MissingCredentialError", "api_key", "load_environment"]

_loaded = False

#: Environment variable names, gathered here so `.env.example` can be checked
#: against the code rather than drifting from it.
RWA_XYZ_KEY_VAR: Final = "RWA_XYZ_API_KEY"
DUNE_KEY_VAR: Final = "DUNE_API_KEY"
DUNE_TRANSFERS_QUERY_VAR: Final = "DUNE_TRANSFERS_QUERY_ID"
DUNE_HOLDERS_QUERY_VAR: Final = "DUNE_HOLDERS_QUERY_ID"


class MissingCredentialError(Exception):
    """A source needs a credential that is not set."""

    def __init__(self, variable: str, source: str) -> None:
        """Say which variable is missing and how to supply it."""
        self.variable = variable
        self.source = source
        super().__init__(
            f"{source} needs {variable}, which is not set. Copy .env.example to .env "
            f"and fill it in, or export the variable. No key is needed to run "
            f"`rwa-liquidity report --demo`."
        )


def load_environment() -> None:
    """Load `.env` into the environment, once per process.

    Existing environment variables win over the file, so an explicit export or a
    CI secret is never silently overridden by a stale local `.env`.
    """
    global _loaded  # noqa: PLW0603 -- one process-wide load, guarded by a flag
    if not _loaded:
        load_dotenv(override=False)
        _loaded = True


def api_key(variable: str, *, source: str) -> str:
    """Return the credential in `variable`.

    Args:
        variable: Environment variable name.
        source: Adapter name, for the error message.

    Returns:
        The credential.

    Raises:
        MissingCredentialError: If the variable is unset or empty.
    """
    load_environment()
    value = os.environ.get(variable, "").strip()
    if not value:
        raise MissingCredentialError(variable, source)
    return value


def optional_setting(variable: str) -> str | None:
    """Return an optional environment setting, or `None` if it is unset."""
    load_environment()
    value = os.environ.get(variable, "").strip()
    return value or None
