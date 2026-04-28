#!/usr/bin/env bash
# 00-bootstrap-state.sh — Create Azure Storage Account for Terraform remote state
#
# Run this ONCE before 'terraform init'. It creates a dedicated resource group,
# storage account, and blob container for state files, secured with Entra ID auth,
# TLS-only, no public blob access, and a delete lock.
#
# Usage:
#   ./00-bootstrap-state.sh
#   ./00-bootstrap-state.sh --location eastus
#
# After this completes, run 'terraform init' with the printed -backend-config flags.

set -euo pipefail

# ── Colour helpers ───────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()   { echo -e "${GREEN}[OK]${NC}    $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail() { echo -e "${RED}[FAIL]${NC}  $*"; exit 1; }

# ── Defaults ─────────────────────────────────────────────────────────────────
PROJECT_NAME="${PROJECT_NAME:-bankingbuddy}"
LOCATION="${LOCATION:-centralindia}"
CONTAINER_NAME="${CONTAINER_NAME:-tfstate}"
STATE_KEY="${STATE_KEY:-${PROJECT_NAME}.terraform.tfstate}"

# ── Parse arguments ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case $1 in
    --project)         PROJECT_NAME="$2";    shift 2 ;;
    --location)        LOCATION="$2";        shift 2 ;;
    --container)       CONTAINER_NAME="$2";  shift 2 ;;
    --state-key)       STATE_KEY="$2";       shift 2 ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)  fail "Unknown argument: $1" ;;
  esac
done

# Derive names from project
RAND_SUFFIX=$(printf '%05x' $((RANDOM * RANDOM % 1048576)))
STORAGE_ACCOUNT="${PROJECT_NAME}tf${RAND_SUFFIX}"
STATE_RG="${PROJECT_NAME}-tfstate-rg"

echo "==============================================================="
echo "  Terraform State Backend - Bootstrap (BankingBuddy)"
echo "==============================================================="
echo ""
echo "  Resource Group:    $STATE_RG"
echo "  Storage Account:   $STORAGE_ACCOUNT"
echo "  Container:         $CONTAINER_NAME"
echo "  State key:         $STATE_KEY"
echo "  Location:          $LOCATION"
echo ""

# ── 0. Register required Azure resource providers ────────────────────────────
log "Registering Azure resource providers (idempotent)..."
PROVIDERS=(
  Microsoft.Storage
  Microsoft.App
  Microsoft.ContainerRegistry
  Microsoft.CognitiveServices
  Microsoft.Insights
  Microsoft.OperationalInsights
  Microsoft.Authorization
)
for p in "${PROVIDERS[@]}"; do
  state=$(az provider show --namespace "$p" --query registrationState -o tsv 2>/dev/null || echo "NotRegistered")
  if [[ "$state" != "Registered" ]]; then
    log "  registering $p (current state: $state)..."
    az provider register --namespace "$p" --output none
  fi
done
for p in "${PROVIDERS[@]}"; do
  for i in $(seq 1 60); do
    state=$(az provider show --namespace "$p" --query registrationState -o tsv 2>/dev/null || echo "Unknown")
    [[ "$state" == "Registered" ]] && break
    sleep 5
  done
  if [[ "$state" != "Registered" ]]; then
    warn "$p is still in state '$state' after 5 minutes — terraform apply may fail."
  fi
done
ok "All required providers registered."
echo ""

# ── 1. Resource group ────────────────────────────────────────────────────────
log "Creating resource group '$STATE_RG'..."
az group create \
  --name "$STATE_RG" \
  --location "$LOCATION" \
  --output none

# ── 2. Storage account ──────────────────────────────────────────────────────
log "Creating storage account '$STORAGE_ACCOUNT'..."
az storage account create \
  --name "$STORAGE_ACCOUNT" \
  --resource-group "$STATE_RG" \
  --location "$LOCATION" \
  --sku Standard_LRS \
  --kind StorageV2 \
  --min-tls-version TLS1_2 \
  --allow-blob-public-access false \
  --https-only true \
  --output none

# ── 3. Entra ID RBAC — Storage Blob Data Contributor ────────────────────────
log "Granting 'Storage Blob Data Contributor' to current user..."
PRINCIPAL_ID=$(az ad signed-in-user show --query id -o tsv 2>/dev/null || true)
if [[ -z "$PRINCIPAL_ID" ]]; then
  fail "Could not detect signed-in user. Run 'az login' and retry."
fi

SCOPE=$(az storage account show \
  --name "$STORAGE_ACCOUNT" \
  --resource-group "$STATE_RG" \
  --query id -o tsv)

az role assignment create \
  --role "Storage Blob Data Contributor" \
  --assignee "$PRINCIPAL_ID" \
  --scope "$SCOPE" \
  --output none 2>/dev/null || warn "Role may already be assigned"
ok "RBAC role granted to $PRINCIPAL_ID"

# ── 4. Wait for RBAC propagation ────────────────────────────────────────────
log "Waiting for RBAC propagation (this can take 1-5 minutes)..."
MAX_ATTEMPTS=30
ATTEMPT=0
while (( ATTEMPT < MAX_ATTEMPTS )); do
  if az storage container list \
       --account-name "$STORAGE_ACCOUNT" \
       --auth-mode login \
       --output none 2>/dev/null; then
    ok "RBAC propagated (attempt $((ATTEMPT+1)))"
    break
  fi
  ATTEMPT=$((ATTEMPT+1))
  printf "  ... attempt %d/%d, waiting 10s\r" "$ATTEMPT" "$MAX_ATTEMPTS"
  sleep 10
done
echo ""

if (( ATTEMPT >= MAX_ATTEMPTS )); then
  warn "RBAC did not propagate within 5 minutes. You may need to retry 'terraform init'."
fi

# ── 5. Blob container ───────────────────────────────────────────────────────
log "Creating blob container '$CONTAINER_NAME'..."
az storage container create \
  --name "$CONTAINER_NAME" \
  --account-name "$STORAGE_ACCOUNT" \
  --auth-mode login \
  --output none 2>/dev/null || warn "Container may already exist"
ok "Container ready"

# ── 6. Disable shared key access ────────────────────────────────────────────
log "Disabling storage account key access (Entra ID only)..."
az storage account update \
  --name "$STORAGE_ACCOUNT" \
  --resource-group "$STATE_RG" \
  --allow-shared-key-access false \
  --output none

# ── 7. Delete lock ──────────────────────────────────────────────────────────
log "Adding CanNotDelete lock..."
az lock create \
  --name "protect-tfstate" \
  --resource-group "$STATE_RG" \
  --lock-type CanNotDelete \
  --output none 2>/dev/null || true

echo ""
echo "==============================================================="
echo -e "  ${GREEN}[PASS]${NC} State backend ready!"
echo ""
echo "  Next steps:"
echo "    cd infra/terraform"
echo "    cp terraform.tfvars.example terraform.tfvars  # then edit values"
echo ""
echo "    terraform init \\"
echo "      -backend-config=\"resource_group_name=$STATE_RG\" \\"
echo "      -backend-config=\"storage_account_name=$STORAGE_ACCOUNT\" \\"
echo "      -backend-config=\"container_name=$CONTAINER_NAME\" \\"
echo "      -backend-config=\"key=$STATE_KEY\" \\"
echo "      -backend-config=\"use_azuread_auth=true\""
echo ""
echo "    terraform plan"
echo "    terraform apply"
echo "==============================================================="
