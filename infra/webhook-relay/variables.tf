variable "github_owner" {
  description = "GitHub organisation or user that owns the Nova repo"
  type        = string
}

variable "github_repo" {
  description = "GitHub repository name"
  type        = string
  default     = "nova"
}

variable "aws_region" {
  description = "AWS region to deploy to"
  type        = string
  default     = "us-east-1"
}
