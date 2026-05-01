"""Shared pytest configuration and fixtures."""
import os
import sys

# Ensure the project root is on sys.path so that `app` is importable
import pathlib
ROOT = pathlib.Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Set a safe APP_VERSION default for tests so the env var path is exercised
os.environ.setdefault("APP_VERSION", "1.0.0")

# Prevent any accidental real DB connections during unit tests by providing
# an obviously-fake DATABASE_URL if none is set. Integration tests that need
# a real DB should override this fixture.
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test_nova")
