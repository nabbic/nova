terraform {
  required_version = ">= 1.7"
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
