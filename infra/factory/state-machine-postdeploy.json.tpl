{
  "Comment": "Nova factory postdeploy verification. Spec §2.7.",
  "TimeoutSeconds": 1800,
  "StartAt": "ProbeStaging",
  "States": {
    "ProbeStaging": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-probe-staging",
        "Payload": {
          "feature_id.$": "$.feature_id",
          "merge_sha.$":  "$.merge_sha"
        }
      },
      "ResultPath": "$.probe",
      "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 30, "MaxAttempts": 2, "BackoffRate": 2.0}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "AlarmAndFail"}],
      "Next": "Healthy"
    },

    "Healthy": {
      "Type": "Choice",
      "Choices": [
        {"Variable": "$.probe.Payload.passed", "BooleanEquals": true, "Next": "MarkVerified"}
      ],
      "Default": "RevertMerge"
    },

    "MarkVerified": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-update-notion",
        "Payload": {
          "feature_id.$": "$.feature_id",
          "status": "Verified",
          "extras": {}
        }
      },
      "ResultPath": null,
      "End": true
    },

    "RevertMerge": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-revert-merge",
        "Payload": {
          "feature_id.$": "$.feature_id",
          "merge_sha.$":  "$.merge_sha",
          "failures.$":   "$.probe.Payload.failures"
        }
      },
      "ResultPath": "$.revert",
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "AlarmAndFail"}],
      "Next": "RevertSuccess"
    },

    "RevertSuccess": {
      "Type": "Pass",
      "Comment": "RevertMerge succeeded — feature is back to a known-good state on main.",
      "End": true
    },

    "AlarmAndFail": {
      "Type": "Task",
      "Resource": "arn:aws:states:::sns:publish",
      "Parameters": {
        "TopicArn": "${sns_alerts_arn}",
        "Subject":  "Postdeploy probe AND revert failed — manual intervention required",
        "Message.$": "States.JsonToString($)"
      },
      "ResultPath": null,
      "Next": "FailState"
    },

    "FailState": {"Type": "Fail", "Error": "PostdeployFailed"}
  }
}
