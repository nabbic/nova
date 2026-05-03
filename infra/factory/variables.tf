variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "github_owner" {
  type    = string
  default = "nabbic"
}

variable "github_repo" {
  type    = string
  default = "nova"
}

variable "workspace_retention_days" {
  type        = number
  default     = 14
  description = "How long to keep factory workspace S3 objects before lifecycle deletes them"
}
