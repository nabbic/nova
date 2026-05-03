#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAMBDAS_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGISTRY="$ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com"
REPO="nova-factory-validators"
IMAGE="$REGISTRY/$REPO:latest"

# Stage shared common module into context dir (validate_workspace.py is already co-located)
cp -r "$LAMBDAS_DIR/common" "$SCRIPT_DIR/common"

cleanup() {
  rm -rf "$SCRIPT_DIR/common"
}
trap cleanup EXIT

# ECR login
aws ecr get-login-password --region "$REGION" | \
  docker login --username AWS --password-stdin "$REGISTRY"

# Build and push (DOCKER_BUILDKIT=0 ensures Docker V2 manifest, not OCI manifest list,
# which Lambda container image support requires)
DOCKER_BUILDKIT=0 docker build --platform linux/amd64 -t validate-workspace "$SCRIPT_DIR"
docker tag validate-workspace "$IMAGE"
docker push "$IMAGE"
echo "Pushed $IMAGE"
