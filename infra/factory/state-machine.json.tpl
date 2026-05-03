{
  "Comment": "Nova factory pipeline",
  "TimeoutSeconds": 3600,
  "StartAt": "AcquireLock",
  "States": {
    "AcquireLock": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:$${region}:$${account_id}:function:$${name_prefix}-acquire-lock",
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
        "FunctionName": "arn:aws:lambda:$${region}:$${account_id}:function:$${name_prefix}-update-notion",
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
        "FunctionName": "arn:aws:lambda:$${region}:$${account_id}:function:$${name_prefix}-load-spec",
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
      "Next": "RunOrchestrator"
    },

    "RunOrchestrator": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:$${region}:$${account_id}:function:$${name_prefix}-run-orchestrator",
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
        "FunctionName": "arn:aws:lambda:$${region}:$${account_id}:function:$${name_prefix}-run-agent",
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
        "FunctionName": "arn:aws:lambda:$${region}:$${account_id}:function:$${name_prefix}-run-agent",
        "Payload": {
          "agent_name": "architect",
          "feature_id.$": "$.feature_id",
          "execution_id.$": "$$.Execution.Name"
        }
      },
      "ResultPath": null,
      "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 10, "MaxAttempts": 2, "BackoffRate": 2.0}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "RunAgentGroupsMap"
    },

    "RunAgentGroupsMap": {
      "Type": "Map",
      "ItemsPath": "$.orchestrator.Payload.plan.parallel_groups",
      "MaxConcurrency": 1,
      "ItemSelector": {
        "group.$": "$$.Map.Item.Value",
        "execution_id.$": "$$.Execution.Name",
        "feature_id.$": "$.feature_id"
      },
      "ItemProcessor": {
        "ProcessorConfig": {"Mode": "INLINE"},
        "StartAt": "FanOut",
        "States": {
          "FanOut": {
            "Type": "Map",
            "ItemsPath": "$.group",
            "MaxConcurrency": 5,
            "ItemSelector": {
              "agent_name.$": "$$.Map.Item.Value",
              "execution_id.$": "$.execution_id",
              "feature_id.$": "$.feature_id",
              "repair_count": 0
            },
            "ItemProcessor": {
              "ProcessorConfig": {"Mode": "INLINE"},
              "StartAt": "RunOneAgent",
              "States": {
                "RunOneAgent": {
                  "Type": "Task",
                  "Resource": "arn:aws:states:::lambda:invoke",
                  "Parameters": {
                    "FunctionName": "arn:aws:lambda:$${region}:$${account_id}:function:$${name_prefix}-run-agent",
                    "Payload": {
                      "agent_name.$": "$.agent_name",
                      "execution_id.$": "$.execution_id",
                      "feature_id.$": "$.feature_id",
                      "repair_context.$": "$.repair_context"
                    }
                  },
                  "ResultPath": "$.agent_result",
                  "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 15, "MaxAttempts": 2, "BackoffRate": 2.0}],
                  "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.run_error", "Next": "AgentFailed"}],
                  "Next": "ChooseValidator"
                },
                "ChooseValidator": {
                  "Type": "Choice",
                  "Choices": [
                    {"Variable": "$.agent_name", "StringEquals": "backend",        "Next": "ValidateAgent"},
                    {"Variable": "$.agent_name", "StringEquals": "frontend",       "Next": "ValidateAgent"},
                    {"Variable": "$.agent_name", "StringEquals": "database",       "Next": "ValidateAgent"},
                    {"Variable": "$.agent_name", "StringEquals": "infrastructure", "Next": "ValidateAgent"},
                    {"Variable": "$.agent_name", "StringEquals": "test",           "Next": "ValidateAgent"}
                  ],
                  "Default": "AgentDone"
                },
                "ValidateAgent": {
                  "Type": "Task",
                  "Resource": "arn:aws:states:::lambda:invoke",
                  "Parameters": {
                    "FunctionName.$": "States.Format('arn:aws:lambda:$${region}:$${account_id}:function:$${name_prefix}-validate-{}', $.agent_name)",
                    "Payload": {
                      "execution_id.$": "$.execution_id",
                      "feature_id.$":   "$.feature_id"
                    }
                  },
                  "ResultPath": "$.validation",
                  "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 10, "MaxAttempts": 2, "BackoffRate": 2.0}],
                  "Next": "ValidationChoice"
                },
                "ValidationChoice": {
                  "Type": "Choice",
                  "Choices": [
                    {
                      "Variable": "$.validation.Payload.passed",
                      "BooleanEquals": true,
                      "Next": "AgentDone"
                    },
                    {
                      "And": [
                        {"Variable": "$.validation.Payload.passed", "BooleanEquals": false},
                        {"Variable": "$.repair_count", "NumericLessThan": 2}
                      ],
                      "Next": "BumpRepairAndRetry"
                    }
                  ],
                  "Default": "ValidationExhausted"
                },
                "BumpRepairAndRetry": {
                  "Type": "Pass",
                  "Parameters": {
                    "agent_name.$":     "$.agent_name",
                    "execution_id.$":   "$.execution_id",
                    "feature_id.$":     "$.feature_id",
                    "repair_context.$": "$.validation.Payload.issues",
                    "repair_count.$":   "States.MathAdd($.repair_count, 1)"
                  },
                  "Next": "RunOneAgent"
                },
                "ValidationExhausted": {
                  "Type": "Fail",
                  "Error": "ValidationExhausted",
                  "Cause": "Code agent could not produce passing output after 2 repair attempts"
                },
                "AgentFailed": {
                  "Type": "Fail",
                  "Error": "AgentFailed",
                  "CausePath": "$.run_error.Cause"
                },
                "AgentDone": {
                  "Type": "Succeed"
                }
              }
            },
            "End": true
          }
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
        "FunctionName": "arn:aws:lambda:$${region}:$${account_id}:function:$${name_prefix}-run-agent",
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
        "FunctionName": "arn:aws:lambda:$${region}:$${account_id}:function:$${name_prefix}-evaluate-security",
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
        "FunctionName": "arn:aws:lambda:$${region}:$${account_id}:function:$${name_prefix}-run-agent",
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
        "FunctionName": "arn:aws:lambda:$${region}:$${account_id}:function:$${name_prefix}-commit-and-push",
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
        "FunctionName": "arn:aws:lambda:$${region}:$${account_id}:function:$${name_prefix}-trigger-quality-gates",
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
        "FunctionName": "arn:aws:lambda:$${region}:$${account_id}:function:$${name_prefix}-update-notion",
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
        "FunctionName": "arn:aws:lambda:$${region}:$${account_id}:function:$${name_prefix}-release-lock",
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
        "FunctionName": "arn:aws:lambda:$${region}:$${account_id}:function:$${name_prefix}-update-notion",
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
        "FunctionName": "arn:aws:lambda:$${region}:$${account_id}:function:$${name_prefix}-release-lock",
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
        "FunctionName": "arn:aws:lambda:$${region}:$${account_id}:function:$${name_prefix}-update-notion",
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
