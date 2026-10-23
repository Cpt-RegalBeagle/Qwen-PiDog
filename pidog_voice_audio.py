import os
import time
import threading
import shutil
import struct
import json
import queue
import requests
import sys
import io
import wave
import config

import pidog_voice_rpc
from pidog_voice_rpc import (
    _rpc_call_with_timeout,
    _rpc_call,
    _critical_error_exit
)

from pidog_personality_engine import personality_queue
from pidog_command_engine import command_queue

# ==================== MODULE-LEVEL GLOBALS ====================
is_running = True
shutdown_requested = False
is_speaking = False
# SOLE cross-thread speaking gate (single-writer: only _speak_text writes).
# is_speaking_deadline is a monotonic-seconds bound; the gate is EXPIRED when
# time.monotonic() >= is_speaking_deadline. The VAD loop only READS both.
is_speaking_deadline = 0.0
audio_worker_thread = None

# Llama router load contract (mirrors main.py load_llama_model)
LLM_LOAD_TIMEOUT: float = 120.0
LLM_LOAD_POLL_INTERVAL: float = 2.0
ROUTER_READY_STATES = ("loaded", "sleeping")
ROUTER_IN_PROGRESS_STATES = ("loading", "downloading", "downloaded")


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
                # Speaking gate: while TTS playback is active (and within its
                # finite deadline) skip VAD. READ-ONLY here (never written); a
                # gate past its deadline is treated as expired without any write,
                # preserving the single-writer invariant.
                if is_speaking and time.monotonic() < is_speaking_deadline:
                    time.sleep(0.5); continue

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


def _router_model_state(entry):
    """Normalize a /v1/models entry into (state, failed, exit_code)."""
    if not isinstance(entry, dict):
        return None, False, None
    status = entry.get("status")
    if isinstance(status, dict):
        return status.get("value"), bool(status.get("failed")), status.get("exit_code")
    # Older router builds may report a plain string status
    return status, False, None


def _ensure_llama_ready(model: str, timeout: float = LLM_LOAD_TIMEOUT, poll_interval: float = LLM_LOAD_POLL_INTERVAL) -> bool:
    """
    Ensures the voice model is resident in the llama.cpp router before the
    chat POST. Triggers the router's POST /models/load when the model is
    evicted, then polls GET /v1/models until the model reports a ready state.

    The router's /models/load returns HTTP 200 as soon as the load is
    *accepted*, not when it has *completed* - success is only confirmed by
    polling. Failure is detected via status.failed / exit_code != 0 (child
    process died, e.g. bad GGUF path), an 'incomplete' model file, an
    unreachable router, or a timeout.
    Returns a plain bool and never raises.
    """
    base_url = f"http://{config.SERVER_IP}:{config.PORT_OLLAMA}"

    def fetch_entry():
        """Return (entry, error): the model's /v1/models entry (or None) and an error string."""
        try:
            response = requests.get(f"{base_url}/v1/models", timeout=10)
            response.raise_for_status()
            payload = response.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            return None, str(e)
        data = payload.get("data") if isinstance(payload, dict) else payload
        if isinstance(data, list):
            for entry in data:
                if isinstance(entry, dict) and entry.get("id") == model:
                    return entry, None
        return None, None

    try:
        # 1) Pre-flight: router reachable and model registered in the preset
        entry, err = fetch_entry()
        if err:
            print(f"  [LLM] Router unreachable, cannot verify model (non-fatal): {err}", file=sys.stderr, flush=True)
            return False
        if entry is None:
            print(f"  [LLM] Model '{model}' not registered in router preset (non-fatal)", file=sys.stderr, flush=True)
            return False

        state, failed, exit_code = _router_model_state(entry)

        # 2) Fast path: already resident
        if state in ROUTER_READY_STATES:
            print(f"  [LLM] Model already resident: {model}", file=sys.stderr, flush=True)
            return True

        # 3) Trigger the load (skip if one is already in progress)
        if state not in ROUTER_IN_PROGRESS_STATES:
            try:
                response = requests.post(
                    f"{base_url}/models/load",
                    json={"model": model},
                    headers={"Content-Type": "application/json"},
                    timeout=60,
                )
            except requests.exceptions.RequestException as e:
                print(f"  [LLM] Model load request failed (non-fatal): {e}", file=sys.stderr, flush=True)
                return False

            if response.status_code in (500, 503):
                print("  [LLM] CRITICAL: Llama server error on model load, exiting...", file=sys.stderr, flush=True)
                _critical_error_exit("LLM server unavailable")
            if response.status_code != 200:
                print(f"  [LLM] Model load rejected (status {response.status_code}) (non-fatal): {response.text[:200]}", file=sys.stderr, flush=True)
                return False
            print(f"  [LLM] Model load accepted for {model}; waiting for 'loaded'...", file=sys.stderr, flush=True)
        else:
            print(f"  [LLM] Model load already in progress ({state}); waiting...", file=sys.stderr, flush=True)

        # 4) Poll until the model is loaded, fails, or times out
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(poll_interval)

            entry, err = fetch_entry()
            if err:
                print(f"  [LLM] Transient router error while waiting for model: {err}", file=sys.stderr, flush=True)
                continue
            if entry is None:
                continue

            state, failed, exit_code = _router_model_state(entry)
            if state in ROUTER_READY_STATES:
                print(f"  [LLM] Model resident: {model}", file=sys.stderr, flush=True)
                return True
            if failed or (exit_code is not None and exit_code != 0):
                print(f"  [LLM] Model load FAILED (state={state}, exit_code={exit_code}) (non-fatal)", file=sys.stderr, flush=True)
                return False
            if state == "incomplete":
                print(f"  [LLM] Model file incomplete (non-fatal)", file=sys.stderr, flush=True)
                return False
            # otherwise loading/unloaded/etc. - keep polling

        print(f"  [LLM] Model not ready within {timeout:.0f}s (non-fatal)", file=sys.stderr, flush=True)
        return False

    except Exception as e:
        print(f"  [LLM] Error (non-fatal): {e}", file=sys.stderr, flush=True)
        return False


def _get_llm_response(text: str):
    """Robot-side LLM bridge.

    First ensures the voice model is resident in the llama.cpp router
    (hot-swap via router /models/load + /v1/models polling), then POSTs
    the STT transcription to the Llama OpenAI-compatible endpoint
    (config.OLLAMA_STREAM_URL, non-streaming) and returns the assistant
    reply string, or None on any failure. Must NEVER raise.
    """
    if not _ensure_llama_ready(config.TARGET_MODEL):
        return None
    try:
        payload = {
            "model": config.TARGET_MODEL,
            "messages": [
                {"role": "system", "content": config.SYSTEM_PROMPT},
                {"role": "user", "content": text}
            ],
            "stream": False,
            "max_tokens": 100
        }

        response = requests.post(
            config.OLLAMA_STREAM_URL,
            json=payload,
            timeout=(10, config.OLLAMA_TIMEOUT)
        )

        if response.status_code == 500 or response.status_code == 503:
            print("  [LLM] CRITICAL: Llama server error, exiting...", file=sys.stderr, flush=True)
            _critical_error_exit("LLM server unavailable")

        if response.status_code == 200:
            data = response.json()
            choices = data.get("choices")
            content = ""
            if choices:
                content = (choices[0].get("message") or {}).get("content") or ""
            content = str(content).strip()
            return content if content else None

        print(f"  [LLM] Error (non-fatal): unexpected status {response.status_code}", file=sys.stderr, flush=True)
        return None

    except Exception as e:
        print(f"  [LLM] Error (non-fatal): {e}", file=sys.stderr, flush=True)
        return None


def _send_audio_to_stt(audio_file: str):
    """Send audio file to OpenWebUI for STT processing - INDEPENDENT OF FACE TRACKING"""

    # OpenWebUI returns the STT transcription only; the robot then bridges it to
    # the Llama LLM via _get_llm_response before speaking.
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
            transcription = stt_response.get("text", "").strip()
            print(f"  [STT] Transcription: {transcription}", file=sys.stderr, flush=True)

            if not transcription:
                print("  [STT] Empty transcription - skipping", file=sys.stderr, flush=True)
                return

            # Enqueue the USER's transcription for the command engine (fires
            # direct action commands, incl. locomotion) BEFORE the LLM call.
            try:
                command_queue.put_nowait(transcription)
            except queue.Full:
                pass  # drop, mirror the existing personality_queue drop handling

            llm_text = _get_llm_response(transcription)

            if llm_text and len(llm_text) > 3:
                print(f"  [LLM] Response: {llm_text}", file=sys.stderr, flush=True)
                try:
                    personality_queue.put_nowait(llm_text)
                except queue.Full:
                    print("  [AUDIO] Personality queue full - dropping message (non-fatal)", file=sys.stderr, flush=True)
                _speak_text(llm_text)
            else:
                print("  [LLM] No usable response - skipping (non-fatal)", file=sys.stderr, flush=True)
                return
        else:
            print(f"  [STT] Unexpected response {response.status_code}: {response.text[:200]}", file=sys.stderr, flush=True)

    except Exception as e:
        print(f"  [STT] Error processing audio (non-fatal): {e}", file=sys.stderr, flush=True)


def _wav_duration_seconds(wav_bytes_or_path):
    """Return the EXACT duration (seconds) of a WAV.

    Accepts raw WAV bytes (preferred - the TTS bytes are already in memory) or a
    file path. Uses stdlib wave + io.BytesIO. On ANY failure returns
    config.PLAYBACK_FALLBACK_DURATION (fail-closed: a generous FINITE bound,
    never zero, so the gate always carries a finite deadline)."""
    try:
        if isinstance(wav_bytes_or_path, bytes):
            with wave.open(io.BytesIO(wav_bytes_or_path), 'rb') as w:
                nframes = w.getnframes()
                framerate = w.getframerate()
        else:
            with wave.open(wav_bytes_or_path, 'rb') as w:
                nframes = w.getnframes()
                framerate = w.getframerate()
        if not framerate or framerate <= 0:
            return config.PLAYBACK_FALLBACK_DURATION
        return float(nframes) / float(framerate)
    except Exception:
        return config.PLAYBACK_FALLBACK_DURATION


def _best_effort_music_stop():
    """Best-effort music_stop() over a DEDICATED 2.0s-timeout proxy so a
    stuck server can never hold the worker for the shared client's 20s.
    Never raises (watchdog path)."""
    try:
        stop_proxy = pidog_voice_rpc._build_proxy(socket_timeout=2.0)
        stop_proxy.music_stop()
    except Exception as e:
        print(f"  [TTS] music_stop() best-effort failed (non-fatal): {e}", file=sys.stderr, flush=True)


def _wait_playback_end(duration):
    """Block (on the EXISTING worker thread) until the tracked playback ends.

    Polls is_music_playing() over a DEDICATED 2.0s-timeout proxy (built via
    _build_proxy) - NOT the shared 20s proxy - so a stuck poll can never blow
    the watchdog bound. Fail-closed: an RPC/timeout error is treated as 'still
    playing'. If the watchdog deadline (duration + PLAYBACK_WATCHDOG_MARGIN)
    fires, a best-effort music_stop() is sent and we return. No new thread/lock -
    this runs on the calling worker thread."""
    start = time.monotonic()
    deadline = start + duration + config.PLAYBACK_WATCHDOG_MARGIN

    try:
        poll_proxy = pidog_voice_rpc._build_proxy(socket_timeout=2.0)
    except Exception as e:
        # Cannot even build the polling proxy: fail-closed. Sleep to the bound,
        # best-effort stop, and return (the gate deadline is the second bound).
        print(f"  [TTS] WARNING: playback-poll proxy build failed ({e}); relying on watchdog", file=sys.stderr, flush=True)
        time.sleep(max(0.0, deadline - time.monotonic()))
        _best_effort_music_stop()
        print("  [TTS] WATCHDOG fired (poll-proxy unavailable) - forcing stop", file=sys.stderr, flush=True)
        return

    while True:
        # Poll playback status over the dedicated short-timeout proxy.
        try:
            if not poll_proxy.is_music_playing():
                # Returned False -> playback ended (accurate detection).
                print(f"  [TTS] playback ended (detected) after {time.monotonic() - start:.1f} s", file=sys.stderr, flush=True)
                return
        except Exception:
            pass  # fail-closed: RPC/timeout => assume still playing, keep waiting

        if time.monotonic() >= deadline:
            _best_effort_music_stop()
            print(f"  [TTS] WATCHDOG fired after {time.monotonic() - start:.1f} s (bound {duration + config.PLAYBACK_WATCHDOG_MARGIN:.1f} s) - forcing stop", file=sys.stderr, flush=True)
            return

        time.sleep(min(config.PLAYBACK_POLL_INTERVAL, max(0.0, deadline - time.monotonic())))


def _release_speak_gate():
    """Single release funnel: clear the speaking gate + its deadline."""
    global is_speaking, is_speaking_deadline
    is_speaking = False
    is_speaking_deadline = 0.0


def _speak_text(text: str):
    """Convert text to speech using Kokoro TTS.

    Straight-line, single-writer, fail-closed. The speaking gate
    (is_speaking / is_speaking_deadline) is armed BEFORE any audio can start and
    ALWAYS carries a finite deadline; it is released on EVERY exit path via the
    finally funnel (the VAD-loop deadline check is the second bound)."""

    global is_speaking, is_speaking_deadline

    duration = config.PLAYBACK_FALLBACK_DURATION
    gate_armed = False
    started = False

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

        # Kokoro TTS POST kept as-is (raises on network error). The gate is NOT
        # armed yet on this path, so a failure here leaks nothing.
        response = requests.post(kokoro_url, headers=headers, json=payload, timeout=(10, 120))

        if response.status_code != 200:
            print(f"  [TTS] TTS returned HTTP {response.status_code} - not speaking", file=sys.stderr, flush=True)
            return

        print(f"  [TTS] TTS complete, playing audio...", file=sys.stderr)

        audio_data = response.content
        audio_file = "/tmp/temp_audio.wav"

        # Exact duration from the TTS bytes (already in memory); fail-closed
        # fallback (PLAYBACK_FALLBACK_DURATION) on any parse failure.
        duration = _wav_duration_seconds(audio_data)

        # ARM the gate BEFORE any audio can start (before music_play_file).
        # deadline = duration + watchdog margin + echo settle + one VAD yield.
        is_speaking = True
        is_speaking_deadline = (time.monotonic() + duration
                               + config.PLAYBACK_WATCHDOG_MARGIN
                               + config.PLAYBACK_SETTLE
                               + 0.5)
        gate_armed = True
        print(f"  [TTS] armed gate (duration={duration:.1f} s, deadline=+{is_speaking_deadline - time.monotonic():.1f} s)", file=sys.stderr, flush=True)

        with open(audio_file, 'wb') as f:
            f.write(audio_data)

        print(f"  [AUDIO] Audio file written ({len(audio_data)} bytes), playing...", file=sys.stderr, flush=True)

        # Send music_play_file (existing rpc_client-is-not-None guard).
        # Fail-closed: a play-RPC failure sets started=False but does NOT abort
        # the wait - unknown state => stay gated until the deadline.
        if pidog_voice_rpc.rpc_client is not None:
            try:
                _rpc_call('music_play_file', audio_file)
                started = True
            except Exception as play_err:
                print(f"  [TTS] music_play_file failed (fail-closed, still gated): {play_err}", file=sys.stderr, flush=True)
        else:
            print("  [TTS] rpc_client is None - skipping music_play_file (fail-closed, still gated)", file=sys.stderr, flush=True)

        # Accurate playback-end detection (poll + watchdog, fail-closed).
        _wait_playback_end(duration)

        # 0.2s echo/reverb settle lives HERE (conversation side).
        time.sleep(config.PLAYBACK_SETTLE)

        print(f"  [TTS] gate released (settle 0.2 s complete; started={started})", file=sys.stderr, flush=True)

    except Exception as e:
        print(f"  [AUDIO] Error playing audio (non-fatal): {e}", file=sys.stderr, flush=True)
    finally:
        # Single release funnel - EVERY exit path (success, TTS failure,
        # play-RPC failure, watchdog) clears the gate here.
        if gate_armed:
            _release_speak_gate()


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
