"""Logging configuration import smoke test."""

import importlib
import logging


def test_logging_setup_import_and_levels():
    import zeus_client.logging_setup as ls

    importlib.reload(ls)
    assert ls.logger.name == "zeus_client"
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("uvicorn.access").level == logging.WARNING
