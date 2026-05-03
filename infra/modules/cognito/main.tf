# ---------------------------------------------------------------------------
# Nova Cognito User Pools
# Two pools:
#   1. nova-buyer-{env}  — PE firm deal team users
#   2. nova-seller-{env} — Target company seller users (per-engagement)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Buyer User Pool
# ---------------------------------------------------------------------------
resource "aws_cognito_user_pool" "buyer" {
  name = "nova-buyer-${var.environment}"

  # Email is the username
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  # Buyer password policy — full complexity required
  password_policy {
    minimum_length                   = 12
    require_uppercase                = true
    require_lowercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 7
  }

  # Custom attributes for buyer users
  # custom:role   — e.g. "deal_lead", "advisor", "analyst"
  # custom:org_id — buyer organisation ID (tenant key)
  schema {
    name                     = "role"
    attribute_data_type      = "String"
    mutable                  = true
    required                 = false
    developer_only_attribute = false

    string_attribute_constraints {
      min_length = 1
      max_length = 64
    }
  }

  schema {
    name                     = "org_id"
    attribute_data_type      = "String"
    mutable                  = true
    required                 = false
    developer_only_attribute = false

    string_attribute_constraints {
      min_length = 1
      max_length = 128
    }
  }

  # Account recovery via email
  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  tags = var.tags
}

# ---------------------------------------------------------------------------
# Buyer User Pool Client (SPA — secret-less, public client)
# generate_secret is NOT set (defaults to false) — required for browser-based
# SPAs that cannot safely store a client secret.
# ---------------------------------------------------------------------------
resource "aws_cognito_user_pool_client" "buyer" {
  name         = "nova-buyer-client-${var.environment}"
  user_pool_id = aws_cognito_user_pool.buyer.id

  # Public client — no client secret (SPA compatibility)
  # generate_secret = false is the default; explicitly omitted

  explicit_auth_flows = [
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  # Token validity
  access_token_validity  = 1   # hours
  id_token_validity      = 1   # hours
  refresh_token_validity = 30  # days

  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }

  # Prevent user existence errors from leaking in auth responses
  prevent_user_existence_errors = "ENABLED"

  # Read and write access to custom attributes
  read_attributes = [
    "email",
    "email_verified",
    "custom:role",
    "custom:org_id",
  ]

  write_attributes = [
    "email",
    "custom:role",
    "custom:org_id",
  ]
}

# ---------------------------------------------------------------------------
# Seller User Pool
# ---------------------------------------------------------------------------
resource "aws_cognito_user_pool" "seller" {
  name = "nova-seller-${var.environment}"

  # Email is the username
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  # Seller password policy — no symbols required (seller UX)
  password_policy {
    minimum_length                   = 12
    require_uppercase                = true
    require_lowercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 7
  }

  # No custom schema attributes for the seller pool

  # Account recovery via email
  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  tags = var.tags
}

# ---------------------------------------------------------------------------
# Seller User Pool Client (SPA — secret-less, public client)
# Longer token TTLs reflect sellers' longer work sessions during diligence.
# generate_secret is NOT set (defaults to false) — public SPA client.
# ---------------------------------------------------------------------------
resource "aws_cognito_user_pool_client" "seller" {
  name         = "nova-seller-client-${var.environment}"
  user_pool_id = aws_cognito_user_pool.seller.id

  # Public client — no client secret (SPA compatibility)
  # generate_secret = false is the default; explicitly omitted

  explicit_auth_flows = [
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  # Token validity — seller sessions are longer (full working day)
  access_token_validity  = 8  # hours
  id_token_validity      = 8  # hours
  refresh_token_validity = 7  # days

  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }

  # Prevent user existence errors from leaking in auth responses
  prevent_user_existence_errors = "ENABLED"

  read_attributes = [
    "email",
    "email_verified",
  ]

  write_attributes = [
    "email",
  ]
}
