import json
import time
import traceback
from common.workspace import (
    write_json, read_json, write_file, list_workspace_jsons,
)
from common.runs import record_step
from common.agent_runner import (
    call_agent_with_continuation, parse_agent_json, AGENT_CONFIG,
)

WORKSPACE_AGENTS = {
    "spec-analyst":      "requirements.json",
    "architect":         "architecture.json",
    "security-reviewer": "security-review.json",
}
CODE_AGENTS = {"database", "backend", "frontend", "infrastructure", "test"}


def _build_context(
    execution_id: str,
    agent_name: str,
    plan: dict | None,
    repair_context: dict | None,
) -> str:
    parts = []
    if repair_context:
        parts.append(
            f"# REPAIR MODE — please fix only these issues\n"
            f"```json\n{json.dumps(repair_context, indent=2)}\n```\n\n"
        )
    if plan:
        notes = plan.get("notes", {}).get(agent_name, "")
        if notes:
            parts.append(f"# Orchestrator Notes for {agent_name}\n{notes}\n\n")
    parts.append("# Project Context\n")
    parts.append(read_json(execution_id, "project_context.json")["claude_md"])
    parts.append("\n")
    for name, data in sorted(list_workspace_jsons(execution_id).items()):
        if name == "project_context.json":
            continue
        parts.append(f"\n# {name[:-5]}\n```json\n{json.dumps(data, indent=2)}\n```\n")
    return "".join(parts)


def handler(event, _ctx):
    agent_name     = event["agent_name"]
    execution_id   = event["execution_id"]
    feature_id     = event["feature_id"]
    repair_context = event.get("repair_context")
    model_override = event.get("model_override")

    plan = read_json(execution_id, "plan.json") if agent_name != "orchestrator" else None

    # Honour model_hint from orchestrator (upgrades only)
    if plan and not model_override:
        hint = plan.get("model_hint", {}).get(agent_name)
        if hint:
            tier = {"haiku": 0, "sonnet": 1, "opus": 2}
            cfg_model = AGENT_CONFIG[agent_name]["model"]
            current_tier = 0 if "haiku" in cfg_model else (1 if "sonnet" in cfg_model else 2)
            wanted_tier = tier.get(hint, current_tier)
            if wanted_tier > current_tier:
                model_map = {
                    0: "claude-haiku-4-5-20251001",
                    1: "claude-sonnet-4-6",
                    2: "claude-opus-4-7",
                }
                model_override = model_map[wanted_tier]

    user_message = _build_context(execution_id, agent_name, plan, repair_context)

    start = time.time()
    try:
        result = call_agent_with_continuation(agent_name, user_message, model_override)
        if agent_name in WORKSPACE_AGENTS:
            data = parse_agent_json(agent_name, result)
            write_json(execution_id, WORKSPACE_AGENTS[agent_name], data)
        elif agent_name in CODE_AGENTS:
            data = parse_agent_json(agent_name, result)
            if not isinstance(data, dict) or not data:
                raise ValueError(f"{agent_name} returned empty or non-dict file map")
            self_check = data.pop("_self_check", None)
            for rel_path, content in data.items():
                if not isinstance(content, str):
                    raise ValueError(f"{agent_name} non-string content for {rel_path}")
                write_file(execution_id, rel_path, content)
            if self_check:
                write_json(execution_id, f"_self_check_{agent_name}.json", self_check)
        record_step(
            execution_id, feature_id, agent_name, "success",
            time.time() - start,
            metadata={"model": model_override or AGENT_CONFIG[agent_name]["model"]},
        )
        return {"status": "ok", "agent": agent_name}
    except Exception as e:
        record_step(execution_id, feature_id, agent_name, "failed",
                    time.time() - start, error=f"{e}\n{traceback.format_exc()}")
        raise
