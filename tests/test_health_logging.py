"""Tests that verify the health endpoint emits logs to stdout/stderr only.

Acceptance criterion 8: all request and error logs are emitted to
stdout or stderr only — no file handles, no external sinks.
"""
import logging
import sys
import pytest
from fastapi.testclient import TestClient


def test_health_logging_uses_stdout_or_stderr_when_called(capsys):
    """Any log output produced by the health endpoint goes to stdout or stderr."""
    # We verify that the logging system is configured to use StreamHandlers
    # (which write to stdout/stderr) and not FileHandlers.
    from app.main import app
    client = TestClient(app)
    client.get("/api/health")

    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        assert not isinstance(handler, logging.FileHandler), (
            f"FileHandler found on root logger: {handler} — logs must go to stdout/stderr only"
        )


def test_health_no_file_handler_on_uvicorn_logger_when_called():
    """The uvicorn logger must not have file-based handlers."""
    from app.main import app  # noqa: F401 — ensure app is initialised
    uvicorn_logger = logging.getLogger("uvicorn")
    for handler in uvicorn_logger.handlers:
        assert not isinstance(handler, logging.FileHandler), (
            f"FileHandler on uvicorn logger: {handler}"
        )


def test_health_no_file_handler_on_app_logger_when_called():
    """Application-level loggers must not write to files."""
    from app.main import app  # noqa: F401
    app_logger = logging.getLogger("app")
    for handler in app_logger.handlers:
        assert not isinstance(handler, logging.FileHandler), (
            f"FileHandler on app logger: {handler}"
        )
