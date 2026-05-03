# Factory Incident Runbook

## 1. Stuck execution — DynamoDB lock won't release

**Symptom:** A new feature build fails immediately with "FeatureLocked: already being processed by another execution", but no execution is actually running.

**Cause:** A previous execution crashed before reaching the `ReleaseLock` state (e.g., Lambda timeout, account quota).

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

Then re-trigger the feature from Notion (set status back to "Ready to Build").

---

## 2. Step Functions hangs at WaitForQualityGates

**Symptom:** The execution is stuck in `WaitForQualityGates` state and `quality-gates.yml` either never ran or failed to POST the callback.

**Fix — manually send success:**
```bash
# Get the task token from the execution history
EXEC_ARN="arn:aws:states:us-east-1:577638385116:execution:nova-factory-pipeline:EXEC_NAME"

TASK_TOKEN=$(aws stepfunctions get-execution-history \
  --execution-arn "$EXEC_ARN" \
  --query 'events[?type==`TaskScheduled`] | [-1].taskScheduledEventDetails.parameters' \
  --output text | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['TaskToken'])")

aws stepfunctions send-task-success \
  --task-token "$TASK_TOKEN" \
  --task-output '{"passed": true, "logs_url": "manual"}'
```

**Fix — manually send failure (and mark Notion Failed):**
```bash
aws stepfunctions send-task-failure \
  --task-token "$TASK_TOKEN" \
  --error "QualityGateFailure" \
  --cause "Manual failure — quality gates did not run"
```

---

## 3. Anthropic outage — pause the webhook

**Symptom:** Multiple executions failing at agent Lambda steps with Anthropic API errors.

**Fix — pause new triggers (flip backend to a no-op):**
```bash
# Edit infra/webhook-relay/main.tf
# Change: FACTORY_BACKEND = "step-functions"
# To:     FACTORY_BACKEND = "paused"
cd /c/Claude/Nova/nova
terraform -chdir=infra/webhook-relay apply -auto-approve
```

The `index.js` webhook Lambda already has no-op handling for unknown backends — it logs and returns 200 without dispatching. In-flight executions continue; new Notion webhooks are silently dropped.

**Restore:**
```bash
# Revert FACTORY_BACKEND = "step-functions" and apply again
```

---

## 4. Useful diagnostic commands

```bash
# List recent executions
aws stepfunctions list-executions \
  --state-machine-arn arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-pipeline \
  --max-results 10

# Describe a specific execution
aws stepfunctions describe-execution --execution-arn <ARN>

# Get full execution history (all state transitions)
aws stepfunctions get-execution-history --execution-arn <ARN>

# Check what's in the S3 workspace for an execution
aws s3 ls s3://nova-factory-workspaces-577638385116/<execution-id>/

# Tail Lambda logs for run_agent
aws logs tail /aws/lambda/nova-factory-run-agent --follow

# Check DynamoDB runs table for an execution
aws dynamodb query \
  --table-name nova-factory-runs \
  --key-condition-expression "execution_id = :e" \
  --expression-attribute-values '{":e":{"S":"EXEC_ID"}}'
```
