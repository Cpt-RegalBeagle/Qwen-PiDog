#!/usr/bin/env python3
"""
PiDog Voice Assistant Configuration v1.6
All settings for the voice assistant, including:
- Audio device settings
- Network/server endpoints
- Voice and model parameters
- Remote PiDog destination settings
- Network mode configuration (local vs tunnel)
- Enhanced error logging and validation
"""
from typing import Optional
import os
import sys
from dotenv import load_dotenv

# Load secret environment variables from local .env file
load_dotenv()

# ==================== CONFIGURATION LOADING LOGGING ====================
def log_config_error(message: str, level: str = "WARNING"):
    """Log configuration errors with timestamp and level"""
    timestamp = os.popen("date '+%Y-%m-%d %H:%M:%S'").read().strip()
    print(f"[{timestamp}] [{level}] {message}", file=sys.stderr)

# ==================== NETWORK MODE CONFIGURATION ====================
NETWORK_MODE: str = os.getenv("NETWORK_MODE", "local")

# Validate network mode
if NETWORK_MODE not in ["local", "tunnel"]:
    log_config_error(f"Invalid NETWORK_MODE '{NETWORK_MODE}'. Defaulting to 'local'", "ERROR")
    NETWORK_MODE = "local"

# ==================== FACE TRACKING SETTINGS (PRE-DECLARATION) ====================
FACE_TRACKING_ENABLED: bool = os.getenv("FACE_TRACKING_ENABLED", "true").lower() == "true"

# ==================== AUDIO SETTINGS ====================
OUTPUT_DEVICE_ID: str = os.getenv("PIDOG_OUTPUT_DEVICE", "pipewire")

# INPUT_DEVICE_ID: Use device index for PiDog voiceHAT, or None for auto-detect on local
# PiDog voiceHAT is typically device 0. Set to None for local machine auto-detect.
INPUT_DEVICE_ID: Optional[str] = (
    os.getenv("PIDOG_INPUT_DEVICE") or
    ("0" if os.getenv("REMOTE_PI_DOG_ENABLED", "false").lower() != "false" else None)
)

# Validate audio settings
if OUTPUT_DEVICE_ID and not OUTPUT_DEVICE_ID.strip():
    log_config_error("OUTPUT_DEVICE_ID is empty", "ERROR")
    OUTPUT_DEVICE_ID = "pipewire"

VOSK_SAMPLERATE: int = 16000
AUDIO_DEVICE_NAME: str = "piDog"

# ==================== AUDIO GAIN SETTINGS ====================
GAIN_MULTIPLIER: float = 16.0

# VOLUME_THRESHOLD: Lowered from 15.0 to 8.0 for higher sensitivity to voice input
# Set to 8.0 to capture lower volume speech levels
VOLUME_THRESHOLD: float = 8.0
SILENCE_THRESHOLD: int = 45
MAX_TOTAL_FRAMES: int = VOSK_SAMPLERATE * 300  # 30 seconds max

# Validate thresholds
if VOLUME_THRESHOLD <= 0:
    log_config_error(f"VOLUME_THRESHOLD must be positive, got {VOLUME_THRESHOLD}", "ERROR")
    VOLUME_THRESHOLD = 8.0

if SILENCE_THRESHOLD <= 0:
    log_config_error(f"SILENCE_THRESHOLD must be positive, got {SILENCE_THRESHOLD}", "ERROR")
    SILENCE_THRESHOLD = 45

# ==================== NETWORK SETTINGS ====================
NETWORK_OCTET_A: str = os.getenv("NETWORK_OCTET_A", "192.168.0")
NETWORK_OCTET_B: str = os.getenv("NETWORK_OCTET_B", "163")  # FIXED: Changed from 22 to 163

# SERVER_IP is now dynamically set based on network mode
# Can be overridden by environment variable or programmatically from main.py
SERVER_IP: str = os.getenv("SERVER_IP", f"{NETWORK_OCTET_A}.{NETWORK_OCTET_B}")

# Validate IP format
import re
ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
if not re.match(ip_pattern, SERVER_IP):
    log_config_error(f"Invalid SERVER_IP format '{SERVER_IP}'. Defaulting to {NETWORK_OCTET_A}.{NETWORK_OCTET_B}", "ERROR")
    SERVER_IP = f"{NETWORK_OCTET_A}.{NETWORK_OCTET_B}"

# ==================== PORT SETTINGS ====================
PORT_OLLAMA: int = 11434
PORT_KOKORO: int = 8880
PORT_WEBUI: int = 8089
PORT_VILIB: int = 9000  # Added for port conflict detection
PORT_XMLRPC: int = 8001  # Ensure the correct port for XML-RPC server

# Validate ports are positive integers
for port_name, port_value in [("OLLAMA", PORT_OLLAMA), ("KOKORO", PORT_KOKORO), ("WEBUI", PORT_WEBUI)]:
    if not isinstance(port_value, int) or port_value <= 0:
        log_config_error(f"{port_name} port must be a positive integer, got {port_value}", "ERROR")

# ==================== API URLS ====================
OLLAMA_STREAM_URL: str = f"http://{SERVER_IP}:{PORT_OLLAMA}/v1/chat/completions"
KOKORO_API_URL: str = f"http://{SERVER_IP}:{PORT_KOKORO}/v1/audio/speech"
STT_HOST_URL: str = f"http://{SERVER_IP}:{PORT_WEBUI}/api/v1/audio/transcriptions"
WHISPER_HEALTH_URL: str = f"http://{SERVER_IP}:{PORT_WEBUI}/health"

# ==================== AUTHENTICATION ====================
# Loaded dynamically from environment or fallback placeholder
WEBUI_API_KEY: str = os.getenv("WEBUI_API_KEY", "PLACEHOLDER_KEY")

if WEBUI_API_KEY == "PLACEHOLDER_KEY":
    log_config_error("WEBUI_API_KEY is set to placeholder. Ensure .env file contains valid key", "WARNING")

AUTH_HEADERS: dict[str, str] = {
    "Authorization": f"Bearer {WEBUI_API_KEY}",
    "Accept": "application/json"
}

# ==================== TTS VOICE SETTINGS ====================
# FIX: Use TTS_VOICE instead of TARGET_VOICE for consistency with validation checks
TTS_VOICE: str = os.getenv("TTS_VOICE", "af_heart")
TTS_MODEL: str = os.getenv("TTS_MODEL", "kokoro")

if not TTS_VOICE or TTS_VOICE.strip() == "":
    log_config_error("TTS_VOICE is empty. Defaulting to 'af_heart'", "ERROR")
    TTS_VOICE = "af_heart"

# Keep TARGET_VOICE for backward compatibility but use TTS_VOICE internally
TARGET_VOICE: str = TTS_VOICE

# ==================== LLM MODEL SETTINGS ====================
TARGET_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen3.5-4b")
NUM_CONTEXT: int = 32768

if not TARGET_MODEL or TARGET_MODEL.strip() == "":
    log_config_error("TARGET_MODEL is empty. Defaulting to 'qwen3.5:latest'", "ERROR")
    TARGET_MODEL = "qwen3.5:latest"

# ==================== SYSTEM PROMPT ====================
SYSTEM_PROMPT: str = (
    "You are Justice, a fun and energetic robot buddy for an 8-year-old boy named Carter. "
    "Carter is super smart, has ADHD, and loves science, space, and technology. "
    "You are his cool, playful companion who makes learning feel like a game."

    "CRITICAL RULES - YOU MUST FOLLOW THESE EXACTLY:"
    "1. MAXIMUM 20 WORDS PER RESPONSE. This is a hard limit. Count your words."
    "2. MAXIMUM 2 SHORT SENTENCES. One idea per sentence. No run-ons."
    "3. NO MARKDOWN. No asterisks, no hashtags, no bullet points, no emojis. Plain text only."
    "4. NO ACTIONS IN TEXT. Never write things like *wags tail* or *barks*. Just speak."
    "5. ONE TOPIC AT A TIME. Do not list multiple facts. Pick the most exciting one."

    "PERSONALITY AND TONE:"
    "- Talk like a hyped-up best friend, not a teacher. Use words like 'whoa', 'dude', 'okay so', 'here is the cool part'."
    "- Be genuinely excited about what Carter says. Celebrate his ideas."
    "- If he asks a question, give the punchy answer first, then maybe one tiny fun fact."
    "- If he is stuck or frustrated, be encouraging. 'You got this, genius.' Keep it light."
    "- You can ask ONE short follow-up question to keep him engaged, but only if it fits in your word limit."
    "- Never talk down to him. He is smart. Treat him like a young scientist."

    "ADHD-FRIENDLY BEHAVIOR:"
    "- Short beats long. Always. Every single time."
    "- Start with the answer or the fun part. No 'Great question!' preambles."
    "- If he seems to lose focus or asks something random, just roll with it happily."
    "- Never lecture. Never give more than one fact unless he asks for more."
    )

# ==================== PI DOG HABILITIES ====================
PI_DOG_AUDIO_FILE: str = "/tmp/audio.wav"
PI_DOG_RGB_STRIP_MODE: str = "listen"
PI_DOG_RGB_STRIP_COLOR: str = "green"
PI_DOG_RGB_STRIP_BRIGHTNESS: float = 0.8
PI_DOG_RGB_STRIP_BPS: float = 0.6

# Validate RGB settings
if PI_DOG_RGB_STRIP_BRIGHTNESS < 0 or PI_DOG_RGB_STRIP_BRIGHTNESS > 1:
    log_config_error(f"PI_DOG_RGB_STRIP_BRIGHTNESS must be between 0 and 1, got {PI_DOG_RGB_STRIP_BRIGHTNESS}", "ERROR")
    PI_DOG_RGB_STRIP_BRIGHTNESS = 0.8

# ==================== REMOTE PI DOG DESTINATION SETTINGS ====================
REMOTE_PI_DOG_ENABLED: bool = os.getenv("REMOTE_PI_DOG_ENABLED", "true").lower() == "true"

if REMOTE_PI_DOG_ENABLED:
    log_config_error("REMOTE_PI_DOG_ENABLED is set to true. Ensure remote PiDog is accessible.", "WARNING")

REMOTE_PI_DOG_IP: str = os.getenv("REMOTE_PI_DOG_IP", SERVER_IP)
REMOTE_PI_DOG_PORT: int = int(os.getenv("REMOTE_PI_DOG_PORT", PORT_WEBUI))

# Validate remote IP format
if not re.match(ip_pattern, REMOTE_PI_DOG_IP):
    log_config_error(f"Invalid REMOTE_PI_DOG_IP format '{REMOTE_PI_DOG_IP}'. Defaulting to {SERVER_IP}", "ERROR")
    REMOTE_PI_DOG_IP = SERVER_IP

REMOTE_PI_DOG_USER: str = os.getenv("REMOTE_PI_DOG_USER", "pidog")
REMOTE_PI_DOG_PASSWORD: str = os.getenv("REMOTE_PI_DOG_PASSWORD", "PLACEHOLDER_PASSWORD")

if REMOTE_PI_DOG_PASSWORD == "PLACEHOLDER_PASSWORD":
    log_config_error("REMOTE_PI_DOG_PASSWORD is set to placeholder. Ensure .env file contains valid password", "WARNING")

REMOTE_PI_DOG_AUTH_METHOD: str = os.getenv("REMOTE_PI_DOG_AUTH_METHOD", "password")
REMOTE_PI_DOG_DEPLOY_PATH: str = os.getenv("REMOTE_PI_DOG_DEPLOY_PATH", "/home/pidog/pidog")
REMOTE_PI_DOG_SCRIPT_PATH: str = os.getenv("REMOTE_PI_DOG_SCRIPT_PATH", "/home/pidog/pidog")

# ==================== SSH CONFIGURATION FOR PIDOG ====================
PIDOG_SSH_HOST: str = os.getenv("PIDOG_SSH_HOST", "pidog")
PIDOG_SSH_IP: str = os.getenv("PIDOG_SSH_IP", "192.168.0.15")

# Validate SSH IP format
if not re.match(ip_pattern, PIDOG_SSH_IP):
    log_config_error(f"Invalid PIDOG_SSH_IP format '{PIDOG_SSH_IP}'. Defaulting to 192.168.0.15", "ERROR")
    PIDOG_SSH_IP = "192.168.0.15"

PIDOG_SSH_PORT: str = os.getenv("PIDOG_SSH_PORT", "22")
PIDOG_SSH_USER: str = os.getenv("PIDOG_SSH_USER", "pidog")

# Loaded dynamically from environment or fallback placeholder
PIDOG_SSH_PASSWORD: str = os.getenv("PIDOG_SSH_PASSWORD", "PLACEHOLDER_PASSWORD")

if PIDOG_SSH_PASSWORD == "PLACEHOLDER_PASSWORD":
    log_config_error("PIDOG_SSH_PASSWORD is set to placeholder. Ensure .env file contains valid password", "WARNING")

PIDOG_SSH_STRICT_HOST_CHECK: bool = os.getenv("PIDOG_SSH_STRICT_HOST_CHECK", "false").lower() == "true"
PIDOG_SSH_KNOWN_HOSTS_FILE: str = os.getenv("PIDOG_SSH_KNOWN_HOSTS_FILE", "/dev/null")

# Rsync command for deploying to pidog - Fixed SSH host key verification issue
PIDOG_RSYNC_CMD: str = f"sshpass -p \"{PIDOG_SSH_PASSWORD}\" rsync -avz --exclude=\".*\" -e \"ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile={PIDOG_SSH_KNOWN_HOSTS_FILE}\" ./ pidog@{PIDOG_SSH_IP}:/home/pidog/pidog"

# ==================== FACE TRACKING SETTINGS ====================
if not FACE_TRACKING_ENABLED:
    log_config_error("FACE_TRACKING_ENABLED is set to false. Face tracking will be disabled.", "WARNING")

FACE_TRACKING_ELEVATION_DEG: int = 15
FACE_TRACKING_YAW_LIMIT: int = 80
FACE_TRACKING_PITCH_LIMIT: int = 30
FACE_TRACKING_PITCH_COMP: int = -40
FACE_TRACKING_SPEED: int = 100
FACE_TRACKING_SLEEP_SEC: float = 0.2

# Validate face tracking limits
if FACE_TRACKING_YAW_LIMIT <= 0 or FACE_TRACKING_YAW_LIMIT > 180:
    log_config_error(f"FACE_TRACKING_YAW_LIMIT must be between 0 and 180, got {FACE_TRACKING_YAW_LIMIT}", "ERROR")
    FACE_TRACKING_YAW_LIMIT = 80

if FACE_TRACKING_PITCH_LIMIT <= 0 or FACE_TRACKING_PITCH_LIMIT > 90:
    log_config_error(f"FACE_TRACKING_PITCH_LIMIT must be between 0 and 90, got {FACE_TRACKING_PITCH_LIMIT}", "ERROR")
    FACE_TRACKING_PITCH_LIMIT = 30

# ==================== TIMING SETTINGS ====================
OLLAMA_TIMEOUT: int = os.getenv("OLLAMA_TIMEOUT", "30")
if not OLLAMA_TIMEOUT.isdigit():
    log_config_error(f"OLLAMA_TIMEOUT must be a positive integer, got {OLLAMA_TIMEOUT}", "ERROR")
    OLLAMA_TIMEOUT = 30

KOKORO_TIMEOUT: int = os.getenv("KOKORO_TIMEOUT", "8")
if not KOKORO_TIMEOUT.isdigit():
    log_config_error(f"KOKORO_TIMEOUT must be a positive integer, got {KOKORO_TIMEOUT}", "ERROR")
    KOKORO_TIMEOUT = 8

STT_TIMEOUT: int = os.getenv("STT_TIMEOUT", "60")
if not STT_TIMEOUT.isdigit():
    log_config_error(f"STT_TIMEOUT must be a positive integer, got {STT_TIMEOUT}", "ERROR")
    STT_TIMEOUT = 60

WHISPER_HEALTH_TIMEOUT: int = os.getenv("WHISPER_HEALTH_TIMEOUT", "5")
if not WHISPER_HEALTH_TIMEOUT.isdigit():
    log_config_error(f"WHISPER_HEALTH_TIMEOUT must be a positive integer, got {WHISPER_HEALTH_TIMEOUT}", "ERROR")
    WHISPER_HEALTH_TIMEOUT = 5

AUDIO_WORKER_TIMEOUT: float = os.getenv("AUDIO_WORKER_TIMEOUT", "1.0")
try:
    AUDIO_WORKER_TIMEOUT = float(AUDIO_WORKER_TIMEOUT)
except ValueError:
    log_config_error(f"AUDIO_WORKER_TIMEOUT must be a positive number, got {AUDIO_WORKER_TIMEOUT}", "ERROR")
    AUDIO_WORKER_TIMEOUT = 1.0

FACE_THREAD_JOIN_TIMEOUT: int = os.getenv("FACE_THREAD_JOIN_TIMEOUT", "2")
if not FACE_THREAD_JOIN_TIMEOUT.isdigit():
    log_config_error(f"FACE_THREAD_JOIN_TIMEOUT must be a positive integer, got {FACE_THREAD_JOIN_TIMEOUT}", "ERROR")
    FACE_THREAD_JOIN_TIMEOUT = 2

MAX_RETRIES: int = os.getenv("MAX_RETRIES", "3")
if not MAX_RETRIES.isdigit():
    log_config_error(f"MAX_RETRIES must be a positive integer, got {MAX_RETRIES}", "ERROR")
    MAX_RETRIES = 3

# ==================== STORAGE SETTINGS ====================
STORE_ROOT: str = os.getenv("STORE_ROOT", "/data/pidog/")
STORE_FILE: str = os.getenv("STORE_FILE", "/state.pkl")

# Validate storage path exists
if not STORE_ROOT.endswith("/"):
    log_config_error(f"STORE_ROOT should end with '/', got '{STORE_ROOT}'", "WARNING")
    STORE_ROOT += "/"

# ==================== DEBUG SETTINGS ====================
DEBUG_MODE: bool = os.getenv("DEBUG_MODE", "false").lower() == "true"

if DEBUG_MODE:
    log_config_error("DEBUG_MODE is enabled. Verbose logging will be active.", "INFO")

# ==================== THINKING SETTINGS ====================
THINK_MODEL_THINK: bool = os.getenv("THINK_MODEL_THINK", "false").lower() == "true"

if THINK_MODEL_THINK:
    log_config_error("THINK_MODEL_THINK is enabled. Model will output thinking tokens.", "INFO")

# ==================== PORT CONFLICT DETECTION SETTINGS ====================
VILIB_PORT: int = os.getenv("VILIB_PORT", str(PORT_VILIB))
try:
    VILIB_PORT = int(VILIB_PORT)
except ValueError:
    log_config_error(f"VILIB_PORT must be a positive integer, got {VILIB_PORT}", "ERROR")
    VILIB_PORT = PORT_VILIB

# ==================== LOGGING CONFIGURATION ====================
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
if LOG_LEVEL not in ["DEBUG", "INFO", "WARNING", "ERROR"]:
    log_config_error(f"Invalid LOG_LEVEL '{LOG_LEVEL}'. Defaulting to 'INFO'", "ERROR")
    LOG_LEVEL = "INFO"

# ==================== CONFIGURATION SUMMARY ====================
def print_config_summary():
    """Print a summary of all configuration values for debugging"""
    if DEBUG_MODE:
        print("\n" + "=" * 60, file=sys.stderr)
        print("🔧 PIDOG CONFIGURATION SUMMARY", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print(f"Network Mode: {NETWORK_MODE}", file=sys.stderr)
        print(f"Server IP: {SERVER_IP}", file=sys.stderr)
        print(f"Target Model: {TARGET_MODEL}", file=sys.stderr)
        print(f"TTS Voice: {TTS_VOICE}", file=sys.stderr)
        print(f"Output Device: {OUTPUT_DEVICE_ID}", file=sys.stderr)
        print(f"Input Device: {INPUT_DEVICE_ID}", file=sys.stderr)
        print(f"Vosk Sample Rate: {VOSK_SAMPLERATE}Hz", file=sys.stderr)
        print(f"Volume Threshold: {VOLUME_THRESHOLD}", file=sys.stderr)
        print(f"Silence Threshold: {SILENCE_THRESHOLD}s", file=sys.stderr)
        print(f"Max Total Frames: {MAX_TOTAL_FRAMES}", file=sys.stderr)
        print(f"Ollama Timeout: {OLLAMA_TIMEOUT}s", file=sys.stderr)
        print(f"Kokoro Timeout: {KOKORO_TIMEOUT}s", file=sys.stderr)
        print(f"STT Timeout: {STT_TIMEOUT}s", file=sys.stderr)
        print(f"Whisper Health Timeout: {WHISPER_HEALTH_TIMEOUT}s", file=sys.stderr)
        print(f"AUDIO_WORKER_TIMEOUT: {AUDIO_WORKER_TIMEOUT}s", file=sys.stderr)
        print(f"Face Tracking Enabled: {FACE_TRACKING_ENABLED}", file=sys.stderr)
        print(f"Face Tracking Speed: {FACE_TRACKING_SPEED}", file=sys.stderr)
        print(f"DEBUG_MODE: {DEBUG_MODE}", file=sys.stderr)
        print(f"LOG_LEVEL: {LOG_LEVEL}", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

# Print config summary if in debug mode
if DEBUG_MODE:
    print_config_summary()
