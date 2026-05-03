variable "environment" {
  type        = string
  description = "Deployment environment (staging or production)"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID in which the RDS security group will be created"
}

variable "subnet_ids" {
  type        = list(string)
  description = "List of subnet IDs for the RDS DB subnet group. Must contain at least two subnets in different AZs."
}

variable "app_sg_id" {
  type        = string
  description = "Security group ID of the application layer (ECS tasks) that is permitted inbound access to RDS on port 5432"
}

variable "db_username" {
  type        = string
  sensitive   = true
  description = "RDS master username. Supply via TF_VAR_db_username — never commit this value."
}

variable "db_password" {
  type        = string
  sensitive   = true
  description = "RDS master password. Supply via TF_VAR_db_password — never commit this value."
}

variable "tags" {
  type        = map(string)
  description = "Tags to apply to all RDS resources"
  default     = {}
}
