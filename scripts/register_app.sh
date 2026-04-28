#!/usr/bin/env bash
# register_app.sh — Register BankingBuddyDemo with PII Shield API.
#
# Idempotent: if an app named "BankingBuddyDemo" already exists, reuses it.
# Sets CUSTOMER_ID in the entity-type allow list so customer IDs are not
# anonymized (agent tools need them).
#
# Usage:
#   ./scripts/register_app.sh                          # uses PII_SHIELD_API_URL from .env or localhost:8000
#   PII_SHIELD_API_URL=http://host:8000 ./scripts/register_app.sh
#
# After running, copy the printed PII_SHIELD_APP_ID into your .env file.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Load .env if present
if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a; source "$REPO_ROOT/.env"; set +a
fi

API_URL="${PII_SHIELD_API_URL:-http://localhost:8000}"
APP_NAME="BankingBuddyDemo"

log()  { printf "\033[1;34m[%s]\033[0m %s\n" "$(date +%H:%M:%S)" "$*"; }
ok()   { printf "\033[1;32m[ok]\033[0m %s\n" "$*"; }
fail() { printf "\033[1;31m[FAIL]\033[0m %s\n" "$*"; exit 1; }

# ── 1. Check API health ─────────────────────────────────────────────────────
log "Checking PII Shield API at $API_URL ..."
if ! curl -sf "$API_URL/health" >/dev/null 2>&1; then
  fail "PII Shield API is not reachable at $API_URL. Is it running?"
fi
ok "PII Shield API is healthy."

# ── 2. Check if app already registered ───────────────────────────────────────
log "Checking for existing app '$APP_NAME'..."
EXISTING=$(curl -sf "$API_URL/apps" | python3 -c "
import sys, json
apps = json.load(sys.stdin)
for app in apps:
    if app['app_name'] == '$APP_NAME':
        print(app['app_id'])
        break
" 2>/dev/null || true)

if [[ -n "$EXISTING" ]]; then
  APP_ID="$EXISTING"
  ok "App '$APP_NAME' already registered (app_id: $APP_ID)"
else
  # ── 3. Register new app ──────────────────────────────────────────────────
  log "Registering app '$APP_NAME'..."
  REGISTER_RESP=$(curl -sf -X POST "$API_URL/apps" \
    -H "Content-Type: application/json" \
    -d "{\"app_name\": \"$APP_NAME\"}")
  APP_ID=$(echo "$REGISTER_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['app_id'])")
  ok "App registered: $APP_NAME (app_id: $APP_ID)"
fi

# ── 4. Set entity-type allow list ─────────────────────────────────────────
# CUSTOMER_ID is NOT allow-listed: the middleware anonymizes it, the
# FunctionMiddleware de-anonymizes tool args, and re-anonymizes tool results.
# This ensures the LLM never sees any real PII.
log "Setting entity-type allow list: [] (empty — all entity types are anonymized) ..."
curl -sf -X PUT "$API_URL/apps/$APP_ID/entity-type-allow-list" \
  -H "Content-Type: application/json" \
  -d '{"entity_type_allow_list": []}' >/dev/null
ok "Entity-type allow list updated (empty)."

# ── 5. Verify ────────────────────────────────────────────────────────────────
log "Verifying app config..."
curl -sf "$API_URL/apps/$APP_ID" | python3 -m json.tool

echo ""
echo "================================================================="
echo "  App registered successfully!"
echo "================================================================="
echo "  App Name:  $APP_NAME"
echo "  App ID:    $APP_ID"
echo ""
echo "  Add this to your .env file:"
echo "    PII_SHIELD_APP_ID=$APP_ID"
echo "================================================================="
