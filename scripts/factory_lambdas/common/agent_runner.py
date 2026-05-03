import json
import os
import re
import time
import anthropic
from common.secrets import get_secret

AGENT_CONFIG = {
    "orchestrator":      {"model": "claude-haiku-4-5-20251001", "max_tokens": 4096},
    "spec-analyst":      {"model": "claude-haiku-4-5-20251001", "max_tokens": 4096},
    "architect":         {"model": "claude-sonnet-4-6",         "max_tokens": 8192},
    "database":          {"model": "claude-sonnet-4-6",         "max_tokens": 16384},
    "backend":           {"model": "claude-sonnet-4-6",         "max_tokens": 32768},
    "frontend":          {"model": "claude-sonnet-4-6",         "max_tokens": 32768},
    "infrastructure":    {"model": "claude-sonnet-4-6",         "max_tokens": 16384},
    "test":              {"model": "claude-sonnet-4-6",         "max_tokens": 16384},
    "security-reviewer": {"model": "claude-opus-4-7",           "max_tokens": 8192},
}

_PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "agent_prompts")
_RETRY_DELAYS = [5, 15, 30]

_REPAIR_SYSTEM = (
    "You are a JSON extractor. The user message contains a response from another model "
    "that was supposed to be pure JSON but may include prose, markdown fences, or commentary. "
    "Extract and output ONLY the intended JSON object. No prose, no fences, no preamble. "
    "If the JSON is truncated or invalid, attempt to repair it minimally. "
    "If no JSON is recoverable at all, output exactly: {}"
)


class EmptyResponseError(RuntimeError):
    pass


class RefusalError(RuntimeError):
    pass


def load_system_prompt(agent_name: str) -> str:
    with open(os.path.join(_PROMPTS_DIR, f"{agent_name}.md")) as f:
        return f.read()


def _try_parse(text: str):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*\n([\s\S]*?)\n```", text)
    if m:
        text = m.group(1).strip()
    return json.loads(text)


def _extract_json_with_repair(agent_name: str, text: str) -> dict:
    try:
        return _try_parse(text)
    except json.JSONDecodeError:
        pass

    print(f"{agent_name}: JSON parse failed, attempting Haiku repair")
    client = anthropic.Anthropic(api_key=get_secret("nova/factory/anthropic-api-key"))
    repair = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=8192,
        system=_REPAIR_SYSTEM,
        messages=[{"role": "user", "content": text[:50000]}],
    )
    repaired = repair.content[0].text.strip()
    return _try_parse(repaired)


def call_agent(
    agent_name: str,
    user_message: str,
    model_override: str | None = None,
    *,
    prior_assistant: str | None = None,
) -> dict:
    cfg = AGENT_CONFIG[agent_name]
    model = model_override or cfg["model"]
    max_tokens = cfg["max_tokens"]
    client = anthropic.Anthropic(api_key=get_secret("nova/factory/anthropic-api-key"))
    system_prompt = load_system_prompt(agent_name)

    messages: list[dict] = [{"role": "user", "content": user_message}]
    if prior_assistant:
        messages.append({"role": "assistant", "content": prior_assistant})

    last_exc: Exception | None = None
    for attempt, delay in enumerate((*_RETRY_DELAYS, None), start=1):
        try:
            msg = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=messages,
            )
        except (anthropic.APIConnectionError, anthropic.APITimeoutError, anthropic.RateLimitError) as e:
            last_exc = e
            if delay is None:
                break
            print(f"{agent_name}: transient error attempt {attempt}, retry in {delay}s: {e}")
            time.sleep(delay)
            continue
        except anthropic.APIStatusError as e:
            if e.status_code >= 500 and delay is not None:
                last_exc = e
                print(f"{agent_name}: server {e.status_code} attempt {attempt}, retry in {delay}s")
                time.sleep(delay)
                continue
            raise

        text = msg.content[0].text if msg.content else ""
        result = {
            "text": text,
            "stop_reason": msg.stop_reason,
            "usage": {"input": msg.usage.input_tokens, "output": msg.usage.output_tokens},
        }
        print(json.dumps({
            "event": "agent_call",
            "agent": agent_name,
            "model": model,
            "stop_reason": result["stop_reason"],
            "input_tokens": result["usage"]["input"],
            "output_tokens": result["usage"]["output"],
        }))
        return result

    raise RuntimeError(f"{agent_name} exhausted retries: {last_exc}")


def call_agent_with_continuation(
    agent_name: str,
    user_message: str,
    model_override: str | None = None,
    max_continuations: int = 2,
) -> dict:
    accumulated = ""
    result = call_agent(agent_name, user_message, model_override)
    accumulated = result["text"]
    continuations = 0
    while result["stop_reason"] == "max_tokens" and continuations < max_continuations:
        continuations += 1
        print(f"{agent_name}: hit max_tokens, requesting continuation {continuations}/{max_continuations}")
        result = call_agent(agent_name, user_message, model_override, prior_assistant=accumulated)
        accumulated += result["text"]
    if result["stop_reason"] == "max_tokens":
        raise RuntimeError(
            f"{agent_name}: still incomplete after {max_continuations} continuations. "
            "Either raise max_tokens for this agent or split the feature."
        )
    return {"text": accumulated, "stop_reason": "end_turn", "usage": result["usage"]}


def parse_agent_json(agent_name: str, result: dict) -> dict:
    text = result["text"].strip()
    if not text:
        raise EmptyResponseError(
            f"{agent_name}: empty response "
            f"(stop_reason={result['stop_reason']}, output_tokens={result['usage']['output']})"
        )
    if result["stop_reason"] == "refusal":
        raise RefusalError(f"{agent_name}: model refused to generate. Full response: {text[:500]}")
    return _extract_json_with_repair(agent_name, text)
