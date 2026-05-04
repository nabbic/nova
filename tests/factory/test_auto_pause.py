"""Tests for the auto_pause Lambda — flips /nova/factory/paused on SNS-delivered alarms."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("PAUSED_PARAM", "/nova/factory/paused")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "factory_lambdas"))


def _sns_event(message: dict) -> dict:
    return {"Records": [{"EventSource": "aws:sns", "Sns": {"Message": json.dumps(message)}}]}


def test_alarm_message_flips_flag():
    from handlers import auto_pause  # type: ignore

    ssm_calls: list[dict] = []

    class FakeSSM:
        def put_parameter(self, **kw):
            ssm_calls.append(kw)
        def get_parameter(self, **kw):
            return {"Parameter": {"Value": "false"}}

    msg = {"AlarmName": "nova-factory-v2-execution-failures", "NewStateValue": "ALARM", "NewStateReason": "3 consecutive failures"}
    with patch.object(auto_pause, "_ssm", FakeSSM()):
        result = auto_pause.handler(_sns_event(msg), None)

    assert result["paused"] is True
    assert ssm_calls and ssm_calls[0]["Value"] == "true"


def test_budget_message_flips_flag():
    from handlers import auto_pause  # type: ignore

    class FakeSSM:
        def __init__(self):
            self.puts = []
        def put_parameter(self, **kw):
            self.puts.append(kw)
        def get_parameter(self, **kw):
            return {"Parameter": {"Value": "false"}}

    fake = FakeSSM()
    msg = {"BudgetName": "nova-factory-monthly-100", "NotificationType": "ACTUAL", "NotificationState": "ALARM", "ActualAmount": "105"}
    with patch.object(auto_pause, "_ssm", fake):
        result = auto_pause.handler(_sns_event(msg), None)

    assert result["paused"] is True
    assert fake.puts and fake.puts[0]["Value"] == "true"


def test_already_paused_is_idempotent():
    from handlers import auto_pause  # type: ignore

    class FakeSSM:
        def __init__(self):
            self.puts = []
        def put_parameter(self, **kw):
            self.puts.append(kw)
        def get_parameter(self, **kw):
            return {"Parameter": {"Value": "true"}}

    fake = FakeSSM()
    msg = {"AlarmName": "nova-factory-v2-execution-failures", "NewStateValue": "ALARM"}
    with patch.object(auto_pause, "_ssm", fake):
        result = auto_pause.handler(_sns_event(msg), None)

    assert result["paused"] is True
    assert result["was_already_paused"] is True
    assert fake.puts == []


def test_ok_state_does_not_unpause():
    """If an alarm transitions back to OK, we do NOT auto-unpause — humans
    must explicitly reset the flag."""
    from handlers import auto_pause  # type: ignore

    class FakeSSM:
        def __init__(self):
            self.puts = []
        def put_parameter(self, **kw):
            self.puts.append(kw)
        def get_parameter(self, **kw):
            return {"Parameter": {"Value": "true"}}

    fake = FakeSSM()
    msg = {"AlarmName": "nova-factory-v2-execution-failures", "NewStateValue": "OK"}
    with patch.object(auto_pause, "_ssm", fake):
        result = auto_pause.handler(_sns_event(msg), None)

    assert fake.puts == []
    assert result.get("ignored") is True
