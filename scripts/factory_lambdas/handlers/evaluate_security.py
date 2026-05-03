from common.workspace import read_json


def handler(event, _ctx):
    execution_id = event["execution_id"]
    try:
        review = read_json(execution_id, "security-review.json")
    except Exception:
        return {"passed": False, "repairable": False, "issues": [], "error": "security-review.json missing"}

    passed = review.get("passed", False)
    issues = review.get("issues", [])
    # Repairable if all blocking issues have repairable=true
    blocking = [i for i in issues if i.get("severity") in ("CRITICAL", "HIGH")]
    repairable = passed or (bool(blocking) and all(i.get("repairable", True) for i in blocking))
    return {
        "passed": passed,
        "repairable": repairable,
        "issues": issues,
    }
