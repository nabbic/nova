import json
import os
from pathlib import Path

import anthropic

MODEL = "claude-sonnet-4-6"
ROOT = Path(__file__).parent.parent  # repo root
WORKSPACE = ROOT / ".factory-workspace"
AGENTS_DIR = ROOT / ".claude/agents"


def _load_system_prompt(agent_name: str) -> str:
    path = AGENTS_DIR / f"{agent_name}.md"
    return path.read_text()


def _load_context() -> str:
    """Assembles CLAUDE.md + all workspace JSON files into a single context string."""
    parts = ["# Project Context\n", (ROOT / "CLAUDE.md").read_text(), "\n"]
    for filename in sorted(WORKSPACE.glob("*.json")):
        parts.append(f"\n# {filename.stem}\n```json\n")
        parts.append(filename.read_text())
        parts.append("\n```\n")
    return "".join(parts)


def run_agent(agent_name: str, user_message: str = None) -> str:
    """Invokes a specialist agent and returns its text response."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    system_prompt = _load_system_prompt(agent_name)
    context = _load_context()

    message = client.messages.create(
        model=MODEL,
        max_tokens=8096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message or context}],
    )
    return message.content[0].text


def run_orchestrator(spec: dict) -> dict:
    """Runs the orchestrator and returns the parsed plan."""
    WORKSPACE.mkdir(exist_ok=True)
    response = run_agent("orchestrator", json.dumps(spec, indent=2))

    plan_path = WORKSPACE / "plan.json"
    if not plan_path.exists():
        # Fallback: parse JSON from the response text directly
        plan = json.loads(response)
        plan_path.write_text(json.dumps(plan, indent=2))
    return json.loads(plan_path.read_text())


def check_security_review() -> dict:
    """Reads and returns the security review result."""
    review_path = WORKSPACE / "security-review.json"
    if not review_path.exists():
        raise RuntimeError("Security reviewer did not produce security-review.json")
    return json.loads(review_path.read_text())
