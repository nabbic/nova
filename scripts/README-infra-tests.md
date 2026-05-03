# Infrastructure Tests

## Overview

This feature is pure Terraform IaC — no application code, no FastAPI routes, no DB
migrations. Therefore **no pytest tests are required** for this feature.

Terraform correctness is validated via two mechanisms:

## 1. Syntax/Config Validation (CI — no AWS credentials required)

```bash
./scripts/test-infra.sh validate
```

This runs:
1. `terraform init -backend=false` — initialises providers without contacting S3 state backend
2. `terraform validate` — validates HCL syntax and configuration correctness

Expected output: `Success! The configuration is valid.` with exit code 0.

This step runs in every CI pull-request workflow and does NOT require AWS credentials
or the S3 state bucket to exist.

## 2. Plan Dry-Run (staging — requires AWS credentials)

```bash
# 1. Copy the example tfvars and fill in real staging values
cp scripts/staging.tfvars.example scripts/staging.tfvars
# Edit staging.tfvars with real VPC/subnet/SG IDs

# 2. Set sensitive variables via environment
export TF_VAR_db_username="nova_staging_user"
export TF_VAR_db_password="your-secure-password"

# 3. Run the plan assertion
./scripts/test-infra.sh plan-staging
```

This asserts the plan contains exactly:
- 2 × `aws_cognito_user_pool`
- 2 × `aws_cognito_user_pool_client`
- 1 × `aws_db_instance`
- 1 × `aws_db_subnet_group`
- 1 × `aws_security_group`

## Acceptance Criteria Coverage

| Criterion | Verification method |
|---|---|
| `terraform validate` passes | `test-infra.sh validate` |
| Correct resource counts in plan | `test-infra.sh plan-staging` |
| Buyer pool has `custom:role`, `custom:org_id` | Code review of `infra/modules/cognito/main.tf` |
| Buyer client has USER_PASSWORD_AUTH, SRP, REFRESH | Code review of `infra/modules/cognito/main.tf` |
| Token TTLs correct for both pools | Code review of `infra/modules/cognito/main.tf` |
| RDS `db.t3.micro`, `engine=postgres`, `engine_version=16` | Code review + plan output |
| `storage_encrypted=true`, no `kms_key_id` | Code review of `infra/modules/rds/main.tf` |
| `deletion_protection` conditional on production | Code review of `infra/modules/rds/main.tf` |
| SG port 5432 from `app_sg_id` only | Code review of `infra/modules/rds/main.tf` |
| All 6 outputs present | Code review of `infra/outputs.tf` |
| No hardcoded account IDs/ARNs/regions | Code review + `grep` scan |
| All resources tagged | Code review |
| `db_password`, `db_username` sensitive=true, not in outputs | Code review |
| `generate_secret` not set (public clients) | Code review of Cognito module |
