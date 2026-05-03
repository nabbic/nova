import os
import time
import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path
from common.workspace import list_code_files, read_code_file
from common.runs import record_step

_PKGS = "/tmp/ws-pkgs"
_PKGS_HASH = "/tmp/ws-pkgs.hash"

OWNERSHIP = {
    "app/db/migrations/": "database",
    "alembic.ini":        "database",
    "frontend/":          "frontend",
    "tests/":             "test",
    "infra/":             "infrastructure",
    "app/":               "backend",
    "Dockerfile":         "backend",
    "docker-compose.yml": "backend",
    ".dockerignore":      "backend",
    "requirements.txt":   "backend",
}


def _owner_for(path: str) -> str:
    for prefix, owner in sorted(OWNERSHIP.items(), key=lambda kv: -len(kv[0])):
        if path.startswith(prefix) or path == prefix:
            return owner
    return "backend"


def _materialize(execution_id: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="ws-"))
    for rel in list_code_files(execution_id):
        dest = tmp / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(read_code_file(execution_id, rel))
    return tmp


def _install_workspace_deps(ws: Path) -> None:
    parts = []
    for name in ("requirements.txt", "tests/requirements.txt"):
        f = ws / name
        if f.exists():
            parts.append(f.read_text())
    if not parts:
        return
    h = hashlib.sha256("\n".join(parts).encode()).hexdigest()
    cached = Path(_PKGS_HASH).read_text() if Path(_PKGS_HASH).exists() else ""
    if h == cached and Path(_PKGS).exists():
        return
    shutil.rmtree(_PKGS, ignore_errors=True)
    cmd = ["pip", "install", "-q", "--target", _PKGS, "--no-compile"]
    for name in ("requirements.txt", "tests/requirements.txt"):
        if (ws / name).exists():
            cmd += ["-r", str(ws / name)]
    subprocess.run(cmd, check=False, timeout=300)
    Path(_PKGS_HASH).write_text(h)


def _run(cmd, cwd, env_extra=None, timeout=120):
    env = {**os.environ, **(env_extra or {})}
    p = subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, env=env
    )
    return p.returncode, (p.stdout + p.stderr)[:8000]


def _python_path(ws: Path) -> str:
    return ":".join(filter(None, [
        _PKGS, str(ws), "/opt/python", os.environ.get("PYTHONPATH", "")
    ]))


def handler(event, _ctx):
    execution_id = event["execution_id"]
    feature_id   = event["feature_id"]
    phase        = event["phase"]   # "database" | "builders" | "test"
    start = time.time()

    ws = _materialize(execution_id)
    issues_by_owner: dict[str, list] = {}

    def add(owner: str, tool: str, output: str, hint: str = ""):
        issues_by_owner.setdefault(owner, []).append(
            {"tool": tool, "output": output, "hint": hint}
        )

    try:
        _install_workspace_deps(ws)
        pp = _python_path(ws)

        if phase in {"builders", "test"}:
            if (ws / "app").exists():
                rc, out = _run(["python", "-m", "ruff", "check", "app/"], ws, {"PYTHONPATH": pp})
                if rc != 0:
                    add("backend", "ruff", out)

                rc, out = _run(
                    ["python", "-m", "mypy", "app/",
                     "--ignore-missing-imports",
                     "--explicit-package-bases"],
                    ws, {"PYTHONPATH": pp},
                )
                if rc != 0:
                    add("backend", "mypy", out)

                rc, out = _run(
                    ["python", "-c",
                     "import importlib, pkgutil; "
                     "[importlib.import_module(n) for _,n,_ in "
                     "pkgutil.walk_packages(['app'], prefix='app.')]"],
                    ws, {"PYTHONPATH": pp},
                )
                if rc != 0:
                    add("backend", "import-check", out,
                        "App modules must be importable without env vars set; "
                        "move env reads inside functions.")

            if (ws / "infra" / "main.tf").exists():
                terraform = "/opt/bin/terraform"
                rc, out = _run(
                    [terraform, "fmt", "-check", "-recursive", "infra/"], ws
                )
                if rc != 0:
                    add("infrastructure", "terraform-fmt", out,
                        "Run `terraform fmt -recursive infra/`.")

                rc, out = _run(
                    [terraform, "init", "-backend=false", "-input=false"],
                    ws / "infra",
                )
                if rc != 0:
                    add("infrastructure", "terraform-init", out)
                else:
                    rc, out = _run([terraform, "validate"], ws / "infra")
                    if rc != 0:
                        add("infrastructure", "terraform-validate", out)

            if (ws / "frontend").exists() and (ws / "frontend" / "tsconfig.json").exists():
                rc, out = _run(
                    ["node", "/opt/node/tsc-runner.js", str(ws / "frontend")], ws
                )
                if rc != 0:
                    add("frontend", "tsc", out)

        if phase == "test" and (ws / "tests").exists():
            rc, out = _run(
                ["python", "-m", "pytest", "--collect-only", "-q", "tests/"],
                ws, {"PYTHONPATH": pp}, timeout=180,
            )
            if rc != 0:
                add("test", "pytest-collect", out)

        if phase in {"database", "builders"} and (ws / "app" / "db" / "migrations").exists():
            rc, out = _run(
                ["python", "-m", "alembic", "check"], ws, {"PYTHONPATH": pp}
            )
            # alembic check non-zero = pending migrations; informational, don't block
    finally:
        shutil.rmtree(ws, ignore_errors=True)

    passed = not issues_by_owner
    record_step(
        execution_id, feature_id, f"validate-workspace-{phase}",
        "success" if passed else "failed",
        time.time() - start,
        metadata={"failing_owners": list(issues_by_owner.keys())},
    )
    return {
        "passed": passed,
        "issues_by_owner": issues_by_owner,
        "failing_owners": list(issues_by_owner.keys()),
        "phase": phase,
    }
