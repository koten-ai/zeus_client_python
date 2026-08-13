"""Env-backed SecretStore — resolves secret *values* at use time only."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping

__all__ = ["EnvSecretStore", "SecretStorePort"]


class SecretStorePort:
    """Protocol-shaped secret lookup (also defined under ports.secrets)."""

    def get(self, name: str) -> str | None:
        raise NotImplementedError


@dataclass
class EnvSecretStore(SecretStorePort):
    """Read secrets from a mapping (default: os.environ)."""

    environ: Mapping[str, str] = field(default_factory=lambda: os.environ)

    def get(self, name: str) -> str | None:
        if not name:
            return None
        val = self.environ.get(name)
        if val is None or val == "":
            return None
        return val

    def __repr__(self) -> str:
        # Never dump environ contents.
        return f"EnvSecretStore(keys={len(self.environ)})"
