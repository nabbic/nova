# Nova Factory v2 — Clean-Rebuild Design Spec

**Date:** 2026-05-03 (evening)
**Status:** Approved (design phase) — ready to translate to an implementation plan
**Branch:** continue on `factory-overhaul-2026-05-03`
**Predecessors (informational):**
- `docs/superpowers/plans/2026-05-03-factory-cost-and-robustness-overhaul.md`
- `docs/superpowers/plans/2026-05-03-factory-overhaul-execution-summary.md`
- `docs/superpowers/plans/2026-05-03-factory-stabilization-and-cutover.md`
- `docs/superpowers/plans/2026-05-03-agent-architecture-overhaul.md`

The above plans are **superseded** by this design. They will be archived under
`docs/superpowers/plans/archive/` as part of cleanup.

---

## 0. Why this rebuild

The existing factory has had **0 of 25 Step Functions executions succeed end-to-end**. Sonnet's last six commits are all symptom-fixes on the same per-agent validators. The architecture's structural problems — 9 chained agents (each repair compounds), JSON file-map output (escaping fragility), per-agent validators racing each other, Lambda streaming as the cost shape — are not bugs in the small. They are a structural mismatch between "deterministic orchestrator + tightly-scoped generators" (the MindStudio AI dark-factory pattern the user asked us to follow) and what was actually built.

This rebuild starts from the dark-factory principles directly:

1. **Deterministic orchestrator, agentic only where required.** Step Functions makes routing decisions; LLMs only generate code or judge code.
2. **Three LLM stages, no more, until data justifies otherwise.** Planner (Haiku) → Implementer (Sonnet, looped) → Reviewer (Sonnet, single call).
3. **One workspace, one validator.** Deterministic tools — no LLM, no per-agent validators, no race conditions.
4. **Hard bounds on cost and iteration.** Per-feature caps on Ralph turns, repair cycles, and tokens.
5. **Self-pausing factory.** Three consecutive failures or a budget breach auto-pauses; humans resume.
6. **Auto-rollback on bad deploys.** Post-merge staging probe; deterministic Lambda reverts on failure.
7. **Idempotent everywhere.** Lock per feature; webhook dedup by Notion event id; turn re-runs are safe.

The pipeline shrinks from 9–13 agents and ~25 Lambdas to **3 LLM stages + ~12 deterministic Lambdas + 2 state machines**.

---

## 1. High-level pipeline

```
Notion (feature → "Ready to Build")
    │  (existing webhook → API Gateway → relay Lambda)
    ▼
Step Functions: nova-factory-v2
  1. AcquireLock           (existing Lambda)
  2. LoadFeature           (new Lambda)              — Notion → spec_raw.md, feature_meta.json
  3. Plan                  (new Lambda + Haiku)      — writes prd.json
  4. PlanGate              (Choice)                  — sizing rubric + hard-blocker check
  5. RalphLoop             (SFN iterator, max 6)
       └─ RalphTurn        (new Lambda, container)   — one Claude Code turn per iteration
  6. Validate              (Lambda, container)       — ruff/mypy/pytest/tf validate/tsc
  7. ValidateRepair?       (≤2 cycles)               — issues → 1 Ralph turn → re-validate
  8. Review                (new Lambda + Sonnet)     — single review call (security + tenancy + spec + migration)
  9. ReviewRepair?         (≤2 cycles)               — blockers → 1 Ralph turn → re-validate → re-review
 10. CommitAndPush         (existing Lambda)
 11. OpenPR                (existing Lambda)
 12. WaitForQualityGates   (callback wait)           — quality-gates.yml → callback API
 13. MarkDone              (existing Lambda)
 14. ReleaseLock           (existing Lambda)

Step Functions: nova-factory-postdeploy
  (triggered by EventBridge on deploy.yml workflow_run success)
  A. ProbeStaging          (new Lambda)              — HTTP probes against acceptance criteria
  B. Healthy?              (Choice)
       pass → MarkVerified in Notion
       fail → RevertMerge (new Lambda, gh)
              → ReFileFeature in Notion (status=Failed, reason=deploy_verification_failed)
              → AlarmSNS
```

Three failure tripwires sit alongside the pipeline:
- **3 consecutive `ExecutionsFailed`** → auto-pause Lambda flips `/nova/factory/paused = true`
- **Per-feature token budget breach** → terminates the run with `MarkBudgetExceeded`
- **Monthly budget alarm at $100** → flips `/nova/factory/paused = true`, pages on-call

---

## 2. Components

### 2.1 Intake (mostly existing)

- **AcquireLock / ReleaseLock** *(existing — reuse)* — DynamoDB conditional put on `feature_id` with TTL.
- **LoadFeature** *(new)* — fetches the Notion page by `feature_id`, extracts title + body + properties, writes `intake/spec_raw.md` and `intake/feature_meta.json` to S3.

### 2.2 Plan (the spec-analyst stage)

**Plan Lambda** *(new — replaces today's `run_orchestrator` + `spec-analyst` agents)*. Single Haiku 4.5 call. Input: `spec_raw.md` + `CLAUDE.md` + `.factory/prd.schema.json`. Output: a normalized `prd.json` written to S3.

**`prd.json` schema** (canonical lives at `.factory/prd.schema.json`):

```jsonc
{
  "feature_id": "notion-uuid",
  "title": "Add buyer engagement export endpoint",
  "narrative_md": "<full Notion body>",
  "stories": [
    {
      "id": "s1",
      "description": "Buyers can GET /api/engagements/{id}/export and receive a JSON report",
      "acceptance_criteria": [
        "Returns 200 with engagement data when authenticated as the owning buyer org",
        "Returns 403 on buyer_org_id mismatch",
        "docs/openapi.json includes the endpoint"
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
  "hard_blockers":    [],
  "risk_flags":       [],
  "suggested_split":  []   // populated only when sizing rubric breached
}
```

#### 2.2.1 Plan-time sizing rubric (deterministic gate)

Decomposing too-big features at plan time is what keeps the Ralph cap workable. After Haiku returns the PRD, the Plan Lambda evaluates a **deterministic rubric** (no LLM judgment):

| Threshold | Limit | Why |
|---|---|---|
| `total_stories` | ≤ 4 | At 6-turn cap, 4 stories ≈ 1.5 turns/story |
| `total_acceptance_criteria` (sum across stories) | ≤ 12 | Tracks token output reliably |
| Distinct scope domains touched (`db` / `backend` / `frontend` / `infra`) | ≤ 2 | Multi-domain features are nearly always too big |
| Haiku-estimated files changed | ≤ 15 (soft) | Soft signal — adds a `risk_flag`; only contributes to a hard fail if wildly above (e.g., > 25) |

Any hard breach → `hard_blockers.append({reason: "feature_too_large", details, suggested_split})`. The same Haiku call is asked to populate `suggested_split` in a follow-up section of its prompt — only emitted if the rubric is breached. No extra LLM calls.

`PlanGate` is a SFN `Choice` that routes to `MarkBlocked` if `hard_blockers.length > 0`. `MarkBlocked` posts a structured Notion comment with the suggested split:

> 🛑 Factory cannot run this feature in one pass — it's too large.
> Detected: N stories, M criteria, touches X+Y.
> Suggested decomposition (paste each as a separate Ready-to-Build feature):
> 1. ...
> 2. ...

The rubric file `.factory/feature-sizing-rubric.md` is committed in the repo so humans writing Notion features can self-size.

### 2.3 RalphLoop — the implementer

Two parts: an SFN-native iterator, and a container Lambda that runs **one** Claude Code turn per iteration.

#### 2.3.1 Iterator (Step Functions)

```
LoopInit              (Pass)    — iter=0, input_tokens=0, output_tokens=0,
                                  validate_repair_count=0, review_repair_count=0
LoopChoice            (Choice)  — exit on: completion_signal=true,
                                  iter>=6, input_tokens>=2_000_000
RalphTurn             (Task)    — one Lambda invocation
LoopBump              (Pass)    — iter+=1, accumulate tokens, copy completion_signal
                  → back to LoopChoice
```

**Hard caps per feature:** 6 Ralph turns, 2M input tokens, 200K output tokens. Any breach → `MarkBudgetExceeded`, mark Notion `Failed`, alarm.

#### 2.3.2 RalphTurn Lambda (container image)

The architecturally critical Lambda. Container Lambda from `public.ecr.aws/lambda/nodejs:20` with `@anthropic-ai/claude-code` installed and Python 3.12 alongside.

Per-turn flow:
1. Download S3 workspace tree to `/tmp/ws`. Restore `.git` (stored as a tarball in S3 between turns to preserve commit history).
2. Read `prd.json`, `progress.txt`, and (if present) `repair_context.md`.
3. Compose the prompt:
   - **System prompt** = repo `CLAUDE.md` + `.factory/implementer-system.md`
   - **User prompt** = `prd.json` + `progress.txt` + `repair_context.md` (if any)
4. Invoke `claude -p --model claude-sonnet-4-6 --max-turns 30 --output-format json --dangerously-skip-permissions` against `/tmp/ws`.
5. After Claude Code exits: parse JSON output for token counts, scan workspace for changed files, regenerate `progress.txt` (append "this turn touched: …; outstanding: …"), upload to S3.
6. Apply the **filesystem allowlist** — reject and DENY in `repair_context.md` any path under `.github/workflows/*`, `.factory/*` (except the literal `.factory/_DONE_` sentinel, which is allowed), `infra/factory/*`, or any `..`/absolute path.
7. Return `{ iter, completion_signal, files_changed, input_tokens, output_tokens, claude_session_id }`.

**Completion signal** = `.factory/_DONE_` sentinel file present **OR** every story's `passes: true` in `prd.json`. Belt-and-braces.

**Lambda timeout** = 14 min (1 min headroom under Lambda's 15-min hard cap). On timeout, return `completion_signal: false` and let the iterator continue.

**Why fresh sessions per turn (no `--continue`)**: matches snarktank/ralph's design — Claude sees its own previous work via the workspace and git history, not via session-state. Simpler Lambda state model; no session-id manifest to maintain across turns.

### 2.4 Validate

**Validate Lambda** *(new — `validate-v2`, container image. The existing `validate-workspace` Lambda is replaced because it carried per-agent ownership routing that the new architecture removes; the build pipeline for the new container can crib from the existing one's Dockerfile to save effort.)*. Single deterministic stage. Materializes workspace, runs in order:

1. `ruff check` (in-process Python API)
2. `mypy --explicit-package-bases app/` (in-process)
3. `pytest --collect-only -q tests/`, then `pytest tests/ -x -q` (subprocess; isolated workspace deps from `tests/requirements.txt` + `requirements.txt`)
4. If `infra/*.tf` present: `terraform fmt -check` + `terraform init -backend=false` + `terraform validate`
5. If `frontend/` present: `tsc --noEmit -p frontend/tsconfig.json`
6. If `app/db/migrations/` changed: `alembic check`

Returns `{ passed: bool, issues: [{tool, file, line, output, hint}, ...] }`. **No agent-ownership routing** — that was the whole point of removing FanOut. On `passed: false`, the issues list is written to S3 as `repair_context.md` and the SFN routes to **ValidateRepair** (one Ralph turn → re-validate, max 2 cycles). After 2 cycles → `MarkValidateFailed`.

### 2.5 Review

**Review Lambda** *(new — collapses today's planned security-reviewer + code-reviewer + migration-safety into one)*. Single Sonnet 4.6 call.

Input bundle assembled in the Lambda:
- `prd.json`
- `git diff main..HEAD` (capped at 50KB; truncated tail with marker)
- `CLAUDE.md`

System prompt: `.factory/reviewer-system.md` (committed in repo). Categories enforced:
- **Security** — secrets in code, missing auth, IAM over-privilege, injection
- **Tenancy / RLS** — every query filters by `buyer_org_id`
- **Spec compliance** — diff matches acceptance criteria
- **Migration safety** — only when migrations changed: backward compat, NOT NULL defaults, reversibility, RLS on new tables, online-safe ops

Output (structured JSON, schema-validated by the Lambda):

```jsonc
{
  "passed": false,
  "blockers": [
    { "category": "tenancy",
      "file": "app/repositories/engagement.py",
      "line": 42,
      "description": "list_engagements does not filter by buyer_org_id",
      "fix": "Add WHERE buyer_org_id = :buyer_org_id to the query" }
  ],
  "warnings": []
}
```

On `blockers.length > 0`: SFN writes blockers to `repair_context.md`, runs **one** Ralph turn, re-runs validate, re-runs review. Max 2 review-repair cycles. After 2 → `MarkReviewFailed`.

### 2.6 Ship

- **CommitAndPush** *(existing — small change)* — materializes the S3 workspace, writes `.factory/last-run/{prd.json,review.json,progress.txt}` for the postdeploy probe and traceability, then `git add -A` and commits with a deterministic message: `feat(factory): <PRD title>\n\n<PRD narrative_md, truncated to 4KB>\n\nfactory-execution: <execution-id>`. Push to `feature/<feature_id>`. The implementer is **not** asked to author commit messages — it's deterministic glue. (Note: this Lambda runs *after* RalphTurn and is not subject to the §4.3 filesystem allowlist; the allowlist applies only to the RalphTurn post-turn upload step.)
- **OpenPR** *(existing — small body change)* — `gh pr create`; body includes the PRD + reviewer JSON.
- **WaitForQualityGates** *(existing)* — task token wait; `quality-gates.yml` calls back through the existing callback API after CI passes and merges to `main`. SFN `TimeoutSeconds: 5400` (90 min) on the wait.
- **MarkDone / ReleaseLock** *(existing)*.

### 2.7 Post-deploy verification (separate state machine)

`nova-factory-postdeploy` — triggered by an EventBridge rule on the `deploy.yml` workflow_run completion event for the `main` branch.

- **ProbeStaging Lambda** — reads `prd.json` from the merged commit's `.factory/last-run/prd.json` (CommitAndPush writes this file deterministically — see §2.6). Constructs HTTP probes from acceptance criteria that mention HTTP verbs/paths. Executes against `STAGING_URL` with `nova/factory/staging-verifier-token` from Secrets Manager. Returns `{ passed, probes[], failures[] }`. 10-second probe timeout.
- **RevertMerge Lambda** *(only on fail)* — uses `gh` to revert the merge commit on `main`, opens a revert PR (which `quality-gates.yml` auto-merges since it's a revert with passing tests), updates the original Notion feature to `status=Failed`, `reason=deploy_verification_failed`.

This is a separate state machine because the main pipeline finishes the moment the PR is merged. Verification of the deployed code is a different timing concern (waits for ECS rollout) and shouldn't hold the main lock open.

### 2.8 Self-pause + observability

- **Self-pause** — Parameter Store `/nova/factory/paused` (default `false`). The relay Lambda reads it on every webhook delivery; if `true`, posts a Notion comment ("Factory currently paused — see CloudWatch alarms") and returns 200. CloudWatch alarms on (a) 3 consecutive `ExecutionsFailed`, (b) $100/month budget breach, both flip the flag via a tiny `auto-pause` Lambda subscribed to the alarm SNS topic.
- **Observability** — keep today's `nova-factory` CloudWatch dashboard. Update widgets to show: turns-per-feature, tokens-per-feature, time-per-stage, validate/review repair rates. Replace `agent-calls-summary` Logs Insights query with `ralph-turn-summary`.

---

## 3. Data flow

### 3.1 S3 layout (per execution)

```
s3://nova-factory-workspaces-577638385116/<execution-id>/
  intake/
    spec_raw.md
    feature_meta.json
  plan/
    prd.json
  workspace/
    .git.tar.gz                 — preserved across Ralph turns
    <full repo tree>
    progress.txt                — Ralph's running notes (each turn appends)
    repair_context.md           — present only when validate/review failed last cycle
    .factory/_DONE_             — completion sentinel (presence = done)
  validate/
    issues.json
  review/
    blockers.json
  artifacts/
    final-diff.patch            — for PR body
    last-run-summary.json       — also committed to main at .factory/last-run/
                                  for the postdeploy probe to read
```

S3 lifecycle: 7-day expiration on workspace prefixes. Intake/plan retained 90 days for postmortem.

### 3.2 SFN payload shape

```jsonc
{
  "feature_id":   "<notion-uuid>",
  "execution_id": "<sfn-execution-name>",
  "loop": {
    "iter": 3,
    "input_tokens": 412000,
    "output_tokens": 28100,
    "completion_signal": false,
    "validate_repair_count": 0,
    "review_repair_count": 0
  },
  "plan":     { "Payload": { "hard_blockers": [], "scope": {...} } },
  "validate": { "Payload": { "passed": false, "issues": [...] } },
  "review":   { "Payload": { "passed": false, "blockers": [...] } }
}
```

---

## 4. Error handling, idempotency, sandbox

### 4.1 Failure modes and responses

| Failure | Response |
|---|---|
| Notion webhook double-delivers | Relay Lambda dedups by Notion `event_id` (DDB conditional put, 24h TTL). |
| Feature already in-flight | `acquire_lock` collision → 200 silently with Notion comment. |
| Notion / Anthropic / GitHub API 5xx | SFN `Retry`: 3 attempts, exponential backoff, jitter. Final fail → terminal `Failed` with reason. |
| Plan returns `hard_blockers[]` | Skip Ralph entirely → `MarkBlocked`, free run cost ≈ one Haiku call. |
| RalphTurn hits 14-min timeout | Turn returns `completion_signal: false`; iterator continues. |
| 2 consecutive RalphTurns return zero file changes | Iterator short-circuits to `Validate` early. |
| Token budget breach | `MarkBudgetExceeded`, mark Notion `Failed`, alarm. |
| Validate fails after 2 repair cycles | `MarkValidateFailed`, write `issues.json` to Notion comment. |
| Review blockers persist after 2 repair cycles | `MarkReviewFailed`, write `blockers.json` to Notion comment. |
| `gh pr create` fails | SFN retry; persistent → `MarkFailed`, branch + workspace preserved. |
| Quality-gates CI fails | Callback returns `passed: false` + test output. SFN routes to **one** Ralph turn with the failures, re-validates. Capped at one CI-repair cycle. |
| `WaitForQualityGates` token never returns | SFN 90-min timeout → `MarkFailed`. |
| Postdeploy probe fails | `RevertMerge` Lambda. If revert PR also fails → SNS pages on-call. |
| 3 consecutive `ExecutionsFailed` | CloudWatch alarm → SNS → `auto-pause` Lambda flips Parameter Store flag. |

### 4.2 Idempotency invariants

- Webhook delivery dedup'd by Notion `event_id`.
- `acquire_lock` is conditional; collisions are no-op successes.
- RalphTurn re-runs for the same `iter` are safe (S3 overwritten, git history preserved).
- Branch push uses fixed `feature/<feature_id>`; force-push-with-lease acceptable.
- `MarkDone` Notion update is a no-op if status already `Done`.
- `RevertMerge` checks whether `main` HEAD is already a revert; if yes, just updates Notion.

### 4.3 Sandbox boundaries (8 layers)

1. **GitHub PAT scope** — fine-grained, single-repo, `contents:write` + `pull_requests:write` only. **No** `workflow` scope, **no** `admin`. Prevents factory commits from editing CI or branch protection.
2. **Branch protection on `main`** — required check `quality-gates`; restrict push to bot identity; no admin override; signed commits required.
3. **Lambda IAM least privilege** — RalphTurn IAM allows S3 read/write to its own execution prefix only, Secrets Manager read for `nova/factory/anthropic-api-key` only, CloudWatch logs. **No** broad AWS, **no** Notion DB access (that's a separate Lambda with a separate scoped Notion key).
4. **Filesystem allowlist on workspace upload** — reject `.github/workflows/*`, `.factory/*`, `infra/factory/*`, `..`, absolute paths. Rejected writes appended to `repair_context.md` as `DENIED: ...`.
5. **Reviewer sees diff, not reasoning** — separate Sonnet call, separate prompt. Reviewer has no access to the implementer's reasoning trace.
6. **Token-budget hard stop** — caps blast radius from a stuck loop.
7. **SFN concurrency cap of 3** — relay Lambda counts in-flight executions in DDB and refuses if ≥ 3. Caps in-flight features.
8. **Auditability** — every commit message includes `factory-execution: <execution-id>`; SFN executions retained 1 year; every Anthropic call logs `feature_id` + `execution_id` + `turn` + token counts to CloudWatch.

### 4.4 Irreducible human touchpoints

The factory is fully autonomous in the operating sense. Three things remain human:
1. Write the feature description in Notion.
2. Resume after auto-pause (3-failure tripwire or budget-ceiling tripwire).
3. Approve non-free-tier AWS resource choices. The Plan stage rubric flags any resource that breaches the cost-policy whitelist in CLAUDE.md as a `hard_blocker` with reason `non_free_tier_resource_unconfirmed`; PlanGate routes to `MarkBlocked` with the proposed resource and rationale in the Notion comment. Human approves by editing the feature description to acknowledge the cost trade-off (e.g., adding `cost_approved: true` to the Notion props), then re-files.

---

## 5. Cost model

### 5.1 Per-feature cost

Sonnet 4.6 + Haiku 4.5 pricing with prompt caching enabled.

| Stage | Model | Tokens (input / output) | Cost |
|---|---|---|---|
| Plan | Haiku 4.5 | 5K / 1.5K | $0.013 |
| RalphLoop (typical, 4 turns) | Sonnet 4.6 | 4×(4K cached + 22K uncached) / 4×9K | $0.61 |
| RalphLoop (worst case, 6 turns + repairs) | Sonnet 4.6 | 6×(4K cached + 26K uncached) / 6×11K | $1.38 |
| Review | Sonnet 4.6 | 30K / 3K | $0.135 |
| Lambda compute (typical, in free tier) | — | — | $0 |
| Lambda compute (post-free-tier) | — | ~3,600 GB-sec | $0.060 |
| S3 + DDB + SFN + CW | — | — | < $0.01 |
| **Per-feature, typical** | | | **~$0.76** |
| **Per-feature, worst case** | | | **~$1.59** |

### 5.2 Free-tier coverage

| AWS service | Permanent free tier | Capacity at our shape |
|---|---|---|
| Lambda compute | 400K GB-sec/month | ~110 features/month |
| Lambda requests | 1M/month | ~66K features/month |
| Step Functions | 4,000 transitions/month | ~130 features/month |
| S3 | 5 GB | unlimited at 5MB × 7-day TTL |
| DynamoDB | 25 GB on-demand | unlimited |

**At 50 features/month we stay entirely within Lambda free tier.** Dominant cost = LLM tokens.

### 5.3 Monthly envelope

| Volume | Typical | Worst case |
|---|---|---|
| 10 features/month | $7.60 | $15.90 |
| 50 features/month | $38 | $79.50 |
| 100 features/month | $76 | $159 + ~$6 over-free |
| 200 features/month | $152 + ~$6 | $318 + ~$13 |

### 5.4 Budget tripwires

1. **$20/month** *(existing)* — early-warning email.
2. **$50/month** *(new)* — secondary alarm; posts a Notion comment on the latest in-flight feature.
3. **$100/month** *(new — hard ceiling)* — flips `/nova/factory/paused = true`, pages on-call.

### 5.5 Cost levers (post-launch, only if needed)

1. Tighten implementer system prompt + per-agent CLAUDE.md context bundles.
2. Downgrade reviewer to Haiku (saves ~$0.10/feature at quality cost).
3. Reduce Ralph turn cap from 6 to 4 if features regularly succeed in 3.
4. Cache `git diff` portion of reviewer input.
5. Migrate to Bedrock (regional pricing).

---

## 6. Cleanup, migration, cutover

### 6.1 What we keep, delete, add

| Category | Keep | Delete (after cutover stable) | Net new |
|---|---|---|---|
| **Lambdas** | acquire-lock, release-lock, commit-and-push, update-notion, trigger-quality-gates, handle-quality-gate-callback | load-spec, load-project-context, run-orchestrator, run-agent, evaluate-security, validate-workspace (replaced) | load-feature, plan, **ralph-turn (container)**, validate-v2, review, post-deploy-probe, revert-merge, auto-pause |
| **State machines** | — | `nova-factory-pipeline` (v1) | `nova-factory-v2`, `nova-factory-postdeploy` |
| **ECR** | — | `nova-factory-validators` (old image) | `nova-factory-ralph-turn`, `nova-factory-validator` |
| **DynamoDB** | nova-factory-locks, nova-factory-runs | — | (no schema changes) |
| **S3** | nova-factory-workspaces-577638385116 | — | (workspace layout reorg only) |
| **Secrets Manager** | all `nova/factory/*` | — | `nova/factory/staging-verifier-token` |
| **Parameter Store** | — | — | `/nova/factory/paused` |
| **API Gateway** | webhook relay, callback API | — | — |
| **CloudWatch** | dashboard, alarm, budget, SNS topic | — (rebuild widgets for v2 stages) | EventBridge rule for postdeploy SFN; second alarm at $50; third at $100 |
| **GitHub Actions** | quality-gates.yml, deploy.yml | factory.yml (after 30 days stable) | — |
| **Repo agent prompts** | — | `.claude/agents/*.md` (all 9), `scripts/factory_lambdas/agent_prompts/*.md` | `.factory/implementer-system.md`, `.factory/reviewer-system.md`, `.factory/prd.schema.json`, `.factory/feature-sizing-rubric.md` |
| **Repo legacy code** | — | `scripts/factory_run.py`, `scripts/agents.py` | — |
| **Webhook config** | — | `FACTORY_BACKEND="github-actions"` mode | flip to `step-functions-v2` |

### 6.2 Cutover sequence (no dark windows)

1. Build v2 in parallel — new state machine + new Lambdas live alongside v1. Webhook still routes to v1.
2. Run 3 synthetic smoke features against v2 manually (`scripts/factory_smoke.sh` repointed at v2 ARN).
3. Once 3 consecutive smokes go `Done`, flip `FACTORY_BACKEND` to `step-functions-v2`. Deploy. Test on a real Notion feature.
4. Wait 30 days of stable operation. Then `terraform destroy` of the v1 module to remove old resources.

### 6.3 Terraform state migration

CLAUDE.md requires Terraform state in S3, but `infra/factory/terraform.tfstate` is currently local (per the execution-summary doc). Migrate during the rebuild via `terraform init -migrate-state` against the existing state bucket `nova-terraform-state-577638385116`. Removes the "all factory state lives on Christopher's laptop" failure mode.

### 6.4 Repo CLAUDE.md updates

The repo CLAUDE.md "Factory" section gets rewritten to describe the v2 pipeline: Notion → SFN-v2 → Plan → RalphLoop → Validate → Review → PR → quality-gates → MarkDone. The 9-agent description is removed.

`.claude/settings.json` (or `.claude/settings.local.json`) gets a permission allowlist tuned for the new Lambda development workflow:
- Allow: `Bash(aws stepfunctions *)`, `Bash(aws lambda *)`, `Bash(terraform *)`, `Bash(docker build *)`, `Bash(docker push *)`, `Bash(gh pr *)`
- Allow MCP: existing
- The factory's *own* container Lambda runs `claude -p --dangerously-skip-permissions` (the Lambda IAM is the security boundary).

---

## 7. Acceptance criteria

This spec is met when **all** of the following are true:

1. **Branch state**: clean `git status` on `factory-overhaul-2026-05-03`; v1 plans archived under `docs/superpowers/plans/archive/`.
2. **State machine**: `nova-factory-v2` exists; the iterator pattern in §2.3.1 is implemented; v1 `nova-factory-pipeline` is still alive but no longer routed to.
3. **Plan stage**: `Plan` Lambda emits `prd.json` matching `.factory/prd.schema.json`; sizing rubric blocks the synthetic "too-big-feature" test fixture with a populated `suggested_split`.
4. **RalphTurn**: container image Lambda runs `claude -p` against the materialized workspace; produces commits in the in-Lambda `.git`; respects the filesystem allowlist (verified by a synthetic "tries-to-edit-workflows" test fixture that should be DENIED and surfaced in `repair_context.md`).
5. **Validate**: single `validate-v2` Lambda runs the 6-step deterministic chain; emits `issues.json` with structured fields.
6. **Review**: single `review` Lambda emits a JSON object matching the §2.5 schema; on a synthetic "missing tenancy filter" test fixture, returns `passed: false` with a `tenancy` blocker.
7. **Smoke**: 3 consecutive synthetic smoke features complete with `Done` in Notion. The smoke fixtures live at `scripts/factory_smoke_fixtures/{trivial,medium,oversized}.json`.
8. **Real cutover**: `FACTORY_BACKEND="step-functions-v2"`; one real Notion-triggered feature reaches `Done` end-to-end.
9. **Postdeploy SFN**: `nova-factory-postdeploy` exists; an injected staging-failure test fixture triggers `RevertMerge` and re-files the feature with `Failed`.
10. **Self-pause**: forcing 3 synthetic failures flips `/nova/factory/paused = true`; a subsequent webhook delivery is silently dropped with a Notion comment.
11. **Cost discipline**: synthetic budget-breach test (200K-output-tokens injected by short-circuit) terminates the run with `MarkBudgetExceeded`.
12. **Observability**: `nova-factory` CloudWatch dashboard shows turns-per-feature, tokens-per-feature, time-per-stage; three saved Logs Insights queries (`ralph-turn-summary`, `validation-failures`, `execution-trace`) appear under `nova-factory/`.
13. **Cleanup**: v1 Lambdas removed from `lambdas.tf`; `.claude/agents/*.md` and `scripts/factory_lambdas/agent_prompts/*.md` deleted; `factory.yml` retained but explicitly deprecated (banner in the workflow file).
14. **Memory updates**: `project_nova_status.md` and `reference_factory_runtime.md` reflect the new v2 architecture; old plans archived.

---

## 8. Out of scope (explicitly deferred)

- **Bedrock-native invocation** (deferred Phase C of stabilization plan) — only worth doing once v2 is stable and we have data.
- **Per-domain context bundles** for the implementer — only worth doing once token cost data shows it's worth the engineering.
- **Splitting reviewer into multiple specialized reviewers** — only worth doing once miss-rate data justifies a split.
- **Multi-feature parallel execution** — concurrency cap stays at 3 for v2; loosen later.
- **Bedrock AgentCore for the implementer** — same family of concerns; defer.
- **Application code** — this rebuild is the factory only. App features (auth, engagements, scans) remain to be built *by* the factory after cutover.
