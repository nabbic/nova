import os
import time
import boto3
from botocore.exceptions import ClientError

TABLE = os.environ["LOCKS_TABLE"]
_ddb = boto3.client("dynamodb")
LOCK_TTL_SECONDS = 3600

def acquire(feature_id: str, execution_id: str) -> bool:
    try:
        _ddb.put_item(
            TableName=TABLE,
            Item={
                "feature_id":   {"S": feature_id},
                "execution_id": {"S": execution_id},
                "acquired_at":  {"N": str(int(time.time()))},
                "expires_at":   {"N": str(int(time.time()) + LOCK_TTL_SECONDS)},
            },
            ConditionExpression="attribute_not_exists(feature_id) OR expires_at < :now",
            ExpressionAttributeValues={":now": {"N": str(int(time.time()))}},
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise

def release(feature_id: str, execution_id: str) -> None:
    try:
        _ddb.delete_item(
            TableName=TABLE,
            Key={"feature_id": {"S": feature_id}},
            ConditionExpression="execution_id = :eid",
            ExpressionAttributeValues={":eid": {"S": execution_id}},
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
