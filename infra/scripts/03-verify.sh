#!/usr/bin/env bash
# ── 03-verify.sh ──────────────────────────────────────────────────────────────
# Verify BankingBuddy deployment on Azure Container Apps.
# Runs health checks against the deployed service.
#
# Prerequisites:
#   - Container app deployed (02-deploy-apps.sh)
#   - Azure CLI logged in
#
# Usage:
#   cd infra/scripts && ./03-verify.sh
#
# Override defaults via env vars:
#   RG_NAME=my-rg APP_NAME=my-app ./03-verify.sh
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Colour helpers ───────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()   { echo -e "${GREEN}[PASS]${NC}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail_msg() { echo -e "${RED}[FAIL]${NC}  $*"; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TF_DIR="$SCRIPT_DIR/../terraform"

APP_NAME="${APP_NAME:-bankingbuddy}"

PASS=0
FAIL=0

check() {
  local label="$1"
  local url="$2"
  local expected_status="${3:-200}"

  status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "$url" 2>/dev/null || echo "000")
  if [[ "$status" == "$expected_status" ]]; then
    ok "$label (HTTP $status)"
    ((PASS++))
  else
    fail_msg "$label (HTTP $status, expected $expected_status)"
    ((FAIL++))
  fi
}

# ── Get FQDN ─────────────────────────────────────────────────────────────────
RG_NAME="${RG_NAME:-$(cd "$TF_DIR" 2>/dev/null && terraform output -raw resource_group_name 2>/dev/null || echo "")}"

if [[ -z "$RG_NAME" ]]; then
  echo -e "${RED}ERROR:${NC} Could not determine resource group. Set RG_NAME env var or run 'terraform apply' first."
  exit 1
fi

log "Fetching service URL..."
APP_FQDN=$(az containerapp show \
  --name "$APP_NAME" \
  --resource-group "$RG_NAME" \
  --query properties.configuration.ingress.fqdn -o tsv 2>/dev/null)

if [[ -z "$APP_FQDN" ]]; then
  echo -e "${RED}ERROR:${NC} Could not find container app '$APP_NAME' in resource group '$RG_NAME'."
  exit 1
fi

APP_URL="https://$APP_FQDN"

echo ""
echo "  BankingBuddy:  $APP_URL"
echo ""

# ── Health checks ────────────────────────────────────────────────────────────
log "Running health checks..."
check "BankingBuddy root"    "$APP_URL"
check "BankingBuddy /healthz" "$APP_URL/_stcore/health"

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "==============================================================="
echo "  Results: $PASS passed, $FAIL failed"
echo "==============================================================="

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
