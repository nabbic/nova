import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from common.workspace import list_code_files, read_code_file
from common.runs import record_step

_PKGS = "/tmp/test-pkgs"
_PKGS_HASH = "/tmp/test-pkgs.hash"


def _materialize(execution_id: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="ws-"))
    for rel in list_code_files(execution_id):
        dest = tmp / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(read_code_file(execution_id, rel))
    return tmp


def _req_hash(ws: Path) -> str:
    import hashlib
    parts = []
    for name in ("requirements.txt", "tests/requirements.txt"):
        f = ws / name
        if f.exists():
            parts.append(f.read_text())
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


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
        current_hash = _req_hash(ws)
        cached_hash = Path(_PKGS_HASH).read_text() if Path(_PKGS_HASH).exists() else ""
        if current_hash != cached_hash:
            shutil.rmtree(_PKGS, ignore_errors=True)
            reqs_to_install = []
            for name in ("requirements.txt", "tests/requirements.txt"):
                if (ws / name).exists():
                    reqs_to_install.extend(["-r", name])
            if reqs_to_install:
                _run(["pip", "install", "-q"] + reqs_to_install +
                     ["--target", _PKGS, "--no-compile"], ws)
            Path(_PKGS_HASH).write_text(current_hash)

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
