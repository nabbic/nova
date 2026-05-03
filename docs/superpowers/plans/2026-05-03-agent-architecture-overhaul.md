# Nova Factory — Agent Architecture Overhaul

**Date:** 2026-05-03 (evening)
**Owner:** Sonnet (autonomous execution)
**Branch:** `factory-overhaul-2026-05-03` (continue)
**Status:** Ready to execute, in priority order
**Related plans:**
- `2026-05-03-factory-cost-and-robustness-overhaul.md` (foundation)
- `2026-05-03-factory-overhaul-execution-summary.md` (execution log)
- `2026-05-03-factory-stabilization-and-cutover.md` (active stabilization)

---

## Audit summary

I read every agent prompt, the product spec, and CLAUDE.md against what's actually built. Three findings drive this plan:

### Finding 1 — JSON file-map output is the wrong abstraction for code agents

The pattern today: each code-producing agent (`database`, `backend`, `frontend`, `infrastructure`, `test`) returns a single JSON object `{file_path: file_content_string, ...}`. The runner parses it and writes each file.

This pattern is responsible for several smoke-run failures:

- **Token waste**: every `\n` and `\"` consumes 1+ tokens just for escape syntax. A 5KB Python file becomes ~7-8KB of JSON-escaped string. Across 5 code agents at 32K max_tokens, this dominates output budget.
- **All-or-nothing emission**: model must commit to the entire file map upfront. Truncation at `max_tokens` produces invalid JSON; we then either retry the full call (expensive) or attempt Haiku JSON repair (incomplete files).
- **No per-file validation**: model can't see "did that file pass syntax check?" before writing the next file. The validate-then-repair cycle exists at the workspace level but feedback is too coarse.
- **Brittle escaping**: models are reliably bad at maintaining JSON escape correctness across a 30KB output. This is the root cause of bug 6 (Anthropic SDK enforcing streaming) and several "invalid JSON" smoke failures.

For workspace-data agents (orchestrator, spec-analyst, architect, security-reviewer) the JSON-output pattern is **fine** — outputs are structured data, small, and benefit from a strict schema. Don't change those.

### Finding 2 — Several missing agent roles relative to the product

The Tech DD platform spec is ambitious: 8 diligence agents in the *product*, multi-tenant SaaS, 30+ external connectors, IP-protection workflows, Bedrock AgentCore + LangGraph + LiteLLM. The factory's 9 agents cover the basics (build code, infra, tests; review security) but miss several quality gates that matter for shipping production code at this scale:

| Missing role | What it does | Why this product needs it |
|---|---|---|
| **Code Reviewer** | Quality, performance, idiomatic patterns, N+1 queries, async correctness, dead code | Multi-tenant SaaS with RLS — query plans matter; security-reviewer only catches security issues, not perf/quality |
| **Documentation** | Keeps `README.md`, `docs/openapi.json`, `CHANGELOG.md`, runbook docs in sync per feature | Product has multiple user portals (buyer/seller/advisor) and external advisors who read docs; must not rot |
| **Deploy Verifier** | Post-deploy smoke probe — hits real endpoints on staging, checks `/health`, asserts the new feature actually works | Today the factory marks Done after PR merge, but no agent verifies the deployed code does what the spec said |
| **Migration Safety** | Reviews schema changes for backward-compat, blue-green deployability, data-backfill correctness | Real users — a bad migration is a P0 incident; database agent writes migrations but no one currently audits them for safety |

Two other roles I considered and ruled out:
- **Cost Agent** — already covered by the cost policy in CLAUDE.md + the budget alarm; spec-analyst flags `non_free_tier_resources`. A dedicated agent would be redundant.
- **Refactoring Agent** — interesting but premature; tackle after the factory is producing reliable single-feature builds.

### Finding 3 — Per-agent prompts are mostly good, but have specific gaps

Going through each agent:

| Agent | Status | Specific issues |
|---|---|---|
| `orchestrator.md` | Good | `parallel_groups` advice should be removed (state machine enforces ordering per the stabilization plan); `model_hint` is well-designed |
| `spec-analyst.md` | Good | Hard blockers definition is right; could use a "spec-quality score" output for observability |
| `architect.md` | Good | `CLAUDE.md.delta` pattern is excellent; should also emit a **per-agent context bundle** so downstream agents don't reload the entire CLAUDE.md |
| `database.md` | **Stale** | Still references `.factory-workspace/` (filesystem) instead of S3 workspace; missing repair-mode section; no migration-safety guidance |
| `backend.md` | OK but bloated | 7.6KB of mandatory boilerplate (Dockerfile, docker-compose, .dockerignore) regenerated every run — should be opt-in; the embedded Dockerfile/compose templates should live in the repo as files the agent references, not be pasted into every prompt |
| `frontend.md` | Sparse | Missing TanStack Query examples, missing `tests/` discipline (Vitest patterns), missing CSS approach (no styling system specified) |
| `infrastructure.md` | Good but fragile | Embeds full ECS/IAM templates that are repeated in every infrastructure call — same bloat issue as backend |
| `test.md` | OK | Per the stabilization plan, needs `tests/requirements.txt` discipline + cross-agent dependency notes |
| `security-reviewer.md` | Good | Could emit per-issue `repairable: bool` for the state machine to route on (mentioned in original plan, verify it's implemented) |

The pattern across `backend`, `frontend`, `infrastructure`: **mandatory boilerplate is being copy-pasted into every agent prompt rather than referenced from the existing repo**. The agent should be told "if `Dockerfile` doesn't exist, copy from `.factory/templates/Dockerfile.tmpl`", not given the entire Dockerfile inline.

---

## Strategy

Three phases, in order of value/effort ratio:

- **Phase 1** (1 session): Fix prompt staleness and cross-agent issues. Pure markdown edits to `.claude/agents/`. No infra changes. Zero risk. Substantially improves smoke reliability.
- **Phase 2** (2 sessions): Add 4 new agents. Pure additive — doesn't change existing behaviour. Each new agent is its own Lambda + Step Functions state.
- **Phase 3** (2-3 sessions): Migrate code agents from JSON file-maps to native tool use. This is the structural change. High-value but bigger blast radius.

Phase 3 should NOT start until Phase 1 + the existing stabilization plan reach a clean smoke run. We want a working baseline before changing the agent execution model.

A separate **Phase 4** (optional, large) covers Bedrock-native invocation for cost — already documented in `2026-05-03-factory-stabilization-and-cutover.md` Phase C; reference, don't duplicate.

---

## Phase 1 — Agent prompt fixes (do first)

### 1.1 — Fix `database.md` staleness

Replace `.factory-workspace/` filesystem references with S3-workspace references. Add the standard repair-mode section. Add migration-safety section.

Edits to `.claude/agents/database.md`:

1. Replace input section:
   ```markdown
   ## Inputs
   - Workspace JSON from S3 (loaded by the runner): `requirements.json`, `architecture.json` (if exists)
   - `CLAUDE.md` — project context
   - `app/` — existing codebase for schema context (provided in the workspace bundle)
   ```

2. Remove the `Write .factory-workspace/migrations.json:` block. The runner now derives migration files from the file map keys.

3. Add **Repair mode** section (table format like other agents):
   ```markdown
   ## Repair mode

   If your input includes a `# REPAIR MODE` block, output ONLY the migration files needed
   to fix the listed issues. Do not regenerate unrelated migrations.

   Common failures:
   | Failure | Repair |
   |---------|--------|
   | `alembic check: Target database is not up to date` | Generate a new migration with the missing operations; never edit an existing applied migration |
   | `alembic check: Multiple head revisions` | Add a merge migration that has both heads as `down_revision = ('head1', 'head2')` |
   | Missing RLS policy on a new table | Add `op.execute("ALTER TABLE ... ENABLE ROW LEVEL SECURITY")` and the CREATE POLICY statement |
   ```

4. Add **Migration safety** section:
   ```markdown
   ## Migration safety — Hard Rule

   This is a multi-tenant production SaaS. Every migration MUST be:

   - **Backward-compatible with the previous app version** for at least one deploy cycle.
     Old code must still run against the new schema. Specifically:
     - NEVER drop a column in the same migration that adds its replacement
     - NEVER rename a column in a single migration — add the new column, backfill, then drop later
     - NEVER add a `NOT NULL` column without a `server_default`
   - **Online-safe** for tables with row counts that may be large (any tenant-scoped table):
     - Use `op.add_column(..., server_default=...)` not application-level default
     - For indexes on existing tables use `CREATE INDEX CONCURRENTLY` (Postgres 12+)
   - **Reversible**: every `upgrade()` has a working `downgrade()` (no `pass`, no `raise`)

   If the change cannot be made safely in one step, split into multiple migrations and
   document the order in a comment at the top of each file.
   ```

### 1.2 — Slim `backend.md`

Move the embedded Dockerfile, docker-compose.yml, .dockerignore content into actual files in the repo at `.factory/templates/`. Update the agent prompt to reference them by path instead of pasting full content.

1. Create new files (commit them once):
   - `.factory/templates/Dockerfile.tmpl`
   - `.factory/templates/docker-compose.yml.tmpl`
   - `.factory/templates/dockerignore.tmpl`
   - `.factory/templates/health-route.py.tmpl`

   Move the content from `backend.md` lines 50-149 verbatim into these files.

2. Replace the entire "Containerization — Hard Requirement" section in `backend.md` with:
   ```markdown
   ## Containerization — Hard Requirement

   The repo ships canonical templates at `.factory/templates/`:
   - `Dockerfile.tmpl` — multi-stage build, non-root user
   - `docker-compose.yml.tmpl` — local dev (api + postgres)
   - `dockerignore.tmpl` — exclusions
   - `health-route.py.tmpl` — `/health` endpoint snippet

   Rules:
   - If `Dockerfile`, `docker-compose.yml`, or `.dockerignore` does NOT exist in the repo,
     copy the corresponding template verbatim into your file map.
   - If they DO exist, do not regenerate them unless this feature requires a change
     (e.g., new env var to add to `docker-compose.yml`'s `environment:` block).
   - The `/health` endpoint must always exist in `app/main.py` — copy from `health-route.py.tmpl`
     if it's missing.

   The workspace validator checks that `Dockerfile`, `.dockerignore`, and a `/health` route
   are present after this agent runs. If they're missing it will route a repair invocation
   back to you.
   ```

3. Add a token-budget self-check at the bottom of `backend.md`:
   ```markdown
   ## Output discipline

   Before finalizing your file map, ask: "Have I included only the files this feature
   needs?" Do not include unrelated files just to be thorough. Each unnecessary file
   wastes ~500 tokens of output budget and increases the risk of hitting `max_tokens`
   with a truncated response.

   If your output approaches the token limit (you'll see fewer characters available),
   prioritize: route handlers + service layer + schemas first, then tests, then
   Dockerfile/compose only if they need updating.
   ```

### 1.3 — Same template-extraction pass for `infrastructure.md`

Move the embedded ECS/IAM/Cluster/CloudWatch HCL into `.factory/templates/`:
- `.factory/templates/ecr.tf.tmpl`
- `.factory/templates/ecs-cluster.tf.tmpl`
- `.factory/templates/ecs-task-api.tf.tmpl`
- `.factory/templates/ecs-task-worker.tf.tmpl`
- `.factory/templates/iam-ecs.tf.tmpl`
- `.factory/templates/cloudwatch-alarm.tf.tmpl`

Replace the prompt's inline HCL with references like:
```markdown
## ECS Container Infrastructure

Canonical templates live in `.factory/templates/`. Reference rules:

| If you need... | Use template | Existing module check first |
|---|---|---|
| ECR repository | `ecr.tf.tmpl` | `infra/modules/ecr/` |
| ECS cluster | `ecs-cluster.tf.tmpl` | `infra/modules/ecs/` |
| API task definition | `ecs-task-api.tf.tmpl` | `infra/modules/ecs/main.tf` |
| Worker task definition | `ecs-task-worker.tf.tmpl` | `infra/modules/ecs/main.tf` |
| ECS IAM roles | `iam-ecs.tf.tmpl` | `infra/modules/ecs/iam.tf` |
| Per-endpoint alarm | `cloudwatch-alarm.tf.tmpl` | n/a — always per-feature |

If a module already exists in `infra/modules/`, extend it rather than recreating.
Only emit a new file in your file map when the module is genuinely missing.
```

### 1.4 — Strengthen `frontend.md`

Add the missing detail. Insert this section between "Stack" and "Your Task":

```markdown
## Patterns

### TanStack Query

Every API call goes through a typed query hook in `frontend/src/api/<resource>.ts`:

```typescript
import { useQuery, useMutation } from "@tanstack/react-query";
import { api } from "../api/client";  // axios instance with baseURL + auth
import type { Engagement } from "../types/engagement";

export function useEngagements() {
  return useQuery<Engagement[]>({
    queryKey: ["engagements"],
    queryFn: () => api.get("/api/engagements").then(r => r.data),
  });
}
```

### Routing

```typescript
// frontend/src/routes.tsx
<Routes>
  <Route path="/buyer/*"  element={<BuyerLayout/>}>...</Route>
  <Route path="/seller/*"  element={<SellerLayout/>}>...</Route>
  <Route path="/advisor/*" element={<AdvisorLayout/>}>...</Route>
</Routes>
```

Never let a buyer URL render seller content; the layout components are auth-gated.

### Styling

This project uses **Tailwind CSS v4** (configured in `frontend/tailwind.config.ts`).
Do not introduce other styling systems. No CSS-in-JS, no inline styles.

### State

- **Server state** = TanStack Query. Cache key starts with the resource name.
- **Client state** = Zustand. Stores live in `frontend/src/stores/`.
- **Form state** = React Hook Form. Validation via Zod schemas in `frontend/src/schemas/`.

### Tests

- Unit/component: Vitest + Testing Library. Files: `<Component>.test.tsx` next to the component.
- E2E: Playwright. Files in `frontend/e2e/<flow>.spec.ts`.

For test deps, write a `frontend/package.json` `devDependencies` entry — do not assume
they are pre-installed.
```

(If Tailwind isn't actually the styling choice yet, the architect agent should pick one — leave a `<<<STYLING_TBD>>>` marker in this section that architect must resolve before frontend runs. Better still: spec-analyst calls out "no styling system established" as a soft note that triggers architect.)

### 1.5 — Architect emits per-agent context bundles

Currently every downstream agent reads the full ~12KB CLAUDE.md plus all workspace JSONs. For a `frontend` invocation, 80% of CLAUDE.md (database conventions, secrets policy, ECS task definitions) is irrelevant.

Add to `.claude/agents/architect.md` output schema:

```json
{
  "context_bundles": {
    "database":       "<extracted CLAUDE.md sections relevant to DB schema, RLS, alembic>",
    "backend":        "<sections on FastAPI, auth, tenancy, env vars, dockerization>",
    "frontend":       "<sections on routing, auth, role layouts, this feature's pages>",
    "infrastructure": "<sections on ECS, IAM, cost policy, env-naming>",
    "test":           "<sections on test framework, multi-tenancy test rules>"
  }
}
```

Update `run_agent.py` to prefer `architecture.json["context_bundles"][agent_name]` over the full `CLAUDE.md` when present. Falls back to full CLAUDE.md if architect didn't run or didn't produce a bundle.

Token savings: ~50-70% on context for code agents. Direct cost win, also reduces "model gets distracted by irrelevant context" failures.

### 1.6 — Verification for Phase 1

After all 1.x edits, smoke test 3 times. Expected:
- Smoke runs no longer produce "invalid JSON" failures from backend agent (less to escape, more headroom under max_tokens).
- Total Anthropic spend per build drops 30-50% (less context per agent, less repeated boilerplate in prompts).
- Database agent successfully runs `alembic check` in validate_workspace.

---

## Phase 2 — Add four new agents

Each new agent is independent: a `.claude/agents/<name>.md` prompt, an entry in `AGENT_CONFIG` in `agent_runner.py`, and a state in the Step Functions state machine. No existing agent changes.

### 2.1 — Code Reviewer agent

**Position in pipeline:** After `validate_workspace` for the builders phase passes, BEFORE the test phase.

**Why now in the pipeline:** Test agent should write tests against code that's been quality-reviewed. Otherwise the test agent locks in tests against suboptimal patterns.

**Model:** sonnet (needs to read full code, reason about quality).
**Output type:** workspace JSON, mirrors `security-reviewer.md`.

`.claude/agents/code-reviewer.md`:

```markdown
# Code Reviewer Agent

You review code for quality, performance, and idiomatic correctness.
You run AFTER backend/frontend/infrastructure code has passed static validation
but BEFORE tests are written. You do NOT review for security — that's the
security-reviewer's job, and it runs later.

## Inputs
- Workspace from S3: all code files written this run
- `requirements.json` — to know what was asked for
- `CLAUDE.md` — for project conventions

## Your task

For each modified file, check:

### Backend (Python/FastAPI)
- N+1 query patterns: every loop that calls `.get()` on a relation is a flag
- Async correctness: any function `def` (not `async def`) that calls an awaitable is a bug; any `async def` that doesn't await anything is suspect
- Service-layer purity: no DB queries in `app/services/`, no business logic in `app/api/routes/`
- Tenant isolation: every repository function accepting `buyer_org_id` actually filters by it
- Pagination: any list endpoint without limit/offset support is a flag for endpoints that may grow

### Frontend (React/TypeScript)
- TanStack Query keys are stable and include all dependencies
- No untyped `any`
- Loading/error states present for every data fetch
- Components > 200 lines should probably be split — flag, don't block

### Infrastructure (Terraform)
- Variables instead of hardcoded values for region, account, environment
- Tags present on every resource (Project/Environment/Component)
- Resource naming matches `nova-${var.environment}-<role>` convention

## Output Format
JSON, same shape as security-reviewer:

```json
{
  "passed": true,
  "issues": [],
  "warnings": []
}
```

If `passed: false`, each issue:
```json
{
  "severity": "BLOCKER" | "MAJOR" | "MINOR",
  "category": "n_plus_one" | "async" | "tenant_isolation" | ...,
  "file": "app/services/engagement.py",
  "line": 42,
  "description": "list_engagements iterates engagements and calls get_findings(eng.id) per row — N+1 query",
  "fix": "Add a join in the repository: load engagements with selectinload(Engagement.findings)"
}
```

Only `BLOCKER` halts the build; `MAJOR` and `MINOR` are fed back to the originating
agent for one repair cycle then accepted as warnings if not fixed.

## Constraints
- Do not duplicate security-reviewer concerns (SQLi, XSS, secrets, IAM)
- Do not flag style issues (ruff/eslint already cover those)
- Be concrete — every issue has a file, line, and a one-line fix
- Respond with ONLY the JSON object — nothing else
```

State machine: add `RunCodeReview → EvaluateCodeReview → CodeReviewChoice` between `ValidateBuilders` and `TestPhase`. `EvaluateCodeReview` is a tiny Lambda that reads the JSON from S3 and returns `{passed, blockers, repairable}`. Repair routes to whichever agent owns the failing file (use the same `OWNERSHIP` map from `validate_workspace`).

### 2.2 — Documentation agent

**Position:** After security-reviewer passes, BEFORE commit.

**Why:** docs that lag behind code are a bug; the factory should produce the docs as part of the same atomic change.

**Model:** sonnet (needs to read code and write prose).
**Output type:** code-agent (file map).

`.claude/agents/documentation.md`:

```markdown
# Documentation Agent

You keep user-facing docs in sync with code changes. You run after all code
has been reviewed and passed validation but before commit.

## Inputs
- Workspace from S3: all code files this run, plus the security review and code review outputs
- `requirements.json` — what the feature was supposed to do
- `CLAUDE.md`
- `README.md`, `docs/openapi.json`, `CHANGELOG.md` (if exists) from the workspace

## Files you MAY produce or modify

| File | When |
|---|---|
| `docs/openapi.json` | Always when `app/api/routes/` changed — regenerate from FastAPI's `app.openapi()` |
| `README.md` | When this feature changes the developer setup story (new env var, new local-dev step) |
| `CHANGELOG.md` | Always — append a section under `## [Unreleased]` describing the user-visible change |
| `docs/runbooks/<topic>.md` | When this feature introduces operational knowledge (new dashboard, new failure mode, new manual remediation) |
| `docs/architecture/<topic>.md` | When architect.json contains a major decision that future engineers should understand |

## CHANGELOG format

Group entries by category. Keep them user-visible — no internal refactors.

```markdown
## [Unreleased]

### Added
- Buyers can now export the engagement report as PDF (`/api/engagements/{id}/export`)

### Changed
- Engagement creation now requires explicit IP scope confirmation (was implicit before)

### Fixed
- Seller portal session expiry no longer logs out advisor users on the same browser
```

## What you do NOT touch

- Code files (`app/`, `frontend/`, `infra/`, `tests/`)
- Agent prompts (`.claude/agents/`)
- Factory infra (`infra/factory/`)
- Pipeline workflows (`.github/workflows/`)

## Output Format
File map, same as backend agent.

## Constraints
- If a file you'd modify already accurately describes the change, skip it
- CHANGELOG is the one file you must always touch
- Respond with ONLY the JSON object — nothing else
```

State machine: insert `RunDocumentation` between `EvaluateSecurity` (when passed=true) and `CommitAndPush`.

### 2.3 — Deploy Verifier agent

**Position:** AFTER quality-gates merge succeeds and AFTER `deploy.yml` reports the staging deploy is stable. So this lives outside the main state machine — it's invoked by a separate CloudWatch Event when `deploy-staging` succeeds.

**Why:** Today's pipeline marks Done when the PR merges, but doesn't verify the deployed code actually works. A bad merge that crashes on `/health` would still be marked Done.

**Model:** haiku (deterministic — runs scripted curl probes; doesn't need code reasoning).
**Output type:** workspace JSON.

`.claude/agents/deploy-verifier.md`:

```markdown
# Deploy Verifier Agent

You verify that the deployed feature actually works in the staging environment.
You run AFTER staging deployment has stabilised. You do not modify code.

## Inputs
- `requirements.json` — what the feature was supposed to do (especially `acceptance_criteria` and `api_endpoints`)
- The staging URL: `https://staging.nova.<domain>` (from environment variable `STAGING_URL`)
- An auth token for the verifier role (from Secrets Manager)

## Your task

For each `api_endpoints` entry in `requirements.json`:
1. Construct a probe request that exercises the endpoint
2. Execute it against staging
3. Assert the response satisfies the acceptance criteria

For frontend pages (each `ui_pages` entry), verify the page returns 200 (full Playwright
testing happens in quality-gates, not here).

## Output Format

```json
{
  "passed": true,
  "probes": [
    {
      "endpoint": "GET /api/version2",
      "status": 200,
      "body_match": true,
      "elapsed_ms": 47
    }
  ],
  "failures": []
}
```

If `passed: false`, the calling Lambda will roll back: revert the merge commit on `main`,
notify Notion that the feature failed deploy verification, and trigger a repair cycle.

## Constraints
- Probes are read-only; never POST/PUT/DELETE in verification
- Use the auth token from Secrets Manager — never inline credentials
- Time out after 10 seconds per probe
- Respond with ONLY the JSON object — nothing else
```

Implementation note: this agent runs in a Lambda that has `requests` plus a tiny probe-runner that reads the agent's plan and executes the curls itself (the agent's "execute" phase is the Lambda doing the curls, not the model). The agent's job is to *plan* the probes; the runner executes them and the Lambda assembles the result. So the agent prompt is small and cheap.

Add a new state machine `nova-factory-post-deploy` triggered by EventBridge when the deploy CloudFormation/Terraform stack reports stable. Steps:
1. `RunDeployVerifierPlan` (Haiku Lambda)
2. `ExecuteProbes` (Lambda, runs the curls)
3. `EvaluateProbes` (Choice)
4. On pass: `MarkDeployVerified` in Notion (new field). On fail: `RollbackMerge` (Lambda that uses GitHub API to revert the commit and re-trigger build) → `NotifyNotionRollback`.

### 2.4 — Migration Safety agent

**Position:** Inside the `database` phase repair loop. Runs only when database agent produced a migration file.

**Why:** Migration safety is a specialised review; bundling it into the database agent's own prompt has not produced reliably safe migrations to date.

**Model:** opus (rigour matters; migrations are P0 risk).
**Output type:** workspace JSON.

`.claude/agents/migration-safety.md`:

```markdown
# Migration Safety Agent

You audit Alembic migrations for production safety. You run after the database
agent and validate_workspace's static checks pass.

## Inputs
- Workspace from S3: all migration files in `app/db/migrations/versions/`
- The previous head migration (so you can see what state the DB is in)
- `CLAUDE.md` — for the multi-tenancy and RLS rules

## Checks (BLOCKER unless noted)

1. **Backward compat**: every column the old code reads still exists with the same type.
2. **No NOT NULL without default**: every new NOT NULL column has `server_default=sa.text(...)`.
3. **No drop-then-add**: if a migration both drops and adds the same column name, fail (must be split into two migrations across two deploys).
4. **Reversibility**: `downgrade()` is non-empty and actually inverts `upgrade()`.
5. **RLS coverage**: every new table with `buyer_org_id` enables RLS and creates a `tenant_isolation` policy.
6. **Online-safe operations** (Postgres ≥12):
   - Index creation on existing tables uses `CREATE INDEX CONCURRENTLY`
   - Constraint additions are NOT VALID + VALIDATE in two steps for tables expected to be large
7. **Order independence**: migrations don't depend on each other except via `down_revision`.

## Output

```json
{
  "passed": true,
  "issues": []
}
```

Issues:
```json
{
  "severity": "BLOCKER",
  "file": "app/db/migrations/versions/20260503120000_add_engagements.py",
  "line": 28,
  "description": "ADD COLUMN status NOT NULL has no server_default — will fail on tables with existing rows",
  "fix": "Add server_default=sa.text(\"'pending'\") to the column definition"
}
```

## Constraints
- Only review migrations from THIS run (don't audit pre-existing migrations)
- Respond with ONLY the JSON object — nothing else
```

State machine: insert between `DatabasePhase` and `ValidateBuilders`:
```
DatabasePhase → ValidateDatabase (workspace) → ChoiceMigrationsPresent
                  → if migrations exist: RunMigrationSafety → SafetyChoice
                  → if no migrations:    skip to BuildersPhase
```

Failure on `RunMigrationSafety` routes back to the database agent with `repair_context = issues`.

### 2.5 — Update orchestrator to know about the new agents

`.claude/agents/orchestrator.md` — update the agent inclusion rules:

```markdown
## Agent Selection Rules
- Always include: spec-analyst, backend, test, code-reviewer, security-reviewer, documentation
- Include architect: when the feature requires new patterns, dependencies, or AWS services
- Include database: when the feature requires schema changes or migrations
  - When database is included, migration-safety is automatically also included
- Include frontend: when the feature includes any UI changes or new pages
- Include infrastructure: when the feature requires new AWS/Cloudflare resources
- Omit agents not needed — include a skip_reason entry for each omitted agent
- deploy-verifier runs in a separate post-deploy state machine — do NOT include it here
```

Add to `AGENT_CONFIG` in `agent_runner.py`:
```python
"code-reviewer":     {"model": "claude-sonnet-4-6",         "max_tokens": 8192},
"documentation":     {"model": "claude-sonnet-4-6",         "max_tokens": 8192},
"migration-safety":  {"model": "claude-opus-4-7",           "max_tokens": 4096},
"deploy-verifier":   {"model": "claude-haiku-4-5-20251001", "max_tokens": 4096},
```

### 2.6 — Phase 2 verification

After deploying:
1. Trigger smoke run; verify `code-reviewer`, `documentation`, `migration-safety` all run.
2. Trigger a feature with a deliberately N+1 service method; verify code-reviewer flags it and routes repair to backend.
3. After staging deploy completes, verify `deploy-verifier` state machine fires and probes the new endpoint.
4. CHANGELOG.md gets a new `[Unreleased]` entry per feature.

---

## Phase 3 — Migrate code agents to native tool use

This is the structural change. Save for after Phase 1 + the existing stabilization plan reach a clean smoke run.

### 3.1 — Why tool use

Anthropic's tool-use API lets the model emit `tool_use` blocks within its response. Each tool call has structured arguments. Compared to JSON file maps:

| Concern | JSON file map | Tool use |
|---|---|---|
| Multi-line code in arguments | Escaped to `\n`/`\"` (token waste, error-prone) | Native multi-line strings |
| Truncation at max_tokens | Whole response invalid | Last tool call may be truncated; preceding files are intact |
| Per-file validation | Only after parsing the full response | Tool result returned to model after each call; model can adjust |
| Streaming | Whole JSON object as one stream | Tool calls stream individually |
| Multiple files | Single response | Multiple parallel `tool_use` blocks (Anthropic supports this) |

### 3.2 — Define the tools

Add `scripts/factory_lambdas/common/tools.py`:

```python
"""Tool definitions for code-generating agents."""

WRITE_FILE_TOOL = {
    "name": "write_file",
    "description": (
        "Write a file to the workspace. Path is relative to repo root. "
        "If the file exists it is overwritten. Use for new files OR full rewrites."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path":     {"type": "string", "description": "Relative path, e.g. app/api/routes/users.py"},
            "content":  {"type": "string", "description": "Complete file content"},
            "rationale":{"type": "string", "description": "One sentence: why this file"},
        },
        "required": ["path", "content"],
    },
}

UPDATE_FILE_TOOL = {
    "name": "update_file",
    "description": (
        "Apply a focused edit to an existing file. Pass an old_string and new_string; "
        "the runner replaces old_string with new_string in the file. "
        "Prefer this over write_file when modifying < ~30% of a file. "
        "old_string must be unique within the file."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path":       {"type": "string"},
            "old_string": {"type": "string", "description": "Exact text to replace; must occur exactly once"},
            "new_string": {"type": "string", "description": "Replacement text"},
        },
        "required": ["path", "old_string", "new_string"],
    },
}

REPORT_DONE_TOOL = {
    "name": "report_done",
    "description": (
        "Signal that you have finished writing all files for this feature. "
        "Include a summary and a self-check listing which acceptance criteria your code satisfies."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "summary":      {"type": "string"},
            "self_check":   {
                "type": "object",
                "properties": {
                    "criteria_met":     {"type": "array", "items": {"type": "string"}},
                    "criteria_not_met": {"type": "array", "items": {"type": "string"}},
                    "open_questions":   {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "required": ["summary"],
    },
}

CODE_AGENT_TOOLS = [WRITE_FILE_TOOL, UPDATE_FILE_TOOL, REPORT_DONE_TOOL]
```

### 3.3 — Tool-use agent loop

Add to `common/agent_runner.py`:

```python
def call_code_agent_with_tools(
    agent_name: str,
    user_message: str,
    tool_handlers: dict,  # {tool_name: callable(args) -> str result}
    *, max_iterations: int = 30,
) -> dict:
    """
    Run a code-generating agent in a tool-use loop.
    Returns when model emits report_done OR max_iterations hit.
    """
    cfg = AGENT_CONFIG[agent_name]
    client = anthropic.Anthropic(api_key=get_secret("nova/factory/anthropic-api-key"))
    system = load_system_prompt(agent_name)

    messages = [{"role": "user", "content": user_message}]
    iterations = 0
    files_written = []
    summary = None
    self_check = None

    while iterations < max_iterations:
        iterations += 1
        with client.messages.stream(
            model=cfg["model"],
            max_tokens=cfg["max_tokens"],
            system=system,
            tools=CODE_AGENT_TOOLS,
            messages=messages,
        ) as stream:
            response = stream.get_final_message()

        # Find tool_use blocks
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        text_blocks = [b.text for b in response.content if b.type == "text"]

        if not tool_uses:
            # Model produced text but no tool call — coax it
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content":
                "Please use the write_file tool to write code, or report_done if you are finished."})
            continue

        # Execute each tool call, collect results
        tool_results = []
        for use in tool_uses:
            if use.name == "report_done":
                summary    = use.input.get("summary", "")
                self_check = use.input.get("self_check", {})
                tool_results.append({"type": "tool_result", "tool_use_id": use.id, "content": "Acknowledged."})
            else:
                handler = tool_handlers.get(use.name)
                if handler is None:
                    tool_results.append({"type": "tool_result", "tool_use_id": use.id,
                                         "content": f"Unknown tool: {use.name}", "is_error": True})
                    continue
                try:
                    result = handler(use.input)
                    if use.name in ("write_file", "update_file"):
                        files_written.append(use.input.get("path"))
                    tool_results.append({"type": "tool_result", "tool_use_id": use.id, "content": str(result)})
                except Exception as e:
                    tool_results.append({"type": "tool_result", "tool_use_id": use.id,
                                         "content": f"Error: {e}", "is_error": True})

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

        if summary is not None:
            return {
                "summary": summary, "self_check": self_check,
                "files_written": files_written, "iterations": iterations,
                "stop_reason": "report_done",
            }

    return {
        "summary": "(model did not call report_done)",
        "self_check": {}, "files_written": files_written,
        "iterations": iterations, "stop_reason": "max_iterations",
    }
```

### 3.4 — Per-handler tool handlers

Each code-agent Lambda provides handlers that write to S3 workspace:

```python
# In handlers/run_agent.py for code agents
from common.workspace import write_file, read_code_file, list_code_files
from common.agent_runner import call_code_agent_with_tools

def _handlers_for_execution(execution_id: str) -> dict:
    def write_file_handler(args):
        path = args["path"]
        content = args["content"]
        # Validate path (no .., no absolute)
        if path.startswith("/") or ".." in path.split("/"):
            raise ValueError(f"Refusing to write outside workspace: {path}")
        write_file(execution_id, path, content)
        return f"Wrote {path} ({len(content)} bytes)"

    def update_file_handler(args):
        path = args["path"]
        existing = read_code_file(execution_id, path)
        if args["old_string"] not in existing:
            raise ValueError(f"old_string not found in {path}")
        if existing.count(args["old_string"]) > 1:
            raise ValueError(f"old_string appears {existing.count(args['old_string'])} times in {path}; must be unique")
        new_content = existing.replace(args["old_string"], args["new_string"], 1)
        write_file(execution_id, path, new_content)
        return f"Updated {path}"

    return {"write_file": write_file_handler, "update_file": update_file_handler}
```

### 3.5 — Update agent prompts

Each code-agent prompt loses its "Output Format" section (no more JSON file map). Replace with:

```markdown
## How you write code

You have these tools:
- `write_file(path, content, rationale?)` — write or fully rewrite a file
- `update_file(path, old_string, new_string)` — focused edit; prefer this for small changes to existing files
- `report_done(summary, self_check)` — call exactly once when finished

Workflow:
1. Read the requirements and existing files (provided in your context).
2. For each file you need to create/modify, call `write_file` or `update_file`.
3. After each tool call you'll see a confirmation. If a tool call fails (e.g., update_file's old_string didn't match), adjust and try again.
4. When all files are written, call `report_done` with a summary and a self-check.

You may write multiple files in a single response (parallel tool use).
There is no "single big response" — work iteratively.
```

### 3.6 — Migrate one agent at a time

To de-risk: convert agents one at a time, in this order:
1. `database` — simplest, smallest output, easy to verify
2. `infrastructure` — Terraform files are well-bounded
3. `frontend` — many small files, big win for parallel tool use
4. `backend` — most complex; convert last when you're confident

For each: change the agent's `run_agent` invocation to use `call_code_agent_with_tools`, deploy, smoke test, only then proceed to next agent.

### 3.7 — Phase 3 verification

After all 5 code agents migrated:
- Average tokens per agent run drops 30-50% (no JSON escaping)
- Empty-response failures gone (no more single-shot truncation risk)
- The `messages.stream()` complexity remains (it's still required by Anthropic SDK) but is now hidden behind `call_code_agent_with_tools`
- `validate_workspace` failures route correctly via the same `OWNERSHIP` map

---

## Phase 4 — Bedrock + native Step Functions invocation (optional, deferred)

Already documented in `2026-05-03-factory-stabilization-and-cutover.md` Phase C. Do this only after Phase 3 is stable. Biggest single cost win remaining after that.

---

## Acceptance criteria

This plan is complete when:

1. `database.md` no longer references `.factory-workspace/`; has Repair mode + Migration safety sections.
2. `backend.md` and `infrastructure.md` reference `.factory/templates/*` instead of pasting full content; templates exist in repo.
3. `frontend.md` includes TanStack Query, routing, styling, and test discipline sections.
4. `architect.md` emits `context_bundles`; `run_agent.py` prefers them over full CLAUDE.md.
5. Four new agents exist with prompts, AGENT_CONFIG entries, and state machine wiring:
   - `code-reviewer` runs after `validate_workspace` (builders), before test phase.
   - `documentation` runs after `security-reviewer` passes, before `commit_and_push`.
   - `migration-safety` runs after `database` agent when migrations are present.
   - `deploy-verifier` runs in a separate post-deploy state machine triggered by EventBridge.
6. Three smoke runs complete with all 13 agents (orchestrator + spec-analyst + architect + code-reviewer + documentation + migration-safety + deploy-verifier + the existing 6) executing where applicable.
7. Code agents migrated to tool use one-by-one; each migration verified by 2 consecutive smoke runs before next agent.
8. Token usage per smoke run measurably lower vs pre-Phase-1 baseline (use the `agent-calls-summary` Logs Insights query from the stabilization plan).
9. CHANGELOG.md has entries for every feature processed during validation.
10. A deploy-verifier failure correctly rolls back a merge (test by injecting a 500-returning endpoint).

---

## Sonnet operating instructions

- Phase 1 is **pure markdown edits** — do them all in one commit per agent file. No infra changes, no Lambda redeployments. Smoke after Phase 1 to establish a baseline.
- Phase 2 is **additive only** — never modify existing agent behavior. New agents = new Lambdas + new state machine nodes. Existing pipeline path unchanged for features that don't touch DB / don't fail code review.
- Phase 3 is the **risky** one. Convert agents one at a time, run 2 smoke tests between each conversion. If conversion N breaks something, revert and skip — the JSON file-map fallback should still work for any agent not yet converted.
- Update the execution-summary file (`2026-05-03-factory-overhaul-execution-summary.md`) with a new "Agent architecture overhaul" section after each phase completes.
- If smoke fails after a Phase 1 edit, the issue is almost certainly the prompt change. Revert the specific edit and try a smaller increment.
- The four new agents are independently valuable; Phase 2 can ship even if Phase 3 doesn't (or vice versa). Don't gate one on the other.
- The user has stated this factory must work autonomously and reliably. Bias toward **fewer, sharper agent prompts** over comprehensive ones. Every line in an agent prompt is paid for in tokens on every invocation.
