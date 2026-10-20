import os
import time
import threading
import shutil
import struct
import json
import requests
import sys
import config

import pidog_voice_rpc
from pidog_voice_rpc import (
    _rpc_call_with_timeout,
    _rpc_call,
    _critical_error_exit
)

from pidog_personality_engine import personality_queue

# ==================== MODULE-LEVEL GLOBALS ====================
is_running = True
shutdown_requested = False
is_speaking = False
audio_worker_thread = None


def _init_session_file(audio_file, session_file):
    """Copy the first triggered VAD chunk into the session file."""
    try:
        shutil.copyfile(audio_file, session_file)
    except Exception as e:
        print(f"  [AUDIO] Session initialization error: {e}", file=sys.stderr, flush=True)


def _append_audio_chunk(audio_file, session_file):
    """Append raw PCM bytes from a 1s chunk to the session file, skipping the WAV header."""
    try:
        with open(audio_file, 'rb') as f_in, open(session_file, 'ab') as f_out:
            f_in.seek(44)
            f_out.write(f_in.read())
    except Exception as e:
        print(f"  [AUDIO] Byte compilation error: {e}", file=sys.stderr, flush=True)


def _patch_wav_header(session_file):
    """Overwrite WAV header size fields to reflect all appended PCM bytes."""
    try:
        file_size = os.path.getsize(session_file)
        if file_size <= 44:
            return
        with open(session_file, 'r+b') as f_patch:
            f_patch.seek(4)
            f_patch.write(struct.pack('<I', file_size - 8))
            f_patch.seek(40)
            f_patch.write(struct.pack('<I', file_size - 44))
        print(f"  [AUDIO] Patched WAV container size ({file_size} bytes total)", file=sys.stderr, flush=True)
    except Exception as header_err:
        print(f"  [AUDIO] WAV size patch warning: {header_err}", file=sys.stderr, flush=True)


def _reset_rgb_idle():
    """Set RGB strip back to idle green breathing."""
    try:
        _rpc_call('rgb_strip_set_mode', 'breath', 'green')
    except Exception as e:
        print(f"  [AUDIO] RGB reset warning (non-fatal): {e}", file=sys.stderr, flush=True)


def _finalize_and_dispatch(session_file):
    """Patch WAV header and send to STT - called when silence threshold is met."""
    _patch_wav_header(session_file)
    print("  [AUDIO] Dispatching compiled session to STT...", file=sys.stderr, flush=True)
    _send_audio_to_stt(session_file)


def _start_audio_worker():
    """Start audio worker thread for microphone input"""
    global audio_worker_thread

    try:
        def _audio_worker_loop():
            global is_running, shutdown_requested
            print("  [AUDIO] Audio worker loop initialized successfully.", file=sys.stderr, flush=True)

            audio_file = config.PI_DOG_AUDIO_FILE
            session_file = "/tmp/buddy_session.wav"
            SPEECH_THRESHOLD = 20.0
            silence_seconds = 0
            is_recording_speech = False

            print("  [AUDIO] Dynamic VAD engine initialized. Idling for voice activity...", file=sys.stderr, flush=True)

            while is_running and not shutdown_requested:
                # Phase 1: VAD - record 1s snippet from the recording mic (sound card)
                result = _rpc_call_with_timeout('audio_record', 1, audio_file)
                if not result or result.get('status') != 'success':
                    time.sleep(0.5)
                    continue

                current_volume = get_wav_volume(audio_file)
                print(f"  [AUDIO VAD] Monitor Vol: {current_volume:.1f} (Threshold: {SPEECH_THRESHOLD})", file=sys.stderr, flush=True)

                if not is_recording_speech:
                    # State A: Listening for speech trigger on recording mic
                    if current_volume <= SPEECH_THRESHOLD:
                        continue

                    # VAD hit - initialize session file and transition to recording
                    _init_session_file(audio_file, session_file)
                    is_recording_speech = True
                    print(f"  [AUDIO] Speech detected - entering recording state", file=sys.stderr, flush=True)
                else:
                    # State B: Accumulate audio from recording mic
                    _append_audio_chunk(audio_file, session_file)

                    if current_volume < SPEECH_THRESHOLD:
                        silence_seconds += 1
                    else:
                        silence_seconds = 0

                    print(f"  [AUDIO] Silence tracking: {silence_seconds}/4 seconds...", file=sys.stderr, flush=True)

                    if silence_seconds >= 4:
                        # Recording complete - STT, reset
                        print("  [AUDIO] 4-Second silence threshold reached. Closing session.", file=sys.stderr, flush=True)
                        _finalize_and_dispatch(session_file)
                        is_recording_speech = False
                        silence_seconds = 0
                        print("  [AUDIO] Lockout cleared. Returning to idle listening.\n", file=sys.stderr, flush=True)
                        _reset_rgb_idle()

        audio_worker_thread = threading.Thread(target=_audio_worker_loop, daemon=True)
        audio_worker_thread.start()
        print("  [AUDIO] Audio worker thread started", file=sys.stderr, flush=True)
        print(f"  [TIME] {time.strftime('%H:%M:%S')} - Audio worker thread PID: {audio_worker_thread.ident}", file=sys.stderr, flush=True)

    except Exception as e:
        print(f"  [AUDIO] Audio worker failed: {e}", file=sys.stderr, flush=True)
        _critical_error_exit("Audio worker initialization failed")


def _send_audio_to_stt(audio_file: str):
    """Send audio file to OpenWebUI for STT processing - INDEPENDENT OF FACE TRACKING"""

    # OpenWebUI owns STT+LLM; response `text` is the LLM's spoken response - do NOT re-route to Ollama.
    try:
        stt_url = config.STT_HOST_URL

        print(f"  [STT] Sending audio to {stt_url}", file=sys.stderr)

        try:
            _rpc_call('rgb_strip_set_mode', 'breath', 'yellow')
        except Exception as e:
            print(f"  [STT] RGB set warning (non-fatal): {e}", file=sys.stderr, flush=True)

        headers = {
            "Authorization": f"Bearer {config.WEBUI_API_KEY}"
        }

        with open(audio_file, 'rb') as f:
            audio_data = f.read()

        response = requests.post(
            stt_url,
            headers=headers,
            files={'file': (os.path.basename(audio_file), audio_data, 'audio/wav')},
            timeout=(10, 180)
        )

        if response.status_code == 500 or response.status_code == 503:
            print(f"  [STT] CRITICAL: OpenWebUI server error, exiting...", file=sys.stderr, flush=True)
            _critical_error_exit("STT server unavailable")

        if response.status_code == 200:
            stt_response = response.json()
            llm_text = stt_response.get("text", "").strip()

            if llm_text and len(llm_text) > 3:
                print(f"  [LLM] Response from OpenWebUI: {llm_text}", file=sys.stderr, flush=True)
                personality_queue.put(llm_text)
                _speak_text(llm_text)
        else:
            print(f"  [STT] Unexpected response {response.status_code}: {response.text[:200]}", file=sys.stderr, flush=True)

    except Exception as e:
        print(f"  [STT] Error processing audio (non-fatal): {e}", file=sys.stderr, flush=True)


def _speak_text(text: str):
    """Convert text to speech using Kokoro TTS"""

    global is_speaking, is_running, shutdown_requested

    try:
        kokoro_url = config.KOKORO_API_URL

        print(f"  [TTS] Converting to speech: {text[:50]}...", file=sys.stderr)

        headers = {
            "Authorization": f"Bearer {config.WEBUI_API_KEY}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": config.TTS_MODEL,
            "input": text,
            "voice": config.TARGET_VOICE,
            "response_format": "wav",
            "speed": 1.0
        }

        response = requests.post(kokoro_url, headers=headers, json=payload, timeout=(10, 120))

        if response.status_code == 200:
            print(f"  [TTS] TTS complete, playing audio...", file=sys.stderr)

            is_speaking = True

            audio_data = response.content
            audio_file = "/tmp/temp_audio.wav"
            with open(audio_file, 'wb') as f:
                f.write(audio_data)

            print(f"  [AUDIO] Audio file written ({len(audio_data)} bytes), playing...", file=sys.stderr)

            if pidog_voice_rpc.rpc_client is not None:
                _rpc_call('music_play_file', audio_file)

            # 9-SECOND SAFETY LOCKOUT - covers physical playback + echo resolution
            print(f"  [AUDIO] Safety lockout active: Waiting 9.0 seconds for voice rendering and echo resolution...", file=sys.stderr, flush=True)
            time.sleep(9.0)

            # Hardware settle delay - let Pi finish releasing audio hardware
            print(f"  [AUDIO] Hardware settle delay: Waiting 0.5 seconds for audio bus to clear...", file=sys.stderr, flush=True)
            time.sleep(0.5)

            # Reset state flags for next VAD cycle
            is_speaking = False
            is_running = True
            shutdown_requested = False

            print(f"  [AUDIO] Software lock released. Ready for next VAD cycle.", file=sys.stderr, flush=True)

    except Exception as e:
        print(f"  [AUDIO] Error playing audio (non-fatal): {e}", file=sys.stderr, flush=True)


def get_wav_volume(file_path):
    """Calculate Root-Mean-Square amplitude of a 16-bit WAV file"""
    import struct
    import math
    import os

    if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
        return 0

    try:
        with open(file_path, 'rb') as f:
            f.seek(44)
            data = f.read()
            count = len(data) / 2
            if count == 0:
                return 0

            format_string = f"<{int(count)}h"
            shorts = struct.unpack(format_string, data)
            sum_squares = sum(s * s for s in shorts)
            return math.sqrt(sum_squares / count)
    except Exception:
        return 0
