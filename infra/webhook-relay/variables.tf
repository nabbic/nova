variable "github_owner" {
  description = "GitHub organisation or user that owns the Nova repo"
  type        = string
}

variable "github_repo" {
  description = "GitHub repository name"
  type        = string
  default     = "nova"
}

variable "github_token" {
  description = "GitHub PAT with repo dispatch permissions"
  type        = string
  sensitive   = true
}

variable "notion_api_key" {
  description = "Notion integration API key — used to fetch page status before triggering factory"
  type        = string
  sensitive   = true
}

variable "aws_region" {
  description = "AWS region to deploy to"
  type        = string
  default     = "us-east-1"
}
