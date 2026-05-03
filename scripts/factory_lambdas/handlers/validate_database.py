import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from common.workspace import list_code_files, read_code_file
from common.runs import record_step


def _materialize(execution_id: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="ws-"))
    for rel in list_code_files(execution_id):
        dest = tmp / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(read_code_file(execution_id, rel))
    return tmp


def _run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    env = {**os.environ, "PYTHONPATH": ":".join(filter(None, [
        "/opt/python", os.environ.get("PYTHONPATH", ""),
    ]))}
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=60, env=env)
    return p.returncode, (p.stdout + p.stderr)[:8000]


def handler(event, _ctx):
    execution_id = event["execution_id"]
    feature_id   = event["feature_id"]
    start = time.time()
    ws = _materialize(execution_id)
    issues = []
    try:
        migrations_dir = ws / "app" / "db" / "migrations"
        if migrations_dir.exists():
            for mig in sorted(migrations_dir.glob("*.py")):
                rc, out = _run(["python", "-m", "py_compile", str(mig)], ws)
                if rc != 0:
                    issues.append({"tool": "py_compile", "file": mig.name, "output": out})
    finally:
        shutil.rmtree(ws, ignore_errors=True)

    passed = len(issues) == 0
    record_step(execution_id, feature_id, "validate-database", "success" if passed else "failed",
                time.time() - start,
                metadata={"issues_count": len(issues)})
    return {
        "passed": passed,
        "issues": issues,
        "agent_to_repair": "database" if not passed else None,
    }
