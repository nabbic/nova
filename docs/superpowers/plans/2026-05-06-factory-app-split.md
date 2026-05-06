# Factory / App Repo Split + App Repo Cleanup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the Nova Software Factory out of `nabbic/nova` into a dedicated `nabbic/nova-factory` repo, and reset `nabbic/nova` to a clean "empty app" state ready for the factory to build features into.

**Architecture:** Two-repo model. `nabbic/nova-factory` owns Terraform (factory + webhook-relay), Lambda source, agent prompts, factory tooling, and Notion config. `nabbic/nova` owns app code, app infra (Cognito, RDS, ECS), app CI/CD, and the product `CLAUDE.md`. The factory clones the configured app repo into `/tmp/ws` and operates only there; agent prompts and PRD scratch state live entirely inside the factory's domain (Lambda image / S3 / DynamoDB) and never touch the app repo's git tree. AWS resources do not change — Terraform state stays at the same S3 keys, ECR repos keep the same names; only the working directory and Lambda image source move.

**Tech Stack:** Terraform 1.x (S3 + DDB backend), AWS Step Functions, AWS Lambda (Python 3.12 + container), AWS ECR, AWS Secrets Manager, GitHub Actions, GitHub CLI (`gh`), Notion REST API, Python 3.12, Anthropic Claude Code CLI.

---

## File Structure

### `nabbic/nova` after the split (target state)

```
nabbic/nova/
├── .github/workflows/
│   ├── quality-gates.yml          # APP CI: ruff, mypy, pytest, docker build, auto-merge on green
│   └── deploy.yml                 # APP CD: build+push to ECR, terraform apply staging
├── app/                           # Empty for now — .gitkeep only
│   └── .gitkeep
├── frontend/                      # Reserved — .gitkeep only
│   └── .gitkeep
├── infra/                         # APP-only Terraform (Cognito, RDS, ECS, VPC)
│   ├── bootstrap/                 # S3 state bucket, DDB lock table (chicken-and-egg)
│   ├── cognito/                   # Buyer + seller user pools
│   ├── rds/                       # PostgreSQL
│   └── (future) ecs/, vpc/, ...   # Added by factory features
├── tests/
│   └── .gitkeep
├── docs/
│   └── superpowers/
│       └── specs/                 # Product/feature specs
├── CLAUDE.md                      # APP product context + conventions (factory mentions removed)
└── .gitignore
```

### `nabbic/nova-factory` after the split (target state)

```
nabbic/nova-factory/
├── .github/workflows/
│   ├── build-images.yml           # Builds Ralph-turn + validate-v2 container images on push
│   └── terraform.yml              # terraform plan on PR, apply on merge to main
├── infra/
│   ├── factory/                   # Factory SFN, Lambdas, ECR, DDB, S3 (same TF state key)
│   └── webhook-relay/             # API GW + Lambda routing Notion → SFN (same TF state key)
├── lambdas/                       # Renamed from scripts/factory_lambdas/
│   ├── common/
│   ├── handlers/
│   └── containers/
│       ├── ralph_turn/
│       └── validate_v2/
├── agent-prompts/                 # Renamed from .factory/
│   ├── implementer-system.md
│   ├── reviewer-system.md
│   ├── feature-sizing-rubric.md
│   └── prd.schema.json
├── tools/                         # Renamed from scripts/ (notion setup, smoke fixtures)
├── docs/
│   └── plans/                     # Operational plans (this file moves here later)
├── CLAUDE.md                      # FACTORY operations context
├── .env.example                   # Notion DB IDs, GH owner/repo target
└── README.md
```

### Files moved out of `nabbic/nova`

| Path in `nova` (current) | Destination |
|---|---|
| `infra/factory/**` | `nova-factory/infra/factory/**` |
| `infra/webhook-relay/**` | `nova-factory/infra/webhook-relay/**` |
| `scripts/factory_lambdas/**` | `nova-factory/lambdas/**` |
| `scripts/factory_smoke_fixtures/**` | `nova-factory/tools/smoke_fixtures/**` |
| `scripts/factory_smoke_v2.sh` | `nova-factory/tools/smoke_v2.sh` |
| `scripts/notion_client.py`, `setup_notion*.py`, `create_foundation_features.py` | `nova-factory/tools/` |
| `.factory/implementer-system.md`, `reviewer-system.md`, `feature-sizing-rubric.md`, `prd.schema.json` | `nova-factory/agent-prompts/` |
| `.github/workflows/factory.yml` | DELETED (legacy v1, deprecated 2026-05-03) |

### Files staying in `nabbic/nova` (renamed/cleaned)

| Path | Change |
|---|---|
| `app/**`, `tests/**`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `requirements.txt`, `docs/openapi.json` | Removed (was leaked from PRs #11/#12/#14/#15) |
| `app/.gitkeep`, `tests/.gitkeep`, `frontend/.gitkeep` | Created |
| `CLAUDE.md` | Edited: remove "## Factory" section + commit-prefix conventions |
| `.gitignore` | Edited: remove factory entries no longer relevant |
| `.github/workflows/quality-gates.yml` | Kept; verify FACTORY_CALLBACK_URL secret still works |
| `.github/workflows/deploy.yml` | Kept |

### Code changes to factory (in `nova-factory` after migration)

| File | Change |
|---|---|
| `lambdas/handlers/commit_and_push_v2.py` | Stop writing `.factory/last-run/*` into the app repo's tree. Postdeploy reads PRD from S3. |
| `lambdas/handlers/probe_staging.py` | Read PRD from S3 (`<exec>/plan/prd.json`) instead of the merged commit. |
| `lambdas/handlers/probe_staging.py` | Same for `meta.json` and `review.json`. |
| `lambdas/containers/ralph_turn/allowlist.py` | Remove `.factory/_DONE_` exception — nothing in the app repo's tree should be under `.factory/`. |
| `lambdas/containers/ralph_turn/Dockerfile` | `COPY agent-prompts/` instead of `COPY .factory/`. |
| `lambdas/containers/ralph_turn/ralph_turn.py` | Update `SYSTEM_PROMPT_PATH` to `agent-prompts/implementer-system.md`. |
| `lambdas/handlers/commit_and_push_v2.py` | Change commit-message prefix from `feat(factory):` to `feat: <title>`. |

### AWS resources NOT changed by this plan

- ECR repos: `nova-factory-ralph-turn`, `nova-factory-validator` (just receive new image pushes from the new repo's CI)
- Step Functions: `nova-factory-v2`, `nova-factory-postdeploy` (Terraform updates definition only if state-machine JSON changes, which it won't)
- Lambda functions, IAM roles, S3 bucket, DynamoDB tables, Secrets Manager keys, SSM Parameter, CloudWatch dashboards/alarms/budgets, SNS topic — all unchanged
- Terraform state location: same S3 keys (`factory/terraform.tfstate`, `webhook-relay/terraform.tfstate`)
- API Gateway: same URL (`https://mx838r82ma.execute-api.us-east-1.amazonaws.com/prod/`)

---

## Pre-flight (already done in this session)

- ✅ Factory paused: `/nova/factory/paused = true`
- ✅ In-flight SFN execution stopped (Foundation 12)
- ✅ PR #15 reverted via PR #16 (open, not yet merged)
- ✅ PR #10 closed
- ✅ Notion: Container Platform 01 + Foundation 12 reset to "Spec Ready"

---

## Phase 1 — Empty the app repo on `nabbic/nova`

**Goal:** Extend the open revert branch (PR #16) with one more commit that removes the app code added by PRs #11/#12/#14, then merge.

### Task 1.1 — Verify branch state and pull latest

**Files:** none (git operations only)

- [ ] **Step 1.1.1: Confirm working directory and branch**

```bash
cd /c/Claude/Nova/nova
git status
git branch --show-current
```

Expected: branch `revert/pr-15-container-platform-01-factory-leak`, working tree clean.

- [ ] **Step 1.1.2: Fetch latest**

```bash
git fetch origin
```

Expected: no errors. If `origin/main` advanced beyond what the revert branch was based on, rebase first:

```bash
git rebase origin/main
```

### Task 1.2 — Remove leftover app code from main

**Files:**
- Delete: all paths under `app/` except create `app/.gitkeep`
- Delete: all paths under `tests/`, create `tests/.gitkeep`
- Delete: `requirements.txt`, `docs/openapi.json`
- Create: `frontend/.gitkeep`

Note: PR #16's first commit (revert of #15) already removed `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `tests/test_docker.py`. This task removes the rest.

- [ ] **Step 1.2.1: Remove app source files**

```bash
git rm -rf app/ tests/ requirements.txt docs/openapi.json
```

Expected: deletion of `app/__init__.py`, `app/main.py`, `app/api/...`, `app/core/...`, `app/models/...`, `app/repositories/...`, `app/schemas/...`, `tests/test_health_info.py`, `tests/test_version.py`, `tests/integration/...`, `tests/unit/...`, `requirements.txt`, `docs/openapi.json`.

- [ ] **Step 1.2.2: Recreate empty placeholders**

```bash
mkdir -p app tests frontend
touch app/.gitkeep tests/.gitkeep frontend/.gitkeep
git add app/.gitkeep tests/.gitkeep frontend/.gitkeep
```

- [ ] **Step 1.2.3: Verify staged state**

```bash
git status
```

Expected (selected lines):
```
deleted:    app/api/routes/version.py
deleted:    app/main.py
... (many more deleted)
deleted:    docs/openapi.json
deleted:    requirements.txt
new file:   app/.gitkeep
new file:   frontend/.gitkeep
new file:   tests/.gitkeep
```

- [ ] **Step 1.2.4: Commit**

```bash
git commit -m "$(cat <<'EOF'
chore(repo): reset app/ tests/ to empty — drop leftovers from PRs #11/#12/#14

PRs #11, #12, #14 leaked app code (version v2 endpoint, engagement listing,
health endpoint version) committed under feat(factory):* messages while the
factory was iterating. Combined with #15's container-platform changes
(reverted earlier in this PR), main no longer reflects an actual product
decision — just the trail of factory smoke runs.

Resetting app/ and tests/ to empty placeholders so the factory can rebuild
the spec'd features cleanly after the factory/app split lands. Removes:

- app/main.py, app/api/, app/core/, app/models/, app/repositories/, app/schemas/
- tests/test_health_info.py, test_version.py, integration/, unit/
- requirements.txt (factory will recreate when first dep is added)
- docs/openapi.json (factory will recreate on first API feature)

Adds .gitkeep placeholders under app/, tests/, frontend/ so the directories
exist for the factory's first run.
EOF
)"
```

Expected: one commit, large delete count, three new files.

### Task 1.3 — Push and update PR description

- [ ] **Step 1.3.1: Push**

```bash
git push
```

Expected: branch updated on origin.

- [ ] **Step 1.3.2: Update PR #16 body to reflect expanded scope**

```bash
export GH_TOKEN=$(grep ^GH_TOKEN /c/Claude/Nova/nova/.env | cut -d= -f2-)
gh pr edit 16 --title "Reset main to empty app — revert #15 + drop leftovers from #11/#12/#14" --body "$(cat <<'EOF'
## Summary
Resets `main` to a clean "empty app" state in preparation for the factory/app repo split.

- Reverts PR #15 (Container Platform 01)
- Removes app code from PRs #11, #12, #14 (smoke tests that landed app-side: version endpoint, engagement listing, health version)
- Removes `requirements.txt`, `docs/openapi.json`
- Adds `app/.gitkeep`, `tests/.gitkeep`, `frontend/.gitkeep`
- Strips leaked `.factory/last-run/*` and `.factory/_DONE_` from the tree
- Gitignores `.factory/last-run/` and `.factory/_DONE_`

## Why
The factory shipped scratch state (`.factory/last-run/*`) into every PR alongside actual app code, and used `feat(factory):` commit prefixes for changes that landed app-side. Resetting to empty so the next round of features lands cleanly after the factory/app repo split (see `docs/superpowers/plans/2026-05-06-factory-app-split.md`).

## What stays on main
- `infra/` (PR #4 Cognito + RDS Terraform — app infra, will be kept when factory infra moves out)
- `infra/factory/`, `infra/webhook-relay/`, `scripts/`, `.factory/*-system.md` — UNTOUCHED in this PR; moved out in a later PR per the split plan
- `.github/workflows/quality-gates.yml`, `deploy.yml`
- `CLAUDE.md`, `docs/superpowers/specs/...`

## Test plan
- [ ] After merge: `app/` contains only `.gitkeep`
- [ ] After merge: `tests/` contains only `.gitkeep`
- [ ] After merge: no `Dockerfile`, no `docker-compose.yml`, no `requirements.txt`, no `docs/openapi.json`
- [ ] Factory remains paused (`/nova/factory/paused=true`) until split completes
EOF
)"
```

### Task 1.4 — Merge PR #16

- [ ] **Step 1.4.1: Wait for `quality-gates.yml` to pass on the branch**

```bash
gh pr checks 16
```

Expected: all checks green. If failures, inspect with `gh run view --log` and fix.

Note: `quality-gates.yml` runs ruff/mypy/pytest. Since we removed all app code AND tests, ruff/mypy may pass with no files; pytest will report "no tests collected" which most configs treat as success. If pytest fails on "no tests", a `tests/.gitkeep` containing a no-op `# placeholder` may be needed — first try the green path.

- [ ] **Step 1.4.2: Merge**

```bash
gh pr merge 16 --squash --delete-branch
```

Expected: PR #16 merged, branch deleted.

- [ ] **Step 1.4.3: Update local main**

```bash
git checkout factory-overhaul-2026-05-03
git fetch origin
```

---

## Phase 2 — Bootstrap `nabbic/nova-factory` repo

**Goal:** Create the new repo with skeleton structure, README, CLAUDE.md, gitignore, GitHub Actions stubs, and an empty `infra/` directory ready to receive the factory Terraform in Phase 3.

### Task 2.1 — Create the GitHub repo

- [ ] **Step 2.1.1: Create empty private repo via gh**

```bash
export GH_TOKEN=$(grep ^GH_TOKEN /c/Claude/Nova/nova/.env | cut -d= -f2-)
gh repo create nabbic/nova-factory --private --description "Nova Software Factory — autonomous multi-agent CI/CD pipeline for the Nova app" --clone=false
```

Expected: `https://github.com/nabbic/nova-factory` exists.

- [ ] **Step 2.1.2: Clone locally next to nova**

```bash
cd /c/Claude/Nova
git clone https://github.com/nabbic/nova-factory.git
cd nova-factory
```

### Task 2.2 — Initial commit: README + CLAUDE.md + .gitignore + .env.example

**Files:**
- Create: `README.md`
- Create: `CLAUDE.md`
- Create: `.gitignore`
- Create: `.env.example`

- [ ] **Step 2.2.1: Write README.md**

```bash
cat > README.md <<'EOF'
# Nova Software Factory

Autonomous multi-agent CI/CD pipeline that builds features into the Nova app
(`nabbic/nova`) from Notion specs.

## Pipeline

```
Notion (Status=Ready to Build) → Webhook → API GW → Lambda relay →
  Step Functions nova-factory-v2:
    Plan (Haiku, sizing rubric)
    → RalphLoop (Sonnet container, ≤6 turns)
    → Validate (deterministic ruff/mypy/pytest/tf/tsc)
    → Review (Sonnet)
    → CommitAndPush
    → quality-gates.yml (in nabbic/nova)
    → MarkDone
  Step Functions nova-factory-postdeploy (after merge):
    ProbeStaging
    → Verified | RevertMerge
```

## Repo layout

| Path | Purpose |
|---|---|
| `infra/factory/` | Terraform — SFN, Lambdas, ECR, DDB, S3, IAM, dashboards, budgets |
| `infra/webhook-relay/` | Terraform — API GW + Lambda routing Notion webhooks to SFN |
| `lambdas/handlers/` | Zip Lambda handler source (load_feature, plan, review, etc.) |
| `lambdas/containers/ralph_turn/` | Container Lambda — single Claude Code turn |
| `lambdas/containers/validate_v2/` | Container Lambda — deterministic validation chain |
| `lambdas/common/` | Shared library (anthropic, notion, secrets, locks, runs) |
| `agent-prompts/` | Implementer + reviewer system prompts, PRD schema, sizing rubric |
| `tools/` | Notion setup, smoke fixtures, dev scripts |

## Operations

See `CLAUDE.md` for credentials, operational commands, runbooks.

## Target app repo

The factory clones `nabbic/nova` into `/tmp/ws` and operates only there.
The app repo never sees factory paths. Configure the target via:

- `GITHUB_OWNER` env var on Ralph-turn Lambda (default: `nabbic`)
- `GITHUB_REPO`  env var on Ralph-turn Lambda (default: `nova`)
EOF
```

- [ ] **Step 2.2.2: Write CLAUDE.md (factory operations context — copied and adapted from nova/CLAUDE.md "Factory" section + nova/memory)**

```bash
cat > CLAUDE.md <<'EOF'
# Nova Factory — Operations Context

## What this repo is
The Nova Software Factory: an autonomous multi-agent CI/CD pipeline that
takes feature specs from Notion and produces PRs against the Nova app repo
(`nabbic/nova`). This repo contains the factory's Terraform, Lambda code,
agent prompts, and tooling — nothing from the app itself.

## Hard rule
**The factory must never write to `nabbic/nova` outside the cloned working
tree at `/tmp/ws`.** Specifically: no `.factory/` files in the app repo,
no `infra/factory/` files in the app repo. Per-run scratch state lives in
S3 (`nova-factory-workspaces-577638385116`) and DynamoDB
(`nova-factory-runs`), not in the app's git history.

## Credentials
All secrets in `.env` (gitignored). Required keys:
- `GH_TOKEN` — GitHub PAT with repo:write on `nabbic/nova` and `nabbic/nova-factory`
- `NOTION_API_KEY`, `NOTION_FEATURES_DB_ID`, `NOTION_RUNS_DB_ID`, `NOTION_DECISIONS_DB_ID`
- `ANTHROPIC_API_KEY`
- `AWS_DEFAULT_REGION=us-east-1`

## AWS
- Account: 577638385116, region us-east-1
- Terraform backend: S3 `nova-terraform-state-577638385116`, DDB `nova-terraform-locks`
- Factory state key: `factory/terraform.tfstate`
- Webhook-relay state key: `webhook-relay/terraform.tfstate`
- ECR: `nova-factory-ralph-turn`, `nova-factory-validator`
- State machines: `nova-factory-v2`, `nova-factory-postdeploy`
- S3 workspace bucket: `nova-factory-workspaces-577638385116`
- DDB: `nova-factory-locks`, `nova-factory-runs`
- Pause flag: SSM `/nova/factory/paused`

## Pause / unpause
```bash
MSYS_NO_PATHCONV=1 aws ssm put-parameter --name /nova/factory/paused --value true  --type String --overwrite
MSYS_NO_PATHCONV=1 aws ssm put-parameter --name /nova/factory/paused --value false --type String --overwrite
```

## Manually start an execution
```bash
aws stepfunctions start-execution \
  --state-machine-arn arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-v2 \
  --name "manual-$(date +%s)" \
  --input '{"feature_id":"<notion-page-uuid>"}'
```

## Build & push container images
```bash
# Ralph-turn
cd lambdas/containers/ralph_turn && ./build.sh
# Validate v2
cd lambdas/containers/validate_v2 && ./build.sh
```

Both push to `577638385116.dkr.ecr.us-east-1.amazonaws.com/<repo>:latest`.
After push, update the Lambda function via Terraform apply OR:

```bash
aws lambda update-function-code \
  --function-name nova-factory-ralph-turn \
  --image-uri 577638385116.dkr.ecr.us-east-1.amazonaws.com/nova-factory-ralph-turn:latest
```

## Terraform
```bash
terraform -chdir=infra/factory       init
terraform -chdir=infra/factory       plan
terraform -chdir=infra/factory       apply
terraform -chdir=infra/webhook-relay init
terraform -chdir=infra/webhook-relay plan
terraform -chdir=infra/webhook-relay apply
```

State stays at the same S3 keys, so `init` against the new working dir
attaches to existing state without recreating any resources.

## Notion
- Features DB: `3530930abc71819092f1fce9b49e768a`
- Runs DB: `3530930abc71814c9d1bddfd521d0af6`
- Decisions DB: `3530930abc7181608114cfb7b0670637`
- Setting a feature to "Ready to Build" triggers the webhook → factory.

## Logs
```bash
MSYS_NO_PATHCONV=1 aws logs tail /aws/lambda/nova-factory-ralph-turn --follow
MSYS_NO_PATHCONV=1 aws logs tail /aws/lambda/nova-factory-validate-v2 --follow
```

## Saved Logs Insights queries
- `nova-factory-v2/ralph-turn-summary` — turns + token totals binned hourly
- `nova-factory-v2/validation-failures` — recent validate failures
- `nova-factory-v2/execution-trace` — combined SFN+Ralph+Validate logs
EOF
```

- [ ] **Step 2.2.3: Write .gitignore**

```bash
cat > .gitignore <<'EOF'
# Python
__pycache__/
*.pyc
.venv/
*.egg-info/

# Terraform
.terraform/
*.tfstate
*.tfstate.backup
*.tfplan
*tfplan
.outputs.json
infra/*/lambda-layer/python/

# Build artifacts
*.zip
.build/

# Secrets
.env
*.pem

# IDE
.serena/
.superpowers/
.qodo/
.claude/local/

# Lambda layer build artifacts
infra/factory/lambda-layer/python/
EOF
```

- [ ] **Step 2.2.4: Write .env.example**

```bash
cat > .env.example <<'EOF'
# GitHub
GH_TOKEN=ghp_xxx
GITHUB_OWNER=nabbic
GITHUB_REPO=nova

# Notion
NOTION_API_KEY=secret_xxx
NOTION_FEATURES_DB_ID=3530930abc71819092f1fce9b49e768a
NOTION_RUNS_DB_ID=3530930abc71814c9d1bddfd521d0af6
NOTION_DECISIONS_DB_ID=3530930abc7181608114cfb7b0670637

# Anthropic
ANTHROPIC_API_KEY=sk-ant-xxx

# AWS
AWS_DEFAULT_REGION=us-east-1
EOF
```

- [ ] **Step 2.2.5: Initial commit**

```bash
git add README.md CLAUDE.md .gitignore .env.example
git commit -m "chore: initial repo skeleton — README, CLAUDE.md, gitignore, env template"
git push -u origin main
```

Expected: first commit on `nova-factory:main`.

---

## Phase 3 — Migrate factory Terraform

**Goal:** Move `infra/factory/` and `infra/webhook-relay/` from `nova` → `nova-factory`. Verify Terraform state attaches cleanly with no resource changes.

The Terraform state backend (S3 + DynamoDB) is referenced by S3 KEY in each module. Pointing a new working directory at the same backend with the same key loads existing state. `terraform plan` should show **zero changes** if files are copied verbatim.

### Task 3.1 — Copy factory Terraform files

**Files:** Copied verbatim from `nabbic/nova` working tree to `nabbic/nova-factory`.

- [ ] **Step 3.1.1: Confirm factory-overhaul branch is checked out in nova (it has the latest factory code)**

```bash
cd /c/Claude/Nova/nova
git checkout factory-overhaul-2026-05-03
git status
```

Expected: branch checked out, clean.

- [ ] **Step 3.1.2: Copy `infra/factory/` and `infra/webhook-relay/` to nova-factory (excluding terraform local state, layer build outputs)**

```bash
cd /c/Claude/Nova/nova-factory
mkdir -p infra
rsync -av --exclude='.terraform/' --exclude='*.tfstate*' --exclude='*.tfplan' \
  --exclude='lambda-layer/python/' --exclude='lambda-layer/*.zip' \
  --exclude='.outputs.json' \
  /c/Claude/Nova/nova/infra/factory/ \
  /c/Claude/Nova/nova-factory/infra/factory/
rsync -av --exclude='.terraform/' --exclude='*.tfstate*' --exclude='*.tfplan' \
  /c/Claude/Nova/nova/infra/webhook-relay/ \
  /c/Claude/Nova/nova-factory/infra/webhook-relay/
ls -la infra/factory/ infra/webhook-relay/
```

Expected: `infra/factory/main.tf`, `state-machine-v2.tf`, `lambdas-v2.tf`, `lambdas-v2-images.tf`, `iam.tf`, `iam-ralph.tf`, `s3.tf`, `dynamodb.tf`, `secrets.tf`, `parameter-store.tf`, `dashboard-v2.tf`, `alarms-v2.tf`, `budgets-v2.tf`, `auto-pause-subscription.tf`, `callback-api.tf`, `state-machine-postdeploy.tf`, `state-machine-postdeploy.json.tpl`, `state-machine-v2.json.tpl`, `outputs.tf`, `variables.tf`, `lambda-layer.tf`, `lambda-layer/build.sh`, `lambda-layer/requirements.txt`, `logs-insights-queries.tf`, `README.md`, `.terraform.lock.hcl`. Plus `infra/webhook-relay/main.tf`, `lambda/index.js`, `lambda/package.json`, `outputs.tf`, `variables.tf`, `.terraform.lock.hcl`.

- [ ] **Step 3.1.3: Inspect any references in TF that point to paths outside the new repo**

```bash
grep -rn "scripts/factory_lambdas\|\\.factory/" infra/
```

Expected: matches in `lambdas-v2-images.tf` (Docker build context for ECR images) and `lambdas-v2.tf` (zip bundling). These reference paths that will move in Phase 4 — flag them; we'll fix in Phase 4.5 after the lambdas are copied. **Do not edit yet** — keep the diff minimal for Phase 3 verification.

### Task 3.2 — Wire `terraform init` against the existing backend

- [ ] **Step 3.2.1: Init factory module**

```bash
cd /c/Claude/Nova/nova-factory
terraform -chdir=infra/factory init
```

Expected: "Initializing the backend... Successfully configured the backend "s3"!" — no prompt to migrate state because the state key matches.

If the lambda layer or scripts paths break the init (e.g., `archive_file` data source referencing `../../scripts/factory_lambdas/...`), DO NOT fix here — note the error, abort, and move to Phase 4 first. Re-attempt this step after Phase 4.

- [ ] **Step 3.2.2: Init webhook-relay module**

```bash
terraform -chdir=infra/webhook-relay init
```

Expected: same — state attaches cleanly.

### Task 3.3 — Defer `terraform plan` until after lambda code moves

The factory TF references the lambda source via relative paths (e.g., `${path.module}/../../scripts/factory_lambdas/handlers/...`). Once lambdas move in Phase 4, those paths need updating to `${path.module}/../../lambdas/handlers/...`. Run `terraform plan` after Phase 4.5.

- [ ] **Step 3.3.1: Commit Terraform-only state**

```bash
git add infra/
git commit -m "chore(infra): import factory + webhook-relay terraform from nova

Verbatim copy. Backend points at the same S3 keys
(factory/terraform.tfstate, webhook-relay/terraform.tfstate) so existing
AWS resources are unchanged. terraform plan deferred until lambda source
paths are updated in Phase 4.5."
git push
```

---

## Phase 4 — Migrate factory Lambda code + agent prompts

**Goal:** Move Lambda handlers, container source, and agent prompts to nova-factory. Update import paths and Dockerfile COPY directives.

### Task 4.1 — Copy `lambdas/`

- [ ] **Step 4.1.1: Copy factory_lambdas to lambdas/**

```bash
cd /c/Claude/Nova/nova-factory
mkdir -p lambdas
rsync -av --exclude='__pycache__/' --exclude='*.pyc' \
  /c/Claude/Nova/nova/scripts/factory_lambdas/ \
  /c/Claude/Nova/nova-factory/lambdas/
ls lambdas/
```

Expected: `common/`, `handlers/`, `containers/`, `build.sh`.

- [ ] **Step 4.1.2: Confirm structure**

```bash
ls lambdas/handlers/
ls lambdas/containers/ralph_turn/ lambdas/containers/validate_v2/
ls lambdas/common/
```

Expected:
- `handlers/`: `acquire_lock.py`, `auto_pause.py`, `commit_and_push_v2.py`, `handle_quality_gate_callback.py`, `load_feature.py`, `mark_blocked.py`, `plan.py`, `probe_staging.py`, `release_lock.py`, `revert_merge.py`, `review.py`, `trigger_quality_gates.py`, `update_notion.py`, `__init__.py`
- `containers/ralph_turn/`: `Dockerfile`, `allowlist.py`, `build.sh`, `git_io.py`, `ralph_turn.py`
- `containers/validate_v2/`: `Dockerfile`, `build.sh`, `validate_v2.py`
- `common/`: `__init__.py`, `anthropic.py`, `locks.py`, `notion.py`, `probe.py`, `runs.py`, `secrets.py`, `sizing.py`, `workspace.py`

### Task 4.2 — Copy agent prompts to `agent-prompts/`

- [ ] **Step 4.2.1: Copy and rename**

```bash
mkdir -p agent-prompts
cp /c/Claude/Nova/nova/.factory/implementer-system.md      agent-prompts/
cp /c/Claude/Nova/nova/.factory/reviewer-system.md         agent-prompts/
cp /c/Claude/Nova/nova/.factory/feature-sizing-rubric.md   agent-prompts/
cp /c/Claude/Nova/nova/.factory/prd.schema.json            agent-prompts/
ls agent-prompts/
```

Expected: 4 files.

### Task 4.3 — Copy tools to `tools/`

- [ ] **Step 4.3.1: Copy non-lambda factory scripts**

```bash
mkdir -p tools tools/smoke_fixtures
cp /c/Claude/Nova/nova/scripts/factory_smoke_v2.sh           tools/smoke_v2.sh
cp /c/Claude/Nova/nova/scripts/notion_client.py              tools/
cp /c/Claude/Nova/nova/scripts/setup_notion.py               tools/
cp /c/Claude/Nova/nova/scripts/setup_notion_dependencies.py  tools/
cp /c/Claude/Nova/nova/scripts/setup_notion_fields.py        tools/
cp /c/Claude/Nova/nova/scripts/create_foundation_features.py tools/
cp -r /c/Claude/Nova/nova/scripts/factory_smoke_fixtures/.   tools/smoke_fixtures/
ls tools/ tools/smoke_fixtures/
```

Expected: 6 .py + 1 .sh files in `tools/`, 4 .json + README.md in `tools/smoke_fixtures/`.

### Task 4.4 — Update Ralph-turn Dockerfile to COPY from new paths

**Files:** `lambdas/containers/ralph_turn/Dockerfile`

- [ ] **Step 4.4.1: Edit Dockerfile to use agent-prompts/ instead of .factory/**

```bash
sed -i 's|COPY \.factory/ |COPY agent-prompts/ |' lambdas/containers/ralph_turn/Dockerfile
sed -i 's|\${LAMBDA_TASK_ROOT}/\.factory/|${LAMBDA_TASK_ROOT}/agent-prompts/|' lambdas/containers/ralph_turn/Dockerfile
cat lambdas/containers/ralph_turn/Dockerfile
```

Expected lines (verify):
```
COPY agent-prompts/                                                 ${LAMBDA_TASK_ROOT}/agent-prompts/
```

If sed didn't match exactly, edit manually:
```
COPY agent-prompts/                                                 ${LAMBDA_TASK_ROOT}/agent-prompts/

COPY lambdas/containers/ralph_turn/allowlist.py                     ${LAMBDA_TASK_ROOT}/
COPY lambdas/containers/ralph_turn/git_io.py                        ${LAMBDA_TASK_ROOT}/
COPY lambdas/containers/ralph_turn/ralph_turn.py                    ${LAMBDA_TASK_ROOT}/
```

- [ ] **Step 4.4.2: Update build.sh context paths**

Read `lambdas/containers/ralph_turn/build.sh`. The build context root is the repo root (one level up from the Dockerfile). Update any `scripts/factory_lambdas/...` references to `lambdas/...`.

```bash
cat lambdas/containers/ralph_turn/build.sh
```

If the script uses `scripts/factory_lambdas/containers/ralph_turn/...` paths, update them:

```bash
sed -i 's|scripts/factory_lambdas/|lambdas/|g' lambdas/containers/ralph_turn/build.sh
sed -i 's|scripts/factory_lambdas/|lambdas/|g' lambdas/containers/validate_v2/build.sh
```

### Task 4.5 — Update Ralph-turn Python to read prompts from new location

**Files:** `lambdas/containers/ralph_turn/ralph_turn.py`

- [ ] **Step 4.5.1: Change SYSTEM_PROMPT_PATH**

Open `lambdas/containers/ralph_turn/ralph_turn.py`. Find:

```python
SYSTEM_PROMPT_PATH = TASK_ROOT / ".factory" / "implementer-system.md"
```

Replace with:

```python
SYSTEM_PROMPT_PATH = TASK_ROOT / "agent-prompts" / "implementer-system.md"
```

```bash
sed -i 's|TASK_ROOT / "\.factory" / "implementer-system\.md"|TASK_ROOT / "agent-prompts" / "implementer-system.md"|' lambdas/containers/ralph_turn/ralph_turn.py
grep -n "implementer-system" lambdas/containers/ralph_turn/ralph_turn.py
```

Expected output:
```
SYSTEM_PROMPT_PATH = TASK_ROOT / "agent-prompts" / "implementer-system.md"
```

- [ ] **Step 4.5.2: Search for any other `.factory/` references in lambdas/**

```bash
grep -rn "\\.factory/" lambdas/ agent-prompts/
```

Expected: matches in `commit_and_push_v2.py` (which intentionally writes `.factory/last-run/*` into the app repo — this is the bug we fix in Phase 5). Also possibly `probe_staging.py`. Note the matches; don't fix here — Phase 5 handles them.

### Task 4.6 — Update Terraform paths to point at the new lambda layout

**Files:** `infra/factory/lambdas-v2.tf`, `infra/factory/lambdas.tf`, `infra/factory/lambdas-v2-images.tf`

- [ ] **Step 4.6.1: Identify all path references**

```bash
grep -rn "scripts/factory_lambdas\|\.factory/" infra/factory/
```

Expected: references in `lambdas.tf` (zip handler bundling), `lambdas-v2.tf` (zip handler bundling for v2), `lambdas-v2-images.tf` (Docker build context for container Lambdas).

- [ ] **Step 4.6.2: Update zip-Lambda paths**

```bash
sed -i 's|scripts/factory_lambdas|lambdas|g' infra/factory/lambdas.tf
sed -i 's|scripts/factory_lambdas|lambdas|g' infra/factory/lambdas-v2.tf
grep -n "lambdas" infra/factory/lambdas-v2.tf | head -20
```

Expected: paths now read `${path.module}/../../lambdas/handlers/...`.

- [ ] **Step 4.6.3: Update container-Lambda Docker build context**

```bash
sed -i 's|scripts/factory_lambdas|lambdas|g' infra/factory/lambdas-v2-images.tf
grep -n "build_context\|context_path\|source_path" infra/factory/lambdas-v2-images.tf
```

Expected: paths reference `lambdas/containers/ralph_turn/` and `lambdas/containers/validate_v2/`.

### Task 4.7 — Run `terraform plan` to verify zero drift

- [ ] **Step 4.7.1: Plan factory module**

```bash
terraform -chdir=infra/factory plan -no-color > /tmp/factory-plan.txt 2>&1
grep -E "Plan:|No changes|error|Error" /tmp/factory-plan.txt | head -20
```

Expected: `No changes. Your infrastructure matches the configuration.`

If the plan shows changes, inspect `/tmp/factory-plan.txt`. Likely causes:
- Lambda source hash changed because `archive_file` re-zipped the same code (acceptable — the function code didn't change; new image tag is the same)
- Image references differ (acceptable if just the image-source path attribute changed but not the digest)

If real resource changes appear (e.g., function deletion/recreation, IAM changes), STOP and reconcile.

- [ ] **Step 4.7.2: Plan webhook-relay module**

```bash
terraform -chdir=infra/webhook-relay plan -no-color > /tmp/webhook-plan.txt 2>&1
grep -E "Plan:|No changes|error|Error" /tmp/webhook-plan.txt | head -20
```

Expected: `No changes.`

### Task 4.8 — Commit Phase 4

- [ ] **Step 4.8.1: Stage and commit**

```bash
git add lambdas/ agent-prompts/ tools/ infra/
git commit -m "feat(factory): import lambdas, agent prompts, tools from nova

- lambdas/         <- nova/scripts/factory_lambdas/
- agent-prompts/   <- nova/.factory/{implementer,reviewer}-system.md, sizing rubric, prd.schema.json
- tools/           <- nova/scripts/{factory_smoke_v2.sh, notion_*, setup_notion*, create_foundation_features.py}
- tools/smoke_fixtures/ <- nova/scripts/factory_smoke_fixtures/

Updated infra/factory/lambdas*.tf source paths to lambdas/ and Ralph-turn
Dockerfile/Python to read prompts from agent-prompts/ instead of .factory/.

terraform plan in both infra/factory and infra/webhook-relay reports
'No changes' — same backend keys, same resources."
git push
```

---

## Phase 5 — Stop committing factory state into the app repo

**Goal:** Modify `commit_and_push_v2.py` to omit `.factory/last-run/*` from the app repo's tree. Read PRD/meta from S3 in the postdeploy probe instead. Drop the `feat(factory):` commit prefix.

### Task 5.1 — Update `commit_and_push_v2.py` to not write `.factory/last-run/*`

**Files:** `lambdas/handlers/commit_and_push_v2.py`

- [ ] **Step 5.1.1: Identify the block to remove**

Read `lambdas/handlers/commit_and_push_v2.py`. Locate the section starting with the comment `# Always inject .factory/last-run/* artifacts (for the postdeploy probe)`. It populates `last_run_blobs` and merges them into the tree.

- [ ] **Step 5.1.2: Remove the injection block**

The block looks roughly like:

```python
# Always inject .factory/last-run/* artifacts (for the postdeploy probe)
last_run_blobs: dict[str, bytes] = {
    ".factory/last-run/prd.json":  json.dumps(prd, indent=2).encode("utf-8"),
    ".factory/last-run/meta.json": json.dumps({
        "feature_id": feature_id, "execution_id": execution_id, ...
    }).encode("utf-8"),
    ".factory/last-run/progress.txt": (progress or "").encode("utf-8"),
    ".factory/last-run/review.json": (review_js or "{}").encode("utf-8"),
}
# ... merge into tree
```

Delete it. Also remove any subsequent code that adds `last_run_blobs` to the GitHub Tree API payload.

After removal, the tree built and pushed contains only files from `<execution_id>/workspace/` (filtered by `changed_files` minus internal artifacts) — pure app code.

- [ ] **Step 5.1.3: Change commit-message prefix from `feat(factory):` to `feat:`**

In the same file, find the commit-message construction. It currently produces:
```
feat(factory): <PRD title>\n\n<narrative>\n\nfactory-execution: <id>
```

Change `feat(factory):` to `feat:` (or omit the trailing `factory-execution:` line — keep for traceability).

```bash
grep -n "feat(factory)" lambdas/handlers/commit_and_push_v2.py
```

Expected: hits to update.

```bash
sed -i 's|feat(factory):|feat:|g' lambdas/handlers/commit_and_push_v2.py
```

### Task 5.2 — Update `probe_staging.py` to read PRD/meta/review from S3

**Files:** `lambdas/handlers/probe_staging.py`

- [ ] **Step 5.2.1: Inspect current probe logic**

```bash
grep -n "\\.factory/last-run" lambdas/handlers/probe_staging.py
```

Expected: hits where the probe fetches `.factory/last-run/*.json` from the merged commit via the GitHub API.

- [ ] **Step 5.2.2: Replace with S3 reads**

Replace any call that fetches `.factory/last-run/<file>.json` from GitHub with an S3 GET against `<execution_id>/<plan|review|workspace>/<file>` using the existing `_s3` boto client. The execution_id is in the SFN event passed to the probe.

If the probe doesn't currently receive `execution_id` in its event, update `state-machine-postdeploy.json.tpl` to pass it through (find the State that calls ProbeStaging and ensure `"execution_id.$": "$.execution_id"` is in the parameters).

```bash
grep -n "execution_id\|prd\\.json\|meta\\.json\|review\\.json" lambdas/handlers/probe_staging.py
```

- [ ] **Step 5.2.3: If postdeploy SFN doesn't yet pass execution_id, update state-machine-postdeploy.json.tpl**

```bash
grep -n "execution_id" infra/factory/state-machine-postdeploy.json.tpl
```

If missing in the ProbeStaging task's parameters, add it. Then `terraform plan` will show a state-machine update (which IS expected this time).

### Task 5.3 — Tighten allowlist (drop `.factory/_DONE_` exception)

**Files:** `lambdas/containers/ralph_turn/allowlist.py`

- [ ] **Step 5.3.1: Remove the sentinel exception**

Open `lambdas/containers/ralph_turn/allowlist.py`. Find:

```python
_FACTORY_DONE_SENTINEL = ".factory/_DONE_"

def classify(path: str) -> str:
    ...
    if path.startswith(".factory/"):
        return ALLOWED if path == _FACTORY_DONE_SENTINEL else DENIED
    ...
```

Replace with:

```python
def classify(path: str) -> str:
    if path.startswith("/"):
        return DENIED
    if ".." in path.split("/"):
        return DENIED
    if path.startswith(".factory/"):
        return DENIED
    for prefix in _DENIED_PREFIXES:
        if path.startswith(prefix):
            return DENIED
    return ALLOWED
```

Delete the `_FACTORY_DONE_SENTINEL` constant.

### Task 5.4 — Tests for allowlist + commit_and_push

**Files:** `lambdas/containers/ralph_turn/test_allowlist.py` (new), `lambdas/handlers/test_commit_and_push_v2.py` (new)

- [ ] **Step 5.4.1: Write failing test — allowlist denies all .factory/ paths**

```bash
cat > lambdas/containers/ralph_turn/test_allowlist.py <<'EOF'
from allowlist import classify, ALLOWED, DENIED


def test_denies_factory_paths():
    assert classify(".factory/_DONE_") == DENIED
    assert classify(".factory/last-run/prd.json") == DENIED
    assert classify(".factory/implementer-system.md") == DENIED


def test_denies_infra_factory():
    assert classify("infra/factory/main.tf") == DENIED


def test_denies_workflows():
    assert classify(".github/workflows/factory.yml") == DENIED


def test_denies_traversal():
    assert classify("../etc/passwd") == DENIED
    assert classify("/etc/passwd") == DENIED


def test_allows_app_paths():
    assert classify("app/main.py") == ALLOWED
    assert classify("infra/cognito/main.tf") == ALLOWED
    assert classify("Dockerfile") == ALLOWED
    assert classify("docs/openapi.json") == ALLOWED
EOF
```

- [ ] **Step 5.4.2: Run test, expect FAIL on `_DONE_` line if allowlist not yet updated**

```bash
cd lambdas/containers/ralph_turn
python -m pytest test_allowlist.py -v
```

Expected: `test_denies_factory_paths` FAILS at `assert classify(".factory/_DONE_") == DENIED` BEFORE the Phase 5.3 edit. After the edit, all pass.

- [ ] **Step 5.4.3: Run test, expect PASS**

```bash
python -m pytest test_allowlist.py -v
```

Expected: 5 passed.

### Task 5.5 — Commit Phase 5

- [ ] **Step 5.5.1: Stage + commit**

```bash
cd /c/Claude/Nova/nova-factory
git add lambdas/ infra/factory/state-machine-postdeploy.json.tpl
git commit -m "fix(factory): stop writing factory state into the app repo

- commit_and_push_v2: remove .factory/last-run/* tree injection. PRD,
  meta, progress, and review live in S3 at <exec_id>/{plan,review,workspace}/.
- commit_and_push_v2: change commit prefix from feat(factory): to feat:.
- probe_staging: read PRD/meta from S3 instead of the merged commit.
- allowlist: deny .factory/_DONE_ along with all other .factory/ paths.
- Add allowlist tests covering factory paths, traversal, app paths.

The app repo's git history now contains only app code. Per-run scratch
state stays inside the factory's domain (S3 + DynamoDB)."
git push
```

---

## Phase 6 — Build, deploy, and smoke-test factory from the new repo

**Goal:** Build container images from `nova-factory`, push to ECR, apply Terraform (now that postdeploy SFN definition changed in 5.2.3), confirm SFN works against a paused factory by manually starting an execution.

### Task 6.1 — Build & push container images

- [ ] **Step 6.1.1: Build Ralph-turn**

```bash
cd /c/Claude/Nova/nova-factory
./lambdas/containers/ralph_turn/build.sh
```

Expected: `docker push 577638385116.dkr.ecr.us-east-1.amazonaws.com/nova-factory-ralph-turn:latest` succeeds.

- [ ] **Step 6.1.2: Build Validate-v2**

```bash
./lambdas/containers/validate_v2/build.sh
```

Expected: `docker push 577638385116.dkr.ecr.us-east-1.amazonaws.com/nova-factory-validator:latest` succeeds.

- [ ] **Step 6.1.3: Force Lambdas to pick up new image digests**

```bash
aws lambda update-function-code --function-name nova-factory-ralph-turn \
  --image-uri 577638385116.dkr.ecr.us-east-1.amazonaws.com/nova-factory-ralph-turn:latest \
  --query 'LastUpdateStatus' --output text
aws lambda update-function-code --function-name nova-factory-validate-v2 \
  --image-uri 577638385116.dkr.ecr.us-east-1.amazonaws.com/nova-factory-validator:latest \
  --query 'LastUpdateStatus' --output text
```

Expected: `Successful` for both.

### Task 6.2 — Apply Terraform changes from Phase 5

- [ ] **Step 6.2.1: Plan**

```bash
terraform -chdir=infra/factory plan -no-color | tail -30
```

Expected: state-machine-postdeploy update (in-place modification) showing the new `execution_id` parameter passthrough. No other changes.

- [ ] **Step 6.2.2: Apply (memory entry `feedback_terraform_apply.md` pre-authorizes apply for Nova factory infra)**

```bash
terraform -chdir=infra/factory apply -auto-approve
```

Expected: `Apply complete! Resources: 0 added, 1 changed, 0 destroyed.`

### Task 6.3 — Smoke test

- [ ] **Step 6.3.1: Verify pause is still on**

```bash
MSYS_NO_PATHCONV=1 aws ssm get-parameter --name /nova/factory/paused --query Parameter.Value --output text
```

Expected: `true`.

- [ ] **Step 6.3.2: Pick smoke fixture (smallest/trivial PRD)**

```bash
cat tools/smoke_fixtures/trivial.json
```

This is a self-contained PRD that doesn't require Notion. Confirm it has a `feature_id`, `prd`, and any other expected fields.

- [ ] **Step 6.3.3: Start a manual SFN execution with the smoke fixture**

The smoke script takes care of S3 prep and SFN start:

```bash
./tools/smoke_v2.sh trivial
```

Expected: SFN execution starts, runs through Plan/Ralph/Validate/Review/Commit. Watch logs:

```bash
EXEC_NAME=$(aws stepfunctions list-executions --state-machine-arn arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-v2 --max-results 1 --query 'executions[0].name' --output text)
aws logs tail /aws/lambda/nova-factory-ralph-turn --follow &
TAIL_PID=$!
aws stepfunctions describe-execution --execution-arn arn:aws:states:us-east-1:577638385116:execution:nova-factory-v2:$EXEC_NAME --query status --output text
# Once SUCCEEDED:
kill $TAIL_PID
```

- [ ] **Step 6.3.4: Verify the resulting PR contains NO `.factory/` paths**

```bash
PR=$(gh pr list --repo nabbic/nova --state open --limit 1 --json number,headRefName,files | python -c "import json,sys; d=json.load(sys.stdin)[0]; print(d['number']); print('\n'.join(f['path'] for f in d['files']))")
echo "$PR"
```

Expected: PR opened on `nabbic/nova`, file list contains only app-side paths (`app/`, `tests/`, `requirements.txt`, etc.) — NO `.factory/last-run/*`, NO `.factory/_DONE_`. Commit message starts with `feat:` (not `feat(factory):`).

If the PR contains any `.factory/` paths, the fix in Phase 5 didn't take. Investigate:
- Is `commit_and_push_v2.py` zipped into the deployed Lambda? Re-run `terraform apply` and `aws lambda update-function-code` for `nova-factory-commit-and-push-v2`.
- Did the Ralph-turn workspace contain pre-existing `.factory/` paths from the cloned `nabbic/nova:main`? After Phase 1 merges, `main` has no `.factory/` files at all, so this should be empty — verify with `git ls-tree origin/main -- .factory/` showing nothing.

- [ ] **Step 6.3.5: Close smoke PR (don't merge — it's just a smoke run)**

```bash
gh pr close <PR_NUMBER> --repo nabbic/nova --delete-branch --comment "Smoke test for factory split — closing without merging"
```

---

## Phase 7 — Tear down factory from `nabbic/nova`

**Goal:** Delete `infra/factory/`, `infra/webhook-relay/`, `scripts/factory*`, `.factory/`, `.github/workflows/factory.yml` from `nabbic/nova`. Edit `CLAUDE.md` to remove factory mentions.

### Task 7.1 — Tear-down branch in nova

- [ ] **Step 7.1.1: Branch off main**

```bash
cd /c/Claude/Nova/nova
git fetch origin
git checkout -b chore/extract-factory-to-separate-repo origin/main
```

### Task 7.2 — Remove factory files

- [ ] **Step 7.2.1: Delete factory paths**

```bash
git rm -rf infra/factory infra/webhook-relay
git rm -rf scripts/factory_lambdas scripts/factory_smoke_fixtures
git rm    scripts/factory_smoke_v2.sh scripts/notion_client.py \
          scripts/setup_notion.py scripts/setup_notion_dependencies.py \
          scripts/setup_notion_fields.py scripts/create_foundation_features.py
git rm    -rf .factory
git rm    .github/workflows/factory.yml
git status --short
```

Expected: large delete count, no other modifications. Verify `infra/cognito/`, `infra/rds/`, `infra/bootstrap/` (or whatever app infra exists) are NOT removed.

### Task 7.3 — Edit CLAUDE.md to remove factory operations

**Files:** `CLAUDE.md`

- [ ] **Step 7.3.1: Read current CLAUDE.md**

```bash
cat CLAUDE.md | head -40
```

- [ ] **Step 7.3.2: Remove the "## Factory" section**

Open `CLAUDE.md`. Find the `## Factory` section (currently 4 lines starting with "This repository is built and maintained by..."). Replace with a one-line pointer:

```markdown
## Factory
This repository is built by the Nova Software Factory (`nabbic/nova-factory`).
Features flow Notion → factory → PR here. Do not edit factory infrastructure
in this repo — it lives in `nabbic/nova-factory`.
```

### Task 7.4 — Update `.gitignore`

- [ ] **Step 7.4.1: Remove obsolete factory entries**

The current `.gitignore` (after PR #16 merge) has:

```
# Factory workspace (ephemeral per run)
.factory-workspace/

# Factory per-run scratch — agent state belongs in S3, never in the app repo
.factory/last-run/
.factory/_DONE_
```

After tear-down these are obsolete (`.factory/` no longer exists in this repo). Replace the three sections with:

```
# Factory artifacts must never appear in this repo
.factory/
.factory-workspace/
```

This is a defense-in-depth — if anything tries to write `.factory/` here, git ignores it.

### Task 7.5 — Commit and push tear-down

- [ ] **Step 7.5.1: Commit**

```bash
git add -A
git commit -m "chore: extract factory to nabbic/nova-factory

The Nova Software Factory now lives in its own repo. This commit removes:

- infra/factory/         -> nova-factory/infra/factory/
- infra/webhook-relay/   -> nova-factory/infra/webhook-relay/
- scripts/factory_lambdas/, factory_smoke_*, notion_*, setup_notion*,
  create_foundation_features.py -> nova-factory/lambdas/, tools/
- .factory/              -> nova-factory/agent-prompts/
- .github/workflows/factory.yml — deprecated v1 GitHub Actions runner

The factory clones this repo into /tmp/ws and operates only there. App
code, app infra (Cognito, RDS, etc.), and app CI/CD remain here.

CLAUDE.md updated to point at the factory repo. .gitignore now denies
.factory/ outright as defense-in-depth.

Refs: docs/superpowers/plans/2026-05-06-factory-app-split.md"
git push -u origin chore/extract-factory-to-separate-repo
```

- [ ] **Step 7.5.2: Open PR**

```bash
gh pr create --title "Extract factory to nabbic/nova-factory" --body "$(cat <<'EOF'
## Summary
Removes factory infrastructure, Lambda source, agent prompts, and tooling from this repo. They now live in [nabbic/nova-factory](https://github.com/nabbic/nova-factory).

## Why
Per `docs/superpowers/plans/2026-05-06-factory-app-split.md`, the factory was leaking scratch state into the app repo and using `feat(factory):` commit prefixes for changes that landed app-side. The fix is physical separation: the factory clones this repo into `/tmp/ws` and operates only there.

## What stays here
- App code (`app/`, `frontend/`, `tests/`)
- App infra (`infra/bootstrap/`, `infra/cognito/`, `infra/rds/`, future `infra/ecs/`)
- App CI/CD (`.github/workflows/quality-gates.yml`, `deploy.yml`)
- Product context (`CLAUDE.md`, `docs/superpowers/specs/...`)

## Verification
- [x] Factory smoke ran from `nova-factory` against `nabbic/nova` and produced a clean PR with no `.factory/` paths and `feat:` commit prefix
- [x] No AWS resource changes — Terraform state migrated by re-init, not by destroy/recreate
- [ ] Factory remains paused (`/nova/factory/paused=true`) until this PR merges
EOF
)"
```

### Task 7.6 — Merge tear-down PR

- [ ] **Step 7.6.1: Wait for checks**

```bash
gh pr checks --watch
```

- [ ] **Step 7.6.2: Merge**

```bash
gh pr merge --squash --delete-branch
```

---

## Phase 8 — Re-trigger spec'd features in Notion

**Goal:** Unpause the factory and walk it through the spec'd backlog, verifying each PR is clean.

### Task 8.1 — Sanity check

- [ ] **Step 8.1.1: Confirm `nabbic/nova:main` is in target state**

```bash
cd /c/Claude/Nova/nova
git fetch origin
git ls-tree origin/main | head -20
git ls-tree -r origin/main | grep -E "^\\.factory|^infra/factory|^infra/webhook|^scripts/factory" | head
```

Expected: app/.gitkeep, tests/.gitkeep, frontend/.gitkeep, infra/{bootstrap,cognito,rds}/, .github/workflows/{deploy,quality-gates}.yml, CLAUDE.md, docs/, .gitignore, README. NO `.factory/`, NO `infra/factory/`, NO `scripts/factory*`.

### Task 8.2 — Unpause + first feature

- [ ] **Step 8.2.1: Unpause factory**

```bash
MSYS_NO_PATHCONV=1 aws ssm put-parameter --name /nova/factory/paused --value false --type String --overwrite
```

- [ ] **Step 8.2.2: Mark Container Platform 01 → "Ready to Build" in Notion**

```bash
export NOTION_API_KEY=$(grep ^NOTION_API_KEY /c/Claude/Nova/nova/.env | cut -d= -f2-)
curl -s -X PATCH "https://api.notion.com/v1/pages/3580930a-bc71-8129-ba24-fe28ee06856d" \
  -H "Authorization: Bearer $NOTION_API_KEY" \
  -H "Notion-Version: 2022-06-28" \
  -H "Content-Type: application/json" \
  -d '{"properties":{"Status":{"select":{"name":"Ready to Build"}}}}'
```

Expected: status returns "Ready to Build". Webhook fires; SFN starts.

- [ ] **Step 8.2.3: Watch the run**

```bash
aws logs tail /aws/lambda/nova-factory-ralph-turn --follow
```

Once SFN reports SUCCEEDED:

- [ ] **Step 8.2.4: Verify the resulting PR**

```bash
gh pr list --repo nabbic/nova --state open --json number,title,files,headRefName | python -m json.tool
```

Expected:
- 1 open PR
- Title: `Container Platform 01: ...`
- `headRefName`: `feature/container-platform-01-...`
- Files: only app/infra paths (Dockerfile, docker-compose.yml, .dockerignore, tests/test_docker.py). NO `.factory/`, NO `feat(factory):` commit prefix.

If anything looks wrong: pause the factory, close the PR, debug, fix in `nova-factory`, redeploy, retry.

### Task 8.3 — Roll the rest of the backlog

- [ ] **Step 8.3.1: Mark Foundation 12 → "Ready to Build"**

```bash
curl -s -X PATCH "https://api.notion.com/v1/pages/3550930a-bc71-811c-8d50-dd3bd62f0713" \
  -H "Authorization: Bearer $NOTION_API_KEY" \
  -H "Notion-Version: 2022-06-28" \
  -H "Content-Type: application/json" \
  -d '{"properties":{"Status":{"select":{"name":"Ready to Build"}}}}'
```

- [ ] **Step 8.3.2: Mark the other "Failed" features back to "Ready to Build" one at a time, watching each run land cleanly**

Features to retry (from earlier query):
- `3580930a-bc71-812c-9cbd-e290fd9e91f4` — Container Platform 03: Terraform ECS Fargate
- `3580930a-bc71-8122-a473-c616720b03f8` — Container Platform 02: Terraform ECR repos
- `3550930a-bc71-81c8-93b7-f9c69f1d6b03` — Foundation 01: Settings, async DB session & /health
- `3580930a-bc71-818c-99ba-c077c37a39a2` — Foundation 11: Terraform RDS PostgreSQL
- `3550930a-bc71-8127-8698-f609f2bae1d0` — Foundation 10: Terraform Cognito user pools

Trigger one at a time; let each PR land before triggering the next, since several have `Depends On` relations.

---

## Self-Review

**Spec coverage:**
- ✅ Empty the app repo: Phase 1
- ✅ Split factory to its own repo: Phases 2–4, 7
- ✅ Factory remains agnostic / parameterized by app repo: Phase 4 (already env-driven), Phase 6 smoke confirms
- ✅ Stop polluting app repo with factory state: Phase 5
- ✅ Reset and rebuild spec'd features: Phase 8
- ✅ No AWS resource recreations: Terraform backend keys preserved (Phase 3.2, 4.7)

**Placeholder scan:** None. Each step has the actual command, expected output, or code edit.

**Type/path consistency:**
- `agent-prompts/` used consistently (Phase 4.2, 4.4.1, 4.5.1, 7.2)
- `lambdas/` used consistently for the new Lambda location (Phase 4.1, 4.6, 5.x, 7.2)
- Terraform module paths `infra/factory/`, `infra/webhook-relay/` consistent throughout
- ECR repo names `nova-factory-ralph-turn`, `nova-factory-validator` consistent (Phase 6.1)
- SSM pause flag `/nova/factory/paused` consistent (Phase 6.3.1, 8.2.1)
- Lambda function names `nova-factory-ralph-turn`, `nova-factory-validate-v2` consistent (Phase 6.1.3)
