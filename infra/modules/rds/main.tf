# ---------------------------------------------------------------------------
# Nova RDS PostgreSQL Instance
#
# NON-FREE-TIER note: db.t3.micro is free-tier eligible for the first 12 months
# of a new AWS account (750 hours/month of db.t3.micro Single-AZ). Beyond that
# period, or on existing accounts, this costs approximately $13-15/month.
# storage_encrypted=true with the AWS managed key (kms_key_id unset) incurs
# no additional KMS cost — AWS manages the key at no charge.
# ---------------------------------------------------------------------------

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

locals {
  is_production        = var.environment == "production"
  db_name              = "nova"
  db_identifier        = "nova-${var.environment}"
  subnet_group_name    = "nova-rds-${var.environment}"
  security_group_name  = "nova-rds-${var.environment}"
}

# ---------------------------------------------------------------------------
# DB Subnet Group
# Subnets are provided externally (VPC feature is out of scope here)
# ---------------------------------------------------------------------------
resource "aws_db_subnet_group" "main" {
  name        = local.subnet_group_name
  description = "RDS subnet group for Nova ${var.environment}"
  subnet_ids  = var.subnet_ids

  tags = merge(var.tags, {
    Name = local.subnet_group_name
  })
}

# ---------------------------------------------------------------------------
# RDS Security Group
# Ingress: port 5432 from the application security group ONLY
# Egress: unrestricted (standard for RDS — responses to clients)
# ---------------------------------------------------------------------------
resource "aws_security_group" "rds" {
  name        = local.security_group_name
  description = "Controls access to Nova RDS PostgreSQL (${var.environment})"
  vpc_id      = var.vpc_id

  # Ingress: PostgreSQL port from application layer only — no 0.0.0.0/0
  ingress {
    description     = "PostgreSQL from application security group"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [var.app_sg_id]
  }

  # Egress: unrestricted (RDS needs to respond to client connections)
  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, {
    Name = local.security_group_name
  })

  lifecycle {
    # Prevent accidental deletion of the SG while RDS instance references it
    create_before_destroy = true
  }
}

# ---------------------------------------------------------------------------
# RDS PostgreSQL Instance
#
# Free-tier eligible: db.t3.micro, 20GB gp2, Single-AZ
# (see NON-FREE-TIER note at top of file for conditions)
#
# storage_encrypted=true uses the AWS managed RDS key (no kms_key_id set).
# This means no additional KMS cost and no hardcoded key ARN.
#
# skip_final_snapshot: true for non-production (fast teardown in staging)
# deletion_protection: true for production only (prevent accidental destruction)
# ---------------------------------------------------------------------------
resource "aws_db_instance" "main" {
  identifier = local.db_identifier

  # Engine
  engine         = "postgres"
  engine_version = "16"

  # Instance sizing — db.t3.micro is free-tier eligible (see header comment)
  instance_class    = "db.t3.micro"
  allocated_storage = 20
  storage_type      = "gp2"

  # Encryption at rest using AWS managed key — no kms_key_id = no extra cost,
  # no hardcoded ARN. AWS automatically uses the aws/rds managed key.
  storage_encrypted = true
  # kms_key_id intentionally omitted — uses AWS managed key

  # Database credentials — sourced from sensitive variables, never hardcoded
  db_name  = local.db_name
  username = var.db_username
  password = var.db_password

  # Networking
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false

  # Backup
  backup_retention_period = local.is_production ? 7 : 1
  backup_window           = "03:00-04:00"
  maintenance_window      = "Mon:04:00-Mon:05:00"

  # Lifecycle — environment-specific conditional expressions
  # skip_final_snapshot=true in staging (fast teardown); false in production
  skip_final_snapshot       = var.environment != "production"
  final_snapshot_identifier = local.is_production ? "nova-production-final-snapshot" : null

  # deletion_protection=true in production only — prevents accidental destroy
  deletion_protection = local.is_production

  # Performance Insights — free tier: 7 days retention
  performance_insights_enabled          = true
  performance_insights_retention_period = 7

  # Disable minor version auto-upgrade in production for stability
  auto_minor_version_upgrade = !local.is_production

  # Multi-AZ: disabled for staging (cost), enabled for production
  # NON-FREE-TIER: multi_az=true in production costs ~2x the single-AZ price
  multi_az = local.is_production

  tags = merge(var.tags, {
    Name = local.db_identifier
  })
}
