#!/usr/bin/env python3
"""
PIDOG Voice Assistant Interface
Direct local hardware deployment - no remote SSH deployment.
Uses config.py for all settings including hardware configuration.
"""
import time
import os
import sys
import threading
import queue
import requests
import json
import signal
import sounddevice as sd
import io
import soundfile as sf
import numpy as np
from typing import Optional

# Type hints
from vilib import Vilib
from pidog import Pidog

# Import configuration
import config

# Import hardware cleanup utility
from cleanup_hardware import cleanup_hardware


print("Initializing Unlocked PiDog Voice Assistant Interface...")
dog: Optional[Pidog] = None
dog = Pidog()
print("Parking PiDog safely in stationary PiDog Voice Assistant mode...")
time.sleep(1)

# ==================== LOAD CONFIGURATION ====================
# All settings loaded from config.py - can override with environment variables
print(f"🔧 Using server: {config.SERVER_IP}")
print(f"🔧 Using model: {config.TARGET_MODEL}")
print(f"📡 Remote PiDog enabled: {config.REMOTE_PI_DOG_ENABLED}")
if config.REMOTE_PI_DOG_ENABLED:
    print(f"📡 Remote PiDog IP: {config.REMOTE_PI_DOG_IP}:{config.REMOTE_PI_DOG_PORT}")
    print(f"🔑 Remote PiDog user: {config.REMOTE_PI_DOG_USER}")

# Audio device configuration
OUTPUT_DEVICE_ID: str = config.OUTPUT_DEVICE_ID
INPUT_DEVICE_ID: Optional[str] = config.INPUT_DEVICE_ID
VOSK_SAMPLERATE: int = config.VOSK_SAMPLERATE
sd.default.device = (None, OUTPUT_DEVICE_ID)

# Network configuration
OLLAMA_STREAM_URL: str = config.OLLAMA_STREAM_URL
KOKORO_API_URL: str = config.KOKORO_API_URL
STT_HOST_URL: str = config.STT_HOST_URL
WHISPER_HEALTH_URL: str = config.WHISPER_HEALTH_URL
WEBUI_API_KEY: str = config.WEBUI_API_KEY
AUTH_HEADERS: dict[str, str] = config.AUTH_HEADERS
THINK_MODEL_THINK: bool = config.THINK_MODEL_THINK

# Model and voice configuration
TARGET_MODEL: str = config.TARGET_MODEL
TARGET_VOICE: str = config.TARGET_VOICE
SYSTEM_PROMPT: str = config.SYSTEM_PROMPT

# Constants derived from config
MAX_TOTAL_FRAMES: int = config.MAX_TOTAL_FRAMES
SILENCE_THRESHOLD: int = config.SILENCE_THRESHOLD
GAIN_MULTIPLIER: float = config.GAIN_MULTIPLIER
VOLUME_THRESHOLD: float = config.VOLUME_THRESHOLD
HEAD_MOVE_SPEED: int = config.FACE_TRACKING_SPEED


# ==================== GLOBAL VARIABLES ====================
audio_queue: queue.Queue = queue.Queue()
tts_lock: threading.Lock = threading.Lock()
face_freeze: bool = False
is_speaking: bool = False
is_exiting: bool = False  # Flag for DEBUG_MODE clean exit

# ==================== OLLAMA QUERY FUNCTION ====================
def query_pidog_stream(user_prompt: str) -> None:
    """Send query to Ollama with streaming"""
    # Use thinking mode only for large models (qwen3.5:90b+), disable for qwen3.5:9b
    think_option: bool = THINK_MODEL_THINK
    payload = {
        "model": TARGET_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        "stream": True,
        "think": think_option,
        "options": {
            "num_ctx": 16384,
        }
    }
    print(f"📡 Querying Ollama: {TARGET_MODEL} (thinking: {think_option})...", flush=True)
    try:
        response = requests.post(OLLAMA_STREAM_URL, json=payload, stream=True, timeout=config.OLLAMA_TIMEOUT)
        if response.status_code != 200:
            print(f"❌ Server Engine Error.")
            return
        current_sentence: str = ""
        is_thinking: bool = False
        first_spoken_token: bool = True
        for line in response.iter_lines():
            if line:
                decoded_line: dict = json.loads(line.decode('utf-8'))
                msg_data: dict = decoded_line.get('message', {})
                thinking_token: str = msg_data.get('thinking', '')
                if thinking_token:
                    if not is_thinking:
                        print("\n🤔 [PiDog's Thoughts]: ", end="", flush=True)
                        is_thinking = True
                    print(thinking_token, end="", flush=True)
                    dog.rgb_strip.set_mode('pulse', color='pink', bps=1.0)
                    continue
                content_token: str = msg_data.get('content', '')
                if content_token:
                    if is_thinking or first_spoken_token:
                        print("\n\nPiDog: ", end="", flush=True)
                        is_thinking = False
                        first_spoken_token = False
                    current_sentence += content_token
                    print(content_token, end="", flush=True)
                    if content_token in ['.', '!', '?', '\n', ','] and len(current_sentence) > 15:
                        audio_queue.put(current_sentence)
                        current_sentence = ""
        if current_sentence.strip():
            audio_queue.put(current_sentence)
    except requests.exceptions.ConnectionError as e:
        print(f"\n❌ Intranet Connection Dropped: {e}")
    except requests.exceptions.Timeout:
        print(f"\n❌ Ollama request timed out")
    except Exception as e:
        print(f"\n❌ Ollama error: {e}")


# ==================== AUDIO WORKER THREAD ====================
def audio_worker_thread() -> None:
    """Process audio queue for TTS"""
    global is_speaking
    with tts_lock:
        is_speaking = False
    while True:
        try:
            # Use timeout to prevent blocking
            text_chunk = audio_queue.get(timeout=config.AUDIO_WORKER_TIMEOUT)
            audio_queue.task_done()
        except queue.Empty:
            continue

        # Exit condition: empty queue and no pending work
        try:
            if audio_queue.empty():
                break
        except Exception:
            break

        try:
            text_chunk = text_chunk.strip() if text_chunk else ""
            if not text_chunk or len(text_chunk) < 2:
                continue
        except Exception:
            break

        payload = {
            "model": config.TTS_MODEL,
            "input": text_chunk,
            "voice": TARGET_VOICE,
            "response_format": "wav"
        }
        try:
            response = requests.post(KOKORO_API_URL, json=payload, timeout=config.KOKORO_TIMEOUT)
            if response.status_code == 200:
                audio_data, samplerate = sf.read(io.BytesIO(response.content))
                with tts_lock:
                    is_speaking = True
                    face_freeze = True
                dog.rgb_strip.set_mode('breath', color='pink', bps=2.5, brightness=0.8)
                if hasattr(dog, 'sound_direction'):
                    try:
                        dog.sound_direction.disable()
                    except Exception:
                        pass
                sd.play(audio_data, samplerate, device=OUTPUT_DEVICE_ID)
                sd.wait()
                with tts_lock:
                    is_speaking = False
                    face_freeze = False
                dog.rgb_strip.set_mode('listen', color='yellow', bps=0.6, brightness=0.8)
                if hasattr(dog, 'sound_direction'):
                    try:
                        dog.sound_direction.enable()
                    except Exception:
                        pass
            else:
                print(f"\n⚠ TTS error (status={response.status_code})")
        except requests.exceptions.ConnectionError as e:
            print(f"\n⚠ TTS connection error: {e}")
        except requests.exceptions.Timeout:
            print(f"\n⚠ TTS timeout")
        except Exception as e:
            print(f"\n⚠ TTS error: {e}")
        finally:
            audio_queue.task_done()


# Start audio worker thread
worker: threading.Thread = threading.Thread(target=audio_worker_thread, daemon=True)
worker.start()


# ==================== STT FUNCTIONS ====================
def check_whisper_health() -> bool:
    """Check if Whisper API is responding"""
    try:
        response = requests.get(WHISPER_HEALTH_URL, timeout=config.WHISPER_HEALTH_TIMEOUT)
        return response.status_code == 200
    except Exception:
        return False


def transcribe_audio(audio_data: np.ndarray) -> Optional[str]:
    """Transcribe audio with retry logic and fallback"""
    max_retries: int = config.MAX_RETRIES
    retry_count: int = 0
    timeout: int = config.STT_TIMEOUT

    while retry_count < max_retries:
        try:
            sf.write("/tmp/speech.wav", audio_data, VOSK_SAMPLERATE)
            with open("/tmp/speech.wav", 'rb') as f:
                audio_binary = f.read()
            files = {
                'file': ('speech.wav', io.BytesIO(audio_binary), 'audio/wav')
            }
            stt_response = requests.post(
                STT_HOST_URL,
                headers=AUTH_HEADERS,
                files=files,
                timeout=timeout
            )
            if stt_response.status_code == 200:
                text = stt_response.json().get("text", "").strip()
                return text if text and len(text) > 1 else None
            elif stt_response.status_code == 401:
                print(f"\n⚠ Authentication failed")
                return None
            else:
                print(f"\n⚠ STT Backend Error: {stt_response.status_code}")
                return None
        except Exception as e:
            retry_count += 1
            if retry_count < max_retries:
                wait_time = 2 ** retry_count
                print(f"\n⚠ Retrying STT in {wait_time}s... (Attempt {retry_count}/{max_retries})")
                time.sleep(wait_time)
            else:
                print(f"\n⚠ STT API failed after {max_retries} retries")
                return None
    return None


# ==================== FACE TRACKING THREAD ====================
def face_tracking_thread() -> None:
    """Run face tracking code in a thread"""
    global face_freeze
    print("🎥 Starting face tracking in thread...", flush=True)

    try:
        # Camera Configuration
        Vilib.camera_start(vflip=False, hflip=False)
        Vilib.display(local=False, web=True)
        Vilib.face_detect_switch(True)
        time.sleep(0.2)
        print('[System] Elevated Look Up Tracking Mode Active!', flush=True)

        # Baseline Variables
        yaw: float = 0
        roll: float = 0
        pitch: float = config.FACE_TRACKING_ELEVATION_DEG
        direction: float = 0
        people_count: int = 0

        # Initial Stationary Stance
        if dog:
            dog.do_action('sit', speed=50)
            dog.head_move([[yaw, 0, pitch]], pitch_comp=config.FACE_TRACKING_PITCH_COMP, immediately=True, speed=80)
            dog.wait_all_done()
            time.sleep(0.5)
            if dog.ears and dog.ears.isdetected():
                direction = dog.ears.read()
            people_count = 0

        # Core Execution Loop
        print(f"🎮 DEBUG_MODE: {config.DEBUG_MODE}", file=sys.stderr, flush=True)
        while True:
            # Check for Ctrl+C in DEBUG mode
            if config.DEBUG_MODE:
                if is_keyboard_interrupt:
                    print(f"\n⚠ DEBUG_MODE: Interrupt detected, exiting cleanly...")
                    break
            # Freeze face tracking during TTS
            if face_freeze:
                print(f"🔒 Face tracking frozen during TTS...", end='\r', flush=True)
                if dog and hasattr(dog, 'head_move'):
                    dog.head_move([[yaw, 0, pitch]], pitch_comp=config.FACE_TRACKING_PITCH_COMP, immediately=True, speed=80)
                time.sleep(0.1)
                continue

            # LED State Management
            if is_speaking:
                dog.rgb_strip.set_mode('breath', 'yellow', bps=0.6, brightness=0.8)
            else:
                dog.rgb_strip.set_mode('breath', 'pink', bps=1)

            # Sound Direction Processing
            if dog and dog.ears and dog.ears.isdetected():
                direction = dog.ears.read()
                pitch = config.FACE_TRACKING_ELEVATION_DEG  # Reset pitch to elevated view
                direction_delta = direction
                if 0 < direction_delta < 160:
                    yaw = -direction_delta
                    if yaw < config.FACE_TRACKING_YAW_LIMIT:
                        yaw = config.FACE_TRACKING_YAW_LIMIT
                elif 200 < direction_delta < 360:
                    yaw = 360 - direction_delta
                    if yaw > config.FACE_TRACKING_YAW_LIMIT:
                        yaw = config.FACE_TRACKING_YAW_LIMIT
                # Snap head to voice origin vector
                if dog and hasattr(dog, 'head_move'):
                    dog.head_move([[yaw, 0, pitch]], pitch_comp=config.FACE_TRACKING_PITCH_COMP, immediately=True, speed=85)
                if dog and hasattr(dog, 'wait_head_done'):
                    dog.wait_head_done()

                # Reduce sleep to prevent stutter - only need a small delay
                time.sleep(0.2)

            # Vision Proportional Calculations
            try:
                ex: int = Vilib.detect_obj_parameter['human_x'] - 320
                ey: int = Vilib.detect_obj_parameter['human_y'] - 240
                people_count: int = Vilib.detect_obj_parameter['human_n']
            except Exception:
                ex = 0
                ey = 0
                people_count = 0

            if people_count > 0:
                if ex > 15 and yaw > -config.FACE_TRACKING_YAW_LIMIT:
                    yaw -= 0.5 * int(ex / 30.0 + 0.5)
                elif ex < -15 and yaw < config.FACE_TRACKING_YAW_LIMIT:
                    yaw += 0.5 * int(-ex / 30.0 + 0.5)
                if ey > 25:
                    pitch -= 1 * int(ey / 50 + 0.5)
                    if pitch < -30:
                        pitch = -30
                elif ey < -25:
                    pitch += 1 * int(-ey / 50 + 0.5)
                    if pitch > 30:
                        pitch = 30
            else:
                # Decay head focus back to elevated lookup zone
                if pitch < config.FACE_TRACKING_ELEVATION_DEG:
                    pitch += 1
                elif pitch > config.FACE_TRACKING_ELEVATION_DEG:
                    pitch -= 1

            # Physical Constraints Clamps
            yaw = max(-config.FACE_TRACKING_YAW_LIMIT, min(config.FACE_TRACKING_YAW_LIMIT, yaw))
            pitch = max(-config.FACE_TRACKING_PITCH_LIMIT, min(config.FACE_TRACKING_PITCH_LIMIT, pitch))
            print(f"👥 Targets: {people_count} | X:{ex} Y:{ey} | Y:{round(yaw,1)} P:{round(pitch,1)}      ", end='\r', flush=True)

            # Execute Hardware Servos
            if dog and hasattr(dog, 'head_move'):
                dog.head_move([[yaw, 0, pitch]], pitch_comp=config.FACE_TRACKING_PITCH_COMP, immediately=True, speed=HEAD_MOVE_SPEED)
            time.sleep(0.05)

    except Exception as e:
        print(f"⚠ Face tracking error: {e}", file=sys.stderr, flush=True)
    finally:
        print("📷 Closing camera...", flush=True)
        Vilib.camera_close()
        if dog and hasattr(dog, 'close'):
            try:
                dog.close()
            except Exception:
                pass


# ==================== MAIN EXECUTION ====================
try:
    print("[System] Linking audio to Host Whisper API...")
    print("⚡ FLUID CONVERSATION LOOP ACTIVE")
    print("PiDog is permanently tracking your voice. Speak freely now... (Use Ctrl+C to Exit)\n")
    if dog and hasattr(dog, 'rgb_strip'):
        dog.rgb_strip.set_mode('listen', color='yellow', bps=config.PI_DOG_RGB_STRIP_BPS, brightness=config.PI_DOG_RGB_STRIP_BRIGHTNESS)

    # Start face tracking thread
    face_thread: Optional[threading.Thread] = threading.Thread(
        target=face_tracking_thread,
        daemon=True
    )
    face_thread.start()
    print("✅ Face tracking thread started! Speak freely now...", flush=True)

    STORE_ROOT: str = config.STORE_ROOT
    STORE_FILE: str = config.STORE_FILE
    AUDIO_FILE_PATH: str = STORE_ROOT + STORE_FILE

    recording_buffer: list[np.ndarray] = []
    is_recording: bool = False
    silence_counter: int = 0

    def mic_callback(indata: np.ndarray, frames: int, time_info, status) -> None:
        """Audio callback - handles mic input"""
        global is_speaking, is_recording, recording_buffer, silence_counter

        # Skip processing while speaking
        if is_speaking:
            return

        raw_audio = (indata * 32767).astype(np.int16)
        audio_data = np.clip(raw_audio * GAIN_MULTIPLIER, -32768, 32767).astype(np.int16)
        volume_norm = np.linalg.norm(audio_data) / len(audio_data) if audio_data.size > 0 else 0

        if volume_norm > VOLUME_THRESHOLD:
            if not is_recording:
                is_recording = True
                recording_buffer = []
                print("🎤 Listening...", end="", flush=True)
                if dog and hasattr(dog, 'rgb_strip'):
                    dog.rgb_strip.set_mode('listen', color='yellow', bps=config.PI_DOG_RGB_STRIP_BPS, brightness=config.PI_DOG_RGB_STRIP_BRIGHTNESS)
            # Check buffer size limit
            current_frames = len(recording_buffer) * frames
            if current_frames < MAX_TOTAL_FRAMES:
                recording_buffer.append(audio_data.copy())
            silence_counter = 0
        elif is_recording:
            recording_buffer.append(audio_data.copy())
            silence_counter += 1
            if silence_counter > config.SILENCE_THRESHOLD:
                print("\n🎤 Processing local GPU transcription...", end="", flush=True)
                audio_to_process = np.concatenate(recording_buffer, axis=0)
                recording_buffer = []
                is_recording = False
                silence_counter = 0
                text_result = transcribe_audio(audio_to_process)
                if text_result:
                    print(f"\n\n🗣 Ollie: {text_result}", end="", flush=True)
                    query_pidog_stream(text_result)
                else:
                    print(f"\n\n⚠ STT returned empty text - audio too quiet or no voice detected", end="", flush=True)
                if dog and hasattr(dog, 'rgb_strip'):
                    dog.rgb_strip.set_mode('listen', color='yellow', bps=config.PI_DOG_RGB_STRIP_BPS, brightness=config.PI_DOG_RGB_STRIP_BRIGHTNESS)

    # Main audio stream with proper cleanup
    audio_stream = sd.InputStream(
        samplerate=VOSK_SAMPLERATE,
        channels=1,
        device=INPUT_DEVICE_ID,
        callback=mic_callback
    )

    try:
        audio_stream.start()
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        # Stop audio stream
        audio_stream.stop()
        audio_stream.close()
        print("\n🛑 Stopping audio stream. ..")

    # Stop face tracking thread
    print("🛑 Stopping face tracking thread...")
    if face_thread:
        face_thread.join(timeout=config.FACE_THREAD_JOIN_TIMEOUT)

except KeyboardInterrupt:
    print("\nStopping and returning to the initial position ... \nQuit")
except Exception as e:
    print(f"\n❌ Core Application Crash: {e}")
finally:
    # Use the cleanup utility for safe hardware teardown
    cleanup_hardware(dog)
    print("\n✅ Hardware cleanup completed", file=sys.stderr)
