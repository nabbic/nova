terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket         = "nova-terraform-state-577638385116"
    key            = "nova/${var.environment}/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "nova-terraform-locks"
    encrypt        = true
  }
}

provider "aws" {
  # Region is not hardcoded — set via AWS_DEFAULT_REGION env var or provider configuration
  # data.aws_region.current is used wherever region is needed in resources
}

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

module "cognito" {
  source      = "./modules/cognito"
  environment = var.environment

  tags = {
    Project     = "nova"
    ManagedBy   = "terraform"
    Environment = var.environment
  }
}

module "rds" {
  source      = "./modules/rds"
  environment = var.environment
  app_sg_id   = var.app_sg_id
  subnet_ids  = var.subnet_ids
  db_username = var.db_username
  db_password = var.db_password
  vpc_id      = var.vpc_id

  tags = {
    Project     = "nova"
    ManagedBy   = "terraform"
    Environment = var.environment
  }
}
