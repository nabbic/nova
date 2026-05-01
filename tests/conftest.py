"""Shared pytest configuration and fixtures."""
import os
import sys
import pytest

# Ensure the repository root is on sys.path so `app` is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def _clean_version_env():
    """Guarantee VERSION env var is unset before every test unless the test sets it."""
    original = os.environ.pop("VERSION", None)
    yield
    if original is None:
        os.environ.pop("VERSION", None)
    else:
        os.environ["VERSION"] = original
