# Factory v2 — Phase 6: Cutover & Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flip the production webhook to route through `nova-factory-v2`, run one real Notion-triggered feature end-to-end, soak for 30 days monitoring v2's health under real traffic, and then permanently delete all v1 artifacts (Lambdas, state machine, agents, scripts, GitHub Actions workflow). End state: the repo and AWS account contain only v2 factory components.

**Architecture:** Two distinct chunks of work separated by a 30-day waiting period:

- **Cutover (Tasks 1–4)**: minimal, reversible. Flips one env var; runs one real feature. The v1 stack stays alive in case we need to revert.
- **Cleanup (Tasks 5–11)**: irreversible (without `git revert`). Removes all v1 components from Terraform, code, GitHub Actions, and updates auto-memory. Run **only** after 30 days of stable v2 operation.

**Tech Stack:** Terraform (destroy paths), git (large multi-file deletes), AWS (Lambda + SFN + ECR cleanup), Notion (real feature for the cutover smoke), markdown (memory file updates).

**Predecessors:** Phases 1–5 complete. v2 SFNs are running synthetic smokes successfully; self-pause / budgets / observability are wired up; `pytest tests/factory/ -v` passes 59 tests.

**Branch:** `factory-overhaul-2026-05-03`. Working directory: `C:\Claude\Nova\nova`. AWS account `577638385116`, region `us-east-1`.

**Out of scope for Phase 6:** Removing `factory.yml` GitHub Actions workflow — kept as emergency fallback for an additional 30 days after this phase completes (so 60 days post-cutover total).

---

## Cutover/Cleanup separation

The plan is structured so the **cutover tasks (1–4) can be executed today**, and the **cleanup tasks (5–11) are gated on the 30-day soak passing**. Each cleanup task lists the soak-criterion it depends on. Don't run Tasks 5–11 in the same session as Tasks 1–4.

---

## File Structure

**Modify:**

| Path | Change | Phase |
|---|---|---|
| `infra/webhook-relay/main.tf` | Change `FACTORY_BACKEND` env var from `"step-functions"` to `"step-functions-v2"`. | Cutover (Task 1) |
| `infra/webhook-relay/lambda/relay.py` | If the relay still has v1-specific dispatch code, ensure both v1 and v2 branches are present until Task 7 cleanup. | Cutover (Task 1) |
| `CLAUDE.md` | Update the `## Factory` section "cutover status" wording from "in flight" to "complete; v1 retained 30 days as fallback". | Cutover (Task 4) |
| `~/.claude/projects/C--Claude/memory/project_nova_status.md` | Mark v2 cutover complete; record cutover date. | Cutover (Task 4) |
| `~/.claude/projects/C--Claude/memory/reference_factory_runtime.md` | Update state machine ARN to `nova-factory-v2`; add postdeploy ARN; remove v1-only references. | Cleanup (Task 11) |

**Delete (Cleanup phase only):**

| Path | Reason |
|---|---|
| `infra/factory/lambdas.tf` | v1 Lambda definitions. |
| `infra/factory/state-machine.tf` | v1 SFN. |
| `infra/factory/state-machine.json.tpl` | v1 SFN template. |
| `infra/factory/lambdas-image.tf` | v1 `validate_workspace` container Lambda. |
| `infra/factory/dashboard.tf` | v1 dashboard (replaced by `dashboard-v2.tf`). |
| `scripts/factory_lambdas/handlers/load_spec.py` | v1-only. |
| `scripts/factory_lambdas/handlers/load_project_context.py` | v1-only. |
| `scripts/factory_lambdas/handlers/run_orchestrator.py` | v1-only. |
| `scripts/factory_lambdas/handlers/run_agent.py` | v1-only. |
| `scripts/factory_lambdas/handlers/evaluate_security.py` | v1-only. |
| `scripts/factory_lambdas/handlers/validate_backend.py` | v1-only (per-agent validator). |
| `scripts/factory_lambdas/handlers/validate_database.py` | Same. |
| `scripts/factory_lambdas/handlers/validate_frontend.py` | Same. |
| `scripts/factory_lambdas/handlers/validate_infrastructure.py` | Same. |
| `scripts/factory_lambdas/handlers/validate_test.py` | Same. |
| `scripts/factory_lambdas/containers/validate_workspace/` | v1 validator container (replaced by `validate_v2/`). |
| `scripts/factory_lambdas/agent_prompts/` (all 9 files) | v1 agent prompt copies. |
| `.claude/agents/` (all 9 files) | v1 agent system prompts. |
| `scripts/factory_run.py` | Local v1 runner. |
| `scripts/agents.py` | v1 agent orchestration helper. |

**Annotate:**

| Path | Change |
|---|---|
| `.github/workflows/factory.yml` | Add a deprecation banner comment + an `if: false` guard so it can't be triggered manually. Keep the file for 30 more days. |

---

# CUTOVER (Tasks 1–4) — execute now

## Pre-flight

- [ ] **P-1: All five preceding phases merged.**

```bash
pytest /c/Claude/Nova/nova/tests/factory/ -q
bash /c/Claude/Nova/nova/scripts/factory_smoke_v2.sh trivial && \
bash /c/Claude/Nova/nova/scripts/factory_smoke_v2.sh medium && \
bash /c/Claude/Nova/nova/scripts/factory_smoke_v2.sh oversized
```
Expected: 59 tests pass; all three smokes pass.

- [ ] **P-2: Pause flag is currently false.**

```bash
aws ssm get-parameter --name /nova/factory/paused --query Parameter.Value --output text
```
Expected: `false`.

- [ ] **P-3: Both v2 SFNs are ACTIVE.**

```bash
for sm in nova-factory-v2 nova-factory-postdeploy; do
  aws stepfunctions describe-state-machine \
    --state-machine-arn arn:aws:states:us-east-1:577638385116:stateMachine:$sm \
    --query '[name,status]' --output text
done
```
Expected: both `ACTIVE`.

- [ ] **P-4: A real Notion feature exists in `Idea` status to use as cutover smoke.**

Pick (or create) a small, real feature in the Notion Features DB. Status `Idea`. Title and body should describe a tiny additive change, e.g., "Add GET /api/system-info returning {api_version, factory_generation}." The feature MUST be small enough to clear the sizing rubric.

Note its `feature_id` (the Notion page UUID). You'll set its status to `Ready to Build` in Task 3 to trigger the v2 pipeline organically.

---

### Task 1: Flip `FACTORY_BACKEND` to v2

**Files:**
- Modify: `infra/webhook-relay/main.tf`

- [ ] **Step 1: Locate the env var.**

```bash
grep -n "FACTORY_BACKEND" /c/Claude/Nova/nova/infra/webhook-relay/main.tf
```
Expected: a line like `FACTORY_BACKEND = "step-functions"`.

- [ ] **Step 2: Change the value.**

Edit `infra/webhook-relay/main.tf`:

```hcl
FACTORY_BACKEND = "step-functions-v2"
```

If the relay handler dispatches based on this env var (with a switch on the value), confirm the v2 branch dispatches to `nova-factory-v2` SFN. If not, add the case:

```python
if FACTORY_BACKEND == "step-functions-v2":
    aws_sfn.start_execution(
        stateMachineArn="arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-v2",
        name=f"webhook-{feature_id}-{int(time.time())}",
        input=json.dumps({"feature_id": feature_id}),
    )
elif FACTORY_BACKEND == "step-functions":
    # v1 path — kept as fallback for 30 days
    aws_sfn.start_execution(
        stateMachineArn="arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-pipeline",
        ...
    )
elif FACTORY_BACKEND == "github-actions":
    # legacy fallback path
    ...
else:
    raise RuntimeError(f"unknown FACTORY_BACKEND={FACTORY_BACKEND}")
```

- [ ] **Step 3: Apply the env var change.**

```bash
cd /c/Claude/Nova/nova/infra/webhook-relay
terraform apply -auto-approve
```
Expected: 1 in-place update on `aws_lambda_function.<relay>`.

- [ ] **Step 4: Verify.**

```bash
aws lambda get-function-configuration --function-name nova-webhook-relay \
  --query 'Environment.Variables.FACTORY_BACKEND' --output text
```
Expected: `step-functions-v2`.

- [ ] **Step 5: Commit.**

```bash
cd /c/Claude/Nova/nova
git add infra/webhook-relay/
git commit -m "factory(v2): cutover — flip FACTORY_BACKEND to step-functions-v2"
```

---

### Task 2: Pre-cutover sanity SFN execution against v2

Before flipping the real Notion feature, do one more synthetic smoke through `nova-factory-v2` to confirm the production-equivalent path is healthy.

- [ ] **Step 1: Run the trivial smoke fixture once more.**

```bash
cd /c/Claude/Nova/nova
bash scripts/factory_smoke_v2.sh trivial
```
Expected: `OK`. The Notion synthetic page reaches `Done`. PR was opened, quality-gates passed, merged on `main`.

- [ ] **Step 2: Confirm the postdeploy SFN was triggered.**

```bash
aws stepfunctions list-executions \
  --state-machine-arn arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-postdeploy \
  --max-results 3 --query 'executions[].{name:name,status:status,start:startDate}' --output table
```
Expected: a recent execution corresponding to the trivial fixture's merge_sha. Status `SUCCEEDED` (or `RUNNING` briefly).

If postdeploy didn't run, the deploy.yml trigger from Phase 4 Task 7 didn't fire — investigate before proceeding to Task 3.

---

### Task 3: Real-feature cutover smoke

Now flip a real Notion feature from `Idea` → `Ready to Build`. The webhook fires, the relay (now routing to v2) starts a `nova-factory-v2` execution, the feature builds, the PR merges, the postdeploy probe verifies, Notion ends `Verified`.

- [ ] **Step 1: Identify the cutover feature.**

```bash
NOTION_API_KEY=$(grep NOTION_API_KEY /c/Claude/Nova/nova/.env | cut -d= -f2)
NOTION_FEATURES_DB_ID=$(grep NOTION_FEATURES_DB_ID /c/Claude/Nova/nova/.env | cut -d= -f2)
FEATURE_ID=<the page UUID you identified in P-4>
```

- [ ] **Step 2: Flip Status to "Ready to Build".**

```bash
curl -s -X PATCH "https://api.notion.com/v1/pages/$FEATURE_ID" \
  -H "Authorization: Bearer $NOTION_API_KEY" \
  -H "Notion-Version: 2022-06-28" \
  -H "Content-Type: application/json" \
  -d '{"properties": {"Status": {"status": {"name": "Ready to Build"}}}}' | jq '.properties.Status'
```
Expected: response shows `"name": "Ready to Build"`.

- [ ] **Step 3: Watch the SFN execution start.**

```bash
sleep 5  # Notion → webhook can take a few seconds
aws stepfunctions list-executions \
  --state-machine-arn arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-v2 \
  --max-results 1 --query 'executions[0].{name:name,status:status,start:startDate}'
```
Expected: a `RUNNING` execution started in the last few seconds.

If you don't see one, the webhook may have been rate-limited or routed wrong. Check the relay logs:

```bash
aws logs tail /aws/lambda/nova-webhook-relay --since 5m
```

- [ ] **Step 4: Tail until terminal.**

```bash
EXEC_ARN=$(aws stepfunctions list-executions \
  --state-machine-arn arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-v2 \
  --max-results 1 --query 'executions[0].executionArn' --output text)

# Poll
for _ in $(seq 1 120); do
  STATUS=$(aws stepfunctions describe-execution --execution-arn "$EXEC_ARN" --query status --output text)
  echo "$(date +%H:%M:%S) — $STATUS"
  if [[ "$STATUS" != "RUNNING" ]]; then break; fi
  sleep 30
done
```

This may take 5–25 minutes for a small feature (1–3 Ralph turns + Validate + Review + quality-gates). Expected terminal state: `SUCCEEDED`.

- [ ] **Step 5: Verify Notion + GitHub.**

```bash
# Notion status
curl -s -H "Authorization: Bearer $NOTION_API_KEY" -H "Notion-Version: 2022-06-28" \
  "https://api.notion.com/v1/pages/$FEATURE_ID" \
  | jq -r '.properties.Status.status.name // .properties.Status.select.name'
```
Expected: `Done` initially, then `Verified` after the postdeploy probe completes.

```bash
# GitHub: PR opened, merged
gh pr list --repo nabbic/nova --state all --search "factory-execution" --limit 5
```
Expected: a recently-merged PR for this feature.

- [ ] **Step 6: Tail the postdeploy SFN.**

```bash
aws stepfunctions list-executions \
  --state-machine-arn arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-postdeploy \
  --max-results 3
```
Expected: an execution that ran for the merge_sha of the cutover feature. `SUCCEEDED` if probes passed; investigate if `FAILED`.

---

### Task 4: Update CLAUDE.md and project status memory

**Files:**
- Modify: `CLAUDE.md`
- Modify: `~/.claude/projects/C--Claude/memory/project_nova_status.md`

- [ ] **Step 1: Update CLAUDE.md cutover status.**

In CLAUDE.md's `## Factory` section, change "Cutover status: v2 is being built in parallel with v1. The webhook still routes to the legacy `nova-factory-pipeline`..." to:

```markdown
**Cutover status:** v2 is live. The webhook routes to `nova-factory-v2` as of
2026-05-XX. The legacy `nova-factory-pipeline` and `factory.yml` GitHub
Actions workflow remain as emergency fallback for 30 days; deletion happens
in the cleanup phase of the rebuild.
```

(Replace `2026-05-XX` with the actual cutover date.)

- [ ] **Step 2: Update the auto-memory project_nova_status.md.**

```markdown
**2026-05-XX:** Factory v2 cutover complete. Webhook routes to
`nova-factory-v2`; the trivial+medium+oversized smokes pass; one real
Notion feature reached `Verified` end-to-end via the new pipeline. v1
artifacts retained for 30-day soak; deletion scheduled around 2026-06-XX.
```

(Replace dates as appropriate.)

- [ ] **Step 3: Commit (CLAUDE.md only — auto-memory is edited via the memory system, not git).**

```bash
cd /c/Claude/Nova/nova
git add CLAUDE.md
git commit -m "docs(claude.md): mark v2 cutover complete (2026-05-XX)"
git push origin factory-overhaul-2026-05-03
```

For the auto-memory file, write directly:

Edit `C:\Users\chris\.claude\projects\C--Claude\memory\project_nova_status.md` with the Edit tool. Add a new bullet under "What's Built" reflecting the cutover; update the "Next Step" section to "30-day soak; cleanup scheduled 2026-06-XX."

---

## Cutover acceptance criteria recap

1. `FACTORY_BACKEND="step-functions-v2"` in the webhook relay's environment.
2. One synthetic smoke (trivial) passed end-to-end after the flip.
3. One real Notion feature reached `Verified` via v2.
4. CLAUDE.md and project_nova_status.md memory reflect the cutover.

**STOP HERE for the cutover session.** Do not proceed to Tasks 5–11 unless the 30-day soak criteria below have passed.

---

# CLEANUP (Tasks 5–11) — execute after 30-day soak passes

## 30-day soak gate

Before running any cleanup task, **all** of the following must hold:

- [ ] **Soak G-1**: ≥10 real Notion features have shipped through v2 with no manual intervention required. (Count by `gh pr list --repo nabbic/nova --search 'factory-execution' --state merged --limit 50 | grep $(date -d "30 days ago" +%Y) | wc -l` — adjust the date filter.)

- [ ] **Soak G-2**: zero auto-pause events in 30 days. (Check `aws ssm get-parameter --name /nova/factory/paused` shows `false` and CloudTrail shows no `PutParameter` events on it from `auto_pause` Lambda.)

- [ ] **Soak G-3**: zero rollback events in 30 days. (Check the postdeploy SFN executions show `SUCCEEDED` for all entries; no `RevertMerge` invocations.)

- [ ] **Soak G-4**: monthly cost stayed under $50. (Check the AWS Budgets dashboard; or `aws ce get-cost-and-usage --time-period Start=$(date -d "30 days ago" +%Y-%m-01),End=$(date +%Y-%m-01) --granularity MONTHLY --metrics UnblendedCost --filter '{"Tags":{"Key":"Project","Values":["nova"]}}'`.)

If any of these fail, **don't clean up yet**. Diagnose, fix, and re-soak for the remainder of the 30-day window. The cost of leaving v1 alive a few extra weeks is trivial — the cost of removing it prematurely and needing it back is high.

---

### Task 5: Remove v1 Lambda definitions from Terraform

**Files:**
- Delete: `infra/factory/lambdas.tf` (v1 entries) — but `lambdas-v2.tf` and `lambdas-v2-images.tf` are SEPARATE files and stay.
- Delete: `infra/factory/state-machine.tf`
- Delete: `infra/factory/state-machine.json.tpl`
- Delete: `infra/factory/lambdas-image.tf` (v1 validator container)
- Delete: `infra/factory/dashboard.tf` (v1 dashboard)

- [ ] **Step 1: Confirm v2 files are NOT named the same as v1.**

```bash
ls /c/Claude/Nova/nova/infra/factory/lambdas*.tf /c/Claude/Nova/nova/infra/factory/state-machine*.tf /c/Claude/Nova/nova/infra/factory/dashboard*.tf
```
Expected:
```
lambdas.tf                    ← v1 (to delete)
lambdas-v2.tf                 ← v2 (keep)
lambdas-image.tf              ← v1 (to delete)
lambdas-v2-images.tf          ← v2 (keep)
state-machine.tf              ← v1 (to delete)
state-machine.json.tpl        ← v1 (to delete)
state-machine-v2.tf           ← v2 (keep)
state-machine-v2.json.tpl     ← v2 (keep)
state-machine-postdeploy.tf   ← v2 (keep)
state-machine-postdeploy.json.tpl
dashboard.tf                  ← v1 (to delete)
dashboard-v2.tf               ← v2 (keep)
```

- [ ] **Step 2: Delete the v1 files.**

```bash
cd /c/Claude/Nova/nova
git rm infra/factory/lambdas.tf
git rm infra/factory/state-machine.tf
git rm infra/factory/state-machine.json.tpl
git rm infra/factory/lambdas-image.tf
git rm infra/factory/dashboard.tf
```

- [ ] **Step 3: Run terraform plan and review the destroy list.**

```bash
cd /c/Claude/Nova/nova/infra/factory
terraform plan -input=false | tee /tmp/cleanup-plan.txt | tail -20
```
Expected destroy list:
- `aws_lambda_function.handlers["acquire_lock"]` (and 10 more — the entire v1 handler set)
- `aws_lambda_function.validate_workspace`
- `aws_cloudwatch_log_group.handlers["..."]` (set)
- `aws_sfn_state_machine.pipeline`
- `aws_cloudwatch_log_group.sfn`
- `aws_ecr_repository.validators`
- `aws_cloudwatch_dashboard.factory`
- `null_resource.build_validate_workspace` (and any others)

The destroy list should NOT contain anything with `v2`, `ralph`, or `validate_v2` in its name. **Verify carefully.**

- [ ] **Step 4: Apply the destroy.**

```bash
cd /c/Claude/Nova/nova/infra/factory
terraform apply -auto-approve
```
Expected: 30+ resources destroyed; 0 added; 0 changed (or some untag-related changes from removing v1 modules' tags).

- [ ] **Step 5: Verify v1 resources are gone.**

```bash
aws stepfunctions describe-state-machine \
  --state-machine-arn arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-pipeline \
  2>&1 | head -3
```
Expected: `ResourceNotFound` (or similar — confirming v1 is deleted).

- [ ] **Step 6: Verify v2 still healthy.**

```bash
bash /c/Claude/Nova/nova/scripts/factory_smoke_v2.sh trivial
```
Expected: `OK`.

- [ ] **Step 7: Commit.**

```bash
cd /c/Claude/Nova/nova
git commit -m "infra(factory v1): remove v1 Lambdas, state machine, validator container, dashboard (30-day soak passed)"
```

---

### Task 6: Delete v1 handler Python files

**Files:**
- Delete: handler files listed above (10 files).
- Delete: `scripts/factory_lambdas/containers/validate_workspace/` directory (the v1 container source).
- Delete: `scripts/factory_lambdas/agent_prompts/` directory (9 .md files).

- [ ] **Step 1: Confirm none of these are imported by v2 code.**

```bash
cd /c/Claude/Nova/nova
grep -rn "load_spec\|load_project_context\|run_orchestrator\|run_agent\|evaluate_security\|validate_backend\|validate_database\|validate_frontend\|validate_infrastructure\|validate_test" \
  scripts/factory_lambdas/handlers/ scripts/factory_lambdas/common/ \
  scripts/factory_lambdas/containers/ralph_turn/ scripts/factory_lambdas/containers/validate_v2/ \
  | grep -v "^scripts/factory_lambdas/handlers/load_spec.py:" \
  | grep -v "^scripts/factory_lambdas/handlers/load_project_context.py:" \
  | grep -v "^scripts/factory_lambdas/handlers/run_orchestrator.py:" \
  | grep -v "^scripts/factory_lambdas/handlers/run_agent.py:" \
  | grep -v "^scripts/factory_lambdas/handlers/evaluate_security.py:" \
  | grep -v "^scripts/factory_lambdas/handlers/validate_"
```
Expected: empty output (no v2 code references v1 handlers).

- [ ] **Step 2: Delete the v1 handlers.**

```bash
cd /c/Claude/Nova/nova
git rm scripts/factory_lambdas/handlers/load_spec.py
git rm scripts/factory_lambdas/handlers/load_project_context.py
git rm scripts/factory_lambdas/handlers/run_orchestrator.py
git rm scripts/factory_lambdas/handlers/run_agent.py
git rm scripts/factory_lambdas/handlers/evaluate_security.py
git rm scripts/factory_lambdas/handlers/validate_backend.py
git rm scripts/factory_lambdas/handlers/validate_database.py
git rm scripts/factory_lambdas/handlers/validate_frontend.py
git rm scripts/factory_lambdas/handlers/validate_infrastructure.py
git rm scripts/factory_lambdas/handlers/validate_test.py
git rm -r scripts/factory_lambdas/containers/validate_workspace/
git rm -r scripts/factory_lambdas/agent_prompts/
```

- [ ] **Step 3: Verify build still succeeds.**

```bash
cd /c/Claude/Nova/nova/scripts/factory_lambdas
bash build.sh
```
Expected: builds the v2 handlers (`load_feature`, `plan`, `mark_blocked`, `review`, `probe_staging`, `revert_merge`, `auto_pause`, `acquire_lock`, `release_lock`, `commit_and_push`, `update_notion`, `trigger_quality_gates`, `handle_quality_gate_callback`) into dist/. No errors. Note: `acquire_lock`, `release_lock`, `commit_and_push`, `update_notion`, `trigger_quality_gates`, `handle_quality_gate_callback` are kept (per spec §6.1 "Keep" column).

The build script also does `cp "$PROMPTS_SRC"/*.md "$PROMPTS_DST/"` — that's the line that reads from `.claude/agents/`. After Task 7 deletes that directory, the build script will fail at this step. **Update the build script** to remove the agent_prompts copy:

```bash
sed -i '/PROMPTS_SRC/d' /c/Claude/Nova/nova/scripts/factory_lambdas/build.sh
sed -i '/PROMPTS_DST/d' /c/Claude/Nova/nova/scripts/factory_lambdas/build.sh
sed -i '/cp "$PROMPTS_SRC"/d' /c/Claude/Nova/nova/scripts/factory_lambdas/build.sh
sed -i '/cp -r "$PROMPTS_DST"/d' /c/Claude/Nova/nova/scripts/factory_lambdas/build.sh
sed -i '/rm -rf "$DIST" "$PROMPTS_DST"/d' /c/Claude/Nova/nova/scripts/factory_lambdas/build.sh
sed -i '/mkdir -p "$DIST" "$PROMPTS_DST"/c\mkdir -p "$DIST"' /c/Claude/Nova/nova/scripts/factory_lambdas/build.sh
```

(Or hand-edit; the goal is to remove all references to `PROMPTS_SRC`, `PROMPTS_DST`, and the cp lines.)

Re-run the build:

```bash
bash /c/Claude/Nova/nova/scripts/factory_lambdas/build.sh
```
Expected: clean build, no errors.

- [ ] **Step 4: Run all tests.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/ -v
```
Expected: 59 tests still pass (none of them depend on the deleted v1 handlers).

- [ ] **Step 5: Commit.**

```bash
cd /c/Claude/Nova/nova
git add scripts/factory_lambdas/build.sh
git commit -m "factory(v1): delete v1 handlers, validator container, agent prompts (30-day soak passed)"
```

---

### Task 7: Delete v1 agent system prompts

**Files:**
- Delete: `.claude/agents/` (all 9 files).

- [ ] **Step 1: Verify no v2 code references these.**

```bash
cd /c/Claude/Nova/nova
grep -rn "\.claude/agents" scripts/ infra/ tests/ .factory/ 2>/dev/null
```
Expected: empty output.

- [ ] **Step 2: Delete the directory.**

```bash
cd /c/Claude/Nova/nova
git rm -r .claude/agents/
```

- [ ] **Step 3: Commit.**

```bash
cd /c/Claude/Nova/nova
git commit -m "factory(v1): delete .claude/agents/ (replaced by .factory/{implementer,reviewer}-system.md)"
```

---

### Task 8: Delete v1 local scripts

**Files:**
- Delete: `scripts/factory_run.py`, `scripts/agents.py`, `scripts/factory_cycle_lambdas.sh` (legacy lambda recycler), `scripts/setup_notion*.py` (only if these are v1-specific), `scripts/update_frontend_feature.py` (v1).

- [ ] **Step 1: Audit each before deleting.**

```bash
ls /c/Claude/Nova/nova/scripts/ | head -30
```

For each candidate script, check if it's referenced by anything still in use:

```bash
cd /c/Claude/Nova/nova
for f in scripts/factory_run.py scripts/agents.py scripts/factory_cycle_lambdas.sh scripts/update_frontend_feature.py; do
  echo "=== $f ==="
  grep -rln "$f" . --include="*.py" --include="*.sh" --include="*.tf" --include="*.yml" --include="*.md" | grep -v "^./.git/" || echo "(unreferenced)"
done
```
Anything that prints "(unreferenced)" is safe to delete. Anything else, investigate.

- [ ] **Step 2: Delete the safe ones.**

```bash
cd /c/Claude/Nova/nova
git rm scripts/factory_run.py
git rm scripts/agents.py
git rm scripts/factory_cycle_lambdas.sh
git rm scripts/update_frontend_feature.py
# setup_notion*.py — keep ONLY if you're certain they're not used to (re)provision the Notion DBs. They're idempotent setup scripts; usually keep.
```

- [ ] **Step 3: Commit.**

```bash
cd /c/Claude/Nova/nova
git commit -m "factory(v1): delete legacy local scripts (factory_run.py, agents.py, factory_cycle_lambdas.sh)"
```

---

### Task 9: Deprecate `factory.yml` with a banner + guard

We keep `factory.yml` for ANOTHER 30 days (per spec line "Keep for emergency fallback; remove after 30 days stable" — the soak we just exited gets us to "Phase 6 stable", and we want one more soak before deleting CI files).

**Files:**
- Modify: `.github/workflows/factory.yml`

- [ ] **Step 1: Add a deprecation banner and disable the trigger.**

Edit `.github/workflows/factory.yml`. At the top of the file, add a banner comment, and change the `on:` block to require manual dispatch only:

```yaml
# ⚠️  DEPRECATED 2026-05-XX (cutover to nova-factory-v2)
# Kept as emergency fallback. Will be deleted after 30 days of stable v2 operation.
# To trigger: requires GitHub UI manual dispatch — `repository_dispatch` is disabled.

name: Factory (DEPRECATED)

on:
  workflow_dispatch: {}
  # Original triggers DISABLED:
  # repository_dispatch:
  #   types: [factory-trigger]
```

(Replace `2026-05-XX` with the cutover date.)

- [ ] **Step 2: Commit.**

```bash
cd /c/Claude/Nova/nova
git add .github/workflows/factory.yml
git commit -m "ci(factory.yml): mark deprecated; disable repository_dispatch (manual-only trigger)"
```

---

### Task 10: Push the cleanup branch and merge

- [ ] **Step 1: Push.**

```bash
git -C /c/Claude/Nova/nova push origin factory-overhaul-2026-05-03
```

- [ ] **Step 2: Open the PR (or fast-forward to main if branch protection allows).**

```bash
gh pr create --repo nabbic/nova \
  --base main \
  --head factory-overhaul-2026-05-03 \
  --title "Factory v2 rebuild — Phases 1-6 complete" \
  --body "Replaces the 9-agent factory with the deterministic-orchestrator + 3-LLM-stage v2 pipeline. See docs/superpowers/specs/2026-05-03-factory-rebuild-design.md and the 6 phase plans under docs/superpowers/plans/."
```

- [ ] **Step 3: Let quality-gates run, merge.**

The PR is large but clean (additions + deletions are well-bounded). Quality-gates should pass.

---

### Task 11: Update auto-memory references for v2

**Files:**
- Modify (via Edit tool, not git): `~/.claude/projects/C--Claude/memory/reference_factory_runtime.md`
- Modify: `~/.claude/projects/C--Claude/memory/project_nova_status.md`
- Modify: `~/.claude/projects/C--Claude/memory/project_nova_operations.md`

- [ ] **Step 1: Update `reference_factory_runtime.md`.**

The current memory has v1 ARNs. Replace with v2:

```markdown
## Key Resources (us-east-1, account 577638385116)

| Resource | Name / ARN |
|---|---|
| Step Functions main pipeline | `arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-v2` |
| Step Functions postdeploy    | `arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-postdeploy` |
| S3 workspace bucket | `nova-factory-workspaces-577638385116` |
| DynamoDB locks table | `nova-factory-locks` |
| DynamoDB runs table | `nova-factory-runs` |
| Lambda exec role (shared) | `nova-factory-lambda-exec` |
| RalphTurn IAM role (tightened) | `nova-factory-ralph-turn-exec` |
| ECR repos | `nova-factory-ralph-turn`, `nova-factory-validator` |
| Pause flag | SSM Parameter `/nova/factory/paused` |
| CloudWatch dashboard | `nova-factory-v2` |
| SNS alerts topic | `nova-factory-alerts` |
| CloudWatch alarm (v2 failures) | `nova-factory-v2-execution-failures` |
| Budgets | `nova-factory-monthly-20`, `-50`, `-100` |

## Saved Logs Insights queries
- `nova-factory/ralph-turn-summary`
- `nova-factory/validation-failures`
- `nova-factory/execution-trace`
```

- [ ] **Step 2: Update `project_nova_status.md`.**

Replace the v1 description with:

```markdown
**2026-06-XX:** Factory v2 rebuild complete. v1 deleted (Lambdas, state machine, validator container, agent prompts, local scripts). `factory.yml` retained as deprecated emergency fallback for one more 30-day window.

**Why:** v1 had 0 of 25 SFN executions succeed end-to-end (per the 2026-05-03 design spec). v2's three-LLM-stages + deterministic-orchestrator architecture (Plan/Implement/Review) replaces it.

**How to apply:** Features flow Notion → webhook → SFN nova-factory-v2 → Plan (Haiku) → RalphLoop (Sonnet, ≤6 turns) → Validate (deterministic) → Review (Sonnet) → CommitAndPush → quality-gates → MarkDone → postdeploy probe → Verified.

## What's Built
- v2 factory state machine `nova-factory-v2` (full pipeline)
- v2 postdeploy state machine `nova-factory-postdeploy`
- RalphTurn container Lambda (Sonnet 4.6, ≤6-turn loop)
- Validate-v2 container (deterministic 6-step chain)
- Review Lambda (single Sonnet call, schema-validated output)
- Plan Lambda (Haiku 4.5 + sizing rubric)
- Self-pause flag, $20/$50/$100 budgets, v2 dashboard, 3 saved Logs Insights queries
- Auto-revert on staging probe failure

## What's NOT Built Yet
(unchanged from prior status — app features beyond /api/version)

## Next Step
Build app features: auth, engagements, scans. Stack remains FastAPI + ECS Fargate + RDS Postgres + Cognito + Cloudflare per the original design.
```

- [ ] **Step 3: Update `project_nova_operations.md`.**

The current memory references v1 commands. Update the "Manually start an execution" section to point at v2:

```bash
aws stepfunctions start-execution \
  --state-machine-arn arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-v2 \
  --name "manual-$(date +%s)" \
  --input "{\"feature_id\":\"$FEATURE_ID\"}"
```

Add the postdeploy SFN ARN to the "Key resources" list. Update "Pipeline" diagram description to match v2.

- [ ] **Step 4: Verify the memories are consistent.**

```bash
ls /c/Users/chris/.claude/projects/C--Claude/memory/
cat /c/Users/chris/.claude/projects/C--Claude/memory/MEMORY.md
```
Expected: the index points to the updated files; descriptions on each file match content.

---

## Phase 6 acceptance criteria recap

**Cutover (Tasks 1–4) — done at cutover time:**

1. `FACTORY_BACKEND="step-functions-v2"` in production.
2. Synthetic smoke (trivial fixture) passes after the flip.
3. One real Notion feature reaches `Verified` end-to-end via v2.
4. CLAUDE.md and `project_nova_status.md` reflect cutover.

**Cleanup (Tasks 5–11) — done after 30-day soak:**

5. v1 Terraform files deleted; `terraform plan` clean (no v1 resources remain).
6. v1 handler `.py` files and `validate_workspace/` container deleted.
7. `.claude/agents/` deleted.
8. v1 local scripts (`factory_run.py`, `agents.py`, etc.) deleted.
9. `factory.yml` annotated as deprecated; `repository_dispatch` trigger commented out.
10. Cleanup PR merged.
11. Auto-memory files (`project_nova_status.md`, `reference_factory_runtime.md`, `project_nova_operations.md`) refreshed to reflect v2 architecture.

---

## After Phase 6

**+30 more days:** delete `factory.yml` entirely. The post-Phase-6 stable window means v2 has run in production for 60 days; CI emergency fallback is no longer needed.

```bash
git rm .github/workflows/factory.yml
git commit -m "ci(factory.yml): delete (60-day post-cutover stability achieved)"
```

**Future deferred work (per spec §8):**
- Bedrock-native invocation
- Per-domain context bundles for the implementer
- Splitting reviewer into multiple specialized reviewers
- Multi-feature parallel execution (concurrency cap > 3)
- Bedrock AgentCore for the implementer

None of these block any product work; they're cost/quality optimizations to revisit if data justifies them.

---

## Done

The factory rebuild is complete. The repo and AWS account contain only v2 components. The architecture matches the spec at `docs/superpowers/specs/2026-05-03-factory-rebuild-design.md`. Future feature work flows through Notion → webhook → `nova-factory-v2` → PR → merge → `nova-factory-postdeploy` → Verified, with self-pause, budget tripwires, and a CloudWatch dashboard providing the operational view.
