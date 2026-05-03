{
  "Comment": "Nova factory v2 — Phase 2 STUB (Plan stage only). Replaced in Phase 3 with the full v2 pipeline.",
  "TimeoutSeconds": 600,
  "StartAt": "AcquireLock",
  "States": {
    "AcquireLock": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-acquire-lock",
        "Payload": {
          "feature_id.$":   "$.feature_id",
          "execution_id.$": "$$.Execution.Name"
        }
      },
      "ResultPath": "$.lock",
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "FailLocked"}],
      "Next": "LoadFeature"
    },

    "LoadFeature": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-load-feature",
        "Payload": {
          "feature_id.$":   "$.feature_id",
          "execution_id.$": "$$.Execution.Name"
        }
      },
      "ResultPath": "$.intake",
      "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 5, "MaxAttempts": 3, "BackoffRate": 2.0}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "Plan"
    },

    "Plan": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-plan",
        "Payload": {
          "feature_id.$":   "$.feature_id",
          "execution_id.$": "$$.Execution.Name"
        }
      },
      "ResultPath": "$.plan",
      "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 10, "MaxAttempts": 2, "BackoffRate": 2.0}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "PlanGate"
    },

    "PlanGate": {
      "Type": "Choice",
      "Choices": [
        {
          "Variable": "$.plan.Payload.blocked",
          "BooleanEquals": true,
          "Next": "MarkBlocked"
        }
      ],
      "Default": "MarkPlanOK"
    },

    "MarkBlocked": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-mark-blocked",
        "Payload": {
          "feature_id.$":      "$.feature_id",
          "hard_blockers.$":   "$.plan.Payload.hard_blockers",
          "suggested_split.$": "$.plan.Payload.suggested_split"
        }
      },
      "ResultPath": null,
      "Next": "ReleaseLock"
    },

    "MarkPlanOK": {
      "Type": "Pass",
      "Comment": "Phase 2 placeholder: in Phase 3 this becomes the entry point to RalphLoop.",
      "Result": {"plan": "ok"},
      "ResultPath": "$.phase2_terminal",
      "Next": "ReleaseLock"
    },

    "ReleaseLock": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-release-lock",
        "Payload": {
          "feature_id.$":   "$.feature_id",
          "execution_id.$": "$$.Execution.Name"
        }
      },
      "ResultPath": null,
      "End": true
    },

    "MarkFailedAndRelease": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-update-notion",
        "Payload": {
          "feature_id.$": "$.feature_id",
          "status": "Failed",
          "extras": {"error.$": "States.JsonToString($.error)"}
        }
      },
      "ResultPath": null,
      "Next": "ReleaseLockAfterFailure"
    },

    "ReleaseLockAfterFailure": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-release-lock",
        "Payload": {
          "feature_id.$":   "$.feature_id",
          "execution_id.$": "$$.Execution.Name"
        }
      },
      "ResultPath": null,
      "Next": "FailState"
    },

    "FailLocked": {
      "Type": "Pass",
      "Result": {"reason": "locked_by_another_execution"},
      "Next": "FailState"
    },

    "FailState": {"Type": "Fail", "Error": "FactoryV2PlanOnlyFailed"}
  }
}
