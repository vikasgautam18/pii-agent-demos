#!/usr/bin/env bash
# 00-teardown-state.sh — Remove the Terraform state backend resources
#
# Removes everything provisioned by 00-bootstrap-state.sh:
#   - CanNotDelete lock on the state resource group
#   - Storage account (and its blob container + RBAC role assignments)
#   - Resource group itself
#
# WARNING: This permanently deletes your Terraform state. Make sure no active
# deployments rely on it (run 'terraform destroy' first if there are live resources).
#
# Usage:
#   ./00-teardown-state.sh
#   ./00-teardown-state.sh --yes   # skip confirmation

set -euo pipefail

# ── Colour helpers ───────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()   { echo -e "${GREEN}[OK]${NC}    $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail() { echo -e "${RED}[FAIL]${NC}  $*"; exit 1; }

# ── Defaults ─────────────────────────────────────────────────────────────────
PROJECT_NAME="${PROJECT_NAME:-bankingbuddy}"
STATE_RG="${PROJECT_NAME}-tfstate-rg"
LOCK_NAME="${LOCK_NAME:-protect-tfstate}"
ASSUME_YES="false"

# ── Parse arguments ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case $1 in
    --project)          PROJECT_NAME="$2"; STATE_RG="${2}-tfstate-rg"; shift 2 ;;
    --resource-group)   STATE_RG="$2";        shift 2 ;;
    --lock-name)        LOCK_NAME="$2";       shift 2 ;;
    -y|--yes)           ASSUME_YES="true";    shift ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)  fail "Unknown argument: $1" ;;
  esac
done

# Verify the resource group exists
if ! az group show --name "$STATE_RG" --output none 2>/dev/null; then
  fail "Resource group '$STATE_RG' not found (already deleted?)"
fi

# Auto-detect storage account
STORAGE_ACCOUNT=$(az storage account list \
  --resource-group "$STATE_RG" \
  --query "[0].name" -o tsv 2>/dev/null || true)

echo "==============================================================="
echo "  Terraform State Backend - TEARDOWN (BankingBuddy)"
echo "==============================================================="
echo ""
echo "  Resource Group:    $STATE_RG"
echo "  Storage Account:   ${STORAGE_ACCOUNT:-<none found>}"
echo "  Lock to remove:    $LOCK_NAME"
echo ""
echo -e "  ${RED}WARNING: This permanently deletes the Terraform state files.${NC}"
echo "  Make sure you have run 'terraform destroy' on any live infrastructure"
echo "  that depends on this state before proceeding."
echo ""

if [[ "$ASSUME_YES" != "true" ]]; then
  read -r -p "Type the resource group name '$STATE_RG' to confirm deletion: " CONFIRM
  if [[ "$CONFIRM" != "$STATE_RG" ]]; then
    echo "Aborted (input did not match)."
    exit 1
  fi
fi

# ── 1. Remove the resource group lock ────────────────────────────────────────
log "Removing lock '$LOCK_NAME' on resource group..."
LOCK_ID=$(az lock show \
  --name "$LOCK_NAME" \
  --resource-group "$STATE_RG" \
  --query id -o tsv 2>/dev/null || true)

if [[ -n "$LOCK_ID" ]]; then
  az lock delete --ids "$LOCK_ID" --output none
  ok "Lock removed"
else
  warn "No lock found — already removed or never created"
fi

# Also check for any locks at the storage account scope
if [[ -n "$STORAGE_ACCOUNT" ]]; then
  SA_ID=$(az storage account show \
    --name "$STORAGE_ACCOUNT" \
    --resource-group "$STATE_RG" \
    --query id -o tsv 2>/dev/null || true)
  if [[ -n "$SA_ID" ]]; then
    SA_LOCKS=$(az lock list --resource "$SA_ID" --query "[].id" -o tsv 2>/dev/null || true)
    if [[ -n "$SA_LOCKS" ]]; then
      log "Removing locks on storage account..."
      while IFS= read -r LID; do
        [[ -n "$LID" ]] && az lock delete --ids "$LID" --output none && ok "Removed $LID"
      done <<< "$SA_LOCKS"
    fi
  fi
fi

# ── 2. Delete the resource group ────────────────────────────────────────────
log "Deleting resource group '$STATE_RG' (this may take a few minutes)..."

MAX_DELETE_ATTEMPTS=6
DELETE_ATTEMPT=0
while (( DELETE_ATTEMPT < MAX_DELETE_ATTEMPTS )); do
  if az group delete --name "$STATE_RG" --yes --no-wait 2>/dev/null; then
    ok "Delete request accepted"
    break
  fi
  DELETE_ATTEMPT=$((DELETE_ATTEMPT+1))
  if (( DELETE_ATTEMPT < MAX_DELETE_ATTEMPTS )); then
    log "Lock propagation pending, retrying in 15s ($DELETE_ATTEMPT/$MAX_DELETE_ATTEMPTS)"
    sleep 15
  fi
done

if (( DELETE_ATTEMPT >= MAX_DELETE_ATTEMPTS )); then
  fail "Could not delete resource group after $MAX_DELETE_ATTEMPTS attempts. Check for remaining locks: az lock list --resource-group $STATE_RG -o table"
fi

echo ""
echo "==============================================================="
echo -e "  ${GREEN}[PASS]${NC} Teardown initiated"
echo ""
echo "  Resource group deletion is running asynchronously."
echo "  Monitor with:"
echo "    az group show --name $STATE_RG --query properties.provisioningState -o tsv"
echo ""
echo "  When complete, all of these are gone:"
echo "    - Resource group: $STATE_RG"
echo "    - Storage account: ${STORAGE_ACCOUNT:-<auto-detected>}"
echo "    - Blob container, RBAC role assignments, locks"
echo "==============================================================="
