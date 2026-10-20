#!/usr/bin/env bash
#==============================================================================
# 🐶 OLLIE'S AI STACK - PiDog Voice Assistant Engine
#==============================================================================
# This script initializes the complete AI infrastructure for the PiDog voice
# assistant. Optimized for simultaneous operation of:
#   - Open WebUI (STT interface at port 8089)
#   - Llama LLMs (ROCm GPU concurrency)
#   - Kokoro TTS (voice synthesis)
#==============================================================================

set -euo pipefail

## Open Websocket for remote Podman commands
systemctl --user enable --now podman.socket

socat TCP-LISTEN:8075,reuseaddr,fork UNIX-CONNECT:/run/user/1000/podman/podman.sock &

# Load environment variables from the shared .env file if it exists
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
else
    echo "⚠️ Warning: .env file not found in current directory. Using system env fields."
fi

#==============================================================================
# 🚀 BAZZITE NATIVE VRAM FLUSH & MEMORY PURGE ENGINE
#==============================================================================
set -euo pipefail

echo "🛑 Commencing native compositor VRAM cache purge..."

# 1. Purge background Steam suite entirely
if pgrep -f "steamwebhelper" > /dev/null; then
    echo "   Stopping background Steam allocations..."
    pkill -9 -f "steamwebhelper" || true
    pkill -9 -x "steam" || true
fi

# 2. Force KWin to immediately release all cached VRAM textures
if pgrep -x "kwin_wayland" > /dev/null || pgrep -x "kwin_x11" > /dev/null; then
    echo "   Sending DBus signal to flush KWin composition buffers..."
    # This forces KWin to re-evaluate and instantly drop unneeded textures from VRAM
    qdbus org.kde.KWin /KWin org.kde.KWin.reconfigure >/dev/null 2>&1 || true
fi

# 3. Strip Plasma Shell Background Buffers
if systemctl --user is-active plasma-plasmashell.service >/dev/null 2>&1; then
    echo "   Collapsing dynamic wallpaper VRAM structures..."
    kwriteconfig6 --file plasmashellrc --group Wallpaper --group image --key WallpaperType "org.kde.color" || true

    # Restarting the shell drops the panel and desktop desktop caches cleanly
    systemctl --user restart plasma-plasmashell.service >/dev/null 2>&1 || true
    sleep 1.0
fi

# 4. Global application environment directives for LLM compute
export AMD_DEBUG=nowait,nodisplaylist # If on AMD, prevents graphic drivers from over-allocating command streams
export DRI_PRIME=0                    # Keeps UI rendering strict

echo "✨ VRAM Reclamation complete. Compositor caches dropped."

#==============================================================================

# 1. Shared System Configurations
TAVILY_API_KEY="${TAVILY_API_KEY:-}"
STORAGE_PATH="/var/home/Ollie/open-webui-storage"
WEBUI_PORT=8089
LLAMA_PORT=11434
LLAMA_VRAM_SPLIT_THRESHOLD=0.95
WEBUI_API_KEY="${WEBUI_API_KEY:-}"
JARVIS_PORT=3000
KOKORO_PORT=8880

# Initialize file path to satisfy strict unbound variable checks (set -u)
TAB_CFG=""

# 2. Context Length Configuration
# Shared context length for all models to prevent resource conflicts

# 3. Container Lifecycle Reset
echo "🧹 Cleaning up previous container instances..."
podman rm -f \
    open-webui \
    kokoro-backend \
    kokoro-tts \
    cf-tunnel \
    cf-tunnel-ollama \
    cf-tunnel-claude \
    llama-router-gpu \
    2>/dev/null || true

# Clean up any orphaned ttyd sessions
## pkill -9 -f ttyd || true
## pkill -9 -f select-project.sh || true

# 4. Launch Llama ROCm GPU Instance
echo "🦙 Starting Llama GPU service..."
podman run -d \
    --name llama-router-gpu \
    --restart unless-stopped \
    -v ~/ollama_models:/models:Z \
    -e HSA_OVERRIDE_GFX_VERSION=10.3.0 \
    --security-opt label=disable \
    --group-add keep-groups \
    --ipc=host \
    --net=host \
    --device /dev/kfd \
    --device /dev/dri \
    localhost/ollie-patched-llama:latest \
    --models-preset /models/models.ini \
    --models-max 1 \
    --cors-origins "*" \
    --host 0.0.0.0 \
    --port ${LLAMA_PORT} \
    --parallel 1



# 5. Cloudflare Tunnel for Ollama (Remote Access)
## echo "🌐 Configuring Ollama Cloudflare tunnel..."
## podman run -d \
##    --name cf-tunnel-ollama \
##    --net=host \
##    --restart always \
##    --security-opt label=disable \
##    -e TUNNEL_TOKEN="${CF_TUNNEL_TOKEN_OLLAMA:-}" \
##    -e TUNNEL_ORIGIN_URL="http://localhost:${OLLAMA_PORT}" \
##    -e TUNNEL_DNS="pidog.meigs.co.uk:11434" \
##    -e TUNNEL_NO_AUTOUPDATE="true" \
##    docker.io/cloudflare/cloudflared:latest \
##    tunnel --no-autoupdate run --protocol http2

# 6. Cloudflare Tunnel for WebUI (STT Interface)
echo "🎤 Starting WebUI STT interface..."
podman run -d \
    --name cf-tunnel \
    --net=host \
    --restart always \
    --security-opt label=disable \
    -e TUNNEL_TOKEN="${CF_TUNNEL_TOKEN_WEBUI:-}" \
    -e TUNNEL_NO_AUTOUPDATE="true" \
    -e TUNNEL_ORIGIN_URL="http://localhost:${WEBUI_PORT}" \
    -e TUNNEL_DNS="ai.meigs.co.uk" \
    docker.io/cloudflare/cloudflared:latest \
    tunnel --no-autoupdate run --protocol http2

# 7. Open WebUI Container (STT Interface)
echo "🤖 Deploying Open WebUI..."
podman run -d \
    --name open-webui \
    --restart unless-stopped \
    -v "$STORAGE_PATH":/app/backend/data:rw \
    -e PORT="${WEBUI_PORT}" \
    -e ENABLE_PERSISTENT_CONFIG=True \
    -e WEBUI_SECRET_KEY="${WEBUI_API_KEY}" \
    -e LLAMA_BASE_URL="http://docker.internal:${LLAMA_PORT}" \
    -e WEBUI_NO_UPDATE_CHECK=True \
    -e WEBUI_ENABLE_AUTH=False \
    -e WEBUI_ENABLE_LOCAL_FILE_UPLOAD=True \
    --net=host \
    --cap-add NET_ADMIN \
    ghcr.io/open-webui/open-webui:v0.9.4

# 8. Kokoro TTS Backend (Voice Synthesis)
echo "🔊 Checking Kokoro TTS backend..."
if ! podman ps -a | grep -q kokoro-backend; then
    echo "   Starting Kokoro TTS backend service..."
    podman run -d \
        --name kokoro-backend \
        --restart unless-stopped \
        --net=host \
        --ipc=host \
        -e KOKORO_MODEL="onnxruntime-gpu" \
        -e KOKORO_DEVICE="rocm" \
        -e KOKORO_CONTEXT_LENGTH=4096 \
        -e KOKORO_MAX_NEW_TOKENS=8192 \
        -e KOKORO_TEMPERATURE=0.7 \
        -e KOKORO_PORT="${KOKORO_PORT}" \
        ghcr.io/remsky/kokoro-fastapi-cpu:latest
else
    echo "   Kokoro TTS backend already running"
fi

# 9. Completion Status & Konsole Multi-Tab Launcher
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ AI STACK ENGINE ONLINE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🦙 Llama GPU:        http://localhost:${LLAMA_PORT}"
echo "  🤖 Open WebUI STT:    http://localhost:${WEBUI_PORT}"
echo "  🔊 Kokoro TTS:        Running (voice synthesis)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if command -v konsole &> /dev/null; then
    echo "📊 Spawning Monitor Board Dashboard..."

    # Generate temporary tab routing profile layout
    TAB_CFG=$(mktemp /tmp/konsole_tabs.XXXXXX)

    # Populate fields with updated double-semicolon formatting + GPU hardware tracking
    cat << EOF > "$TAB_CFG"
title: GPU VRAM Monitor ;; command: nvtop
title: Llama Logs ;; command: podman logs -f llama-router-gpu
title: Open WebUI Logs ;; command: podman logs -f open-webui
title: Kokoro Logs ;; command: podman logs -f kokoro-backend
EOF

    # Open Konsole in background tracking processes safely
    konsole --hold --tabs-from-file "$TAB_CFG" &

    # Asynchronously delete tracking map layout profile after spawn execution
    (sleep 5 && rm -f "$TAB_CFG") &
else
    echo "⚠️ Konsole target binary path not found. Monitor logs directly via:"
    echo "   podman logs -f llama-router-gpu"
fi
