"""Validate-v2 — deterministic 6-step validation chain. Spec §2.4.

Runs in a Lambda container with ruff/mypy/pytest/terraform/tsc/alembic
pre-installed. Materializes the workspace from S3, runs each step, collects
issues, and writes issues.json back. No LLM, no per-agent routing.

Stops AT THE FIRST FAILING STEP — there's no value in running mypy if ruff
flagged 30 syntax errors. Caller (SFN) routes to ValidateRepair on any
non-empty issues array.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import boto3

BUCKET = os.environ["WORKSPACE_BUCKET"]
WS_ROOT = Path("/tmp/ws")

_s3 = boto3.client("s3")


def _materialize(execution_id: str) -> None:
    if WS_ROOT.exists():
        shutil.rmtree(WS_ROOT)
    WS_ROOT.mkdir(parents=True)
    prefix = f"{execution_id}/workspace/"
    paginator = _s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            rel = key[len(prefix):]
            if not rel or rel.endswith("/") or rel == ".git.tar.gz":
                continue
            dest = WS_ROOT / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            _s3.download_file(BUCKET, key, str(dest))


def _issue(tool: str, file: str, line: int, output: str, hint: str = "") -> dict:
    return {"tool": tool, "file": file, "line": line, "output": output[:1000], "hint": hint}


def _run(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def _step_ruff() -> list[dict]:
    rc, out, err = _run([sys.executable, "-m", "ruff", "check", "--output-format=json", "."], WS_ROOT)
    if rc == 0:
        return []
    try:
        items = json.loads(out)
    except Exception:
        return [_issue("ruff", "?", 0, (out + err)[:1000], "ruff stdout unparseable")]
    return [_issue("ruff", i.get("filename", "?"), i.get("location", {}).get("row", 0),
                   f"{i.get('code')}: {i.get('message')}",
                   (i.get("fix", {}) or {}).get("message", ""))
            for i in items]


def _step_mypy() -> list[dict]:
    if not (WS_ROOT / "app").exists():
        return []
    rc, out, err = _run([sys.executable, "-m", "mypy", "--explicit-package-bases", "--no-color-output", "app/"], WS_ROOT)
    if rc == 0:
        return []
    issues: list[dict] = []
    for line in (out + err).splitlines():
        parts = line.split(":", 3)
        if len(parts) < 4 or "error" not in parts[2]:
            continue
        try:
            ln = int(parts[1])
        except ValueError:
            ln = 0
        issues.append(_issue("mypy", parts[0], ln, parts[3].strip(), ""))
    if not issues and rc != 0:
        issues.append(_issue("mypy", "?", 0, (out + err)[:1000], ""))
    return issues


def _step_pytest() -> list[dict]:
    if not (WS_ROOT / "tests").exists():
        return [_issue("pytest", "tests/", 0, "tests/ directory missing", "RalphTurn must add tests")]
    for req in [WS_ROOT / "requirements.txt", WS_ROOT / "tests" / "requirements.txt"]:
        if req.is_file():
            _run([sys.executable, "-m", "pip", "install", "-q", "-r", str(req)], WS_ROOT)
    rc, out, err = _run([sys.executable, "-m", "pytest", "tests/", "-x", "-q", "--tb=short"], WS_ROOT)
    if rc == 0:
        return []
    return [_issue("pytest", "tests/", 0, (out + err)[-2000:], "Failing test(s); RalphTurn must fix before re-validation")]


def _step_terraform() -> list[dict]:
    tf_dirs = sorted({p.parent for p in WS_ROOT.rglob("*.tf")})
    issues: list[dict] = []
    factory_dir = WS_ROOT / "infra" / "factory"
    for d in tf_dirs:
        try:
            d.relative_to(factory_dir)
            continue  # factory infra is sandboxed and not editable by Ralph
        except ValueError:
            pass
        rc, out, err = _run(["terraform", "fmt", "-check"], d)
        if rc != 0:
            issues.append(_issue("terraform fmt", str(d.relative_to(WS_ROOT)), 0, (out+err)[:1000], "Run `terraform fmt`"))
        rc, out, err = _run(["terraform", "init", "-backend=false", "-input=false"], d)
        if rc != 0:
            issues.append(_issue("terraform init", str(d.relative_to(WS_ROOT)), 0, (out+err)[-1000:], ""))
            continue
        rc, out, err = _run(["terraform", "validate", "-no-color"], d)
        if rc != 0:
            issues.append(_issue("terraform validate", str(d.relative_to(WS_ROOT)), 0, (out+err)[-1000:], ""))
    return issues


def _step_tsc() -> list[dict]:
    fe = WS_ROOT / "frontend"
    if not fe.is_dir() or not (fe / "tsconfig.json").is_file():
        return []
    rc, out, err = _run(["tsc", "--noEmit", "-p", str(fe / "tsconfig.json")], WS_ROOT)
    if rc == 0:
        return []
    return [_issue("tsc", "frontend/", 0, (out+err)[-2000:], "")]


def _step_alembic() -> list[dict]:
    mig = WS_ROOT / "app" / "db" / "migrations"
    if not mig.is_dir():
        return []
    rc, out, err = _run([sys.executable, "-m", "alembic", "check"], WS_ROOT)
    if rc == 0:
        return []
    return [_issue("alembic", "app/db/migrations/", 0, (out+err)[-1000:], "Migration check failed")]


def handler(event, _ctx):
    execution_id = event["execution_id"]
    _materialize(execution_id)

    issues: list[dict] = []
    for step in (_step_ruff, _step_mypy, _step_pytest, _step_terraform, _step_tsc, _step_alembic):
        step_issues = step()
        issues.extend(step_issues)
        if step_issues:
            break  # short-circuit on first failure

    passed = len(issues) == 0
    payload = {"passed": passed, "issues": issues}

    _s3.put_object(
        Bucket=BUCKET,
        Key=f"{execution_id}/validate/issues.json",
        Body=json.dumps(payload, indent=2).encode("utf-8"),
        ContentType="application/json",
    )

    if not passed:
        body = "# Validate failures (must address before re-validation)\n\n"
        for it in issues:
            body += f"## {it['tool']} — {it['file']}:{it['line']}\n\n{it['output']}\n\n"
            if it.get("hint"):
                body += f"_Hint:_ {it['hint']}\n\n"
        _s3.put_object(
            Bucket=BUCKET,
            Key=f"{execution_id}/workspace/repair_context.md",
            Body=body.encode("utf-8"),
            ContentType="text/markdown",
        )

    return payload
