{
  "Comment": "Nova factory v2 — full pipeline. Spec §1 + §2.3.1.",
  "TimeoutSeconds": 7200,
  "StartAt": "AcquireLock",
  "States": {
    "AcquireLock": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-acquire-lock",
        "Payload": {"feature_id.$": "$.feature_id", "execution_id.$": "$$.Execution.Name"}
      },
      "ResultPath": "$.lock",
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "FailLocked"}],
      "Next": "MarkInProgress"
    },

    "MarkInProgress": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-update-notion",
        "Payload": {"feature_id.$": "$.feature_id", "status": "Building"}
      },
      "ResultPath": null,
      "Next": "LoadFeature"
    },

    "LoadFeature": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-load-feature",
        "Payload": {"feature_id.$": "$.feature_id", "execution_id.$": "$$.Execution.Name"}
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
        "Payload": {"feature_id.$": "$.feature_id", "execution_id.$": "$$.Execution.Name"}
      },
      "ResultPath": "$.plan",
      "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 10, "MaxAttempts": 2, "BackoffRate": 2.0}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "PlanGate"
    },

    "PlanGate": {
      "Type": "Choice",
      "Choices": [{"Variable": "$.plan.Payload.blocked", "BooleanEquals": true, "Next": "MarkBlocked"}],
      "Default": "LoopInit"
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

    "LoopInit": {
      "Type": "Pass",
      "Parameters": {
        "iter":                  0,
        "input_tokens":          0,
        "output_tokens":         0,
        "completion_signal":     false,
        "validate_repair_count": 0,
        "review_repair_count":   0
      },
      "ResultPath": "$.loop",
      "Next": "LoopChoice"
    },

    "LoopChoice": {
      "Type": "Choice",
      "Choices": [
        {"Variable": "$.loop.completion_signal", "BooleanEquals": true,        "Next": "Validate"},
        {"Variable": "$.loop.iter",              "NumericGreaterThanEquals": 6, "Next": "MarkBudgetExceeded"},
        {"Variable": "$.loop.input_tokens",      "NumericGreaterThanEquals": 2000000, "Next": "MarkBudgetExceeded"}
      ],
      "Default": "RalphTurn"
    },

    "RalphTurn": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-ralph-turn",
        "Payload": {
          "feature_id.$":   "$.feature_id",
          "execution_id.$": "$$.Execution.Name",
          "iter.$":         "$.loop.iter"
        }
      },
      "ResultPath": "$.turn",
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "LoopBump"
    },

    "LoopBump": {
      "Type": "Pass",
      "Parameters": {
        "iter.$":                "$.turn.Payload.iter",
        "input_tokens.$":        "States.MathAdd($.loop.input_tokens,  $.turn.Payload.input_tokens)",
        "output_tokens.$":       "States.MathAdd($.loop.output_tokens, $.turn.Payload.output_tokens)",
        "completion_signal.$":   "$.turn.Payload.completion_signal",
        "validate_repair_count.$": "$.loop.validate_repair_count",
        "review_repair_count.$":   "$.loop.review_repair_count"
      },
      "ResultPath": "$.loop",
      "Next": "LoopChoice"
    },

    "Validate": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-validate-v2",
        "Payload": {"execution_id.$": "$$.Execution.Name"}
      },
      "ResultPath": "$.validate",
      "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 10, "MaxAttempts": 2, "BackoffRate": 2.0}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "ValidateChoice"
    },

    "ValidateChoice": {
      "Type": "Choice",
      "Choices": [
        {"Variable": "$.validate.Payload.passed", "BooleanEquals": true, "Next": "Review"},
        {"Variable": "$.loop.validate_repair_count", "NumericGreaterThanEquals": 2, "Next": "MarkValidateFailed"}
      ],
      "Default": "ValidateRepairTurn"
    },

    "ValidateRepairTurn": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-ralph-turn",
        "Payload": {
          "feature_id.$":   "$.feature_id",
          "execution_id.$": "$$.Execution.Name",
          "iter.$":         "$.loop.iter"
        }
      },
      "ResultPath": "$.turn",
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "ValidateRepairBump"
    },

    "ValidateRepairBump": {
      "Type": "Pass",
      "Parameters": {
        "iter.$":                  "$.turn.Payload.iter",
        "input_tokens.$":          "States.MathAdd($.loop.input_tokens,  $.turn.Payload.input_tokens)",
        "output_tokens.$":         "States.MathAdd($.loop.output_tokens, $.turn.Payload.output_tokens)",
        "completion_signal.$":     "$.turn.Payload.completion_signal",
        "validate_repair_count.$": "States.MathAdd($.loop.validate_repair_count, 1)",
        "review_repair_count.$":   "$.loop.review_repair_count"
      },
      "ResultPath": "$.loop",
      "Next": "Validate"
    },

    "Review": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-review",
        "Payload": {"execution_id.$": "$$.Execution.Name", "feature_id.$": "$.feature_id"}
      },
      "ResultPath": "$.review",
      "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 10, "MaxAttempts": 2, "BackoffRate": 2.0}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "ReviewChoice"
    },

    "ReviewChoice": {
      "Type": "Choice",
      "Choices": [
        {"Variable": "$.review.Payload.passed", "BooleanEquals": true, "Next": "CommitAndPush"},
        {"Variable": "$.loop.review_repair_count", "NumericGreaterThanEquals": 2, "Next": "MarkReviewFailed"}
      ],
      "Default": "ReviewRepairTurn"
    },

    "ReviewRepairTurn": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-ralph-turn",
        "Payload": {
          "feature_id.$":   "$.feature_id",
          "execution_id.$": "$$.Execution.Name",
          "iter.$":         "$.loop.iter"
        }
      },
      "ResultPath": "$.turn",
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "ReviewRepairBump"
    },

    "ReviewRepairBump": {
      "Type": "Pass",
      "Parameters": {
        "iter.$":                  "$.turn.Payload.iter",
        "input_tokens.$":          "States.MathAdd($.loop.input_tokens,  $.turn.Payload.input_tokens)",
        "output_tokens.$":         "States.MathAdd($.loop.output_tokens, $.turn.Payload.output_tokens)",
        "completion_signal.$":     "$.turn.Payload.completion_signal",
        "validate_repair_count.$": "$.loop.validate_repair_count",
        "review_repair_count.$":   "States.MathAdd($.loop.review_repair_count, 1)"
      },
      "ResultPath": "$.loop",
      "Next": "Validate"
    },

    "CommitAndPush": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-commit-and-push-v2",
        "Payload": {"feature_id.$": "$.feature_id", "execution_id.$": "$$.Execution.Name"}
      },
      "ResultPath": "$.commit",
      "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 10, "MaxAttempts": 2, "BackoffRate": 2.0}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "WaitForQualityGates"
    },

    "WaitForQualityGates": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke.waitForTaskToken",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-trigger-quality-gates",
        "Payload": {
          "branch.$":     "$.commit.Payload.branch",
          "pr_number.$":  "$.commit.Payload.pr_number",
          "task_token.$": "$$.Task.Token"
        }
      },
      "TimeoutSeconds": 5400,
      "ResultPath": "$.quality",
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "MarkDone"
    },

    "MarkDone": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-update-notion",
        "Payload": {
          "feature_id.$": "$.feature_id",
          "status": "Done",
          "extras": {"pr_url.$": "$.commit.Payload.pr_url"}
        }
      },
      "ResultPath": null,
      "Next": "ReleaseLock"
    },

    "ReleaseLock": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-release-lock",
        "Payload": {"feature_id.$": "$.feature_id", "execution_id.$": "$$.Execution.Name"}
      },
      "ResultPath": null,
      "End": true
    },

    "MarkValidateFailed": {
      "Type": "Pass",
      "Parameters": {"reason": "validate_failed_after_repairs"},
      "ResultPath": "$.error",
      "Next": "MarkFailedAndRelease"
    },

    "MarkReviewFailed": {
      "Type": "Pass",
      "Parameters": {"reason": "review_failed_after_repairs"},
      "ResultPath": "$.error",
      "Next": "MarkFailedAndRelease"
    },

    "MarkBudgetExceeded": {
      "Type": "Pass",
      "Parameters": {"reason": "ralph_budget_exceeded"},
      "ResultPath": "$.error",
      "Next": "MarkFailedAndRelease"
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
        "Payload": {"feature_id.$": "$.feature_id", "execution_id.$": "$$.Execution.Name"}
      },
      "ResultPath": null,
      "Next": "FailState"
    },

    "FailLocked": {"Type": "Pass", "Result": {"reason": "locked_by_another_execution"}, "Next": "FailState"},
    "FailState":  {"Type": "Fail", "Error": "FactoryV2Failed"}
  }
}
