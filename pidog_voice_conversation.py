import os
import sys
import time

# Import pidog_voice_rpc.py
import pidog_voice_rpc
from pidog_voice_rpc import _rpc_call_with_timeout, _setup_rpc_client, _critical_error_exit, _send_sigterm_to_parent

# Import pidog_voice_audio.py
import pidog_voice_audio
from pidog_voice_audio import _start_audio_worker

# Import personality engine
from pidog_personality_engine import start_personality_engine, stop_personality_engine

# Import command engine (filters the USER's STT for direct action commands)
from pidog_command_engine import start_command_engine, stop_command_engine

# ==================== MODULE-LEVEL STATE ====================
is_running = True
shutdown_requested = False


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


# Sustained-outage counter: a permanent RPC outage must self-terminate the
# voice subprocess (os._exit -> main.py watchdog) instead of retrying forever.
# A failed check keeps last_check_time stale, so a check is due every ~3s;
# 100 consecutive failures ~= 5 minutes of sustained outage.
_health_fail_streak = 0


def _maybe_health_check(last_check_time):
    """Perform RPC health check if due. Returns updated last_check_time.

    Single fail-soft path for ALL errors: the old separate ConnectionError
    branch plus the dead-code keyword check in the generic branch are
    collapsed (those keywords already arrive as ConnectionError via
    _classify, and a raw keyword check could never see them otherwise).
    """
    global _health_fail_streak
    current = time.time()
    if current - last_check_time < 10:
        return last_check_time
    try:
        result = _rpc_call_with_timeout('status')
        _health_fail_streak = 0
        print("  [INFO] Health check result: %s" % result, file=sys.stderr, flush=True)
        return current
    except Exception as e:
        _health_fail_streak += 1
        if _health_fail_streak >= 100:
            _critical_error_exit("RPC server unreachable (sustained outage)")
        print("  [WARNING] RPC health check failed (%d consecutive): %s" % (_health_fail_streak, e), file=sys.stderr, flush=True)
        time.sleep(2)
        return last_check_time


def _maybe_restart_audio_worker():
    """Check if audio worker needs restarting. Restarts it if the thread is dead."""
    audio_worker = pidog_voice_audio.audio_worker_thread
    if audio_worker is not None and audio_worker.is_alive():
        return

    print("  [INFO] Audio worker thread not running. Restarting.", file=sys.stderr, flush=True)
    _start_audio_worker()


def _cleanup_threads():
    """Stop all background threads gracefully."""
    global is_running

    is_running = False
    stop_personality_engine()
    stop_command_engine()
    # Stop the audio module's own worker loop condition BEFORE the join so the
    # daemon worker exits cleanly instead of relying on the join timeout.
    pidog_voice_audio.is_running = False
    pidog_voice_audio.shutdown_requested = True
    if pidog_voice_audio.audio_worker_thread and pidog_voice_audio.audio_worker_thread.is_alive():
        try:
            pidog_voice_audio.audio_worker_thread.join(timeout=2)
        except Exception:
            pass


def main():
    """Main entry point for the voice assistant - runs continuously until interrupted."""
    global is_running, shutdown_requested

    print("  [INFO] Starting main() with PID: %d" % os.getpid(), file=sys.stderr, flush=True)
    print("  [INFO] Entering main()", file=sys.stderr, flush=True)
    print("  [INFO] Initializing PiDog Voice Conversation Engine...", file=sys.stderr, flush=True)
    print("  [INFO] Starting RPC connection setup", file=sys.stderr, flush=True)

    if not _connect_rpc():
        _critical_error_exit("RPC server unreachable")

    is_running = True

    # Start personality engine (scans AI responses for trigger words, fires RPC actions)
    start_personality_engine(pidog_voice_rpc.rpc_client)

    # Start command engine (scans the USER's STT for direct action commands, fires RPC actions)
    start_command_engine(pidog_voice_rpc.rpc_client)

    # Start VAD audio worker (listens for human speech -> STT -> LLM -> TTS)
    _start_audio_worker()

    # RGB: BREATH GREEN - initial idle state
    _init_rgb()

    print("  [INFO] Listening for voice input...", file=sys.stderr, flush=True)
    print("  [INFO] Entering main conversation loop", file=sys.stderr, flush=True)
    print("  [INFO] Use Ctrl+C to exit\n", file=sys.stderr, flush=True)

    last_health_check = time.time()

    try:
        while is_running and not shutdown_requested:
            last_health_check = _maybe_health_check(last_health_check)
            _maybe_restart_audio_worker()
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
