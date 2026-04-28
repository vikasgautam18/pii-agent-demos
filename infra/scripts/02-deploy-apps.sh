#!/usr/bin/env bash
# ── 02-deploy-apps.sh ────────────────────────────────────────────────────────
# Deploy the BankingBuddy container app to Azure Container Apps.
# Reads infrastructure details from Terraform outputs.
#
# Deploys a single container app "bankingbuddy" running the Streamlit UI on
# port 8501, with system-assigned managed identity and the
# "Cognitive Services OpenAI User" role for Azure OpenAI access.
#
# Prerequisites:
#   - Terraform applied (infra/terraform)
#   - Image built and pushed (01-build-push.sh)
#   - Azure CLI logged in with containerapp extension
#
# Usage:
#   cd infra/scripts && ./02-deploy-apps.sh
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

# ── Ensure required Azure CLI extensions ─────────────────────────────────────
az config set extension.dynamic_install_allow_preview=true  2>/dev/null
az config set extension.use_dynamic_install=yes_without_prompt  2>/dev/null
az extension add --name containerapp --upgrade --allow-preview true -y 2>/dev/null || true

IMAGE_TAG="${IMAGE_TAG:-latest}"
IMAGE_NAME="${IMAGE_NAME:-bankingbuddy}"
APP_NAME="${APP_NAME:-bankingbuddy}"
APP_PORT="${APP_PORT:-8501}"
NLP_ENGINE="${NLP_ENGINE:-onnx}"

# ── Read Terraform outputs ───────────────────────────────────────────────────
log "Reading Terraform outputs..."
RG_NAME=$(cd "$TF_DIR" && terraform output -raw resource_group_name)
ACA_ENV=$(cd "$TF_DIR" && terraform output -raw aca_env_name)
ACR_LOGIN=$(cd "$TF_DIR" && terraform output -raw acr_login_server)
OPENAI_DEPLOYMENT=$(cd "$TF_DIR" && terraform output -raw openai_deployment_name)
APPINSIGHTS_CONN=$(cd "$TF_DIR" && terraform output -raw app_insights_connection_string)

# FOUNDRY_PROJECT_ENDPOINT is the AI Foundry project URL, NOT the raw OpenAI endpoint.
# It must be set via env var or .env — Terraform doesn't manage Foundry projects.
# Format: https://<name>.services.ai.azure.com/api/projects/<project-id>
FOUNDRY_PROJECT_ENDPOINT="${FOUNDRY_PROJECT_ENDPOINT:-}"
if [[ -z "$FOUNDRY_PROJECT_ENDPOINT" ]]; then
  fail "FOUNDRY_PROJECT_ENDPOINT is not set.
  Get it from: Azure AI Foundry portal → Project → Overview → Endpoint
  Set it as:   export FOUNDRY_PROJECT_ENDPOINT=https://xxx.services.ai.azure.com/api/projects/yyy"
fi

IMAGE="${ACR_LOGIN}/${IMAGE_NAME}:${IMAGE_TAG}"

echo ""
echo "  Resource Group:       $RG_NAME"
echo "  ACA Environment:     $ACA_ENV"
echo "  ACR Login:            $ACR_LOGIN"
echo "  Image:                $IMAGE"
echo "  Foundry Endpoint:    $FOUNDRY_PROJECT_ENDPOINT"
echo "  Model Deployment:    $OPENAI_DEPLOYMENT"
echo "  NLP Engine:           $NLP_ENGINE"
echo "  App Insights:         ${APPINSIGHTS_CONN:0:50}...(redacted)"
echo ""

# ── Deploy bankingbuddy container app ──────────────────────────────────────────
log "Deploying container app '$APP_NAME'..."

az containerapp create \
  --name "$APP_NAME" \
  --resource-group "$RG_NAME" \
  --environment "$ACA_ENV" \
  --image "$IMAGE" \
  --registry-server "$ACR_LOGIN" \
  --target-port "$APP_PORT" \
  --ingress external \
  --min-replicas 0 \
  --max-replicas 3 \
  --cpu 1 \
  --memory 2Gi \
  --env-vars \
    FOUNDRY_PROJECT_ENDPOINT="$FOUNDRY_PROJECT_ENDPOINT" \
    FOUNDRY_MODEL="$OPENAI_DEPLOYMENT" \
    NLP_ENGINE="$NLP_ENGINE" \
    APPLICATIONINSIGHTS_CONNECTION_STRING="$APPINSIGHTS_CONN"

APP_FQDN=$(az containerapp show \
  --name "$APP_NAME" \
  --resource-group "$RG_NAME" \
  --query properties.configuration.ingress.fqdn -o tsv)

ok "Container app deployed: https://$APP_FQDN"

# ── Enable system-assigned managed identity ──────────────────────────────────
log "Enabling system-assigned managed identity..."
az containerapp identity assign \
  --name "$APP_NAME" \
  --resource-group "$RG_NAME" \
  --system-assigned \
  2>/dev/null || warn "System identity may already be assigned"

PRINCIPAL_ID=$(az containerapp identity show \
  --name "$APP_NAME" \
  --resource-group "$RG_NAME" \
  --query principalId -o tsv)

ok "Managed identity principal: ${PRINCIPAL_ID}"

# ── Assign "Cognitive Services OpenAI User" role ─────────────────────────────
log "Assigning 'Cognitive Services OpenAI User' role to managed identity..."

# Find the OpenAI account resource ID from the endpoint
OPENAI_ACCOUNT_ID=$(az cognitiveservices account list \
  --resource-group "$RG_NAME" \
  --query "[?contains(properties.endpoint, '$(echo "$OPENAI_ENDPOINT" | sed "s|https://||;s|/||g")')].[id]" \
  -o tsv 2>/dev/null || true)

# Fallback: list all Cognitive Services accounts in the RG and pick the first one
if [[ -z "$OPENAI_ACCOUNT_ID" ]]; then
  OPENAI_ACCOUNT_ID=$(az cognitiveservices account list \
    --resource-group "$RG_NAME" \
    --query "[0].id" -o tsv 2>/dev/null || true)
fi

if [[ -n "$OPENAI_ACCOUNT_ID" ]]; then
  az role assignment create \
    --role "Cognitive Services OpenAI User" \
    --assignee "$PRINCIPAL_ID" \
    --scope "$OPENAI_ACCOUNT_ID" \
    --output none 2>/dev/null || warn "Role may already be assigned"
  ok "Role assigned on scope: ${OPENAI_ACCOUNT_ID##*/}"
else
  warn "Could not find OpenAI account in RG '$RG_NAME'. Assign the role manually."
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  BankingBuddy — Azure Container Apps Deployment Complete"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "  App:   https://$APP_FQDN"
echo ""
echo "  Run ./03-verify.sh to run smoke tests."
echo "═══════════════════════════════════════════════════════════════"
