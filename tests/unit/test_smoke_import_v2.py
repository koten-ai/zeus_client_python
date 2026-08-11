"""Phase 0 smoke: V2 dual-tree package is importable."""


def test_v2_version_and_runtime_importable() -> None:
    import zeus_client_v2 as zc

    assert zc.__version__.startswith("2.")
    from zeus_client_v2.runtime import ZeusRuntime

    assert ZeusRuntime is not None
    assert "ZeusRuntime" in zc.__all__


def test_v1_still_importable_as_zeus_client() -> None:
    """Dual-tree: default import remains 0.3.1 oracle tree."""
    import zeus_client as zc

    assert hasattr(zc, "__version__") or hasattr(zc, "run_agent")
    # Package metadata stays 0.3.x until default-import cutover
    from zeus_client.constants import __version__ as v1

    assert v1.startswith("0.3")


def test_compat_v1_importable() -> None:
    from zeus_client_v2.compat import v1

    assert hasattr(v1, "run_agent")
    assert hasattr(v1, "run_search")
    assert hasattr(v1, "run_verb")
