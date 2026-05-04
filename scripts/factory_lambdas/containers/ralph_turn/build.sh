#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../../../.." && pwd)

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION="${AWS_REGION:-us-east-1}"
REPO="nova-factory-ralph-turn"
ECR_REPO="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${REPO}"

# Ensure ECR repo exists (Terraform creates this; this is a defensive fallback)
aws ecr describe-repositories --repository-names "$REPO" --region "$REGION" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "$REPO" --region "$REGION"

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ECR_REPO"

# Build with repo root as context so we can COPY .factory/
docker build \
  --platform linux/amd64 \
  -f "$HERE/Dockerfile" \
  -t "$ECR_REPO:latest" \
  "$REPO_ROOT"

docker push "$ECR_REPO:latest"
echo "Pushed $ECR_REPO:latest"
