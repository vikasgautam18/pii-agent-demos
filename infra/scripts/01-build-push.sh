#!/usr/bin/env bash
# ── 01-build-push.sh ─────────────────────────────────────────────────────────
# Build the BankingBuddy Docker image in Azure Container Registry (cloud build).
# Reads ACR details from Terraform outputs.
#
# Prerequisites:
#   - Terraform applied (infra/terraform)
#   - Azure CLI logged in
#
# Usage:
#   cd infra/scripts && ./01-build-push.sh
#   cd infra/scripts && ./01-build-push.sh --tag v1.0
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Colour helpers ───────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()   { echo -e "${GREEN}[OK]${NC}    $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail() { echo -e "${RED}[FAIL]${NC}  $*"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TF_DIR="$SCRIPT_DIR/../terraform"
REPO_ROOT="$SCRIPT_DIR/../.."

IMAGE_TAG="${IMAGE_TAG:-latest}"
IMAGE_NAME="${IMAGE_NAME:-bankingbuddy}"

# ── Parse CLI args ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag)   IMAGE_TAG="$2"; shift 2 ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)  fail "Unknown arg: $1" ;;
  esac
done

# ── Read Terraform outputs ──────────────────────────────────────────────────
log "Reading Terraform outputs..."
ACR_LOGIN=$(cd "$TF_DIR" && terraform output -raw acr_login_server)
ACR_NAME=$(cd "$TF_DIR" && terraform output -raw acr_name)
RG_NAME=$(cd "$TF_DIR" && terraform output -raw resource_group_name)

echo ""
echo "  ACR Registry:  $ACR_LOGIN"
echo "  ACR Name:      $ACR_NAME"
echo "  Resource Group: $RG_NAME"
echo "  Image:         ${IMAGE_NAME}:${IMAGE_TAG}"
echo ""

# ── Build image in ACR ───────────────────────────────────────────────────────
log "Building image in ACR: ${ACR_LOGIN}/${IMAGE_NAME}:${IMAGE_TAG}"

az acr build \
  --registry "$ACR_NAME" \
  --resource-group "$RG_NAME" \
  --image "${IMAGE_NAME}:${IMAGE_TAG}" \
  "$REPO_ROOT"

echo ""
ok "Image pushed: ${ACR_LOGIN}/${IMAGE_NAME}:${IMAGE_TAG}"
