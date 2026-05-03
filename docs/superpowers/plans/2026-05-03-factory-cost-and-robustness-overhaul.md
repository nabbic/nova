# Nova Factory — Cost & Robustness Overhaul

**Date:** 2026-05-03
**Owner:** Sonnet (autonomous execution)
**Estimated effort:** 1 long autonomous session (~4–6 hours of agent work)
**Status:** Ready to execute

---

## Mission

Move the Nova factory's expensive long-running agent execution OFF GitHub Actions and onto **AWS Lambda + Step Functions**, while substantially upgrading robustness (concurrency locking, resumability, repair loops, parallel execution, per-agent model tiering). After this is done the GitHub Actions runner only runs short quality gates and merges (~5 min/build), instead of sitting idle for 15–30 min waiting on Anthropic API responses.

This plan is designed to be **executed end-to-end by Sonnet without human interaction**. The user has pre-authorised `terraform apply` for Nova factory infrastructure (see `feedback_terraform_apply.md` in user memory). Apply Terraform automatically when validation passes.

---

## Operating context (do not skip)

- **Working dir:** `C:\Claude\Nova\nova`
- **Repo:** https://github.com/nabbic/nova (default branch `main`)
- **AWS account:** `577638385116`, region `us-east-1`, profile `default` (SSO)
- **Existing infra:** API Gateway `nova-webhook-relay` + Lambda `nova-webhook-relay` (Node.js) in `infra/webhook-relay/`. Secrets Manager already holds `nova/webhook-relay/notion-api-key` and `nova/webhook-relay/github-token`.
- **Existing factory:** `scripts/factory_run.py` (Python) + `scripts/agents.py` + `.github/workflows/factory.yml`. Agents in `.claude/agents/`. Notion DB IDs in `.env`.
- **GitHub auth:** A fine-grained PAT lives in `.env` as `GH_TOKEN`. CI uses `secrets.GH_TOKEN` and `secrets.ANTHROPIC_API_KEY`.
- **Hard rule:** never commit secrets, `.env`, or anything in `.factory-workspace/`.

When in doubt about an existing pattern, **read the file first** before writing new code that diverges from it.

---

## State tracking

Maintain an execution log at `.factory-overhaul-state.json` (gitignored). Update after each completed phase:

```json
{
  "phase": "P3",
  "completed": ["P0", "P1", "P2"],
  "last_action": "Created Step Functions state machine",
  "notes": []
}
```

If you (Sonnet) lose context partway through, read this file first to know where to resume.

Add `.factory-overhaul-state.json` to `.gitignore` in P0.

---

## Target architecture

```
                    Notion ("Ready to Build")
                            │
                            ▼
                ┌───────────────────────┐
                │ API Gateway (existing) │
                └──────────┬─────────────┘
                           ▼
              ┌──────────────────────────┐
              │ webhook Lambda (UPDATED) │
              │  routes by FACTORY_BACKEND│
              └─────┬────────────────┬───┘
        backend=    │                │   backend=
        step-funcs  ▼                ▼  github-actions
        ┌─────────────────┐   ┌────────────────┐
        │  StartExecution │   │ repository     │ ← existing path
        │  on Step Funcs  │   │ dispatch event │   (kept as fallback)
        └────────┬────────┘   └────────────────┘
                 ▼
   ┌─────────────────────────────────────────────────────┐
   │  Step Functions Standard State Machine              │
   │  "nova-factory-pipeline"                            │
   │                                                     │
   │  AcquireLock → MarkInProgress → LoadSpec →          │
   │  RunOrchestrator → RunSpecAnalyst →                 │
   │  Choice(architect?) → RunArchitect →                │
   │  Choice(database?) → RunDatabase →                  │
   │  Parallel(backend, frontend, infrastructure) →      │
   │  RunTest → RunSecurityReview →                      │
   │  Choice(security passed?) →                         │
   │     Yes: CommitAndPush → TriggerQualityGates → Wait │
   │          → Choice(gates passed?)                    │
   │             Yes: MergePR → MarkDone → ReleaseLock   │
   │             No:  RunRepair → re-test → re-gate      │
   │                  (max 1 repair cycle)               │
   │     No:  RunRepair (security) → re-review           │
   │          (max 1 repair cycle, then MarkFailed)      │
   │                                                     │
   │  Catch all → MarkFailed → ReleaseLock               │
   └────────────┬────────────────────────────────────────┘
                ▼
   ┌──────────────────────────────────────────────┐
   │  S3 workspace bucket                         │
   │  s3://nova-factory-workspaces-577638385116/  │
   │  <execution-id>/                             │
   │     plan.json                                │
   │     requirements.json                        │
   │     architecture.json                        │
   │     security-review.json                     │
   │     code/<rel-path>... (file map outputs)    │
   └──────────────────────────────────────────────┘

   ┌──────────────────────────────────────────────┐
   │  DynamoDB tables                             │
   │  nova-factory-locks   (pkey feature_id, TTL) │
   │  nova-factory-runs    (pkey execution_id,    │
   │                        sk step)              │
   └──────────────────────────────────────────────┘

   ┌──────────────────────────────────────────────┐
   │  GitHub Actions: quality-gates.yml (NEW)     │
   │  on: workflow_dispatch from Step Functions   │
   │  - checkout feature branch                   │
   │  - lint, mypy, pytest, docker build, tf val  │
   │  - POST result back to API Gateway callback  │
   │    endpoint with task token                  │
   └──────────────────────────────────────────────┘
```

---

## Phase 0 — Pre-flight

**Goal:** Verify access, snapshot current state, set up state tracking.

1. Verify AWS access:
   ```bash
   aws sts get-caller-identity --output json
   ```
   Confirm account is `577638385116`.

2. Verify GitHub access:
   ```bash
   GH_TOKEN=$(grep '^GH_TOKEN=' /c/Claude/Nova/nova/.env | cut -d= -f2-)
   curl -sH "Authorization: token $GH_TOKEN" https://api.github.com/repos/nabbic/nova | jq -r '.full_name'
   ```
   Should print `nabbic/nova`.

3. Verify Notion access:
   ```bash
   NOTION_API_KEY=$(grep '^NOTION_API_KEY=' /c/Claude/Nova/nova/.env | cut -d= -f2-)
   FEATURES_DB_ID=$(grep '^NOTION_FEATURES_DB_ID=' /c/Claude/Nova/nova/.env | cut -d= -f2-)
   curl -s -X POST "https://api.notion.com/v1/databases/$FEATURES_DB_ID/query" \
     -H "Authorization: Bearer $NOTION_API_KEY" \
     -H "Notion-Version: 2022-06-28" -H "Content-Type: application/json" \
     -d '{"page_size":1}' | jq -r '.results[0].id'
   ```
   Should print a UUID.

4. Snapshot current Terraform state for the webhook relay:
   ```bash
   cd /c/Claude/Nova/nova/infra/webhook-relay
   terraform state list > /tmp/factory-pre-overhaul-state.txt
   ```

5. Add `.factory-overhaul-state.json` to `.gitignore`. Initialise it:
   ```json
   {"phase": "P0", "completed": [], "last_action": "preflight passed", "notes": []}
   ```

6. Create a feature branch for the overhaul:
   ```bash
   git checkout -b factory-overhaul-2026-05-03
   ```

**Done when:** all three access checks pass and state file exists.

---

## Phase 1 — Foundational AWS resources

**Goal:** Stand up S3, DynamoDB, Secrets Manager entries, and IAM roles before any Lambda code is written.

### Files to create

```
infra/factory/
├── main.tf            # provider, locals
├── s3.tf              # workspace bucket
├── dynamodb.tf        # locks + runs tables
├── iam.tf             # Lambda exec role, policies
├── secrets.tf         # data sources for ANTHROPIC_API_KEY, etc.
├── variables.tf
├── outputs.tf
└── README.md          # how this module relates to webhook-relay
```

**Important:** Use a **separate Terraform root** at `infra/factory/` so the existing webhook-relay state is untouched. Use a local backend for now (state file gitignored). Migration to S3 backend can happen later.

### `infra/factory/main.tf`

```hcl
terraform {
  required_version = ">= 1.7"
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 5.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.0" }
  }
}

provider "aws" {
  region = var.aws_region
}

locals {
  name_prefix = "nova-factory"
  common_tags = {
    Project   = "nova"
    Component = "factory"
    ManagedBy = "terraform"
  }
}

data "aws_caller_identity" "current" {}
```

### `infra/factory/variables.tf`

```hcl
variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "github_owner" {
  type    = string
  default = "nabbic"
}

variable "github_repo" {
  type    = string
  default = "nova"
}

variable "workspace_retention_days" {
  type        = number
  default     = 14
  description = "How long to keep factory workspace S3 objects before lifecycle deletes them"
}
```

### `infra/factory/s3.tf`

```hcl
resource "aws_s3_bucket" "workspaces" {
  bucket = "${local.name_prefix}-workspaces-${data.aws_caller_identity.current.account_id}"
  tags   = local.common_tags
}

resource "aws_s3_bucket_versioning" "workspaces" {
  bucket = aws_s3_bucket.workspaces.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "workspaces" {
  bucket = aws_s3_bucket.workspaces.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_public_access_block" "workspaces" {
  bucket                  = aws_s3_bucket.workspaces.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "workspaces" {
  bucket = aws_s3_bucket.workspaces.id
  rule {
    id     = "expire-old-workspaces"
    status = "Enabled"
    expiration { days = var.workspace_retention_days }
    noncurrent_version_expiration { noncurrent_days = 7 }
  }
}
```

### `infra/factory/dynamodb.tf`

```hcl
resource "aws_dynamodb_table" "locks" {
  name         = "${local.name_prefix}-locks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "feature_id"

  attribute { name = "feature_id"  type = "S" }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery { enabled = true }
  tags = local.common_tags
}

resource "aws_dynamodb_table" "runs" {
  name         = "${local.name_prefix}-runs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "execution_id"
  range_key    = "step"

  attribute { name = "execution_id" type = "S" }
  attribute { name = "step"         type = "S" }
  attribute { name = "feature_id"   type = "S" }

  global_secondary_index {
    name            = "by-feature"
    hash_key        = "feature_id"
    range_key       = "step"
    projection_type = "ALL"
  }

  point_in_time_recovery { enabled = true }
  tags = local.common_tags
}
```

### `infra/factory/iam.tf`

Create the Lambda execution role with permissions for: CloudWatch Logs, S3 workspace bucket, DynamoDB tables, Secrets Manager (read), Step Functions (start execution + send task heartbeat), and X-Ray.

```hcl
resource "aws_iam_role" "lambda_exec" {
  name = "${local.name_prefix}-lambda-exec"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "lambda_xray" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

resource "aws_iam_role_policy" "lambda_factory" {
  name = "${local.name_prefix}-permissions"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
        Resource = [
          aws_s3_bucket.workspaces.arn,
          "${aws_s3_bucket.workspaces.arn}/*",
        ]
      },
      {
        Effect   = "Allow"
        Action   = [
          "dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem",
          "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:ConditionCheckItem",
        ]
        Resource = [
          aws_dynamodb_table.locks.arn,
          aws_dynamodb_table.runs.arn,
          "${aws_dynamodb_table.runs.arn}/index/*",
        ]
      },
      {
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:nova/factory/*"
      },
      {
        Effect   = "Allow"
        Action   = ["states:SendTaskSuccess", "states:SendTaskFailure", "states:SendTaskHeartbeat"]
        Resource = "*"
      },
    ]
  })
}

# Step Functions execution role
resource "aws_iam_role" "sfn_exec" {
  name = "${local.name_prefix}-sfn-exec"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "states.amazonaws.com" }
    }]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy" "sfn_permissions" {
  name = "${local.name_prefix}-sfn-permissions"
  role = aws_iam_role.sfn_exec.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:${local.name_prefix}-*"
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery",
                   "logs:DeleteLogDelivery", "logs:ListLogDeliveries", "logs:PutResourcePolicy",
                   "logs:DescribeResourcePolicies", "logs:DescribeLogGroups"]
        Resource = "*"
      },
    ]
  })
}
```

### `infra/factory/secrets.tf`

```hcl
# Application-runtime secrets used by the factory Lambdas.
# Create these manually before first apply (one-time bootstrap):
#   aws secretsmanager create-secret --name nova/factory/anthropic-api-key --secret-string "$ANTHROPIC_API_KEY"
#   aws secretsmanager create-secret --name nova/factory/notion-api-key --secret-string "$NOTION_API_KEY"
#   aws secretsmanager create-secret --name nova/factory/github-token --secret-string "$GH_TOKEN"
#   aws secretsmanager create-secret --name nova/factory/notion-features-db-id --secret-string "$NOTION_FEATURES_DB_ID"
#   aws secretsmanager create-secret --name nova/factory/notion-runs-db-id --secret-string "$NOTION_RUNS_DB_ID"
#   aws secretsmanager create-secret --name nova/factory/notion-decisions-db-id --secret-string "$NOTION_DECISIONS_DB_ID"

# These are referenced by ARN in Lambda environment.
data "aws_secretsmanager_secret" "anthropic_api_key"      { name = "nova/factory/anthropic-api-key" }
data "aws_secretsmanager_secret" "notion_api_key"         { name = "nova/factory/notion-api-key" }
data "aws_secretsmanager_secret" "github_token"           { name = "nova/factory/github-token" }
data "aws_secretsmanager_secret" "notion_features_db_id"  { name = "nova/factory/notion-features-db-id" }
data "aws_secretsmanager_secret" "notion_runs_db_id"      { name = "nova/factory/notion-runs-db-id" }
data "aws_secretsmanager_secret" "notion_decisions_db_id" { name = "nova/factory/notion-decisions-db-id" }
```

### `infra/factory/outputs.tf`

```hcl
output "workspace_bucket"        { value = aws_s3_bucket.workspaces.bucket }
output "locks_table"             { value = aws_dynamodb_table.locks.name }
output "runs_table"              { value = aws_dynamodb_table.runs.name }
output "lambda_exec_role_arn"    { value = aws_iam_role.lambda_exec.arn }
output "sfn_exec_role_arn"       { value = aws_iam_role.sfn_exec.arn }
```

### Bootstrap secrets (run once, before terraform apply)

```bash
cd /c/Claude/Nova/nova
# shellcheck disable=SC1091
set -a; source <(sed 's/^/export /' .env); set +a

aws secretsmanager create-secret --name nova/factory/anthropic-api-key      --secret-string "$ANTHROPIC_API_KEY"      2>/dev/null || \
  aws secretsmanager put-secret-value --secret-id nova/factory/anthropic-api-key --secret-string "$ANTHROPIC_API_KEY"
aws secretsmanager create-secret --name nova/factory/notion-api-key         --secret-string "$NOTION_API_KEY"         2>/dev/null || \
  aws secretsmanager put-secret-value --secret-id nova/factory/notion-api-key --secret-string "$NOTION_API_KEY"
aws secretsmanager create-secret --name nova/factory/github-token           --secret-string "$GH_TOKEN"               2>/dev/null || \
  aws secretsmanager put-secret-value --secret-id nova/factory/github-token --secret-string "$GH_TOKEN"
aws secretsmanager create-secret --name nova/factory/notion-features-db-id  --secret-string "$NOTION_FEATURES_DB_ID"  2>/dev/null || \
  aws secretsmanager put-secret-value --secret-id nova/factory/notion-features-db-id --secret-string "$NOTION_FEATURES_DB_ID"
aws secretsmanager create-secret --name nova/factory/notion-runs-db-id      --secret-string "$NOTION_RUNS_DB_ID"      2>/dev/null || \
  aws secretsmanager put-secret-value --secret-id nova/factory/notion-runs-db-id --secret-string "$NOTION_RUNS_DB_ID"
aws secretsmanager create-secret --name nova/factory/notion-decisions-db-id --secret-string "$NOTION_DECISIONS_DB_ID" 2>/dev/null || \
  aws secretsmanager put-secret-value --secret-id nova/factory/notion-decisions-db-id --secret-string "$NOTION_DECISIONS_DB_ID"
```

### Apply

```bash
cd /c/Claude/Nova/nova/infra/factory
terraform init
terraform validate
terraform plan -out=tfplan
terraform apply tfplan
terraform output -json > .outputs.json
```

**Verification:**
```bash
aws s3 ls s3://nova-factory-workspaces-577638385116
aws dynamodb describe-table --table-name nova-factory-locks --query 'Table.TableStatus'
aws dynamodb describe-table --table-name nova-factory-runs  --query 'Table.TableStatus'
```

All three commands should succeed and report `ACTIVE`.

**Done when:** Terraform apply succeeds, outputs file exists, all three resources verified.

---

## Phase 2 — Agent definition refactor

**Goal:** Improve agent prompts before they get embedded in Lambda functions. Pure repo edits — no AWS work in this phase.

### Per-agent edits

#### `orchestrator.md`
- Add an explicit `parallel_groups` array to the output schema so Step Functions can fan out independent agents:
  ```json
  "parallel_groups": [
    ["database"],
    ["backend", "frontend", "infrastructure"],
    ["test"]
  ]
  ```
  Rules: agents in the same inner array run concurrently; outer array entries are sequential. `spec-analyst` and `architect` always run before `parallel_groups`. `security-reviewer` always runs last.
- Add a `model_hint` field per agent (`"haiku" | "sonnet" | "opus"`) — orchestrator can override default tiering when a feature is unusually trivial or unusually complex.
- Add explicit guidance to **always** emit `parallel_groups` (never empty).

#### `spec-analyst.md`
- Switch default model to **haiku** in agent runner (no prompt change needed; runner reads model from a per-agent config map).
- Tighten "blockers" guidance: the autonomous factory never halts on soft questions — only on contradictions that make implementation undefined.

#### `architect.md`
- Require output to include a structured `decisions[]` array (id, area, choice, rationale, ripple_effects). The runner will append each decision to a Notion `Decisions Log` row.
- Require it to update `CLAUDE.md` only via a delta block in its file map (key `CLAUDE.md.delta`) — runner merges the delta into `CLAUDE.md`. This avoids race conditions when multiple architect runs happen back to back.

#### `database.md`
- No changes needed beyond confirming model = sonnet.

#### `backend.md`
- **Critical change**: stop unconditional regeneration of `Dockerfile`, `.dockerignore`, `docker-compose.yml`. Replace the "always include" rule with: include them in the file map ONLY if (a) they don't exist yet OR (b) this feature requires a change. The runner will diff the existing files against the agent's output and reject regenerations that don't actually change anything.
- Add a "repair mode" section: when invoked with a `repair_context` (test failures, security issues), focus only on fixing those issues without touching unrelated code. The agent runner sets `repair_context` on retry invocations.
- Add a "self-check" requirement: after generating files, the agent must include a `_self_check` JSON sibling key (sibling to file paths in the file map) listing: which acceptance criteria each file satisfies, and which acceptance criteria are NOT yet covered.

#### `frontend.md`
- Currently only 1.1KB — under-specified. Bring it up to parity with backend:
  - Stack: Vite + React 18 + TypeScript + React Router 6 (already in CLAUDE.md)
  - Routing convention: `/buyer/...`, `/seller/...`, `/advisor/...`
  - State: TanStack Query for server state, Zustand for client state. Add this to CLAUDE.md if not already there.
  - Tests: Vitest unit + Playwright e2e
  - Output a `frontend/` subtree (mirrors `app/`)
  - Same "repair mode" + `_self_check` rules as backend
  - Same JSON-only file-map output format

#### `infrastructure.md`
- Add explicit cost-tag enforcement: every Terraform resource must have `tags = { Project = "nova", Environment = var.environment, Component = "<name>" }`.
- Add "repair mode" support.

#### `test.md`
- Keep the "never overwrite" rule.
- Add: if `repair_context` is provided with failing test paths, generate an additional file `tests/test_<feature>_regression.py` that pins the failure (after backend has fixed it). Do NOT modify the failing test.

#### `security-reviewer.md`
- Switch default model to **opus** in agent runner.
- Add: if a previous review failed and produced fixes, you receive both the original issues and the diff that attempted to fix them — verify each issue is actually resolved in the new code, don't re-flag things already fixed.
- Add a `repairable` boolean per issue: `true` if the originating agent can plausibly fix it in one round, `false` for fundamental design issues. The state machine uses this to decide whether to enter the repair loop or fail immediately.

### Verification

For each modified agent file, smoke-check:
- Markdown is valid (no broken code fences)
- Schema examples are valid JSON when extracted

```bash
for f in /c/Claude/Nova/nova/.claude/agents/*.md; do
  python3 -c "
import re, json, sys
text = open('$f').read()
for m in re.finditer(r'\`\`\`json\n([\s\S]*?)\n\`\`\`', text):
    try: json.loads(m.group(1))
    except Exception as e: print('BAD JSON in $f:', e); sys.exit(1)
print('OK: $f')
"
done
```

**Done when:** all agent files updated, JSON examples parse cleanly, file structure intact.

---

## Phase 3 — Shared Lambda layer

**Goal:** Build a single Python layer with shared dependencies (anthropic, requests, boto3 already in runtime). All Lambdas import from it.

### Files

```
infra/factory/lambda-layer/
├── build.sh            # produces layer.zip
└── requirements.txt    # anthropic>=0.40, requests>=2.32
```

### `build.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
rm -rf "$HERE/python" "$HERE/layer.zip"
mkdir -p "$HERE/python"
pip install --target "$HERE/python" -r "$HERE/requirements.txt" --quiet
cd "$HERE" && zip -r layer.zip python/ -q
echo "layer.zip built ($(du -h layer.zip | cut -f1))"
```

### Add to `infra/factory/main.tf` (or new `lambda-layer.tf`)

```hcl
resource "null_resource" "build_layer" {
  triggers = {
    requirements = filemd5("${path.module}/lambda-layer/requirements.txt")
  }
  provisioner "local-exec" {
    command = "bash ${path.module}/lambda-layer/build.sh"
  }
}

resource "aws_lambda_layer_version" "shared" {
  filename            = "${path.module}/lambda-layer/layer.zip"
  source_code_hash    = filebase64sha256("${path.module}/lambda-layer/layer.zip")
  layer_name          = "${local.name_prefix}-shared"
  compatible_runtimes = ["python3.12"]
  depends_on          = [null_resource.build_layer]
}
```

Add `terraform { required_providers { null = { source = "hashicorp/null", version = "~> 3.0" } } }`.

**Verification:**
```bash
bash /c/Claude/Nova/nova/infra/factory/lambda-layer/build.sh
unzip -l /c/Claude/Nova/nova/infra/factory/lambda-layer/layer.zip | grep anthropic
```

**Done when:** layer.zip built and contains the anthropic package.

---

## Phase 4 — Lambda functions

**Goal:** Implement every Lambda. All in Python 3.12, packaged as individual zips.

### Layout

```
scripts/factory_lambdas/
├── common/
│   ├── __init__.py
│   ├── workspace.py      # S3 read/write helpers
│   ├── runs.py           # DynamoDB run-tracking helpers
│   ├── locks.py          # acquire/release feature lock
│   ├── notion.py         # Notion API client (port from scripts/notion_client.py)
│   ├── github.py         # GitHub API client (port from scripts/github_client.py)
│   ├── secrets.py        # Secrets Manager fetch with caching
│   └── agent_runner.py   # Anthropic call + JSON extraction + retry
├── handlers/
│   ├── acquire_lock.py
│   ├── release_lock.py
│   ├── load_spec.py
│   ├── run_orchestrator.py
│   ├── run_agent.py             # generic; takes agent_name from event
│   ├── run_security_reviewer.py # special: opus model + diff awareness
│   ├── commit_and_push.py
│   ├── update_notion.py
│   ├── trigger_quality_gates.py
│   └── handle_quality_gate_callback.py
├── agent_prompts/        # baked-in copies of .claude/agents/*.md
│   └── (synced at build time)
└── build.sh              # zips each handler with common/ + agent_prompts/
```

### Per-agent model and config map

In `scripts/factory_lambdas/common/agent_runner.py`:

```python
# Per-agent model tiering. Anthropic pricing as of late 2025:
#   haiku-4.5 ≈ $0.80/M in, $4/M out  — JSON-deterministic agents
#   sonnet-4.6 ≈ $3/M in, $15/M out   — code generation
#   opus-4.7 ≈ $15/M in, $75/M out    — security review (rigour matters)
AGENT_CONFIG = {
    "orchestrator":      {"model": "claude-haiku-4-5-20251001", "max_tokens": 4096},
    "spec-analyst":      {"model": "claude-haiku-4-5-20251001", "max_tokens": 4096},
    "architect":         {"model": "claude-sonnet-4-6",         "max_tokens": 8192},
    "database":          {"model": "claude-sonnet-4-6",         "max_tokens": 16384},
    "backend":           {"model": "claude-sonnet-4-6",         "max_tokens": 32768},
    "frontend":          {"model": "claude-sonnet-4-6",         "max_tokens": 32768},
    "infrastructure":    {"model": "claude-sonnet-4-6",         "max_tokens": 16384},
    "test":              {"model": "claude-sonnet-4-6",         "max_tokens": 16384},
    "security-reviewer": {"model": "claude-opus-4-7",           "max_tokens": 8192},
}
```

The runner allows orchestrator-emitted `model_hint` to upgrade (haiku→sonnet→opus) but never downgrade.

### `common/workspace.py`

```python
import json
import os
import boto3

BUCKET = os.environ["WORKSPACE_BUCKET"]
_s3 = boto3.client("s3")

def _key(execution_id: str, name: str) -> str:
    return f"{execution_id}/{name}"

def write_json(execution_id: str, name: str, data) -> None:
    _s3.put_object(
        Bucket=BUCKET,
        Key=_key(execution_id, name),
        Body=json.dumps(data, indent=2).encode("utf-8"),
        ContentType="application/json",
    )

def read_json(execution_id: str, name: str):
    obj = _s3.get_object(Bucket=BUCKET, Key=_key(execution_id, name))
    return json.loads(obj["Body"].read())

def write_file(execution_id: str, rel_path: str, content: str) -> None:
    _s3.put_object(
        Bucket=BUCKET,
        Key=_key(execution_id, f"code/{rel_path}"),
        Body=content.encode("utf-8"),
    )

def list_workspace_jsons(execution_id: str) -> dict:
    """Return {filename: parsed_json} for all *.json in the workspace root."""
    resp = _s3.list_objects_v2(Bucket=BUCKET, Prefix=f"{execution_id}/")
    out = {}
    for obj in resp.get("Contents", []):
        key = obj["Key"]
        name = key[len(f"{execution_id}/"):]
        if "/" in name or not name.endswith(".json"):
            continue
        out[name] = read_json(execution_id, name)
    return out

def list_code_files(execution_id: str) -> list[str]:
    """Returns list of repo-relative paths the agents have written."""
    resp = _s3.list_objects_v2(Bucket=BUCKET, Prefix=f"{execution_id}/code/")
    return [obj["Key"][len(f"{execution_id}/code/"):] for obj in resp.get("Contents", [])]

def read_code_file(execution_id: str, rel_path: str) -> str:
    obj = _s3.get_object(Bucket=BUCKET, Key=_key(execution_id, f"code/{rel_path}"))
    return obj["Body"].read().decode("utf-8")
```

### `common/locks.py`

Implements optimistic locking by feature_id. TTL is 1 hour to auto-release stuck locks.

```python
import os, time, boto3
from botocore.exceptions import ClientError

TABLE = os.environ["LOCKS_TABLE"]
_ddb = boto3.client("dynamodb")
LOCK_TTL_SECONDS = 3600

def acquire(feature_id: str, execution_id: str) -> bool:
    try:
        _ddb.put_item(
            TableName=TABLE,
            Item={
                "feature_id":  {"S": feature_id},
                "execution_id":{"S": execution_id},
                "acquired_at": {"N": str(int(time.time()))},
                "expires_at":  {"N": str(int(time.time()) + LOCK_TTL_SECONDS)},
            },
            ConditionExpression="attribute_not_exists(feature_id) OR expires_at < :now",
            ExpressionAttributeValues={":now": {"N": str(int(time.time()))}},
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise

def release(feature_id: str, execution_id: str) -> None:
    """Release only if we own the lock. Silent no-op otherwise."""
    try:
        _ddb.delete_item(
            TableName=TABLE,
            Key={"feature_id": {"S": feature_id}},
            ConditionExpression="execution_id = :eid",
            ExpressionAttributeValues={":eid": {"S": execution_id}},
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
```

### `common/runs.py`

```python
import os, time, boto3

TABLE = os.environ["RUNS_TABLE"]
_ddb = boto3.client("dynamodb")

def record_step(execution_id: str, feature_id: str, step: str, outcome: str,
                duration_s: float, error: str = "", metadata: dict = None) -> None:
    item = {
        "execution_id": {"S": execution_id},
        "step":         {"S": step},
        "feature_id":   {"S": feature_id},
        "outcome":      {"S": outcome},
        "duration_s":   {"N": str(round(duration_s, 2))},
        "ts":           {"N": str(int(time.time()))},
    }
    if error:
        item["error"] = {"S": error[:4000]}
    if metadata:
        item["metadata"] = {"S": str(metadata)[:4000]}
    _ddb.put_item(TableName=TABLE, Item=item)

def get_steps(execution_id: str) -> list[dict]:
    resp = _ddb.query(
        TableName=TABLE,
        KeyConditionExpression="execution_id = :e",
        ExpressionAttributeValues={":e": {"S": execution_id}},
    )
    return resp["Items"]
```

### `common/secrets.py`

Cache secrets in module scope so each warm Lambda invocation hits Secrets Manager only once.

```python
import os, json, boto3, functools

_sm = boto3.client("secretsmanager")

@functools.lru_cache(maxsize=32)
def get_secret(name: str) -> str:
    return _sm.get_secret_value(SecretId=name)["SecretString"]
```

### `common/agent_runner.py`

```python
import json
import os
import re
import time
import anthropic
from common.secrets import get_secret

AGENT_CONFIG = {  # see above
    "orchestrator":      {"model": "claude-haiku-4-5-20251001", "max_tokens": 4096},
    "spec-analyst":      {"model": "claude-haiku-4-5-20251001", "max_tokens": 4096},
    "architect":         {"model": "claude-sonnet-4-6",         "max_tokens": 8192},
    "database":          {"model": "claude-sonnet-4-6",         "max_tokens": 16384},
    "backend":           {"model": "claude-sonnet-4-6",         "max_tokens": 32768},
    "frontend":          {"model": "claude-sonnet-4-6",         "max_tokens": 32768},
    "infrastructure":    {"model": "claude-sonnet-4-6",         "max_tokens": 16384},
    "test":              {"model": "claude-sonnet-4-6",         "max_tokens": 16384},
    "security-reviewer": {"model": "claude-opus-4-7",           "max_tokens": 8192},
}

_PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "agent_prompts")
_RETRY_DELAYS = [5, 15, 30]

def load_system_prompt(agent_name: str) -> str:
    with open(os.path.join(_PROMPTS_DIR, f"{agent_name}.md")) as f:
        return f.read()

def call_agent(agent_name: str, user_message: str, model_override: str | None = None) -> str:
    cfg = AGENT_CONFIG[agent_name]
    model = model_override or cfg["model"]
    max_tokens = cfg["max_tokens"]
    client = anthropic.Anthropic(api_key=get_secret("nova/factory/anthropic-api-key"))
    system_prompt = load_system_prompt(agent_name)

    last_exc: Exception | None = None
    for attempt, delay in enumerate((*_RETRY_DELAYS, None), start=1):
        try:
            msg = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            return msg.content[0].text
        except (anthropic.APIConnectionError, anthropic.APITimeoutError, anthropic.RateLimitError) as e:
            last_exc = e
            if delay is None: break
            print(f"{agent_name}: transient error attempt {attempt}, retry in {delay}s: {e}")
            time.sleep(delay)
        except anthropic.APIStatusError as e:
            if e.status_code >= 500 and delay is not None:
                last_exc = e
                print(f"{agent_name}: server {e.status_code} attempt {attempt}, retry in {delay}s")
                time.sleep(delay)
            else:
                raise
    raise RuntimeError(f"{agent_name} failed after {len(_RETRY_DELAYS)} retries: {last_exc}")

def extract_json(text: str):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*\n([\s\S]*?)\n```", text)
    if m:
        text = m.group(1).strip()
    return json.loads(text)
```

### `handlers/run_agent.py`

Generic agent handler — invoked once per agent. Receives `{agent_name, execution_id, feature_id, repair_context?}` from Step Functions, returns the agent's structured output.

```python
import json, time, traceback
from common.workspace import (
    write_json, read_json, write_file, list_workspace_jsons,
)
from common.runs import record_step
from common.agent_runner import call_agent, extract_json, AGENT_CONFIG

WORKSPACE_AGENTS = {
    "spec-analyst": "requirements.json",
    "architect": "architecture.json",
    "security-reviewer": "security-review.json",
}
CODE_AGENTS = {"database", "backend", "frontend", "infrastructure", "test"}

def _build_context(execution_id: str, agent_name: str, plan: dict, repair_context: dict | None) -> str:
    parts = []
    if repair_context:
        parts.append(f"# REPAIR MODE — please fix only these issues\n```json\n{json.dumps(repair_context, indent=2)}\n```\n")
    notes = (plan or {}).get("notes", {}).get(agent_name, "")
    if notes:
        parts.append(f"# Orchestrator Notes for {agent_name}\n{notes}\n\n")
    parts.append("# Project Context\n")
    parts.append(read_json(execution_id, "project_context.json")["claude_md"])
    parts.append("\n")
    for name, data in sorted(list_workspace_jsons(execution_id).items()):
        if name == "project_context.json":
            continue
        parts.append(f"\n# {name[:-5]}\n```json\n{json.dumps(data, indent=2)}\n```\n")
    return "".join(parts)

def handler(event, _ctx):
    agent_name     = event["agent_name"]
    execution_id   = event["execution_id"]
    feature_id     = event["feature_id"]
    repair_context = event.get("repair_context")

    plan = read_json(execution_id, "plan.json") if agent_name != "orchestrator" else None
    user_message = _build_context(execution_id, agent_name, plan, repair_context)

    start = time.time()
    try:
        response = call_agent(agent_name, user_message)
        if agent_name in WORKSPACE_AGENTS:
            data = extract_json(response)
            write_json(execution_id, WORKSPACE_AGENTS[agent_name], data)
        elif agent_name in CODE_AGENTS:
            data = extract_json(response)
            if not isinstance(data, dict) or not data:
                raise ValueError(f"{agent_name} returned empty or non-dict file map")
            self_check = data.pop("_self_check", None)
            for rel_path, content in data.items():
                if not isinstance(content, str):
                    raise ValueError(f"{agent_name} non-string content for {rel_path}")
                write_file(execution_id, rel_path, content)
            if self_check:
                write_json(execution_id, f"_self_check_{agent_name}.json", self_check)
        record_step(execution_id, feature_id, agent_name, "success", time.time() - start)
        return {"status": "ok", "agent": agent_name}
    except Exception as e:
        record_step(execution_id, feature_id, agent_name, "failed",
                    time.time() - start, error=f"{e}\n{traceback.format_exc()}")
        raise
```

### `handlers/run_orchestrator.py`

Slightly different — produces `plan.json` and emits `parallel_groups` for the state machine to consume.

```python
import json, time, traceback
from common.workspace import write_json, read_json
from common.runs import record_step
from common.agent_runner import call_agent, extract_json

def handler(event, _ctx):
    execution_id = event["execution_id"]
    feature_id   = event["feature_id"]

    spec = read_json(execution_id, "spec.json")
    project_context = read_json(execution_id, "project_context.json")["claude_md"]
    user_message = (
        f"# Project Context\n{project_context}\n\n"
        f"# Feature Spec\n```json\n{json.dumps(spec, indent=2)}\n```"
    )

    start = time.time()
    try:
        response = call_agent("orchestrator", user_message)
        plan = extract_json(response)
        # Sanity: parallel_groups must include all agents in plan["agents"]
        flat = [a for grp in plan.get("parallel_groups", []) for a in grp]
        missing = set(plan.get("agents", [])) - set(flat) - {"orchestrator", "spec-analyst", "architect", "security-reviewer"}
        if missing:
            # Repair: tack remaining agents on as a final sequential group
            plan.setdefault("parallel_groups", []).append(sorted(missing))
        write_json(execution_id, "plan.json", plan)
        record_step(execution_id, feature_id, "orchestrator", "success", time.time() - start)
        return {"status": "ok", "plan": plan}
    except Exception as e:
        record_step(execution_id, feature_id, "orchestrator", "failed",
                    time.time() - start, error=f"{e}\n{traceback.format_exc()}")
        raise
```

### `handlers/load_spec.py`

```python
import os, json, time
from common.workspace import write_json
from common.secrets import get_secret
import urllib.request

NOTION_VERSION = "2022-06-28"

def _notion_request(path: str, method: str = "GET", body: dict | None = None) -> dict:
    api_key = get_secret("nova/factory/notion-api-key")
    req = urllib.request.Request(
        f"https://api.notion.com/v1{path}",
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
        data=json.dumps(body).encode("utf-8") if body else None,
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())

def _rich(props, key):
    return "".join(t["plain_text"] for t in props.get(key, {}).get("rich_text", []))

def _title(props):
    return "".join(t["plain_text"] for t in props.get("Title", {}).get("title", []))

def _multi(props, key):
    return [t["name"] for t in props.get(key, {}).get("multi_select", [])]

def _status(props):
    s = props.get("Status", {})
    return (s.get("status") or {}).get("name") or (s.get("select") or {}).get("name") or "Unknown"

def handler(event, _ctx):
    feature_id   = event["feature_id"]
    execution_id = event["execution_id"]

    page = _notion_request(f"/pages/{feature_id}")
    props = page["properties"]

    deps = []
    for dep in props.get("Depends On", {}).get("relation", []):
        dp = _notion_request(f"/pages/{dep['id']}")["properties"]
        deps.append({
            "id": dep["id"],
            "title": _title(dp),
            "status": _status(dp),
            "description": _rich(dp, "Description") or _rich(dp, "Tech Notes"),
        })

    spec = {
        "feature_id": feature_id,
        "title": _title(props),
        "description": _rich(props, "Description") or _rich(props, "Tech Notes"),
        "tech_notes": _rich(props, "Tech Notes"),
        "acceptance_criteria": _rich(props, "Acceptance Criteria"),
        "out_of_scope": _rich(props, "Out of Scope"),
        "affected_roles": _multi(props, "Affected Roles"),
        "feature_flag": _rich(props, "Feature Flag"),
        "dependencies": deps,
    }

    write_json(execution_id, "spec.json", spec)
    return {"feature_id": feature_id, "title": spec["title"]}
```

### `handlers/acquire_lock.py`, `handlers/release_lock.py`

```python
# acquire_lock.py
from common.locks import acquire

def handler(event, _ctx):
    feature_id   = event["feature_id"]
    execution_id = event["execution_id"]
    if not acquire(feature_id, execution_id):
        raise Exception(f"FeatureLocked: {feature_id} is already being processed by another execution")
    return {"locked": True}
```

```python
# release_lock.py
from common.locks import release

def handler(event, _ctx):
    release(event["feature_id"], event["execution_id"])
    return {"released": True}
```

### `handlers/commit_and_push.py`

This Lambda needs `git`. Lambda's standard runtime doesn't include git, so use a container-image Lambda for this one with the AWS Lambda Python base image plus `git` installed.

Alternative (simpler): use the GitHub REST API to create the branch + commits via the [Git Data API](https://docs.github.com/en/rest/git) — no git binary needed. **Use this approach.**

```python
import base64, json, os, time
from common.workspace import list_code_files, read_code_file, read_json
from common.secrets import get_secret
from common.runs import record_step
import urllib.request, urllib.error

GH_OWNER = os.environ["GITHUB_OWNER"]
GH_REPO  = os.environ["GITHUB_REPO"]
GH_API   = f"https://api.github.com/repos/{GH_OWNER}/{GH_REPO}"

def _gh(method: str, path: str, body=None) -> dict:
    token = get_secret("nova/factory/github-token")
    req = urllib.request.Request(
        f"{GH_API}{path}",
        method=method,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
        data=json.dumps(body).encode("utf-8") if body else None,
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())

def handler(event, _ctx):
    execution_id = event["execution_id"]
    feature_id   = event["feature_id"]
    spec = read_json(execution_id, "spec.json")

    title = spec["title"]
    slug  = "".join(c if c.isalnum() else "-" for c in title.lower()).strip("-")[:50]
    branch = f"feature/{slug}-{int(time.time())}"

    # 1. Get main HEAD sha
    main_ref = _gh("GET", "/git/ref/heads/main")
    main_sha = main_ref["object"]["sha"]
    main_commit = _gh("GET", f"/git/commits/{main_sha}")
    base_tree   = main_commit["tree"]["sha"]

    # 2. Build a tree of all files changed by agents
    tree_items = []
    for rel in list_code_files(execution_id):
        content = read_code_file(execution_id, rel)
        blob = _gh("POST", "/git/blobs", {
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "encoding": "base64",
        })
        tree_items.append({
            "path": rel,
            "mode": "100644",
            "type": "blob",
            "sha": blob["sha"],
        })

    if not tree_items:
        raise RuntimeError("No files produced by agents — refusing to commit empty change")

    new_tree = _gh("POST", "/git/trees", {
        "base_tree": base_tree,
        "tree": tree_items,
    })

    # 3. Commit
    new_commit = _gh("POST", "/git/commits", {
        "message": f"feat: {title} (factory build)\n\nFeature ID: {feature_id}\nExecution: {execution_id}",
        "tree": new_tree["sha"],
        "parents": [main_sha],
    })

    # 4. Create branch ref
    _gh("POST", "/git/refs", {
        "ref": f"refs/heads/{branch}",
        "sha": new_commit["sha"],
    })

    # 5. Open PR
    pr = _gh("POST", "/pulls", {
        "title": title,
        "body": f"Built by Nova Software Factory (Step Functions backend).\n\nFeature ID: `{feature_id}`\nExecution: `{execution_id}`",
        "head": branch,
        "base": "main",
    })

    record_step(execution_id, feature_id, "commit_and_push", "success", 0,
                metadata={"branch": branch, "pr_number": pr["number"]})

    return {
        "branch": branch,
        "pr_number": pr["number"],
        "pr_url": pr["html_url"],
        "commit_sha": new_commit["sha"],
    }
```

### `handlers/trigger_quality_gates.py`

Uses Step Functions task token for callback. Posts a `workflow_dispatch` event to GitHub with `task_token` in the inputs.

```python
import os, json
from common.secrets import get_secret
import urllib.request

GH_OWNER = os.environ["GITHUB_OWNER"]
GH_REPO  = os.environ["GITHUB_REPO"]

def handler(event, _ctx):
    branch     = event["branch"]
    pr_number  = event["pr_number"]
    task_token = event["task_token"]  # injected by Step Functions waitForTaskToken

    token = get_secret("nova/factory/github-token")
    body = {
        "ref": "main",
        "inputs": {
            "branch":     branch,
            "pr_number":  str(pr_number),
            "task_token": task_token,
        },
    }
    req = urllib.request.Request(
        f"https://api.github.com/repos/{GH_OWNER}/{GH_REPO}/actions/workflows/quality-gates.yml/dispatches",
        method="POST",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
        data=json.dumps(body).encode("utf-8"),
    )
    urllib.request.urlopen(req, timeout=15)
    return {"dispatched": True}
```

### `handlers/handle_quality_gate_callback.py`

API Gateway endpoint receives the result from GitHub Actions; this Lambda forwards to Step Functions via task token.

```python
import json, boto3

_sfn = boto3.client("stepfunctions")

def handler(event, _ctx):
    body = json.loads(event["body"])
    task_token = body["task_token"]
    if body.get("passed"):
        _sfn.send_task_success(taskToken=task_token, output=json.dumps({"passed": True, "logs_url": body.get("logs_url", "")}))
    else:
        _sfn.send_task_failure(
            taskToken=task_token,
            error="QualityGateFailure",
            cause=body.get("error", "unknown")[:256],
        )
    return {"statusCode": 200, "body": "ok"}
```

### `handlers/update_notion.py`

```python
import json, urllib.request
from common.secrets import get_secret

NOTION_VERSION = "2022-06-28"

def handler(event, _ctx):
    feature_id = event["feature_id"]
    status     = event["status"]      # "In Progress" | "Done" | "Failed"
    extras     = event.get("extras", {})

    props = {"Status": {"select": {"name": status}}}
    if "pr_url" in extras:
        props["PR Link"] = {"url": extras["pr_url"]}
    if "error" in extras:
        props["Error Log"] = {"rich_text": [{"text": {"content": extras["error"][:2000]}}]}

    api_key = get_secret("nova/factory/notion-api-key")
    req = urllib.request.Request(
        f"https://api.notion.com/v1/pages/{feature_id}",
        method="PATCH",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
        data=json.dumps({"properties": props}).encode("utf-8"),
    )
    urllib.request.urlopen(req, timeout=15)
    return {"updated": True}
```

### Build & deploy

`scripts/factory_lambdas/build.sh` — packages each handler as a zip including `common/` and `agent_prompts/`.

```bash
#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
DIST="$HERE/dist"
PROMPTS_SRC="$REPO_ROOT/.claude/agents"
PROMPTS_DST="$HERE/agent_prompts"

rm -rf "$DIST" "$PROMPTS_DST"
mkdir -p "$DIST" "$PROMPTS_DST"
cp "$PROMPTS_SRC"/*.md "$PROMPTS_DST/"

for handler in "$HERE"/handlers/*.py; do
  name=$(basename "$handler" .py)
  STAGE=$(mktemp -d)
  cp -r "$HERE/common" "$STAGE/"
  cp -r "$PROMPTS_DST" "$STAGE/agent_prompts"
  cp "$handler" "$STAGE/$name.py"
  (cd "$STAGE" && zip -r "$DIST/$name.zip" . -q)
  rm -rf "$STAGE"
  echo "built dist/$name.zip"
done
```

In Terraform (`infra/factory/lambdas.tf`):

```hcl
locals {
  handlers = {
    acquire_lock                  = { timeout = 30,  memory = 256 }
    release_lock                  = { timeout = 30,  memory = 256 }
    load_spec                     = { timeout = 60,  memory = 512 }
    run_orchestrator              = { timeout = 300, memory = 2048 }
    run_agent                     = { timeout = 600, memory = 2048 }
    run_security_reviewer         = { timeout = 600, memory = 2048 }
    commit_and_push               = { timeout = 300, memory = 1024 }
    update_notion                 = { timeout = 30,  memory = 256 }
    trigger_quality_gates         = { timeout = 30,  memory = 256 }
    handle_quality_gate_callback  = { timeout = 30,  memory = 256 }
  }
}

resource "null_resource" "build_handlers" {
  triggers = {
    src_hash = sha256(join("", [for f in fileset("${path.module}/../../scripts/factory_lambdas", "**") : filemd5("${path.module}/../../scripts/factory_lambdas/${f}")]))
  }
  provisioner "local-exec" {
    command = "bash ${path.module}/../../scripts/factory_lambdas/build.sh"
  }
}

resource "aws_lambda_function" "handlers" {
  for_each = local.handlers

  function_name = "${local.name_prefix}-${replace(each.key, "_", "-")}"
  filename      = "${path.module}/../../scripts/factory_lambdas/dist/${each.key}.zip"
  source_code_hash = filebase64sha256("${path.module}/../../scripts/factory_lambdas/dist/${each.key}.zip")
  role          = aws_iam_role.lambda_exec.arn
  handler       = "${each.key}.handler"
  runtime       = "python3.12"
  timeout       = each.value.timeout
  memory_size   = each.value.memory
  layers        = [aws_lambda_layer_version.shared.arn]

  tracing_config { mode = "Active" }

  environment {
    variables = {
      WORKSPACE_BUCKET = aws_s3_bucket.workspaces.bucket
      LOCKS_TABLE      = aws_dynamodb_table.locks.name
      RUNS_TABLE       = aws_dynamodb_table.runs.name
      GITHUB_OWNER     = var.github_owner
      GITHUB_REPO      = var.github_repo
    }
  }

  depends_on = [null_resource.build_handlers]
  tags       = local.common_tags
}

resource "aws_cloudwatch_log_group" "handlers" {
  for_each          = local.handlers
  name              = "/aws/lambda/${local.name_prefix}-${replace(each.key, "_", "-")}"
  retention_in_days = 30
  tags              = local.common_tags
}
```

### Verification

Per-Lambda smoke test (after `terraform apply`):

```bash
# Test load_spec end-to-end
EXEC_ID="test-$(date +%s)"
FEATURE_ID="<a-known-feature-uuid-from-notion>"
aws lambda invoke \
  --function-name nova-factory-load-spec \
  --payload "{\"feature_id\":\"$FEATURE_ID\",\"execution_id\":\"$EXEC_ID\"}" \
  --cli-binary-format raw-in-base64-out \
  /tmp/out.json
cat /tmp/out.json
aws s3 cp s3://nova-factory-workspaces-577638385116/$EXEC_ID/spec.json -
```

**Done when:** every handler zip builds, every Lambda is created, `load_spec` smoke test returns a real spec.

---

## Phase 5 — Step Functions state machine

**Goal:** Wire the Lambdas into a Standard state machine with locking, parallel branches, repair loops, and quality-gate callback.

### `infra/factory/state-machine.tf`

```hcl
resource "aws_cloudwatch_log_group" "sfn" {
  name              = "/aws/states/${local.name_prefix}-pipeline"
  retention_in_days = 30
  tags              = local.common_tags
}

resource "aws_sfn_state_machine" "pipeline" {
  name     = "${local.name_prefix}-pipeline"
  role_arn = aws_iam_role.sfn_exec.arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/state-machine.json.tpl", {
    region                       = var.aws_region
    account_id                   = data.aws_caller_identity.current.account_id
    fn_acquire_lock              = aws_lambda_function.handlers["acquire_lock"].arn
    fn_release_lock              = aws_lambda_function.handlers["release_lock"].arn
    fn_load_spec                 = aws_lambda_function.handlers["load_spec"].arn
    fn_run_orchestrator          = aws_lambda_function.handlers["run_orchestrator"].arn
    fn_run_agent                 = aws_lambda_function.handlers["run_agent"].arn
    fn_run_security_reviewer     = aws_lambda_function.handlers["run_security_reviewer"].arn
    fn_commit_and_push           = aws_lambda_function.handlers["commit_and_push"].arn
    fn_update_notion             = aws_lambda_function.handlers["update_notion"].arn
    fn_trigger_quality_gates     = aws_lambda_function.handlers["trigger_quality_gates"].arn
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }

  tracing_configuration { enabled = true }
  tags                  = local.common_tags
}
```

### `infra/factory/state-machine.json.tpl`

A complete state-machine definition. Key features:

- `AcquireLock` first; if it fails, jump to `MarkFailed` with reason "FeatureLocked".
- `LoadProjectContext` step (separate Lambda or inline pass) loads `CLAUDE.md` from GitHub raw API and writes to `project_context.json` in S3.
- `RunOrchestrator` produces `plan.json` including `parallel_groups`.
- A `Map` state iterates over `parallel_groups`; each group is processed via inner `Parallel`. (Step Functions supports nested Map/Parallel; if the depth becomes painful, flatten by emitting a fixed sequence with `Choice` skips.)
- `RunSecurityReviewer` is a separate state with a `Choice` that forks to `Repair` (one cycle) or `MarkFailed`.
- `CommitAndPush` → `TriggerQualityGates` (waitForTaskToken) → `Choice(passed?)` → `MergePR` or `Repair`.
- Catch on every Task: route to `MarkFailed` → `ReleaseLock` → `Fail`.

```json
{
  "Comment": "Nova factory pipeline",
  "StartAt": "AcquireLock",
  "States": {
    "AcquireLock": {
      "Type": "Task",
      "Resource": "${fn_acquire_lock}",
      "Parameters": {
        "feature_id.$": "$.feature_id",
        "execution_id.$": "$$.Execution.Name"
      },
      "ResultPath": "$.lock",
      "Catch": [{
        "ErrorEquals": ["States.ALL"],
        "ResultPath": "$.error",
        "Next": "MarkFailed"
      }],
      "Next": "MarkInProgress"
    },

    "MarkInProgress": {
      "Type": "Task",
      "Resource": "${fn_update_notion}",
      "Parameters": {
        "feature_id.$": "$.feature_id",
        "status": "In Progress"
      },
      "ResultPath": null,
      "Next": "LoadSpec"
    },

    "LoadSpec": {
      "Type": "Task",
      "Resource": "${fn_load_spec}",
      "Parameters": {
        "feature_id.$": "$.feature_id",
        "execution_id.$": "$$.Execution.Name"
      },
      "ResultPath": "$.spec_meta",
      "Retry": [{
        "ErrorEquals": ["States.ALL"],
        "IntervalSeconds": 5,
        "MaxAttempts": 3,
        "BackoffRate": 2.0
      }],
      "Catch": [{ "ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease" }],
      "Next": "RunOrchestrator"
    },

    "RunOrchestrator": {
      "Type": "Task",
      "Resource": "${fn_run_orchestrator}",
      "Parameters": {
        "feature_id.$": "$.feature_id",
        "execution_id.$": "$$.Execution.Name"
      },
      "ResultPath": "$.orchestrator",
      "Retry": [{ "ErrorEquals": ["States.ALL"], "IntervalSeconds": 10, "MaxAttempts": 2, "BackoffRate": 2.0 }],
      "Catch": [{ "ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease" }],
      "Next": "RunSpecAnalyst"
    },

    "RunSpecAnalyst": {
      "Type": "Task",
      "Resource": "${fn_run_agent}",
      "Parameters": {
        "agent_name": "spec-analyst",
        "feature_id.$": "$.feature_id",
        "execution_id.$": "$$.Execution.Name"
      },
      "ResultPath": null,
      "Retry": [{ "ErrorEquals": ["States.ALL"], "IntervalSeconds": 10, "MaxAttempts": 2, "BackoffRate": 2.0 }],
      "Catch": [{ "ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease" }],
      "Next": "RunAgentGroupsMap"
    },

    "RunAgentGroupsMap": {
      "Type": "Map",
      "ItemsPath": "$.orchestrator.plan.parallel_groups",
      "MaxConcurrency": 1,
      "ItemSelector": {
        "group.$": "$$.Map.Item.Value",
        "execution_id.$": "$$.Execution.Name",
        "feature_id.$": "$.feature_id"
      },
      "ItemProcessor": {
        "ProcessorConfig": { "Mode": "INLINE" },
        "StartAt": "FanOut",
        "States": {
          "FanOut": {
            "Type": "Map",
            "ItemsPath": "$.group",
            "MaxConcurrency": 5,
            "ItemSelector": {
              "agent_name.$": "$$.Map.Item.Value",
              "execution_id.$": "$.execution_id",
              "feature_id.$": "$.feature_id"
            },
            "ItemProcessor": {
              "ProcessorConfig": { "Mode": "INLINE" },
              "StartAt": "RunOneAgent",
              "States": {
                "RunOneAgent": {
                  "Type": "Task",
                  "Resource": "${fn_run_agent}",
                  "Retry": [{ "ErrorEquals": ["States.ALL"], "IntervalSeconds": 15, "MaxAttempts": 2, "BackoffRate": 2.0 }],
                  "End": true
                }
              }
            },
            "End": true
          }
        }
      },
      "ResultPath": null,
      "Catch": [{ "ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease" }],
      "Next": "RunSecurityReview"
    },

    "RunSecurityReview": {
      "Type": "Task",
      "Resource": "${fn_run_agent}",
      "Parameters": {
        "agent_name": "security-reviewer",
        "feature_id.$": "$.feature_id",
        "execution_id.$": "$$.Execution.Name"
      },
      "ResultPath": "$.security",
      "Retry": [{ "ErrorEquals": ["States.ALL"], "IntervalSeconds": 10, "MaxAttempts": 2, "BackoffRate": 2.0 }],
      "Catch": [{ "ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease" }],
      "Next": "EvaluateSecurityResult"
    },

    "EvaluateSecurityResult": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "${fn_run_agent}",
        "Payload": {
          "agent_name": "security-evaluator",
          "execution_id.$": "$$.Execution.Name",
          "feature_id.$": "$.feature_id"
        }
      },
      "ResultPath": "$.security_eval",
      "Next": "SecurityChoice"
    },

    "SecurityChoice": {
      "Type": "Choice",
      "Choices": [
        {
          "Variable": "$.security_eval.Payload.passed",
          "BooleanEquals": true,
          "Next": "CommitAndPush"
        },
        {
          "And": [
            { "Variable": "$.security_eval.Payload.passed", "BooleanEquals": false },
            { "Variable": "$.security_eval.Payload.repairable", "BooleanEquals": true },
            { "Variable": "$.repair_attempted", "IsPresent": false }
          ],
          "Next": "RunSecurityRepair"
        }
      ],
      "Default": "MarkFailedAndRelease"
    },

    "RunSecurityRepair": {
      "Type": "Pass",
      "Result": true,
      "ResultPath": "$.repair_attempted",
      "Next": "RunRepairAgents"
    },

    "RunRepairAgents": {
      "Type": "Task",
      "Resource": "${fn_run_agent}",
      "Parameters": {
        "agent_name": "backend",
        "feature_id.$": "$.feature_id",
        "execution_id.$": "$$.Execution.Name",
        "repair_context.$": "$.security_eval.Payload.issues"
      },
      "ResultPath": null,
      "Catch": [{ "ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease" }],
      "Next": "RunSecurityReview"
    },

    "CommitAndPush": {
      "Type": "Task",
      "Resource": "${fn_commit_and_push}",
      "Parameters": {
        "feature_id.$": "$.feature_id",
        "execution_id.$": "$$.Execution.Name"
      },
      "ResultPath": "$.commit",
      "Retry": [{ "ErrorEquals": ["States.ALL"], "IntervalSeconds": 10, "MaxAttempts": 2, "BackoffRate": 2.0 }],
      "Catch": [{ "ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease" }],
      "Next": "WaitForQualityGates"
    },

    "WaitForQualityGates": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke.waitForTaskToken",
      "Parameters": {
        "FunctionName": "${fn_trigger_quality_gates}",
        "Payload": {
          "branch.$": "$.commit.branch",
          "pr_number.$": "$.commit.pr_number",
          "task_token.$": "$$.Task.Token"
        }
      },
      "TimeoutSeconds": 1200,
      "ResultPath": "$.quality",
      "Catch": [
        { "ErrorEquals": ["QualityGateFailure"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease" },
        { "ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease" }
      ],
      "Next": "MarkDone"
    },

    "MarkDone": {
      "Type": "Task",
      "Resource": "${fn_update_notion}",
      "Parameters": {
        "feature_id.$": "$.feature_id",
        "status": "Done",
        "extras": { "pr_url.$": "$.commit.pr_url" }
      },
      "ResultPath": null,
      "Next": "ReleaseLock"
    },

    "ReleaseLock": {
      "Type": "Task",
      "Resource": "${fn_release_lock}",
      "Parameters": {
        "feature_id.$": "$.feature_id",
        "execution_id.$": "$$.Execution.Name"
      },
      "ResultPath": null,
      "End": true
    },

    "MarkFailedAndRelease": {
      "Type": "Task",
      "Resource": "${fn_update_notion}",
      "Parameters": {
        "feature_id.$": "$.feature_id",
        "status": "Failed",
        "extras": { "error.$": "States.JsonToString($.error)" }
      },
      "ResultPath": null,
      "Next": "ReleaseLockAfterFailure"
    },

    "ReleaseLockAfterFailure": {
      "Type": "Task",
      "Resource": "${fn_release_lock}",
      "Parameters": {
        "feature_id.$": "$.feature_id",
        "execution_id.$": "$$.Execution.Name"
      },
      "ResultPath": null,
      "Next": "FailState"
    },

    "MarkFailed": {
      "Type": "Task",
      "Resource": "${fn_update_notion}",
      "Parameters": {
        "feature_id.$": "$.feature_id",
        "status": "Failed",
        "extras": { "error": "Locked by another execution" }
      },
      "ResultPath": null,
      "Next": "FailState"
    },

    "FailState": { "Type": "Fail", "Error": "FactoryFailed" }
  }
}
```

> **Note for Sonnet:** the `EvaluateSecurityResult` state above invokes `run_agent` with `agent_name=security-evaluator` as a placeholder. Replace it with a small inline Lambda OR a Step Functions Pass state that reads `$.security` and computes `passed`/`repairable` from the JSON the security reviewer wrote to S3. The cleanest implementation is a tiny `evaluate_security` Lambda (~10 lines) that reads `security-review.json` from the workspace and returns `{passed: bool, repairable: bool, issues: [...]}`. Add it to the handler list.

### Verification

```bash
aws stepfunctions describe-state-machine \
  --state-machine-arn $(aws stepfunctions list-state-machines --query 'stateMachines[?name==`nova-factory-pipeline`].stateMachineArn' --output text) \
  --query 'status'
# Should print "ACTIVE"
```

**Done when:** state machine is ACTIVE and the JSON definition validates. Don't smoke-test the full pipeline yet — that's Phase 8.

---

## Phase 6 — Webhook routing update

**Goal:** Update the existing `nova-webhook-relay` Lambda so that, when `FACTORY_BACKEND=step-functions`, it starts a Step Functions execution instead of (or in addition to) firing the GitHub repository_dispatch.

### Edits

`infra/webhook-relay/lambda/index.js`:

- Read `process.env.FACTORY_BACKEND` (default: `github-actions`).
- If `step-functions`, call `aws-sdk` `StepFunctions.startExecution` with the state machine ARN from env.
- Use a deterministic `name` based on `feature_id + timestamp` so duplicate webhooks don't create duplicate executions.

`infra/webhook-relay/main.tf`:

- Add a new env var `FACTORY_BACKEND` (default `github-actions` for safe rollout) and `STATE_MACHINE_ARN`.
- Add a remote-state data source pointing at `infra/factory/` so the webhook can read the state machine ARN.

```hcl
data "terraform_remote_state" "factory" {
  backend = "local"
  config = { path = "../factory/terraform.tfstate" }
}

# Update the lambda environment block:
environment {
  variables = {
    GITHUB_OWNER      = var.github_owner
    GITHUB_REPO       = var.github_repo
    GITHUB_TOKEN      = data.aws_secretsmanager_secret_version.github_token.secret_string
    NOTION_API_KEY    = data.aws_secretsmanager_secret_version.notion_api_key.secret_string
    FACTORY_BACKEND   = "github-actions"   # flip to "step-functions" in Phase 8
    STATE_MACHINE_ARN = data.terraform_remote_state.factory.outputs.state_machine_arn
  }
}
```

Also expose `state_machine_arn` from `infra/factory/outputs.tf`:

```hcl
output "state_machine_arn" { value = aws_sfn_state_machine.pipeline.arn }
```

Add IAM permission to the webhook role:

```hcl
resource "aws_iam_role_policy" "lambda_states" {
  name = "nova-webhook-relay-states"
  role = aws_iam_role.lambda_exec.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "states:StartExecution"
      Resource = data.terraform_remote_state.factory.outputs.state_machine_arn
    }]
  })
}
```

### `index.js` snippet

```js
const { SFNClient, StartExecutionCommand } = require("@aws-sdk/client-sfn");
const sfn = new SFNClient({});

async function startStateMachine(featureId) {
  const safeName = `${featureId.replace(/-/g, "")}-${Date.now()}`;
  await sfn.send(new StartExecutionCommand({
    stateMachineArn: process.env.STATE_MACHINE_ARN,
    name: safeName,
    input: JSON.stringify({ feature_id: featureId }),
  }));
}

// inside handler, replace the dispatch call with:
if (process.env.FACTORY_BACKEND === "step-functions") {
  await startStateMachine(featureId);
} else {
  await dispatchGithubEvent(featureId); // existing path
}
```

Bump `package.json` to add `@aws-sdk/client-sfn`. Re-run `npm install` in `lambda/` directory before terraform apply (the existing zip pattern already handles dependencies via the source_dir archive).

### Verification

After `terraform apply` of webhook-relay:

```bash
# Confirm the new env vars are set
aws lambda get-function-configuration --function-name nova-webhook-relay \
  --query 'Environment.Variables.[FACTORY_BACKEND,STATE_MACHINE_ARN]' --output table
```

**Done when:** webhook Lambda has both env vars and IAM permission, FACTORY_BACKEND still defaulting to `github-actions` so behaviour is unchanged.

---

## Phase 7 — GitHub Actions: thin quality-gates workflow

**Goal:** Replace `factory.yml` with a much smaller `quality-gates.yml` triggered by Step Functions (via webhook callback). Keep `factory.yml` in place for fallback during cutover.

### `.github/workflows/quality-gates.yml`

```yaml
name: Nova Quality Gates

on:
  workflow_dispatch:
    inputs:
      branch:
        required: true
        type: string
      pr_number:
        required: true
        type: string
      task_token:
        required: true
        type: string

concurrency:
  group: quality-gates-${{ github.event.inputs.branch }}
  cancel-in-progress: false

jobs:
  gates:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ inputs.branch }}
          fetch-depth: 0
          token: ${{ secrets.GH_TOKEN }}

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install
        run: |
          pip install -r requirements.txt
          pip install ruff mypy pytest pytest-asyncio httpx starlette

      - name: Auto-format & lint fix
        id: fmt
        if: hashFiles('app/**/*.py') != ''
        run: |
          ruff format app/
          ruff check app/ --fix --unsafe-fixes || true
          if ! git diff --quiet; then
            git config user.name  "Nova Factory"
            git config user.email "factory@nova.build"
            git add app/
            git commit -m "style: auto-fix ruff"
            git push origin HEAD
          fi

      - name: Lint
        if: hashFiles('app/**/*.py') != ''
        run: ruff check app/

      - name: Types
        if: hashFiles('app/**/*.py') != ''
        run: mypy app/ --ignore-missing-imports || true

      - name: Tests
        run: |
          if find tests/ -name "test_*.py" | grep -q .; then
            pytest tests/ -x -q --tb=short
          else
            echo "no tests"
          fi

      - name: Docker build
        if: hashFiles('Dockerfile') != ''
        run: docker build -t nova-api:gate .

      - name: Terraform validate
        if: hashFiles('infra/main.tf') != ''
        run: |
          curl -fsSL https://releases.hashicorp.com/terraform/1.7.5/terraform_1.7.5_linux_amd64.zip -o tf.zip
          unzip -q tf.zip && sudo mv terraform /usr/local/bin/
          cd infra && terraform init -backend=false && terraform validate

      - name: Merge PR (success)
        if: success()
        env:
          GH_TOKEN: ${{ secrets.GH_TOKEN }}
        run: |
          gh pr review ${{ inputs.pr_number }} --approve
          gh pr merge ${{ inputs.pr_number }} --squash --admin --delete-branch

      - name: Notify Step Functions (success)
        if: success()
        env:
          CALLBACK_URL: ${{ secrets.FACTORY_CALLBACK_URL }}
        run: |
          curl -fsSL -X POST "$CALLBACK_URL" \
            -H "Content-Type: application/json" \
            -d "{\"task_token\":\"${{ inputs.task_token }}\",\"passed\":true,\"logs_url\":\"${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}\"}"

      - name: Notify Step Functions (failure)
        if: failure()
        env:
          CALLBACK_URL: ${{ secrets.FACTORY_CALLBACK_URL }}
        run: |
          curl -fsSL -X POST "$CALLBACK_URL" \
            -H "Content-Type: application/json" \
            -d "{\"task_token\":\"${{ inputs.task_token }}\",\"passed\":false,\"error\":\"Quality gate failed — see ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}\"}"
```

### Add a callback API Gateway resource to `infra/factory/`

```hcl
resource "aws_api_gateway_rest_api" "factory_callback" {
  name = "${local.name_prefix}-callback"
  endpoint_configuration { types = ["REGIONAL"] }
  tags = local.common_tags
}

resource "aws_api_gateway_resource" "callback" {
  rest_api_id = aws_api_gateway_rest_api.factory_callback.id
  parent_id   = aws_api_gateway_rest_api.factory_callback.root_resource_id
  path_part   = "callback"
}

resource "aws_api_gateway_method" "callback_post" {
  rest_api_id   = aws_api_gateway_rest_api.factory_callback.id
  resource_id   = aws_api_gateway_resource.callback.id
  http_method   = "POST"
  authorization = "NONE"
  api_key_required = true
}

resource "aws_api_gateway_integration" "callback_lambda" {
  rest_api_id             = aws_api_gateway_rest_api.factory_callback.id
  resource_id             = aws_api_gateway_resource.callback.id
  http_method             = aws_api_gateway_method.callback_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.handlers["handle_quality_gate_callback"].invoke_arn
}

resource "aws_lambda_permission" "callback_apigw" {
  statement_id  = "AllowAPIGatewayInvokeCallback"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.handlers["handle_quality_gate_callback"].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.factory_callback.execution_arn}/*/*"
}

resource "aws_api_gateway_deployment" "callback" {
  depends_on  = [aws_api_gateway_integration.callback_lambda]
  rest_api_id = aws_api_gateway_rest_api.factory_callback.id
  lifecycle { create_before_destroy = true }
}

resource "aws_api_gateway_stage" "callback" {
  deployment_id = aws_api_gateway_deployment.callback.id
  rest_api_id   = aws_api_gateway_rest_api.factory_callback.id
  stage_name    = "prod"
}

resource "aws_api_gateway_api_key" "callback" {
  name = "${local.name_prefix}-callback-key"
}

resource "aws_api_gateway_usage_plan" "callback" {
  name = "${local.name_prefix}-callback-plan"
  api_stages {
    api_id = aws_api_gateway_rest_api.factory_callback.id
    stage  = aws_api_gateway_stage.callback.stage_name
  }
  throttle_settings { rate_limit = 10  burst_limit = 20 }
}

resource "aws_api_gateway_usage_plan_key" "callback" {
  key_id        = aws_api_gateway_api_key.callback.id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.callback.id
}

output "callback_url" {
  value = "${aws_api_gateway_stage.callback.invoke_url}/callback"
}
output "callback_api_key" {
  value     = aws_api_gateway_api_key.callback.value
  sensitive = true
}
```

After `terraform apply`, register the callback URL + key as GitHub Actions secrets:

```bash
CALLBACK_URL=$(terraform -chdir=/c/Claude/Nova/nova/infra/factory output -raw callback_url)
CALLBACK_KEY=$(terraform -chdir=/c/Claude/Nova/nova/infra/factory output -raw callback_api_key)
gh secret set FACTORY_CALLBACK_URL --body "$CALLBACK_URL?key=$CALLBACK_KEY" --repo nabbic/nova
```

(Alternative: send the API key in the `x-api-key` header inside the curl in `quality-gates.yml`. Slightly cleaner.)

**Done when:** workflow file committed, callback Gateway live, `FACTORY_CALLBACK_URL` set as a repo secret.

---

## Phase 8 — End-to-end smoke test & cutover

**Goal:** Prove the new pipeline works on a known-good feature, then flip the webhook to the new backend.

### Smoke test setup

1. Create a tiny test feature in Notion (status = `Idea`):
   ```
   Title:        Factory smoke — version v2 endpoint
   Description:  Add GET /api/version2 returning {"version": "2.0.0"}
   Acceptance:   curl /api/version2 returns 200 with that JSON body
   ```

2. Manually start an execution (without going through the webhook):
   ```bash
   FEATURE_ID="<uuid-of-smoke-feature>"
   aws stepfunctions start-execution \
     --state-machine-arn $(terraform -chdir=/c/Claude/Nova/nova/infra/factory output -raw state_machine_arn) \
     --name "smoke-$(date +%s)" \
     --input "{\"feature_id\":\"$FEATURE_ID\"}"
   ```

3. Watch the execution:
   ```bash
   aws stepfunctions describe-execution --execution-arn <arn-from-prev>
   # Or open in the console
   ```

4. Verify outcomes:
   - PR was opened
   - quality-gates.yml ran and merged the PR
   - Notion card status = Done with PR link
   - DynamoDB `nova-factory-runs` has a row per agent
   - S3 workspace bucket has `<execution-id>/...` artifacts
   - DynamoDB `nova-factory-locks` is empty (lock released)

### Failure-injection tests

Run each in isolation:

| Scenario | How to trigger | Expected behaviour |
|---|---|---|
| Concurrent triggers | Start two executions for the same feature 1s apart | Second goes to MarkFailed with "Locked" |
| Agent JSON malformed | Temporarily set backend agent's max_tokens to 100 → JSON truncated | Lambda retries 2× then fails state machine; Notion = Failed |
| Quality gate fails | Add `assert False` to a test, manual feature build | Step Functions catches QualityGateFailure → MarkFailed |
| Security reviewer fails | Spec asking for `eval(user_input)` | Repair loop runs once; if still failing, MarkFailed |
| Lambda timeout on agent | Set run_agent timeout to 30s | Step Functions retry kicks in |

If all five behave as expected, cutover:

5. **Flip the webhook** by editing `infra/webhook-relay/main.tf`, change `FACTORY_BACKEND = "github-actions"` → `"step-functions"`. `terraform apply`.

6. Mark the existing `factory.yml` as deprecated by adding a comment header:
   ```yaml
   # DEPRECATED 2026-05-03 — superseded by quality-gates.yml + Step Functions pipeline.
   # Kept for emergency fallback. Remove after 30 days of stable operation.
   ```

7. Trigger one more Notion-driven feature to confirm the end-to-end production path works.

**Done when:** smoke test green, all 5 failure-injection scenarios behave correctly, webhook flipped, real Notion-triggered feature completes.

---

## Phase 9 — Observability & guardrails

**Goal:** Make the new system actually robust by surfacing failures and runaway cost.

### CloudWatch dashboard

`infra/factory/dashboard.tf`:

```hcl
resource "aws_cloudwatch_dashboard" "factory" {
  dashboard_name = "${local.name_prefix}"
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6,
        properties = {
          metrics = [
            ["AWS/States", "ExecutionsStarted",   "StateMachineArn", aws_sfn_state_machine.pipeline.arn],
            [".",          "ExecutionsSucceeded", ".",                "."],
            [".",          "ExecutionsFailed",    ".",                "."],
          ]
          view = "timeSeries", stacked = false
          region = var.aws_region
          title  = "Pipeline executions"
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 12, height = 6,
        properties = {
          metrics = [
            for k in keys(local.handlers) :
              ["AWS/Lambda", "Duration", "FunctionName", "${local.name_prefix}-${replace(k, "_", "-")}"]
          ]
          view = "timeSeries", stacked = false
          region = var.aws_region
          title  = "Lambda durations"
        }
      },
    ]
  })
}
```

### Alarms

```hcl
resource "aws_cloudwatch_metric_alarm" "execution_failures" {
  alarm_name          = "${local.name_prefix}-execution-failures"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ExecutionsFailed"
  namespace           = "AWS/States"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  dimensions = { StateMachineArn = aws_sfn_state_machine.pipeline.arn }
  alarm_actions = [aws_sns_topic.factory_alerts.arn]
}

resource "aws_sns_topic" "factory_alerts" {
  name = "${local.name_prefix}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.factory_alerts.arn
  protocol  = "email"
  endpoint  = "nabbic@gmail.com"
}
```

(Note: SNS email subscription requires a one-time confirmation click in the email after first apply.)

### AWS Budget

Set a $20/month budget on the factory tag with email at 80% and 100%.

```hcl
resource "aws_budgets_budget" "factory" {
  name              = "${local.name_prefix}-monthly"
  budget_type       = "COST"
  limit_amount      = "20"
  limit_unit        = "USD"
  time_unit         = "MONTHLY"
  cost_filter { name = "TagKeyValue" values = ["user:Component$factory"] }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = ["nabbic@gmail.com"]
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = ["nabbic@gmail.com"]
  }
}
```

### Notion runs DB integration

The `runs.py` helper writes to DynamoDB. Add a trigger Lambda subscribed to the runs table stream that mirrors completed runs into the existing Notion `Runs` DB so the user sees the same UI as today. Optional — defer if time-pressed.

**Done when:** dashboard live, alarm + budget configured, SNS email confirmed.

---

## Phase 10 — Documentation & memory updates

**Goal:** Make sure future agents (and the user) understand the new architecture.

1. Update `CLAUDE.md` Factory section:

   ```markdown
   ## Factory
   This repository is built and maintained by the Nova Software Factory.

   **Pipeline (as of 2026-05-03):** Notion → Webhook Lambda → Step Functions
   (`nova-factory-pipeline`) → per-agent Lambdas → S3 workspace → GitHub feature
   branch → `quality-gates.yml` → auto-merge → `deploy.yml`.

   The legacy `factory.yml` is deprecated and will be removed once the new
   pipeline has run cleanly for 30 days.
   ```

2. Update user memory:
   - Update `project_nova_status.md`: add a "2026-05-03: Migrated agent execution from GitHub Actions to AWS Lambda + Step Functions" line.
   - Update `project_nova_operations.md`: replace the "GitHub Actions Workflows" section with a "Pipeline" section pointing at the state machine; add new commands for inspecting an execution.
   - Add a new `reference_factory_runtime.md` with: state machine ARN, S3 bucket name, DynamoDB table names, callback URL location.

3. Write a short `docs/runbooks/factory-incident.md`:
   - Stuck execution (DynamoDB lock won't release) → manual delete command
   - Failed quality-gate callback (Step Functions hangs at WaitForQualityGates) → how to send_task_success manually
   - Anthropic outage → how to pause the webhook (env var flip)

**Done when:** CLAUDE.md, user memory, and runbook all updated.

---

## Phase 11 — Cleanup (after 30 days of stable operation)

Not part of this execution — leave a TODO note in `factory.yml` header. Once stable:
- Delete `factory.yml`
- Delete `scripts/factory_run.py` and `scripts/agents.py` (now lives in Lambdas)
- Migrate `infra/factory/` Terraform state to S3 backend matching app infra

---

## Cost forecast (post-overhaul, 100 builds/month)

| Component | Cost |
|---|---|
| Lambda invocations (~50/build × 100 = 5k) | $0 (free tier) |
| Lambda compute (~3 GB-min/agent × 9 × 100 = 2,700 GB-min) | $0 (well under 400k GB-sec free tier) |
| Step Functions (Standard, ~50 transitions × 100 = 5k) | $0.13 |
| DynamoDB (PAY_PER_REQUEST, ~10 ops/build × 100) | $0 |
| S3 (~5 MB/exec × 100 = 500 MB, lifecycle to 0 after 14d) | <$0.05 |
| API Gateway callback (100 req/month) | $0 (free tier) |
| GitHub Actions (~5 min/build × 100 = 500 min) | $0 (within 2,000 free) |
| CloudWatch Logs (modest retention) | <$0.50 |
| **Infra subtotal** | **~$0.70/month** |
| Anthropic API tokens | unchanged from today (same agents, similar prompts; haiku/opus tiering may net to slight savings) |

Compare to baseline ~$10–20/month if running 100 builds/month entirely on GitHub Actions after free tier exhaustion.

---

## Robustness improvements summary

| Concern | Fix |
|---|---|
| Two webhooks for same feature collide | DynamoDB conditional-put lock per feature_id, TTL'd at 1h |
| Agent failure forces full rebuild | Workspace lives in S3 — re-running individual Lambdas is allowed |
| Sequential agent execution wastes wall-clock | Orchestrator emits `parallel_groups`; Step Functions Map fans out |
| Security review is a hard fail | One repair cycle: review → fix → re-review (max 1 iteration) |
| Quality gate failure forces full rebuild | Same repair loop applies to gate failures |
| Backend rewrites Dockerfile every run | Backend prompt updated to only emit when changed |
| All agents pay Sonnet pricing | Per-agent model tiering (haiku for JSON, sonnet for code, opus for security) |
| No observability into per-agent latency | DynamoDB runs table + CloudWatch dashboard + X-Ray |
| No alerting on failures | SNS + email on any failed execution |
| Runaway cost | $20/month AWS Budgets alert + Lambda concurrency caps |
| Stuck/orphaned executions | TTL on locks + Step Functions execution timeout (1h overall via state machine timeout) |
| Lost workspace on CI runner restart | Workspace in S3, durable across restarts |

Add an overall execution timeout to the state machine definition: `"TimeoutSeconds": 3600` at the top level.

---

## Acceptance criteria for the whole overhaul

The plan is complete when ALL of the following are true:

1. `terraform apply` in `infra/factory/` succeeds cleanly on a fresh checkout.
2. A Notion feature transition to "Ready to Build" results in: Step Functions execution starts → all agents run → PR opened → quality gates pass → PR merged → Notion = Done. End-to-end without human intervention.
3. Concurrent webhook triggers for the same feature do NOT cause data corruption (one wins, one fails fast with "Locked").
4. A deliberately-broken test causes the pipeline to attempt a repair, then fail cleanly with Notion = Failed and a useful error log.
5. CloudWatch shows per-agent metrics, X-Ray shows traces.
6. SNS email fires on a real failure (verified by injecting one).
7. AWS Budget alarm wired and confirmed.
8. `CLAUDE.md` and user memory updated.
9. The legacy `factory.yml` is marked deprecated but still present.
10. A clean `git status` (no untracked or modified files outside the planned edits).

---

## Sonnet operating instructions

- Work phase by phase. After each phase, update `.factory-overhaul-state.json`.
- For Terraform: validate, plan, apply (auto-approved per user memory).
- For each Lambda: write code, build zip, deploy, then immediately smoke-test.
- If a phase verification fails, debug before moving on. Don't accumulate failures.
- Commit per phase to the overhaul branch with messages like `factory-overhaul: phase N — <summary>`.
- At Phase 8 cutover, do NOT proceed if any of the 5 failure-injection scenarios misbehaves.
- If you hit something genuinely ambiguous (not covered by this plan), prefer the safer option, document the deviation in `.factory-overhaul-state.json` notes, and continue. Do NOT pause for the user.
- When done, open a PR titled "Factory overhaul: Lambda + Step Functions cost & robustness" describing what changed and a link to the dashboard.

---

# Addendum A — Validate-as-you-build & deploy hardening

**Why this addendum exists:** The user is hitting two concrete failure modes today that the base plan above only loosely addresses:

1. **Deploy failure** — `Terraform Init (staging)` exits with `The value cannot be empty or all whitespace` on `-backend-config=...`. Root cause: the deploy job runs without first checking that `TF_STATE_BUCKET` (and other required secrets/resources) actually exist. There is no pre-flight gate.
2. **Factory build failure** — backend agent returned an empty/whitespace response three times: `backend: invalid JSON on attempt 1/3 — Expecting value: line 1 column 1 (char 0)`. Root cause: the agent runner blindly retries the same prompt; it doesn't inspect `stop_reason`, doesn't attempt JSON repair on prose preambles, has no continuation when `max_tokens` is hit, and there is no per-agent validation step that would catch broken output before it propagates.

**Goal of this addendum:** Make agents validate their own output the moment they produce it, and make the deploy step prove the environment is actually ready before it tries to act. Self-heal where possible, fail loudly and informatively where not.

These changes interleave with phases above — execute them in the order written below.

---

## A.1 — Harden the agent runner (slots into Phase 4)

Replace the simple retry loop in `common/agent_runner.py` with a multi-strategy recovery loop. Add this before any of the per-handler Lambdas are built so all of them inherit it.

### A.1.1 Inspect `stop_reason` before parsing

```python
def call_agent(agent_name, user_message, model_override=None, *, prior_assistant=None):
    cfg = AGENT_CONFIG[agent_name]
    model = model_override or cfg["model"]
    max_tokens = cfg["max_tokens"]
    client = anthropic.Anthropic(api_key=get_secret("nova/factory/anthropic-api-key"))
    system_prompt = load_system_prompt(agent_name)

    messages = [{"role": "user", "content": user_message}]
    if prior_assistant:  # continuation
        messages.append({"role": "assistant", "content": prior_assistant})

    last_exc = None
    for attempt, delay in enumerate((*_RETRY_DELAYS, None), start=1):
        try:
            msg = client.messages.create(
                model=model, max_tokens=max_tokens,
                system=system_prompt, messages=messages,
            )
        except (anthropic.APIConnectionError, anthropic.APITimeoutError, anthropic.RateLimitError) as e:
            last_exc = e
            if delay is None: break
            time.sleep(delay)
            continue
        except anthropic.APIStatusError as e:
            if e.status_code >= 500 and delay is not None:
                last_exc = e; time.sleep(delay); continue
            raise

        text = msg.content[0].text if msg.content else ""
        return {
            "text": text,
            "stop_reason": msg.stop_reason,        # "end_turn" | "max_tokens" | "stop_sequence" | "refusal"
            "usage": {"input": msg.usage.input_tokens, "output": msg.usage.output_tokens},
        }
    raise RuntimeError(f"{agent_name} exhausted retries: {last_exc}")
```

Callers now receive a dict instead of a raw string. They MUST check `stop_reason` and `usage["output"]`.

### A.1.2 Empty-response guard

Before any JSON parse, check that the response is non-empty:

```python
def parse_agent_json(agent_name: str, result: dict) -> dict:
    text = result["text"].strip()
    if not text:
        raise EmptyResponseError(
            f"{agent_name}: empty response "
            f"(stop_reason={result['stop_reason']}, output_tokens={result['usage']['output']})"
        )
    if result["stop_reason"] == "refusal":
        raise RefusalError(f"{agent_name}: model refused to generate. Full response: {text[:500]}")
    return _extract_json_with_repair(agent_name, text)
```

`EmptyResponseError` and `RefusalError` are custom exceptions so Step Functions can route them differently (refusals are NOT retryable; empty responses ARE).

### A.1.3 JSON repair with Haiku

When the response is non-empty but `json.loads` fails, don't immediately retry the full agent. Instead, ask Haiku to extract the JSON from the messy response. This is ~$0.001 vs running the whole backend agent again.

```python
_REPAIR_SYSTEM = (
    "You are a JSON extractor. The user message contains a response from another model "
    "that was supposed to be pure JSON but may include prose, markdown fences, or commentary. "
    "Extract and output ONLY the intended JSON object. No prose, no fences, no preamble. "
    "If the JSON is truncated or invalid, attempt to repair it minimally. "
    "If no JSON is recoverable at all, output exactly: {}"
)

def _extract_json_with_repair(agent_name: str, text: str) -> dict:
    # Fast path: maybe it's already valid
    try:
        return _try_parse(text)
    except json.JSONDecodeError:
        pass

    # Repair path
    print(f"{agent_name}: JSON parse failed, attempting Haiku repair")
    client = anthropic.Anthropic(api_key=get_secret("nova/factory/anthropic-api-key"))
    repair = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=8192,
        system=_REPAIR_SYSTEM,
        messages=[{"role": "user", "content": text[:50000]}],  # cap input
    )
    repaired = repair.content[0].text.strip()
    return _try_parse(repaired)  # raises if still bad

def _try_parse(text: str):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*\n([\s\S]*?)\n```", text)
    if m:
        text = m.group(1).strip()
    return json.loads(text)
```

### A.1.4 Continuation when `stop_reason == "max_tokens"`

If the model stopped because it hit the token limit, send the partial response back as the assistant turn and ask it to continue. Do this once. If still incomplete, fail loudly so the human can either raise `max_tokens` for this agent or split the feature.

```python
def call_agent_with_continuation(agent_name: str, user_message: str, max_continuations: int = 2) -> dict:
    accumulated = ""
    msg = call_agent(agent_name, user_message)
    accumulated = msg["text"]
    continuations = 0
    while msg["stop_reason"] == "max_tokens" and continuations < max_continuations:
        continuations += 1
        print(f"{agent_name}: hit max_tokens, requesting continuation {continuations}/{max_continuations}")
        msg = call_agent(agent_name, user_message, prior_assistant=accumulated)
        accumulated += msg["text"]
    if msg["stop_reason"] == "max_tokens":
        raise RuntimeError(
            f"{agent_name}: still incomplete after {max_continuations} continuations. "
            f"Either raise max_tokens for this agent or split the feature."
        )
    return {"text": accumulated, "stop_reason": "end_turn", "usage": msg["usage"]}
```

Use `call_agent_with_continuation` from inside `handlers/run_agent.py`.

### A.1.5 Per-attempt logging

Every Lambda call logs structured JSON to CloudWatch:

```python
print(json.dumps({
    "event": "agent_call",
    "agent": agent_name,
    "model": model,
    "stop_reason": result["stop_reason"],
    "input_tokens": result["usage"]["input"],
    "output_tokens": result["usage"]["output"],
    "execution_id": os.environ.get("AWS_LAMBDA_LOG_STREAM_NAME", ""),
}))
```

This lets CloudWatch Logs Insights surface "all max_tokens hits in the last hour" as one query — much faster than reading raw logs.

---

## A.2 — Inline validation Lambdas (slots into Phase 4)

Add a new family of Lambdas that validate each code agent's output the moment it's written. These run between each code agent and the next state in the state machine. No agent's output gets to the next stage without passing its validator.

### A.2.1 Validator Lambdas

Create one Lambda per validator. All share `common/validation.py` helpers that download the workspace from S3 to `/tmp` (Lambda has 512MB ephemeral by default; bump to 2048MB for these via `ephemeral_storage`).

```
scripts/factory_lambdas/handlers/
├── validate_backend.py         # ruff + mypy + import-check
├── validate_frontend.py        # tsc --noEmit + eslint
├── validate_database.py        # alembic check
├── validate_infrastructure.py  # terraform fmt + validate
└── validate_test.py            # pytest --collect-only + sample run
```

### A.2.2 `validate_backend.py`

Lightweight: run ruff and mypy in-process (both are pip-installable Python libraries; bake them into the shared layer). For import-time check, use `importlib`.

```python
import os, sys, json, subprocess, tempfile, shutil, traceback
from pathlib import Path
from common.workspace import list_code_files, read_code_file

def _materialize_to_tmp(execution_id: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="ws-"))
    for rel in list_code_files(execution_id):
        dest = tmp / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(read_code_file(execution_id, rel))
    return tmp

def _run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)
    return p.returncode, (p.stdout + p.stderr)[:8000]

def handler(event, _ctx):
    execution_id = event["execution_id"]
    feature_id   = event["feature_id"]
    ws = _materialize_to_tmp(execution_id)
    issues = []

    if (ws / "app").exists():
        rc, out = _run(["python", "-m", "ruff", "check", "app/"], ws)
        if rc != 0:
            issues.append({"tool": "ruff", "output": out})
        rc, out = _run(["python", "-m", "mypy", "app/", "--ignore-missing-imports", "--no-error-summary"], ws)
        if rc != 0:
            issues.append({"tool": "mypy", "output": out})

        # Import-time check: critical because the user has been bitten by app/main.py
        # raising at import time when env vars are unset
        rc, out = _run(
            ["python", "-c", "import importlib, pkgutil; "
                              "[importlib.import_module(name) for _, name, _ in "
                              "pkgutil.walk_packages(['app'], prefix='app.')]"],
            ws,
        )
        if rc != 0:
            issues.append({
                "tool": "import-check",
                "output": out,
                "hint": "App must be importable without environment variables set. "
                        "Move env-var reads inside functions, not module top level.",
            })

    shutil.rmtree(ws, ignore_errors=True)
    passed = len(issues) == 0
    return {"passed": passed, "issues": issues, "agent_to_repair": "backend" if not passed else None}
```

### A.2.3 `validate_infrastructure.py`

Lambda doesn't ship Terraform binary — bundle it. The shared layer adds a `bin/terraform` (download once at layer-build time). Or use a Lambda container image for this one specifically.

Simplest: container-image Lambda with Terraform installed.

```dockerfile
# scripts/factory_lambdas/containers/validate_infrastructure/Dockerfile
FROM public.ecr.aws/lambda/python:3.12

RUN dnf install -y unzip wget && \
    wget -q https://releases.hashicorp.com/terraform/1.7.5/terraform_1.7.5_linux_amd64.zip && \
    unzip -q terraform_1.7.5_linux_amd64.zip && mv terraform /usr/local/bin/ && \
    rm terraform_1.7.5_linux_amd64.zip

COPY common/ ${LAMBDA_TASK_ROOT}/common/
COPY handlers/validate_infrastructure.py ${LAMBDA_TASK_ROOT}/

CMD ["validate_infrastructure.handler"]
```

```python
# handler
def handler(event, _ctx):
    ws = _materialize_to_tmp(event["execution_id"])
    issues = []
    if (ws / "infra" / "main.tf").exists():
        rc, out = _run(["terraform", "fmt", "-check", "-recursive", "infra/"], ws)
        if rc != 0:
            issues.append({"tool": "terraform-fmt", "output": out,
                           "hint": "Run `terraform fmt -recursive infra/` to fix."})
        rc, out = _run(["terraform", "init", "-backend=false", "-input=false"], ws / "infra")
        if rc != 0:
            issues.append({"tool": "terraform-init", "output": out})
        else:
            rc, out = _run(["terraform", "validate", "-json"], ws / "infra")
            if rc != 0:
                issues.append({"tool": "terraform-validate", "output": out})
    shutil.rmtree(ws, ignore_errors=True)
    passed = not issues
    return {"passed": passed, "issues": issues, "agent_to_repair": "infrastructure" if not passed else None}
```

Add this to Terraform with `package_type = "Image"`:

```hcl
resource "aws_ecr_repository" "validators" {
  name = "${local.name_prefix}-validators"
}

resource "null_resource" "build_validate_infra_image" {
  triggers = {
    src = filemd5("${path.module}/../../scripts/factory_lambdas/handlers/validate_infrastructure.py")
  }
  provisioner "local-exec" {
    command = <<-EOT
      cd ${path.module}/../../scripts/factory_lambdas/containers/validate_infrastructure
      aws ecr get-login-password --region ${var.aws_region} | docker login --username AWS --password-stdin ${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com
      docker build -t ${aws_ecr_repository.validators.repository_url}:validate-infra .
      docker push ${aws_ecr_repository.validators.repository_url}:validate-infra
    EOT
  }
}

resource "aws_lambda_function" "validate_infrastructure" {
  function_name = "${local.name_prefix}-validate-infrastructure"
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.validators.repository_url}:validate-infra"
  role          = aws_iam_role.lambda_exec.arn
  timeout       = 300
  memory_size   = 2048
  ephemeral_storage { size = 2048 }
  depends_on    = [null_resource.build_validate_infra_image]
}
```

### A.2.4 `validate_backend_runtime.py` — docker build + /health probe

This catches runtime failures (broken Dockerfile, missing /health, import errors at startup) that the static checks above can miss.

Use **AWS CodeBuild** for this one (Lambda can't run Docker). CodeBuild has a generous free tier (100 build-min/month for `general1.small`, $0.005/min after) and supports privileged mode for Docker.

`infra/factory/codebuild.tf`:

```hcl
resource "aws_codebuild_project" "validate_runtime" {
  name         = "${local.name_prefix}-validate-runtime"
  service_role = aws_iam_role.codebuild_exec.arn
  artifacts { type = "NO_ARTIFACTS" }
  environment {
    type            = "LINUX_CONTAINER"
    compute_type    = "BUILD_GENERAL1_SMALL"
    image           = "aws/codebuild/standard:7.0"
    privileged_mode = true
  }
  source {
    type      = "NO_SOURCE"
    buildspec = file("${path.module}/codebuild-validate-runtime.yml")
  }
  cache { type = "LOCAL"  modes = ["LOCAL_DOCKER_LAYER_CACHE", "LOCAL_SOURCE_CACHE"] }
  tags = local.common_tags
}
```

`infra/factory/codebuild-validate-runtime.yml`:

```yaml
version: 0.2
env:
  variables: { EXECUTION_ID: "" }
phases:
  install:
    commands:
      - aws s3 cp --recursive "s3://${WORKSPACE_BUCKET}/${EXECUTION_ID}/code/" .
  build:
    commands:
      - test -f Dockerfile || { echo "no-dockerfile"; exit 0; }
      - docker build -t nova-runtime-test .
      - docker run -d --name testapp -p 18080:8000
          -e DATABASE_URL=postgresql://nope -e ENVIRONMENT=test
          nova-runtime-test
      - sleep 5
      - curl -fsSL http://localhost:18080/health || (docker logs testapp; exit 1)
      - docker stop testapp
```

A small Lambda `trigger_runtime_validation.py` invokes the CodeBuild project synchronously (Step Functions `waitForTaskToken` pattern) and returns pass/fail with the build log URL. Failures route to backend repair.

### A.2.5 State machine wiring

After each code agent in the parallel group, append a Validate state. Use a sub-state-machine pattern so each code agent has its own validate-and-repair micro-loop:

```
RunBackend → ValidateBackend
  ↓ pass                    ↓ fail (attempts < 2)
  done                       → RepairBackend → ValidateBackend
                            ↓ fail (attempts >= 2)
                             → MarkFailedAndRelease
```

State machine snippet (replace the simple `RunOneAgent` task in `RunAgentGroupsMap`):

```json
"RunOneAgent": {
  "Type": "Task",
  "Resource": "${fn_run_agent}",
  "ResultPath": "$.agent_result",
  "Retry": [{ "ErrorEquals": ["States.ALL"], "IntervalSeconds": 15, "MaxAttempts": 2, "BackoffRate": 2.0 }],
  "Next": "ChooseValidator"
},
"ChooseValidator": {
  "Type": "Choice",
  "Choices": [
    { "Variable": "$.agent_name", "StringEquals": "backend",        "Next": "ValidateBackend" },
    { "Variable": "$.agent_name", "StringEquals": "frontend",       "Next": "ValidateFrontend" },
    { "Variable": "$.agent_name", "StringEquals": "database",       "Next": "ValidateDatabase" },
    { "Variable": "$.agent_name", "StringEquals": "infrastructure", "Next": "ValidateInfrastructure" },
    { "Variable": "$.agent_name", "StringEquals": "test",           "Next": "ValidateTest" }
  ],
  "Default": "DoneAgent"
},
"ValidateBackend": {
  "Type": "Task",
  "Resource": "${fn_validate_backend}",
  "Parameters": {
    "execution_id.$": "$.execution_id",
    "feature_id.$":   "$.feature_id"
  },
  "ResultPath": "$.validation",
  "Next": "ValidationChoice"
},
"ValidationChoice": {
  "Type": "Choice",
  "Choices": [
    { "Variable": "$.validation.passed", "BooleanEquals": true, "Next": "DoneAgent" },
    {
      "And": [
        { "Variable": "$.validation.passed", "BooleanEquals": false },
        { "Or": [
          { "Variable": "$.repair_count", "IsPresent": false },
          { "Variable": "$.repair_count", "NumericLessThan": 2 }
        ]}
      ],
      "Next": "BumpRepair"
    }
  ],
  "Default": "ValidationFailed"
},
"BumpRepair": {
  "Type": "Pass",
  "Parameters": {
    "agent_name.$":      "$.agent_name",
    "execution_id.$":    "$.execution_id",
    "feature_id.$":      "$.feature_id",
    "repair_context.$":  "$.validation.issues",
    "repair_count.$":    "States.MathAdd($.repair_count, 1)"
  },
  "Next": "RunOneAgent"
},
"ValidationFailed": {
  "Type": "Fail",
  "Error": "ValidationExhausted",
  "Cause": "Code agent could not produce passing output after 2 repair attempts"
},
"DoneAgent": { "Type": "Succeed" }
```

(`States.MathAdd` requires `"QueryLanguage": "JSONata"` mode OR set `repair_count: 0` in the FanOut item selector and use `"$.repair_count"` from the start. JSONata mode is cleaner; available in Step Functions since late 2024.)

The same pattern wraps `RunBackend` → `ValidateBackendRuntime` (CodeBuild) so docker build + /health is also gated.

---

## A.3 — Per-agent prompt updates for repair mode (slots into Phase 2)

Augment `backend.md`, `frontend.md`, `database.md`, `infrastructure.md`, `test.md` with an explicit "Repair mode" section:

```markdown
## Repair mode

If your input includes a `# REPAIR MODE` block, you are receiving validation failures
from the previous attempt. Your job is to:

1. Read the `validation_errors` array carefully — each entry has a `tool` and `output`.
2. Identify which file(s) caused each failure.
3. Output a file map containing ONLY the files you are changing to fix the issues.
4. Do NOT regenerate files that aren't related to the failures.
5. Do NOT modify tests in `tests/` to make them pass — fix the underlying code.
6. If a failure looks like a tool/environment issue (e.g. terraform version mismatch),
   include a JSON sibling `_repair_notes` explaining why you can't fix it in code.

Common failure patterns and the right repair:

| Failure                                              | Repair                                              |
|------------------------------------------------------|-----------------------------------------------------|
| `mypy: <file>: error: Module has no attribute "X"`  | Add the missing import or remove the bad reference  |
| `ruff: <file>: F401 unused import`                  | Remove the import                                   |
| `import-check: ImportError`                          | Move the failing import inside a function           |
| `import-check: KeyError on os.environ['X']`          | Make the env-var read lazy (inside a function)      |
| `docker build: COPY failed: file not found`          | Add the missing file or fix the COPY path           |
| `curl /health: Connection refused`                   | Check the CMD in Dockerfile; ensure /health exists  |
```

Add equivalent rows to each agent's repair table.

---

## A.4 — Deploy pre-flight (slots into Phase 7)

The current `deploy.yml` failure (`The value cannot be empty or all whitespace`) happens because no one checks that `TF_STATE_BUCKET` is set. Fix it in two layers: a one-time bootstrap that creates everything deploy needs, and a per-deploy pre-flight that fails fast with clear errors.

### A.4.1 Bootstrap module

`infra/bootstrap/` — runs once, creates the foundational resources that `deploy.yml` and `factory.yml` assume exist.

```hcl
# infra/bootstrap/main.tf
terraform {
  required_version = ">= 1.7"
  required_providers { aws = { source = "hashicorp/aws", version = "~> 5.0" } }
}

provider "aws" { region = var.aws_region }

variable "aws_region" { type = string  default = "us-east-1" }

data "aws_caller_identity" "current" {}

# Terraform state bucket (used by infra/main.tf for staging + production)
resource "aws_s3_bucket" "tf_state" {
  bucket        = "nova-terraform-state-${data.aws_caller_identity.current.account_id}"
  force_destroy = false
}

resource "aws_s3_bucket_versioning" "tf_state" {
  bucket = aws_s3_bucket.tf_state.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tf_state" {
  bucket = aws_s3_bucket.tf_state.id
  rule { apply_server_side_encryption_by_default { sse_algorithm = "AES256" } }
}

resource "aws_s3_bucket_public_access_block" "tf_state" {
  bucket                  = aws_s3_bucket.tf_state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_dynamodb_table" "tf_locks" {
  name         = "nova-terraform-locks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"
  attribute { name = "LockID"  type = "S" }
}

# ECR repos referenced by deploy.yml
resource "aws_ecr_repository" "api"    { name = "nova-api"    image_tag_mutability = "MUTABLE" }
resource "aws_ecr_repository" "worker" { name = "nova-worker" image_tag_mutability = "MUTABLE" }

# Output everything deploy.yml will need
output "tf_state_bucket"      { value = aws_s3_bucket.tf_state.bucket }
output "tf_lock_table"        { value = aws_dynamodb_table.tf_locks.name }
output "ecr_api_repo_url"     { value = aws_ecr_repository.api.repository_url }
output "ecr_worker_repo_url"  { value = aws_ecr_repository.worker.repository_url }
```

After applying bootstrap, set the GitHub Actions secrets it produces:

```bash
cd /c/Claude/Nova/nova/infra/bootstrap
terraform init && terraform apply -auto-approve
gh secret set TF_STATE_BUCKET --body "$(terraform output -raw tf_state_bucket)"      --repo nabbic/nova
gh secret set TF_LOCK_TABLE   --body "$(terraform output -raw tf_lock_table)"         --repo nabbic/nova
gh secret set ECR_API_REPO    --body "$(terraform output -raw ecr_api_repo_url)"      --repo nabbic/nova
gh secret set ECR_WORKER_REPO --body "$(terraform output -raw ecr_worker_repo_url)"   --repo nabbic/nova
```

### A.4.2 Pre-flight job in `deploy.yml`

Add a new first job that fails fast if anything is missing. All other jobs depend on it.

```yaml
jobs:
  preflight:
    name: Pre-flight checks
    runs-on: ubuntu-latest
    timeout-minutes: 3
    steps:
      - name: Required GitHub secrets
        env:
          TF_STATE_BUCKET:        ${{ secrets.TF_STATE_BUCKET }}
          TF_LOCK_TABLE:          ${{ secrets.TF_LOCK_TABLE }}
          ECR_API_REPO:           ${{ secrets.ECR_API_REPO }}
          ECR_WORKER_REPO:        ${{ secrets.ECR_WORKER_REPO }}
          AWS_ACCESS_KEY_ID:      ${{ secrets.AWS_ACCESS_KEY_ID }}
          AWS_SECRET_ACCESS_KEY:  ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          CLOUDFLARE_API_TOKEN:   ${{ secrets.CLOUDFLARE_API_TOKEN }}
        run: |
          missing=()
          for v in TF_STATE_BUCKET TF_LOCK_TABLE ECR_API_REPO ECR_WORKER_REPO \
                   AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY CLOUDFLARE_API_TOKEN; do
            if [ -z "${!v}" ]; then missing+=("$v"); fi
          done
          if [ ${#missing[@]} -gt 0 ]; then
            echo "::error::Missing required GitHub secrets: ${missing[*]}"
            echo "::error::Run \`infra/bootstrap\` and the post-bootstrap \`gh secret set\` commands."
            exit 1
          fi

      - uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id:     ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-east-1

      - name: Required AWS resources
        env:
          TF_STATE_BUCKET: ${{ secrets.TF_STATE_BUCKET }}
          TF_LOCK_TABLE:   ${{ secrets.TF_LOCK_TABLE }}
          ECR_API_REPO:    ${{ secrets.ECR_API_REPO }}
          ECR_WORKER_REPO: ${{ secrets.ECR_WORKER_REPO }}
        run: |
          fail() { echo "::error::$1"; exit 1; }
          aws s3api head-bucket --bucket "$TF_STATE_BUCKET" 2>/dev/null \
            || fail "Terraform state bucket $TF_STATE_BUCKET does not exist or is not accessible"
          aws dynamodb describe-table --table-name "$TF_LOCK_TABLE" >/dev/null \
            || fail "DynamoDB lock table $TF_LOCK_TABLE missing"
          # ECR repo names are full URLs in the secret — extract repo name
          for full in "$ECR_API_REPO" "$ECR_WORKER_REPO"; do
            name="${full##*/}"
            aws ecr describe-repositories --repository-names "$name" >/dev/null \
              || fail "ECR repo $name missing"
          done
          echo "All required AWS resources present"

  build-and-push:
    needs: preflight
    # ... existing definition
  deploy-staging:
    needs: [preflight, build-and-push]
    # ... existing definition
  deploy-production:
    needs: [preflight, build-and-push, deploy-staging]
    # ... existing definition
```

Now the deploy fails in 30 seconds with a concrete error pointing at exactly what's missing, instead of running for several minutes and erroring inside `terraform init`.

### A.4.3 Optional: Self-heal missing infra

If `preflight` finds a missing AWS resource that bootstrap should have created, an opt-in second pass can run `infra/bootstrap` automatically. Default this OFF for safety (creates resources without the user noticing). To enable, set repo variable `FACTORY_AUTO_BOOTSTRAP=1`. When true, `preflight` runs `terraform apply` in `infra/bootstrap` and re-checks. If still missing, fail.

---

## A.5 — Hardened `quality-gates.yml` (slots into Phase 7)

The new `quality-gates.yml` should also run a pre-flight against the workspace:

```yaml
- name: Workspace pre-flight
  run: |
    fail() { echo "::error::$1"; exit 1; }
    [ -f requirements.txt ] || fail "missing requirements.txt — backend agent did not produce it"
    [ -f Dockerfile ]       || fail "missing Dockerfile — backend agent did not produce it"
    grep -q '"/health"' app/main.py || grep -q "'/health'" app/main.py \
      || fail "/health endpoint missing from app/main.py"
    python -c "import ast, sys; ast.parse(open('app/main.py').read())" \
      || fail "app/main.py is not syntactically valid Python"
```

These pre-flight checks duplicate some Lambda validations but defense-in-depth is fine — they're cheap and they protect against any path where workspace S3 → branch upload diverges.

---

## A.6 — Notion runs DB: surface validation outcomes

In `runs.py`, record one row per validator invocation:

```python
record_step(execution_id, feature_id, "validate-backend", outcome, dur,
            metadata={"issues_count": len(issues), "tools_failed": [i["tool"] for i in issues]})
```

Update the Notion `Runs` mirror to display:
- Total agent calls
- Total repair attempts (count of `repair_count > 0` events)
- Total validation failures
- Token usage per agent (from `usage` we logged in A.1.5)

This lets the user see at a glance: "this build needed 3 repair cycles for backend — the spec is probably ambiguous." Strong signal for spec quality.

---

## A.7 — Updates to existing phases

| Phase | Update |
|---|---|
| Phase 1 | Add `infra/bootstrap/` apply as a prerequisite step BEFORE Phase 1's factory infra apply. |
| Phase 2 | Add the "Repair mode" section to backend.md, frontend.md, database.md, infrastructure.md, test.md (table from A.3). |
| Phase 3 | Add `ruff`, `mypy`, `pytest` to the shared layer requirements (validators import them). |
| Phase 4 | Add the 5 validator handlers + the runtime-validation CodeBuild project. Update `agent_runner.py` per A.1.1–A.1.5. |
| Phase 5 | Update state-machine template per A.2.5 (per-agent validate-and-repair sub-loops). |
| Phase 7 | Add pre-flight job to `deploy.yml` per A.4.2; add workspace pre-flight to `quality-gates.yml` per A.5. |
| Phase 8 | Add three new failure-injection scenarios: (a) backend agent returns empty response → A.1 recovery kicks in; (b) backend agent produces code with import-time error → A.2.2 catches it, repair runs; (c) `TF_STATE_BUCKET` secret unset → preflight fails in <1 min. |

---

## A.8 — Updated acceptance criteria additions

Append to the existing acceptance criteria:

11. An agent returning an empty response triggers JSON repair (Haiku call) before consuming a full retry; CloudWatch shows the repair attempt.
12. An agent returning code with a deliberate `import broken_module` triggers `validate_backend`, which feeds the failure into a backend repair invocation; the repair fixes it; the next validate passes.
13. A `TF_STATE_BUCKET` GitHub secret cleared to empty causes `deploy.yml` to fail in the `preflight` job in under 60 seconds with a clear error message — never reaches `terraform init`.
14. Running `infra/bootstrap` from a fresh clone produces every resource needed by `deploy.yml`; subsequent `terraform apply` is a no-op.
15. The Notion `Runs` mirror shows token usage and repair counts per agent for any completed execution.

---

## A.9 — Cost impact of validation

| Component | Added cost |
|---|---|
| Validator Lambdas (5 × ~30s × 2 GB) | ~1 GB-min per build × 100 = 100 GB-min/month — free |
| CodeBuild runtime validation (~3 min × 100) | 300 min/month, 100 free, 200 paid × $0.005 = $1.00/month |
| Haiku JSON repair calls (sporadic) | <$0.10/month |
| ECR storage for validator container image | ~$0.10/month |
| **Net added** | **~$1.20/month** |

Net savings from preventing failed deploys (each currently burns ~10 min of Actions before erroring out): roughly equivalent. The real win is **time saved debugging** plus **avoiding broken merges**.

---

## A.10 — Sonnet operating notes for this addendum

- Execute A.1 immediately after writing `common/agent_runner.py` — do not build any handler that imports the runner until A.1 is in place.
- Execute A.4.1 (bootstrap) BEFORE Phase 1 factory infra. Without it, downstream deploy tests will fail.
- For A.2.3 container-image Lambda: if the ECR push step times out (large image), retry with `--no-cache`. If still failing, fall back to layered approach (bundle terraform binary in the shared layer instead of using a container image).
- Test A.1.3 (Haiku JSON repair) standalone before deploying — feed it a known-bad response, confirm it returns valid JSON or `{}`.
- The state-machine JSONata mode (used in A.2.5 for `States.MathAdd`) requires Step Functions API version 2024-11. If your account/region somehow doesn't support it, fall back to a Pass state that hardcodes the repair_count increment via `Parameters` interpolation in JSONPath mode — slightly uglier but functionally identical.

