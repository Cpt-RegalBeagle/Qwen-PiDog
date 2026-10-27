#!/usr/bin/env python3
"""Public template — setup.sh copies this to config.py. Edit freely."""
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

# ==================== NETWORK SETTINGS ====================
# IP of the AI server, as seen from the robot
SERVER_IP: str = os.getenv("SERVER_IP", "127.0.0.1")
TUNNEL_IP: str = os.getenv("TUNNEL_IP", "http://localhost")

# ==================== PORT SETTINGS ====================
PORT_LLAMA: int = 11434
PORT_KOKORO: int = 8880
PORT_WEBUI: int = 8089
PORT_XMLRPC: int = 8001

# Validate ports are positive integers
for port_name, port_value in [("LLAMA", PORT_LLAMA), ("KOKORO", PORT_KOKORO), ("WEBUI", PORT_WEBUI), ("XMLRPC", PORT_XMLRPC)]:
    if not isinstance(port_value, int) or port_value <= 0:
        log_config_error(f"{port_name} port must be a positive integer, got {port_value}", "ERROR")

# ==================== API URLS ====================
LLAMA_STREAM_URL: str = f"http://{SERVER_IP}:{PORT_LLAMA}/v1/chat/completions"
KOKORO_API_URL: str = f"http://{SERVER_IP}:{PORT_KOKORO}/v1/audio/speech"
STT_HOST_URL: str = f"http://{SERVER_IP}:{PORT_WEBUI}/api/v1/audio/transcriptions"

# ==================== AUTHENTICATION ====================
# Loaded dynamically from environment or fallback placeholder
WEBUI_API_KEY: str = os.getenv("WEBUI_API_KEY", "PLACEHOLDER_KEY")

if WEBUI_API_KEY == "PLACEHOLDER_KEY":
    log_config_error("WEBUI_API_KEY is set to placeholder. Ensure .env file contains valid key", "WARNING")

# ==================== TTS VOICE SETTINGS ====================
TTS_VOICE: str = os.getenv("TTS_VOICE", "af_heart")
TTS_MODEL: str = os.getenv("TTS_MODEL", "kokoro")

if not TTS_VOICE or TTS_VOICE.strip() == "":
    log_config_error("TTS_VOICE is empty. Defaulting to 'af_heart'", "ERROR")
    TTS_VOICE = "af_heart"

TARGET_VOICE: str = TTS_VOICE

# ==================== LLM MODEL SETTINGS ====================
TARGET_MODEL: str = os.getenv("LLAMA_MODEL", "qwen3.5-4b")

if not TARGET_MODEL or TARGET_MODEL.strip() == "":
    log_config_error("TARGET_MODEL is empty. Defaulting to 'qwen3.5:latest'", "ERROR")
    TARGET_MODEL = "qwen3.5:latest"

LLM_LOAD_TIMEOUT: float = 120.0
LLM_LOAD_POLL_INTERVAL: float = 2.0
ROUTER_READY_STATES: tuple[str, ...] = ("loaded", "sleeping")
ROUTER_IN_PROGRESS_STATES: tuple[str, ...] = ("loading", "downloading", "downloaded")

# ==================== SYSTEM PROMPT ====================
# customize me
SYSTEM_PROMPT: str = (
    "You are a friendly, upbeat robot buddy for a young person. "
    "Keep every reply short: at most 50 words, plain text, no markdown. "
    "If you get an action command, the robot is already doing it - reply with 3-5 words of hype only."
    )

# ==================== PI DOG ABILITIES ====================
PI_DOG_AUDIO_FILE: str = "/tmp/audio.wav"
SELF_TEST_AUDIO_PATH: str = "/tmp/pidog_test_audio.wav"

# ==================== TIMING SETTINGS ====================
def _env_int(name: str, default: int) -> int:
    """Read an env var as a positive int, falling back to default."""
    raw = os.getenv(name, str(default))
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        log_config_error(f"{name} must be a positive integer, got '{raw}'. Defaulting to {default}", "ERROR")
        return default
    if value <= 0:
        log_config_error(f"{name} must be a positive integer, got {value}. Defaulting to {default}", "ERROR")
        return default
    return value

LLAMA_TIMEOUT: int = _env_int("LLAMA_TIMEOUT", 30)

# ==================== PLAYBACK END-DETECTION ====================
# TTS playback-end detection, all values in seconds.
PLAYBACK_POLL_INTERVAL = 0.5        # is_music_playing() poll cadence
PLAYBACK_SETTLE = 0.2               # echo/reverb settle after playback ends
PLAYBACK_WATCHDOG_MARGIN = 3.0      # extra bound beyond expected duration
PLAYBACK_FALLBACK_DURATION = 9.5    # assumed duration if the WAV parse fails

# ==================== ACTION ENGINE SETTINGS ====================
COOLDOWN_SECONDS: float = 2.0            # min gap between same-action firings
MAX_ACTIONS_PER_MESSAGE: int = 1         # only fire the first match per text blob
ENABLED: bool = True                     # master on/off switch
RETURN_TO_SIT_AFTER_ACTION: bool = True  # engine fires action('sit') after each personality action

# ==================== ROOMMAP SETTINGS ====================
ROOMMAP_DIR: str = os.path.expanduser("~/roommap_data")
ROOMMAP_TRIGGER_FILE: str = os.path.join(ROOMMAP_DIR, "roommap.trigger")
ROOMMAP_FOCUS_FILE: str = os.path.join(ROOMMAP_DIR, "roommap.focus")
ROOMMAP_LATEST_FILE: str = os.path.join(ROOMMAP_DIR, "roommap_latest.json")
ROOMMAP_YAW_STEP_DEG: int = 10
ROOMMAP_MIN_CLEAR_CM: int = 30
ROOMMAP_MAX_RANGE_CM: int = 150
ROOMMAP_STEP_CM: int = 30
ROOMMAP_MAX_CLUSTERS: int = 6
ROOMMAP_MAX_DURATION_S: int = 300

