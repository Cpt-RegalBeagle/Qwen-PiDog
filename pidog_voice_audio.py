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
    _setup_rpc_client,
    _rpc_call,
    _send_sigterm_to_parent,
    _critical_error_exit
)

# ==================== MODULE-LEVEL GLOBALS ====================
is_running = True
shutdown_requested = False
wakeup_azimuth = -1
is_speaking = False
last_processed_azimuth = -1
audio_worker_thread = None


def _start_audio_worker():
    """Start audio worker thread for microphone input"""
    global audio_worker_thread

    try:
        def _audio_worker_loop():
            """Streamlined, non-blocking single-pass recording worker loop with VAD."""
            global is_running, shutdown_requested, wakeup_azimuth
            print("  [AUDIO] Audio worker loop initialized successfully.", file=sys.stderr, flush=True)

            audio_file = config.PI_DOG_AUDIO_FILE
            session_file = "/tmp/buddy_session.wav"

            try:
                # Calibrated baseline matching our real-world hardware gain data
                SPEECH_THRESHOLD = 20.0
                silence_seconds = 0
                is_recording_speech = False

                print("  [AUDIO] Dynamic VAD engine initialized. Idling for voice activity...", file=sys.stderr, flush=True)

                while is_running and not shutdown_requested:
                    # Target a quick 1-second snippet from the server to monitor room volume
                    result = _rpc_call_with_timeout('audio_record', 1, audio_file)

                    if not result or result.get('status') != 'success':
                        time.sleep(0.5)
                        continue

                    current_volume = get_wav_volume(audio_file)
                    print(f"  [AUDIO VAD] Monitor Vol: {current_volume:.1f} (Threshold: {SPEECH_THRESHOLD})", file=sys.stderr, flush=True)

                    if not is_recording_speech:
                        # State A: Listening for initial human speech trigger
                        if current_volume > SPEECH_THRESHOLD:
                            # CRITICAL FIX: Capture azimuth IMMEDIATELY when speech detected
                            # This stores the "pre-echo" vector before ears are paused
                            try:
                                wakeup_azimuth = _rpc_call_with_timeout('get_latched_azimuth')
                                print(f"  [AUDIO] Captured wakeup azimuth: {wakeup_azimuth}", file=sys.stderr, flush=True)
                            except Exception as e:
                                print(f"  [AUDIO] Warning: Could not capture initial azimuth: {e}", file=sys.stderr)

                            # CRITICAL FIX: Pause ears monitor to prevent GPIO conflicts during audio capture
                            try:
                                _rpc_call_with_timeout('pause_ears_monitor')
                                print(f"  [AUDIO] Ears monitoring paused for audio capture", file=sys.stderr, flush=True)
                            except Exception as e:
                                print(f"  [AUDIO] Ears pause warning (non-fatal): {e}", file=sys.stderr)

                            # Initialize our clean session file by copying the first triggered chunk over
                            try:
                                shutil.copyfile(audio_file, session_file)
                            except Exception as e:
                                print(f"  [AUDIO] Session initialization error: {e}", file=sys.stderr)

                            # CRITICAL FIX: Transition to State B so we start accumulating audio
                            is_recording_speech = True
                            print(f"  [AUDIO] Speech detected - entering recording state", file=sys.stderr, flush=True)
                        else:
                            continue
                    else:
                        # State B: Human is speaking. Accumulate bytes inline.
                        try:
                            # Append the fresh 1-second raw PCM audio bytes to our session file
                            with open(audio_file, 'rb') as f_in, open(session_file, 'ab') as f_out:
                                f_in.seek(44)  # Skip the individual chunk's WAV header to prevent corrupted headers inside the PCM body
                                f_out.write(f_in.read())
                        except Exception as e:
                            print(f"  [AUDIO] Byte compilation error: {e}", file=sys.stderr)

                        # Monitor silence frames
                        if current_volume < SPEECH_THRESHOLD:
                            silence_seconds += 1
                            print(f"  [AUDIO] Silence tracking: {silence_seconds}/4 seconds...", file=sys.stderr, flush=True)
                        else:
                            silence_seconds = 0

                        # If we hit 4 consecutive seconds of silence, the human is fully done talking!
                        if silence_seconds >= 4:
                            print("  [AUDIO] 4-Second silence threshold reached. Closing session.", file=sys.stderr, flush=True)

                            # CRITICAL FIX: Align head using STORED wakeup_azimuth BEFORE STT dispatch
                            # This ensures we use the vector captured when speech was first detected
                            try:
                                if wakeup_azimuth != -1 and wakeup_azimuth != 0:
                                    _rpc_call_with_timeout('look_at_angle', wakeup_azimuth)
                                    print(f"  [AUDIO] Head aligned to stored wakeup azimuth: {wakeup_azimuth}", file=sys.stderr, flush=True)
                                else:
                                    print("  [AUDIO] Warning: No valid wakeup azimuth captured", file=sys.stderr, flush=True)
                            except Exception as e:
                                print(f"  [AUDIO] Head alignment warning (non-fatal): {e}", file=sys.stderr)

                            print("  [AUDIO] Dispatching compiled session to STT...", file=sys.stderr, flush=True)

                            # CRITICAL CONTAINER FIX: Overwrite the WAV header sizes to reflect all appended bytes
                            try:
                                file_size = os.path.getsize(session_file)
                                if file_size > 44:
                                    with open(session_file, 'r+b') as f_patch:
                                        # Update ChunkSize (Total File Size - 8 bytes) at byte offset 4
                                        f_patch.seek(4)
                                        f_patch.write(struct.pack('<I', file_size - 8))
                                        # Update Subchunk2Size (Data payload size) at byte offset 40
                                        f_patch.seek(40)
                                        f_patch.write(struct.pack('<I', file_size - 44))
                                    print(f"  [AUDIO] Patched WAV container size properties dynamically ({file_size} bytes total)", file=sys.stderr, flush=True)
                            except Exception as header_err:
                                print(f"  [AUDIO] WAV size patch warning: {header_err}", file=sys.stderr)

                            # 1. Forward the fully compiled variable-length session file to STT
                            _send_audio_to_stt(session_file)

                            # Drive tracking servos using stored wakeup azimuth again for consistency
                            try:
                                if wakeup_azimuth != -1 and wakeup_azimuth != 0:
                                    _rpc_call_with_timeout('look_at_angle', wakeup_azimuth)
                                    print(f"  [AUDIO] Head aligned to stored wakeup azimuth (second pass): {wakeup_azimuth}", file=sys.stderr, flush=True)
                            except Exception as e:
                                print(f"  [AUDIO] Second alignment warning (non-fatal): {e}", file=sys.stderr)

                            # Reset states and clean up heading tracker for the next cycle
                            captured_heading = -1
                            is_recording_speech = False
                            silence_seconds = 0
                            wakeup_azimuth = -1  # CRITICAL FIX: Clear stored azimuth after use
                            print("  [AUDIO] Lockout cleared. Returning to idle listener.\n", file=sys.stderr, flush=True)

                            # RGB: BREATH GREEN - back to idle listening state (step 3 of the cycle)
                            try:
                                _rpc_call('rgb_strip_set_mode', 'breath', 'green')
                            except Exception as e:
                                print(f"  [AUDIO] RGB reset warning (non-fatal): {e}", file=sys.stderr)
            except Exception as e:
                print(f"  [AUDIO] Audio worker thread exception: {e}", file=sys.stderr, flush=True)

        # CRITICAL FIX: Use Daemon thread so it closes instantly on shutdown signal
        audio_worker_thread = threading.Thread(target=_audio_worker_loop, daemon=True)
        audio_worker_thread.start()
        print("  [AUDIO] Audio worker thread started", file=sys.stderr, flush=True)
        print(f"  [TIME] {time.strftime('%H:%M:%S')} - Audio worker thread PID: {audio_worker_thread.ident}", file=sys.stderr, flush=True)

    except Exception as e:
        print(f"  [AUDIO] Audio worker failed: {e}", file=sys.stderr, flush=True)
        _critical_error_exit("Audio worker initialization failed")


def _send_audio_to_stt(audio_file: str):
    """Send audio file to OpenWebUI for STT processing - INDEPENDENT OF FACE TRACKING"""

    try:
        stt_url = config.STT_HOST_URL

        print(f"  [STT] Sending audio to {stt_url}", file=sys.stderr)

        # RGB: BREATH YELLOW - processing/active state (step 2 of the cycle)
        try:
            _rpc_call('rgb_strip_set_mode', 'breath', 'yellow')
        except Exception as e:
            print(f"  [STT] RGB set warning (non-fatal): {e}", file=sys.stderr)

        headers = {
            "Authorization": f"Bearer {config.WEBUI_API_KEY}"
        }

        # Read the audio file content
        with open(audio_file, 'rb') as f:
            audio_data = f.read()

        # FIX: OpenWebUI expects multipart form upload with field name 'file'
        response = requests.post(
            stt_url,
            headers=headers,
            files={'file': (os.path.basename(audio_file), audio_data, 'audio/wav')}
        )

        # Only exit on critical errors - 422 is not always fatal
        if response.status_code == 500 or response.status_code == 503:
            print(f"  [STT] CRITICAL: OpenWebUI server error, exiting...", file=sys.stderr, flush=True)
            _critical_error_exit("STT server unavailable")

        if response.status_code == 200:
            stt_response = response.json()
            user_text = stt_response.get("text", "").strip()

            if user_text and len(user_text) > 3:
                print(f"  [STT] Transcribed: {user_text}", file=sys.stderr)
                _process_conversation(user_text)
        else:
            print(f"  [STT] Unexpected response {response.status_code}: {response.text[:200]}", file=sys.stderr, flush=True)

    except Exception as e:
        # Don't exit on every STT error - just log and continue
        print(f"  [STT] Error processing audio (non-fatal): {e}", file=sys.stderr, flush=True)


def _process_conversation(text: str):
    """Process transcribed text and generate response"""

    try:
        ollama_url = config.OLLAMA_STREAM_URL

        print(f"  [LLM] Sending request to {ollama_url}", file=sys.stderr)

        # CRITICAL FIX: Add keep_alive=-1 to lock buddy:latest in memory permanently
        payload = {
            "model": config.TARGET_MODEL,
            "keep_alive": -1,
            "messages": [
                {"role": "system", "content": config.SYSTEM_PROMPT},
                {"role": "user", "content": text}
            ],
            "stream": True
        }

        response = requests.post(ollama_url, json=payload)

        if response.status_code == 200:
            print(f"  [LLM] Response received, streaming...", file=sys.stderr)
            _stream_and_speak(response)

    except Exception as e:
        # Don't exit on every LLM error - just log and continue
        print(f"  [LLM] Error processing conversation (non-fatal): {e}", file=sys.stderr, flush=True)


def _stream_and_speak(response):
    """Stream LLM response and convert to TTS"""

    try:
        full_response = ""

        for line in response.iter_lines():
            if line:
                try:
                    data = json.loads(line)
                    message = data.get("message", {}).get("content", "")
                    full_response += message

                except json.JSONDecodeError:
                    pass

        # Convert the full response to speech
        _speak_text(full_response)

    except Exception as e:
        # Don't exit on every TTS error - just log and continue
        print(f"  [TTS] Error streaming response (non-fatal): {e}", file=sys.stderr, flush=True)


def _speak_text(text: str):
    """Convert text to speech using Kokoro TTS"""

    global is_speaking, is_running, shutdown_requested, last_processed_azimuth

    try:
        kokoro_url = config.KOKORO_API_URL

        print(f"  [TTS] Converting to speech: {text[:50]}...", file=sys.stderr)

        headers = {
            "Authorization": f"Bearer {config.WEBUI_API_KEY}",
            "Content-Type": "application/json"
        }

        # CRITICAL FIX: Use OpenAI-compatible payload structure for Kokoro
        payload = {
            "model": config.TTS_MODEL,
            "input": text,
            "voice": config.TARGET_VOICE,
            "response_format": "wav",
            "speed": 1.0
        }

        response = requests.post(kokoro_url, headers=headers, json=payload)

        if response.status_code == 200:
            print(f"  [TTS] TTS complete, playing audio...", file=sys.stderr)

            # CRITICAL FIX: Set speaking lock BEFORE playback starts to prevent self-transcription!
            is_speaking = True

            # Play the audio
            audio_data = response.content
            audio_file = "/tmp/temp_audio.wav"
            with open(audio_file, 'wb') as f:
                f.write(audio_data)

            print(f"  [AUDIO] Audio file written ({len(audio_data)} bytes), playing...", file=sys.stderr)

            # CRITICAL FIX: Use RPC to play music instead of direct dog.music call
            if pidog_voice_rpc.rpc_client is not None:
                _rpc_call('music_play_file', audio_file)

            # CRITICAL FIX: 9-SECOND SAFETY LOCKOUT - Execute AFTER playback command starts
            # This window covers the physical audio playback duration + network latency buffer
            print(f"  [AUDIO] Safety lockout active: Waiting 9.0 seconds for voice rendering and echo resolution...", file=sys.stderr, flush=True)
            time.sleep(9.0)

            # CRITICAL FIX: STOP LOCAL VAD RECORDING STREAM FIRST - Free up hardware line!
            print(f"  [AUDIO] Stopping local VAD recording stream to release GPIO resources...", file=sys.stderr, flush=True)

            # CRITICAL FIX: Audio worker is daemon thread - no explicit stop needed
            # Just clear the shutdown flag and let it exit naturally
            shutdown_requested = True

            # CRITICAL FIX: NOW execute RPC resume call AFTER local stream is closed
            print(f"  [AUDIO] Executing server-side ears monitor resume handshake...", file=sys.stderr, flush=True)

            try:
                _rpc_call_with_timeout('resume_ears_monitor')
                print(f"  [AUDIO] Server-side ears monitoring resumed successfully", file=sys.stderr, flush=True)
            except Exception as e:
                error_msg = str(e).lower()
                if "gpio busy" in error_msg or "permission denied" in error_msg:
                    print(f"  [AUDIO] CRITICAL: GPIO bus conflict during resume! {e}", file=sys.stderr, flush=True)
                    _critical_error_exit("GPIO hardware lockup - ears monitor failed")
                else:
                    print(f"  [AUDIO] Ears resume warning (non-fatal): {e}", file=sys.stderr, flush=True)

            # CRITICAL FIX: Hardware settle delay - let Pi finish initializing SoundDirection class
            print(f"  [AUDIO] Hardware settle delay: Waiting 0.5 seconds for GPIO bus to clear...", file=sys.stderr, flush=True)
            time.sleep(0.5)

            # CRITICAL FIX: NOW execute RPC resume call AFTER local stream is closed AND alignment is done
            # This ensures azimuth buffer is fresh for NEXT conversation cycle, not current one
            print(f"  [AUDIO] Executing server-side ears monitor resume handshake...", file=sys.stderr, flush=True)

            try:
                _rpc_call_with_timeout('resume_ears_monitor')
                print(f"  [AUDIO] Server-side ears monitoring resumed successfully", file=sys.stderr, flush=True)
            except Exception as e:
                error_msg = str(e).lower()
                if "gpio busy" in error_msg or "permission denied" in error_msg:
                    print(f"  [AUDIO] CRITICAL: GPIO bus conflict during resume! {e}", file=sys.stderr, flush=True)
                    _critical_error_exit("GPIO hardware lockup - ears monitor failed")
                else:
                    print(f"  [AUDIO] Ears resume warning (non-fatal): {e}", file=sys.stderr, flush=True)

            # Reset state flags for next cycle
            is_running = True
            shutdown_requested = False
            last_processed_azimuth = -1  # CRITICAL FIX: Reset freshness tracker for next conversation cycle

            print(f"  [AUDIO] Server-side ears monitoring ready for next cycle", file=sys.stderr, flush=True)

    except Exception as e:
        # Don't exit on every audio error - just log and continue
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
            f.seek(44)  # Skip standard WAV header lines
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
