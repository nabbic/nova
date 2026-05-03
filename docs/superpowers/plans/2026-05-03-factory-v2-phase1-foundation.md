# Factory v2 — Phase 1: Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lay the prerequisite foundation for the Factory v2 rebuild — archive superseded plans, migrate Terraform state to S3, create the canonical schemas/prompts under `.factory/`, and update repo CLAUDE.md to reference the v2 architecture.

**Architecture:** This phase produces no runtime code — it produces durable artifacts (schemas, system prompts, sizing rubric) and infrastructure prerequisites (S3-backed Terraform state, bootstrap module) that every later phase depends on. Each artifact has a unit test or a verification command so the plan ends at a green test boundary.

**Tech Stack:** Terraform 1.7+, AWS (S3, DynamoDB), Python 3.12 + pytest + jsonschema, Markdown.

**Predecessors:** Spec at `docs/superpowers/specs/2026-05-03-factory-rebuild-design.md`. This is **Phase 1 of 6** in the v2 rebuild. Phase 2 (Plan stage), Phase 3 (RalphTurn + Validate + Review + SFN-v2 wiring), Phase 4 (Postdeploy SFN), Phase 5 (Self-pause + observability + budgets), and Phase 6 (Cutover & cleanup) follow.

**Branch:** continue on `factory-overhaul-2026-05-03`. Working directory: `C:\Claude\Nova\nova` (Windows; `/c/Claude/Nova/nova` in the Git Bash shell). AWS account `577638385116`, region `us-east-1`, profile `default`.

**Out of scope for Phase 1:** Any new Lambdas, the v2 state machine, smoke fixtures (Notion-page shape — those land in Phase 2 because that's where they're consumed), deletion of v1 Lambdas/agents (deferred to Phase 6, post-cutover, post-30-day soak).

---

## File Structure

**Create:**

| Path | Responsibility |
|---|---|
| `.factory/prd.schema.json` | JSON Schema (draft 2020-12) for the Plan Lambda's `prd.json` output. Single source of truth — the Plan Lambda (Phase 2), validators, and tests all read from this file. |
| `.factory/feature-sizing-rubric.md` | Human-readable description of the deterministic sizing thresholds (§2.2.1 of spec). Committed so humans writing Notion features can self-size. |
| `.factory/implementer-system.md` | System prompt for the RalphTurn container Lambda (Phase 3). Concatenated with repo `CLAUDE.md` at runtime. |
| `.factory/reviewer-system.md` | System prompt for the Review Lambda (Phase 3). Defines the four review categories (security / tenancy / spec / migration). |
| `tests/factory/__init__.py` | Marks `tests/factory/` as a package. |
| `tests/factory/test_prd_schema.py` | pytest unit tests: schema is a valid JSON Schema; valid fixtures pass; invalid fixture fails. |
| `tests/factory/fixtures/prd_valid_minimal.json` | Smallest valid PRD — one story, one criterion, no blockers. |
| `tests/factory/fixtures/prd_valid_blocked.json` | Valid PRD that has `hard_blockers` populated (the shape PlanGate routes on). |
| `tests/factory/fixtures/prd_invalid_missing_field.json` | Negative fixture — `stories` key omitted. Schema must reject. |
| `tests/requirements.txt` | Test-only Python deps: `pytest`, `jsonschema`. Existing factory Lambdas pull `requirements.txt` from the workspace; tests get their own to avoid polluting runtime image. |
| `infra/bootstrap/main.tf` | One-time bootstrap: creates `nova-terraform-state-<account-id>` S3 bucket (versioned, encrypted, public-blocked) + `nova-terraform-locks` DynamoDB table. State stored locally in this directory only — chicken-and-egg. |
| `infra/bootstrap/variables.tf` | `aws_region`. |
| `infra/bootstrap/outputs.tf` | Bucket name + table name (so other modules can reference them). |
| `infra/bootstrap/README.md` | "Run me once" instructions, why state is local here, how to verify. |
| `.claude/settings.local.json` | Local permission allowlist tuned for v2 dev (terraform, aws CLI, docker, gh, pytest). Per `.gitignore`, `*.local.json` is not committed — but this repo doesn't gitignore it, so it WILL be committed. That's intentional — the team should share v2 dev permissions. |

**Modify:**

| Path | Change |
|---|---|
| `CLAUDE.md` | Rewrite the `## Factory` section (lines 18–28) to describe the v2 pipeline and mark v1 as in-flight cutover. |
| `infra/factory/main.tf` | Add `backend "s3"` block in the `terraform {}` stanza. |
| `infra/webhook-relay/main.tf` | Add `backend "s3"` block; change `data "terraform_remote_state" "factory"` from `backend = "local"` to `backend = "s3"`. |

**Move:**

| From | To |
|---|---|
| `docs/superpowers/plans/2026-05-03-factory-cost-and-robustness-overhaul.md` | `docs/superpowers/plans/archive/` |
| `docs/superpowers/plans/2026-05-03-factory-overhaul-execution-summary.md` | `docs/superpowers/plans/archive/` |
| `docs/superpowers/plans/2026-05-03-factory-stabilization-and-cutover.md` | `docs/superpowers/plans/archive/` |
| `docs/superpowers/plans/2026-05-03-agent-architecture-overhaul.md` | `docs/superpowers/plans/archive/` |

**Do NOT move:** `2026-05-01-platform-foundation.md` is not superseded.

---

## Pre-flight

Before Task 1, the engineer should confirm preconditions. If any fail, stop and ask.

- [ ] **P-1: Verify branch.**

Run: `git -C /c/Claude/Nova/nova rev-parse --abbrev-ref HEAD`
Expected: `factory-overhaul-2026-05-03`

- [ ] **P-2: Verify AWS profile + account.**

Run: `aws sts get-caller-identity --query Account --output text`
Expected: `577638385116`

- [ ] **P-3: Verify Terraform.**

Run: `terraform version`
Expected: `Terraform v1.7.x` or higher.

- [ ] **P-4: Verify the spec is reachable.**

Run: `ls /c/Claude/Nova/nova/docs/superpowers/specs/2026-05-03-factory-rebuild-design.md`
Expected: file exists.

---

### Task 1: Resolve uncommitted in-flight change to `database.md` agent prompt

The branch has one modified file (`scripts/factory_lambdas/agent_prompts/database.md`). It's part of the v1 prompts that Phase 6 will delete entirely, but we still need a clean tree before reorganizing. Decision: review the diff and either commit it as a checkpoint or discard it. Most likely "commit" — the change exists for a reason — but engineer chooses.

**Files:**
- Modify (or discard): `scripts/factory_lambdas/agent_prompts/database.md`

- [ ] **Step 1: Inspect the diff.**

Run: `git -C /c/Claude/Nova/nova diff scripts/factory_lambdas/agent_prompts/database.md`
Expected: a non-empty diff. Engineer reads it and decides intent.

- [ ] **Step 2a (commit path): Commit if intentional.**

Run:
```bash
git -C /c/Claude/Nova/nova add scripts/factory_lambdas/agent_prompts/database.md
git -C /c/Claude/Nova/nova commit -m "wip(factory v1): align database agent prompt before v2 rebuild"
```

- [ ] **Step 2b (discard path): Discard if accidental.**

Run: `git -C /c/Claude/Nova/nova checkout -- scripts/factory_lambdas/agent_prompts/database.md`

- [ ] **Step 3: Verify clean tree.**

Run: `git -C /c/Claude/Nova/nova status`
Expected: `nothing to commit, working tree clean`.

---

### Task 2: Archive superseded v1 plans

Four predecessor plans are superseded by the v2 design spec. Move them under `archive/` so future readers immediately see they're no longer load-bearing. The `archive/` directory already exists but is empty.

**Files:**
- Move: 4 plans listed in the File Structure table above

- [ ] **Step 1: Verify the archive target directory exists.**

Run: `ls -la /c/Claude/Nova/nova/docs/superpowers/plans/archive/`
Expected: directory listing (likely empty).

- [ ] **Step 2: Move the four superseded plans.**

Run:
```bash
cd /c/Claude/Nova/nova
git mv docs/superpowers/plans/2026-05-03-factory-cost-and-robustness-overhaul.md   docs/superpowers/plans/archive/
git mv docs/superpowers/plans/2026-05-03-factory-overhaul-execution-summary.md     docs/superpowers/plans/archive/
git mv docs/superpowers/plans/2026-05-03-factory-stabilization-and-cutover.md      docs/superpowers/plans/archive/
git mv docs/superpowers/plans/2026-05-03-agent-architecture-overhaul.md            docs/superpowers/plans/archive/
```

- [ ] **Step 3: Verify the moves.**

Run: `ls /c/Claude/Nova/nova/docs/superpowers/plans/archive/`
Expected: 4 files listed (the four above). `2026-05-01-platform-foundation.md` and the v2 plans (this file + future phase plans) remain at the top level.

- [ ] **Step 4: Commit.**

```bash
git -C /c/Claude/Nova/nova add docs/superpowers/plans/
git -C /c/Claude/Nova/nova commit -m "docs: archive v1 factory plans superseded by 2026-05-03 v2 design spec"
```

---

### Task 3: Bootstrap the Terraform state backend (S3 + DynamoDB)

Today both `infra/factory/` and `infra/webhook-relay/` keep state locally on the developer's laptop. Spec §6.3 requires migration to S3. We need the bucket + lock table to exist before any other module can reference them, so we create a one-time `infra/bootstrap/` module whose own state lives locally (chicken-and-egg).

The bucket name is `nova-terraform-state-577638385116`, the lock table is `nova-terraform-locks`. CLAUDE.md already references these names.

**Files:**
- Create: `infra/bootstrap/main.tf`
- Create: `infra/bootstrap/variables.tf`
- Create: `infra/bootstrap/outputs.tf`
- Create: `infra/bootstrap/README.md`

- [ ] **Step 1: Create `infra/bootstrap/variables.tf`.**

```hcl
variable "aws_region" {
  description = "AWS region for the Terraform state backend resources."
  type        = string
  default     = "us-east-1"
}
```

- [ ] **Step 2: Create `infra/bootstrap/main.tf`.**

```hcl
terraform {
  required_version = ">= 1.7"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  # State for THIS module is intentionally local (chicken-and-egg with the bucket
  # this module creates). Do not migrate this module to S3.
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

locals {
  bucket_name = "nova-terraform-state-${data.aws_caller_identity.current.account_id}"
  table_name  = "nova-terraform-locks"
  common_tags = {
    Project   = "nova"
    Component = "tf-state-bootstrap"
    ManagedBy = "terraform"
  }
}

resource "aws_s3_bucket" "state" {
  bucket = local.bucket_name
  tags   = local.common_tags
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_dynamodb_table" "locks" {
  name         = local.table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  tags = local.common_tags
}
```

- [ ] **Step 3: Create `infra/bootstrap/outputs.tf`.**

```hcl
output "state_bucket_name" {
  description = "Name of the S3 bucket holding Terraform state for all Nova modules."
  value       = aws_s3_bucket.state.id
}

output "lock_table_name" {
  description = "Name of the DynamoDB table used for Terraform state locking."
  value       = aws_dynamodb_table.locks.name
}

output "aws_region" {
  description = "Region in which the state bucket and lock table live."
  value       = var.aws_region
}
```

- [ ] **Step 4: Create `infra/bootstrap/README.md`.**

```markdown
# Terraform state backend bootstrap

One-time module that provisions the shared Terraform state backend used by all
other Nova modules:

- S3 bucket `nova-terraform-state-<account-id>` (versioned, AES256 encrypted,
  public access blocked)
- DynamoDB table `nova-terraform-locks` (PAY_PER_REQUEST, hash key `LockID`)

## Why state is local here

This module's own state is stored in `terraform.tfstate` in this directory.
That's intentional — we cannot use the bucket as the backend for the module
that creates the bucket. Treat this as bootstrap-only.

## Running

```bash
cd infra/bootstrap
terraform init
terraform apply -auto-approve
```

Re-running the module is idempotent (no-op once resources exist).

## Verifying

```bash
aws s3 ls s3://nova-terraform-state-577638385116/
aws dynamodb describe-table --table-name nova-terraform-locks --query 'Table.TableStatus'
```
```

- [ ] **Step 5: Initialize and apply.**

```bash
cd /c/Claude/Nova/nova/infra/bootstrap
terraform init
terraform apply -auto-approve
```

Expected: `Apply complete! Resources: 5 added, 0 changed, 0 destroyed.` (1 bucket + 3 bucket configs + 1 DDB table.)

- [ ] **Step 6: Verify the bucket and lock table.**

Run:
```bash
aws s3api head-bucket --bucket nova-terraform-state-577638385116
aws dynamodb describe-table --table-name nova-terraform-locks --query 'Table.TableStatus' --output text
```
Expected: head-bucket returns no error (empty stdout, exit 0); describe-table prints `ACTIVE`.

- [ ] **Step 7: Verify versioning + encryption.**

Run:
```bash
aws s3api get-bucket-versioning --bucket nova-terraform-state-577638385116 --query Status --output text
aws s3api get-bucket-encryption --bucket nova-terraform-state-577638385116 --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault.SSEAlgorithm' --output text
```
Expected: `Enabled` and `AES256`.

- [ ] **Step 8: Commit.**

```bash
cd /c/Claude/Nova/nova
git add infra/bootstrap/main.tf infra/bootstrap/variables.tf infra/bootstrap/outputs.tf infra/bootstrap/README.md
git commit -m "infra(bootstrap): add S3+DynamoDB Terraform state backend module"
```

Note: `infra/bootstrap/terraform.tfstate*` MUST stay local — it's already covered by `.gitignore` (`*.tfstate`). Verify with `git status` after the commit; the state file should not appear.

---

### Task 4: Migrate `infra/factory/` state to S3

`infra/factory/main.tf` currently has no `backend` block, so state lives in `infra/factory/terraform.tfstate` on disk. Add the S3 backend block, then `terraform init -migrate-state -force-copy` to push the local state up.

Spec §6.3 mandates this. Memory feedback authorizes auto-approve for factory infra.

**Files:**
- Modify: `infra/factory/main.tf:1-8` (the `terraform {}` block)

- [ ] **Step 1: Read the current `terraform {}` block.**

Run: `head -8 /c/Claude/Nova/nova/infra/factory/main.tf`
Expected output:
```hcl
terraform {
  required_version = ">= 1.7"
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 5.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.0" }
    null    = { source = "hashicorp/null", version = "~> 3.0" }
  }
}
```

- [ ] **Step 2: Insert the `backend "s3"` stanza inside the `terraform {}` block.**

Edit `infra/factory/main.tf` so the block becomes:

```hcl
terraform {
  required_version = ">= 1.7"
  backend "s3" {
    bucket         = "nova-terraform-state-577638385116"
    key            = "factory/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "nova-terraform-locks"
    encrypt        = true
  }
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 5.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.0" }
    null    = { source = "hashicorp/null", version = "~> 3.0" }
  }
}
```

- [ ] **Step 3: Migrate state to S3.**

```bash
cd /c/Claude/Nova/nova/infra/factory
terraform init -migrate-state -force-copy
```

`-force-copy` skips the interactive "Do you want to copy existing state…?" prompt; the user's `feedback_terraform_apply.md` memory authorizes non-interactive operation for factory infra.

Expected: `Successfully configured the backend "s3"! Terraform will automatically use this backend unless the backend configuration changes.`

- [ ] **Step 4: Verify state landed in S3 and is non-empty.**

```bash
aws s3 ls s3://nova-terraform-state-577638385116/factory/
aws s3 cp s3://nova-terraform-state-577638385116/factory/terraform.tfstate - | head -c 200
```
Expected: the `ls` shows `factory/terraform.tfstate`; the head dump shows valid JSON starting `{"version": 4, "terraform_version": ...`.

- [ ] **Step 5: Verify resources still resolve from the new backend.**

```bash
cd /c/Claude/Nova/nova/infra/factory
terraform plan -input=false
```
Expected: `No changes. Your infrastructure matches the configuration.` This proves the migrated state still describes the live resources accurately. If a non-empty plan shows up, **do NOT apply** — investigate first; state migration shouldn't change anything semantically.

- [ ] **Step 6: Remove the now-stale local state files.**

After the S3 migration, Terraform leaves `terraform.tfstate` and `terraform.tfstate.backup` on disk (gitignored, but let's not let them rot and confuse future readers).

```bash
cd /c/Claude/Nova/nova/infra/factory
rm -f terraform.tfstate terraform.tfstate.backup
```

- [ ] **Step 7: Commit.**

```bash
cd /c/Claude/Nova/nova
git add infra/factory/main.tf
git commit -m "infra(factory): migrate Terraform state from local to S3 backend"
```

---

### Task 5: Migrate `infra/webhook-relay/` state to S3 and update its remote_state reference

`infra/webhook-relay/main.tf` keeps its own state locally AND reads the factory state via `data "terraform_remote_state" "factory" { backend = "local" path = "../factory/terraform.tfstate" }`. Both need to flip to S3 — the factory state is no longer at that local path after Task 4.

**Files:**
- Modify: `infra/webhook-relay/main.tf:1-26` (the `terraform {}` block and the `terraform_remote_state` data source)

- [ ] **Step 1: Read the current top of `webhook-relay/main.tf` for context.**

Run: `head -26 /c/Claude/Nova/nova/infra/webhook-relay/main.tf`

- [ ] **Step 2: Add `backend "s3"` to the `terraform {}` block.**

Edit `infra/webhook-relay/main.tf` so the `terraform {}` block becomes:

```hcl
terraform {
  required_version = ">= 1.7"
  backend "s3" {
    bucket         = "nova-terraform-state-577638385116"
    key            = "webhook-relay/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "nova-terraform-locks"
    encrypt        = true
  }
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }
}
```

- [ ] **Step 3: Update the `terraform_remote_state` reference for factory.**

Replace:

```hcl
data "terraform_remote_state" "factory" {
  backend = "local"
  config = {
    path = "${path.module}/../factory/terraform.tfstate"
  }
}
```

With:

```hcl
data "terraform_remote_state" "factory" {
  backend = "s3"
  config = {
    bucket = "nova-terraform-state-577638385116"
    key    = "factory/terraform.tfstate"
    region = "us-east-1"
  }
}
```

- [ ] **Step 4: Migrate webhook-relay state to S3.**

```bash
cd /c/Claude/Nova/nova/infra/webhook-relay
terraform init -migrate-state -force-copy
```
Expected: same `Successfully configured the backend "s3"!` line as Task 4.

- [ ] **Step 5: Verify the plan is empty.**

```bash
cd /c/Claude/Nova/nova/infra/webhook-relay
terraform plan -input=false
```
Expected: `No changes.` Both the migrated state AND the new remote_state lookup must resolve cleanly. If you see plan output suggesting recreation of the relay Lambda or API Gateway, the remote_state reference probably broke a reference — recheck Step 3.

- [ ] **Step 6: Remove stale local state files.**

```bash
cd /c/Claude/Nova/nova/infra/webhook-relay
rm -f terraform.tfstate terraform.tfstate.backup
```

- [ ] **Step 7: Commit.**

```bash
cd /c/Claude/Nova/nova
git add infra/webhook-relay/main.tf
git commit -m "infra(webhook-relay): migrate state to S3 and switch factory remote_state to S3"
```

---

### Task 6: Add a `tests/requirements.txt` for the test-only deps

Tests need `jsonschema` (for §2.2 PRD validation), but we don't want it in the runtime `requirements.txt`. Spec §2.4 references `tests/requirements.txt` as the canonical test-deps file consumed by Phase 3's validate-v2. Establish it now.

**Files:**
- Create: `tests/requirements.txt`

- [ ] **Step 1: Create `tests/requirements.txt`.**

```
pytest>=8.0,<9.0
jsonschema>=4.21,<5.0
```

- [ ] **Step 2: Install deps locally.**

```bash
cd /c/Claude/Nova/nova
pip install -r tests/requirements.txt
```
Expected: pytest and jsonschema install (or report "already satisfied").

- [ ] **Step 3: Smoke-test pytest still finds the existing test.**

Run: `cd /c/Claude/Nova/nova && pytest tests/test_version_endpoint.py -q`
Expected: existing tests pass (or fail for unrelated reasons — note them but don't fix here, that's outside this plan's scope). What we're checking is that pytest is correctly installed and discovers tests.

- [ ] **Step 4: Commit.**

```bash
cd /c/Claude/Nova/nova
git add tests/requirements.txt
git commit -m "tests: pin test-only deps (pytest, jsonschema) in tests/requirements.txt"
```

---

### Task 7: Create the PRD JSON Schema (TDD)

Spec §2.2 defines the canonical PRD shape. We commit `.factory/prd.schema.json` as the single source of truth. Write the test first (TDD), watch it fail with "schema not found," then write the schema, then write fixtures.

**Files:**
- Create: `tests/factory/__init__.py`
- Create: `tests/factory/test_prd_schema.py`
- Create: `.factory/prd.schema.json`
- Create: `tests/factory/fixtures/prd_valid_minimal.json`
- Create: `tests/factory/fixtures/prd_valid_blocked.json`
- Create: `tests/factory/fixtures/prd_invalid_missing_field.json`

- [ ] **Step 1: Create empty `tests/factory/__init__.py`.**

Run: `touch /c/Claude/Nova/nova/tests/factory/__init__.py`

- [ ] **Step 2: Write the failing schema validation test.**

Create `tests/factory/test_prd_schema.py`:

```python
"""Validates that .factory/prd.schema.json is correct and that fixtures
round-trip against it. The schema is the contract every later phase relies on
(Plan Lambda emits prd.json; RalphTurn reads it; Validate / Review consume it)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / ".factory" / "prd.schema.json"
FIXTURES = Path(__file__).parent / "fixtures"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_schema_file_exists():
    assert SCHEMA_PATH.is_file(), f"missing PRD schema at {SCHEMA_PATH}"


def test_schema_is_valid_jsonschema():
    schema = _load_json(SCHEMA_PATH)
    # Will raise SchemaError if the schema itself is malformed.
    Draft202012Validator.check_schema(schema)


def test_minimal_valid_prd_passes():
    schema = _load_json(SCHEMA_PATH)
    fixture = _load_json(FIXTURES / "prd_valid_minimal.json")
    Draft202012Validator(schema).validate(fixture)


def test_blocked_valid_prd_passes():
    """A PRD with hard_blockers populated (the shape PlanGate routes on)
    must still validate as a structurally well-formed PRD."""
    schema = _load_json(SCHEMA_PATH)
    fixture = _load_json(FIXTURES / "prd_valid_blocked.json")
    Draft202012Validator(schema).validate(fixture)


def test_invalid_prd_is_rejected():
    schema = _load_json(SCHEMA_PATH)
    fixture = _load_json(FIXTURES / "prd_invalid_missing_field.json")
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(fixture)
```

- [ ] **Step 3: Run the tests and verify ALL fail.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/test_prd_schema.py -v
```
Expected: 4 tests, all fail (FileNotFoundError / missing schema). This is correct — we haven't written the schema or fixtures yet.

- [ ] **Step 4: Write the PRD schema.**

Create `.factory/prd.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://nova.factory/prd.schema.json",
  "title": "Nova Factory PRD",
  "description": "Schema for prd.json — the structured product spec emitted by the Plan Lambda. Single source of truth consumed by RalphTurn, Validate, Review, and the postdeploy probe.",
  "type": "object",
  "required": [
    "feature_id",
    "title",
    "narrative_md",
    "stories",
    "scope",
    "hard_blockers",
    "risk_flags",
    "suggested_split"
  ],
  "additionalProperties": false,
  "properties": {
    "feature_id": {
      "type": "string",
      "minLength": 1,
      "description": "Notion page UUID."
    },
    "title": {
      "type": "string",
      "minLength": 1
    },
    "narrative_md": {
      "type": "string",
      "description": "The full Notion body, markdown."
    },
    "stories": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": ["id", "description", "acceptance_criteria", "passes"],
        "additionalProperties": false,
        "properties": {
          "id": {
            "type": "string",
            "pattern": "^s[1-9][0-9]*$"
          },
          "description": {
            "type": "string",
            "minLength": 1
          },
          "acceptance_criteria": {
            "type": "array",
            "minItems": 1,
            "items": {
              "type": "string",
              "minLength": 1
            }
          },
          "passes": {
            "type": "boolean"
          }
        }
      }
    },
    "scope": {
      "type": "object",
      "required": ["touches_db", "touches_frontend", "touches_infra", "files_in_scope"],
      "additionalProperties": false,
      "properties": {
        "touches_db":       { "type": "boolean" },
        "touches_frontend": { "type": "boolean" },
        "touches_infra":    { "type": "boolean" },
        "files_in_scope": {
          "type": "array",
          "items": { "type": "string", "minLength": 1 }
        }
      }
    },
    "hard_blockers": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["reason"],
        "additionalProperties": false,
        "properties": {
          "reason": {
            "type": "string",
            "enum": [
              "feature_too_large",
              "non_free_tier_resource_unconfirmed",
              "ambiguous_requirements"
            ]
          },
          "details": { "type": "string" },
          "suggested_split": {
            "type": "array",
            "items": { "type": "string", "minLength": 1 }
          }
        }
      }
    },
    "risk_flags": {
      "type": "array",
      "items": { "type": "string", "minLength": 1 }
    },
    "suggested_split": {
      "type": "array",
      "items": { "type": "string", "minLength": 1 },
      "description": "Populated only when sizing rubric is breached. Each entry is a one-line description of a sub-feature the human should re-file as Ready-to-Build."
    }
  }
}
```

- [ ] **Step 5: Write the minimal valid fixture.**

Create `tests/factory/fixtures/prd_valid_minimal.json`:

```json
{
  "feature_id": "00000000-0000-0000-0000-000000000001",
  "title": "Add buyer engagement export endpoint",
  "narrative_md": "Buyers need a JSON export of an engagement's findings.",
  "stories": [
    {
      "id": "s1",
      "description": "GET /api/engagements/{id}/export returns the engagement as JSON",
      "acceptance_criteria": [
        "Returns 200 with engagement data when authenticated as the owning buyer org",
        "Returns 403 on buyer_org_id mismatch"
      ],
      "passes": false
    }
  ],
  "scope": {
    "touches_db":       false,
    "touches_frontend": false,
    "touches_infra":    false,
    "files_in_scope":   ["app/", "tests/", "docs/openapi.json"]
  },
  "hard_blockers":   [],
  "risk_flags":      [],
  "suggested_split": []
}
```

- [ ] **Step 6: Write the blocked-but-valid fixture.**

Create `tests/factory/fixtures/prd_valid_blocked.json`:

```json
{
  "feature_id": "00000000-0000-0000-0000-000000000002",
  "title": "Build the entire seller portal",
  "narrative_md": "Seller portal: invitations, connectors, dashboard, billing, reports.",
  "stories": [
    { "id": "s1", "description": "Seller invitation flow",     "acceptance_criteria": ["Invite email sent", "Token verified"], "passes": false },
    { "id": "s2", "description": "Cloud connector wiring",     "acceptance_criteria": ["AWS connector OK", "GCP connector OK"], "passes": false },
    { "id": "s3", "description": "Seller dashboard UI",        "acceptance_criteria": ["Lists engagements", "Shows status"], "passes": false },
    { "id": "s4", "description": "Billing surface for sellers", "acceptance_criteria": ["Shows invoices"], "passes": false },
    { "id": "s5", "description": "Per-engagement reports",     "acceptance_criteria": ["Renders findings"], "passes": false }
  ],
  "scope": {
    "touches_db":       true,
    "touches_frontend": true,
    "touches_infra":    true,
    "files_in_scope":   ["app/", "frontend/", "infra/", "tests/"]
  },
  "hard_blockers": [
    {
      "reason":  "feature_too_large",
      "details": "5 stories, 4 domains touched (db+frontend+backend+infra) — breaches sizing rubric",
      "suggested_split": [
        "Seller invitation flow (auth + email)",
        "Cloud connector wiring (one connector per feature)",
        "Seller dashboard UI",
        "Billing surface",
        "Per-engagement reports"
      ]
    }
  ],
  "risk_flags": ["multi-domain", "high-token-output-risk"],
  "suggested_split": [
    "Seller invitation flow",
    "Cloud connector wiring",
    "Seller dashboard UI",
    "Billing surface",
    "Per-engagement reports"
  ]
}
```

- [ ] **Step 7: Write the invalid fixture.**

Create `tests/factory/fixtures/prd_invalid_missing_field.json`:

```json
{
  "feature_id": "00000000-0000-0000-0000-000000000003",
  "title": "Broken PRD missing stories",
  "narrative_md": "This PRD intentionally omits the required `stories` field.",
  "scope": {
    "touches_db":       false,
    "touches_frontend": false,
    "touches_infra":    false,
    "files_in_scope":   []
  },
  "hard_blockers":   [],
  "risk_flags":      [],
  "suggested_split": []
}
```

- [ ] **Step 8: Run the tests and verify ALL pass.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/test_prd_schema.py -v
```
Expected: 5 tests pass:
```
tests/factory/test_prd_schema.py::test_schema_file_exists PASSED
tests/factory/test_prd_schema.py::test_schema_is_valid_jsonschema PASSED
tests/factory/test_prd_schema.py::test_minimal_valid_prd_passes PASSED
tests/factory/test_prd_schema.py::test_blocked_valid_prd_passes PASSED
tests/factory/test_prd_schema.py::test_invalid_prd_is_rejected PASSED
```

- [ ] **Step 9: Commit.**

```bash
cd /c/Claude/Nova/nova
git add .factory/prd.schema.json tests/factory/
git commit -m "factory(v2): add prd.schema.json + fixtures + schema validation tests"
```

---

### Task 8: Write `feature-sizing-rubric.md`

Spec §2.2.1 defines a deterministic rubric the Plan Lambda enforces. Committing the rubric in the repo lets humans writing Notion features self-size before the factory rejects them. No code change — just the doc.

**Files:**
- Create: `.factory/feature-sizing-rubric.md`

- [ ] **Step 1: Write `.factory/feature-sizing-rubric.md`.**

```markdown
# Feature sizing rubric

The factory's Plan stage runs a deterministic check against this rubric after
Haiku produces the structured PRD. Any **hard breach** routes the feature to
`MarkBlocked` in Notion with a suggested decomposition. Use this rubric when
writing a feature in Notion to self-size before submitting.

## Hard limits (any breach blocks)

| Threshold | Limit | Rationale |
|---|---|---|
| Total stories                                      | ≤ 4   | At a 6-Ralph-turn cap, 4 stories ≈ 1.5 turns/story |
| Total acceptance criteria (sum across stories)     | ≤ 12  | Tracks token-output budget reliably |
| Distinct scope domains (`db` / `backend` / `frontend` / `infra`) | ≤ 2 | Multi-domain features are nearly always too big |

## Soft signals (raise a `risk_flag`, may contribute to a hard block if extreme)

| Signal | Soft threshold | Hard threshold |
|---|---|---|
| Haiku-estimated files changed | > 15 | > 25 |
| Touches `app/db/migrations/` | always raise `migration` flag | — |
| Mentions OAuth, IAM cross-account, or webhook signing | always raise `auth` flag | — |

## Self-sizing tips

- **One verb per story.** "Buyers can export an engagement" — not "Buyers can
  export, edit, and re-import."
- **Acceptance criteria are observable, not implementation steps.** Bad:
  "Adds an `engagement_exports` table." Good: "GET /api/engagements/{id}/export
  returns 200 with the engagement payload for the owner buyer org."
- **Multi-domain features almost always split cleanly.** A typical bad shape
  is "ship the report PDF" — that's backend (rendering), frontend (download
  link), infra (S3 + CloudFront for the PDFs), db (a `reports` table). Each
  is its own feature; ship them in dependency order.

## What happens when a feature is blocked

The factory posts a structured Notion comment listing the breach and a
suggested decomposition (one bullet per sub-feature). You re-file each as a
fresh `Ready to Build` feature. The factory does not auto-create the children —
that's a deliberate human checkpoint.
```

- [ ] **Step 2: Verify the file is non-empty.**

Run: `wc -l /c/Claude/Nova/nova/.factory/feature-sizing-rubric.md`
Expected: at least 30 lines.

- [ ] **Step 3: Commit.**

```bash
cd /c/Claude/Nova/nova
git add .factory/feature-sizing-rubric.md
git commit -m "factory(v2): add feature-sizing-rubric.md (human-readable Plan-stage rubric)"
```

---

### Task 9: Write `implementer-system.md` (RalphTurn system prompt)

Spec §2.3.2: the RalphTurn Lambda concatenates repo `CLAUDE.md` with `.factory/implementer-system.md` as its system prompt and invokes `claude -p` against the materialized workspace. This is the load-bearing prompt for everything Phase 3 does.

**Files:**
- Create: `.factory/implementer-system.md`

- [ ] **Step 1: Write `.factory/implementer-system.md`.**

```markdown
# Nova Factory — Implementer (Ralph Turn) System Prompt

You are the implementer agent inside the Nova Factory. You are running in a
**Lambda container** with `claude -p --dangerously-skip-permissions` against
a materialized git workspace at `/tmp/ws`. You see the workspace, the PRD, a
running progress log, and (sometimes) a repair-context file. The orchestrator
runs you for **one turn at a time** — at the end of each turn the workspace is
re-uploaded, validators run, and a fresh you is invoked next turn against the
new state. Anything you want future-you to remember must be in the workspace
or git history.

## What you read each turn

- `prd.json` — the structured spec. The single source of truth for what to build.
- `progress.txt` — a running log of which stories were touched in prior turns
  and what is outstanding. Append, do not overwrite.
- `repair_context.md` (if present) — validator/reviewer issues from the
  previous turn. Address these first; if the file is present you are in a
  repair cycle, not a fresh build.
- `CLAUDE.md` and any agent docs in the repo. The repo's coding conventions
  override your defaults.

## What you must do each turn

1. Read `prd.json`, `progress.txt`, and `repair_context.md` (if present) FIRST,
   before touching any code.
2. Pick the smallest next story (or repair item) that can plausibly close in
   one turn. Do NOT try to close every story in a single turn — you have up to
   6 turns budgeted for this feature.
3. Write tests first when adding new behavior (TDD). Run them. Make them pass.
4. Commit incrementally inside the workspace via `git add` + `git commit`.
   Use clear commit messages — the orchestrator preserves git history across
   turns and reviewers can read it.
5. Update `progress.txt` at the end of the turn:
   - Append a section dated with the current turn number
   - List the stories you closed (set their `passes: true` in `prd.json` if
     all their acceptance criteria are demonstrably met)
   - List what is still outstanding
6. Touch `prd.json` only to flip `passes` from `false` to `true` on stories
   whose acceptance criteria are now verifiably met. Do not edit any other
   field of `prd.json`.
7. When ALL stories have `passes: true` (or you are otherwise done), create
   the file `.factory/_DONE_` (empty contents are fine — presence is the
   signal). Do this only when the entire feature is complete.

## What you must NOT do

- **Do not edit anything outside the project sandbox.** The orchestrator
  enforces a filesystem allowlist after your turn — anything you wrote under
  `.github/workflows/`, `.factory/` (except the literal `.factory/_DONE_`
  sentinel), `infra/factory/`, or any path containing `..` or absolute paths
  will be REJECTED and surfaced back as `DENIED:` lines in `repair_context.md`
  next turn. You will waste a turn this way.
- **Do not edit `prd.json` beyond flipping `passes` booleans.** If the spec
  is wrong, write the disagreement into `progress.txt` and let the human
  re-file the feature.
- **Do not skip tests** because "the change is small." Every behavior change
  needs at least one new or modified test. Tests not added at this stage will
  block the Validate stage and consume one of your remaining turns repairing.
- **Do not invent endpoints, tables, or schema fields not in the PRD.** If
  the PRD is ambiguous, narrate the ambiguity in `progress.txt` and pick the
  simplest path. The reviewer will flag the gap if it matters.
- **Do not touch CI configuration** (`.github/workflows/*`). The factory's
  GitHub PAT cannot push workflow changes — your edits will be discarded.
- **Do not log secrets.** No tokens or keys should appear in `progress.txt`,
  commit messages, or test output. The repo `CLAUDE.md` "Secrets Strategy"
  section is non-negotiable.

## Idempotency and re-runs

A single turn may be re-invoked if the previous one timed out at the 14-minute
Lambda cap. Treat your work as idempotent — running it twice should not break
the workspace. Use `git status` and `git log --oneline -10` early in each
turn to ground yourself in what exists.

## Done signal

You have two ways to signal "feature done":

1. Every story in `prd.json` has `passes: true`.
2. You explicitly create `.factory/_DONE_` (the orchestrator treats this as
   completion regardless of `passes` state).

Use `.factory/_DONE_` for the final turn of a feature you believe is complete;
the orchestrator runs Validate and Review next, and either passes the feature
through to PR or routes back to you with `repair_context.md`.
```

- [ ] **Step 2: Verify the file is non-empty and well-formed markdown.**

Run: `wc -l /c/Claude/Nova/nova/.factory/implementer-system.md`
Expected: ≥ 60 lines.

- [ ] **Step 3: Commit.**

```bash
cd /c/Claude/Nova/nova
git add .factory/implementer-system.md
git commit -m "factory(v2): add implementer-system.md (RalphTurn system prompt)"
```

---

### Task 10: Write `reviewer-system.md` (Review Lambda system prompt)

Spec §2.5: a single Sonnet 4.6 call evaluates four categories (security / tenancy / spec / migration) and emits a structured JSON object. The system prompt encodes the categories, the JSON contract, and the heuristics.

**Files:**
- Create: `.factory/reviewer-system.md`

- [ ] **Step 1: Write `.factory/reviewer-system.md`.**

```markdown
# Nova Factory — Reviewer System Prompt

You are the **Reviewer** in the Nova Factory pipeline. You are invoked once
per feature, after the implementer has produced a green test suite and
Validate has passed. You see the feature's PRD, the diff against `main`, and
the repo `CLAUDE.md`. You DO NOT see the implementer's reasoning or
intermediate work — only the final diff.

Your output is a single JSON object that the orchestrator schema-validates.
You return blockers and warnings; the orchestrator decides whether to route
back to the implementer for repair or to PR. Be precise; every blocker turns
into one Ralph turn the factory has to spend.

## What you receive

- `prd.json` — the structured spec the feature was built against.
- `git_diff` — `git diff main..HEAD` for the feature branch, capped at 50KB.
  If truncation marker `<diff truncated at 50KB>` appears, focus your review on
  what's visible and flag the truncation as a `warning`.
- `CLAUDE.md` — the repo's coding conventions, secrets strategy, multi-tenancy
  rules, container strategy, and AWS cost policy.

## What you check (four categories, in order of severity)

### 1. Security (always check)

- **Hardcoded secrets** — API keys, tokens, DB passwords in source. Always a
  blocker.
- **Missing auth** — new HTTP endpoints without an auth dependency. Blocker
  unless the endpoint is `/health` or explicitly `public_endpoint=True` in the
  PRD.
- **IAM over-privilege** — Terraform IAM policies with `*:*`, broad resource
  ARNs, or `iam:*`. Blocker.
- **Injection** — raw SQL string concatenation, unparameterized template
  rendering, `eval`/`exec` on user input. Blocker.
- **Logged secrets** — `LOG.info(token)`, `print(api_key)`. Blocker.

### 2. Tenancy / Row-Level Security (always check)

Every database query in `app/repositories/` MUST filter by `buyer_org_id`. The
seller path is an exception only when the query is scoped to a single
`engagement_id` AND the engagement table itself filters by `buyer_org_id`
upstream.

- **Missing `WHERE buyer_org_id = :buyer_org_id`** on a query that touches a
  buyer-tenanted table. Blocker.
- **Cross-tenant joins** — joining across two tables without applying the
  tenant filter to the joined-in side. Blocker.
- **API endpoint that returns rows without applying the auth-context tenant
  filter.** Blocker.

### 3. Spec compliance (always check)

For each story in the PRD:
- Is there a code change demonstrably implementing it?
- Is there at least one test asserting the corresponding acceptance criterion?
- If not, the story is a blocker (`category: spec`).

### 4. Migration safety (only if `app/db/migrations/` changed)

- New `NOT NULL` columns must have a backfill default OR the table must be
  empty (verify the migration script handles existing rows). Blocker.
- New tables must declare RLS policies as part of the migration. Blocker.
- `DROP COLUMN` / `DROP TABLE` on tables with > 0 rows in production. Blocker.
- Long-running operations on hot tables (rebuilding indexes inline,
  uncondtional `UPDATE`). Warning unless the migration is gated behind a
  no-traffic window.
- Reversibility — every migration must define a `downgrade` path. Warning if
  irreversible (occasionally legitimate; flag for human review).

## Output format

Return ONLY a JSON object matching this schema (no prose around it, no code
fences). The orchestrator parses your stdout as JSON.

```json
{
  "passed": false,
  "blockers": [
    {
      "category": "tenancy",
      "file": "app/repositories/engagement.py",
      "line": 42,
      "description": "list_engagements does not filter by buyer_org_id",
      "fix": "Add WHERE buyer_org_id = :buyer_org_id to the query"
    }
  ],
  "warnings": [
    {
      "category": "migration",
      "file": "app/db/migrations/20260503_add_export.py",
      "line": 17,
      "description": "Migration is irreversible (no downgrade); confirm with human before merge"
    }
  ]
}
```

- `passed` MUST be `false` if `blockers` is non-empty; otherwise `true`.
- `category` ∈ `{security, tenancy, spec, migration}`.
- `file` and `line` reference paths inside the diff; if you can't pin a
  specific line, omit `line` (do NOT guess).
- `fix` should be a one-sentence remediation the implementer can act on in
  one Ralph turn. If you can't write a one-sentence fix, the issue may be
  bigger than this feature — file it as a `warning` instead and let the
  human triage.

## Heuristics for staying useful

- **Read the diff first, then the PRD.** Many false positives come from
  reviewing in spec-first mode and inventing concerns the diff doesn't
  warrant.
- **Don't flag style.** ruff and mypy already ran. If you find yourself
  about to write "use snake_case here," stop.
- **Don't flag missing tests for dead lines** (e.g., `__repr__`, simple
  property accessors). The implementer's TDD already covered the behavior.
- **Don't flag the absence of an OpenAPI update** if `docs/openapi.json` was
  modified in the diff. Confirm the diff matches the new endpoints; if it
  doesn't, that's a `spec` blocker.
- **Be terse.** Each blocker description should fit on one line. The fix
  should fit on one line. Long descriptions cost the implementer turn time.
```

- [ ] **Step 2: Verify the file is non-empty.**

Run: `wc -l /c/Claude/Nova/nova/.factory/reviewer-system.md`
Expected: ≥ 80 lines.

- [ ] **Step 3: Commit.**

```bash
cd /c/Claude/Nova/nova
git add .factory/reviewer-system.md
git commit -m "factory(v2): add reviewer-system.md (Review Lambda system prompt)"
```

---

### Task 11: Update repo `CLAUDE.md` Factory section to reference v2

The current `## Factory` section (lines 18–28) describes the v1 architecture. We rewrite it to describe v2 while marking that v1 is still the production-routed path until cutover (Phase 6). The pipeline diagram, key resources, and references to `.factory/` artifacts are added.

**Files:**
- Modify: `CLAUDE.md:18-28` (the `## Factory` section)

- [ ] **Step 1: Read the current Factory section to confirm boundaries.**

Run: `sed -n '18,32p' /c/Claude/Nova/nova/CLAUDE.md`
Expected output starts with `## Factory` at line 18 and ends with the line `Never manually edit files that agents own unless you update this doc to reflect it.`

- [ ] **Step 2: Replace the Factory section.**

Use `Edit` to replace the block from `## Factory` through `Never manually edit files that agents own unless you update this doc to reflect it.` with:

```markdown
## Factory
This repository is built and maintained by the **Nova Software Factory v2** —
a deterministic Step Functions orchestrator that drives three LLM stages
(Plan → Implement → Review) plus a deterministic Validate stage. The factory
is described in detail in
`docs/superpowers/specs/2026-05-03-factory-rebuild-design.md`.

**Pipeline (v2):**
Notion → Webhook Lambda → Step Functions `nova-factory-v2` → Plan (Haiku)
→ PlanGate → RalphLoop (≤ 6 turns of Sonnet, container Lambda) → Validate
(deterministic ruff/mypy/pytest/tf/tsc) → Review (Sonnet) → CommitAndPush →
OpenPR → quality-gates.yml → MarkDone. A separate state machine
`nova-factory-postdeploy` probes staging after each merge and can revert.

**Cutover status:** v2 is being built in parallel with v1. The webhook still
routes to the legacy `nova-factory-pipeline` until Phase 6 of the rebuild
flips `FACTORY_BACKEND="step-functions-v2"`. The legacy `factory.yml`
GitHub Actions workflow remains as emergency fallback and is removed 30 days
after stable v2 cutover.

**Canonical factory artifacts** (committed to this repo):

| Path | Purpose |
|---|---|
| `.factory/prd.schema.json`             | JSON Schema for the structured PRD emitted by Plan and consumed by every later stage. |
| `.factory/feature-sizing-rubric.md`    | Deterministic sizing rubric Plan enforces — humans use it to self-size before filing. |
| `.factory/implementer-system.md`       | System prompt RalphTurn concatenates with this CLAUDE.md when invoking `claude -p`. |
| `.factory/reviewer-system.md`          | System prompt Review uses; encodes the four review categories and the JSON contract. |
| `tests/factory/`                        | Unit tests for the schemas and (Phase 2+) the factory Lambdas. |

**Sandbox boundaries:** RalphTurn writes only to its execution's S3 prefix
and the Lambda-local `/tmp/ws`. Anything it tries to write under
`.github/workflows/`, `.factory/` (except the `.factory/_DONE_` completion
sentinel), `infra/factory/`, or any path containing `..` or absolute paths is
DENIED at upload time and surfaced back as `DENIED:` lines in
`repair_context.md` for the next turn. The factory's GitHub PAT is
fine-grained, single-repo, `contents:write` + `pull_requests:write` only —
no `workflow` scope, no admin.

Never manually edit files that the factory owns unless you update this doc
and the relevant `.factory/*` prompt to reflect it.
```

- [ ] **Step 3: Verify the section is well-placed and the rest of the file is intact.**

Run: `head -55 /c/Claude/Nova/nova/CLAUDE.md` and confirm the Secrets Strategy section that previously followed Factory still appears below.

- [ ] **Step 4: Commit.**

```bash
cd /c/Claude/Nova/nova
git add CLAUDE.md
git commit -m "docs(claude.md): rewrite Factory section for v2 architecture (cutover in flight)"
```

---

### Task 12: Add `.claude/settings.local.json` for v2 dev workflow

Spec §6.4: the v2 development workflow needs additional permission allowlist entries (terraform, aws CLI, docker, gh, pytest) so the engineer doing the rebuild work isn't prompted on every tool call. The repo's `.claude/settings.json` already has the v1-era basics; we add a non-overlapping local file with v2-specific permissions.

**Files:**
- Create: `.claude/settings.local.json`

- [ ] **Step 1: Confirm `.claude/settings.local.json` does not exist.**

Run: `ls /c/Claude/Nova/nova/.claude/settings.local.json 2>&1`
Expected: `cannot access`. (If it exists, stop and read it — merge instead of clobber.)

- [ ] **Step 2: Create the file.**

```json
{
  "permissions": {
    "allow": [
      "Bash(aws stepfunctions *)",
      "Bash(aws lambda *)",
      "Bash(aws logs *)",
      "Bash(aws s3 *)",
      "Bash(aws s3api *)",
      "Bash(aws s3 cp *)",
      "Bash(aws s3 ls *)",
      "Bash(aws dynamodb *)",
      "Bash(aws ssm *)",
      "Bash(aws secretsmanager *)",
      "Bash(aws cloudwatch *)",
      "Bash(aws sts *)",
      "Bash(aws ecr *)",
      "Bash(aws events *)",
      "Bash(aws iam get-* *)",
      "Bash(aws iam list-* *)",
      "Bash(terraform *)",
      "Bash(docker build *)",
      "Bash(docker push *)",
      "Bash(docker tag *)",
      "Bash(docker images *)",
      "Bash(docker run *)",
      "Bash(docker login *)",
      "Bash(gh pr *)",
      "Bash(gh run *)",
      "Bash(gh workflow *)",
      "Bash(gh release *)",
      "Bash(pytest *)",
      "Bash(ruff *)",
      "Bash(mypy *)",
      "Bash(jq *)",
      "Bash(wc *)",
      "Bash(head *)",
      "Bash(tail *)",
      "Bash(diff *)",
      "Bash(sed *)"
    ]
  }
}
```

- [ ] **Step 3: Verify the JSON is well-formed.**

Run: `python -c "import json; json.load(open('/c/Claude/Nova/nova/.claude/settings.local.json'))"`
Expected: no output, exit 0.

- [ ] **Step 4: Commit.**

```bash
cd /c/Claude/Nova/nova
git add .claude/settings.local.json
git commit -m "chore(claude): add v2 dev permission allowlist in settings.local.json"
```

Note: this file is committed (not gitignored). The factory's own RalphTurn
container Lambda runs `claude -p --dangerously-skip-permissions` — its IAM
role is the security boundary, not this file.

---

### Task 13: Final verification

Sanity-check every artifact exists, every test passes, and Terraform plans are clean. This is the green-test boundary that lets us hand off to Phase 2.

- [ ] **Step 1: Verify all `.factory/` artifacts exist.**

Run:
```bash
ls -la /c/Claude/Nova/nova/.factory/
```
Expected: 4 files — `prd.schema.json`, `feature-sizing-rubric.md`, `implementer-system.md`, `reviewer-system.md`.

- [ ] **Step 2: Verify the v1 plans are archived.**

Run:
```bash
ls /c/Claude/Nova/nova/docs/superpowers/plans/archive/
```
Expected: 4 files (the four superseded plans).

- [ ] **Step 3: Run the schema test suite.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/ -v
```
Expected: 5 tests pass (`test_schema_file_exists`, `test_schema_is_valid_jsonschema`, `test_minimal_valid_prd_passes`, `test_blocked_valid_prd_passes`, `test_invalid_prd_is_rejected`).

- [ ] **Step 4: Verify Terraform state is in S3 for both factory and webhook-relay.**

```bash
aws s3 ls s3://nova-terraform-state-577638385116/factory/
aws s3 ls s3://nova-terraform-state-577638385116/webhook-relay/
```
Expected: each prints `terraform.tfstate` of non-zero size.

- [ ] **Step 5: Verify both modules plan clean.**

```bash
cd /c/Claude/Nova/nova/infra/factory && terraform plan -input=false | tail -3
cd /c/Claude/Nova/nova/infra/webhook-relay && terraform plan -input=false | tail -3
```
Expected: each prints `No changes. Your infrastructure matches the configuration.`

- [ ] **Step 6: Verify no stale local state files remain in factory or webhook-relay.**

```bash
ls /c/Claude/Nova/nova/infra/factory/terraform.tfstate* 2>&1
ls /c/Claude/Nova/nova/infra/webhook-relay/terraform.tfstate* 2>&1
```
Expected: both `cannot access`. (Bootstrap module's local state is fine — it lives at `infra/bootstrap/terraform.tfstate*` and is gitignored.)

- [ ] **Step 7: Verify the working tree is clean.**

```bash
git -C /c/Claude/Nova/nova status
```
Expected: `nothing to commit, working tree clean`.

- [ ] **Step 8: Verify commit count for the phase.**

```bash
git -C /c/Claude/Nova/nova log --oneline factory-overhaul-2026-05-03 --not main | head -20
```
Expected: 11–12 fresh commits on top of `main`, one per task that produced changes (Tasks 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12 — Task 1 produces 0 or 1 commits depending on the commit/discard path; Task 13 produces 0).

- [ ] **Step 9: Push the branch.**

```bash
git -C /c/Claude/Nova/nova push -u origin factory-overhaul-2026-05-03
```
Expected: branch pushed; if it already exists upstream, this fast-forwards.

---

## Phase 1 acceptance criteria recap

The phase is **DONE** when all of these hold:

1. `git status` is clean on `factory-overhaul-2026-05-03`.
2. The four superseded v1 plans are under `docs/superpowers/plans/archive/`.
3. `infra/bootstrap/` exists and has been applied; the S3 bucket
   `nova-terraform-state-577638385116` and DDB table `nova-terraform-locks`
   exist and are healthy.
4. `infra/factory/` and `infra/webhook-relay/` have S3 backends; `terraform
   plan` is clean for both.
5. `.factory/prd.schema.json`, `.factory/feature-sizing-rubric.md`,
   `.factory/implementer-system.md`, `.factory/reviewer-system.md` all exist
   and are non-empty.
6. `pytest tests/factory/ -v` passes 5/5.
7. `CLAUDE.md` `## Factory` section describes v2 with the cutover-in-flight
   note.
8. `.claude/settings.local.json` exists and is valid JSON.

---

## What Phase 2 will do

Phase 2 ("Plan stage end-to-end") will create:

- `LoadFeature` Lambda — Notion → `intake/spec_raw.md` + `intake/feature_meta.json`.
- `Plan` Lambda — Haiku call against the spec + repo CLAUDE.md, emits `prd.json`
  validated against the schema we wrote in Task 7 of this plan.
- The deterministic sizing-rubric implementation that produces `hard_blockers`.
- `MarkBlocked` Lambda + Notion comment formatter.
- A stub state machine `nova-factory-v2-planonly` that runs LoadFeature → Plan →
  PlanGate → MarkBlocked-or-end. The full Ralph + Validate + Review wiring lands
  in Phase 3.
- Smoke fixtures `scripts/factory_smoke_fixtures/{trivial,medium,oversized}.json`
  driven through the stub state machine, asserting `oversized` is blocked.

That phase consumes everything Phase 1 produced — schemas, prompts, S3 state
backend, and the `.claude/settings.local.json` allowlist.
