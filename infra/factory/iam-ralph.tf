# Tightened IAM role for RalphTurn — scoped to its own execution S3 prefix
# and Anthropic API key only. Spec §4.3 layer 3.

resource "aws_iam_role" "ralph_turn_exec" {
  name = "${local.name_prefix}-ralph-turn-exec"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect = "Allow",
      Principal = { Service = "lambda.amazonaws.com" },
      Action = "sts:AssumeRole",
    }]
  })
  tags = merge(local.common_tags, { Generation = "v2" })
}

resource "aws_iam_role_policy_attachment" "ralph_turn_basic" {
  role       = aws_iam_role.ralph_turn_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "ralph_turn_xray" {
  role       = aws_iam_role.ralph_turn_exec.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

resource "aws_iam_role_policy" "ralph_turn_inline" {
  role = aws_iam_role.ralph_turn_exec.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "s3:GetObject", "s3:PutObject", "s3:DeleteObject",
          "s3:ListBucket"
        ],
        Resource = [
          aws_s3_bucket.workspaces.arn,
          "${aws_s3_bucket.workspaces.arn}/*",
        ]
      },
      {
        # ONLY the Anthropic API key + GitHub token (needed for first-turn clone).
        Effect = "Allow",
        Action = ["secretsmanager:GetSecretValue"],
        Resource = [
          "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:nova/factory/anthropic-api-key*",
          "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:nova/factory/github-token*",
        ]
      }
    ]
  })
}
