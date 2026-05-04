# Factory Incident Runbook

Incident response for the **Nova Software Factory v2**. For the architecture
overview and routine operations, see [`docs/factory/README.md`](../factory/README.md).

> Git Bash on Windows: prefix AWS CLI calls that take parameter names
> starting with `/` with `MSYS_NO_PATHCONV=1`.

---

## 0. First response — pause the factory

If anything looks wrong and you need to stop dispatches without interrupting
in-flight work, flip the pause flag:

```bash
MSYS_NO_PATHCONV=1 aws ssm put-parameter \
  --name /nova/factory/paused --value true --type String --overwrite
```

The webhook relay reads this on every Notion delivery; paused = 200-OK with a
Notion comment. In-flight SFN executions continue normally.

To resume:

```bash
MSYS_NO_PATHCONV=1 aws ssm put-parameter \
  --name /nova/factory/paused --value false --type String --overwrite
```

The factory **does not auto-unpause** when alarms return to OK — humans reset
deliberately.

---

## 1. Stuck execution — DynamoDB lock won't release

**Symptom:** A new feature build fails immediately at `AcquireLock` with
"FeatureLocked: already being processed by another execution", but no
execution is actually running.

**Cause:** A previous execution crashed before reaching `ReleaseLock` (Lambda
hard-timeout, account quota hit, transient AWS error).

**Fix:**
```bash
# Find the stuck lock
aws dynamodb scan \
  --table-name nova-factory-locks \
  --filter-expression "attribute_exists(feature_id)"

# Delete the stuck lock (replace FEATURE_ID with the Notion page UUID)
aws dynamodb delete-item \
  --table-name nova-factory-locks \
  --key '{"feature_id": {"S": "FEATURE_ID"}}'
```

Then re-trigger the feature from Notion (toggle status to "Idea" then back to
"Ready to Build").

---

## 2. Step Functions stuck at `WaitForQualityGates`

**Symptom:** Execution sits in `WaitForQualityGates` past 10 minutes with no
state change. `quality-gates.yml` either never ran or failed to POST the
callback.

**Diagnose:** Check whether the workflow ran:

```bash
gh run list --workflow quality-gates.yml --repo nabbic/nova --limit 5
```

**Fix — manually send success (replace EXEC_ARN):**
```bash
EXEC_ARN="arn:aws:states:us-east-1:577638385116:execution:nova-factory-v2:EXEC_NAME"

# Pull the task token from the WaitForQualityGates TaskScheduled event
TASK_TOKEN=$(python -c "
import boto3, json
c = boto3.client('stepfunctions')
events = c.get_execution_history(executionArn='$EXEC_ARN', reverseOrder=True, maxResults=200)['events']
for e in events:
    d = e.get('taskScheduledEventDetails')
    if d and 'WaitForQualityGates' in str(events):
        params = json.loads(d['parameters'])
        print(params['Payload']['task_token'])
        break
")

aws stepfunctions send-task-success \
  --task-token "$TASK_TOKEN" \
  --task-output '{"passed": true, "logs_url": "manual"}'
```

**Fix — manually send failure:**
```bash
aws stepfunctions send-task-failure \
  --task-token "$TASK_TOKEN" \
  --error "QualityGateFailure" \
  --cause "Manual failure — quality gates did not run"
```

The `Catch` arm routes to `MarkFailedAndRelease`, which marks the Notion page
`Failed` and releases the lock cleanly.

---

## 3. Anthropic outage — pause the webhook

**Symptom:** Multiple RalphTurn or Plan/Review Lambda invocations fail with
Anthropic API errors (5xx, rate-limit at unusual rates).

**Fix:** flip the pause flag (see section 0). In-flight executions continue
(and may fail at the next Anthropic call → that trips
`MarkFailedAndRelease`). New Notion webhooks are dropped with a comment.

When Anthropic recovers, set the flag back to `false`. There is no automatic
retry of dropped webhooks — humans re-trigger affected features by toggling
their Notion status.

---

## 4. RalphTurn keeps timing out (14 min)

**Symptom:** RalphTurn returns `completion_signal: false` repeatedly because
the Lambda hits its 14-minute hard cap before claude finishes a turn.

**Diagnose:**
```bash
MSYS_NO_PATHCONV=1 aws logs tail /aws/lambda/nova-factory-ralph-turn --since 30m \
  --format short | grep -E "claude exit|invoking claude"
```

If `claude exit=` shows elapsed close to 780s, claude is running too long
per inner turn. If `claude exit=1 subtype=error_max_turns`, claude is
hitting the inner `--max-turns 30` cap (this is benign — preserves progress,
loop iterator continues).

**Fix:**
- If feature is genuinely too big, the sizing rubric should have caught it
  at Plan; check `s3://.../<exec>/plan/prd.json` for `hard_blockers` —
  the rubric may need tightening (see [`scripts/factory_lambdas/common/sizing.py`](../../scripts/factory_lambdas/common/sizing.py)).
- For one-off cases, manually stop the execution (`aws stepfunctions stop-execution`)
  and re-file the feature with narrower scope.

---

## 5. Validate keeps flagging the same false positive

**Symptom:** Validate fails 3× across all repair turns, hits
`MarkValidateFailed`, on issues that aren't actually the implementer's
problem (e.g., pre-existing test failures, vendored code, environmental
flakiness).

**Diagnose:**
```bash
EXEC_NAME=<from list-executions>
aws s3 cp s3://nova-factory-workspaces-577638385116/$EXEC_NAME/validate/issues.json -
```

**Fix paths:**

- **Pre-existing repo state issue** (e.g., vendored `infra/factory/lambda-layer/python/`):
  edit `scripts/factory_lambdas/containers/validate_v2/validate_v2.py` to skip the
  affected check (e.g., add to `RUFF_EXCLUDES`), rebuild + push:
  ```bash
  bash scripts/factory_lambdas/containers/validate_v2/build.sh
  cd infra/factory && terraform apply -auto-approve -var=github_owner=nabbic
  ```
  Then re-trigger the feature.
- **Real bug claude can't fix in 2 turns**: the sizing rubric should likely
  have caught this; mark the feature `Failed` in Notion with the diagnosis
  and re-file as a smaller decomposition.

---

## 6. Postdeploy probe failed — feature got reverted

**Symptom:** A feature reached `Done`, then `nova-factory-postdeploy` ran
and `RevertMerge` opened a revert PR. Notion is now `Failed` with
`reason=deploy_verification_failed`.

**Diagnose:**
```bash
aws stepfunctions list-executions \
  --state-machine-arn arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-postdeploy \
  --max-results 5
EXEC_ARN=<the failed one>
aws stepfunctions describe-execution --execution-arn "$EXEC_ARN" --query output --output text \
  | python -c "import json,sys; d=json.loads(sys.stdin.read()); print(json.dumps(d['probe']['Payload']['failures'], indent=2))"
```

The `failures` array shows which probe(s) failed and the actual_status seen.

**Fix:**
- If the bug is real: leave the revert PR merged, fix the issue (manually or
  by re-filing in Notion).
- If the probe is wrong (e.g., spec criteria didn't match deployed reality):
  edit [`scripts/factory_lambdas/common/probe.py`](../../scripts/factory_lambdas/common/probe.py) to tighten the parser, or
  rewrite the PRD's acceptance criteria with cleaner HTTP-shape language.

---

## 7. Auto-pause fired — diagnose before resuming

**Symptom:** `/nova/factory/paused` is `true`. You didn't set it manually.

**Diagnose what tripped it:**
```bash
# Recent alarm history
aws cloudwatch describe-alarm-history \
  --alarm-name nova-factory-v2-execution-failures \
  --max-records 5 --query 'AlarmHistoryItems[].{ts:Timestamp,sum:HistorySummary}' --output table

# auto_pause Lambda logs (it logs the trigger)
MSYS_NO_PATHCONV=1 aws logs tail /aws/lambda/nova-factory-auto-pause --since 24h --format short
```

**Common causes:**
- 3+ executions hit `MarkValidateFailed` or `MarkReviewFailed` in 15 min →
  fix the underlying issue (often a flaky test or stale dep).
- $50 or $100 budget threshold hit → check costs in CloudWatch / Cost
  Explorer; could be unusual feature volume or a stuck Lambda burning tokens.

**Resume only after the root cause is understood:**
```bash
MSYS_NO_PATHCONV=1 aws ssm put-parameter \
  --name /nova/factory/paused --value false --type String --overwrite
```

---

## 8. Useful diagnostic commands

```bash
# List recent v2 executions
aws stepfunctions list-executions \
  --state-machine-arn arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-v2 \
  --max-results 10

# Describe a specific execution
aws stepfunctions describe-execution --execution-arn <ARN>

# State-by-state history (boto3 avoids AWS CLI charmap issues on Windows)
python -c "
import boto3
c = boto3.client('stepfunctions')
for e in c.get_execution_history(executionArn='<ARN>', reverseOrder=False, maxResults=200)['events']:
    name = (e.get('stateExitedEventDetails') or e.get('stateEnteredEventDetails') or {}).get('name', '')
    if name: print(e['timestamp'], e['type'], name)
"

# What's in the S3 workspace for an execution
aws s3 ls s3://nova-factory-workspaces-577638385116/<execution-id>/ --recursive

# Tail any factory Lambda
MSYS_NO_PATHCONV=1 aws logs tail /aws/lambda/nova-factory-<name> --follow

# Check the runs table
aws dynamodb query \
  --table-name nova-factory-runs \
  --key-condition-expression "execution_id = :e" \
  --expression-attribute-values '{":e":{"S":"EXEC_ID"}}'
```
