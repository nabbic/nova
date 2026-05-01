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
- Security Reviewer must pass before any commit lands
- Every Terraform change runs `terraform validate` and `terraform plan` before apply
- Multi-tenancy: all queries must filter by `tenant_id` — row-level security enforced at DB layer

## Agent Roles
See `.claude/agents/` for each agent's system prompt.
Orchestrator coordinates all agents. Do not call agents directly.

## Repository Layout
- `app/` — web application
- `infra/` — Terraform modules
- `scripts/` — factory tooling
- `.claude/agents/` — agent system prompts
- `docs/` — specs and plans
