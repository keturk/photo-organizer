#!/bin/bash
# Photo Organizer - Setup Script
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "  📸 Photo Organizer - Setup"
echo "  ════════════════════════════════════════"
echo ""

# ── Check Python ───────────────────────────────────────────────
echo -n "  Python 3.10+... "
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    echo "✅ ($PY_VER)"
else
    echo "❌ Not found. Install python3."
    exit 1
fi

# ── Check exiftool ─────────────────────────────────────────────
echo -n "  exiftool... "
if command -v exiftool &>/dev/null; then
    echo "✅ ($(exiftool -ver))"
else
    echo "❌ Missing"
    echo "     Install: sudo apt install libimage-exiftool-perl"
    MISSING=1
fi

# ── Check ImageMagick ──────────────────────────────────────────
echo -n "  ImageMagick... "
if command -v convert &>/dev/null; then
    echo "✅"
else
    echo "❌ Missing (needed for HEIC conversion)"
    echo "     Install: sudo apt install imagemagick"
    MISSING=1
fi

# ── Create virtual environment ────────────────────────────────
echo ""
if [ ! -d .venv ]; then
    echo "  Creating virtual environment..."
    python3 -m venv .venv
    echo "  ✅ .venv created"
else
    echo "  ℹ️  .venv already exists"
fi

# shellcheck disable=SC1091
source .venv/bin/activate
echo "  ✅ Virtual environment activated"

# ── Install Python dependencies ──────────────────────────────
echo -n "  Installing Python dependencies... "
pip install -q -r requirements.txt
echo "✅"

# ── Create config ──────────────────────────────────────────────
echo ""
if [ ! -f .env ]; then
    echo "  Creating .env from template..."
    cp .env.example .env
    echo "  ✅ .env created — edit if your paths differ"
else
    echo "  ℹ️  .env already exists"
fi

# ── Check Ollama connectivity ──────────────────────────────────
OLLAMA_HOST=$(grep '^OLLAMA_URL=' .env 2>/dev/null | sed 's|OLLAMA_URL=http://||;s|/.*||' | tr -d '\r')
OLLAMA_HOST="${OLLAMA_HOST:-localhost:11434}"
echo -n "  Ollama ($OLLAMA_HOST)... "
if curl -s --connect-timeout 3 "http://$OLLAMA_HOST/api/tags" >/dev/null 2>&1; then
    echo "✅"
else
    echo "⚠️  Not reachable (needed for AI vision)"
fi

# ── Check qwen3-vl model ──────────────────────────────────────
echo -n "  qwen3-vl:32b model... "
if curl -s "http://$OLLAMA_HOST/api/tags" 2>/dev/null | grep -q "qwen3-vl:32b"; then
    echo "✅"
else
    echo "⚠️  Not found on Ollama server"
    echo "     Pull it: ssh <llm-pc> 'docker exec ollama ollama pull qwen3-vl:32b'"
fi

# ── Make scripts executable ────────────────────────────────────
chmod +x photo_audit.py photo_tools.py

# ── Install IronClaw skill ─────────────────────────────────────
echo ""
SKILL_DIR="$HOME/.ironclaw/skills"
if [ -d "$HOME/.ironclaw" ]; then
    mkdir -p "$SKILL_DIR"
    cp ironclaw_skill/photo_collection_manager.md "$SKILL_DIR/"
    echo "  ✅ IronClaw skill installed to $SKILL_DIR"
else
    echo "  ℹ️  IronClaw not found — skill not installed"
    echo "     Install manually later: mkdir -p ~/.ironclaw/skills && cp ironclaw_skill/photo_collection_manager.md ~/.ironclaw/skills/"
fi

# ── Summary ────────────────────────────────────────────────────
echo ""
echo "  ════════════════════════════════════════"
if [ "${MISSING:-0}" = "1" ]; then
    echo "  ⚠️  Some dependencies missing — install them first"
    echo "     sudo apt install libimage-exiftool-perl imagemagick -y"
else
    echo "  ✅ Setup complete!"
fi
echo ""
echo "  Next steps:"
echo "    1. Edit .env if needed"
echo "    2. Activate the venv:  source .venv/bin/activate"
echo "    3. Run the audit:  python3 photo_audit.py"
echo "    4. Start IronClaw: ironclaw"
echo "       Then ask: 'Show me photo collection stats'"
echo "    5. When done:  deactivate"
echo ""
