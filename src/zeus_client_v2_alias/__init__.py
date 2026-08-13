"""Deprecated import path: use ``import zeus_client`` (2.0+)."""
from __future__ import annotations

import warnings

warnings.warn(
    "zeus_client_v2 is deprecated; import zeus_client (2.0+). "
    "Alias removes on or before 2.1.0.",
    DeprecationWarning,
    stacklevel=2,
)

from zeus_client import *  # noqa: F403
from zeus_client import __all__ as _all
from zeus_client import __version__

__all__ = list(_all)
