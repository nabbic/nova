terraform {
  required_version = ">= 1.7"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/lambda"
  output_path = "${path.module}/.build/webhook-relay.zip"
}

resource "aws_iam_role" "lambda_exec" {
  name = "nova-webhook-relay-exec"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  tags = {
    Project   = "nova"
    ManagedBy = "terraform"
  }
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "webhook_relay" {
  function_name    = "nova-webhook-relay"
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  runtime          = "nodejs20.x"
  handler          = "index.handler"
  role             = aws_iam_role.lambda_exec.arn
  timeout          = 10

  environment {
    variables = {
      GITHUB_OWNER          = var.github_owner
      GITHUB_REPO           = var.github_repo
      GITHUB_TOKEN          = var.github_token
      NOTION_WEBHOOK_SECRET = var.notion_webhook_secret
    }
  }

  tags = {
    Project   = "nova"
    ManagedBy = "terraform"
  }
}

resource "aws_lambda_function_url" "webhook_relay" {
  function_name      = aws_lambda_function.webhook_relay.function_name
  authorization_type = "NONE"

  cors {
    allow_origins = ["https://api.notion.com"]
    allow_methods = ["POST"]
  }
}
