# Factory v2 — Phase 5: Self-Pause + Budgets + Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Operational hardening for the v2 factory. Add the self-pause tripwire (Parameter Store `/nova/factory/paused`), the budget alarms ($20 / $50 / $100), the auto-pause Lambda that flips the flag on alarm-triggered SNS, the webhook-relay update that honors the flag, and the v2 CloudWatch dashboard widgets + saved Logs Insights queries.

**Architecture:** Two SNS topics already exist from v1 (`nova-factory-alerts` for execution failures). We add two more triggers (50/100 dollar budgets), wire all alerts to a new `auto_pause` Lambda subscribed to the SNS topic, and have it flip `/nova/factory/paused = true` in Parameter Store. The webhook relay reads this flag at every delivery — when `true`, it short-circuits, posts a Notion comment, and returns 200. Dashboard widgets and saved queries are the operational view.

**Tech Stack:** Lambda (zip), AWS Budgets, CloudWatch (alarms + dashboard + Logs Insights), SNS, Parameter Store, Terraform.

**Predecessors:** Phases 1–4 complete. v2 SFNs (`nova-factory-v2`, `nova-factory-postdeploy`) are running synthetic smokes successfully. **This plan assumes Phase 4 is complete.**

**Branch:** `factory-overhaul-2026-05-03`. Working directory: `C:\Claude\Nova\nova`. AWS account `577638385116`, region `us-east-1`.

**Out of scope for Phase 5:** Cutover (Phase 6) — the webhook still routes to v1 until Phase 6 flips `FACTORY_BACKEND="step-functions-v2"`. Phase 5 only ensures v2 is *safe to flip to* by hardening its pause/budget/observability surface.

---

## File Structure

**Create:**

| Path | Responsibility |
|---|---|
| `scripts/factory_lambdas/handlers/auto_pause.py` | SNS-triggered Lambda. Reads the SNS message, decides whether the alarm is one of our pause triggers, flips `/nova/factory/paused = true` in Parameter Store, posts a single notification comment to the most recent in-flight Notion feature (best-effort). |
| `tests/factory/test_auto_pause.py` | Unit tests: SNS message parsing, Parameter Store flip, idempotency. |
| `infra/factory/parameter-store.tf` | `aws_ssm_parameter "factory_paused"` (default `false`). |
| `infra/factory/budgets.tf` | Three `aws_budgets_budget` resources at $20/$50/$100 with SNS notification. |
| `infra/factory/alarms-v2.tf` | New `nova-factory-v2-execution-failures` alarm (3 consecutive failures → SNS) replacing/parallel to v1 alarm. |
| `infra/factory/dashboard-v2.tf` | v2 dashboard JSON: turns-per-feature, tokens-per-feature, time-per-stage, validate/review repair rates, executions over time. |
| `infra/factory/logs-insights-queries.tf` | Three saved Logs Insights queries: `ralph-turn-summary`, `validation-failures`, `execution-trace`. |

**Modify:**

| Path | Change |
|---|---|
| `infra/webhook-relay/lambda/relay.py` | Read `/nova/factory/paused` on every delivery. If `true`, post a Notion comment and return 200 without forwarding. |
| `infra/webhook-relay/main.tf` | Grant the relay Lambda `ssm:GetParameter` on `/nova/factory/paused`. |
| `infra/factory/lambdas-v2.tf` | Add `auto_pause` to the `handlers_v2` map. |
| `infra/factory/iam.tf` | Grant `lambda_exec` `ssm:PutParameter` + `ssm:GetParameter` on `/nova/factory/paused`. |
| `scripts/factory_lambdas/handlers/auto_pause.py` | (Subscribed to SNS — see Lambda permission resource in `auto-pause-subscription.tf`.) |
| `infra/factory/dashboard.tf` | Old v1 dashboard kept until Phase 6 cleanup; no edit. |

**Delete:**

None. v1 dashboard/alarms stay until Phase 6 cleanup.

---

## Pre-flight

- [ ] **P-1: Phase 4 complete.**

```bash
pytest /c/Claude/Nova/nova/tests/factory/ -q
aws stepfunctions describe-state-machine --state-machine-arn arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-postdeploy --query status --output text
```
Expected: 55 tests pass; postdeploy SFN `ACTIVE`.

- [ ] **P-2: SNS alerts topic exists.**

```bash
aws sns list-topics --query 'Topics[?contains(TopicArn, `nova-factory-alerts`)].TopicArn' --output text
```
Expected: a single topic ARN ending in `nova-factory-alerts`.

- [ ] **P-3: Notion in-flight DB query is reachable.**

The auto_pause Lambda will look up the most-recent in-flight feature to comment on. Verify the Features DB ID is in Secrets Manager:

```bash
aws secretsmanager get-secret-value --secret-id nova/factory/notion-features-db-id --query 'SecretString != null' --output text
```
Expected: `True`.

---

### Task 1: Create the `/nova/factory/paused` Parameter Store flag

**Files:**
- Create: `infra/factory/parameter-store.tf`

- [ ] **Step 1: Add the Terraform resource.**

```hcl
resource "aws_ssm_parameter" "factory_paused" {
  name        = "/nova/factory/paused"
  description = "Boolean flag — when 'true', webhook deliveries 200-OK without dispatching."
  type        = "String"
  value       = "false"
  overwrite   = false  # Manage the slot's existence; the auto_pause Lambda flips the value.

  lifecycle {
    ignore_changes = [value]  # Lambda updates this — Terraform only owns existence.
  }

  tags = merge(local.common_tags, { Generation = "v2" })
}

output "factory_paused_param_name" {
  value = aws_ssm_parameter.factory_paused.name
}
```

- [ ] **Step 2: Apply.**

```bash
cd /c/Claude/Nova/nova/infra/factory
terraform apply -auto-approve
```
Expected: 1 new resource (`aws_ssm_parameter`).

- [ ] **Step 3: Verify default state.**

```bash
aws ssm get-parameter --name /nova/factory/paused --query Parameter.Value --output text
```
Expected: `false`.

- [ ] **Step 4: Commit.**

```bash
cd /c/Claude/Nova/nova
git add infra/factory/parameter-store.tf
git commit -m "infra(factory v2): add /nova/factory/paused SSM Parameter Store flag"
```

---

### Task 2: Implement auto_pause Lambda (TDD)

**Files:**
- Create: `scripts/factory_lambdas/handlers/auto_pause.py`
- Create: `tests/factory/test_auto_pause.py`

- [ ] **Step 1: Write tests.**

`tests/factory/test_auto_pause.py`:

```python
"""Tests for the auto_pause Lambda — flips /nova/factory/paused on SNS-delivered alarms."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

os.environ.setdefault("PAUSED_PARAM", "/nova/factory/paused")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "factory_lambdas"))


def _sns_event(message: dict) -> dict:
    return {"Records": [{"EventSource": "aws:sns", "Sns": {"Message": json.dumps(message)}}]}


def test_alarm_message_flips_flag():
    from handlers import auto_pause  # type: ignore

    ssm_calls: list[dict] = []

    class FakeSSM:
        def put_parameter(self, **kw):
            ssm_calls.append(kw)
        def get_parameter(self, **kw):
            return {"Parameter": {"Value": "false"}}

    msg = {"AlarmName": "nova-factory-v2-execution-failures", "NewStateValue": "ALARM", "NewStateReason": "3 consecutive failures"}
    with patch.object(auto_pause, "_ssm", FakeSSM()):
        result = auto_pause.handler(_sns_event(msg), None)

    assert result["paused"] is True
    assert ssm_calls and ssm_calls[0]["Value"] == "true"


def test_budget_message_flips_flag():
    from handlers import auto_pause  # type: ignore

    class FakeSSM:
        def __init__(self):
            self.puts = []
        def put_parameter(self, **kw):
            self.puts.append(kw)
        def get_parameter(self, **kw):
            return {"Parameter": {"Value": "false"}}

    fake = FakeSSM()
    msg = {"BudgetName": "nova-factory-monthly-100", "NotificationType": "ACTUAL", "NotificationState": "ALARM", "ActualAmount": "105"}
    with patch.object(auto_pause, "_ssm", fake):
        result = auto_pause.handler(_sns_event(msg), None)

    assert result["paused"] is True
    assert fake.puts and fake.puts[0]["Value"] == "true"


def test_already_paused_is_idempotent():
    from handlers import auto_pause  # type: ignore

    class FakeSSM:
        def __init__(self):
            self.puts = []
        def put_parameter(self, **kw):
            self.puts.append(kw)
        def get_parameter(self, **kw):
            return {"Parameter": {"Value": "true"}}  # already paused

    fake = FakeSSM()
    msg = {"AlarmName": "nova-factory-v2-execution-failures", "NewStateValue": "ALARM"}
    with patch.object(auto_pause, "_ssm", fake):
        result = auto_pause.handler(_sns_event(msg), None)

    assert result["paused"] is True
    assert result["was_already_paused"] is True
    assert fake.puts == []  # no-op


def test_ok_state_does_not_unpause():
    """If an alarm transitions back to OK, we do NOT auto-unpause — humans
    must explicitly reset the flag."""
    from handlers import auto_pause  # type: ignore

    class FakeSSM:
        def __init__(self):
            self.puts = []
        def put_parameter(self, **kw):
            self.puts.append(kw)
        def get_parameter(self, **kw):
            return {"Parameter": {"Value": "true"}}

    fake = FakeSSM()
    msg = {"AlarmName": "nova-factory-v2-execution-failures", "NewStateValue": "OK"}
    with patch.object(auto_pause, "_ssm", fake):
        result = auto_pause.handler(_sns_event(msg), None)

    assert fake.puts == []
    assert result.get("ignored") is True
```

- [ ] **Step 2: Run, verify failure.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/test_auto_pause.py -v
```
Expected: ImportError on `handlers.auto_pause`.

- [ ] **Step 3: Write `handlers/auto_pause.py`.**

```python
"""auto_pause Lambda — flips /nova/factory/paused = true on SNS-delivered
alarm or budget messages. Idempotent. Never auto-unpauses (humans only)."""

from __future__ import annotations

import json
import os
from typing import Any

import boto3

PAUSED_PARAM = os.environ.get("PAUSED_PARAM", "/nova/factory/paused")
_ssm = boto3.client("ssm")


def _is_pausing_signal(msg: dict) -> bool:
    """Recognize either a CloudWatch alarm transitioning to ALARM, or a
    Budgets notification at the threshold we care about."""
    if "AlarmName" in msg:
        return msg.get("NewStateValue") == "ALARM"
    if "BudgetName" in msg:
        # Budgets messages: NotificationState is "ALARM" at threshold breach
        return msg.get("NotificationState") == "ALARM"
    return False


def _read_paused() -> bool:
    try:
        v = _ssm.get_parameter(Name=PAUSED_PARAM)["Parameter"]["Value"].lower().strip()
    except _ssm.exceptions.ParameterNotFound:
        return False
    return v == "true"


def handler(event, _ctx) -> dict[str, Any]:
    record = (event.get("Records") or [{}])[0]
    sns_msg = (record.get("Sns") or {}).get("Message", "{}")
    try:
        msg = json.loads(sns_msg)
    except json.JSONDecodeError:
        msg = {"raw": sns_msg}

    if not _is_pausing_signal(msg):
        return {"ignored": True, "reason": "not a pausing signal", "message_keys": sorted(msg.keys())}

    if _read_paused():
        return {"paused": True, "was_already_paused": True, "trigger": msg.get("AlarmName") or msg.get("BudgetName")}

    _ssm.put_parameter(
        Name=PAUSED_PARAM,
        Value="true",
        Type="String",
        Overwrite=True,
    )
    return {"paused": True, "was_already_paused": False, "trigger": msg.get("AlarmName") or msg.get("BudgetName")}
```

- [ ] **Step 4: Run tests, verify pass.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/test_auto_pause.py -v
```
Expected: 4 tests pass.

- [ ] **Step 5: Commit.**

```bash
cd /c/Claude/Nova/nova
git add scripts/factory_lambdas/handlers/auto_pause.py tests/factory/test_auto_pause.py
git commit -m "factory(v2): add auto_pause Lambda (SNS-triggered pause flag flip)"
```

---

### Task 3: Deploy auto_pause Lambda + SNS subscription

**Files:**
- Modify: `infra/factory/lambdas-v2.tf` — extend `handlers_v2` map.
- Modify: `infra/factory/iam.tf` — grant `ssm:Put/GetParameter` on `/nova/factory/paused`.
- Create: `infra/factory/auto-pause-subscription.tf`

- [ ] **Step 1: Extend the handlers map.**

In `infra/factory/lambdas-v2.tf`:

```hcl
locals {
  handlers_v2 = {
    load_feature   = { timeout = 60,  memory = 512  }
    plan           = { timeout = 120, memory = 1024 }
    mark_blocked   = { timeout = 30,  memory = 256  }
    review         = { timeout = 180, memory = 1024 }
    probe_staging  = { timeout = 60,  memory = 512  }
    revert_merge   = { timeout = 300, memory = 1024 }
    auto_pause     = { timeout = 30,  memory = 256  }
  }
}
```

And add the env var inside the env block:

```hcl
PAUSED_PARAM = aws_ssm_parameter.factory_paused.name
```

- [ ] **Step 2: Grant SSM permissions to lambda_exec.**

Add to the existing inline policy on `aws_iam_role.lambda_exec` in `iam.tf`:

```hcl
{
  Effect = "Allow",
  Action = ["ssm:GetParameter", "ssm:PutParameter"],
  Resource = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/nova/factory/paused"
}
```

- [ ] **Step 3: Create `auto-pause-subscription.tf`.**

```hcl
# Subscribe the auto_pause Lambda to the existing alerts SNS topic.

resource "aws_sns_topic_subscription" "auto_pause_to_alerts" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.handlers_v2["auto_pause"].arn
}

resource "aws_lambda_permission" "auto_pause_from_sns" {
  statement_id  = "AllowSNSInvokeAutoPause"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.handlers_v2["auto_pause"].function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.alerts.arn
}
```

- [ ] **Step 4: Build + apply.**

```bash
cd /c/Claude/Nova/nova/scripts/factory_lambdas && bash build.sh
cd /c/Claude/Nova/nova/infra/factory && terraform apply -auto-approve
```
Expected: 1 new Lambda + 1 log group + 1 SNS subscription + 1 Lambda permission + 1 IAM policy update.

- [ ] **Step 5: Verify subscription.**

```bash
aws sns list-subscriptions-by-topic --topic-arn $(aws sns list-topics --query 'Topics[?contains(TopicArn, `nova-factory-alerts`)].TopicArn' --output text) \
  --query 'Subscriptions[].{Endpoint:Endpoint,Protocol:Protocol}' --output table
```
Expected: a subscription with the auto_pause Lambda's ARN.

- [ ] **Step 6: Commit.**

```bash
cd /c/Claude/Nova/nova
git add infra/factory/auto-pause-subscription.tf infra/factory/lambdas-v2.tf infra/factory/iam.tf
git commit -m "infra(factory v2): subscribe auto_pause Lambda to alerts SNS topic"
```

---

### Task 4: Add the v2 execution-failure alarm

Spec §2.8 + §4.1 row "3 consecutive ExecutionsFailed". v1 already has this; v2 needs an equivalent on `nova-factory-v2`.

**Files:**
- Create: `infra/factory/alarms-v2.tf`

- [ ] **Step 1: Add the alarm.**

```hcl
resource "aws_cloudwatch_metric_alarm" "v2_executions_failed" {
  alarm_name          = "nova-factory-v2-execution-failures"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 3   # 3 consecutive 5-min periods
  datapoints_to_alarm = 3
  metric_name         = "ExecutionsFailed"
  namespace           = "AWS/States"
  period              = 300
  statistic           = "Sum"
  threshold           = 1   # any failure in a period counts; 3 consecutive periods of failures trips
  alarm_description   = "3 consecutive nova-factory-v2 execution failures within 15 min."
  treat_missing_data  = "notBreaching"

  dimensions = {
    StateMachineArn = aws_sfn_state_machine.v2.arn
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = []

  tags = merge(local.common_tags, { Generation = "v2" })
}
```

- [ ] **Step 2: Apply.**

```bash
cd /c/Claude/Nova/nova/infra/factory
terraform apply -auto-approve
```
Expected: 1 new alarm.

- [ ] **Step 3: Sanity-check the alarm exists.**

```bash
aws cloudwatch describe-alarms --alarm-names nova-factory-v2-execution-failures --query 'MetricAlarms[].{Name:AlarmName,State:StateValue,Threshold:Threshold,Evaluations:EvaluationPeriods}' --output table
```
Expected: state `INSUFFICIENT_DATA` initially.

- [ ] **Step 4: Commit.**

```bash
cd /c/Claude/Nova/nova
git add infra/factory/alarms-v2.tf
git commit -m "infra(factory v2): add 3-consecutive-failures alarm on nova-factory-v2 SFN"
```

---

### Task 5: Add the budget tripwires ($20 / $50 / $100)

Spec §5.4. The $20 alarm already exists from v1 — keep it, add new $50 and $100 budgets. The $100 budget routes to the alerts SNS topic so auto_pause flips the flag.

**Files:**
- Create: `infra/factory/budgets.tf`

- [ ] **Step 1: Locate the existing $20 budget.**

```bash
grep -rn "20" /c/Claude/Nova/nova/infra/factory/ | grep -i "budget\|cost"
```
If you find a `aws_budgets_budget "factory_monthly"` or similar, **don't duplicate it** — extend the file to add 50 and 100.

If no existing budget resource is in Terraform (only console-created), create the file fresh.

- [ ] **Step 2: Add `infra/factory/budgets.tf`.**

```hcl
# Three monthly cost budgets at $20 / $50 / $100. The $100 budget is the
# hard ceiling — its breach SNS message flips /nova/factory/paused = true
# via the auto_pause Lambda.

locals {
  budget_thresholds = {
    "20"  = 20
    "50"  = 50
    "100" = 100
  }
  notification_email = var.cost_alert_email
}

resource "aws_budgets_budget" "factory_monthly" {
  for_each = local.budget_thresholds

  name              = "nova-factory-monthly-${each.key}"
  budget_type       = "COST"
  limit_amount      = tostring(each.value)
  limit_unit        = "USD"
  time_unit         = "MONTHLY"
  time_period_start = "2026-01-01_00:00"

  cost_filter {
    name   = "TagKeyValue"
    values = ["user:Project$nova"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [local.notification_email]
    subscriber_sns_topic_arns  = [aws_sns_topic.alerts.arn]
  }

  tags = merge(local.common_tags, { Generation = "v2" })
}
```

- [ ] **Step 3: Add the variable.**

In `infra/factory/variables.tf`:

```hcl
variable "cost_alert_email" {
  description = "Email address that receives Budget threshold notifications."
  type        = string
  default     = "nabbic@gmail.com"
}
```

- [ ] **Step 4: Apply.**

```bash
cd /c/Claude/Nova/nova/infra/factory
terraform apply -auto-approve
```
Expected: 3 new budgets (or 2 if the existing $20 budget was already in TF). If you got a "budget already exists" error, import the existing one:

```bash
terraform import aws_budgets_budget.factory_monthly[\"20\"] 577638385116:nova-factory-monthly-20
```
…then re-apply.

- [ ] **Step 5: Verify.**

```bash
aws budgets describe-budgets --account-id 577638385116 --query 'Budgets[?starts_with(BudgetName, `nova-factory-monthly`)].{Name:BudgetName,Limit:BudgetLimit.Amount}' --output table
```
Expected: 3 rows for $20/$50/$100.

- [ ] **Step 6: Commit.**

```bash
cd /c/Claude/Nova/nova
git add infra/factory/budgets.tf infra/factory/variables.tf
git commit -m "infra(factory v2): add $20/$50/$100 monthly budget tripwires"
```

---

### Task 6: Update the webhook relay to honor the pause flag

**Files:**
- Modify: `infra/webhook-relay/lambda/relay.py` (or whatever the relay handler file is named)
- Modify: `infra/webhook-relay/main.tf` — grant SSM read

- [ ] **Step 1: Locate the relay handler.**

```bash
ls /c/Claude/Nova/nova/infra/webhook-relay/lambda/
```
Expected: a `*.py` handler. Identify the existing entry point (search for `def handler` or `lambda_handler`).

- [ ] **Step 2: Add the pause check at the top of the handler.**

Insert at the top of the handler function (after parsing the request, before forwarding to the factory backend):

```python
import boto3
import os

_ssm = boto3.client("ssm")
PAUSED_PARAM = os.environ.get("PAUSED_PARAM", "/nova/factory/paused")


def _is_paused() -> bool:
    try:
        v = _ssm.get_parameter(Name=PAUSED_PARAM)["Parameter"]["Value"].lower().strip()
    except _ssm.exceptions.ParameterNotFound:
        return False
    return v == "true"


def _post_paused_comment(feature_id: str) -> None:
    if not feature_id:
        return
    try:
        # The relay already has helpers to talk to Notion — reuse them.
        # If not, inline a quick PATCH/comment call here.
        _post_notion_comment(feature_id, "🛑 Nova Factory is currently PAUSED — see CloudWatch alarms. This feature was not dispatched. Resume by setting /nova/factory/paused = false after diagnosing.")
    except Exception:
        pass  # don't let comment failures cause webhook retries
```

Then in the handler body, after parsing the Notion event payload to extract `feature_id`, but before forwarding:

```python
if _is_paused():
    _post_paused_comment(feature_id)
    return {"statusCode": 200, "body": '{"paused": true, "skipped": true}'}
```

If the relay already has Notion-comment infrastructure, wire to that. Otherwise, copy the small `urllib.request`-based comment helper from `mark_blocked.py`.

- [ ] **Step 3: Grant SSM read to the relay Lambda role.**

In `infra/webhook-relay/main.tf`, locate the Lambda's IAM role inline policy and add:

```hcl
{
  Effect = "Allow",
  Action = ["ssm:GetParameter"],
  Resource = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/nova/factory/paused"
}
```

Also add the env var to the Lambda definition:

```hcl
environment {
  variables = {
    # ... existing ...
    PAUSED_PARAM = "/nova/factory/paused"
  }
}
```

- [ ] **Step 4: Apply.**

```bash
cd /c/Claude/Nova/nova/infra/webhook-relay
terraform apply -auto-approve
```
Expected: Lambda function code update + IAM policy update.

- [ ] **Step 5: Smoke-test the pause path.**

```bash
# Manually flip the flag to true
aws ssm put-parameter --name /nova/factory/paused --value true --type String --overwrite

# Trigger the webhook with a known-good fixture (this should NOT start an SFN execution)
# Re-use the smoke runner with a slight tweak: pause + try to trigger the trivial fixture
# via the webhook (not direct SFN start). The cleanest test: start a real Notion change
# event and verify NO new SFN executions appear.

# Then unpause:
aws ssm put-parameter --name /nova/factory/paused --value false --type String --overwrite
```

If you don't want to mess with Notion for the smoke, invoke the relay Lambda directly with a synthetic Notion event payload:

```bash
aws lambda invoke --function-name nova-webhook-relay \
  --payload "$(cat <<'EOF'
{ "body": "{\"event_id\": \"smoke-paused\", \"page\": {\"id\": \"00000000-0000-0000-0000-000000000001\", \"properties\": {\"Status\": {\"status\": {\"name\": \"Ready to Build\"}}}}}" }
EOF
)" \
  --cli-binary-format raw-in-base64-out /tmp/relay.json
cat /tmp/relay.json
```
Expected: response body contains `"paused": true`.

- [ ] **Step 6: Reset the flag.**

```bash
aws ssm put-parameter --name /nova/factory/paused --value false --type String --overwrite
```

- [ ] **Step 7: Commit.**

```bash
cd /c/Claude/Nova/nova
git add infra/webhook-relay/
git commit -m "infra(webhook-relay): honor /nova/factory/paused flag (returns 200 + Notion comment when paused)"
```

---

### Task 7: Build the v2 CloudWatch dashboard

Spec §2.8: dashboard widgets for turns-per-feature, tokens-per-feature, time-per-stage, validate/review repair rates, executions over time.

**Files:**
- Create: `infra/factory/dashboard-v2.tf`

- [ ] **Step 1: Author the dashboard JSON.**

```hcl
resource "aws_cloudwatch_dashboard" "v2" {
  dashboard_name = "nova-factory-v2"

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6,
        properties = {
          title  = "v2 SFN executions (started / succeeded / failed)",
          metrics = [
            ["AWS/States", "ExecutionsStarted",   "StateMachineArn", aws_sfn_state_machine.v2.arn],
            [".",          "ExecutionsSucceeded", ".",                "."],
            [".",          "ExecutionsFailed",    ".",                "."]
          ],
          view = "timeSeries", stat = "Sum", period = 300, region = var.aws_region
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6,
        properties = {
          title  = "RalphTurn invocations (success/error/throttle)",
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.ralph_turn.function_name],
            [".",          "Errors",      ".",            "."],
            [".",          "Throttles",   ".",            "."]
          ],
          view = "timeSeries", stat = "Sum", period = 300, region = var.aws_region
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 12, height = 6,
        properties = {
          title  = "Validate-v2 invocations + duration",
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.validate_v2.function_name],
            [".",          "Duration",    ".",            ".",  {stat = "Average"}],
            [".",          "Errors",      ".",            "."]
          ],
          view = "timeSeries", stat = "Sum", period = 300, region = var.aws_region
        }
      },
      {
        type = "metric", x = 12, y = 6, width = 12, height = 6,
        properties = {
          title  = "Plan / Review token usage (proxy: invocations × duration)",
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.handlers_v2["plan"].function_name,   {stat = "Sum"}],
            [".",          ".",        ".",            aws_lambda_function.handlers_v2["review"].function_name, {stat = "Sum"}]
          ],
          view = "timeSeries", period = 300, region = var.aws_region
        }
      },
      {
        type = "log", x = 0, y = 12, width = 24, height = 6,
        properties = {
          title  = "RalphTurn outcomes (last 1h)",
          query  = "SOURCE '/aws/lambda/${aws_lambda_function.ralph_turn.function_name}' | fields @timestamp, @message | filter @message like /completion_signal/ | sort @timestamp desc | limit 50",
          region = var.aws_region,
          view   = "table"
        }
      }
    ]
  })
}

output "v2_dashboard_url" {
  value = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=nova-factory-v2"
}
```

- [ ] **Step 2: Apply.**

```bash
cd /c/Claude/Nova/nova/infra/factory
terraform apply -auto-approve
```
Expected: 1 dashboard.

- [ ] **Step 3: Open it in the browser.**

```bash
echo "Open: $(terraform -chdir=/c/Claude/Nova/nova/infra/factory output -raw v2_dashboard_url)"
```

- [ ] **Step 4: Commit.**

```bash
cd /c/Claude/Nova/nova
git add infra/factory/dashboard-v2.tf
git commit -m "infra(factory v2): add v2 CloudWatch dashboard (executions, RalphTurn, Validate, Plan/Review)"
```

---

### Task 8: Save Logs Insights queries

Spec §2.8: three saved queries: `ralph-turn-summary`, `validation-failures`, `execution-trace`.

**Files:**
- Create: `infra/factory/logs-insights-queries.tf`

- [ ] **Step 1: Add the resource definitions.**

```hcl
resource "aws_cloudwatch_query_definition" "ralph_turn_summary" {
  name = "nova-factory/ralph-turn-summary"
  log_group_names = [
    aws_cloudwatch_log_group.ralph_turn.name,
  ]
  query_string = <<-EOT
    fields @timestamp, @message
    | parse @message /completion_signal=(?<done>true|false), input_tokens=(?<inp>\d+), output_tokens=(?<out>\d+)/
    | filter ispresent(done)
    | stats count() as turns, sum(inp) as total_input, sum(out) as total_output by bin(1h)
    | sort @timestamp desc
  EOT
}

resource "aws_cloudwatch_query_definition" "validation_failures" {
  name = "nova-factory/validation-failures"
  log_group_names = [
    aws_cloudwatch_log_group.validate_v2.name,
  ]
  query_string = <<-EOT
    fields @timestamp, @message
    | filter @message like /"passed":\s*false/
    | sort @timestamp desc
    | limit 100
  EOT
}

resource "aws_cloudwatch_query_definition" "execution_trace" {
  name = "nova-factory/execution-trace"
  log_group_names = [
    aws_cloudwatch_log_group.sfn_v2.name,
    aws_cloudwatch_log_group.ralph_turn.name,
    aws_cloudwatch_log_group.validate_v2.name,
  ]
  query_string = <<-EOT
    fields @timestamp, @log, @message
    | filter @message like /<execution-id>/
    | sort @timestamp asc
    | limit 200
  EOT
}
```

The third query has `<execution-id>` as a placeholder; users replace it in the console with the actual execution name when running the query.

- [ ] **Step 2: Apply.**

```bash
cd /c/Claude/Nova/nova/infra/factory
terraform apply -auto-approve
```
Expected: 3 new query definitions.

- [ ] **Step 3: Verify.**

```bash
aws logs describe-query-definitions --query-definition-name-prefix nova-factory/ \
  --query 'queryDefinitions[].{Name:name,QueryDefinitionId:queryDefinitionId}' --output table
```
Expected: 3 entries.

- [ ] **Step 4: Commit.**

```bash
cd /c/Claude/Nova/nova
git add infra/factory/logs-insights-queries.tf
git commit -m "infra(factory v2): add saved Logs Insights queries (ralph-turn-summary/validation-failures/execution-trace)"
```

---

### Task 9: End-to-end exercise the pause path

Inject 3 synthetic failures, verify the alarm fires, the auto_pause Lambda triggers, the flag flips, and the webhook honors it.

- [ ] **Step 1: Force 3 v2 SFN failures.**

The fastest way is to start 3 executions with malformed input that fail immediately:

```bash
for i in 1 2 3; do
  aws stepfunctions start-execution \
    --state-machine-arn arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-v2 \
    --name "force-fail-$i-$(date +%s)" \
    --input '{}' >/dev/null   # missing feature_id → fails at AcquireLock
  sleep 2
done
```

- [ ] **Step 2: Wait for the alarm to fire (≥15 min).**

```bash
aws cloudwatch describe-alarms --alarm-names nova-factory-v2-execution-failures \
  --query 'MetricAlarms[].StateValue' --output text
```
Expected: progresses to `ALARM` within 15 min (3 evaluation periods × 5 min).

To accelerate testing, temporarily reduce `evaluation_periods` to `1` in `alarms-v2.tf`, apply, run the test, then revert.

- [ ] **Step 3: Verify the flag flipped.**

```bash
aws ssm get-parameter --name /nova/factory/paused --query Parameter.Value --output text
```
Expected: `true`.

- [ ] **Step 4: Verify the relay honors the flag.**

(Same invocation as Task 6 Step 5.) Expected: response body contains `"paused": true`.

- [ ] **Step 5: Reset.**

```bash
aws ssm put-parameter --name /nova/factory/paused --value false --type String --overwrite
aws cloudwatch set-alarm-state --alarm-name nova-factory-v2-execution-failures --state-value OK --state-reason "Resetting after smoke test"
```

---

### Task 10: Final verification

- [ ] **Step 1: All tests pass.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/ -v
```
Expected: 55 (Phase 4) + 4 (auto_pause) = 59 tests pass.

- [ ] **Step 2: Terraform plan clean.**

```bash
cd /c/Claude/Nova/nova/infra/factory && terraform plan -input=false | tail -3
cd /c/Claude/Nova/nova/infra/webhook-relay && terraform plan -input=false | tail -3
```
Expected: both `No changes.`

- [ ] **Step 3: Three smokes still pass.**

```bash
cd /c/Claude/Nova/nova
bash scripts/factory_smoke_v2.sh trivial   && \
bash scripts/factory_smoke_v2.sh medium    && \
bash scripts/factory_smoke_v2.sh oversized && \
echo "ALL THREE END-TO-END SMOKES STILL PASS"
```

- [ ] **Step 4: Push branch.**

```bash
git -C /c/Claude/Nova/nova push origin factory-overhaul-2026-05-03
```

---

## Phase 5 acceptance criteria recap

1. `/nova/factory/paused` Parameter Store flag exists, defaults to `false`.
2. `auto_pause` Lambda deployed and subscribed to the alerts SNS topic.
3. v2 execution-failures alarm exists.
4. $20 / $50 / $100 monthly budgets exist and route to the alerts SNS topic.
5. Webhook relay reads `/nova/factory/paused` on every delivery; when `true`, returns 200 + Notion comment.
6. v2 CloudWatch dashboard exists with 5 widgets.
7. 3 saved Logs Insights queries exist.
8. End-to-end pause exercise confirms 3 failures → flag flip → relay honors flag.
9. `pytest tests/factory/ -v` passes 59 tests.

---

## What Phase 6 will do

Phase 6 ("Cutover & cleanup"):

- **Cutover**: flip `FACTORY_BACKEND="step-functions-v2"` in the webhook relay env. Run a real Notion-triggered feature end-to-end. Watch the v2 dashboard.
- **30-day soak**: keep v1 alive as fallback. Monitor v2's alarm/budget/pause health.
- **Cleanup (after stable soak)**:
  - `terraform destroy` — well, not quite — instead, delete the v1-only files (`lambdas.tf` v1 entries, `state-machine.tf`, `state-machine.json.tpl`, `lambdas-image.tf` for the old validators ECR) so a normal `terraform apply` removes the resources.
  - Delete v1 handler files: `load_spec.py`, `load_project_context.py`, `run_orchestrator.py`, `run_agent.py`, `evaluate_security.py`, the validator handlers per-phase, the old `validate_workspace` container.
  - Delete `.claude/agents/*.md` and `scripts/factory_lambdas/agent_prompts/*.md` (all 9).
  - Delete `scripts/factory_run.py` and `scripts/agents.py`.
  - Mark `factory.yml` deprecated (banner) and remove after 30 more days.
- **Memory updates**: `project_nova_status.md` and `reference_factory_runtime.md` refreshed to reflect the v2 architecture.
