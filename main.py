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

# Physical button interrupts are now handled inside pidog_init.py RPC server
# where self.dog has exclusive access to the GPIO registers


def hardware_button_watchdog():
    """Lightweight background thread that checks the physical USER button state directly via the OS kernel."""
    sys.stdout.write("🔘 [HARDWARE] Active USER button watchdog listening...\n")
    sys.stdout.flush()
    
    # On the PiDog, the USER button is routed directly to Broadcom GPIO 25
    # We use a non-blocking loop to check its physical state every 200ms
    while True:
        try:
            # Query the hardware pin state directly via the native Linux gpiod utility
            # This completely bypasses the 'robot_hat' driver lock!
            result = subprocess.run(
                ['gpioget', 'gpiochip4', '25'], 
                capture_output=True, 
                text=True
            )
            
            # If the tool isn't available, fall back to the older raspi-gpio interface
            if result.returncode != 0:
                result = subprocess.run(
                    ['raspi-gpio', 'get', '25'], 
                    capture_output=True, 
                    text=True
                )
                is_pressed = "level=0" in result.stdout
            else:
                is_pressed = result.stdout.strip() == "0"
            
            # If the physical line is grounded (0), the button is being actively pressed!
            if is_pressed:
                sys.stderr.write("\n🚨 [HARDWARE PANIC] USER Button pressed physically! Triggering graceful exit...\n")
                sys.stderr.flush()
                
                # Fire a native SIGTERM to our own main process thread to execute all custom cleanups!
                os.kill(os.getpid(), signal.SIGTERM)
                break
                
        except Exception:
            pass
            
        time.sleep(0.2)  # 200ms polling rate keeps CPU consumption at 0.0%


class GlobalState:
    """Central state management for the PiDog system"""
    
    def __init__(self):
        self.running = True
        self.pidog_init_process = None
        self.voice_profile_process = None
        self.shutdown_callbacks = []
        self._shutdown_in_progress = False
        
    def register_shutdown(self, callback):
        """Register a function to run on clean shutdown"""
        self.shutdown_callbacks.append(callback)
        
    def shutdown(self):
        """Execute all registered shutdown callbacks and stop processes"""
        if self._shutdown_in_progress:
            print("⚠ Shutdown already in progress, skipping...")
            return
            
        self._shutdown_in_progress = True
        
        try:
            # Kill voice profile subprocess first
            if self.voice_profile_process is not None:
                try:
                    self.voice_profile_process.terminate()
                    self.voice_profile_process.wait(timeout=5)
                    print("[Cleanup] voice_profile process terminated cleanly", file=sys.stderr)
                except subprocess.TimeoutExpired:
                    try:
                        self.voice_profile_process.kill()
                        print("[Cleanup] voice_profile process killed (force)", file=sys.stderr)
                    except Exception as e:
                        print(f"[Cleanup] Failed to kill voice_profile: {e}", file=sys.stderr)
                finally:
                    self.voice_profile_process = None
            
            # Kill pidog_init subprocess second
            if self.pidog_init_process is not None:
                try:
                    self.pidog_init_process.terminate()
                    self.pidog_init_process.wait(timeout=5)
                    print("[Cleanup] pidog_init process terminated cleanly", file=sys.stderr)
                except subprocess.TimeoutExpired:
                    try:
                        self.pidog_init_process.kill()
                        print("[Cleanup] pidog_init process killed (force)", file=sys.stderr)
                    except Exception as e:
                        print(f"[Cleanup] Failed to kill pidog_init: {e}", file=sys.stderr)
                finally:
                    self.pidog_init_process = None
            
            # Run shutdown callbacks
            for callback in reversed(self.shutdown_callbacks):
                try:
                    callback()
                except Exception as e:
                    pass
                    
        finally:
            self._shutdown_in_progress = False


state = GlobalState()


def signal_handler(signum, frame):
    """Handle Ctrl+C and other signals gracefully - ONLY cleanup on critical errors"""
    print("\n\n⚠ Interrupt signal received. Shutting down...")
    
    # CRITICAL FIX: Just exit immediately - cleanup_hardware.py will kill all python processes
    sys.exit(130)


def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown"""
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def set_network_mode(network_mode: str):
    """Set network mode and update configuration accordingly"""
    if network_mode == 'local':
        print("\n🌐 Network Mode: LOCAL (Direct Wi-Fi)")
        config.SERVER_IP = "192.168.0.163"
        config.NETWORK_MODE = 'local'
    elif network_mode == 'tunnel':
        print("\n🔌 Network Mode: TUNNEL (Cloudflare Proxy)")
        config.SERVER_IP = "ai.meigs.co.uk"
        config.NETWORK_MODE = 'tunnel'


def run_test_mode():
    """Run in test mode for CI/CD pipeline validation"""
    print("\n🧪 TEST MODE - Running active verification...")
    
    # CRITICAL FIX: Don't disable FACE_TRACKING_ENABLED - STT is independent!
    # Only disable camera-related features if needed
    
    import pidog_voice_conversation as vp
    vp.set_test_mode(True)
    
    TEST_TIMEOUT_SECONDS = config.TEST_MODE_TIMEOUT_SECONDS
    
    def test_with_timeout():
        try:
            print("  1. Testing voice module...")
            if not vp.verify_engine(timeout=TEST_TIMEOUT_SECONDS):
                return False
                
            print("  ✅ Voice module verified")
            
            print("\n✅ All modules verified successfully")
            return True
            
        except Exception as e:
            print(f"\n❌ Verification error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    test_thread = threading.Thread(target=test_with_timeout)
    test_thread.daemon = True
    state.register_shutdown(lambda: None)  # Register for cleanup tracking
    test_thread.start()
    
    try:
        test_thread.join(timeout=TEST_TIMEOUT_SECONDS + 5)
        
        if test_thread.is_alive():
            print(f"\n⚠ TEST TIMEOUT - Test exceeded {TEST_TIMEOUT_SECONDS} seconds")
            print("🛑 Force stopping test to prevent indefinite hanging...")
            state.shutdown()
            return False
        
        time.sleep(0.5)
        
    except Exception as e:
        print(f"⚠ Timeout error: {e}")
        state.shutdown()
        return False
    
    print("\n✅ Test mode completed successfully")
    return True


def run_parallel_modules():
    """Run core hardware tests and cleanup - no voice profile for now"""
    # Import and test voice profile module
    try:
        import pidog_voice_conversation as vp
        
        print("\n🧪 Testing Voice Profile Module...")
        
        # Test RPC connection
        if not vp._setup_rpc_client():
            print("  ❌ Voice profile failed to connect to RPC server")
            return False
        
        print("  ✅ Voice profile connected to RPC server")
        
        # Verify engine
        success = vp.verify_engine(timeout=30)
        
        if success:
            print("  ✅ Voice profile verification complete")
            return True
        else:
            print("  ❌ Voice profile verification failed")
            return False
            
    except Exception as e:
        print(f"  ❌ Voice profile test error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False


def background_module_watchdog(voice_proc, tracking_proc=None):
    """Watches active background AI modules. If any module drops dead, 

    it forces main.py to handle a clean hardware safety shutdown."""
    sys.stdout.write("📋 [WATCHDOG] Active background module supervision initialized...\n")
    sys.stdout.flush()
    
    while True:
        # 1. Check the Voice Module state
        if voice_proc.poll() is not None:  # .poll() returns None if still running, or the exit code if dead!
            exit_code = voice_proc.returncode
            sys.stderr.write(f"\n💥 [WATCHDOG ALERT] pidog_voice_conversation.py dropped dead with exit code {exit_code}!\n")
            break
            
        # 2. Check the Head Tracking Module state (when you add it later)
        if tracking_proc and tracking_proc.poll() is not None:
            exit_code = tracking_proc.returncode
            sys.stderr.write(f"\n💥 [WATCHDOG ALERT] head_tracking.py dropped dead with exit code {exit_code}!\n")
            break
            
        time.sleep(0.2)  # Check every 200ms drawing 0.0% CPU overhead
    
    # Execution only reaches here if a child dropped! Trigger your central cleanup
    sys.stderr.write("🔌 Watchdog initiating central hardware recovery teardown...\n")
    cleanup_and_exit(1)
    sys.exit(1)


def run_voice_profile():
    """Run pidog_voice_conversation.py as background subprocess with watchdog supervision"""
    
    try:
        print("\n🎤 Launching Voice Profile Module...")
        
        voice_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pidog_voice_conversation.py')
        
        # Launch your voice script as an active background handle (NO .wait() call!)
        voice_process = subprocess.Popen(
            [sys.executable, voice_script],
            stdout=None,   # Inherit parent's stdout (terminal) - SEE OUTPUT!
            stderr=None,   # Inherit parent's stderr (terminal) - SEE OUTPUT!
            cwd=os.path.dirname(os.path.abspath(__file__)),
            preexec_fn=os.setsid     # Create new process group for clean kill
        )
        
        print(f"  [VOICE PROFILE] Subprocess started (PID: {voice_process.pid})", file=sys.stderr)
        
        # Spin up the background watchdog thread, handing it the live process pointer
        monitor_thread = threading.Thread(
            target=background_module_watchdog, 
            args=(voice_process, None),  # Pass your tracking_process handle here later!
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
    
    rpc_url = "http://localhost:8001"
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
    
    # CRITICAL FIX: Call cleanup_hardware directly - it has os._exit() at end
    try:
        from cleanup_hardware import cleanup_hardware
        
        # This will call os._exit() and terminate everything cleanly
        cleanup_hardware()
        
    except Exception as e:
        print(f"❌ Critical error during hardware cleanup: {e}", file=sys.stderr)
    
    # CRITICAL FIX: Always exit immediately - never fall through to more code
    import sys
    sys.exit(return_code)  # Changed from os._exit() to sys.exit()


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
  python main.py --test             # Run in test mode for CI/CD (active verification, 60s timeout)
        """
    )
    
    parser.add_argument('--local', action='store_true', help='Run with direct local Wi-Fi connection')
    parser.add_argument('--tunnel', action='store_true', help='Run with Cloudflare tunnel proxy routing')
    parser.add_argument('--test', action='store_true', help='Run in test mode for CI/CD (active verification, 60s timeout)')
    
    args = parser.parse_args()
    
    if args.local and args.tunnel:
        print("Error: --local and --tunnel are mutually exclusive configurations.")
        sys.exit(1)
    
    setup_signal_handlers()
    
    # CRITICAL FIX: Start hardware button watchdog thread for headless shutdown
    button_thread = threading.Thread(target=hardware_button_watchdog, daemon=True)
    button_thread.start()
    
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
            result = sock.connect_ex(('localhost', 8001))
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
        
        # CRITICAL FIX: Pre-heat Ollama model before voice profile loads
        print("  🔥 Pre-heating Ollama model 'buddy:latest' for instant response...", file=sys.stderr)
        _pre_heat_ollama_model()
        
        # Perform startup movements before voice module loads
        perform_startup_movements()
        
        # CRITICAL FIX: Launch voice profile IMMEDIATELY after port verification
        print("\n🎤 Launching Voice Profile Module immediately...", file=sys.stderr)
        
        success = run_voice_profile()
        
        if success:
            print("\n✅ PIDOG Core Pipeline initialization complete")
            print("  🎤 Voice profile launched successfully")
            
            # Give voice profile a moment to initialize RPC connection
            time.sleep(2)
            
            print("\n🛑 PIDOG Core Pipeline complete - voice profile running continuously...")
            print("  🎤 Voice assistant ready. Press Ctrl+C to exit.\n")

            # Main loop to keep script alive until Ctrl+C
            while state.running:
                time.sleep(1)
                
        else:
            print("\n❌ Failed to launch voice profile")
            cleanup_and_exit(1)
            
    # Hardware RST button handles panic shutdown via GPIO interrupt
    # Ctrl+C still works but is secondary to hardware panic
    except KeyboardInterrupt:
        print("\n⚠ Interrupted by user (Ctrl+C)")
        return cleanup_and_exit(130)
        
    except Exception as e:
        print(f"\n❌ System error: {e}")
        import traceback
        traceback.print_exc()
        return cleanup_and_exit(1)


def _pre_heat_ollama_model():
    """Pre-warm the buddy:latest model in memory with persistent keep_alive"""
    
    try:
        import requests
        
        ollama_url = config.OLLAMA_STREAM_URL
        
        print(f"  [PRE-HEAT] Warming up Ollama model at {ollama_url}", file=sys.stderr)
        
        # Use generate endpoint to load model into memory with -1 (infinite) keep_alive
        payload = {
            "model": "buddy:latest",
            "prompt": "System ready. Model loaded and waiting for voice input.",
            "stream": False,
            "keep_alive": -1  # CRITICAL: Keep model in memory indefinitely
        }
        
        response = requests.post(ollama_url, json=payload)
        
        if response.status_code == 200:
            print(f"  ✅ Model pre-heated successfully with keep_alive=-1", file=sys.stderr)
        else:
            print(f"  ⚠ Pre-heat warning (non-fatal): {response.status_code}", file=sys.stderr)
            
    except Exception as e:
        # Don't crash on pre-heat failure - voice module will still work
        print(f"  ⚠ Pre-heat error (non-fatal): {e}", file=sys.stderr, flush=True)


if __name__ == '__main__':
    sys.exit(main())
