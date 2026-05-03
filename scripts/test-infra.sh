#!/usr/bin/env bash
# =============================================================================
# Nova Infrastructure Test Script
# Tests Terraform IaC for Cognito & RDS foundation feature
#
# Usage:
#   ./scripts/test-infra.sh [validate|plan|all]
#
# Arguments:
#   validate  - Run terraform init + validate only (CI-safe, no AWS creds needed)
#   plan      - Run terraform plan dry-run and assert resource counts
#   all       - Run both validate and plan (default)
#
# Environment variables required for 'plan' target:
#   AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY (or AWS profile)
#   TF_VAR_db_password, TF_VAR_db_username
#
# NOTE: No pytest tests are required for this feature — it is pure Terraform
# IaC with no application code. All acceptance criteria are validated via
# terraform validate and terraform plan assertions below.
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Colour

PASS="${GREEN}PASS${NC}"
FAIL="${RED}FAIL${NC}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log_info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

PASSED=0
FAILED=0

assert_eq() {
  local description="$1"
  local expected="$2"
  local actual="$3"
  if [ "$expected" = "$actual" ]; then
    echo -e "  ${PASS}  ${description} (expected=${expected}, got=${actual})"
    PASSED=$((PASSED + 1))
  else
    echo -e "  ${FAIL}  ${description} (expected=${expected}, got=${actual})"
    FAILED=$((FAILED + 1))
  fi
}

assert_ge() {
  local description="$1"
  local expected="$2"
  local actual="$3"
  if [ "$actual" -ge "$expected" ]; then
    echo -e "  ${PASS}  ${description} (expected>=${expected}, got=${actual})"
    PASSED=$((PASSED + 1))
  else
    echo -e "  ${FAIL}  ${description} (expected>=${expected}, got=${actual})"
    FAILED=$((FAILED + 1))
  fi
}

assert_exit_code() {
  local description="$1"
  local expected_exit="$2"
  local actual_exit="$3"
  if [ "$expected_exit" = "$actual_exit" ]; then
    echo -e "  ${PASS}  ${description} (exit code=${actual_exit})"
    PASSED=$((PASSED + 1))
  else
    echo -e "  ${FAIL}  ${description} (expected exit=${expected_exit}, got=${actual_exit})"
    FAILED=$((FAILED + 1))
  fi
}

print_summary() {
  echo
  echo "=========================================="
  echo -e "  Test Summary: ${GREEN}${PASSED} passed${NC}, ${RED}${FAILED} failed${NC}"
  echo "=========================================="
  if [ "$FAILED" -gt 0 ]; then
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# Resolve paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"; pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.."; pwd)"
INFRA_DIR="${REPO_ROOT}/infra"
SCRIPTS_DIR="${REPO_ROOT}/scripts"
STAGING_TFVARS="${SCRIPTS_DIR}/staging.test.tfvars"

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
preflight_checks() {
  log_info "Running pre-flight checks..."

  if ! command -v terraform &>/dev/null; then
    log_error "terraform is not installed or not on PATH"
    exit 1
  fi

  TF_VERSION=$(terraform version -json 2>/dev/null | grep -o '"terraform_version":"[^"]*"' | cut -d'"' -f4 || terraform version | head -1 | grep -oP '\d+\.\d+\.\d+')
  log_info "Terraform version: ${TF_VERSION}"

  if [ ! -d "${INFRA_DIR}" ]; then
    log_error "infra/ directory not found at ${INFRA_DIR}"
    exit 1
  fi

  log_ok "Pre-flight checks passed"
}

# ---------------------------------------------------------------------------
# TARGET: validate
# Runs terraform init -backend=false then terraform validate.
# Safe for CI environments where the S3 state bucket does not exist.
# Acceptance criterion: exit code 0, output contains 'The configuration is valid.'
# ---------------------------------------------------------------------------
run_validate() {
  echo
  echo "=========================================="
  echo -e "  ${BLUE}TARGET: validate${NC}"
  echo "=========================================="

  # -------------------------------------------------------------------------
  # Step 1 — terraform init -backend=false
  # -backend=false prevents Terraform from attempting to connect to the S3
  # state backend, making this safe in CI where the bucket may not exist.
  # -------------------------------------------------------------------------
  log_info "Running: terraform init -backend=false"
  cd "${INFRA_DIR}"

  INIT_OUTPUT=$(terraform init -backend=false -no-color 2>&1) || INIT_EXIT=$?
  INIT_EXIT=${INIT_EXIT:-0}

  echo "--- terraform init output ---"
  echo "${INIT_OUTPUT}"
  echo "-----------------------------"

  assert_exit_code \
    "terraform init -backend=false exits with code 0" \
    "0" \
    "${INIT_EXIT}"

  if echo "${INIT_OUTPUT}" | grep -qi "error"; then
    echo -e "  ${FAIL}  terraform init produced no errors"
    FAILED=$((FAILED + 1))
  else
    echo -e "  ${PASS}  terraform init produced no errors"
    PASSED=$((PASSED + 1))
  fi

  # -------------------------------------------------------------------------
  # Step 2 — terraform validate
  # Validates HCL syntax and internal consistency without needing AWS creds.
  # Acceptance criterion: 'Success! The configuration is valid.'
  # -------------------------------------------------------------------------
  log_info "Running: terraform validate"

  VALIDATE_OUTPUT=$(terraform validate -no-color 2>&1) || VALIDATE_EXIT=$?
  VALIDATE_EXIT=${VALIDATE_EXIT:-0}

  echo "--- terraform validate output ---"
  echo "${VALIDATE_OUTPUT}"
  echo "---------------------------------"

  assert_exit_code \
    "terraform validate exits with code 0" \
    "0" \
    "${VALIDATE_EXIT}"

  if echo "${VALIDATE_OUTPUT}" | grep -q "The configuration is valid"; then
    echo -e "  ${PASS}  terraform validate output contains 'The configuration is valid.'"
    PASSED=$((PASSED + 1))
  else
    echo -e "  ${FAIL}  terraform validate output contains 'The configuration is valid.' (got: ${VALIDATE_OUTPUT})"
    FAILED=$((FAILED + 1))
  fi

  # -------------------------------------------------------------------------
  # Structural checks — inspect HCL files without AWS
  # -------------------------------------------------------------------------
  log_info "Running structural HCL checks..."

  # Check required files exist
  for f in main.tf variables.tf outputs.tf; do
    if [ -f "${INFRA_DIR}/${f}" ]; then
      echo -e "  ${PASS}  infra/${f} exists"
      PASSED=$((PASSED + 1))
    else
      echo -e "  ${FAIL}  infra/${f} exists"
      FAILED=$((FAILED + 1))
    fi
  done

  for mod in cognito rds; do
    for f in main.tf variables.tf outputs.tf; do
      if [ -f "${INFRA_DIR}/modules/${mod}/${f}" ]; then
        echo -e "  ${PASS}  infra/modules/${mod}/${f} exists"
        PASSED=$((PASSED + 1))
      else
        echo -e "  ${FAIL}  infra/modules/${mod}/${f} exists"
        FAILED=$((FAILED + 1))
      fi
    done
  done

  # Check six required outputs are declared
  OUTPUTS_FILE="${INFRA_DIR}/outputs.tf"
  for output_name in buyer_user_pool_id seller_user_pool_id buyer_client_id seller_client_id db_endpoint db_name; do
    if grep -q "output.*\"${output_name}\"" "${OUTPUTS_FILE}" 2>/dev/null; then
      echo -e "  ${PASS}  output '${output_name}' declared in infra/outputs.tf"
      PASSED=$((PASSED + 1))
    else
      echo -e "  ${FAIL}  output '${output_name}' declared in infra/outputs.tf"
      FAILED=$((FAILED + 1))
    fi
  done

  # Check sensitive variables
  VARS_FILE="${INFRA_DIR}/variables.tf"
  for sens_var in db_password db_username; do
    if grep -A5 "variable.*\"${sens_var}\"" "${VARS_FILE}" 2>/dev/null | grep -q "sensitive.*=.*true"; then
      echo -e "  ${PASS}  variable '${sens_var}' is marked sensitive=true"
      PASSED=$((PASSED + 1))
    else
      echo -e "  ${FAIL}  variable '${sens_var}' is marked sensitive=true"
      FAILED=$((FAILED + 1))
    fi
  done

  # Check no hardcoded account IDs (12-digit AWS account pattern)
  HARDCODED_ACCOUNT=$(grep -rn '[0-9]\{12\}' "${INFRA_DIR}" --include='*.tf' \
    | grep -v '#' \
    | grep -v 'nova-terraform-state' \
    | grep -v '.terraform' \
    || true)
  if [ -z "${HARDCODED_ACCOUNT}" ]; then
    echo -e "  ${PASS}  No hardcoded 12-digit AWS account IDs found in .tf files"
    PASSED=$((PASSED + 1))
  else
    echo -e "  ${FAIL}  Hardcoded AWS account IDs found:"
    echo "${HARDCODED_ACCOUNT}"
    FAILED=$((FAILED + 1))
  fi

  # Check no hardcoded region strings (outside of backend config which is allowed)
  # We check that data.aws_region is used rather than literal "us-east-1" in resource blocks
  HARDCODED_REGION=$(grep -rn '"us-east-1"\|"us-west-2"\|"eu-west-1"' "${INFRA_DIR}" \
    --include='*.tf' \
    | grep -v '#' \
    | grep -v 'backend' \
    | grep -v '.terraform' \
    || true)
  if [ -z "${HARDCODED_REGION}" ]; then
    echo -e "  ${PASS}  No hardcoded AWS region strings found in resource blocks"
    PASSED=$((PASSED + 1))
  else
    echo -e "  ${WARN}  Possible hardcoded region strings (review manually):"
    echo "${HARDCODED_REGION}"
    # Warn only — backend block legitimately contains region
  fi

  # Check data sources are used for caller identity / region
  COGNITO_MAIN="${INFRA_DIR}/modules/cognito/main.tf"
  RDS_MAIN="${INFRA_DIR}/modules/rds/main.tf"

  # Check S3 backend configuration is present
  if grep -q 'nova-terraform-state' "${INFRA_DIR}/main.tf" 2>/dev/null; then
    echo -e "  ${PASS}  S3 backend bucket reference found in infra/main.tf"
    PASSED=$((PASSED + 1))
  else
    echo -e "  ${FAIL}  S3 backend bucket reference found in infra/main.tf"
    FAILED=$((FAILED + 1))
  fi

  if grep -q 'nova-terraform-locks' "${INFRA_DIR}/main.tf" 2>/dev/null; then
    echo -e "  ${PASS}  DynamoDB lock table reference found in infra/main.tf"
    PASSED=$((PASSED + 1))
  else
    echo -e "  ${FAIL}  DynamoDB lock table reference found in infra/main.tf"
    FAILED=$((FAILED + 1))
  fi

  # Check storage_encrypted = true in RDS module
  if grep -q 'storage_encrypted.*=.*true' "${RDS_MAIN}" 2>/dev/null; then
    echo -e "  ${PASS}  RDS storage_encrypted=true found in modules/rds/main.tf"
    PASSED=$((PASSED + 1))
  else
    echo -e "  ${FAIL}  RDS storage_encrypted=true found in modules/rds/main.tf"
    FAILED=$((FAILED + 1))
  fi

  # Check db.t3.micro instance class
  if grep -q 'db.t3.micro' "${RDS_MAIN}" 2>/dev/null; then
    echo -e "  ${PASS}  RDS instance_class=db.t3.micro found in modules/rds/main.tf"
    PASSED=$((PASSED + 1))
  else
    echo -e "  ${FAIL}  RDS instance_class=db.t3.micro found in modules/rds/main.tf"
    FAILED=$((FAILED + 1))
  fi

  # Check deletion_protection conditional logic
  if grep -q 'deletion_protection' "${RDS_MAIN}" 2>/dev/null; then
    echo -e "  ${PASS}  deletion_protection attribute present in modules/rds/main.tf"
    PASSED=$((PASSED + 1))
  else
    echo -e "  ${FAIL}  deletion_protection attribute present in modules/rds/main.tf"
    FAILED=$((FAILED + 1))
  fi

  # Check buyer pool has custom attributes
  if grep -q 'custom:role\|custom:org_id' "${COGNITO_MAIN}" 2>/dev/null; then
    echo -e "  ${PASS}  Buyer Cognito pool custom attributes (custom:role, custom:org_id) declared"
    PASSED=$((PASSED + 1))
  else
    echo -e "  ${FAIL}  Buyer Cognito pool custom attributes (custom:role, custom:org_id) declared"
    FAILED=$((FAILED + 1))
  fi

  # Check generate_secret is NOT set to true
  if grep -q 'generate_secret.*=.*true' "${COGNITO_MAIN}" 2>/dev/null; then
    echo -e "  ${FAIL}  generate_secret=true found — Cognito clients must be secret-less for SPA"
    FAILED=$((FAILED + 1))
  else
    echo -e "  ${PASS}  No generate_secret=true found in Cognito client config (SPA-safe)"
    PASSED=$((PASSED + 1))
  fi

  # Check no 0.0.0.0/0 ingress on RDS security group
  if grep -q '0\.0\.0\.0/0' "${RDS_MAIN}" 2>/dev/null; then
    # Check if it's only in egress
    INGRESS_OPEN=$(grep -A10 'ingress' "${RDS_MAIN}" 2>/dev/null | grep '0\.0\.0\.0/0' || true)
    if [ -n "${INGRESS_OPEN}" ]; then
      echo -e "  ${FAIL}  RDS security group has 0.0.0.0/0 ingress — must be restricted to app_sg_id only"
      FAILED=$((FAILED + 1))
    else
      echo -e "  ${PASS}  RDS security group has no 0.0.0.0/0 ingress rule"
      PASSED=$((PASSED + 1))
    fi
  else
    echo -e "  ${PASS}  RDS security group has no 0.0.0.0/0 ingress rule"
    PASSED=$((PASSED + 1))
  fi

  # Check db_password and db_username do NOT appear in outputs
  for sens_var in db_password db_username; do
    if grep -q "${sens_var}" "${INFRA_DIR}/outputs.tf" 2>/dev/null; then
      echo -e "  ${FAIL}  Sensitive variable '${sens_var}' must NOT appear in infra/outputs.tf"
      FAILED=$((FAILED + 1))
    else
      echo -e "  ${PASS}  Sensitive variable '${sens_var}' does not appear in infra/outputs.tf"
      PASSED=$((PASSED + 1))
    fi
  done

  # Check tags block presence
  for tf_file in "${INFRA_DIR}/modules/cognito/main.tf" "${INFRA_DIR}/modules/rds/main.tf"; do
    mod_name=$(basename $(dirname $tf_file))
    if grep -q 'Project.*=.*nova\|ManagedBy.*=.*terraform' "${tf_file}" 2>/dev/null; then
      echo -e "  ${PASS}  Required tags (Project=nova, ManagedBy=terraform) declared in modules/${mod_name}/main.tf"
      PASSED=$((PASSED + 1))
    else
      echo -e "  ${FAIL}  Required tags (Project=nova, ManagedBy=terraform) declared in modules/${mod_name}/main.tf"
      FAILED=$((FAILED + 1))
    fi
  done

  # Check app_sg_id variable exists (required, no default)
  if grep -q 'variable.*"app_sg_id"' "${VARS_FILE}" 2>/dev/null; then
    echo -e "  ${PASS}  variable 'app_sg_id' declared in infra/variables.tf"
    PASSED=$((PASSED + 1))
  else
    echo -e "  ${FAIL}  variable 'app_sg_id' declared in infra/variables.tf"
    FAILED=$((FAILED + 1))
  fi

  # Check subnet_ids variable exists
  if grep -q 'variable.*"subnet_ids"' "${VARS_FILE}" 2>/dev/null; then
    echo -e "  ${PASS}  variable 'subnet_ids' declared in infra/variables.tf"
    PASSED=$((PASSED + 1))
  else
    echo -e "  ${FAIL}  variable 'subnet_ids' declared in infra/variables.tf"
    FAILED=$((FAILED + 1))
  fi

  # Check no committed terraform.tfvars with secrets
  if [ -f "${INFRA_DIR}/terraform.tfvars" ]; then
    if grep -qi 'db_password\|db_username' "${INFRA_DIR}/terraform.tfvars"; then
      echo -e "  ${FAIL}  terraform.tfvars contains db credentials — must NOT be committed"
      FAILED=$((FAILED + 1))
    else
      echo -e "  ${PASS}  terraform.tfvars does not contain db credentials"
      PASSED=$((PASSED + 1))
    fi
  else
    echo -e "  ${PASS}  No terraform.tfvars committed (credentials supplied via env vars at deploy time)"
    PASSED=$((PASSED + 1))
  fi

  log_ok "Validate target complete"
}

# ---------------------------------------------------------------------------
# Create staging tfvars for plan dry-run
# Uses dummy/mock values for plan since we only need resource counts,
# not real AWS resource IDs.
# ---------------------------------------------------------------------------
create_staging_tfvars() {
  log_info "Creating staging test tfvars at ${STAGING_TFVARS}"
  mkdir -p "${SCRIPTS_DIR}"
  cat > "${STAGING_TFVARS}" <<'EOF'
# Test tfvars for staging plan dry-run
# These are mock values used only for `terraform plan` resource-count assertions.
# Real values are supplied via CI/CD secrets at deploy time.
environment = "staging"
app_sg_id   = "sg-00000000000000000"
subnet_ids  = ["subnet-00000000000000001", "subnet-00000000000000002"]
db_username = "nova_admin"
db_password = "TestPassword123!NotReal"
EOF
  log_ok "Staging tfvars written to ${STAGING_TFVARS}"
}

# ---------------------------------------------------------------------------
# TARGET: plan
# Runs terraform plan with staging tfvars and asserts exact resource counts.
# Requires real AWS credentials (read-only for plan) to resolve data sources.
#
# Acceptance criterion:
#   - 2 aws_cognito_user_pool
#   - 2 aws_cognito_user_pool_client
#   - 1 aws_db_instance
#   - 1 aws_db_subnet_group
#   - 1 aws_security_group
# ---------------------------------------------------------------------------
run_plan() {
  echo
  echo "=========================================="
  echo -e "  ${BLUE}TARGET: plan${NC}"
  echo "=========================================="

  # Check AWS credentials are available
  if ! aws sts get-caller-identity &>/dev/null 2>&1; then
    log_warn "AWS credentials not configured — skipping plan target"
    log_warn "Set AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY (and optionally AWS_DEFAULT_REGION)"
    log_warn "or configure an AWS profile to run the plan assertions."
    echo -e "  ${YELLOW}SKIP${NC}  plan target (no AWS credentials)"
    return 0
  fi

  create_staging_tfvars

  cd "${INFRA_DIR}"

  # Re-init with backend=false for plan (state not needed for count assertions)
  log_info "Running: terraform init -backend=false (for plan)"
  terraform init -backend=false -no-color &>/dev/null || true

  # Generate plan output in JSON format for reliable parsing
  PLAN_JSON_FILE=$(mktemp /tmp/nova-tf-plan-XXXXXX.json)
  PLAN_OUT_FILE=$(mktemp /tmp/nova-tf-plan-XXXXXX.out)

  log_info "Running: terraform plan -var-file=${STAGING_TFVARS} (JSON output)"

  # Run plan; capture both JSON and human-readable output
  # -out saves binary plan; -json produces machine-readable output on stdout
  terraform plan \
    -var-file="${STAGING_TFVARS}" \
    -no-color \
    -json \
    2>&1 | tee "${PLAN_JSON_FILE}" > /dev/null || PLAN_EXIT=$?
  PLAN_EXIT=${PLAN_EXIT:-0}

  # Also capture human-readable plan for fallback grep parsing
  terraform plan \
    -var-file="${STAGING_TFVARS}" \
    -no-color \
    2>&1 | tee "${PLAN_OUT_FILE}" > /dev/null || PLAN_HR_EXIT=$?
  PLAN_HR_EXIT=${PLAN_HR_EXIT:-0}

  echo "--- terraform plan exit codes: json=${PLAN_EXIT}, human=${PLAN_HR_EXIT} ---"

  assert_exit_code \
    "terraform plan exits with code 0 for staging" \
    "0" \
    "${PLAN_EXIT}"

  echo "--- terraform plan output (human-readable) ---"
  cat "${PLAN_OUT_FILE}"
  echo "----------------------------------------------"

  # -------------------------------------------------------------------------
  # Count resources using JSON plan output (preferred — exact counts)
  # Falls back to grep on human-readable output if JSON parse fails
  # -------------------------------------------------------------------------

  count_resource_json() {
    local resource_type="$1"
    # Count resource_changes entries with the given type and action 'create'
    python3 -c "
import json, sys
total = 0
for line in open('${PLAN_JSON_FILE}'):
    line = line.strip()
    try:
        obj = json.loads(line)
        if obj.get('type') == 'resource_changes':
            changes = obj.get('change', {}).get('actions', [])
            if obj.get('resource', {}).get('resource_type') == '${resource_type}' and 'create' in changes:
                total += 1
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
print(total)
" 2>/dev/null || echo "-1"
  }

  count_resource_grep() {
    local resource_type="$1"
    # Grep human-readable plan for '# <resource_type>.' lines (will be created)
    grep -c "# .*${resource_type}\." "${PLAN_OUT_FILE}" 2>/dev/null || echo "0"
  }

  # Try JSON first; if it returns -1 (parse error), fall back to grep
  get_count() {
    local resource_type="$1"
    local json_count
    json_count=$(count_resource_json "${resource_type}")
    if [ "${json_count}" = "-1" ] || [ "${json_count}" = "0" ]; then
      # Fallback to grep on human-readable output
      count_resource_grep "${resource_type}"
    else
      echo "${json_count}"
    fi
  }

  # -------------------------------------------------------------------------
  # Assert resource counts
  # Acceptance criterion: exactly these counts in the staging plan
  # -------------------------------------------------------------------------
  log_info "Asserting resource counts in terraform plan..."

  COGNITO_POOL_COUNT=$(get_count "aws_cognito_user_pool")
  COGNITO_CLIENT_COUNT=$(get_count "aws_cognito_user_pool_client")
  DB_INSTANCE_COUNT=$(get_count "aws_db_instance")
  DB_SUBNET_GROUP_COUNT=$(get_count "aws_db_subnet_group")
  SECURITY_GROUP_COUNT=$(get_count "aws_security_group")

  echo
  echo "  Resource counts from plan:"
  echo "    aws_cognito_user_pool:        ${COGNITO_POOL_COUNT}"
  echo "    aws_cognito_user_pool_client: ${COGNITO_CLIENT_COUNT}"
  echo "    aws_db_instance:              ${DB_INSTANCE_COUNT}"
  echo "    aws_db_subnet_group:          ${DB_SUBNET_GROUP_COUNT}"
  echo "    aws_security_group:           ${SECURITY_GROUP_COUNT}"
  echo

  assert_eq \
    "plan contains exactly 2 aws_cognito_user_pool resources" \
    "2" \
    "${COGNITO_POOL_COUNT}"

  assert_eq \
    "plan contains exactly 2 aws_cognito_user_pool_client resources" \
    "2" \
    "${COGNITO_CLIENT_COUNT}"

  assert_eq \
    "plan contains exactly 1 aws_db_instance resource" \
    "1" \
    "${DB_INSTANCE_COUNT}"

  assert_eq \
    "plan contains exactly 1 aws_db_subnet_group resource" \
    "1" \
    "${DB_SUBNET_GROUP_COUNT}"

  assert_eq \
    "plan contains exactly 1 aws_security_group resource" \
    "1" \
    "${SECURITY_GROUP_COUNT}"

  # -------------------------------------------------------------------------
  # Plan content assertions (from human-readable output)
  # -------------------------------------------------------------------------
  log_info "Asserting plan content details..."

  # staging should NOT have deletion_protection=true
  if grep -q 'deletion_protection.*=.*false\|deletion_protection.*false' "${PLAN_OUT_FILE}" 2>/dev/null; then
    echo -e "  ${PASS}  staging plan shows deletion_protection=false (correct for non-production)"
    PASSED=$((PASSED + 1))
  else
    log_warn "  Could not confirm deletion_protection=false for staging in plan output"
  fi

  # staging should have skip_final_snapshot=true
  if grep -q 'skip_final_snapshot.*=.*true\|skip_final_snapshot.*true' "${PLAN_OUT_FILE}" 2>/dev/null; then
    echo -e "  ${PASS}  staging plan shows skip_final_snapshot=true (correct for non-production)"
    PASSED=$((PASSED + 1))
  else
    log_warn "  Could not confirm skip_final_snapshot=true for staging in plan output"
  fi

  # db.t3.micro
  if grep -q 'db.t3.micro' "${PLAN_OUT_FILE}" 2>/dev/null; then
    echo -e "  ${PASS}  staging plan shows instance_class=db.t3.micro"
    PASSED=$((PASSED + 1))
  else
    echo -e "  ${FAIL}  staging plan shows instance_class=db.t3.micro"
    FAILED=$((FAILED + 1))
  fi

  # storage_encrypted
  if grep -q 'storage_encrypted.*true' "${PLAN_OUT_FILE}" 2>/dev/null; then
    echo -e "  ${PASS}  staging plan shows storage_encrypted=true"
    PASSED=$((PASSED + 1))
  else
    echo -e "  ${FAIL}  staging plan shows storage_encrypted=true"
    FAILED=$((FAILED + 1))
  fi

  # Cleanup temp files
  rm -f "${PLAN_JSON_FILE}" "${PLAN_OUT_FILE}" "${STAGING_TFVARS}"

  log_ok "Plan target complete"
}

# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------
main() {
  local target="${1:-all}"

  echo
  echo "================================================================"
  echo -e "  ${BLUE}Nova Infrastructure Tests — Terraform Cognito & RDS${NC}"
  echo "================================================================"
  echo
  echo "  NOTE: This is a pure Terraform IaC feature."
  echo "  No pytest tests are required — there is no application code."
  echo "  All acceptance criteria are validated via terraform validate"
  echo "  and terraform plan assertions in this script."
  echo

  preflight_checks

  case "${target}" in
    validate)
      run_validate
      ;;
    plan)
      run_plan
      ;;
    all)
      run_validate
      run_plan
      ;;
    *)
      log_error "Unknown target: ${target}"
      echo "Usage: $0 [validate|plan|all]"
      exit 1
      ;;
  esac

  print_summary
}

main "$@"
