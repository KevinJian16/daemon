#!/usr/bin/env bash
# Daemon environment setup — run on a fresh Mac to install all dependencies.
# Usage: bash scripts/setup.sh
set -euo pipefail

DAEMON_HOME="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DAEMON_HOME"

echo "=== Daemon Setup ==="
echo "  DAEMON_HOME: $DAEMON_HOME"

# ── 0. Prerequisites ──
echo ""
echo "[0/7] Checking prerequisites..."

# Xcode Command Line Tools (required for Rust/Tauri build)
if ! xcode-select -p &>/dev/null; then
  echo "  Installing Xcode Command Line Tools..."
  xcode-select --install
  echo "  ⚠ Wait for Xcode CLT installation to finish, then re-run this script."
  exit 1
fi
echo "  Xcode CLT: OK"

# Python 3.11+
if ! command -v python3 &>/dev/null; then
  echo "  ERROR: Python 3.11+ required. Install from python.org or brew install python@3.11"
  exit 1
fi
PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_OK=$(python3 -c "import sys; print('1' if sys.version_info >= (3, 11) else '0')")
if [ "$PY_OK" != "1" ]; then
  echo "  ERROR: Python 3.11+ required, found $PY_VERSION"
  exit 1
fi
echo "  Python: $PY_VERSION OK"

# ── 1. Homebrew ──
echo ""
if ! command -v brew &>/dev/null; then
  echo "[1/7] Installing Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
else
  echo "[1/7] Homebrew already installed"
fi

# ── 2. Brew packages ──
echo ""
echo "[2/7] Installing brew packages..."

# CLI tools
brew install duti ollama gh 2>/dev/null || true

# GUI apps
brew install --cask zotero 2>/dev/null || true

# Rust (for Tauri build)
if ! command -v cargo &>/dev/null; then
  echo "  Installing Rust..."
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
  export PATH="$HOME/.cargo/bin:$PATH"
else
  echo "  Rust already installed"
fi

# ── 3. Node.js + OpenClaw ──
echo ""
if ! command -v node &>/dev/null; then
  echo "[3/7] Installing Node.js..."
  brew install node
else
  echo "[3/7] Node.js already installed ($(node --version))"
fi

if ! command -v openclaw &>/dev/null; then
  echo "  Installing OpenClaw..."
  npm install -g openclaw
else
  echo "  OpenClaw already installed"
fi

# ── 4. Python dependencies ──
echo ""
echo "[4/7] Installing Python dependencies..."
pip install -e . 2>/dev/null || pip install -e ".[dev]" 2>/dev/null || echo "  Warning: pip install failed, check pyproject.toml"

# ── 5. Portal frontend + Tauri ──
echo ""
echo "[5/7] Installing frontend dependencies..."
cd interfaces/portal
npm install
npm install @tauri-apps/cli@latest @tauri-apps/api@latest
cd "$DAEMON_HOME"

# ── 6. .env file ──
echo ""
echo "[6/7] Checking .env..."
if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    cp .env.example .env
    echo "  .env created from .env.example — fill in API keys before starting"
  else
    echo "  ⚠ No .env or .env.example found — create .env manually"
  fi
else
  KEY_COUNT=$(grep -c '=' .env || echo 0)
  echo "  .env exists ($KEY_COUNT keys)"
fi

# ── 7. Docker containers ──
echo ""
echo "[7/7] Starting Docker containers..."
if command -v docker &>/dev/null; then
  docker compose up -d
else
  echo "  ⚠ Docker not installed — install Docker Desktop from docker.com"
fi

# ── Post-setup: default apps ──
echo ""
echo "=== Post-setup ==="
duti -s org.zotero.zotero .pdf all 2>/dev/null && echo "  PDF default → Zotero" || true

# Symlink
if [ ! -L "$HOME/.openclaw" ]; then
  ln -sf "$DAEMON_HOME/openclaw" "$HOME/.openclaw"
  echo "  Created ~/.openclaw → $DAEMON_HOME/openclaw"
fi

# Ollama models
echo ""
echo "=== Pulling Ollama models ==="
ollama pull qwen2.5:32b 2>/dev/null &
ollama pull qwen2.5:7b 2>/dev/null &
ollama pull nomic-embed-text 2>/dev/null &
wait
echo "  Ollama models ready"

# ── Verification ──
echo ""
echo "=== Verification ==="
echo "  Homebrew:   $(brew --version 2>/dev/null | head -1 || echo 'missing')"
echo "  Node:       $(node --version 2>/dev/null || echo 'missing')"
echo "  Python:     $(python3 --version 2>/dev/null || echo 'missing')"
echo "  Rust:       $(rustc --version 2>/dev/null || echo 'missing')"
echo "  Docker:     $(docker --version 2>/dev/null || echo 'missing')"
echo "  Ollama:     $(ollama --version 2>/dev/null || echo 'missing')"
echo "  gh:         $(gh --version 2>/dev/null | head -1 || echo 'missing')"
echo "  OpenClaw:   $(openclaw --version 2>/dev/null || echo 'installed')"
echo "  VS Code:    $(code --version 2>/dev/null | head -1 || echo 'missing — install manually')"
echo "  Zotero:     $([ -d /Applications/Zotero.app ] && echo 'installed' || echo 'missing')"
echo "  .env:       $([ -f .env ] && echo "$(grep -c '=' .env) keys" || echo 'missing')"
echo "  ~/.openclaw: $([ -L "$HOME/.openclaw" ] && echo 'linked' || echo 'missing')"

echo ""
echo "=== Setup complete ==="
echo "Next steps:"
echo "  1. Fill in .env API keys (GITHUB_TOKEN, BRAVE_API_KEY, etc.)"
echo "  2. Run: python scripts/verify.py"
echo "  3. Run: python scripts/warmup.py"
