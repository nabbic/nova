import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from common.workspace import list_code_files, read_code_file
from common.runs import record_step

_PKGS = "/tmp/test-pkgs"


def _materialize(execution_id: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="ws-"))
    for rel in list_code_files(execution_id):
        dest = tmp / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(read_code_file(execution_id, rel))
    return tmp


def _run(cmd: list[str], cwd: Path, extra_env: dict | None = None) -> tuple[int, str]:
    env = {**os.environ, **(extra_env or {})}
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=180, env=env)
    return p.returncode, (p.stdout + p.stderr)[:8000]


def handler(event, _ctx):
    execution_id = event["execution_id"]
    feature_id   = event["feature_id"]
    start = time.time()
    ws = _materialize(execution_id)
    issues = []
    try:
        req = ws / "requirements.txt"
        if req.exists() and not Path(_PKGS).exists():
            _run(["pip", "install", "-q", "-r", "requirements.txt",
                  "--target", _PKGS, "--no-compile"], ws)

        tests_dir = ws / "tests"
        if tests_dir.exists():
            # Include Lambda layer path (/opt/python) explicitly — the runtime
            # adds it to sys.path but not necessarily to the PYTHONPATH env var
            pythonpath = ":".join(filter(None, [
                _PKGS, str(ws), "/opt/python", os.environ.get("PYTHONPATH", ""),
            ]))
            rc, out = _run(
                ["python", "-m", "pytest", "--collect-only", "-q", "tests/"],
                ws,
                extra_env={"PYTHONPATH": pythonpath},
            )
            if rc != 0:
                issues.append({"tool": "pytest-collect", "output": out})
    finally:
        shutil.rmtree(ws, ignore_errors=True)

    passed = len(issues) == 0
    record_step(execution_id, feature_id, "validate-test", "success" if passed else "failed",
                time.time() - start,
                metadata={"issues_count": len(issues)})
    return {
        "passed": passed,
        "issues": issues,
        "agent_to_repair": "test" if not passed else None,
    }
