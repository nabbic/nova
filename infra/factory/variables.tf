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

variable "staging_url" {
  type        = string
  default     = "https://httpbin.org"
  description = "Base URL the postdeploy probe hits. Defaults to httpbin.org until real staging is provisioned (the probe parser tolerates 'no_http_probes' for runs that don't add HTTP-shape acceptance criteria)."
}
