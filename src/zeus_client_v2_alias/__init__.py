"""Deprecated import path: use ``import zeus_client`` (2.0+).

This module re-exports the default package and installs a meta path hook so
submodule imports such as ``zeus_client_v2.adapters…`` resolve to the same
objects as ``zeus_client.adapters…`` for one minor (Travel/sample BFFs).
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import sys
import warnings

warnings.warn(
    "zeus_client_v2 is deprecated; import zeus_client (2.0+). Alias removes on or before 2.1.0.",
    DeprecationWarning,
    stacklevel=2,
)

import zeus_client as _zc

# Public re-export
from zeus_client import *  # noqa: F403
from zeus_client import __all__ as _all
from zeus_client import __version__

__all__ = list(_all)


class _ZeusClientV2AliasFinder(importlib.abc.MetaPathFinder):
    """Map zeus_client_v2.* → zeus_client.* for the deprecation window."""

    _PREFIX = "zeus_client_v2"

    def find_spec(self, fullname, path, target=None):  # noqa: ANN001
        if fullname != self._PREFIX and not fullname.startswith(self._PREFIX + "."):
            return None
        real = "zeus_client" + fullname[len(self._PREFIX) :]
        # Load (or fetch) the real module, then register under the alias name.
        try:
            mod = importlib.import_module(real)
        except ModuleNotFoundError:
            return None
        sys.modules[fullname] = mod
        # Return a loader that just returns the already-bound module.
        return importlib.machinery.ModuleSpec(
            fullname,
            _AliasLoader(mod),
            is_package=hasattr(mod, "__path__"),
        )


class _AliasLoader(importlib.abc.Loader):
    def __init__(self, module):  # noqa: ANN001
        self._module = module

    def create_module(self, spec):  # noqa: ANN001
        return self._module

    def exec_module(self, module):  # noqa: ANN001
        return None


# Install once
if not any(isinstance(f, _ZeusClientV2AliasFinder) for f in sys.meta_path):
    sys.meta_path.insert(0, _ZeusClientV2AliasFinder())

# Ensure top-level alias name is this module (with warn already fired)
sys.modules.setdefault("zeus_client_v2", sys.modules[__name__])
