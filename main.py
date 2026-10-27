#!/usr/bin/env python3
"""
PIDOG System - Central Orchestrator (Fixed Subprocess Model)
Master controller for PiDog voice assistant and hardware modules.
Uses subprocess model: pidog_init.py runs as background process, main.py manages lifecycle.
"""
import argparse
import sys
import os
import signal
import time
import threading
import subprocess

# Import configuration
import config

# Import cleanup utility
from cleanup_hardware import cleanup_hardware


class GlobalState:
    """Central state management for the PiDog system"""
    
    def __init__(self):
        self.pidog_init_process = None
        self.roommap_thread = None


state = GlobalState()


def signal_handler(signum, frame):
    """Handle Ctrl+C and other signals gracefully - ONLY cleanup on critical errors"""
    print("\n\n⚠ Interrupt signal received. Shutting down...")
    
    # Run the same hardware cleanup as the normal shutdown path
    cleanup_and_exit(130)


def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown"""
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def set_network_mode(network_mode: str):
    """Set network mode and update configuration accordingly"""
    if network_mode == 'local':
        print("\n🌐 Network Mode: LOCAL (Direct Wi-Fi)")
        SERVER_IP = config.SERVER_IP
    elif network_mode == 'tunnel':
        print("\n🔌 Network Mode: TUNNEL (Cloudflare Proxy)")
        SERVER_IP = config.TUNNEL_IP


# Heartbeat staleness bound for the roommap daemon (beats are 0.5 s while parked
# and per-sample during a scan; 30 s is generous over a worst-case sample cycle).
ROOMMAP_HEARTBEAT_STALE_S = 30.0


def background_module_watchdog(voice_proc, roommap_thread=None, roommap=None):
    """Watch background AI modules; run central hardware shutdown if one dies."""
    sys.stdout.write("📋 [WATCHDOG] Active background module supervision initialized...\n")
    sys.stdout.flush()
    
    while True:
        # 1. Check the Voice Module state
        if voice_proc.poll() is not None:  # .poll() returns None if still running, or the exit code if dead!
            exit_code = voice_proc.returncode
            sys.stderr.write(f"\n💥 [WATCHDOG ALERT] pidog_voice_conversation.py dropped dead with exit code {exit_code}!\n")
            break

        # 2. Check the roommap thread state (thread liveness + fresh heartbeat)
        if roommap_thread is not None and roommap is not None:
            if not roommap_thread.is_alive():
                sys.stderr.write("\n💥 [WATCHDOG ALERT] roommap thread dropped dead!\n")
                break
            if time.time() - roommap.last_beat > ROOMMAP_HEARTBEAT_STALE_S:
                sys.stderr.write(f"\n💥 [WATCHDOG ALERT] roommap heartbeat stale (> {ROOMMAP_HEARTBEAT_STALE_S:.0f} s, thread wedged)!\n")
                break

        time.sleep(0.2)  # 200ms poll
    
    # Reached only when a child died; run central cleanup
    sys.stderr.write("🔌 Watchdog initiating central hardware recovery teardown...\n")
    cleanup_and_exit(1)
    sys.exit(1)


# ==================== ROOMMAP BRIDGE ====================
# Dedicated locked XML-RPC proxy for the roommap daemon, mirroring the
# pidog_voice_rpc._rpc_call pattern (ServerProxy is NOT thread-safe; every
# call is serialized on a dedicated lock).
import xmlrpc.client as xmlrpc_client

_roommap_proxy = xmlrpc_client.ServerProxy(f"http://localhost:{config.PORT_XMLRPC}")
_roommap_proxy_lock = threading.Lock()


def _roommap_rpc(method_name, *args):
    """Locked RPC bridge handed to pidog_roommap.start_roommap (rpc(method, *args))."""
    with _roommap_proxy_lock:
        return getattr(_roommap_proxy, method_name)(*args)


def run_voice_profile(roommap_thread=None, roommap=None):
    """Run pidog_voice_conversation.py as background subprocess with watchdog supervision"""
    
    try:
        print("\n🎤 Launching Voice Profile Module...")
        
        voice_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pidog_voice_conversation.py')
        
        # Launch voice script as background process
        env = os.environ.copy()
        env["SERVER_IP"] = config.SERVER_IP  # read current value at launch, not import-time copy
        voice_process = subprocess.Popen(
            [sys.executable, voice_script],
            stdout=None,   # Inherit parent's stdout (terminal) - SEE OUTPUT!
            stderr=None,   # Inherit parent's stderr (terminal) - SEE OUTPUT!
            cwd=os.path.dirname(os.path.abspath(__file__)),
            env=env,
            preexec_fn=os.setsid     # Create new process group for clean kill
        )
        
        print(f"  [VOICE PROFILE] Subprocess started (PID: {voice_process.pid})", file=sys.stderr)
        
        # Spin up the background watchdog thread, handing it the live process pointer
        monitor_thread = threading.Thread(
            target=background_module_watchdog, 
            args=(voice_process, roommap_thread, roommap),  # The watchdog thread supervises the voice module through this handle
            daemon=True
        )
        monitor_thread.start()
        
        print("  ✅ Voice profile launched and actively supervised")
        return True
        
    except Exception as e:
        print(f"  ❌ Failed to launch voice profile: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return False


def perform_startup_movements():
    """Perform the startup movement sequence: Stretch, Sit, Wag Tail, Bark via local RPC."""
    import xmlrpc.client as xmlrpc_client
    
    rpc_url = f"http://localhost:{config.PORT_XMLRPC}"
    rpc_client = xmlrpc_client.ServerProxy(rpc_url)
    
    print("\n🐕 Performing startup movements...", file=sys.stderr)
    
    # Stretch
    try:
        result = rpc_client.stretch()
        if result and result.get('status') == 'success':
            print("  ✅ Stretch completed", file=sys.stderr)
        else:
            print(f"  ⚠ Stretch returned: {result}", file=sys.stderr)
    except Exception as e:
        print(f"  ⚠ Stretch movement failed (non-fatal): {e}", file=sys.stderr)
    
    time.sleep(1.0)
    
    # Sit (return to neutral stance after stretch)
    try:
        result = rpc_client.action('sit')
        if result and result.get('status') == 'success':
            print("  ✅ Sit completed", file=sys.stderr)
        else:
            print(f"  ⚠ Sit returned: {result}", file=sys.stderr)
    except Exception as e:
        print(f"  ⚠ Sit movement failed (non-fatal): {e}", file=sys.stderr)
    
    time.sleep(1.0)
    
    # Wag Tail
    try:
        result = rpc_client.wag_tail()
        if result and result.get('status') == 'success':
            print("  ✅ Wag tail started", file=sys.stderr)
            time.sleep(4.0)
            rpc_client.tail_stop()
            time.sleep(1.0)
            print("  ✅ Wag tail completed", file=sys.stderr)
        else:
            print(f"  ⚠ Wag tail returned: {result}", file=sys.stderr)
    except Exception as e:
        print(f"  ⚠ Wag tail movement failed (non-fatal): {e}", file=sys.stderr)
        try:
            rpc_client.tail_stop()
        except Exception:
            pass
    
    time.sleep(1.0)
    
    # Bark
    try:
        result = rpc_client.head_bark()
        if result and result.get('status') == 'success':
            print("  ✅ Bark completed", file=sys.stderr)
        else:
            print(f"  ⚠ Bark returned: {result}", file=sys.stderr)
    except Exception as e:
        print(f"  ⚠ Bark movement failed (non-fatal): {e}", file=sys.stderr)
    
    time.sleep(1.0)
    print("  🐕 Startup movements complete!", file=sys.stderr)


def cleanup_and_exit(return_code: int):
    """Unified cleanup function that runs before exit"""
    print("\n🛑 Ensuring hardware cleanup...")

    # Stop the roommap daemon BEFORE the hardware close (mirrors voice stop ordering).
    try:
        import pidog_roommap as roommap
        roommap.stop_roommap()
    except Exception as e:
        print(f"⚠️ roommap stop failed (non-fatal): {e}", file=sys.stderr)

    # cleanup_hardware() ends with os._exit() and never returns
    try:
        # This call terminates the whole process via os._exit()
        cleanup_hardware()
        
    except Exception as e:
        print(f"❌ Critical error during hardware cleanup: {e}", file=sys.stderr)
    
    # Always terminate here - never fall through to more code
    sys.exit(return_code)


def main():
    """Main entrypoint for PIDOG system"""

    parser = argparse.ArgumentParser(
        description='PIDOG Voice Assistant System - Subprocess Orchestrator',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                    # Run voice assistant (default: local Wi-Fi)
  python main.py --local            # Run with direct local Wi-Fi connection
  python main.py --tunnel           # Run with Cloudflare tunnel proxy
        """
    )

    parser.add_argument('--local', action='store_true', help='Run with direct local Wi-Fi connection')
    parser.add_argument('--tunnel', action='store_true', help='Run with Cloudflare tunnel proxy routing')

    args = parser.parse_args()

    if args.local and args.tunnel:
        print("Error: --local and --tunnel are mutually exclusive configurations.")
        sys.exit(1)

    setup_signal_handlers()

    network_mode = 'local' if args.local else ('tunnel' if args.tunnel else None)
    if network_mode:
        set_network_mode(network_mode)

    try:
        # Use non-blocking subprocess with no PIPE to avoid buffer deadlock
        pidog_init_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pidog_init.py')

        state.pidog_init_process = subprocess.Popen(
            [sys.executable, pidog_init_script],
            stdout=None,  # Inherit parent's stdout (terminal) - SEE OUTPUT!
            stderr=None,  # Inherit parent's stderr (terminal) - SEE OUTPUT!
            cwd=os.path.dirname(os.path.abspath(__file__)),
            preexec_fn=os.setsid       # Create new process group for clean kill
        )

        print(f"  [PID] pidog_init.py started (PID: {state.pidog_init_process.pid})")

        # CRITICAL FIX: Wait for pidog_init to complete with proper timeout
        print("  ⏳ Waiting for pidog_init.py to complete hardware tests...", file=sys.stderr)

        try:
            state.pidog_init_process.wait(timeout=180)  # 3 minute max wait
            returncode = state.pidog_init_process.poll()

            if returncode == 0:
                print(f"  ✅ pidog_init.py completed successfully (exit code: {returncode})", file=sys.stderr)
            else:
                print(f"  ❌ pidog_init.py failed with exit code: {returncode}", file=sys.stderr)
                cleanup_and_exit(1)

        except subprocess.TimeoutExpired:
            print(f"  ❌ pidog_init.py timed out after 180s", file=sys.stderr)
            state.pidog_init_process.kill()
            cleanup_and_exit(1)

        # CRITICAL FIX: Verify port 8001 is actually open before launching voice profile
        print("  🔍 Verifying RPC server port 8001 is accessible...", file=sys.stderr)

        import socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)

        try:
            result = sock.connect_ex(('localhost', config.PORT_XMLRPC))
            if result == 0:
                print(f"  ✅ Port 8001 is open and accepting connections", file=sys.stderr)
            else:
                print(f"  ❌ Port 8001 is NOT accessible (error: {result})", file=sys.stderr)
                cleanup_and_exit(1)
        except Exception as e:
            print(f"  ❌ Failed to verify port 8001: {e}", file=sys.stderr)
            cleanup_and_exit(1)
        finally:
            sock.close()

        # Pre-heat fast conversation model via llama-server router API
        print(f"  🔥 Pre-heating lightweight model '{config.TARGET_MODEL}' for instant response...", file=sys.stderr)

        # Pulls network configuration and the active model target from global config
        model_warmed = load_llama_model(
            server_ip=config.SERVER_IP,
            port=config.PORT_LLAMA,
            model_name=config.TARGET_MODEL
        )

        if not model_warmed:
            print("  ⚠️ Warning: Model pre-heating failed or timed out. Attempting to continue...", file=sys.stderr)

        # Perform startup movements before voice module loads
        perform_startup_movements()

        # Start the roommap daemon (local module; dedicated locked XML-RPC proxy)
        # before the voice profile so the watchdog can supervise both.
        import pidog_roommap as roommap
        state.roommap_thread = roommap.start_roommap(_roommap_rpc)
        print(f"  [ROOMMAP] roommap daemon started (thread: {state.roommap_thread.name})", file=sys.stderr)

        # CRITICAL FIX: Launch voice profile IMMEDIATELY after port verification
        print("\n🎤 Launching Voice Profile Module immediately...", file=sys.stderr)

        success = run_voice_profile(state.roommap_thread, roommap)

        if success:
            print("\n✅ PIDOG Core Pipeline initialization complete")
            print("  🎤 Voice profile launched successfully")

            # Give voice profile a moment to initialize RPC connection
            time.sleep(2)

            print("\n🛑 PIDOG Core Pipeline complete - voice profile running continuously...")
            print("  🎤 Voice assistant ready. Press Ctrl+C to exit.\n")

            # Main loop to keep script alive until Ctrl+C
            while True:
                time.sleep(1)

        else:
            print("\n❌ Failed to launch voice profile")
            cleanup_and_exit(1)

    except Exception as e:
        print(f"\n❌ System error: {e}")
        import traceback
        traceback.print_exc()
        return cleanup_and_exit(1)



import requests



def _router_model_state(entry):
    """Normalize a /v1/models entry into (state, failed, exit_code)."""
    if not isinstance(entry, dict):
        return None, False, None
    status = entry.get("status")
    if isinstance(status, dict):
        return status.get("value"), bool(status.get("failed")), status.get("exit_code")
    # Older router builds may report a plain string status
    return status, False, None


def load_llama_model(server_ip, port, model_name, timeout=config.LLM_LOAD_TIMEOUT, poll_interval=config.LLM_LOAD_POLL_INTERVAL):
    """
    Triggers llama-server Router Mode to hot-swap or preload a specific model,
    then polls /v1/models until the model's status reports 'loaded'.

    The router's POST /models/load returns HTTP 200 as soon as the load is
    *accepted*, not when it has *completed* - so the 200 alone is not a success
    signal. Success is only confirmed by polling. Failure is detected via
    status.failed / exit_code != 0 (child process died, e.g. bad GGUF path),
    an 'incomplete' model file, an unreachable router, or a timeout.
    Returns a plain bool and never raises - boot continues on failure.
    """
    base_url = f"http://{server_ip}:{port}"

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
                if isinstance(entry, dict) and entry.get("id") == model_name:
                    return entry, None
        return None, None

    try:
        # 1) Pre-flight: router reachable and model registered in the preset
        entry, err = fetch_entry()
        if err:
            print(f"Model pre-heat aborted - cannot reach router model list: {err}")
            return False
        if entry is None:
            print(f"Model pre-heat aborted - '{model_name}' is not registered in the router preset")
            return False

        state, failed, exit_code = _router_model_state(entry)

        # 2) Fast path: already serving
        if state in config.ROUTER_READY_STATES:
            print(f"Model already loaded: {model_name}")
            return True

        # 3) Trigger the load (skip if one is already in progress)
        if state not in config.ROUTER_IN_PROGRESS_STATES:
            response = requests.post(
                f"{base_url}/models/load",
                json={"model": model_name},
                headers={"Content-Type": "application/json"},
                timeout=60,
            )
            if response.status_code != 200:
                print(f"Failed to load model. Server returned {response.status_code}: {response.text}")
                return False
            print(f"Model load accepted for {model_name}; polling for 'loaded'...")
        else:
            print(f"Model load already in progress ({state}); waiting for 'loaded'...")

        # 4) Poll until the model is loaded, fails, or times out
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(poll_interval)

            entry, err = fetch_entry()
            if err:
                print(f"Transient router error while polling '{model_name}': {err}")
                continue
            if entry is None:
                continue

            state, failed, exit_code = _router_model_state(entry)
            if state in config.ROUTER_READY_STATES:
                print(f"Successfully loaded model: {model_name}")
                return True
            if failed or (exit_code is not None and exit_code != 0):
                print(f"Model load FAILED: {model_name} (state={state}, exit_code={exit_code})")
                return False
            if state == "incomplete":
                print(f"Model load FAILED: {model_name} (router reports model file is incomplete)")
                return False
            # otherwise loading/unloaded/etc. - keep polling

        print(f"Timed out after {timeout:.0f}s waiting for model '{model_name}' to reach 'loaded'")
        return False

    except Exception as e:
        print(f"Error pre-heating model {model_name}: {e}")
        return False


if __name__ == '__main__':
    sys.exit(main())
