"""Secret access. Values are read when a provider call needs them and are not stored."""

from __future__ import annotations

import os
from typing import Mapping, Protocol

from ecommerce_agent.errors import PluginConfigError


class SecretSource(Protocol):
    def get(self, name: str) -> str | None:
        """Return the current value of a named secret, or None when it is unset."""


class EnvSecrets:
    """Read secrets from the process environment at call time."""

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self._env = env

    def get(self, name: str) -> str | None:
        source = os.environ if self._env is None else self._env
        value = source.get(name)
        if value is None or value.strip() == "":
            return None
        return value


class MapSecrets:
    """In-memory secret source for tests and local wiring."""

    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = dict(values)

    def get(self, name: str) -> str | None:
        value = self._values.get(name)
        if value is None or value.strip() == "":
            return None
        return value


def require_secret(secrets: SecretSource, name: str) -> str:
    value = secrets.get(name)
    if value is None:
        raise PluginConfigError(
            f"Missing environment variable {name}. Set it on your server and do not commit it."
        )
    return value
