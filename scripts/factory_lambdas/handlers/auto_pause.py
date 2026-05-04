"""auto_pause Lambda — flips /nova/factory/paused = true on SNS-delivered
alarm or budget messages. Idempotent. Never auto-unpauses (humans only)."""

from __future__ import annotations

import json
import os
from typing import Any

import boto3

PAUSED_PARAM = os.environ.get("PAUSED_PARAM", "/nova/factory/paused")
_ssm = boto3.client("ssm")


def _is_pausing_signal(msg: dict) -> bool:
    """Recognize either a CloudWatch alarm transitioning to ALARM, or a
    Budgets notification at the threshold we care about."""
    if "AlarmName" in msg:
        return msg.get("NewStateValue") == "ALARM"
    if "BudgetName" in msg:
        return msg.get("NotificationState") == "ALARM"
    return False


def _read_paused() -> bool:
    try:
        v = _ssm.get_parameter(Name=PAUSED_PARAM)["Parameter"]["Value"].lower().strip()
    except _ssm.exceptions.ParameterNotFound:
        return False
    return v == "true"


def handler(event, _ctx) -> dict[str, Any]:
    record = (event.get("Records") or [{}])[0]
    sns_msg = (record.get("Sns") or {}).get("Message", "{}")
    try:
        msg = json.loads(sns_msg)
    except json.JSONDecodeError:
        msg = {"raw": sns_msg}

    if not _is_pausing_signal(msg):
        return {"ignored": True, "reason": "not a pausing signal", "message_keys": sorted(msg.keys())}

    if _read_paused():
        return {"paused": True, "was_already_paused": True, "trigger": msg.get("AlarmName") or msg.get("BudgetName")}

    _ssm.put_parameter(
        Name=PAUSED_PARAM,
        Value="true",
        Type="String",
        Overwrite=True,
    )
    return {"paused": True, "was_already_paused": False, "trigger": msg.get("AlarmName") or msg.get("BudgetName")}
