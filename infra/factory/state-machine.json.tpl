{
  "Comment": "Nova factory pipeline",
  "TimeoutSeconds": 3600,
  "StartAt": "AcquireLock",
  "States": {
    "AcquireLock": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-acquire-lock",
        "Payload": {
          "feature_id.$": "$.feature_id",
          "execution_id.$": "$$.Execution.Name"
        }
      },
      "ResultPath": "$.lock",
      "Catch": [{
        "ErrorEquals": ["States.ALL"],
        "ResultPath": "$.error",
        "Next": "MarkFailed"
      }],
      "Next": "MarkInProgress"
    },

    "MarkInProgress": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-update-notion",
        "Payload": {
          "feature_id.$": "$.feature_id",
          "status": "In Progress"
        }
      },
      "ResultPath": null,
      "Next": "LoadSpec"
    },

    "LoadSpec": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-load-spec",
        "Payload": {
          "feature_id.$": "$.feature_id",
          "execution_id.$": "$$.Execution.Name"
        }
      },
      "ResultPath": "$.spec_meta",
      "Retry": [{
        "ErrorEquals": ["States.ALL"],
        "IntervalSeconds": 5,
        "MaxAttempts": 3,
        "BackoffRate": 2.0
      }],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "LoadProjectContext"
    },

    "LoadProjectContext": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-load-project-context",
        "Payload": {
          "execution_id.$": "$$.Execution.Name"
        }
      },
      "ResultPath": null,
      "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 5, "MaxAttempts": 2, "BackoffRate": 2.0}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "RunOrchestrator"
    },

    "RunOrchestrator": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-run-orchestrator",
        "Payload": {
          "feature_id.$": "$.feature_id",
          "execution_id.$": "$$.Execution.Name"
        }
      },
      "ResultPath": "$.orchestrator",
      "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 10, "MaxAttempts": 2, "BackoffRate": 2.0}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "RunSpecAnalyst"
    },

    "RunSpecAnalyst": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-run-agent",
        "Payload": {
          "agent_name": "spec-analyst",
          "feature_id.$": "$.feature_id",
          "execution_id.$": "$$.Execution.Name"
        }
      },
      "ResultPath": null,
      "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 10, "MaxAttempts": 2, "BackoffRate": 2.0}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "RunArchitect"
    },

    "RunArchitect": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-run-agent",
        "Payload": {
          "agent_name": "architect",
          "feature_id.$": "$.feature_id",
          "execution_id.$": "$$.Execution.Name"
        }
      },
      "ResultPath": null,
      "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 10, "MaxAttempts": 2, "BackoffRate": 2.0}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "DatabasePhase"
    },

    "DatabasePhase": {
      "Type": "Map",
      "ItemsPath": "$.orchestrator.Payload.plan.execution_phases.database",
      "MaxConcurrency": 1,
      "ItemSelector": {
        "agent_name.$":   "$$.Map.Item.Value",
        "execution_id.$": "$$.Execution.Name",
        "feature_id.$":   "$.feature_id",
        "repair_count":   0,
        "repair_context": null
      },
      "ItemProcessor": {
        "ProcessorConfig": {"Mode": "INLINE"},
        "StartAt": "DB_RunAgent",
        "States": {
          "DB_RunAgent": {
            "Type": "Task",
            "Resource": "arn:aws:states:::lambda:invoke",
            "Parameters": {
              "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-run-agent",
              "Payload": {
                "agent_name.$":     "$.agent_name",
                "execution_id.$":   "$.execution_id",
                "feature_id.$":     "$.feature_id",
                "repair_context.$": "$.repair_context"
              }
            },
            "ResultPath": "$.agent_result",
            "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 15, "MaxAttempts": 2, "BackoffRate": 2.0}],
            "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.run_error", "Next": "DB_AgentFailed"}],
            "Next": "DB_Validate"
          },
          "DB_Validate": {
            "Type": "Task",
            "Resource": "arn:aws:states:::lambda:invoke",
            "Parameters": {
              "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-validate-database",
              "Payload": {
                "execution_id.$": "$.execution_id",
                "feature_id.$":   "$.feature_id"
              }
            },
            "ResultPath": "$.validation",
            "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 10, "MaxAttempts": 2, "BackoffRate": 2.0}],
            "Next": "DB_ValidationChoice"
          },
          "DB_ValidationChoice": {
            "Type": "Choice",
            "Choices": [
              {"Variable": "$.validation.Payload.passed", "BooleanEquals": true, "Next": "DB_Done"},
              {
                "And": [
                  {"Variable": "$.validation.Payload.passed", "BooleanEquals": false},
                  {"Variable": "$.repair_count", "NumericLessThan": 2}
                ],
                "Next": "DB_BumpRepair"
              }
            ],
            "Default": "DB_Exhausted"
          },
          "DB_BumpRepair": {
            "Type": "Pass",
            "Parameters": {
              "agent_name.$":     "$.agent_name",
              "execution_id.$":   "$.execution_id",
              "feature_id.$":     "$.feature_id",
              "repair_context.$": "$.validation.Payload.issues",
              "repair_count.$":   "States.MathAdd($.repair_count, 1)"
            },
            "Next": "DB_RunAgent"
          },
          "DB_Exhausted": {
            "Type": "Fail",
            "Error": "ValidationExhausted",
            "Cause": "Database agent could not produce passing output after 2 repair attempts"
          },
          "DB_AgentFailed": {
            "Type": "Fail",
            "Error": "AgentFailed",
            "CausePath": "$.run_error.Cause"
          },
          "DB_Done": {"Type": "Succeed"}
        }
      },
      "ResultPath": null,
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "BuildersPhase"
    },

    "BuildersPhase": {
      "Type": "Map",
      "ItemsPath": "$.orchestrator.Payload.plan.execution_phases.builders",
      "MaxConcurrency": 3,
      "ItemSelector": {
        "agent_name.$":   "$$.Map.Item.Value",
        "execution_id.$": "$$.Execution.Name",
        "feature_id.$":   "$.feature_id",
        "repair_count":   0,
        "repair_context": null
      },
      "ItemProcessor": {
        "ProcessorConfig": {"Mode": "INLINE"},
        "StartAt": "BLD_RunAgent",
        "States": {
          "BLD_RunAgent": {
            "Type": "Task",
            "Resource": "arn:aws:states:::lambda:invoke",
            "Parameters": {
              "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-run-agent",
              "Payload": {
                "agent_name.$":     "$.agent_name",
                "execution_id.$":   "$.execution_id",
                "feature_id.$":     "$.feature_id",
                "repair_context.$": "$.repair_context"
              }
            },
            "ResultPath": "$.agent_result",
            "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 15, "MaxAttempts": 2, "BackoffRate": 2.0}],
            "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.run_error", "Next": "BLD_AgentFailed"}],
            "Next": "BLD_ChooseValidator"
          },
          "BLD_ChooseValidator": {
            "Type": "Choice",
            "Choices": [
              {"Variable": "$.agent_name", "StringEquals": "backend",        "Next": "BLD_Validate"},
              {"Variable": "$.agent_name", "StringEquals": "frontend",       "Next": "BLD_Validate"},
              {"Variable": "$.agent_name", "StringEquals": "infrastructure", "Next": "BLD_Validate"}
            ],
            "Default": "BLD_Done"
          },
          "BLD_Validate": {
            "Type": "Task",
            "Resource": "arn:aws:states:::lambda:invoke",
            "Parameters": {
              "FunctionName.$": "States.Format('arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-validate-{}', $.agent_name)",
              "Payload": {
                "execution_id.$": "$.execution_id",
                "feature_id.$":   "$.feature_id"
              }
            },
            "ResultPath": "$.validation",
            "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 10, "MaxAttempts": 2, "BackoffRate": 2.0}],
            "Next": "BLD_ValidationChoice"
          },
          "BLD_ValidationChoice": {
            "Type": "Choice",
            "Choices": [
              {"Variable": "$.validation.Payload.passed", "BooleanEquals": true, "Next": "BLD_Done"},
              {
                "And": [
                  {"Variable": "$.validation.Payload.passed", "BooleanEquals": false},
                  {"Variable": "$.repair_count", "NumericLessThan": 2}
                ],
                "Next": "BLD_BumpRepair"
              }
            ],
            "Default": "BLD_Exhausted"
          },
          "BLD_BumpRepair": {
            "Type": "Pass",
            "Parameters": {
              "agent_name.$":     "$.agent_name",
              "execution_id.$":   "$.execution_id",
              "feature_id.$":     "$.feature_id",
              "repair_context.$": "$.validation.Payload.issues",
              "repair_count.$":   "States.MathAdd($.repair_count, 1)"
            },
            "Next": "BLD_RunAgent"
          },
          "BLD_Exhausted": {
            "Type": "Fail",
            "Error": "ValidationExhausted",
            "Cause": "Builder agent could not produce passing output after 2 repair attempts"
          },
          "BLD_AgentFailed": {
            "Type": "Fail",
            "Error": "AgentFailed",
            "CausePath": "$.run_error.Cause"
          },
          "BLD_Done": {"Type": "Succeed"}
        }
      },
      "ResultPath": null,
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "TestPhase"
    },

    "TestPhase": {
      "Type": "Map",
      "ItemsPath": "$.orchestrator.Payload.plan.execution_phases.test",
      "MaxConcurrency": 1,
      "ItemSelector": {
        "agent_name.$":   "$$.Map.Item.Value",
        "execution_id.$": "$$.Execution.Name",
        "feature_id.$":   "$.feature_id",
        "repair_count":   0,
        "repair_context": null
      },
      "ItemProcessor": {
        "ProcessorConfig": {"Mode": "INLINE"},
        "StartAt": "TST_RunAgent",
        "States": {
          "TST_RunAgent": {
            "Type": "Task",
            "Resource": "arn:aws:states:::lambda:invoke",
            "Parameters": {
              "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-run-agent",
              "Payload": {
                "agent_name.$":     "$.agent_name",
                "execution_id.$":   "$.execution_id",
                "feature_id.$":     "$.feature_id",
                "repair_context.$": "$.repair_context"
              }
            },
            "ResultPath": "$.agent_result",
            "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 15, "MaxAttempts": 2, "BackoffRate": 2.0}],
            "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.run_error", "Next": "TST_AgentFailed"}],
            "Next": "TST_Validate"
          },
          "TST_Validate": {
            "Type": "Task",
            "Resource": "arn:aws:states:::lambda:invoke",
            "Parameters": {
              "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-validate-test",
              "Payload": {
                "execution_id.$": "$.execution_id",
                "feature_id.$":   "$.feature_id"
              }
            },
            "ResultPath": "$.validation",
            "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 10, "MaxAttempts": 2, "BackoffRate": 2.0}],
            "Next": "TST_ValidationChoice"
          },
          "TST_ValidationChoice": {
            "Type": "Choice",
            "Choices": [
              {"Variable": "$.validation.Payload.passed", "BooleanEquals": true, "Next": "TST_Done"},
              {
                "And": [
                  {"Variable": "$.validation.Payload.passed", "BooleanEquals": false},
                  {"Variable": "$.repair_count", "NumericLessThan": 2}
                ],
                "Next": "TST_BumpRepair"
              }
            ],
            "Default": "TST_Exhausted"
          },
          "TST_BumpRepair": {
            "Type": "Pass",
            "Parameters": {
              "agent_name.$":     "$.agent_name",
              "execution_id.$":   "$.execution_id",
              "feature_id.$":     "$.feature_id",
              "repair_context.$": "$.validation.Payload.issues",
              "repair_count.$":   "States.MathAdd($.repair_count, 1)"
            },
            "Next": "TST_RunAgent"
          },
          "TST_Exhausted": {
            "Type": "Fail",
            "Error": "ValidationExhausted",
            "Cause": "Test agent could not produce passing output after 2 repair attempts"
          },
          "TST_AgentFailed": {
            "Type": "Fail",
            "Error": "AgentFailed",
            "CausePath": "$.run_error.Cause"
          },
          "TST_Done": {"Type": "Succeed"}
        }
      },
      "ResultPath": null,
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "RunSecurityReview"
    },

    "RunSecurityReview": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-run-agent",
        "Payload": {
          "agent_name": "security-reviewer",
          "feature_id.$": "$.feature_id",
          "execution_id.$": "$$.Execution.Name"
        }
      },
      "ResultPath": "$.security",
      "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 10, "MaxAttempts": 2, "BackoffRate": 2.0}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "EvaluateSecurity"
    },

    "EvaluateSecurity": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-evaluate-security",
        "Payload": {
          "execution_id.$": "$$.Execution.Name",
          "feature_id.$": "$.feature_id"
        }
      },
      "ResultPath": "$.security_eval",
      "Next": "SecurityChoice"
    },

    "SecurityChoice": {
      "Type": "Choice",
      "Choices": [
        {
          "Variable": "$.security_eval.Payload.passed",
          "BooleanEquals": true,
          "Next": "CommitAndPush"
        },
        {
          "And": [
            {"Variable": "$.security_eval.Payload.passed",     "BooleanEquals": false},
            {"Variable": "$.security_eval.Payload.repairable", "BooleanEquals": true},
            {"Variable": "$.repair_attempted",                 "IsPresent": false}
          ],
          "Next": "SetRepairAttempted"
        }
      ],
      "Default": "MarkFailedAndRelease"
    },

    "SetRepairAttempted": {
      "Type": "Pass",
      "Result": true,
      "ResultPath": "$.repair_attempted",
      "Next": "RunSecurityRepairAgent"
    },

    "RunSecurityRepairAgent": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-run-agent",
        "Payload": {
          "agent_name": "backend",
          "feature_id.$": "$.feature_id",
          "execution_id.$": "$$.Execution.Name",
          "repair_context.$": "$.security_eval.Payload.issues"
        }
      },
      "ResultPath": null,
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "RunSecurityReview"
    },

    "CommitAndPush": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-commit-and-push",
        "Payload": {
          "feature_id.$": "$.feature_id",
          "execution_id.$": "$$.Execution.Name"
        }
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
      "TimeoutSeconds": 1200,
      "ResultPath": "$.quality",
      "Catch": [
        {"ErrorEquals": ["QualityGateFailure"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"},
        {"ErrorEquals": ["States.ALL"],         "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}
      ],
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

    "MarkFailed": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-update-notion",
        "Payload": {
          "feature_id.$": "$.feature_id",
          "status": "Failed",
          "extras": {"error": "Locked by another execution"}
        }
      },
      "ResultPath": null,
      "Next": "FailState"
    },

    "FailState": {"Type": "Fail", "Error": "FactoryFailed"}
  }
}
