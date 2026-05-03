import os
import hashlib
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from common.workspace import list_code_files, read_code_file
from common.runs import record_step

_PKGS = "/tmp/backend-pkgs"
_PKGS_HASH = "/tmp/backend-pkgs.hash"


def _materialize(execution_id: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="ws-"))
    for rel in list_code_files(execution_id):
        dest = tmp / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(read_code_file(execution_id, rel))
    return tmp


def _pythonpath(extra: str | None = None) -> str:
    parts = [p for p in [extra, "/opt/python", os.environ.get("PYTHONPATH", "")] if p]
    return ":".join(parts)


def _run(cmd: list[str], cwd: Path, extra_env: dict | None = None) -> tuple[int, str]:
    env = {**os.environ, **(extra_env or {})}
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=120, env=env)
    return p.returncode, (p.stdout + p.stderr)[:8000]


def _install_reqs(ws: Path) -> None:
    req = ws / "requirements.txt"
    if not req.exists():
        return
    current_hash = hashlib.sha256(req.read_text().encode()).hexdigest()
    cached_hash = Path(_PKGS_HASH).read_text() if Path(_PKGS_HASH).exists() else ""
    if current_hash == cached_hash:
        return
    shutil.rmtree(_PKGS, ignore_errors=True)
    _run(["pip", "install", "-q", "-r", "requirements.txt",
          "--target", _PKGS, "--no-compile"], ws)
    Path(_PKGS_HASH).write_text(current_hash)


def handler(event, _ctx):
    execution_id = event["execution_id"]
    feature_id   = event["feature_id"]
    start = time.time()
    ws = _materialize(execution_id)
    issues = []
    try:
        if (ws / "app").exists():
            _install_reqs(ws)
            pp = _pythonpath(_PKGS)

            rc, out = _run(["python", "-m", "ruff", "check", "app/"], ws,
                           extra_env={"PYTHONPATH": pp})
            if rc != 0:
                issues.append({"tool": "ruff", "output": out})

            rc, out = _run(
                ["python", "-m", "mypy", "app/", "--ignore-missing-imports", "--no-error-summary"],
                ws,
                extra_env={"PYTHONPATH": pp},
            )
            if rc != 0:
                issues.append({"tool": "mypy", "output": out})

            rc, out = _run(
                ["python", "-c",
                 "import importlib, pkgutil; "
                 "[importlib.import_module(name) for _, name, _ in "
                 "pkgutil.walk_packages(['app'], prefix='app.')]"],
                ws,
                extra_env={"PYTHONPATH": pp},
            )
            if rc != 0:
                issues.append({
                    "tool": "import-check",
                    "output": out,
                    "hint": (
                        "App must be importable without environment variables set. "
                        "Move env-var reads inside functions, not module top level."
                    ),
                })
    finally:
        shutil.rmtree(ws, ignore_errors=True)

    passed = len(issues) == 0
    record_step(execution_id, feature_id, "validate-backend", "success" if passed else "failed",
                time.time() - start,
                metadata={"issues_count": len(issues), "tools_failed": [i["tool"] for i in issues]})
    return {
        "passed": passed,
        "issues": issues,
        "agent_to_repair": "backend" if not passed else None,
    }
