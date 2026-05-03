# Nova Factory Infrastructure

Terraform module for the Nova Software Factory pipeline.

## Relationship to webhook-relay

This is a separate Terraform root from `../webhook-relay/`. The webhook-relay Lambda is updated in Phase 6 to read outputs from this module via `data.terraform_remote_state.factory`.

## Resources

- S3 bucket: `nova-factory-workspaces-<account-id>` — per-execution workspace storage
- DynamoDB `nova-factory-locks` — concurrency locking per feature_id
- DynamoDB `nova-factory-runs` — per-step audit trail
- IAM roles for Lambda and Step Functions execution
