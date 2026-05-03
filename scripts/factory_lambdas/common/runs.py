import os
import time
import boto3

TABLE = os.environ["RUNS_TABLE"]
_ddb = boto3.client("dynamodb")

def record_step(
    execution_id: str,
    feature_id: str,
    step: str,
    outcome: str,
    duration_s: float,
    error: str = "",
    metadata: dict | None = None,
) -> None:
    item = {
        "execution_id": {"S": execution_id},
        "step":         {"S": step},
        "feature_id":   {"S": feature_id},
        "outcome":      {"S": outcome},
        "duration_s":   {"N": str(round(duration_s, 2))},
        "ts":           {"N": str(int(time.time()))},
    }
    if error:
        item["error"] = {"S": error[:4000]}
    if metadata:
        item["metadata"] = {"S": str(metadata)[:4000]}
    _ddb.put_item(TableName=TABLE, Item=item)

def get_steps(execution_id: str) -> list[dict]:
    resp = _ddb.query(
        TableName=TABLE,
        KeyConditionExpression="execution_id = :e",
        ExpressionAttributeValues={":e": {"S": execution_id}},
    )
    return resp["Items"]
