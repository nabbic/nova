terraform {
  required_version = ">= 1.7"
  backend "s3" {
    bucket         = "nova-terraform-state-577638385116"
    key            = "factory/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "nova-terraform-locks"
    encrypt        = true
  }
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 5.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.0" }
    null    = { source = "hashicorp/null", version = "~> 3.0" }
  }
}

provider "aws" {
  region = var.aws_region
}

locals {
  name_prefix = "nova-factory"
  common_tags = {
    Project   = "nova"
    Component = "factory"
    ManagedBy = "terraform"
  }
}

data "aws_caller_identity" "current" {}
