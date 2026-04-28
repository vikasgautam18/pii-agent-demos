#!/usr/bin/env bash
# run_local.sh — Run BankingBuddy locally WITHOUT Docker.
#
# This script:
#   1. Checks Python version (3.10-3.12 required)
#   2. Creates / activates a virtualenv at .venv
#   3. Installs pip dependencies
#   4. Downloads the spaCy / ONNX NLP model matching $NLP_ENGINE
#   5. Creates .env from .env.example if missing
#   6. Verifies Azure CLI login (needed for FoundryChatClient auth)
#   7. Launches the Streamlit chat UI
#
# Usage:
#   ./scripts/run_local.sh              # full setup + launch Streamlit
#   ./scripts/run_local.sh --stop       # stop Streamlit
#
# Requirements:
#   - Python 3.10, 3.11, or 3.12 (NOT 3.13+ yet)
#   - Azure CLI logged in (`az login`)
#
# Windows users: run this from WSL, or use the PowerShell equivalent.

set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────────────
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

VENV_DIR="${VENV_DIR:-$REPO_ROOT/.venv}"
PID_DIR="${PID_DIR:-$REPO_ROOT/.run}"
LOG_DIR="${LOG_DIR:-$REPO_ROOT/.run/logs}"
NLP_ENGINE="${NLP_ENGINE:-onnx}"   # matches .env.example default

STREAMLIT_PORT="${STREAMLIT_PORT:-8501}"

MODE="full"

# ── Parse args ───────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case $1 in
    --stop)  MODE="stop"; shift ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

mkdir -p "$PID_DIR" "$LOG_DIR"

# ── Helpers ──────────────────────────────────────────────────────────────────
log()   { printf "\033[1;34m[%s]\033[0m %s\n" "$(date +%H:%M:%S)" "$*"; }
warn()  { printf "\033[1;33m[WARN]\033[0m %s\n" "$*"; }
fail()  { printf "\033[1;31m[FAIL]\033[0m %s\n" "$*"; exit 1; }
ok()    { printf "\033[1;32m[ok]\033[0m %s\n" "$*"; }

stop_pid() {
  local name="$1"
  local pidfile="$PID_DIR/${name}.pid"
  if [[ -f "$pidfile" ]]; then
    local pid
    pid=$(cat "$pidfile")
    if kill -0 "$pid" 2>/dev/null; then
      log "Stopping $name (pid $pid)..."
      kill "$pid" 2>/dev/null || true
      sleep 1
      kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$pidfile"
  fi
}

# ── Stop mode ────────────────────────────────────────────────────────────────
if [[ "$MODE" == "stop" ]]; then
  stop_pid streamlit
  ok "Stopped all local services."
  exit 0
fi

# ── 1. Python version check ─────────────────────────────────────────────────
log "Checking Python..."
PYTHON=""
for candidate in python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    version=$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    major=${version%%.*}
    minor=${version##*.}
    if [[ "$major" -eq 3 && "$minor" -ge 10 && "$minor" -le 12 ]]; then
      PYTHON="$candidate"
      log "  Using $candidate (version $version)"
      break
    fi
  fi
done

if [[ -z "$PYTHON" ]]; then
  fail "Need Python 3.10, 3.11, or 3.12 on PATH. Found none compatible.
  Ubuntu/Debian:   sudo apt install python3.12 python3.12-venv
  macOS:           brew install python@3.12
  Windows (WSL):   use the apt command above"
fi

# ── 2. Virtualenv ────────────────────────────────────────────────────────────
if [[ ! -d "$VENV_DIR" ]]; then
  log "Creating virtualenv at $VENV_DIR..."
  "$PYTHON" -m venv "$VENV_DIR" || fail "venv creation failed.
  On Debian/Ubuntu you may need:  sudo apt install ${PYTHON}-venv"
fi
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

# ── 3. Dependencies ─────────────────────────────────────────────────────────
STAMP="$VENV_DIR/.deps_installed_$(md5sum requirements.txt | cut -c1-8)"
if [[ ! -f "$STAMP" ]]; then
  log "Installing dependencies (this takes a few minutes on first run)..."
  pip install --upgrade pip >/dev/null
  pip install -r requirements.txt
  pip install -e .
  touch "$STAMP"
  ok "Dependencies installed."
else
  log "Dependencies already installed (stamp: $(basename "$STAMP"))."
fi

# ── 4. Env file (must come before model download — NLP_ENGINE may be set here) ──
if [[ ! -f .env ]]; then
  log "Creating .env from .env.example..."
  cp .env.example .env
  ok ".env created — edit it to set FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_MODEL."
fi

# Source .env so NLP_ENGINE / TRANSFORMERS_MODEL / QUANTIZED_MODEL_DIR / etc.
# are visible to both this script AND the child streamlit process.
# Shell-level NLP_ENGINE (set before invoking the script) wins over .env.
log "Loading .env into the shell environment..."
PRE_NLP_ENGINE="${NLP_ENGINE:-}"
set -a
# shellcheck source=/dev/null
source .env
set +a
# Restore caller's NLP_ENGINE override if they set one explicitly.
if [[ -n "$PRE_NLP_ENGINE" ]]; then
  NLP_ENGINE="$PRE_NLP_ENGINE"
  export NLP_ENGINE
fi
NLP_ENGINE="${NLP_ENGINE:-onnx}"
export NLP_ENGINE
ok "NLP_ENGINE=$NLP_ENGINE"

# ── 5. NLP model ─────────────────────────────────────────────────────────────
log "Ensuring NLP model is available (NLP_ENGINE=$NLP_ENGINE)..."
case "$NLP_ENGINE" in
  spacy)
    python -c "import spacy; spacy.load('en_core_web_lg')" 2>/dev/null \
      || python -m spacy download en_core_web_lg
    ;;
  onnx)
    # Tokenizer model
    python -c "import spacy; spacy.load('en_core_web_sm')" 2>/dev/null \
      || python -m spacy download en_core_web_sm
    # Pre-download + INT8 quantize the ONNX NER model so the app doesn't
    # block on first request (and avoids silent FP32 fallback).
    TRANSFORMERS_MODEL="${TRANSFORMERS_MODEL:-protectai/bert-base-NER-onnx}"
    QUANTIZED_MODEL_DIR="${QUANTIZED_MODEL_DIR:-models/onnx-int8}"
    QUANTIZE_MODEL="${QUANTIZE_MODEL:-true}"
    if [[ "$QUANTIZE_MODEL" == "true" && ! -f "$QUANTIZED_MODEL_DIR/model_quantized.onnx" ]]; then
      log "Quantized ONNX model not found at $QUANTIZED_MODEL_DIR — building it now (one-time, ~1-2 min)..."
      mkdir -p "$(dirname "$QUANTIZED_MODEL_DIR")"
      python scripts/quantize_model.py "$TRANSFORMERS_MODEL" "$QUANTIZED_MODEL_DIR" \
        || warn "Quantization failed — engine will fall back to FP32 download at runtime."
    elif [[ "$QUANTIZE_MODEL" == "true" ]]; then
      log "  Quantized model already present at $QUANTIZED_MODEL_DIR."
    else
      log "  Pre-downloading FP32 ONNX model $TRANSFORMERS_MODEL into HF cache..."
      python -c "from optimum.onnxruntime import ORTModelForTokenClassification; from transformers import AutoTokenizer; ORTModelForTokenClassification.from_pretrained('$TRANSFORMERS_MODEL'); AutoTokenizer.from_pretrained('$TRANSFORMERS_MODEL')" \
        || warn "Could not pre-download $TRANSFORMERS_MODEL — will be retried at runtime."
    fi
    ;;
  transformers)
    python -c "import spacy; spacy.load('en_core_web_sm')" 2>/dev/null \
      || python -m spacy download en_core_web_sm
    TRANSFORMERS_MODEL="${TRANSFORMERS_MODEL:-dslim/bert-base-NER}"
    log "  Pre-downloading transformers model $TRANSFORMERS_MODEL into HF cache..."
    python -c "from transformers import AutoModelForTokenClassification, AutoTokenizer; AutoModelForTokenClassification.from_pretrained('$TRANSFORMERS_MODEL'); AutoTokenizer.from_pretrained('$TRANSFORMERS_MODEL')" \
      || warn "Could not pre-download $TRANSFORMERS_MODEL — will be retried at runtime."
    ;;
  *)
    warn "Unknown NLP_ENGINE=$NLP_ENGINE — skipping model download."
    ;;
esac
ok "NLP model ready."

# ── 6. Azure CLI check ──────────────────────────────────────────────────────
log "Checking Azure CLI login (required for FoundryChatClient auth)..."
if command -v az >/dev/null 2>&1; then
  if az account show >/dev/null 2>&1; then
    ACCOUNT=$(az account show --query '{name:name, id:id}' -o tsv 2>/dev/null || echo "unknown")
    ok "Azure CLI logged in ($ACCOUNT)"
  else
    warn "Azure CLI installed but not logged in. Run: az login"
    warn "BankingBuddy needs Azure credentials for FoundryChatClient."
  fi
else
  warn "Azure CLI (az) not found on PATH. Install it and run: az login"
  warn "BankingBuddy needs Azure credentials for FoundryChatClient."
fi

# ── 7. Launch Streamlit ─────────────────────────────────────────────────────
log "Starting Streamlit chat UI on port $STREAMLIT_PORT..."
stop_pid streamlit   # kill previous instance if running

nohup streamlit run app/streamlit_chat.py \
  --server.port "$STREAMLIT_PORT" \
  --server.address 0.0.0.0 \
  --server.headless true \
  >"$LOG_DIR/streamlit.log" 2>&1 &
echo $! > "$PID_DIR/streamlit.pid"

sleep 2

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "==============================================================="
echo "  BankingBuddy is running locally (no Docker)"
echo "==============================================================="
echo "  Streamlit UI:  http://localhost:$STREAMLIT_PORT"
echo ""
echo "  Logs:          $LOG_DIR/"
echo "  Stop:          ./scripts/run_local.sh --stop"
echo "==============================================================="
