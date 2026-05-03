# Nova Factory Overhaul — Execution Summary

**Date:** 2026-05-03  
**Original plan:** `docs/superpowers/plans/2026-05-03-factory-cost-and-robustness-overhaul.md`  
**Branch:** `factory-overhaul-2026-05-03`  
**Status:** Phases 1-7, 9, 10 complete. Phase 8 (smoke test & cutover) still failing on run 13.

---

## What Was Built

### Phases 1-7: Infrastructure & Agents ✅

- Step Functions state machine (`nova-factory-pipeline`) with FanOut map for parallel agents
- 16 Lambda handlers: orchestrator, per-agent runners, validators, lifecycle (lock/release, commit, Notion update, quality gate callback)
- DynamoDB optimistic locking per feature, S3 workspace bucket per execution
- Lambda layer with shared Python dependencies
- Webhook relay Lambda for routing Notion triggers to Step Functions

### Phase 9: Observability ✅

- `infra/factory/dashboard.tf` — CloudWatch dashboard, SNS topic + email subscription, execution failures alarm (threshold: any failure in 5-min window), $20/month budget alert
- Alarm verified working — fired from failed smoke runs and delivered email successfully

### Phase 10: Documentation ✅

- `CLAUDE.md` — Factory section updated to describe Step Functions pipeline
- `docs/runbooks/factory-incident.md` — 3 runbooks: stuck DynamoDB lock, hung WaitForQualityGates, Anthropic outage
- Memory files updated: `project_nova_status.md`, `project_nova_operations.md`, `reference_factory_runtime.md` (new)

### Phase 8: Smoke Test & Cutover 🔴 In Progress

13 smoke runs attempted. See "Bugs Found and Fixed" below. Current blocker: multiple agents hitting `ValidationExhausted` in smoke13. Webhook cutover (flip `FACTORY_BACKEND = "step-functions"`) is blocked until a clean run succeeds.

---

## Files Modified

| File | Change |
|---|---|
| `infra/factory/state-machine.json.tpl` | Template var escaping fix, added `LoadProjectContext` state, removed `repair_context` from initial dispatch params |
| `infra/factory/lambdas.tf` | Added `load_project_context` handler entry |
| `infra/factory/dashboard.tf` | **New** — CloudWatch dashboard, SNS topic, alarm, budget |
| `infra/factory/lambda-layer/build.sh` | Docker-based build for Linux x86_64 binaries |
| `infra/factory/lambda-layer/requirements.txt` | Added `httpx>=0.27`, `anyio>=4.0` |
| `scripts/factory_lambdas/handlers/load_project_context.py` | **New** — fetches `CLAUDE.md` from GitHub raw API, writes to S3 workspace |
| `scripts/factory_lambdas/handlers/validate_test.py` | Hash-based pkg caching, `/opt/python` in PYTHONPATH, `tests/requirements.txt` support |
| `scripts/factory_lambdas/handlers/validate_backend.py` | `/opt/python` in PYTHONPATH for all subprocesses, hash-based `requirements.txt` install for import-check |
| `scripts/factory_lambdas/handlers/validate_database.py` | `/opt/python` in PYTHONPATH |
| `scripts/factory_lambdas/common/agent_runner.py` | Switched from `messages.create()` to `messages.stream()` + `get_final_message()` |
| `CLAUDE.md` | Updated Factory section for SFN pipeline |
| `docs/runbooks/factory-incident.md` | **New** — 3 incident runbooks |

---

## Bugs Found and Fixed During Execution

### Bug 1: Terraform template variable escaping
- **Symptom:** Step Functions validation error — `Value 'arn:aws:lambda:${region}:...'` failed
- **Root cause:** `state-machine.json.tpl` used `${region}` (correct in Terraform `templatefile()`) but someone had changed them to `$${region}` (double-dollar), which outputs the literal string `${region}` instead of substituting the value
- **Fix:** sed'd 18 occurrences back to single-dollar syntax
- **Note:** `$.Execution.Name` is CORRECT — `$` without `{` is literal in Terraform template syntax

### Bug 2: Lambda layer compiled for Windows
- **Symptom:** `Unable to import module 'run_orchestrator': No module named 'pydantic_core._pydantic_core'`
- **Root cause:** `build.sh` used local `pip install` on a Windows dev machine → compiled native extensions for Windows; Lambda needs Linux x86_64 binaries
- **Fix:** Updated `build.sh` to use `docker run python:3.12-slim` when Docker is available; falls back to local pip. Used `cygpath` for Windows path conversion.

### Bug 3: Terraform reverted Lambda functions to old layer
- **Symptom:** After manually publishing Linux layer v2, `terraform apply` reverted Lambda functions back to v1
- **Root cause:** Terraform's state said the managed layer was v1; manually publishing v2 was outside Terraform's control
- **Fix:** `terraform apply -replace=aws_lambda_layer_version.shared` to force Terraform to recreate the layer from the new Linux zip and update all functions

### Bug 4: `project_context.json` missing from S3
- **Symptom:** `run_orchestrator` threw `NoSuchKey` when reading `project_context.json`
- **Root cause:** The plan specified a `LoadProjectContext` step to fetch `CLAUDE.md` and write it to S3, but it was never implemented — neither the Lambda handler nor the state machine state existed
- **Fix:** Created `load_project_context.py` Lambda + added `LoadProjectContext` state between `LoadSpec` and `RunOrchestrator` in the ASL + added Lambda to `lambdas.tf`

### Bug 5: `repair_context` JSONPath error in normal agent dispatch
- **Symptom:** JSONPath `$.repair_context` could not be found in input during initial (non-repair) agent invocations
- **Root cause:** `RunOneAgent` Parameters block included `"repair_context.$": "$.repair_context"` — this field only exists in the repair loop path, not in the initial dispatch path
- **Fix:** Removed that parameter from `RunOneAgent`; the repair loop's `BumpRepairAndRetry` state adds it correctly

### Bug 6: Anthropic SDK enforces streaming for large max_tokens
- **Symptom:** `Streaming is required for operations that may take longer than 10 minutes`
- **Root cause:** Anthropic SDK ≥0.40 enforces streaming for requests with large `max_tokens` (backend/frontend use 32768); `client.messages.create()` is blocked
- **Fix:** Switched to `client.messages.stream(...)` context manager + `stream.get_final_message()` in both `call_agent()` and the Haiku JSON-repair call in `agent_runner.py`

### Bug 7: Subprocess validators can't see Lambda layer packages
- **Symptom:** `validate_test` pytest subprocess: `/var/lang/bin/python: No module named pytest`
- **Root cause:** Lambda runtime adds `/opt/python` (layer) to `sys.path` for the Lambda process itself, but NOT to the `PYTHONPATH` environment variable. Child processes spawned via `subprocess.run` don't inherit `/opt/python` on their path.
- **Fix:** Explicitly construct PYTHONPATH including `/opt/python` and pass it via `extra_env` to all subprocess calls in validate_test, validate_backend, and validate_database

### Bug 8: Warm Lambda container caches stale packages for validate_test
- **Symptom:** Repair loop re-runs validate_test; even if `requirements.txt` changes, pip install is skipped
- **Root cause:** Original code: `if req.exists() and not Path(_PKGS).exists()` — once `/tmp/test-pkgs` is created (first invocation of a warm container), it's never refreshed. If the backend agent writes `requirements.txt` AFTER the first validate_test run (parallel execution race), the repair loop still uses the stale empty package set.
- **Fix:** Hash-based caching — compute sha256 of requirements file content, store in `/tmp/test-pkgs.hash`, only reinstall if hash differs. Also purge the old package dir before reinstalling. Supports both `requirements.txt` and `tests/requirements.txt`.

### Bug 9: `starlette.testclient.TestClient` requires `httpx` at import time
- **Symptom:** `pytest --collect-only` fails with `ModuleNotFoundError: No module named 'starlette'` even after fastapi (which depends on starlette) is installed from requirements.txt
- **Root cause:** Modern starlette (≥0.20) imports `httpx` at module level in `testclient.py` and raises `ImportError` if it's missing. `httpx` was not in the Lambda layer or workspace requirements. The error message says "starlette" because the starlette import itself fails when httpx is absent.
- **Fix:** Added `httpx>=0.27` and `anyio>=4.0` to `infra/factory/lambda-layer/requirements.txt`, rebuilt layer with Docker (Linux x86_64), deployed as layer v4

### Bug 10: `validate_backend` subprocess can't see layer packages or workspace deps
- **Symptom (ruff/mypy):** `No module named ruff` / `No module named mypy` — same root cause as Bug 7
- **Symptom (import-check):** `No module named 'fastapi'` — workspace `requirements.txt` packages not installed for the subprocess
- **Fix:** Added `/opt/python` to PYTHONPATH for all `validate_backend` subprocesses; added hash-based `requirements.txt` install (to `/tmp/backend-pkgs`) so the import-check can see fastapi and other workspace deps. Same pattern as validate_test fix.

---

## Current Failure: smoke13

smoke13 shows 8 separate `ValidationExhausted` events — nearly every agent type is hitting its repair limit. This suggests either:

1. **Parallel execution timing race** — backend agent writes `requirements.txt` after test/backend validators already run their first attempt. Since all agents run in parallel (FanOut map), validators start immediately after their own agent finishes, often before sibling agents (e.g., backend) have written shared files.

2. **Repair loop ineffectiveness** — the test and backend agents are failing validation repeatedly without making meaningful fixes on each repair attempt. The repair context (validation error output) may not be sufficiently actionable for the agent.

3. **Warm container staleness** — even after code/layer updates, existing warm containers continue running old code for 15-45 minutes. Smoke runs started immediately after a code update may hit old containers.

---

## Open Questions for Review

1. **Parallel execution timing**: Backend and test agents run in parallel. `validate_test` runs immediately after the test agent finishes, often before the backend agent has written `requirements.txt`. Should agents run in dependency-ordered groups (e.g., backend first → test second) rather than fully parallel? The state machine supports groups but they currently all run together.

2. **Validator subprocess isolation**: All validators use `subprocess.run` and manually construct PYTHONPATH. Is there a cleaner approach — e.g., running validators in a fresh venv built from the workspace requirements, or using importlib within the same process for the import-check?

3. **Test agent prompt quality**: The test agent consistently generates tests using `starlette.testclient.TestClient` without adding `httpx` to requirements. Should the test agent prompt explicitly require it to write a `tests/requirements.txt` with test-only dependencies (httpx, pytest-asyncio, etc.)?

4. **Smoke test feature complexity**: The smoke feature ("Factory smoke — version v2 endpoint") requires the backend, test, database, and infrastructure agents to all generate valid code simultaneously. Is this feature too complex for an initial smoke test? A simpler feature (documentation-only, or a single-agent task) might be a better canary.

5. **Warm container force-flush**: Lambda preserves `/tmp` and may run stale code for 15-45 minutes after a code update. During debugging, this makes iteration very slow. Should there be a utility script that force-cycles Lambda containers (e.g., by updating an env var)?

---

## Commits on Branch

| Hash | Message |
|---|---|
| `3cdbc82` | Phase 9+10 observability + docs |
| `900058d` | fix(factory): template var escaping (Bug 1) |
| `928eb45` | fix(factory): LoadProjectContext state + Docker layer build (Bugs 2, 4) |
| `1727d80` | fix(factory): streaming API + remove repair_context from dispatch (Bugs 5, 6) |
| `7783595` | fix(factory): validate_test installs requirements.txt (Bug 7 partial) |
| `ca33522` | fix(factory): include /opt/python in validate_test subprocess PYTHONPATH (Bug 7) |

Bugs 8, 9, 10 are fixed in working directory but not yet committed (smoke run still failing).
