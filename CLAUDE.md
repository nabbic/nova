# Nova — Master Project Context

## Product
Nova is a multi-tenant SaaS web application. Details TBD by product spec.
Target users: TBD.

## Factory
This repository is built and maintained by the Nova Software Factory — an autonomous
multi-agent CI/CD pipeline. Features flow from Notion → GitHub Actions → AWS.
Never manually edit files that agents own unless you update this doc to reflect it.

## Architecture Constraints
- **12-factor methodology** is non-negotiable (https://12factor.net/)
- Config via environment variables only — never hardcoded, never committed
- Secrets via AWS Parameter Store / Secrets Manager
- Stateless processes — no local disk state between requests
- Logs to stdout/stderr only

## API Design — Hard Requirement
**All HTTP API endpoints MUST be built using OpenAPI (OAS 3.x).**
- Backend routes must include full request/response schema decorators
- The factory commits an updated `docs/openapi.json` on every run that touches the API
- No endpoint ships without a machine-readable contract

## AWS Cost Policy
- **Prefer AWS free-tier-eligible resources whenever possible**
- Do not sacrifice correctness or quality to stay in free tier
- If the right resource for a job is not free-tier eligible, flag it explicitly in
  a comment in the Terraform code and in `architecture.json` under `cost_notes`
- The human will review and approve non-free-tier resource choices before they ship
- Free-tier targets: t3.micro/t4g.micro for EC2, db.t3.micro for RDS,
  Lambda (1M requests/month), S3 (5GB), CloudWatch (10 metrics)

## Environments
- **Staging**: Terraform state in S3 at `nova/staging/terraform.tfstate`
- **Production**: Terraform state in S3 at `nova/production/terraform.tfstate`
- Every feature deploys to staging first; production deploy requires staging to pass
- S3 state bucket: `nova-terraform-state-<account-id>` (created by infra bootstrap)
- DynamoDB lock table: `nova-terraform-locks`

## Fixed Baseline Stack
| Layer | Choice |
|---|---|
| Compute | ECS Fargate |
| Database | RDS PostgreSQL |
| Auth | AWS Cognito |
| Edge | Cloudflare (CDN, DNS, WAF) |
| IaC | Terraform |

## Tech Stack Decisions (maintained by Architect agent)
_Starts empty. Architect appends here as decisions are made._

## Coding Conventions
- All code must have tests before merging
- All tests must pass in CI before merging (pytest, ruff, mypy)
- Security Reviewer must pass before any commit lands
- Every Terraform change runs `terraform validate` and `terraform plan` before apply
- Multi-tenancy: all queries must filter by `tenant_id` — row-level security enforced at DB layer
- Backend agent always updates `requirements.txt` when adding new dependencies

## Agent Roles
See `.claude/agents/` for each agent's system prompt.
Orchestrator coordinates all agents. Do not call agents directly.

## Repository Layout
- `app/` — web application
- `infra/` — Terraform modules
- `infra/bootstrap/` — one-time S3/DynamoDB state backend setup
- `scripts/` — factory tooling
- `.claude/agents/` — agent system prompts
- `docs/` — specs and plans
- `docs/openapi.json` — always up to date, committed by factory on API changes
