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
