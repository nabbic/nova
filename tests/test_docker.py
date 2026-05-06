import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parent.parent
_docker_available = shutil.which("docker") is not None


@pytest.mark.skipif(not _docker_available, reason="docker not installed")
def test_docker_build():
    result = subprocess.run(
        ["docker", "build", "-t", "nova-api:test", "."],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not _docker_available, reason="docker not installed")
def test_app_main_importable():
    result = subprocess.run(
        ["docker", "run", "--rm", "nova-api:test", "python", "-c", "from app.main import app"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
