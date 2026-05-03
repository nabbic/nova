from common.locks import release

def handler(event, _ctx):
    release(event["feature_id"], event["execution_id"])
    return {"released": True}
