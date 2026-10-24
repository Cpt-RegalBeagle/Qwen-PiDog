import sys
import os
import time
import config

# ==================== GLOBAL STATE ====================
dog = None



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
        
        # Keep stdout/stderr visible for debugging; only stdin is redirected
        
    except Exception as e:
        print(f"❌ Daemonization failed: {e}", file=sys.stderr, flush=True)
        os._exit(1)


def _run_xml_rpc_server_loop():
    """Standalone function to run the XML-RPC server loop - called by forked child"""
    global dog
    
    # Daemonize before running RPC server
    _daemonize()
    
    print("📡 [RPC] Starting RPC server event loop in daemonized context...", flush=True)
    print(f"  [RPC_SERVER] PID: {os.getpid()} starting", file=sys.stderr, flush=True)
    
    # Child must init hardware itself; parent's dog is not accessible post-fork
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
            rpc_server = SimpleXMLRPCServer(('0.0.0.0', config.PORT_XMLRPC), logRequests=False)
            
            # Instantiate once so network and thread share memory
            active_handler = PidogRPCHandler(dog)
            rpc_server.register_instance(active_handler)
            print("  📡 [RPC] Registered primary PidogRPCHandler instance to socket matrix.", file=sys.stderr, flush=True)
        else:
            # Create minimal server with fallback handler
            rpc_server = SimpleXMLRPCServer(('0.0.0.0', config.PORT_XMLRPC), logRequests=False)
            rpc_server.register_instance(MinimalRPCHandler())
        
        
        # serve_forever() for proper daemon behavior
        rpc_server.serve_forever()
        
    except Exception as e:
        print(f"❌ RPC server failed to start: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        os._exit(1)


def run():
    """Parent: fork RPC daemon, run hardware self-tests, exit"""
    
    # Parent does NOT init hardware - waits for child to fork and initialize
    print("🤖 [1/4] Waiting for child process to initialize hardware...", flush=True)
    print(f"  [PARENT] PID: {os.getpid()} starting", file=sys.stderr, flush=True)
    
    print("📡 [2/4] Launching XML-RPC Server as orphaned daemon process...", flush=True)

    # Double-fork daemonization - NOT threading
    try:
        pid = os.fork()
        if pid > 0:
            # PARENT: wait for RPC port, verify child hardware, run self-tests
            import socket
            
            max_retries = 5
            retry_delay = 0.5
            
            for attempt in range(max_retries):
                sock = None
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(2)
                    
                    result = sock.connect_ex(('localhost', config.PORT_XMLRPC))
                    if result == 0:
                        print(f"  ✅ Port 8001 is open and accepting connections (attempt {attempt + 1})", flush=True)
                        break
                except Exception:
                    pass
                finally:
                    if sock is not None:
                        sock.close()
                
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
            
            # Wait for child hardware ready before tests
            max_wait_attempts = 20
            wait_delay = 1.0
            
            for attempt in range(max_wait_attempts):
                try:
                    # Check if child is still initializing by trying a simple RPC call
                    import xmlrpc.client as xmlrpc_client
                    rpc_client = xmlrpc_client.ServerProxy(f"http://localhost:{config.PORT_XMLRPC}")
                        
                    result = rpc_client.status()
                        
                    if result and 'initialized' in str(result).lower():
                        print(f"  ✅ Child hardware ready (attempt {attempt + 1}/{max_wait_attempts})", flush=True)
                        break
                        
                except Exception as e:
                    pass
                    
                if attempt < max_wait_attempts - 1:
                    time.sleep(wait_delay)
            
            # If loop ends without breaking, child didn't initialize
            if attempt >= max_wait_attempts - 1:
                print(f"  ❌ Child hardware initialization timeout after {max_wait_attempts * wait_delay}s", file=sys.stderr, flush=True)
                sys.exit(1)

            # Run loopback verification tests (port + hardware ready)
            test_results = []
            
            try:
                # Local RPC client for API handler tests
                rpc_url = f"http://localhost:{config.PORT_XMLRPC}"
                import xmlrpc.client as xmlrpc_client
                rpc_client = xmlrpc_client.ServerProxy(rpc_url)
                
                # Test sit action via RPC
                print("  Testing sit action via RPC...", flush=True)
                try:
                    result = rpc_client.action('sit')
                    
                    if result and result.get('status') == 'success':
                        test_results.append(("Sit Action", True))
                        print(f"  ✅ Sit action started", flush=True)
                        
                        # Parent cannot wait on child actions - settle pause
                        time.sleep(1.0)
                        
                        print(f"  ✅ Sit action completed via RPC", flush=True)
                    else:
                        test_results.append(("Sit Action", False))
                        print(f"  ❌ Sit action failed: {result}", flush=True)
                except Exception as e:
                    print(f"  ❌ Sit action RPC error: {e}", file=sys.stderr, flush=True)
                    test_results.append(("Sit Action", False))

                # Settle: flush I2C/I2S buffers
                time.sleep(1.0)

                # Test tail wag via RPC
                print("  Testing tail wag via RPC...", flush=True)
                try:
                    result = rpc_client.wag_tail()
                    
                    if result and result.get('status') == 'success':
                        test_results.append(("Tail Wag", True))
                        
                        time.sleep(6.0)
                        
                        rpc_client.tail_stop()
                        # Parent cannot wait on child actions - settle pause
                        time.sleep(1.0)
                        
                        print(f"  ✅ Tail wag completed via RPC", flush=True)
                    else:
                        test_results.append(("Tail Wag", False))
                        print(f"  ❌ Tail wag failed: {result}", flush=True)
                except Exception as e:
                    try:
                        rpc_client.tail_stop()
                    except Exception:
                        pass
                    print(f"  ❌ Tail wag RPC error: {e}", file=sys.stderr, flush=True)
                    test_results.append(("Tail Wag", False))

                # Settle: flush I2C/I2S buffers
                time.sleep(1.0)

                # Test head shake via RPC
                print("  Testing head shake via RPC...", flush=True)

                try:
                    result = rpc_client.shake_head()
                    
                    if result and result.get('status') == 'success':
                        test_results.append(("Head Shake", True))
                        
                        time.sleep(3.0)
                        
                        rpc_client.head_stop()
                        # Parent cannot wait on child actions - settle pause
                        time.sleep(1.0)
                        
                        print(f"  ✅ Head shake completed via RPC", flush=True)
                    else:
                        test_results.append(("Head Shake", False))
                        print(f"  ❌ Head shake failed: {result}", flush=True)
                except Exception as e:
                    print(f"  ❌ Head shake RPC error: {e}", file=sys.stderr, flush=True)
                    test_results.append(("Head Shake", False))

                # Settle: flush I2C/I2S buffers
                time.sleep(1.0)

                # Test audio input via RPC (arecord on server side)
                print("  Testing audio input via RPC...", flush=True)
                try:
                    result = rpc_client.audio_record(1, config.SELF_TEST_AUDIO_PATH)
                    if result and result.get('status') == 'success':
                        test_results.append(("Audio Input", True))
                        print(f"  ✅ Audio recording completed: {result}", flush=True)
                    else:
                        test_results.append(("Audio Input", False))
                        print(f"  ❌ Audio recording failed: {result}", file=sys.stderr, flush=True)
                except Exception as e:
                    print(f"  ❌ Audio input RPC error: {e}", file=sys.stderr, flush=True)
                    test_results.append(("Audio Input", False))

                # Settle: flush PipeWire buffers
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

                # Settle: flush I2C buffers
                time.sleep(1.0)

                # Test camera capture via RPC
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

                # Settle: flush camera I2C bus
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
            
            # Hand off to main.py (exit; RPC daemon survives)
            print("🚀 [4/4] Handing control back to main.py (RPC remains active)...", flush=True)

            # Exit cleanly; double-forked RPC daemon survives as orphan
            print("  🚪 pidog_init.py exiting - RPC server daemon is orphaned and running", file=sys.stderr, flush=True)

            sys.exit(0 if all_passed else 1)
            
        else:
            # CHILD (pid == 0): init hardware + RPC server
            print("  [CHILD] Forked successfully (PID: {}) - initializing hardware and RPC server...".format(os.getpid()), file=sys.stderr, flush=True)
            
            # Child entry: Pidog init, RPC server on 8001, serve_forever()
            _run_xml_rpc_server_loop()
    except OSError as e:
        print(f"❌ Failed to fork daemon process: {e}", file=sys.stderr, flush=True)
        sys.exit(1)


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
