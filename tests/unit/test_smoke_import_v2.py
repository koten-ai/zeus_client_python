"""Post-cutover smoke: default import is Runtime tree; alias deprecates."""

from __future__ import annotations

import warnings


def test_default_import_is_runtime_tree() -> None:
    import zeus_client as zc

    assert zc.__version__ == "2.3.0"
    from zeus_client import ZeusRuntime

    assert ZeusRuntime is not None
    assert "ZeusRuntime" in zc.__all__


def test_compat_v1_importable() -> None:
    from zeus_client.compat import v1

    assert hasattr(v1, "run_agent")
    assert hasattr(v1, "run_search")
    assert hasattr(v1, "run_verb")


def test_zeus_client_v2_alias_warns() -> None:
    # Fresh import path
    import sys

    for key in list(sys.modules):
        if key == "zeus_client_v2" or key.startswith("zeus_client_v2."):
            del sys.modules[key]

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        import zeus_client_v2 as alias

        assert alias.__version__ == "2.3.0"
        from zeus_client_v2 import ZeusRuntime

        assert ZeusRuntime is not None
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)
