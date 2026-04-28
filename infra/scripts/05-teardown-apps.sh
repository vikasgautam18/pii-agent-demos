#!/usr/bin/env bash
# ── 05-teardown-apps.sh ──────────────────────────────────────────────────────
# Delete out-of-band Azure resources that were created by 02-deploy-apps.sh
# but are NOT tracked in Terraform state. Run this BEFORE `terraform destroy`,
# otherwise destroy will fail with errors like:
#
#   ManagedEnvironmentHasContainerApps: The specified environment
#   <project>-env cannot be deleted because it still contains N ContainerApps
#
# What this script removes:
#   - All Container Apps inside the ACA Managed Environment
#
# Usage:
#   cd infra/scripts && ./05-teardown-apps.sh
#   # then:
#   cd ../terraform && terraform destroy
#
# Env overrides:
#   RG_NAME, ACA_ENV  (otherwise read from Terraform outputs)
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

tf_out() {
  (cd "$TF_DIR" && terraform output -raw "$1" 2>/dev/null) || true
}

RG_NAME="${RG_NAME:-$(tf_out resource_group_name)}"
ACA_ENV="${ACA_ENV:-$(tf_out aca_env_name)}"

if [[ -z "$RG_NAME" ]]; then
  fail "Could not determine RG_NAME. Either run from a directory with terraform state available, or set RG_NAME env var."
fi

echo "  Target resource group:  $RG_NAME"
[[ -n "$ACA_ENV" ]] && echo "  ACA environment:        $ACA_ENV"
echo ""

# ── 1. Container Apps ────────────────────────────────────────────────────────
log "Listing container apps in resource group '$RG_NAME'..."
CAPPS=$(az containerapp list -g "$RG_NAME" --query "[].name" -o tsv 2>/dev/null || true)

if [[ -z "$CAPPS" ]]; then
  warn "No container apps found"
else
  while IFS= read -r name; do
    [[ -z "$name" ]] && continue
    log "Deleting container app: $name"
    az containerapp delete -g "$RG_NAME" -n "$name" --yes --only-show-errors >/dev/null \
      && ok "Deleted $name" \
      || fail "Failed to delete $name"
  done <<< "$CAPPS"
fi

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo -e "  ${GREEN}[PASS]${NC} Teardown complete"
echo ""
echo "  You can now run:"
echo "    cd $TF_DIR && terraform destroy"
echo "═══════════════════════════════════════════════════════════════"
