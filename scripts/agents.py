import json
import os
import re
import time
from pathlib import Path

import anthropic

MODEL = "claude-sonnet-4-6"
_MAX_RETRIES = 3
_RETRY_DELAYS = [5, 15, 30]  # seconds between attempts
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

    last_exc: Exception | None = None
    for attempt, delay in enumerate((*_RETRY_DELAYS, None), start=1):
        try:
            message = client.messages.create(
                model=MODEL,
                max_tokens=16384,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            return message.content[0].text
        except (anthropic.APIConnectionError, anthropic.APITimeoutError, anthropic.RateLimitError) as exc:
            last_exc = exc
            if delay is None:
                break
            print(f"  {agent_name}: transient error on attempt {attempt}/{_MAX_RETRIES} — retrying in {delay}s: {exc}")
            time.sleep(delay)
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500 and delay is not None:
                last_exc = exc
                print(f"  {agent_name}: server error {exc.status_code} on attempt {attempt}/{_MAX_RETRIES} — retrying in {delay}s")
                time.sleep(delay)
            else:
                raise

    raise RuntimeError(f"{agent_name} failed after {_MAX_RETRIES} attempts: {last_exc}") from last_exc


def _build_agent_context(agent_name: str, plan: dict) -> str:
    """Builds the user message for an agent: context + any orchestrator notes for this agent."""
    context = _load_context()
    notes = plan.get("notes", {}).get(agent_name, "")
    if notes:
        context = f"# Orchestrator Notes for {agent_name}\n{notes}\n\n{context}"
    return context


def run_agent(agent_name: str, plan: dict = None) -> str:
    """Runs an agent with accumulated workspace context.

    Workspace agents save their JSON response to .factory-workspace/.
    Code agents parse their response as a file map and write each file to disk.
    Orchestrator notes from the plan are surfaced at the top of each agent's context.
    """
    context = _build_agent_context(agent_name, plan or {})
    response = _call_agent(agent_name, context)

    if agent_name in WORKSPACE_AGENTS:
        data = _extract_json(response)
        path = WORKSPACE / WORKSPACE_AGENTS[agent_name]
        path.write_text(json.dumps(data, indent=2))
    elif agent_name in CODE_AGENTS:
        files = _extract_json(response)
        if not isinstance(files, dict):
            raise RuntimeError(
                f"{agent_name} returned a {type(files).__name__} instead of a JSON file map"
            )
        if not files:
            raise RuntimeError(f"{agent_name} returned an empty file map — no files written")
        for rel_path, content in files.items():
            abs_path = ROOT / rel_path
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(content, encoding="utf-8")
        print(f"  {agent_name}: wrote {len(files)} file(s)")

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
