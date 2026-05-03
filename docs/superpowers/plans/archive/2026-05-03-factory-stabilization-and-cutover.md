# Nova Factory — Stabilization & First-Clean-Smoke Plan

**Date:** 2026-05-03 (afternoon)
**Owner:** Sonnet (autonomous execution)
**Branch:** `factory-overhaul-2026-05-03` (continue on the existing branch)
**Status:** Ready to execute
**Predecessor:** `2026-05-03-factory-cost-and-robustness-overhaul.md`
**Counterpart:** `2026-05-03-factory-overhaul-execution-summary.md`

---

## Why this plan exists

The original overhaul shipped Phases 1–7, 9, and 10. Phase 8 (smoke + cutover) is stuck — 13 smoke runs, all failing. The `factory.yml` GitHub Actions backend is still live; `FACTORY_BACKEND` is still `"github-actions"`.

I audited the implementation against the original plan and the in-flight code. Sonnet executed the plan competently. The 10 bugs found during execution are real and the fixes are reasonable. But the symptoms in smoke13 (eight separate `ValidationExhausted` events) point to **architectural problems in how validators interact with parallel agent execution**, not just more fix-this-one-bug work.

This plan fixes those architectural issues, then reaches a clean smoke run, then cuts over.

---

## Triage — what is actually wrong

### Root cause #1: validators race against in-flight peer agents (CRITICAL)

`infra/factory/state-machine.json.tpl:125–243` runs each agent inside an inner Map (`FanOut`, `MaxConcurrency: 5`). Each agent goes immediately into `ChooseValidator → ValidateAgent` upon completion, **regardless of whether sibling agents in the same parallel group have finished**.

Concrete failure path observed in smoke13:
1. Group `["backend", "frontend", "infrastructure", "test"]` fans out
2. Test agent finishes first (smaller output)
3. `validate_test` Lambda fires — downloads workspace, runs `pytest --collect-only`
4. Workspace has `tests/` from test agent but no `app/` from backend yet (or no `requirements.txt`)
5. `pytest --collect-only` fails: `ModuleNotFoundError: No module named 'app'`
6. Test agent enters repair loop with `repair_context = "app module missing"`
7. Test agent re-runs, still can't fix — it doesn't own `app/`
8. `ValidationExhausted` after 2 cycles → group fails → execution fails

The same pattern hits backend (waiting for infrastructure-provided env), frontend (waiting for backend's openapi.json), etc.

The orchestrator's example schema in `.claude/agents/orchestrator.md:30-34` shows the **right** grouping:
```json
[["database"], ["backend", "frontend", "infrastructure"], ["test"]]
```
…but nothing enforces this in the state machine. The orchestrator can (and apparently does) emit looser groupings.

### Root cause #2: validators have non-trivial ordering dependencies the architecture doesn't model

Even with the right `parallel_groups`, `validate_backend` needs the workspace requirements.txt produced by *backend itself*, plus any `.tf` files from *infrastructure*, before it can verify imports under realistic conditions. Today each validator only knows about its own agent's output.

### Root cause #3: subprocess gymnastics in validators

`validate_backend.py`, `validate_test.py`, `validate_database.py` all juggle:
- A `/tmp/<agent>-pkgs` directory with hash-based pip cache invalidation
- Manual `PYTHONPATH` construction including `/opt/python` because Lambda's layer path isn't propagated to subprocesses
- A workspace materialization step that runs on every invocation
- `cygpath` workarounds for Windows-built layer artifacts

This is brittle. Bug 7 (subprocess can't see layer), Bug 8 (warm container caches stale pkgs), Bug 9 (httpx missing), Bug 10 (subprocess can't see workspace deps) are all symptoms of the same architectural error: **subprocesses aren't a good fit for Lambda when you need full workspace materialization + dependency installation**.

### Root cause #4: streaming Lambda I/O is the wrong cost shape

Bug 6 forced switching to `client.messages.stream()`. This is correct for Anthropic API ≥0.40, BUT a streaming call holds the Lambda open for the *entire* response duration — 5 to 15 minutes for a backend agent. The Lambda is billed for that wall-clock time at 2GB. This is exactly the cost shape the user moved off GitHub Actions to escape.

Multiplied across 9 agents × parallel branches × repair retries, this can dominate the Lambda spend.

### Root cause #5: tooling friction makes iteration painful

- Stray `lambda-layer;C/` directory (escaping bug from Windows path conversion) sitting in `infra/factory/` — never cleaned up.
- Bug 8/9/10 fixes are uncommitted in working directory — high risk of being lost or rolled back during further debugging.
- Warm container cache (15-45 min) means a fix may not take effect on the next smoke run, leading to false-failure debugging spirals.
- No way to trigger the state machine with a synthetic fixture instead of a real Notion feature, so each iteration costs Anthropic tokens + waits 10+ minutes.

### Secondary observations

- `validate_infrastructure.py` is shipped as a regular zip Lambda but the original plan called for a container image (because it needs the `terraform` binary). Need to verify it actually has a working `terraform` binary on `$PATH`.
- `lambdas.tf` only ships a single Lambda `nova-factory-validate-infrastructure` (3KB zip) — a 3KB zip cannot contain Terraform. Either it's bundled in the layer (check size) or this validator silently passes everything.
- Per-agent CloudWatch metrics from Phase 9's dashboard exist but no Logs Insights queries are saved to surface "which agent's repair loop is failing this run". Debugging requires raw CloudWatch log spelunking.

---

## Strategy

Two layers of fix:

**Layer A — Get smoke green ASAP** (Phases A1–A4): the smallest changes that eliminate the race, simplify validators, and produce a passing smoke run. Same Lambda+Step Functions architecture, same agent execution model.

**Layer B — Architectural simplification** (Phases B1–B3): consolidate the validation pattern, remove subprocess gymnastics, add iteration tooling. These are higher leverage but bigger diffs; do them after smoke is green so you have a reliable baseline to test against.

**Layer C — Long-term cost wins** (Phase C, *optional*): replace Anthropic API + Lambda streaming with Bedrock + Step Functions native invocation. This is the right answer for sustained cost-effectiveness but isn't required to get smoke working. Call out, don't gate cutover on it.

---

## Phase A0 — Triage commit & cleanup (do first, takes 10 min)

1. Commit the uncommitted Bug 8/9/10 fixes so they don't get lost. Use a single commit:
   ```bash
   cd /c/Claude/Nova/nova
   git add scripts/factory_lambdas/handlers/validate_backend.py \
           scripts/factory_lambdas/handlers/validate_database.py \
           scripts/factory_lambdas/handlers/validate_test.py \
           infra/factory/lambda-layer/requirements.txt
   git commit -m "fix(factory): bug 8/9/10 — workspace pkg install, httpx in layer, validator subprocess PYTHONPATH"
   ```

2. Delete the stray `infra/factory/lambda-layer;C/` directory (artifact from a Windows path-conversion bug):
   ```bash
   rm -rf "/c/Claude/Nova/nova/infra/factory/lambda-layer;C"
   ```
   Verify nothing references it (`grep -r 'lambda-layer;C' infra/ scripts/`). Commit the deletion.

3. Add `*tfplan` and `infra/*/python/` and `infra/factory/lambda-layer/python/` to `.gitignore` so build artifacts stop showing in `git status`.

4. Before any further changes, snapshot current Lambda code versions for rollback:
   ```bash
   for fn in $(aws lambda list-functions --query 'Functions[?starts_with(FunctionName, `nova-factory-`)].FunctionName' --output text); do
     aws lambda get-function --function-name "$fn" --query 'Configuration.[FunctionName,Version,LastModified]' --output text
   done > /tmp/factory-lambda-snapshot-pre-stabilization.txt
   ```
   Commit that file to the branch as `docs/runbooks/factory-lambda-snapshot.txt` for incident recovery.

**Done when:** clean `git status`, no stray directory, snapshot saved.

---

## Phase A1 — Fix the parallel-execution race (the big one)

The orchestrator should emit groups that respect dependency order, AND the state machine should enforce a fallback ordering even if the orchestrator gets it wrong.

### A1.1 Hardcode safe ordering in the state machine

In `infra/factory/state-machine.json.tpl`, replace the `RunAgentGroupsMap` block with a fixed sequence of `Map` states. This eliminates the orchestrator's ability to emit a bad grouping. The orchestrator's `parallel_groups` becomes advisory; the state machine ignores it.

Replace `RunAgentGroupsMap` with this sequence (keep the same outer Catch + Next):

```
RunArchitect
  → DatabasePhase   (Map over plan.agents ∩ {"database"})
  → BuildersPhase   (Map over plan.agents ∩ {"backend", "frontend", "infrastructure"}, MaxConcurrency: 3)
  → TestPhase       (Map over plan.agents ∩ {"test"})
  → RunSecurityReview
```

Each phase Map calls `RunOneAgent` (existing per-agent ItemProcessor) for each agent in its scope. A phase with no agents (e.g. database when the orchestrator skipped it) is a no-op — the Map iterates zero times. Use a `Pass` state ahead of each Map to compute its filtered agent list:

```json
"FilterDatabaseAgents": {
  "Type": "Pass",
  "Parameters": {
    "agents.$": "States.ArrayContains($.orchestrator.Payload.plan.agents, 'database')",
    "execution_id.$": "$$.Execution.Name",
    "feature_id.$":   "$.feature_id"
  },
  "Next": "DatabasePhase"
}
```

Actually, `ArrayContains` returns boolean. Use a JSONata `States.JsonataEval` (Step Functions has supported JSONata mode since 2024-11) or pre-compute the filtered arrays in `run_orchestrator` and stash them on the plan. **Cleaner:** have `run_orchestrator` write three arrays to the plan output:

```python
plan["execution_phases"] = {
    "database":  [a for a in plan["agents"] if a == "database"],
    "builders":  [a for a in plan["agents"] if a in {"backend", "frontend", "infrastructure"}],
    "test":      [a for a in plan["agents"] if a == "test"],
}
```

State machine then reads `$.orchestrator.Payload.plan.execution_phases.database`, `…builders`, `…test`. Each phase is a Map over its array. If the array is empty the Map iterates zero times.

### A1.2 Remove `parallel_groups` enforcement code

Delete the orchestrator post-processing in `run_orchestrator.py:23-29` that backfills `parallel_groups`. Replace with `execution_phases` computation per A1.1. Keep `parallel_groups` as informational output only.

### A1.3 Update the orchestrator agent prompt

`.claude/agents/orchestrator.md`:
- Remove the `parallel_groups` rules section.
- Add: "The state machine enforces fixed phase ordering: database → (backend, frontend, infrastructure) → test → security-reviewer. You do NOT decide ordering. Just list which agents are needed via `agents` and `skip_reason`."
- Drop `parallel_groups` from the example schema; replace with a `notes` example that explains how dependencies between agents in the *same* phase should be handled (e.g. "frontend must read backend's openapi.json from the workspace").

### A1.4 Verification

After deploying:
```bash
# Trigger the smoke feature manually
aws stepfunctions start-execution \
  --state-machine-arn arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-pipeline \
  --name "smoke-a1-$(date +%s)" \
  --input '{"feature_id":"<smoke-feature-uuid>"}'
# Watch in console; assert ALL of database, backend, infrastructure, frontend complete BEFORE
# any validate_* invocation runs.
```

The race should be gone: validators only fire after all agents in their phase complete.

**Done when:** state machine has 3 sequential phase Maps; orchestrator's plan no longer drives ordering; one smoke run reaches at least the test phase before any `ValidationExhausted` (proves no race).

---

## Phase A2 — Replace per-agent validators with a single workspace validator

Per-agent validators are the wrong abstraction. The workspace is shared state; one validator should examine the whole workspace and report all issues at once. This eliminates:
- Per-agent S3 download (5x → 1x per phase)
- Per-agent pip install (5x → 1x per phase)
- Per-agent PYTHONPATH gymnastics
- The "test failed because backend hasn't finished" race

### A2.1 New Lambda: `validate_workspace`

Create `scripts/factory_lambdas/handlers/validate_workspace.py`. Single Lambda runs ALL static checks on the materialized workspace and returns a structured `{passed, issues_by_owner}` map. Owners are agent names so the repair loop can route correctly.

```python
import os, time, hashlib, shutil, subprocess, tempfile
from pathlib import Path
from common.workspace import list_code_files, read_code_file
from common.runs import record_step

_PKGS = "/tmp/ws-pkgs"
_PKGS_HASH = "/tmp/ws-pkgs.hash"

OWNERSHIP = {
    "app/":        "backend",
    "frontend/":   "frontend",
    "tests/":      "test",
    "infra/":      "infrastructure",
    "Dockerfile":  "backend",
    "docker-compose.yml": "backend",
    ".dockerignore": "backend",
    "requirements.txt":   "backend",
    "alembic.ini":        "database",
    "app/db/migrations/": "database",
}

def _owner_for(path: str) -> str:
    for prefix, owner in sorted(OWNERSHIP.items(), key=lambda kv: -len(kv[0])):
        if path.startswith(prefix) or path == prefix:
            return owner
    return "backend"  # safe default

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
            cmd += ["-r", name]
    subprocess.run(cmd, cwd=ws, check=False, timeout=300)
    Path(_PKGS_HASH).write_text(h)

def _run(cmd, cwd, env_extra=None, timeout=120):
    env = {**os.environ, **(env_extra or {})}
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, env=env)
    return p.returncode, (p.stdout + p.stderr)[:8000]

def _python_path(ws: Path) -> str:
    return ":".join(filter(None, [_PKGS, str(ws), "/opt/python", os.environ.get("PYTHONPATH", "")]))

def handler(event, _ctx):
    execution_id = event["execution_id"]
    feature_id   = event["feature_id"]
    phase        = event["phase"]   # "database" | "builders" | "test"
    start = time.time()
    ws = _materialize(execution_id)
    issues_by_owner: dict[str, list] = {}

    def add(owner: str, tool: str, output: str, hint: str = ""):
        issues_by_owner.setdefault(owner, []).append({"tool": tool, "output": output, "hint": hint})

    try:
        _install_workspace_deps(ws)
        pp = _python_path(ws)

        # Phase-conditioned checks. After the "builders" phase we run the heavy
        # backend/frontend/infra checks. After "test" phase we add pytest collection.
        if phase in {"builders", "test"}:
            if (ws / "app").exists():
                rc, out = _run(["python", "-m", "ruff", "check", "app/"], ws, {"PYTHONPATH": pp})
                if rc != 0: add("backend", "ruff", out)
                rc, out = _run(["python", "-m", "mypy", "app/", "--ignore-missing-imports"], ws, {"PYTHONPATH": pp})
                if rc != 0: add("backend", "mypy", out)
                rc, out = _run(["python", "-c",
                    "import importlib, pkgutil; "
                    "[importlib.import_module(n) for _,n,_ in pkgutil.walk_packages(['app'], prefix='app.')]"],
                    ws, {"PYTHONPATH": pp})
                if rc != 0: add("backend", "import-check", out,
                                "App modules must be importable without env vars set; move env reads inside functions.")
            if (ws / "infra" / "main.tf").exists():
                # terraform fmt + validate — requires terraform binary; see A2.2 for how to ship it
                rc, out = _run(["/opt/bin/terraform", "fmt", "-check", "-recursive", "infra/"], ws)
                if rc != 0: add("infrastructure", "terraform-fmt", out, "Run `terraform fmt -recursive infra/`.")
                rc, out = _run(["/opt/bin/terraform", "init", "-backend=false", "-input=false"], ws / "infra")
                if rc != 0: add("infrastructure", "terraform-init", out)
                else:
                    rc, out = _run(["/opt/bin/terraform", "validate"], ws / "infra")
                    if rc != 0: add("infrastructure", "terraform-validate", out)
            if (ws / "frontend").exists():
                # tsc + eslint — node toolchain in container image (see A2.2)
                rc, out = _run(["node", "/opt/node/tsc-runner.js", str(ws / "frontend")], ws)
                if rc != 0: add("frontend", "tsc", out)
        if phase == "test" and (ws / "tests").exists():
            rc, out = _run(["python", "-m", "pytest", "--collect-only", "-q", "tests/"],
                           ws, {"PYTHONPATH": pp}, timeout=180)
            if rc != 0: add("test", "pytest-collect", out)
        if phase in {"database", "builders"} and (ws / "app" / "db" / "migrations").exists():
            # alembic check — requires alembic in workspace deps
            rc, out = _run(["python", "-m", "alembic", "check"], ws, {"PYTHONPATH": pp})
            # alembic check returns non-zero if there are pending migrations — informational only
    finally:
        shutil.rmtree(ws, ignore_errors=True)

    passed = not issues_by_owner
    record_step(execution_id, feature_id, f"validate-workspace-{phase}",
                "success" if passed else "failed", time.time() - start,
                metadata={"failing_owners": list(issues_by_owner.keys())})
    return {
        "passed": passed,
        "issues_by_owner": issues_by_owner,
        "phase": phase,
    }
```

### A2.2 Container-image Lambda for `validate_workspace`

This Lambda needs `terraform`, `node`/`tsc`, `pip`, and Python deps. Ship as a container image:

```dockerfile
# scripts/factory_lambdas/containers/validate_workspace/Dockerfile
FROM public.ecr.aws/lambda/python:3.12

# terraform
RUN dnf install -y unzip wget && \
    wget -q https://releases.hashicorp.com/terraform/1.7.5/terraform_1.7.5_linux_amd64.zip && \
    unzip -q terraform_1.7.5_linux_amd64.zip && \
    mkdir -p /opt/bin && mv terraform /opt/bin/terraform && \
    rm terraform_1.7.5_linux_amd64.zip

# node + typescript (only what tsc needs to typecheck)
RUN dnf install -y nodejs npm && \
    npm install -g typescript@5 --prefix /opt/node && \
    ln -s /opt/node/lib/node_modules/typescript/bin/tsc /opt/bin/tsc

# Python build/test tooling pre-installed at image build time so warm
# containers don't repeat the install
RUN pip install --no-cache-dir ruff mypy pytest pytest-asyncio httpx anyio alembic

COPY common/  ${LAMBDA_TASK_ROOT}/common/
COPY handlers/validate_workspace.py ${LAMBDA_TASK_ROOT}/

CMD ["validate_workspace.handler"]
```

Provide a tiny `tsc-runner.js` script:
```javascript
// /opt/node/tsc-runner.js
const { execSync } = require("child_process");
const dir = process.argv[2];
try {
  execSync("/opt/bin/tsc --noEmit --project tsconfig.json", { cwd: dir, stdio: "inherit" });
} catch (e) { process.exit(1); }
```

Add the ECR repo + container build to Terraform (use `infra/factory/lambdas-image.tf`):

```hcl
resource "aws_ecr_repository" "validators" {
  name                 = "${local.name_prefix}-validators"
  image_tag_mutability = "MUTABLE"
  tags                 = local.common_tags
}

resource "null_resource" "build_validate_workspace" {
  triggers = {
    dockerfile = filemd5("${path.module}/../../scripts/factory_lambdas/containers/validate_workspace/Dockerfile")
    handler    = filemd5("${path.module}/../../scripts/factory_lambdas/handlers/validate_workspace.py")
  }
  provisioner "local-exec" {
    command = <<-EOT
      set -e
      cd ${path.module}/../../scripts/factory_lambdas/containers/validate_workspace
      cp -r ../../common .
      cp ../../handlers/validate_workspace.py .
      aws ecr get-login-password --region ${var.aws_region} | \
        docker login --username AWS --password-stdin ${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com
      docker build --platform linux/amd64 -t validate-workspace .
      docker tag validate-workspace ${aws_ecr_repository.validators.repository_url}:latest
      docker push ${aws_ecr_repository.validators.repository_url}:latest
      rm -rf common validate_workspace.py
    EOT
  }
}

resource "aws_lambda_function" "validate_workspace" {
  function_name = "${local.name_prefix}-validate-workspace"
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.validators.repository_url}:latest"
  role          = aws_iam_role.lambda_exec.arn
  timeout       = 600
  memory_size   = 3008
  ephemeral_storage { size = 4096 }
  tracing_config { mode = "Active" }
  environment {
    variables = {
      WORKSPACE_BUCKET = aws_s3_bucket.workspaces.bucket
      RUNS_TABLE       = aws_dynamodb_table.runs.name
    }
  }
  depends_on = [null_resource.build_validate_workspace]
  tags       = local.common_tags
}
```

### A2.3 Update state machine to invoke `validate_workspace` after each phase

Replace each phase's per-agent `ChooseValidator → ValidateAgent → ValidationChoice → BumpRepairAndRetry` micro-loop with: phase Map runs all its agents, then a single `Validate{phase}` task calls `validate_workspace` with `{phase: "..."}`. If issues are found, route to a phase-level repair Map.

Sketch (BuildersPhase shown; same pattern for Database/Test):

```json
"BuildersPhase": {
  "Type": "Map",
  "ItemsPath": "$.orchestrator.Payload.plan.execution_phases.builders",
  "MaxConcurrency": 3,
  "ItemSelector": {
    "agent_name.$": "$$.Map.Item.Value",
    "execution_id.$": "$$.Execution.Name",
    "feature_id.$":   "$.feature_id"
  },
  "ItemProcessor": {
    "ProcessorConfig": {"Mode": "INLINE"},
    "StartAt": "RunOneAgent",
    "States": {
      "RunOneAgent": {
        "Type": "Task",
        "Resource": "arn:aws:states:::lambda:invoke",
        "Parameters": {
          "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-run-agent",
          "Payload": {
            "agent_name.$":    "$.agent_name",
            "execution_id.$":  "$.execution_id",
            "feature_id.$":    "$.feature_id"
          }
        },
        "End": true
      }
    }
  },
  "ResultPath": null,
  "Next": "ValidateBuilders"
},
"ValidateBuilders": {
  "Type": "Task",
  "Resource": "arn:aws:states:::lambda:invoke",
  "Parameters": {
    "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-validate-workspace",
    "Payload": {
      "execution_id.$": "$$.Execution.Name",
      "feature_id.$":   "$.feature_id",
      "phase":          "builders"
    }
  },
  "ResultPath": "$.builders_validation",
  "Next": "BuildersValidationChoice"
},
"BuildersValidationChoice": {
  "Type": "Choice",
  "Choices": [
    { "Variable": "$.builders_validation.Payload.passed", "BooleanEquals": true, "Next": "TestPhase" },
    {
      "And": [
        { "Variable": "$.builders_validation.Payload.passed", "BooleanEquals": false },
        { "Or": [
          { "Variable": "$.builders_repair_count", "IsPresent": false },
          { "Variable": "$.builders_repair_count", "NumericLessThan": 2 }
        ]}
      ],
      "Next": "RepairBuilders"
    }
  ],
  "Default": "MarkFailedAndRelease"
},
"RepairBuilders": {
  "Type": "Map",
  "ItemsPath": "$.builders_validation.Payload.failing_owners",
  "MaxConcurrency": 3,
  "ItemSelector": {
    "agent_name.$":     "$$.Map.Item.Value",
    "execution_id.$":   "$$.Execution.Name",
    "feature_id.$":     "$.feature_id",
    "repair_context.$": "$.builders_validation.Payload.issues_by_owner"
  },
  "ItemProcessor": {
    "ProcessorConfig": {"Mode": "INLINE"},
    "StartAt": "RepairOneAgent",
    "States": {
      "RepairOneAgent": {
        "Type": "Task",
        "Resource": "arn:aws:states:::lambda:invoke",
        "Parameters": {
          "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-run-agent",
          "Payload": {
            "agent_name.$":     "$.agent_name",
            "execution_id.$":   "$.execution_id",
            "feature_id.$":     "$.feature_id",
            "repair_context.$": "$.repair_context"
          }
        },
        "End": true
      }
    }
  },
  "ResultPath": null,
  "Parameters": {
    "feature_id.$": "$.feature_id",
    "orchestrator.$": "$.orchestrator",
    "builders_repair_count": 1
  },
  "Next": "ValidateBuilders"
}
```

(`builders_repair_count` increment uses `States.MathAdd` if you stay in JSONPath mode and bump on each iteration; the Pass-state pattern from the original plan still works.)

### A2.4 Delete the per-agent validators

Once `validate_workspace` is verified working in smoke:
- Delete `validate_backend.py`, `validate_frontend.py`, `validate_database.py`, `validate_infrastructure.py`, `validate_test.py`.
- Remove their entries from `lambdas.tf`.
- `terraform apply` removes the Lambda functions.

**Done when:** `validate_workspace` Lambda is live (container image), state machine routes through it after each phase, smoke run shows a single validation per phase, per-agent validator Lambdas removed.

---

## Phase A3 — Strengthen the test agent prompt

The test agent has been the highest-friction agent in smoke runs. Two prompt-level fixes:

1. **Mandate `tests/requirements.txt`** for any test-only deps (httpx, pytest-asyncio, etc.). Add to `.claude/agents/test.md`:
   ```markdown
   ## Test dependencies — Hard Rule
   You MUST include a `tests/requirements.txt` file in your output containing every
   package the tests import that isn't already in the root `requirements.txt`.
   At minimum: `pytest>=8`, `pytest-asyncio>=0.23`, `httpx>=0.27`. Add others as needed
   (e.g. `aiosqlite` for async SQLite tests).
   ```

2. **Forbid the missing-app-module failure mode**. Add:
   ```markdown
   ## Cross-agent dependencies
   You run AFTER backend and frontend have completed. The workspace contains the full
   `app/` tree they produced. If you import from `app.X` and that module doesn't exist,
   that is a bug in YOUR test (you imported the wrong path), NOT a failure of the backend.
   Read `requirements.json` (spec) AND the actual files in `app/` to see what backend produced.
   ```

3. **Add a smoke-friendly minimal-test fallback**. If the spec is trivial (e.g. one new endpoint), the test agent should write at most 1–2 tests instead of trying to cover the full app. Add:
   ```markdown
   ## Test scope
   Cover what THIS feature added or changed. If the spec adds one endpoint, write 1-2
   tests for that endpoint and stop. Do NOT write tests for unrelated existing code.
   ```

**Done when:** `test.md` has the three new sections.

---

## Phase A4 — Iteration tooling

Reach a clean smoke run faster by removing toil from the debug loop.

### A4.1 Local synthetic-fixture trigger

Create `scripts/factory_smoke.sh`:

```bash
#!/usr/bin/env bash
# Trigger a state-machine run against a minimal smoke fixture WITHOUT writing to Notion.
# Use during development to iterate on factory bugs without burning Notion state.
set -euo pipefail

NAME="smoke-$(date +%Y%m%d-%H%M%S)"
SM_ARN=$(aws stepfunctions list-state-machines \
  --query 'stateMachines[?name==`nova-factory-pipeline`].stateMachineArn' \
  --output text)

# A real Notion feature_id (use a permanent "factory smoke" Notion page) OR a synthetic one
# if you've taught load_spec.py to recognize a smoke prefix and return canned content.
FEATURE_ID="${1:-<NOTION_SMOKE_PAGE_UUID>}"

echo "Starting execution $NAME against $SM_ARN"
EXEC_ARN=$(aws stepfunctions start-execution \
  --state-machine-arn "$SM_ARN" \
  --name "$NAME" \
  --input "{\"feature_id\":\"$FEATURE_ID\"}" \
  --query executionArn --output text)

echo "Execution ARN: $EXEC_ARN"
echo "Console: https://us-east-1.console.aws.amazon.com/states/home?region=us-east-1#/executions/details/$EXEC_ARN"

# Tail status every 5s
while :; do
  STATUS=$(aws stepfunctions describe-execution --execution-arn "$EXEC_ARN" --query status --output text)
  echo "[$(date +%H:%M:%S)] $STATUS"
  if [[ "$STATUS" != "RUNNING" ]]; then
    aws stepfunctions describe-execution --execution-arn "$EXEC_ARN" --output json > "/tmp/$NAME.json"
    echo "Final state in /tmp/$NAME.json"
    break
  fi
  sleep 5
done
```

### A4.2 Force-cycle warm Lambdas

Bug 8 (warm container caches stale code/pkgs) means a code fix can take 15–45 min to take effect. Mitigate with a one-shot script that bumps each function's `Description` to force a new container:

```bash
# scripts/factory_cycle_lambdas.sh
#!/usr/bin/env bash
set -euo pipefail
TS=$(date +%s)
for fn in $(aws lambda list-functions --query 'Functions[?starts_with(FunctionName, `nova-factory-`)].FunctionName' --output text); do
  aws lambda update-function-configuration \
    --function-name "$fn" \
    --description "Force-cycled $TS" >/dev/null
  echo "cycled $fn"
done
```

Run this after deploying a code fix and BEFORE the next smoke run.

### A4.3 Saved Logs Insights queries

Add to `infra/factory/dashboard.tf`:

```hcl
resource "aws_cloudwatch_query_definition" "agent_calls_summary" {
  name = "${local.name_prefix}/agent-calls-summary"
  log_group_names = [for k in keys(local.handlers) :
    "/aws/lambda/${local.name_prefix}-${replace(k, "_", "-")}"]
  query_string = <<-EOQ
    fields @timestamp, agent, model, stop_reason, input_tokens, output_tokens
    | filter event = "agent_call"
    | sort @timestamp desc
    | limit 200
  EOQ
}

resource "aws_cloudwatch_query_definition" "validation_failures" {
  name = "${local.name_prefix}/validation-failures"
  log_group_names = ["/aws/lambda/${local.name_prefix}-validate-workspace"]
  query_string = <<-EOQ
    fields @timestamp, @message
    | filter @message like /failing_owners/
    | sort @timestamp desc
    | limit 50
  EOQ
}

resource "aws_cloudwatch_query_definition" "execution_traces" {
  name = "${local.name_prefix}/execution-trace"
  log_group_names = ["/aws/states/${local.name_prefix}-pipeline"]
  query_string = <<-EOQ
    fields @timestamp, type, details.stateName, details.error, details.cause
    | sort @timestamp asc
    | limit 1000
  EOQ
}
```

**Done when:** `factory_smoke.sh` works, `factory_cycle_lambdas.sh` works, three Logs Insights queries appear in the AWS console.

---

## Phase A5 — First clean smoke run + cutover

1. Apply A0–A4 changes via `terraform apply`.
2. Run `factory_cycle_lambdas.sh` to flush warm containers.
3. Run `factory_smoke.sh <smoke-feature-id>`.
4. Watch the execution. Expected behaviour:
   - `LoadSpec → LoadProjectContext → RunOrchestrator → RunSpecAnalyst → RunArchitect`
   - `DatabasePhase` (probably empty) → `ValidateDatabase` (no-op pass)
   - `BuildersPhase` runs backend + infrastructure (frontend skipped if API-only feature)
   - `ValidateBuilders` runs once on the merged workspace
   - `TestPhase` runs test agent
   - `ValidateTest` runs once
   - `RunSecurityReview` → `EvaluateSecurity` → `CommitAndPush` → `WaitForQualityGates` → `MarkDone`
5. If validation issues are found, the repair phase runs. Up to 2 repair cycles. Then either passes or fails cleanly.
6. Iterate on agent prompts only — don't touch architecture again until 3 consecutive smoke runs pass.

Once 3 consecutive runs pass:
- Edit `infra/webhook-relay/main.tf`: `FACTORY_BACKEND = "step-functions"`.
- `terraform apply`.
- Mark a real Notion feature `Ready to Build`. Watch end-to-end.
- If the real run passes, cutover is complete.

**Done when:** 3 smoke runs pass + 1 real Notion-triggered run completes Done.

---

## Phase B1 — Subprocess-free in-process validation (defer until A5 green)

Once the workspace validator works, simplify it further by removing subprocess for the Python-only checks. Ruff and mypy expose Python APIs:

```python
# In-process ruff
from ruff_api import lint  # ruff publishes Python bindings as 'ruff' on PyPI
results = lint.check(["app/"])
# ...

# In-process mypy
from mypy import api as mypy_api
exit_code, stdout, stderr = mypy_api.run(["app/", "--ignore-missing-imports"])
```

This eliminates PYTHONPATH issues entirely for Python checks. Subprocess is still needed for terraform, tsc, and pytest collection. But those have stable invocation patterns now.

Net effect: fewer moving parts in `validate_workspace.py`, faster execution (no subprocess fork overhead), no `/tmp` package cache concerns for ruff/mypy.

**Defer until smoke is reliably green.**

---

## Phase B2 — Cutover-time hardening (defer)

After cutover, add:

1. **Concurrency cap on the state machine**: `aws_sfn_state_machine` doesn't natively cap concurrent executions. Add a check in `acquire_lock`: count current executions for the same feature in DynamoDB, refuse if >= 1. Prevents runaway loops.

2. **Per-execution token budget**: track total Anthropic tokens in DynamoDB `runs` table. If a single execution exceeds 1M tokens, abort. Stops infinite repair loops cold.

3. **Spec-quality gating**: if spec-analyst reports `len(blockers) > 0` with HARD prefix, fail before any code agent runs. Already done — verify the path works.

4. **Parameter Store env-var bootstrap**: when spec-analyst lists `new_env_vars`, infrastructure agent should create Parameter Store entries with placeholder values (`__PLACEHOLDER__`). Deploy then fails until human populates them. Better than today where missing env vars surface only at runtime.

---

## Phase C — Move Anthropic calls off Lambda (optional, large win)

Lambda is the wrong primitive for a 5-15 minute streaming HTTP call to an external API. Two cleaner options:

### Option C1 — Bedrock + Step Functions native invocation

Step Functions can call Bedrock directly: `Resource: arn:aws:states:::bedrock:invokeModel`. No Lambda runs during the wait — Step Functions pays per state transition (~$0.025/1k), not per second of compute.

Refactor:
- Each agent becomes two Step Functions states:
  1. `Prepare<Agent>Input` (small Lambda, <5s) — builds the prompt from S3 workspace.
  2. `Invoke<Agent>` (Bedrock direct) — calls Claude through Bedrock, returns response.
  3. `Process<Agent>Output` (small Lambda, <5s) — parses response, writes to S3.

- Each Lambda runs in seconds instead of minutes. Lambda cost drops by ~90%.
- Bedrock and Anthropic API have the same models (Claude 3.5+ available in Bedrock). Per-token cost is comparable; some regions are slightly cheaper via Bedrock.
- Get rid of `messages.stream()` complexity entirely.

Tradeoffs:
- Bedrock has model availability lag (Sonnet 4.6 may not be in all regions immediately on release).
- Bedrock invokeModel has its own response-size limits; large code outputs may need the Converse API or splitting.
- One more AWS service to monitor.

### Option C2 — AWS Batch / Fargate task per agent

If Bedrock isn't viable, run each agent as a Fargate task with `aws_batch_job_definition`. Step Functions launches the task, waits for completion. Fargate Spot is ~$0.012/hr — at ~10 min per agent, that's ~$0.002 per agent. Cheaper than Lambda's per-second pricing for long calls.

**Don't gate cutover on this.** Get smoke green first.

---

## Cleanup checklist (apply at end)

- [ ] Delete `scripts/factory_run.py` and `scripts/agents.py` (legacy GitHub Actions code path) — only after `factory.yml` is removed.
- [ ] Delete `.github/workflows/factory.yml` after 30 days of stable Step Functions operation.
- [ ] Migrate `infra/factory/` Terraform state from local backend to S3 backend.
- [ ] Update `CLAUDE.md` Factory section if any architectural element changed.
- [ ] Update user memory `project_nova_status.md` and `reference_factory_runtime.md` (current state machine has the new phase Maps).
- [ ] Move execution summary to `docs/superpowers/execution-summaries/` (new directory) for archival.

---

## Acceptance criteria

This plan is complete when ALL of the following are true:

1. `git status` clean on `factory-overhaul-2026-05-03` branch (no uncommitted Bug 8/9/10 fixes).
2. State machine has fixed phase ordering: database → builders → test → security; orchestrator no longer drives ordering.
3. A single `validate_workspace` Lambda replaces all 5 per-agent validators; per-agent validator Lambdas deleted from Terraform and from disk.
4. Three consecutive smoke runs of the test feature complete with status `Done` in Notion.
5. One real Notion-triggered feature (any "Ready to Build" feature in the Features DB) completes end-to-end.
6. `factory_smoke.sh` and `factory_cycle_lambdas.sh` exist and work.
7. CloudWatch console shows three saved Logs Insights queries under `nova-factory/`.
8. `FACTORY_BACKEND = "step-functions"` in `infra/webhook-relay/main.tf` (cutover applied).
9. `factory.yml` workflow has a deprecation header dated today and is otherwise unchanged.
10. No stray `lambda-layer;C/` directory or other build artifacts in the repo.

---

## Sonnet operating instructions

- **Resume on the existing branch** (`factory-overhaul-2026-05-03`); do NOT branch off main.
- **A0 first**, no exceptions. The uncommitted fixes are protective; lose them and you'll regress.
- For each phase: implement → terraform apply → cycle Lambdas → smoke test → only then move to next phase.
- If a smoke run fails, identify whether the failure is **architectural** (re-read this plan) or **a specific agent prompt issue** (edit the agent .md only). Don't re-architect on agent-prompt issues.
- The "ValidationExhausted" error after these changes means EITHER the agent legitimately can't write valid code OR the validator is wrong. Read `validation_failures` Logs Insights query first.
- Phase B1, B2, C are **optional**. Do not start them until A5 acceptance criteria 1–10 are satisfied.
- When done, open or update PR. Title: "Factory stabilization: phase ordering + workspace validator + smoke green". Body: list which acceptance criteria are now true.
- Update the execution-summary file (`docs/superpowers/plans/2026-05-03-factory-overhaul-execution-summary.md`) with a new "Stabilization round" section listing what changed, what bugs surfaced, and final smoke results.
