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
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=120)
    return p.returncode, (p.stdout + p.stderr)[:8000]


def handler(event, _ctx):
    execution_id = event["execution_id"]
    feature_id   = event["feature_id"]
    start = time.time()
    ws = _materialize(execution_id)
    issues = []
    try:
        infra_dir = ws / "infra"
        if infra_dir.exists():
            # NOTE: terraform binary must be in PATH on the Lambda execution environment.
            # If not present, these checks are skipped with a warning rather than crashing.
            try:
                rc, out = _run(["terraform", "fmt", "-check", "-recursive", "infra/"], ws)
                if rc != 0:
                    issues.append({
                        "tool": "terraform-fmt",
                        "output": out,
                        "hint": "Run `terraform fmt -recursive infra/` to fix.",
                    })
            except FileNotFoundError:
                issues.append({
                    "tool": "terraform-fmt",
                    "output": "terraform binary not found in Lambda PATH — skipping fmt check",
                    "hint": "Add terraform to the Lambda layer or use a container image.",
                })

            try:
                rc, out = _run(["terraform", "init", "-backend=false", "-input=false"], infra_dir)
                if rc != 0:
                    issues.append({"tool": "terraform-init", "output": out})
                else:
                    rc, out = _run(["terraform", "validate"], infra_dir)
                    if rc != 0:
                        issues.append({"tool": "terraform-validate", "output": out})
            except FileNotFoundError:
                issues.append({
                    "tool": "terraform-validate",
                    "output": "terraform binary not found in Lambda PATH — skipping validate check",
                    "hint": "Add terraform to the Lambda layer or use a container image.",
                })
    finally:
        shutil.rmtree(ws, ignore_errors=True)

    passed = len(issues) == 0
    record_step(execution_id, feature_id, "validate-infrastructure", "success" if passed else "failed",
                time.time() - start,
                metadata={"issues_count": len(issues)})
    return {
        "passed": passed,
        "issues": issues,
        "agent_to_repair": "infrastructure" if not passed else None,
    }
