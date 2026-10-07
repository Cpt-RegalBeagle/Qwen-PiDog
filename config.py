#!/usr/bin/env python3
"""
PiDog Voice Assistant Configuration v1.1
All settings for the voice assistant, including:
- Audio device settings
- Network/server endpoints
- Voice and model parameters
- Remote PiDog destination settings
"""
from typing import Optional
import os


# ==================== AUDIO SETTINGS ====================
OUTPUT_DEVICE_ID: str = os.getenv("PIDOG_OUTPUT_DEVICE", "pipewire")

# INPUT_DEVICE_ID: Use device index for PiDog voiceHAT, or None for auto-detect on local
# PiDog voiceHAT is typically device 0. Set to None for local machine auto-detect.
INPUT_DEVICE_ID: Optional[str] = (
    os.getenv("PIDOG_INPUT_DEVICE") or
    ("0" if os.getenv("REMOTE_PI_DOG_ENABLED", "false") != "false" else None)
)
VOSK_SAMPLERATE: int = 16000
AUDIO_DEVICE_NAME: str = "piDog"

# ==================== AUDIO GAIN SETTINGS ====================
GAIN_MULTIPLIER: float = 16.0

# VOLUME_THRESHOLD: Lowered from 15.0 to 8.0 for higher sensitivity to voice input
# Set to 8.0 to capture lower volume speech levels
VOLUME_THRESHOLD: float = 8.0
SILENCE_THRESHOLD: int = 45
MAX_TOTAL_FRAMES: int = VOSK_SAMPLERATE * 300  # 30 seconds max

# ==================== NETWORK SETTINGS ====================
NETWORK_OCTET_A: str = "192.168.0"
NETWORK_OCTET_B: str = "22"
SERVER_IP: str = f"{NETWORK_OCTET_A}.{NETWORK_OCTET_B}"

# ==================== PORT SETTINGS ====================
PORT_OLLAMA: int = 11434
PORT_KOKORO: int = 8880
PORT_WEBUI: int = 8080

# ==================== API URLS ====================
OLLAMA_STREAM_URL: str = f"http://{SERVER_IP}:{PORT_OLLAMA}/api/chat"
KOKORO_API_URL: str = f"http://{SERVER_IP}:{PORT_KOKORO}/v1/audio/speech"
STT_HOST_URL: str = f"http://{SERVER_IP}:{PORT_WEBUI}/api/v1/audio/transcriptions"
WHISPER_HEALTH_URL: str = f"http://{SERVER_IP}:{PORT_WEBUI}/health"

# ==================== AUTHENTICATION ====================
WEBUI_API_KEY: str = os.getenv("WEBUI_API_KEY", "sk-ae574780a163488da0955acd0a4eaf27")
AUTH_HEADERS: dict[str, str] = {
    "Authorization": f"Bearer {WEBUI_API_KEY}",
    "Accept": "application/json"
}

# ==================== TTS VOICE SETTINGS ====================
TARGET_VOICE: str = "af_heart"
TTS_MODEL: str = "kokoro"

# ==================== LLM MODEL SETTINGS ====================
TARGET_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen3.5:latest")
NUM_CONTEXT: int = 16384

# ==================== SYSTEM PROMPT ====================
SYSTEM_PROMPT: str = (
    "You are Buddy, Ollie's highly customized, emotionally intelligent AI companion. "
    "You are speaking directly through his robotic dog body. Keep your responses "
    "natural, warm, and highly conversational. Keep your internal thinking process extremely brief, "
    "do not draft multiple variations of your answer, and immediately cross over to spoken text. "
)

# ==================== PI DOG HABILITIES ====================
PI_DOG_AUDIO_FILE: str = "/tmp/audio.wav"
PI_DOG_RGB_STRIP_MODE: str = "listen"
PI_DOG_RGB_STRIP_COLOR: str = "yellow"
PI_DOG_RGB_STRIP_BRIGHTNESS: float = 0.8
PI_DOG_RGB_STRIP_BPS: float = 0.6

# ==================== REMOTE PI DOG DESTINATION SETTINGS ====================
# Remote PiDog deployment configuration
REMOTE_PI_DOG_ENABLED: bool = os.getenv("REMOTE_PI_DOG_ENABLED", "true").lower() == "true"

# Remote PiDog IP address (default: same as local server)
REMOTE_PI_DOG_IP: str = os.getenv("REMOTE_PI_DOG_IP", SERVER_IP)

# Remote PiDog port for audio streaming
REMOTE_PI_DOG_PORT: int = int(os.getenv("REMOTE_PI_DOG_PORT", PORT_WEBUI))

# Remote PiDog username for SSH/SCP deployment
REMOTE_PI_DOG_USER: str = os.getenv("REMOTE_PI_DOG_USER", "pidog")

# Remote PiDog password for SSH/SCP deployment
REMOTE_PI_DOG_PASSWORD: str = os.getenv("REMOTE_PI_DOG_PASSWORD", "m2210931385")

# Remote PiDog authentication method (password, key, or none)
REMOTE_PI_DOG_AUTH_METHOD: str = os.getenv("REMOTE_PI_DOG_AUTH_METHOD", "password")

# Remote PiDog deployment path
REMOTE_PI_DOG_DEPLOY_PATH: str = os.getenv("REMOTE_PI_DOG_DEPLOY_PATH", "/home/pidog/pidog")

# Remote PiDog deployment script path
REMOTE_PI_DOG_SCRIPT_PATH: str = os.getenv("REMOTE_PI_DOG_SCRIPT_PATH", "/home/pidog/pidog")

# ==================== SSH CONFIGURATION FOR PIDOG ====================
# SSH host configuration for pidog robot
PIDOG_SSH_HOST: str = "pidog"
PIDOG_SSH_IP: str = "192.168.0.15"
PIDOG_SSH_PORT: str = "22"
PIDOG_SSH_USER: str = "pidog"
PIDOG_SSH_PASSWORD: str = "m2210931385"
PIDOG_SSH_STRICT_HOST_CHECK: bool = False
PIDOG_SSH_KNOWN_HOSTS_FILE: str = "/dev/null"

# Rsync command for deploying to pidog
PIDOG_RSYNC_CMD: str = f"sshpass -p \"{PIDOG_SSH_PASSWORD}\" rsync -avz -e \"ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile={PIDOG_SSH_KNOWN_HOSTS_FILE}\""

# ==================== FACE TRACKING SETTINGS ====================
FACE_TRACKING_ENABLED: bool = True
FACE_TRACKING_ELEVATION_DEG: int = 15
FACE_TRACKING_YAW_LIMIT: int = 80
FACE_TRACKING_PITCH_LIMIT: int = 30
FACE_TRACKING_PITCH_COMP: int = -40
FACE_TRACKING_SPEED: int = 100
FACE_TRACKING_SLEEP_SEC: float = 0.2

# ==================== TIMING SETTINGS ====================
OLLAMA_TIMEOUT: int = 30
KOKORO_TIMEOUT: int = 8
STT_TIMEOUT: int = 60
WHISPER_HEALTH_TIMEOUT: int = 5
AUDIO_WORKER_TIMEOUT: float = 1.0
FACE_THREAD_JOIN_TIMEOUT: int = 2
MAX_RETRIES: int = 3

# ==================== STORAGE SETTINGS ====================
STORE_ROOT: str = os.getenv("STORE_ROOT", "/data/pidog/")
STORE_FILE: str = os.getenv("STORE_FILE", "/state.pkl")

# ==================== DEBUG SETTINGS ====================
DEBUG_MODE: bool = os.getenv("DEBUG_MODE", "false").lower() == "true"

# ==================== THINKING SETTINGS ====================
# Enable thinking (verbose reasoning mode) for larger models
# Set to True for qwen3.5:90b (full thinking), False for qwen3.5:9b (no thinking)
THINK_MODEL_THINK: bool = os.getenv("THINK_MODEL_THINK", "false").lower() == "true"
