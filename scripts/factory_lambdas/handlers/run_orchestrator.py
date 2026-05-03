import json
import time
import traceback
from common.workspace import write_json, read_json
from common.runs import record_step
from common.agent_runner import call_agent_with_continuation, parse_agent_json


def handler(event, _ctx):
    execution_id = event["execution_id"]
    feature_id   = event["feature_id"]

    spec = read_json(execution_id, "spec.json")
    project_context = read_json(execution_id, "project_context.json")["claude_md"]
    user_message = (
        f"# Project Context\n{project_context}\n\n"
        f"# Feature Spec\n```json\n{json.dumps(spec, indent=2)}\n```"
    )

    start = time.time()
    try:
        result = call_agent_with_continuation("orchestrator", user_message)
        plan = parse_agent_json("orchestrator", result)
        # Compute execution_phases so the state machine can enforce fixed ordering.
        # parallel_groups is kept for informational purposes only.
        agents = plan.get("agents", [])
        plan["execution_phases"] = {
            "database": [a for a in agents if a == "database"],
            "builders": [a for a in agents if a in {"backend", "frontend", "infrastructure"}],
            "test":     [a for a in agents if a == "test"],
        }
        write_json(execution_id, "plan.json", plan)
        record_step(execution_id, feature_id, "orchestrator", "success", time.time() - start)
        return {"status": "ok", "plan": plan}
    except Exception as e:
        record_step(execution_id, feature_id, "orchestrator", "failed",
                    time.time() - start, error=f"{e}\n{traceback.format_exc()}")
        raise
