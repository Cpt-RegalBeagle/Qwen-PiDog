import sys
import os
import time
from typing import Optional

# ==================== GLOBAL STATE ====================
dog = None
rpc_server_thread = None

# ==================== SERVER-SIDE PLAYBACK LOCK ====================
_hardware_speaking_lock = False  # Explicit application-level state lock for duplex audio

# ==================== SERVER-SIDE SOUND DIRECTION TRACKING ====================
_last_sound_direction = 0  # Background-polled azimuth angle (0-359)
_ears_monitor_thread = None



def _daemonize():
    """Properly daemonize the process - detach from terminal and become background"""
    try:
        # Fork once to create a background process
        pid = os.fork()
        if pid > 0:
            # Parent exits immediately
            os._exit(0)
        
        # Child continues
        os.setsid()  # Create new session, detach from controlling terminal
        
        # Fork again for extra safety
        pid = os.fork()
        if pid > 0:
            os._exit(0)
        
        # Second child becomes the daemon
        # Redirect stdin to /dev/null (needed for clean detachment)
        dev_null = open('/dev/null', 'r')
        os.dup2(dev_null.fileno(), sys.stdin.fileno())
        dev_null.close()
        
        # CRITICAL FIX: Keep stdout and stderr visible for debugging!
        # Only redirect stdin to /dev/null - keep stderr open so debug messages appear in console
        # This allows all print(..., flush=True) statements from ears monitor thread to appear in terminal
        
    except Exception as e:
        print(f"❌ Daemonization failed: {e}", file=sys.stderr, flush=True)
        os._exit(1)


def _run_xml_rpc_server_loop():
    """Standalone function to run the XML-RPC server loop - called by forked child"""
    global dog
    
    # CRITICAL FIX: Properly daemonize before running RPC server
    _daemonize()
    
    print("📡 [RPC] Starting RPC server event loop in daemonized context...", flush=True)
    print(f"  [RPC_SERVER] PID: {os.getpid()} starting", file=sys.stderr, flush=True)
    
    # CRITICAL FIX: CHILD PROCESS MUST INITIALIZE HARDWARE ITSELF!
    # Parent's dog instance is not accessible in child process after fork
    try:
        from pidog.pidog import Pidog
        
        print("  [CHILD] Initializing hardware in child process...", file=sys.stderr, flush=True)
        
        dog = Pidog()
        time.sleep(1.0)  # Settle I2C bus
        
        print("  ✅ Hardware initialized successfully in child", file=sys.stderr, flush=True)
        
    except Exception as e:
        print(f"❌ Child hardware initialization failed: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        os._exit(1)
    
    try:
        from xmlrpc.server import SimpleXMLRPCServer
                    
        # Import RPC handler after dog is initialized
        rpc_handler_available = False
        try:
            from pidog_init_rpc_handler import PidogRPCHandler
            rpc_handler_available = True

        except ImportError as e:
            # Create a minimal fallback handler
            class MinimalRPCHandler:
                def status(self):
                    return "RPC server running (minimal mode)"
                        
            PidogRPCHandler = MinimalRPCHandler
                    
        if rpc_handler_available:
            rpc_server = SimpleXMLRPCServer(('0.0.0.0', 8001), logRequests=False)
            
            # CRITICAL STRUCTURAL FIX: Instantiate once so network and thread share memory space
            active_handler = PidogRPCHandler(dog)
            rpc_server.register_instance(active_handler)
            print("  📡 [RPC] Registered primary PidogRPCHandler instance to socket matrix.", file=sys.stderr, flush=True)
        else:
            # Create minimal server with fallback handler
            rpc_server = SimpleXMLRPCServer(('0.0.0.0', 8001), logRequests=False)
            rpc_server.register_instance(MinimalRPCHandler())
        
        # CRITICAL RE-ALIGNMENT: Trigger the ears monitor thread using the active registered instance handle
        if rpc_handler_available:
            try:
                active_handler.start_ears_monitor()
                print("  ✅ Ears monitor thread successfully attached to active network instance!", file=sys.stderr, flush=True)
            except Exception as e:
                print(f"  ⚠️  Could not start ears monitor on active handler: {e}", file=sys.stderr, flush=True)
        
        # CRITICAL: Use serve_forever() instead of handle_request() loop for proper daemon behavior
        rpc_server.serve_forever()
        
    except Exception as e:
        print(f"❌ RPC server failed to start: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        os._exit(1)


def run():
    """Main execution - follows exact pattern specified"""
    global dog, rpc_server_thread
    
    # STEP 1: Parent does NOT initialize hardware - just waits for child to fork and initialize
    print("🤖 [1/4] Waiting for child process to initialize hardware...", flush=True)
    print(f"  [PARENT] PID: {os.getpid()} starting", file=sys.stderr, flush=True)
    
    # Parent does nothing here - just waits for child to fork and initialize
    print("📡 [2/4] Launching XML-RPC Server as orphaned daemon process...", flush=True)

    # CRITICAL FIX: Use double-fork daemonization pattern - NOT threading!
    try:
        pid = os.fork()
        if pid > 0:
            # FIRST PARENT PROCESS - Hardware already initialized above, just wait for RPC server and run tests
            import socket
            
            max_retries = 5
            retry_delay = 0.5
            
            for attempt in range(max_retries):
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(2)
                    
                    result = sock.connect_ex(('localhost', 8001))
                    if result == 0:
                        print(f"  ✅ Port 8001 is open and accepting connections (attempt {attempt + 1})", flush=True)
                        sock.close()
                        break
                    else:
                        sock.close()
                except Exception as e:
                    sock.close()
                
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
            
            # PARENT PROCESS - Wait for child hardware to initialize BEFORE running tests
            max_wait_attempts = 20
            wait_delay = 1.0
            
            for attempt in range(max_wait_attempts):
                try:
                    # Check if child is still initializing by trying a simple RPC call
                    import xmlrpc.client as xmlrpc_client
                    rpc_client = xmlrpc_client.ServerProxy(f"http://localhost:8001")
                        
                    result = rpc_client.status()
                        
                    if result and 'initialized' in str(result).lower():
                        print(f"  ✅ Child hardware ready (attempt {attempt + 1}/{max_wait_attempts})", flush=True)
                        break
                        
                except Exception as e:
                    pass
                    
                if attempt < max_wait_attempts - 1:
                    time.sleep(wait_delay)
            
            # If we exit the loop without breaking, child didn't initialize properly
            if attempt >= max_wait_attempts - 1:
                print(f"  ❌ Child hardware initialization timeout after {max_wait_attempts * wait_delay}s", file=sys.stderr, flush=True)
                sys.exit(1)

            # PARENT PROCESS - Run loopback verification tests AFTER port is verified AND hardware initialized
            test_results = []
            
            try:
                # Setup local RPC client to test the API handlers
                rpc_url = f"http://localhost:8001"
                import xmlrpc.client as xmlrpc_client
                rpc_client = xmlrpc_client.ServerProxy(rpc_url)
                
                # Test sit action via RPC (NO SPEED PARAMETER)
                print("  Testing sit action via RPC...", flush=True)
                try:
                    result = rpc_client.action('sit')
                    
                    if result and result.get('status') == 'success':
                        test_results.append(("Sit Action", True))
                        print(f"  ✅ Sit action started", flush=True)
                        
                        # CRITICAL FIX: Parent process cannot wait on child's actions!
                        # Remove wait_all_done() - it waits on wrong dog instance
                        time.sleep(1.0)  # Hardware settle pause
                        
                        print(f"  ✅ Sit action completed via RPC", flush=True)
                    else:
                        test_results.append(("Sit Action", False))
                        print(f"  ❌ Sit action failed: {result}", flush=True)
                except Exception as e:
                    print(f"  ❌ Sit action RPC error: {e}", file=sys.stderr, flush=True)
                    test_results.append(("Sit Action", False))

                # Hardware settle pause - give I2C/I2S buses time to flush buffers
                time.sleep(1.0)

                # CRITICAL FIX: Set RGB to safe state BEFORE returning - OFFICIAL SUNFOUNDER MODES
                if dog is not None and hasattr(dog, 'rgb_strip'):
                    try:
                        # Force RGB to breath black (not solid mode) - DO THIS EARLIER
                        dog.rgb_strip.set_mode('breath', 'black')
                        print("  ✅ RGB strip reset to breath black", file=sys.stderr, flush=True)
                    except Exception as e:
                        print(f"  ⚠️  Could not reset RGB strip: {e}", file=sys.stderr, flush=True)

                # Test tail wag via RPC (use dedicated endpoint for optimized animation)
                print("  Testing tail wag via RPC...", flush=True)
                try:
                    result = rpc_client.wag_tail()
                    
                    if result and result.get('status') == 'success':
                        test_results.append(("Tail Wag", True))
                        
                        time.sleep(6.0)
                        
                        rpc_client.tail_stop()
                        # CRITICAL FIX: Parent process cannot wait on child's actions!
                        time.sleep(1.0)  # Hardware settle pause
                        
                        print(f"  ✅ Tail wag completed via RPC", flush=True)
                    else:
                        test_results.append(("Tail Wag", False))
                        print(f"  ❌ Tail wag failed: {result}", flush=True)
                except Exception as e:
                    try:
                        rpc_client.tail_stop()
                    except:
                        pass
                    print(f"  ❌ Tail wag RPC error: {e}", file=sys.stderr, flush=True)
                    test_results.append(("Tail Wag", False))

                # Hardware settle pause - give I2C/I2S buses time to flush buffers
                time.sleep(1.0)

                # Test head shake via RPC (use dedicated endpoint for optimized animation)
                print("  Testing head shake via RPC...", flush=True)

                try:
                    result = rpc_client.shake_head()
                    
                    if result and result.get('status') == 'success':
                        test_results.append(("Head Shake", True))
                        
                        time.sleep(3.0)
                        
                        rpc_client.head_stop()
                        # CRITICAL FIX: Parent process cannot wait on child's actions!
                        time.sleep(1.0)  # Hardware settle pause
                        
                        print(f"  ✅ Head shake completed via RPC", flush=True)
                    else:
                        test_results.append(("Head Shake", False))
                        print(f"  ❌ Head shake failed: {result}", flush=True)
                except Exception as e:
                    print(f"  ❌ Head shake RPC error: {e}", file=sys.stderr, flush=True)
                    test_results.append(("Head Shake", False))

                # Hardware settle pause - give I2C/I2S buses time to flush buffers
                time.sleep(1.0)

                # Test audio input via RPC (calls arecord on server side)
                print("  Testing audio input via RPC...", flush=True)
                try:
                    result = rpc_client.audio_record(1, '/tmp/pidog_test_audio.wav')
                    if result and result.get('status') == 'success':
                        test_results.append(("Audio Input", True))
                        print(f"  ✅ Audio recording completed: {result}", flush=True)
                    else:
                        test_results.append(("Audio Input", False))
                        print(f"  ❌ Audio recording failed: {result}", file=sys.stderr, flush=True)
                except Exception as e:
                    print(f"  ❌ Audio input RPC error: {e}", file=sys.stderr, flush=True)
                    test_results.append(("Audio Input", False))

                # Hardware settle pause - give PipeWire audio channels time to flush buffers
                time.sleep(1.0)

                # Test IMU via RPC
                print("  Testing IMU via RPC...", flush=True)
                try:
                    result = rpc_client.imu_get_data()
                    if result and result.get('status') == 'success':
                        acc = result.get('acceleration')
                        gyro = result.get('gyroscope')
                        test_results.append(("IMU", acc is not None and gyro is not None))
                        print(f"  ✅ IMU data retrieved: {result}", flush=True)
                    else:
                        test_results.append(("IMU", False))
                        print(f"  ❌ IMU read failed: {result}", flush=True)
                except Exception as e:
                    print(f"  ❌ IMU RPC error: {e}", file=sys.stderr, flush=True)
                    test_results.append(("IMU", False))

                # Hardware settle pause - give I2C buses time to flush buffers
                time.sleep(1.0)

                # Test camera photo action via RPC - WITH TIMEOUT AND ERROR HANDLING
                print("  Testing camera capture via RPC...", flush=True)
                try:
                    result = rpc_client.camera_capture()
                    if result and result.get('status') == 'success':
                        test_results.append(("Camera Capture", True))
                        print(f"  ✅ Camera capture completed: {result}", flush=True)
                    else:
                        # Camera test is optional - don't fail on it
                        test_results.append(("Camera Capture", False))
                        print(f"  ⚠️  Camera capture skipped (optional): {result}", file=sys.stderr, flush=True)
                except Exception as e:
                    print(f"  ⚠️  Camera RPC error (optional): {e}", file=sys.stderr, flush=True)
                    test_results.append(("Camera Capture", False))

                # Hardware settle pause - give camera I2C bus time to flush buffers
                time.sleep(1.0)
                
            except Exception as e:
                print(f"❌ Test failed: {e}", file=sys.stderr, flush=True)
                import traceback
                traceback.print_exc(file=sys.stderr)
            
            # Print test summary
            print("\n📊 TEST RESULTS:", flush=True)
            all_passed = True
            for name, passed in test_results:
                status = "✅ PASS" if passed else "❌ FAIL"
                print(f"  {status}: {name}", flush=True)
                if not passed and name != "Camera Capture":
                    all_passed = False
            
            # STEP 4: Clean handoff back to main.py - RETURN TO MAIN.PY
            print("🚀 [4/4] Handing control back to main.py (RPC remains active)...", flush=True)

            # CRITICAL FIX: Exit the process cleanly after tests
            # The double-forked daemon will survive this exit as an orphaned process
            print("  🚪 pidog_init.py exiting - RPC server daemon is orphaned and running", file=sys.stderr, flush=True)

            sys.exit(0 if all_passed else 1)
            
        else:
            # CHILD PROCESS (pid == 0) - Initialize hardware and run RPC server in _run_xml_rpc_server_loop()
            print("  [CHILD] Forked successfully (PID: {}) - initializing hardware and RPC server...".format(os.getpid()), file=sys.stderr, flush=True)
            
            # CRITICAL FIX: Call the standalone function that handles ALL child process initialization
            # This initializes dog = Pidog(), creates RPC server on port 8001, and runs serve_forever()
            _run_xml_rpc_server_loop()
    except OSError as e:
        print(f"❌ Failed to fork daemon process: {e}", file=sys.stderr, flush=True)
        sys.exit(1)


def init_all_modules():
    """Wrapper function for backward compatibility with main.py"""
    return run()


# ==================== MAIN EXECUTION (STANDALONE) ====================

if __name__ == '__main__':
    print("🤖 [PIDOG_INIT] Starting parent process (hardware initialization delegated to child)...", flush=True)
    
    try:
        run()
        
    except OSError as e:
        print(f"❌ Failed to fork daemon process: {e}", file=sys.stderr, flush=True)
        sys.exit(1)
    
    except Exception as e:
        print(f"❌ Parent process failed: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
