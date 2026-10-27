#!/usr/bin/env bash
#==============================================================================
# setup.sh - bootstrap working config from the public templates
#==============================================================================
# Copies each *.example template to its working name ONLY IF the target is
# missing, so your local edits are never overwritten.

set -euo pipefail

copy_if_missing() {
    local src="$1" dst="$2"
    if [ -e "$dst" ]; then
        echo "  skip  $dst (already exists)"
    else
        cp "$src" "$dst"
        echo "  made  $dst  (from $src)"
    fi
}

copy_if_missing .env.example .env
copy_if_missing config.example.py config.py
copy_if_missing ai-stack.sh.example ai-stack.sh

chmod +x ai-stack.sh

# The robot needs Python 3
if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found - install Python 3 and re-run setup.sh" >&2
    exit 1
fi

# Warn (not fail) on missing Python deps
if ! python3 -c "import requests, dotenv" >/dev/null 2>&1; then
    echo "WARNING: 'requests' or 'python-dotenv' missing for python3."
    echo "         pip3 install requests python-dotenv"
fi

cat <<'EOF'
Next steps:

  AI server:
    1. Edit .env              (SERVER_IP, LLAMA_MODEL, WEBUI_API_KEY)
    2. Put your .gguf in MODEL_DIR
    3. ./ai-stack.sh

  Robot:
    1. Edit .env SERVER_IP    (AI server IP as seen from the robot)
    2. python3 pidog_init.py  (once - hardware init + RPC daemon)
    3. python3 main.py
EOF
