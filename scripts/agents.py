import json
import os
import re
from pathlib import Path

import anthropic

MODEL = "claude-sonnet-4-6"
ROOT = Path(__file__).parent.parent
WORKSPACE = ROOT / ".factory-workspace"
AGENTS_DIR = ROOT / ".claude/agents"

# Agents whose full response is a JSON workspace file
WORKSPACE_AGENTS = {
    "spec-analyst": "requirements.json",
    "architect": "architecture.json",
    "security-reviewer": "security-review.json",
}

# Agents whose response is a JSON map of {file_path: file_content}
CODE_AGENTS = {"database", "backend", "frontend", "infrastructure", "test"}


def _load_system_prompt(agent_name: str) -> str:
    path = AGENTS_DIR / f"{agent_name}.md"
    return path.read_text()


def _load_context() -> str:
    parts = ["# Project Context\n", (ROOT / "CLAUDE.md").read_text(), "\n"]
    for filename in sorted(WORKSPACE.glob("*.json")):
        parts.append(f"\n# {filename.stem}\n```json\n")
        parts.append(filename.read_text())
        parts.append("\n```\n")
    return "".join(parts)


def _extract_json(text: str):
    """Extract JSON from a response that may be wrapped in a markdown code block."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*\n([\s\S]*?)\n```", text)
    if match:
        text = match.group(1).strip()
    return json.loads(text)


def _call_agent(agent_name: str, user_message: str) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    system_prompt = _load_system_prompt(agent_name)
    message = client.messages.create(
        model=MODEL,
        max_tokens=16384,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return message.content[0].text


def run_agent(agent_name: str) -> str:
    """Runs an agent with accumulated workspace context.

    Workspace agents save their JSON response to .factory-workspace/.
    Code agents parse their response as a file map and write each file to disk.
    """
    context = _load_context()
    response = _call_agent(agent_name, context)

    if agent_name in WORKSPACE_AGENTS:
        data = _extract_json(response)
        path = WORKSPACE / WORKSPACE_AGENTS[agent_name]
        path.write_text(json.dumps(data, indent=2))
    elif agent_name in CODE_AGENTS:
        try:
            files = _extract_json(response)
            if isinstance(files, dict):
                for rel_path, content in files.items():
                    abs_path = ROOT / rel_path
                    abs_path.parent.mkdir(parents=True, exist_ok=True)
                    abs_path.write_text(content, encoding="utf-8")
                print(f"  {agent_name}: wrote {len(files)} file(s)")
        except Exception as exc:
            print(f"  WARNING: {agent_name} response could not be parsed as file map: {exc}")

    return response


def run_orchestrator(spec: dict) -> dict:
    """Runs the orchestrator agent and returns the parsed plan."""
    WORKSPACE.mkdir(exist_ok=True)
    context = _load_context()
    user_message = (
        f"{context}\n\n# Feature Spec\n```json\n{json.dumps(spec, indent=2)}\n```"
    )
    response = _call_agent("orchestrator", user_message)
    plan = _extract_json(response)
    (WORKSPACE / "plan.json").write_text(json.dumps(plan, indent=2))
    return plan


def check_security_review() -> dict:
    review_path = WORKSPACE / "security-review.json"
    if not review_path.exists():
        raise RuntimeError("Security reviewer did not produce security-review.json")
    return json.loads(review_path.read_text())
