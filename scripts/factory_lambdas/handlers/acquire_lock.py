from common.locks import acquire

def handler(event, _ctx):
    feature_id   = event["feature_id"]
    execution_id = event["execution_id"]
    if not acquire(feature_id, execution_id):
        raise Exception(f"FeatureLocked: {feature_id} is already being processed by another execution")
    return {"locked": True}
