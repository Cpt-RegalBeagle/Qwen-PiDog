import os
import time
import threading
import sys
import xmlrpc.client

# Import config to get module-level settings
import config

# Import pidog_init_rpc_handler.py
from pidog_init_rpc_handler import PidogRPCHandler

# Import pidog_voice_rpc.py
import pidog_voice_rpc
from pidog_voice_rpc import _rpc_call_with_timeout, _setup_rpc_client, _critical_error_exit, _send_sigterm_to_parent

# Import pidog_voice_audio.py
import pidog_voice_audio
from pidog_voice_audio import _start_audio_worker, _send_audio_to_stt, _process_conversation, _stream_and_speak, _speak_text, get_wav_volume

# Import personality engine
from pidog_personality_engine import start_personality_engine, stop_personality_engine

# ==================== MODULE-LEVEL STATE ====================
is_running = True
shutdown_requested = False
audio_worker_thread = None
idle_listener_thread = None
last_processed_azimuth = -1


def _connect_rpc():
    """Connect to RPC server with retry. Returns True on success."""
    max_retries = 3
    retry_delay = 0.5
    for attempt in range(max_retries):
        try:
            if not _setup_rpc_client():
                raise ConnectionError("Failed to connect")
            result = _rpc_call_with_timeout('status')
            print("  [INFO] Verified connection: %s" % result, file=sys.stderr, flush=True)
            return True
        except Exception as e:
            if attempt < max_retries - 1:
                print("  [WARNING] Connection attempt %d failed: %s. Retrying in %ds..." % (attempt + 1, e, retry_delay), file=sys.stderr, flush=True)
                time.sleep(retry_delay)
    print("  [ERROR] FATAL ERROR: Cannot connect to XML-RPC server!", file=sys.stderr, flush=True)
    return False


def _init_rgb():
    """Initialize RGB strip to breath green with retry logic."""
    max_retries = 3
    retry_delay = 0.5
    for attempt in range(max_retries):
        try:
            _rpc_call_with_timeout('rgb_strip_set_mode', 'breath', 'green')
            return
        except Exception as e:
            if attempt < max_retries - 1:
                print("  [WARNING] RGB init attempt %d failed: %s. Retrying in %ds..." % (attempt + 1, e, retry_delay), file=sys.stderr, flush=True)
                time.sleep(retry_delay)


def _poll_server_azimuth() -> int:
    """Poll server for a fresh sound azimuth. Returns azimuth int or -1 if none."""
    global last_processed_azimuth

    try:
        result = _rpc_call_with_timeout('get_latched_azimuth')
    except Exception as e:
        print("  [IDLE] Server poll error (non-fatal): %s" % e, file=sys.stderr, flush=True)
        return -1

    if not isinstance(result, int):
        return -1
    if result == -1 or result == 0:
        return -1
    if result == last_processed_azimuth:
        return -1

    prev_azimuth = last_processed_azimuth
    last_processed_azimuth = result
    print("  [IDLE] Fresh azimuth detected: %d (prev: %d)" % (result, prev_azimuth), file=sys.stderr, flush=True)
    return result


def _idle_listener_loop():
    """Poll server-side ears tracking to detect sound, turn head, start capture."""
    global is_running, shutdown_requested

    print("  [IDLE] Idle listener loop initialized. Polling server for sound detection...", file=sys.stderr, flush=True)

    while is_running and not shutdown_requested:
        azimuth = _poll_server_azimuth()
        if azimuth == -1:
            time.sleep(0.5)
            continue

        print("  [IDLE] Server detected sound at azimuth %d! Triggering capture phase..." % azimuth, file=sys.stderr, flush=True)

        # Turn head to face the sound source
        try:
            _rpc_call_with_timeout('look_at_angle', azimuth)
        except Exception as e:
            print("  [IDLE] Head turn failed (non-fatal): %s" % e, file=sys.stderr, flush=True)

        # Let head motor and SPI bus settle before touching ears GPIO
        time.sleep(1.0)

        # Pause ears to prevent re-trigger during conversation
        try:
            _rpc_call_with_timeout('pause_ears_monitor')
        except Exception as e:
            print("  [IDLE] Ears pause failed (non-fatal): %s" % e, file=sys.stderr, flush=True)

        # Let GPIO/SPI bus fully release after background thread stop
        time.sleep(0.5)

        # Start local VAD recording loop
        _start_audio_worker()

        # Exit idle listener - audio worker will handle the rest
        break


def _start_idle_listener_loop():
    """Start background thread to poll server for sound detection."""
    global idle_listener_thread

    try:
        idle_listener_thread = threading.Thread(target=_idle_listener_loop, daemon=True)
        idle_listener_thread.start()
        print("  [IDLE] Idle listener thread started", file=sys.stderr, flush=True)
        print("  [TIME] %s - Idle listener PID: %d" % (time.strftime('%H:%M:%S'), idle_listener_thread.ident), file=sys.stderr, flush=True)
    except Exception as e:
        print("  [IDLE] Idle listener failed: %s" % e, file=sys.stderr, flush=True)
        _critical_error_exit("Idle listener initialization failed")


def _maybe_health_check(last_check_time):
    """Perform RPC health check if due. Returns updated last_check_time."""
    current = time.time()
    if current - last_check_time < 10:
        return last_check_time
    try:
        result = _rpc_call_with_timeout('status')
        print("  [INFO] Health check result: %s" % result, file=sys.stderr, flush=True)
        return current
    except ConnectionError as e:
        print("  [WARNING] RPC temporarily unavailable: %s" % e, file=sys.stderr, flush=True)
        time.sleep(2)
        return last_check_time
    except Exception as e:
        error_msg = str(e)
        if "Connection refused" in error_msg or "timed out" in error_msg.lower():
            _critical_error_exit("RPC server unreachable")
        return current


def _maybe_restart_idle_listener():
    """Check if idle listener needs restarting. Restarts it if audio worker is done."""
    global idle_listener_thread

    if idle_listener_thread is None:
        return
    if idle_listener_thread.is_alive():
        return
    audio_worker = pidog_voice_audio.audio_worker_thread
    if audio_worker is not None and audio_worker.is_alive():
        return

    print("  [INFO] Idle listener exited, audio worker done. Restarting idle listener.", file=sys.stderr, flush=True)
    try:
        _rpc_call_with_timeout('resume_ears_monitor')
    except Exception:
        pass
    _start_idle_listener_loop()


def _cleanup_threads():
    """Stop all background threads gracefully."""
    global is_running, idle_listener_thread

    is_running = False
    stop_personality_engine()
    if idle_listener_thread and idle_listener_thread.is_alive():
        try:
            idle_listener_thread.join(timeout=2)
        except Exception:
            pass
    if pidog_voice_audio.audio_worker_thread and pidog_voice_audio.audio_worker_thread.is_alive():
        try:
            pidog_voice_audio.audio_worker_thread.join(timeout=2)
        except Exception:
            pass


def main():
    """Main entry point for the voice assistant - runs continuously until interrupted."""
    global is_running, shutdown_requested, audio_worker_thread, idle_listener_thread

    print("  [INFO] Starting main() with PID: %d" % os.getpid(), file=sys.stderr, flush=True)
    print("  [INFO] Entering main()", file=sys.stderr, flush=True)
    print("  [INFO] Initializing PiDog Voice Conversation Engine...", file=sys.stderr, flush=True)
    print("  [INFO] Starting RPC connection setup", file=sys.stderr, flush=True)

    if not _connect_rpc():
        _critical_error_exit("RPC server unreachable")

    is_running = True

    # Start personality engine (scans AI responses for trigger words, fires RPC actions)
    start_personality_engine(pidog_voice_rpc.rpc_client)

    # Start idle listener (polls server, no local recording)
    _start_idle_listener_loop()

    # RGB: BREATH GREEN - initial idle state
    _init_rgb()

    print("  [INFO] Listening for voice input...", file=sys.stderr, flush=True)
    print("  [INFO] Entering main conversation loop", file=sys.stderr, flush=True)
    print("  [INFO] Use Ctrl+C to exit\n", file=sys.stderr, flush=True)

    last_health_check = time.time()
    start_time = time.time()

    try:
        while is_running and not shutdown_requested:
            last_health_check = _maybe_health_check(last_health_check)
            _maybe_restart_idle_listener()
            time.sleep(1)
    except KeyboardInterrupt:
        print("  [INFO] Interrupted by user - stopping...", file=sys.stderr, flush=True)
        print("  [INFO] Received KeyboardInterrupt", file=sys.stderr, flush=True)
    except Exception as e:
        print("  [ERROR] UNHANDLED EXCEPTION in main loop: %s" % e, file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        _send_sigterm_to_parent()
        sys.exit(1)
    finally:
        print("  [INFO] Exiting main loop", file=sys.stderr, flush=True)
        _cleanup_threads()

    sys.exit(0)


if __name__ == '__main__':
    main()
