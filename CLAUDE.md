# Nova — Master Project Context

> This repo contains **two distinct things**:
> 1. **The Product** (`app/`, `frontend/`, application `infra/` modules) — the
>    Nova Tech DD platform. Most of the rules in this file describe HOW the
>    product is built and constrained.
> 2. **The Factory** (`.factory/`, `infra/factory/`, `infra/bootstrap/`,
>    `infra/webhook-relay/`, `scripts/factory_lambdas/`, `tests/factory/`) —
>    an autonomous CI/CD pipeline that builds the product. It runs in AWS,
>    triggers off Notion webhooks, and merges PRs to `main`. It is governed
>    by its own docs at [`docs/factory/README.md`](docs/factory/README.md);
>    only a brief orientation lives here.
>
> When in doubt about which set of rules applies: if you're writing app code
> (FastAPI routes, React components, RDS migrations), follow the Product
> sections. If you're touching factory plumbing (state machines, Lambdas,
> the implementer's system prompt), read the factory docs first.

---

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

## Factory (orientation only — see [`docs/factory/README.md`](docs/factory/README.md) for details)

The product is built and maintained by the **Nova Software Factory v2** — an
autonomous AWS Step Functions pipeline that turns Notion features (status =
"Ready to Build") into merged PRs on `main`. **Live as of 2026-05-04.**

**One-line architecture:** deterministic Step Functions orchestrator with three
LLM stages (Plan → Implement → Review) plus a deterministic Validate stage,
ending in a PR + GitHub Actions quality gates + auto-merge + post-deploy probe.

**Pipeline (v2):**
Notion → Webhook Lambda → Step Functions `nova-factory-v2` → Plan (Haiku)
→ PlanGate → RalphLoop (≤6 turns of Sonnet, container Lambda) → Validate
(deterministic ruff/mypy/pytest/tf/tsc) → Review (Sonnet) → CommitAndPush v2
→ OpenPR → quality-gates.yml → MarkDone. After merge, `nova-factory-postdeploy`
probes staging from the merged commit's `.factory/last-run/prd.json` and
auto-reverts via the GitHub Tree API on failure.

**Pause / unpause:** SSM parameter `/nova/factory/paused` (string `true`/`false`).
The webhook relay reads this on every delivery; auto-pause flips it on alarm
or budget breach. **Auto-pause never auto-resumes** — humans reset deliberately.

**Canonical factory artifacts in this repo:**

| Path | Purpose |
|---|---|
| `.factory/prd.schema.json`            | JSON Schema for the PRD emitted by Plan; the contract every later stage relies on. |
| `.factory/feature-sizing-rubric.md`   | Deterministic sizing thresholds — humans use this to self-size before filing in Notion. |
| `.factory/implementer-system.md`      | System prompt the RalphTurn container injects on every `claude -p` invocation. |
| `.factory/reviewer-system.md`         | Reviewer system prompt; encodes the four review categories (security/tenancy/spec/migration). |

**Sandbox boundary the factory enforces against itself:** the implementer's
writes under `.github/workflows/`, `.factory/` (except `.factory/_DONE_`),
`infra/factory/`, or paths containing `..`/absolute prefixes are rejected at
the post-turn upload step (see [`scripts/factory_lambdas/containers/ralph_turn/allowlist.py`](scripts/factory_lambdas/containers/ralph_turn/allowlist.py)). The factory's GitHub PAT lacks `workflow` scope — even
if the allowlist were bypassed, CI cannot be edited.

**Operating the factory (cheat sheet):**
```bash
# Pause (humans only — no auto-resume)
MSYS_NO_PATHCONV=1 aws ssm put-parameter --name /nova/factory/paused --value true  --type String --overwrite
MSYS_NO_PATHCONV=1 aws ssm put-parameter --name /nova/factory/paused --value false --type String --overwrite

# Manually start an execution (skipping the Notion webhook)
aws stepfunctions start-execution \
  --state-machine-arn arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-v2 \
  --name "manual-$(date +%s)" --input '{"feature_id":"<notion-page-uuid>"}'

# Tail the implementer
MSYS_NO_PATHCONV=1 aws logs tail /aws/lambda/nova-factory-ralph-turn --follow

# Smoke test (creates a synthetic Notion page + waits for terminal)
bash scripts/factory_smoke_v2.sh trivial
```

**Where to read more about the factory:**
- Operator's guide: [`docs/factory/README.md`](docs/factory/README.md) (architecture, AWS resources, common ops, cost model, sandbox layers)
- Incident runbook: [`docs/runbooks/factory-incident.md`](docs/runbooks/factory-incident.md)
- Original design rationale: [`docs/superpowers/specs/2026-05-03-factory-rebuild-design.md`](docs/superpowers/specs/2026-05-03-factory-rebuild-design.md)
- Implementation history (Phase 1–6): [`docs/superpowers/plans/2026-05-03-factory-v2-phase{1..6}-*.md`](docs/superpowers/plans/)

> **Rule of thumb for app agents:** never edit `.factory/*`, `infra/factory/*`,
> `infra/bootstrap/*`, `infra/webhook-relay/*`, `scripts/factory_lambdas/*`,
> `tests/factory/*`, `.github/workflows/quality-gates.yml`, or
> `.github/workflows/deploy.yml` unless you're explicitly working on the
> factory itself. Edits to those paths are rejected by the implementer's
> sandbox allowlist and surface as `DENIED:` lines in the next turn.

## Secrets Strategy — Hard Requirement
All secrets follow a strict tiering. Violations are caught by the factory's
Review stage (security category) and block the PR.

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
- The factory's Review stage (Sonnet) must return `passed: true` with no
  blockers in the security/tenancy/spec/migration categories before the
  PR can be opened
- Every Terraform change runs `terraform validate` and `terraform plan` before apply
- Multi-tenancy: all queries must filter by `buyer_org_id` — row-level security
  enforced at DB layer
- Always update `requirements.txt` when adding new Python dependencies
- Use Alembic for all database migrations (not raw SQL files)
- Python: SQLAlchemy 2.x async (`mapped_column`, `AsyncSession`); modern type hints
  (`X | None` not `Optional[X]`, `dict` not `Dict`)

## Repository Layout

**App (the Tech DD platform):**
- `app/` — Python backend
  - `app/api/routes/` — FastAPI route handlers (thin, delegate to services)
  - `app/services/` — business logic
  - `app/repositories/` — data access (always filter by `buyer_org_id`)
  - `app/models/` — SQLAlchemy ORM models
  - `app/schemas/` — Pydantic request/response schemas
  - `app/core/` — config, database, auth utilities
  - `app/db/migrations/` — Alembic migrations
  - `app/workers/` — SQS consumer workers (async scan jobs)
  - `app/agents/` — LangGraph agent definitions (these are *application* agents
    that scan seller code; not the build-system agents that put them there)
- `frontend/` — React 18 + TypeScript SPA
- `infra/` (excluding `infra/factory/`, `infra/bootstrap/`, `infra/webhook-relay/`) — application Terraform modules (RDS, Cognito, ECS Fargate, etc.)
- `tests/` (excluding `tests/factory/`) — application test suite. The factory runs this in `Validate`.
- `docs/openapi.json` — always up to date; committed by the factory on every run that touches the API.

**Factory (the build system; managed by [`docs/factory/README.md`](docs/factory/README.md)):**
- `.factory/` — schema + system prompts the factory's LLMs read at runtime
- `infra/factory/` — Lambdas, state machines, IAM, dashboard, alarms, budgets
- `infra/bootstrap/` — one-time S3 state bucket + DDB lock table
- `infra/webhook-relay/` — Notion webhook → SFN dispatch Lambda
- `scripts/factory_lambdas/` — source code for all factory Lambdas (handlers, common helpers, container images)
- `scripts/factory_smoke_fixtures/` + `factory_smoke_v2.sh` — synthetic feature fixtures + smoke runner
- `scripts/setup_notion*.py`, `notion_client.py`, `create_foundation_features.py` — one-time setup utilities for the Notion DB
- `tests/factory/` — unit tests for factory code (59 tests; runs independently of the app)
- `.github/workflows/quality-gates.yml`, `.github/workflows/deploy.yml` — post-PR validation + deploy

**Shared / docs:**
- `docs/factory/` — factory operator's guide
- `docs/runbooks/` — incident runbooks
- `docs/superpowers/` — design specs and implementation plans for the factory rebuild

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
