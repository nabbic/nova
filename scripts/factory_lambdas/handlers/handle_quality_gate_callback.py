import json
import boto3

_sfn = boto3.client("stepfunctions")


def handler(event, _ctx):
    body = json.loads(event.get("body") or "{}")
    task_token = body.get("task_token", "")
    if not task_token:
        return {"statusCode": 400, "body": "missing task_token"}

    if body.get("passed"):
        _sfn.send_task_success(
            taskToken=task_token,
            output=json.dumps({"passed": True, "logs_url": body.get("logs_url", "")}),
        )
    else:
        _sfn.send_task_failure(
            taskToken=task_token,
            error="QualityGateFailure",
            cause=str(body.get("error", "unknown"))[:256],
        )
    return {"statusCode": 200, "body": "ok"}
