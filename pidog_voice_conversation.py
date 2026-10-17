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


def main():
    """Main entry point for the voice assistant - runs continuously until interrupted"""
    global is_running, shutdown_requested, audio_worker_thread, idle_listener_thread

    print("  [INFO] Starting main() with PID: %d" % os.getpid(), file=sys.stderr, flush=True)
    print("  [INFO] Entering main()", file=sys.stderr, flush=True)

    print("  [INFO] Initializing PiDog Voice Conversation Engine...", file=sys.stderr, flush=True)
    print("  [INFO] Starting RPC connection setup", file=sys.stderr, flush=True)

    # Setup RPC client to communicate with pidog_init.py server - WITH RETRY LOGIC
    max_retries = 3
    retry_delay = 0.5
    rpc_connected = False

    for attempt in range(max_retries):
        try:
            if not _setup_rpc_client():
                raise ConnectionError("Failed to connect")

            # Verify connection with status call
            print("  [INFO] Attempting RPC status verification...", file=sys.stderr, flush=True)
            result = _rpc_call_with_timeout('status')
            print("  [INFO] Verified connection: %s" % result, file=sys.stderr, flush=True)
            print("  [INFO] RPC connection successful", file=sys.stderr, flush=True)

            # Hardcode state confirmation once connectivity is physically proven
            rpc_connected = True
            break

        except Exception as e:
            if attempt < max_retries - 1:
                print("  [WARNING] Connection attempt %d failed: %s. Retrying in %ds..." % (attempt + 1, e, retry_delay), file=sys.stderr, flush=True)
                time.sleep(retry_delay)
            else:
                print("  [ERROR] FATAL ERROR: Cannot connect to XML-RPC server!", file=sys.stderr, flush=True)

    # CRITICAL FIX: Exit immediately if RPC connection failed - no conditional gate!
    if not rpc_connected:
        _critical_error_exit("RPC server unreachable")

    # Hardcode state confirmation once connectivity is physically proven
    is_running = True

    # Start personality engine (scans AI responses for trigger words, fires RPC actions)
    start_personality_engine(pidog_voice_rpc.rpc_client)

    # CRITICAL FIX: Start IDLE LISTENER FIRST (polls server, no local recording)
    _start_idle_listener_loop()

    # Main conversation loop - runs CONTINUOUSLY until interrupted
    print("  [INFO] Listening for voice input...", file=sys.stderr, flush=True)

    # RGB: BREATH GREEN - initial idle state (step 1 of the cycle)
    for attempt in range(max_retries):
        try:
            _rpc_call_with_timeout('rgb_strip_set_mode', 'breath', 'green')
            break
        except Exception as e:
            if attempt < max_retries - 1:
                print("  [WARNING] RGB init attempt %d failed: %s. Retrying in %ds..." % (attempt + 1, e, retry_delay), file=sys.stderr, flush=True)
                time.sleep(retry_delay)

    print("  [INFO] Entering main conversation loop", file=sys.stderr, flush=True)
    print("  [INFO] Use Ctrl+C to exit\n", file=sys.stderr, flush=True)

    last_health_check = time.time()
    start_time = time.time()

    try:
        while is_running and not shutdown_requested:
            current_time = time.time()
            time_delta = current_time - last_health_check

            if time_delta > 10:
                last_health_check = current_time

                try:
                    result = _rpc_call_with_timeout('status')
                    print("  [INFO] Health check result: %s" % result, file=sys.stderr, flush=True)
                except ConnectionError as e:
                    print("  [WARNING] RPC temporarily unavailable: %s" % e, file=sys.stderr, flush=True)
                    time.sleep(2)
                    continue
                except Exception as e:
                    error_msg = str(e)
                    if "Connection refused" in error_msg or "timed out" in error_msg.lower():
                        _critical_error_exit("RPC server unreachable")

            time.sleep(1)

    except KeyboardInterrupt:
        print("  [INFO] Interrupted by user - stopping...", file=sys.stderr, flush=True)
        print("  [INFO] Received KeyboardInterrupt", file=sys.stderr, flush=True)

    except Exception as e:
        # CRITICAL FIX: Catch ALL exceptions to prevent silent crashes!
        print("  [ERROR] UNHANDLED EXCEPTION in main loop: %s" % e, file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)

        # Signal parent process for cleanup
        _send_sigterm_to_parent()

        # CRITICAL FIX: Exit with code 1 to indicate error (not 255)
        sys.exit(1)

    finally:
        # CRITICAL FIX: ALWAYS run cleanup on ANY exit path!
        print("  [INFO] Exiting main loop", file=sys.stderr, flush=True)
        is_running = False

        # Stop personality engine gracefully
        stop_personality_engine()

        # Stop idle listener thread gracefully
        if idle_listener_thread and idle_listener_thread.is_alive():
            try:
                idle_listener_thread.join(timeout=2)
            except Exception:
                pass

        # Stop audio worker thread gracefully (lives in pidog_voice_audio namespace)
        if pidog_voice_audio.audio_worker_thread and pidog_voice_audio.audio_worker_thread.is_alive():
            try:
                pidog_voice_audio.audio_worker_thread.join(timeout=2)
            except Exception:
                pass

    # CRITICAL FIX: Exit the main function when interrupted
    # The subprocess will exit, allowing main.py to continue or clean up
    sys.exit(0)


def _start_idle_listener_loop():
    """Start background thread to poll server for sound detection - NO LOCAL RECORDING"""
    global idle_listener_thread

    try:
        def _idle_listener_loop():
            """Poll server-side ears tracking to check if sound has been detected"""
            global is_running, shutdown_requested

            print("  [IDLE] Idle listener loop initialized. Polling server for sound detection...", file=sys.stderr, flush=True)

            while is_running and not shutdown_requested:
                # CRITICAL FIX: