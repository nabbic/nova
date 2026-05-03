import json
import os
import boto3

BUCKET = os.environ["WORKSPACE_BUCKET"]
_s3 = boto3.client("s3")

def _key(execution_id: str, name: str) -> str:
    return f"{execution_id}/{name}"

def write_json(execution_id: str, name: str, data) -> None:
    _s3.put_object(
        Bucket=BUCKET,
        Key=_key(execution_id, name),
        Body=json.dumps(data, indent=2).encode("utf-8"),
        ContentType="application/json",
    )

def read_json(execution_id: str, name: str):
    obj = _s3.get_object(Bucket=BUCKET, Key=_key(execution_id, name))
    return json.loads(obj["Body"].read())

def write_file(execution_id: str, rel_path: str, content: str) -> None:
    _s3.put_object(
        Bucket=BUCKET,
        Key=_key(execution_id, f"code/{rel_path}"),
        Body=content.encode("utf-8"),
    )

def list_workspace_jsons(execution_id: str) -> dict:
    resp = _s3.list_objects_v2(Bucket=BUCKET, Prefix=f"{execution_id}/")
    out = {}
    for obj in resp.get("Contents", []):
        key = obj["Key"]
        name = key[len(f"{execution_id}/"):]
        if "/" in name or not name.endswith(".json"):
            continue
        out[name] = read_json(execution_id, name)
    return out

def list_code_files(execution_id: str) -> list[str]:
    resp = _s3.list_objects_v2(Bucket=BUCKET, Prefix=f"{execution_id}/code/")
    return [obj["Key"][len(f"{execution_id}/code/"):] for obj in resp.get("Contents", [])]

def read_code_file(execution_id: str, rel_path: str) -> str:
    obj = _s3.get_object(Bucket=BUCKET, Key=_key(execution_id, f"code/{rel_path}"))
    return obj["Body"].read().decode("utf-8")
