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
        "feature_id.$":   "$.feature_id"
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
                "agent_name.$":   "$.agent_name",
                "execution_id.$": "$.execution_id",
                "feature_id.$":   "$.feature_id"
              }
            },
            "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 15, "MaxAttempts": 2, "BackoffRate": 2.0}],
            "End": true
          }
        }
      },
      "ResultPath": null,
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "ValidateDatabase"
    },

    "ValidateDatabase": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-validate-workspace",
        "Payload": {
          "execution_id.$": "$$.Execution.Name",
          "feature_id.$":   "$.feature_id",
          "phase":          "database"
        }
      },
      "ResultPath": "$.db_validation",
      "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 10, "MaxAttempts": 2, "BackoffRate": 2.0}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "DBValidationChoice"
    },

    "DBValidationChoice": {
      "Type": "Choice",
      "Choices": [
        {"Variable": "$.db_validation.Payload.passed", "BooleanEquals": true, "Next": "BuildersPhase"},
        {
          "And": [
            {"Variable": "$.db_validation.Payload.passed", "BooleanEquals": false},
            {"Variable": "$.db_repaired", "IsPresent": false}
          ],
          "Next": "SetDBRepaired"
        }
      ],
      "Default": "MarkFailedAndRelease"
    },

    "SetDBRepaired": {
      "Type": "Pass",
      "Result": true,
      "ResultPath": "$.db_repaired",
      "Next": "RepairDatabase"
    },

    "RepairDatabase": {
      "Type": "Map",
      "ItemsPath": "$.db_validation.Payload.failing_owners",
      "MaxConcurrency": 1,
      "ItemSelector": {
        "agent_name.$":     "$$.Map.Item.Value",
        "execution_id.$":   "$$.Execution.Name",
        "feature_id.$":     "$.feature_id",
        "repair_context.$": "$.db_validation.Payload.issues_by_owner"
      },
      "ItemProcessor": {
        "ProcessorConfig": {"Mode": "INLINE"},
        "StartAt": "DB_RepairAgent",
        "States": {
          "DB_RepairAgent": {
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
            "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 15, "MaxAttempts": 2, "BackoffRate": 2.0}],
            "End": true
          }
        }
      },
      "ResultPath": null,
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "ValidateDatabase"
    },

    "BuildersPhase": {
      "Type": "Map",
      "ItemsPath": "$.orchestrator.Payload.plan.execution_phases.builders",
      "MaxConcurrency": 3,
      "ItemSelector": {
        "agent_name.$":   "$$.Map.Item.Value",
        "execution_id.$": "$$.Execution.Name",
        "feature_id.$":   "$.feature_id"
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
                "agent_name.$":   "$.agent_name",
                "execution_id.$": "$.execution_id",
                "feature_id.$":   "$.feature_id"
              }
            },
            "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 15, "MaxAttempts": 2, "BackoffRate": 2.0}],
            "End": true
          }
        }
      },
      "ResultPath": null,
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "ValidateBuilders"
    },

    "ValidateBuilders": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-validate-workspace",
        "Payload": {
          "execution_id.$": "$$.Execution.Name",
          "feature_id.$":   "$.feature_id",
          "phase":          "builders"
        }
      },
      "ResultPath": "$.bld_validation",
      "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 10, "MaxAttempts": 2, "BackoffRate": 2.0}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "BLDValidationChoice"
    },

    "BLDValidationChoice": {
      "Type": "Choice",
      "Choices": [
        {"Variable": "$.bld_validation.Payload.passed", "BooleanEquals": true, "Next": "TestPhase"},
        {
          "And": [
            {"Variable": "$.bld_validation.Payload.passed", "BooleanEquals": false},
            {"Variable": "$.bld_repaired", "IsPresent": false}
          ],
          "Next": "SetBLDRepaired"
        }
      ],
      "Default": "MarkFailedAndRelease"
    },

    "SetBLDRepaired": {
      "Type": "Pass",
      "Result": true,
      "ResultPath": "$.bld_repaired",
      "Next": "RepairBuilders"
    },

    "RepairBuilders": {
      "Type": "Map",
      "ItemsPath": "$.bld_validation.Payload.failing_owners",
      "MaxConcurrency": 3,
      "ItemSelector": {
        "agent_name.$":     "$$.Map.Item.Value",
        "execution_id.$":   "$$.Execution.Name",
        "feature_id.$":     "$.feature_id",
        "repair_context.$": "$.bld_validation.Payload.issues_by_owner"
      },
      "ItemProcessor": {
        "ProcessorConfig": {"Mode": "INLINE"},
        "StartAt": "BLD_RepairAgent",
        "States": {
          "BLD_RepairAgent": {
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
            "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 15, "MaxAttempts": 2, "BackoffRate": 2.0}],
            "End": true
          }
        }
      },
      "ResultPath": null,
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "ValidateBuilders"
    },

    "TestPhase": {
      "Type": "Map",
      "ItemsPath": "$.orchestrator.Payload.plan.execution_phases.test",
      "MaxConcurrency": 1,
      "ItemSelector": {
        "agent_name.$":   "$$.Map.Item.Value",
        "execution_id.$": "$$.Execution.Name",
        "feature_id.$":   "$.feature_id"
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
                "agent_name.$":   "$.agent_name",
                "execution_id.$": "$.execution_id",
                "feature_id.$":   "$.feature_id"
              }
            },
            "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 15, "MaxAttempts": 2, "BackoffRate": 2.0}],
            "End": true
          }
        }
      },
      "ResultPath": null,
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "ValidateTest"
    },

    "ValidateTest": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-validate-workspace",
        "Payload": {
          "execution_id.$": "$$.Execution.Name",
          "feature_id.$":   "$.feature_id",
          "phase":          "test"
        }
      },
      "ResultPath": "$.tst_validation",
      "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 10, "MaxAttempts": 2, "BackoffRate": 2.0}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "TSTValidationChoice"
    },

    "TSTValidationChoice": {
      "Type": "Choice",
      "Choices": [
        {"Variable": "$.tst_validation.Payload.passed", "BooleanEquals": true, "Next": "RunSecurityReview"},
        {
          "And": [
            {"Variable": "$.tst_validation.Payload.passed", "BooleanEquals": false},
            {"Variable": "$.tst_repaired", "IsPresent": false}
          ],
          "Next": "SetTSTRepaired"
        }
      ],
      "Default": "MarkFailedAndRelease"
    },

    "SetTSTRepaired": {
      "Type": "Pass",
      "Result": true,
      "ResultPath": "$.tst_repaired",
      "Next": "RepairTest"
    },

    "RepairTest": {
      "Type": "Map",
      "ItemsPath": "$.tst_validation.Payload.failing_owners",
      "MaxConcurrency": 2,
      "ItemSelector": {
        "agent_name.$":     "$$.Map.Item.Value",
        "execution_id.$":   "$$.Execution.Name",
        "feature_id.$":     "$.feature_id",
        "repair_context.$": "$.tst_validation.Payload.issues_by_owner"
      },
      "ItemProcessor": {
        "ProcessorConfig": {"Mode": "INLINE"},
        "StartAt": "TST_RepairAgent",
        "States": {
          "TST_RepairAgent": {
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
            "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 15, "MaxAttempts": 2, "BackoffRate": 2.0}],
            "End": true
          }
        }
      },
      "ResultPath": null,
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "ValidateTest"
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
