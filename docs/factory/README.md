# Nova Software Factory v2 — Operator's Guide

The Nova Software Factory is the **autonomous CI/CD pipeline that builds the Nova
Tech DD application**. It is **NOT** the application itself. This document
covers the factory's architecture, day-to-day operation, and troubleshooting.

For the application architecture (FastAPI/Cognito/RDS/etc.), see the repo-root
[`CLAUDE.md`](../../CLAUDE.md) "Product" section. For the rebuild design that
produced today's factory, see [`docs/superpowers/specs/2026-05-03-factory-rebuild-design.md`](../superpowers/specs/2026-05-03-factory-rebuild-design.md).

---

## What the factory is (in one paragraph)

A human writes a feature description in Notion and flips its status to "Ready
to Build". An AWS Step Functions state machine picks it up, runs three LLM
stages (Plan with Haiku, Implement with Claude Code in a container Lambda,
Review with Sonnet), validates the result deterministically (ruff/mypy/pytest/
tf-validate/tsc), opens a PR, lets GitHub Actions run quality gates and
auto-merge, then a separate state machine probes staging and reverts the
merge if it doesn't deploy cleanly. The whole thing self-pauses on alarm or
budget breach.

---

## Pipeline diagram

```
                        Notion (feature → "Ready to Build")
                                    │
                                    ▼
                        nova-webhook-relay (API Gateway + Lambda)
                                    │  reads /nova/factory/paused
                                    │  if paused → 200 + Notion comment, drop
                                    ▼
                        Step Functions: nova-factory-v2
                                    │
   ┌────────────────────────────────┼──────────────────────────────────────┐
   │                                                                       │
   │  AcquireLock (DDB conditional put on feature_id)                      │
   │  MarkInProgress (Notion status="Building")                            │
   │  LoadFeature (Notion → S3 intake/spec_raw.md + feature_meta.json)     │
   │  Plan (Haiku → S3 plan/prd.json; sizing rubric merged in)             │
   │  PlanGate (Choice)                                                    │
   │     │                                                                 │
   │     ├─ blocked=true ──▶ MarkBlocked (Notion comment + Failed)         │
   │     │                   ReleaseLock                                   │
   │     │                                                                 │
   │     └─ blocked=false ──▶ LoopInit (iter=0, tokens=0)                  │
   │                          │                                            │
   │              ┌───────────▼──────────┐                                 │
   │              │ LoopChoice           │ exit on completion_signal=true, │
   │              │                      │  iter≥6, or input_tokens≥2M     │
   │              └───┬──────────────────┘                                 │
   │                  │                                                    │
   │                  ▼                                                    │
   │              RalphTurn (container Lambda; claude -p, 14-min cap)      │
   │                  │                                                    │
   │              LoopBump  ─────▶ back to LoopChoice                      │
   │                                                                       │
   │  Validate (container Lambda; ruff/mypy/pytest/tf/tsc/alembic)         │
   │     │                                                                 │
   │     ├─ passed=false ──▶ ValidateRepairTurn (≤2 cycles)                │
   │     └─ passed=true  ──▶ Review (Sonnet)                               │
   │                            │                                          │
   │                            ├─ blockers → ReviewRepairTurn (≤2 cycles) │
   │                            └─ no blockers → CommitAndPush v2          │
   │                                              (writes .factory/last-run/) │
   │                                              │                        │
   │                                              ▼                        │
   │                                          WaitForQualityGates          │
   │                                              │  (90-min timeout)      │
   │                                              ▼                        │
   │                                          MarkDone → ReleaseLock       │
   │                                                                       │
   └──────────────────────────────────────────────────────────────────────┘

After PR merges on main, deploy.yml runs and triggers:

                        Step Functions: nova-factory-postdeploy
                                    │
                          ProbeStaging (HTTP probes from PRD criteria)
                                    │
                            ┌───────┴───────┐
                            │               │
                          passed         failed
                            │               │
                            ▼               ▼
                       MarkVerified   RevertMerge (Tree API)
                                            │
                                       (revert PR opens; quality-gates
                                        auto-merges; Notion=Failed)
```

---

## Repo layout — factory vs app

| Path | Owner | What it is |
|---|---|---|
| `app/` | **App** | The Tech DD platform's Python backend. The factory builds this. |
| `frontend/` | **App** | The React+TypeScript frontend. The factory builds this. |
| `tests/` (everything except `tests/factory/`) | **App** | App test suite. The factory runs this in `Validate`. |
| `infra/factory/` | **Factory** | The Lambdas, state machines, IAM, dashboard, alarms, budgets. |
| `infra/bootstrap/` | **Factory** | One-time bootstrap module (S3 state bucket + DDB lock table). |
| `infra/webhook-relay/` | **Factory** | Notion webhook → SFN dispatch Lambda. |
| `infra/` (anything else, e.g. `infra/main.tf`) | **App** | Application infrastructure (RDS, Cognito, ECS Fargate, etc.). |
| `scripts/factory_lambdas/` | **Factory** | Source code for all factory Lambdas (handlers, common helpers, container images). |
| `scripts/factory_smoke_fixtures/` + `factory_smoke_v2.sh` | **Factory** | Synthetic feature fixtures + smoke runner. |
| `scripts/setup_notion*.py`, `notion_client.py`, `create_foundation_features.py` | **Factory** | One-time setup utilities for the Notion DB the factory reads from. |
| `tests/factory/` | **Factory** | Unit tests for factory code. 59 tests as of cutover. |
| `.factory/` | **Factory** | Schema + system prompts the factory's LLMs read at runtime. **App agents must NOT touch this.** |
| `.github/workflows/quality-gates.yml` | **Factory** | Post-PR validation pipeline. Triggered by `nova-factory-v2`. |
| `.github/workflows/deploy.yml` | **Factory** | Post-merge deploy + postdeploy SFN trigger. |

The factory's RalphTurn enforces this boundary at runtime: anything written
under `.factory/`, `infra/factory/`, or `.github/workflows/` is rejected
post-turn (see `scripts/factory_lambdas/containers/ralph_turn/allowlist.py`).

---

## AWS resources

### State machines

| ARN | Purpose |
|---|---|
| `arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-v2` | Main factory pipeline. Triggered by webhook on Notion status=Ready to Build. |
| `arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-postdeploy` | Post-merge probe + auto-revert. Triggered by `deploy.yml`. |

### Container Lambdas (image-based)

| Function | Image | Role |
|---|---|---|
| `nova-factory-ralph-turn` | `577638385116.dkr.ecr.us-east-1.amazonaws.com/nova-factory-ralph-turn:latest` | Runs `claude -p` in a workspace materialized from S3. 14-min timeout. Tightened IAM (`nova-factory-ralph-turn-exec`) — S3 prefix scoped, anthropic + GitHub secrets only. |
| `nova-factory-validate-v2` | `577638385116.dkr.ecr.us-east-1.amazonaws.com/nova-factory-validator:latest` | Deterministic 6-step chain. Shared IAM role. |

### Zip Lambdas

**v2-only:** `nova-factory-{load-feature, plan, mark-blocked, review, commit-and-push-v2, probe-staging, revert-merge, auto-pause}`.

**Shared (used by current v2 SFN; survived v1 cleanup):** `nova-factory-{acquire-lock, release-lock, update-notion, trigger-quality-gates, handle-quality-gate-callback}`.

All zip Lambdas use the shared layer `nova-factory-shared` (anthropic, requests,
httpx, anyio, ruff, mypy, pytest, jsonschema). Build via
`scripts/factory_lambdas/build.sh`.

### Storage + state

| Resource | Purpose |
|---|---|
| `s3://nova-factory-workspaces-577638385116/<execution_id>/` | Per-execution working directory. `intake/`, `plan/`, `workspace/`, `validate/`, `review/`. 14-day TTL. |
| `dynamodb:nova-factory-locks` | Per-feature lock (conditional put on `feature_id`). |
| `dynamodb:nova-factory-runs` | Run history (one row per execution). |
| `dynamodb:nova-terraform-locks` | Terraform state locking. |
| `s3://nova-terraform-state-577638385116/` | Terraform state for all Nova modules. |

### Operational levers

| Lever | What | Where |
|---|---|---|
| `/nova/factory/paused` | SSM parameter — when `true`, webhook relay 200-OKs without dispatching, posts a Notion comment. | SSM Parameter Store |
| `nova-factory-v2-execution-failures` alarm | 3 consecutive 5-min periods with ≥1 ExecutionsFailed. Fires SNS → auto_pause flips the flag. | CloudWatch |
| `nova-factory-monthly-100` budget | Monthly cost ceiling. ALARM notification → SNS → auto_pause. | AWS Budgets |
| `nova-factory-monthly-50` budget | Warning. Notifies, doesn't pause. | AWS Budgets |
| `nova-factory-monthly` budget | $20 monthly soft warn. Email-only. | AWS Budgets |

### Observability

| Tool | Where |
|---|---|
| Dashboard | [`nova-factory-v2`](https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards:name=nova-factory-v2) — SFN executions, Lambda invocations, validate duration, plan/review duration, recent RalphTurn outcomes |
| Saved query: `ralph-turn-summary` | Hourly turn count + cumulative tokens |
| Saved query: `validation-failures` | Recent Validate `passed: false` events |
| Saved query: `execution-trace` | Cross-source log timeline (replace `<execution-id>` with the SFN execution name) |
| Email alerts | `nabbic@gmail.com` via SNS topic `nova-factory-alerts` |

---

## Common operations

> Git Bash on Windows: AWS CLI commands that take parameter names starting
> with `/` need `MSYS_NO_PATHCONV=1` to prevent path conversion.

### Pause the factory

```bash
MSYS_NO_PATHCONV=1 aws ssm put-parameter \
  --name /nova/factory/paused --value true --type String --overwrite
```

The webhook relay reads this on every Notion delivery. Paused = 200-OK with
a Notion comment. **In-flight executions are not interrupted** — they finish
naturally; new dispatches just don't start. Auto-pause does NOT auto-unpause:
humans reset by setting `false`.

### Resume the factory

```bash
MSYS_NO_PATHCONV=1 aws ssm put-parameter \
  --name /nova/factory/paused --value false --type String --overwrite
```

### Manually start an execution

```bash
FEATURE_ID="<notion-page-uuid>"
aws stepfunctions start-execution \
  --state-machine-arn arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-v2 \
  --name "manual-$(date +%s)" \
  --input "{\"feature_id\":\"$FEATURE_ID\"}"
```

### Watch an execution

```bash
EXEC_ARN=$(aws stepfunctions list-executions \
  --state-machine-arn arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-v2 \
  --max-results 1 --query 'executions[0].executionArn' --output text)

# Poll status
aws stepfunctions describe-execution --execution-arn "$EXEC_ARN" --query status --output text

# State-by-state history (use boto3 if AWS CLI's text output mangles unicode)
python -c "
import boto3
c = boto3.client('stepfunctions')
for e in c.get_execution_history(executionArn='$EXEC_ARN', reverseOrder=False, maxResults=200)['events']:
    name = (e.get('stateExitedEventDetails') or e.get('stateEnteredEventDetails') or {}).get('name', '')
    if name: print(e['timestamp'], e['type'], name)
"

# Tail RalphTurn logs (the implementer)
MSYS_NO_PATHCONV=1 aws logs tail /aws/lambda/nova-factory-ralph-turn --follow
```

### Inspect a run's S3 workspace

```bash
EXEC_NAME=<from list-executions>
aws s3 ls s3://nova-factory-workspaces-577638385116/$EXEC_NAME/ --recursive | head
aws s3 cp s3://nova-factory-workspaces-577638385116/$EXEC_NAME/plan/prd.json -
aws s3 cp s3://nova-factory-workspaces-577638385116/$EXEC_NAME/validate/issues.json -
aws s3 cp s3://nova-factory-workspaces-577638385116/$EXEC_NAME/review/blockers.json -
```

### Run smoke tests

```bash
# Single fixture (creates a synthetic Notion page, runs the full pipeline)
bash scripts/factory_smoke_v2.sh trivial    # 1 story, expects Done
bash scripts/factory_smoke_v2.sh medium     # ~3 stories, expects Done
bash scripts/factory_smoke_v2.sh oversized  # 5+ stories, expects blocked at Plan

# Each smoke run costs ~$0.50–$1.50 in Sonnet/Haiku tokens for trivial/medium,
# ~$0.013 for oversized (Haiku-only, blocked at Plan).
```

### Rebuild and redeploy a Lambda

```bash
# Zip Lambdas — rebuild + apply
bash scripts/factory_lambdas/build.sh
cd infra/factory && terraform apply -auto-approve -var=github_owner=nabbic
# (Re-run apply if you hit "filebase64sha256: inconsistent result" — known race; second pass converges.)

# Container Lambdas — build + push image, then apply to bump the image digest pin
bash scripts/factory_lambdas/containers/ralph_turn/build.sh
bash scripts/factory_lambdas/containers/validate_v2/build.sh
cd infra/factory && terraform apply -auto-approve -var=github_owner=nabbic
```

### Run unit tests

```bash
pytest tests/factory/ -v   # 59 tests as of v2 cutover
```

The `tests/factory/` suite is independent of the app; it doesn't import
`fastapi` or app modules.

---

## Cost model (per-feature)

Sonnet 4.6 + Haiku 4.5 with prompt caching:

| Stage | Model | Tokens (in/out) | Cost |
|---|---|---|---|
| Plan | Haiku 4.5 | 5K / 1.5K | $0.013 |
| RalphLoop (typical, 4 turns) | Sonnet 4.6 | 4×(4K cached + 22K uncached) / 4×9K | $0.61 |
| RalphLoop (worst, 6 turns + repairs) | Sonnet 4.6 | 6×(4K cached + 26K uncached) / 6×11K | $1.38 |
| Review | Sonnet 4.6 | 30K / 3K | $0.135 |
| Lambda compute (free-tier covers ~110 features/month) | — | — | $0–0.06 |
| S3 + DDB + SFN + CW | — | — | < $0.01 |
| **Per-feature, typical** | | | **~$0.76** |
| **Per-feature, worst case** | | | **~$1.59** |

Budget tripwires at $20 (warn email), $50 (warn email + SNS), $100 (auto-pause).
At 50 features/month the typical bill is ~$38 — well under the $50 warning.

---

## Hard sandbox boundaries

The RalphTurn implementer runs `claude -p --dangerously-skip-permissions`
inside a Lambda container. **Eight layers of containment limit blast radius:**

1. **GitHub PAT scope** — fine-grained, single-repo, `contents:write` + `pull_requests:write` only. No `workflow` scope; the implementer cannot edit CI.
2. **Branch protection on `main`** — required check `quality-gates`; only the bot identity can push; no admin override.
3. **Lambda IAM least privilege** — `nova-factory-ralph-turn-exec` allows S3 read/write to the workspace bucket only, Secrets Manager for `nova/factory/anthropic-api-key` and `nova/factory/github-token` only. **No** broad AWS, **no** Notion DB access.
4. **Filesystem allowlist on workspace upload** — `scripts/factory_lambdas/containers/ralph_turn/allowlist.py` rejects paths under `.github/workflows/*`, `.factory/*` (except `.factory/_DONE_`), `infra/factory/*`, `..`, or absolute paths. Rejected writes are reverted in the workspace and surfaced in `repair_context.md` as `DENIED:` lines.
5. **Reviewer sees diff, not reasoning** — separate Sonnet call with separate prompt; no implementer reasoning trace.
6. **Token-budget hard stop** — 6 outer turns × 30 inner turns max; 2M input tokens or 200K output tokens trips `MarkBudgetExceeded`.
7. **SFN concurrency cap of 3** — relay refuses if ≥ 3 in-flight executions.
8. **Auditability** — every commit message includes `factory-execution: <execution-id>`; SFN executions retained 1 year; every Anthropic call logs `feature_id` + `execution_id` + `turn` + token counts.

---

## Irreducible human touchpoints

The factory is fully autonomous in steady state. Three things still need humans:

1. **Write the feature description** in Notion.
2. **Resume after auto-pause** — alarm or budget tripwire flipped `/nova/factory/paused`. Humans diagnose root cause, then `aws ssm put-parameter --name /nova/factory/paused --value false`.
3. **Approve non-free-tier AWS resource choices** — Plan emits `non_free_tier_resource_unconfirmed` in `hard_blockers` for any new AWS resource not on the cost-policy whitelist (CLAUDE.md). MarkBlocked posts the proposed resource + rationale to Notion; human re-files the feature description with `cost_approved: true` to acknowledge.

---

## Where to learn more

| Topic | File |
|---|---|
| The original design rationale (why this shape) | [`docs/superpowers/specs/2026-05-03-factory-rebuild-design.md`](../superpowers/specs/2026-05-03-factory-rebuild-design.md) |
| Implementation history (how we got here) | [`docs/superpowers/plans/2026-05-03-factory-v2-phase{1..6}-*.md`](../superpowers/plans/) |
| Incident response runbook | [`docs/runbooks/factory-incident.md`](../runbooks/factory-incident.md) |
| Sizing rubric humans use to self-size features | [`.factory/feature-sizing-rubric.md`](../../.factory/feature-sizing-rubric.md) |
| Implementer system prompt (read at every Ralph turn) | [`.factory/implementer-system.md`](../../.factory/implementer-system.md) |
| Reviewer system prompt | [`.factory/reviewer-system.md`](../../.factory/reviewer-system.md) |
| PRD JSON schema (single source of truth) | [`.factory/prd.schema.json`](../../.factory/prd.schema.json) |
