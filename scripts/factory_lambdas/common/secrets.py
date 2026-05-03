import boto3

_sm = boto3.client("secretsmanager")

def get_secret(name: str) -> str:
    return _sm.get_secret_value(SecretId=name)["SecretString"]
