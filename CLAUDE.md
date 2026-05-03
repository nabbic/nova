# Nova — Master Project Context

## Product
Nova is a **Technical Due Diligence (Tech DD) Platform** for PE M&A transactions.

It is a neutral SaaS platform that sits between buyers (PE firms) and sellers (target
companies), automating technical diligence gathering, AI-powered analysis, and report
generation. The platform is paid for by the buyer; the seller connects their tooling
via cloud connectors and is guided through the process.

**Target users:**
- **Buyers** — PE firm deal teams; see curated findings and risk-scored reports
- **External Advisors** — independent technical advisors engaged per-deal; see raw
  scan data and annotate findings
- **Sellers** — target company engineering teams; connect tooling, respond to
  questionnaires, manage their data per-engagement

## Factory
This repository is built and maintained by the Nova Software Factory — an autonomous
multi-agent CI/CD pipeline. Features flow from Notion → GitHub Actions → AWS.
Never manually edit files that agents own unless you update this doc to reflect it.

## Secrets Strategy — Hard Requirement
All secrets follow a strict tiering. Violations will be caught by the Security Reviewer and block the build.

| Where secret lives | What goes here |
|---|---|
| **AWS Secrets Manager** (`nova/*/...`) | Application runtime secrets: database credentials, Cognito client secrets, third-party API keys the running app needs, invitation signing keys |
| **GitHub Actions Secrets** | CI/CD secrets only: `ANTHROPIC_API_KEY`, `NOTION_API_KEY`, `GH_TOKEN`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`. These are ephemeral pipeline credentials, not application config. |
| **ECS task definition `secrets:` block** | References to Secrets Manager or Parameter Store ARNs only — never plaintext values |
| **ECS task definition `environment:` block** | Non-secret config only: `ENVIRONMENT`, `LOG_LEVEL`, etc. |

**Never:**
- Hardcode any secret in source code, Terraform HCL, or Dockerfiles
- Put application secrets in `environment:` blocks — use `secrets:` with a Secrets Manager ARN
- Store secrets in `.env` files committed to the repo

## Architecture Constraints
- **12-factor methodology** is non-negotiable (https://12factor.net/)
- Config via environment variables only — never hardcoded, never committed
- Secrets via AWS Parameter Store / Secrets Manager
- Stateless processes — no local disk state between requests
- Logs to stdout/stderr only
- **API-only connectivity** — agents expose an API; cloud connectors push data to it;
  the OS-level agent calls out to the platform API. Under NO circumstances are
  network connections established INTO seller environments. All data collection
  happens over APIs and encrypted channels.

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

## Container Strategy — Hard Requirement
**Every service is containerized. The factory produces container images; ECS Fargate runs them.**

### Images
| Image | Purpose | CMD |
|---|---|---|
| `nova-api` | FastAPI app | `uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| `nova-worker` | SQS scan-job consumer | `python -m app.workers.main` |

Both images are built from the **same `Dockerfile`** at the repo root.
Worker uses a different `command` override in the ECS task definition.

### Registry
- ECR repository per image: `nova-api`, `nova-worker`
- Registry: `{aws_account_id}.dkr.ecr.us-east-1.amazonaws.com`
- Tags: `{git_sha_short}` (immutable) + `latest` (mutable, always points to newest)
- Infra variable: `var.api_image` — ECS task definitions reference this

### Dockerfile — Hard Requirement (Backend Agent)
Every feature that touches `app/` MUST include or update:
1. `Dockerfile` — multi-stage build at repo root:
   - Stage `builder`: `python:3.12-slim`, install deps from `requirements.txt`
   - Stage `runtime`: `python:3.12-slim`, copy deps + `app/`, run as non-root user
2. `.dockerignore` — exclude `.git`, `tests/`, `infra/`, `frontend/`, `.env`, `__pycache__`
3. `/health` endpoint in `app/main.py` — returns `{"status": "ok"}`, no auth, no DB
4. `docker-compose.yml` at repo root — local dev: API + PostgreSQL container

### Local Development
`docker-compose.yml` at repo root provides the local dev environment:
- `api` service: builds from `Dockerfile`, port 8000
- `db` service: `postgres:16-alpine`, port 5432, health-checked
- All env vars provided via `environment:` block (12-factor)
- No `.env` file mounting — explicit vars only

### Image Tagging in CI/CD
- Factory build phase: validates `Dockerfile` builds (`docker build -t nova-api:test .`)
- Deploy workflow: builds image → tags `{sha}` + `latest` → pushes to ECR → applies Terraform → ECS force-redeploys

## Fixed Baseline Stack
| Layer | Choice |
|---|---|
| Compute | ECS Fargate |
| Database | RDS PostgreSQL |
| Auth | AWS Cognito (two user pools: buyer + seller) |
| Edge | Cloudflare (CDN, DNS, WAF) |
| IaC | Terraform |
| Backend | FastAPI (Python) |
| Frontend | React 18 + TypeScript |
| Container runtime | Docker (ECS Fargate) |
| Container registry | Amazon ECR |

## Extended Stack (Tech DD Platform additions)
| Concern | Choice | Notes |
|---|---|---|
| Async scan jobs | SQS + ECS workers | Fan-out per diligence category |
| Caching / sessions | ElastiCache Redis | Sub-10ms reads, session state |
| Evidence storage | S3 | Scan artefacts, uploaded evidence |
| Vector search | OpenSearch (3-AZ) | pgvector NOT available on RDS |
| Agent orchestration | LangGraph | Agent workflow graphs |
| AI gateway | LiteLLM | Claude/OpenAI/Gemini/Bedrock routing |
| Agent runtime | Amazon Bedrock AgentCore | Agent lifecycle management |
| AI safety | Bedrock Guardrails | Input/output filtering |
| Agent memory | AgentCore Memory | Cross-session context for agents |
| AI observability | Langfuse or Arize | LLM tracing, token usage, latency |
| OS-level agent | Go binary | Buyer-requestable escalation; outbound-only |

## Multi-Tenancy Model
- **Tenant key**: `buyer_org_id` — all queries must filter by this
- Row-level security enforced at DB layer on all tables
- Seller accounts are scoped **per engagement** — not global tenants
- Two Cognito user pools: one for buyer users, one for seller users

## Diligence Categories (8 Agents)
Each category has an AI specialist agent. Default weights (sum to 100%) are stored
in the `scoring_config` table (versioned) and are configurable per engagement.

| # | Category | Default Weight |
|---|---|---|
| 1 | Security | 23% |
| 2 | Compliance | 18% |
| 3 | Infrastructure | 13% |
| 4 | Code Quality | 13% |
| 5 | Engineering Process | 11% |
| 6 | IT Operations | 10% |
| 7 | Dependencies | 7% |
| 8 | Documentation | 5% |

## Scoring Model
Findings are scored on two independent axes:
- **Financial Risk** (Critical / High / Medium / Low) — 60% weight
- **Remediation Effort** (Days / Weeks / Months / Years) — 25% weight
- Finding Count (10%) and Trend/Coverage (5%) also factor in

All weights are stored in the `scoring_config` table, versioned. Reports record
which config version produced them for reproducibility.

## Engagement Lifecycle
9 steps: Deal Room Created → Seller Invited → Seller Accepts → Cloud Connectors
Connected → Autonomous Scan Runs → AI Synthesis → Advisor Review & Annotations →
Buyer Report Delivered → Clarification Q&A → Deal Outcome

## Data Retention Policy
- **Deal closed**: Buyer retains curated report; raw scan data deleted within 30 days
- **Deal abandoned**: 7-day seller offboarding period (seller completes connector
  revocation checklist); buyer access suspended immediately; all data deleted after
  offboarding period (buyer retains nothing)

## Coding Conventions
- All code must have tests before merging
- All tests must pass in CI before merging (pytest, ruff, mypy)
- Security Reviewer must pass before any commit lands
- Every Terraform change runs `terraform validate` and `terraform plan` before apply
- Multi-tenancy: all queries must filter by `buyer_org_id` — row-level security
  enforced at DB layer
- Backend agent always updates `requirements.txt` when adding new dependencies
- Use Alembic for all database migrations (not raw SQL files)
- Python: SQLAlchemy 2.x async (`mapped_column`, `AsyncSession`); modern type hints
  (`X | None` not `Optional[X]`, `dict` not `Dict`)

## Agent Roles
See `.claude/agents/` for each agent's system prompt.
Orchestrator coordinates all agents. Do not call agents directly.

## Repository Layout
- `app/` — web application
  - `app/api/routes/` — FastAPI route handlers (thin, delegate to services)
  - `app/services/` — business logic
  - `app/repositories/` — data access (always filter by `buyer_org_id`)
  - `app/models/` — SQLAlchemy ORM models
  - `app/schemas/` — Pydantic request/response schemas
  - `app/core/` — config, database, auth utilities
  - `app/db/migrations/` — Alembic migrations
  - `app/workers/` — SQS consumer workers (async scan jobs)
  - `app/agents/` — LangGraph agent definitions
- `frontend/` — React 18 + TypeScript SPA
- `infra/` — Terraform modules
- `infra/bootstrap/` — one-time S3/DynamoDB state backend setup
- `scripts/` — factory tooling
- `.claude/agents/` — agent system prompts
- `docs/` — specs and plans
- `docs/openapi.json` — always up to date, committed by factory on API changes

## Tech Stack Decisions (maintained by Architect agent)

| Library / Tool | Version constraint | Decision |
|---|---|---|
| Vite | `>=5.0,<6.0` | Build tool for the React frontend — scaffolded with `npm create vite@latest --template react-ts` |
| React Router | `react-router-dom>=6.0,<7.0` | Client-side routing in the React SPA |
| axios | `>=1.6,<2.0` | HTTP client for frontend→API calls |
| amazon-cognito-identity-js | `>=6.3,<7.0` | Cognito auth in the React frontend — native AWS library; handles both buyer and seller pools independently without Amplify framework overhead |
| asyncpg | `>=0.29,<1.0` | Async PostgreSQL driver for SQLAlchemy `AsyncSession` |
| python-jose[cryptography] | `>=3.3,<4.0` | JWT decoding and validation for Cognito tokens in the backend |
| pydantic-settings | `>=2.0,<3.0` | Settings management from environment variables (12-factor) |
| Alembic | `>=1.13,<2.0` | Database migrations — all migrations are Python files under `app/db/migrations/` |
