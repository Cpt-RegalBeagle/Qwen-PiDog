#!/usr/bin/env bash
#==============================================================================
# 🐶 OLLIE'S AI STACK - PiDog Voice Assistant Engine
#==============================================================================
# This script initializes the complete AI infrastructure for the PiDog voice
# assistant. Optimized for simultaneous operation of:
#   - Open WebUI (STT interface at port 8080)
#   - Ollama LLMs (qwen3.5:latest exclusively on ROCm GPU)
#   - Kokoro TTS (voice synthesis)
#==============================================================================

set -euo pipefail

# Load environment variables from the shared .env file if it exists
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
else
    echo "⚠️ Warning: .env file not found in current directory. Using system env fields."
fi

# 1. Shared System Configurations
TAVILY_API_KEY="${TAVILY_API_KEY:-}"
STORAGE_PATH="/var/home/Ollie/open-webui-storage"
WEBUI_PORT=8080
OLLAMA_PORT=11434
WEBUI_API_KEY="${WEBUI_API_KEY:-}"
JARVIS_PORT=3000
KOKORO_PORT=8880

# 2. Context Length Configuration
# Shared context length for all models to prevent resource conflicts
CONTEXT_LEN=32768

# 3. Container Lifecycle Reset
echo "🧹 Cleaning up previous container instances..."
podman rm -f \
    open-webui \
    kokoro-backend \
    kokoro-tts \
    cf-tunnel \
    cf-tunnel-ollama \
    cf-tunnel-claude \
    ollama-gpu \
    2>/dev/null || true

# Clean up any orphaned ttyd sessions
pkill -9 -f ttyd || true
pkill -9 -f select-project.sh || true

# 4. Launch Ollama ROCm GPU Instance
echo "🦙 Starting Ollama GPU service..."
podman run -d \
    --name ollama-gpu \
    --restart unless-stopped \
    --cap-add SYS_PTRACE \
    -v ~/ollama_models:/root/.ollama:Z \
    -e OLLAMA_HOST="0.0.0.0:${OLLAMA_PORT}" \
    -e OLLAMA_ORIGINS="*" \
    -e HSA_OVERRIDE_GFX_VERSION="10.3.0" \
    -e OLLAMA_KEEP_ALIVE="-1" \
    -e OLLAMA_NUM_PARALLEL=2 \
    -e OLLAMA_CONTEXT_LENGTH="${CONTEXT_LEN}" \
    -e OLLAMA_FLASH_ATTENTION=1 \
    -e OLLAMA_KEEP_LOADED=8h \
    --device /dev/kfd \
    --device /dev/dri \
    --group-add keep-groups \
    --security-opt label=disable \
    --ipc=host \
    --net=host \
    --entrypoint /bin/bash \
    docker.io/ollama/ollama:rocm \
    -c "ollama serve & sleep 5 && ollama pull qwen3.5:latest 2>&1 && wait"

# 5. Cloudflare Tunnel for Ollama (Remote Access)
echo "🌐 Configuring Ollama Cloudflare tunnel..."
podman run -d \
    --name cf-tunnel-ollama \
    --net=host \
    --restart always \
    --security-opt label=disable \
    -e TUNNEL_TOKEN="${CF_TUNNEL_TOKEN_OLLAMA:-}" \
    -e TUNNEL_ORIGIN_URL="http://localhost:${OLLAMA_PORT}" \
    -e TUNNEL_DNS="pidog.meigs.co.uk:11434" \
    -e TUNNEL_NO_AUTOUPDATE="true" \
    docker.io/cloudflare/cloudflared:latest \
    tunnel --no-autoupdate run --protocol http2

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
    -e ENABLE_PERSISTENT_CONFIG=True \
    -e WEBUI_SECRET_KEY="${WEBUI_API_KEY}" \
    -e OLLAMA_BASE_URL="http://host.docker.internal:${OLLAMA_PORT}" \
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

# 9. Completion Status
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ AI STACK ENGINE ONLINE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🦙 Ollama GPU:        http://localhost:${OLLAMA_PORT}"
echo "  🤖 Open WebUI STT:    http://localhost:${WEBUI_PORT}"
echo "  🔊 Kokoro TTS:        Running (voice synthesis)"
echo "  🌐 External Access:   See profile-specific URLs above"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Cleanup temp tab config
(konsole --hold --tabs-from-file "$TAB_CFG" &) &
(sleep 5 && rm -f "$TAB_CFG") &
