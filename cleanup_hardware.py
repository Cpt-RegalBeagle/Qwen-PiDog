#!/usr/bin/env python3
"""
cleanup_hardware.py - Hardware cleanup utility
Kills all python processes and resets hardware components.
Called by main.py for clean shutdown.
"""
import signal
import sys
import os
import time
import subprocess
import requests
import xmlrpc.client

# Import config to get module-level settings
import config


def kill_python_processes():
    """Kill ALL python3 processes including itself"""
    print("\n[Cleanup] Killing ALL python3 processes...")
    subprocess.run(['sudo', 'killall', 'python3', '-9'], capture_output=True)
    print("[Cleanup] All python3 processes killed", file=sys.stderr)

def _kill_remote_kokoro_via_api():
    bazzite_ip = config.SERVER_IP
    kill_url = f"http://{bazzite_ip}:8075/v4.0.0/libpod/containers/kokoro-backend/kill"

    print("  [CLEANUP] Force-killing remote Kokoro container...", file=sys.stderr)

    try:
        response = requests.post(kill_url, timeout=3)
        if response.status_code == 204:
            print("  ✅ Kokoro container terminated successfully.", file=sys.stderr)
        elif response.status_code == 404:
            print("  ⚠ Kokoro container is already dead or gone.", file=sys.stderr)
        elif response.status_code == 304:
            print("  ⚠ Kokoro container is not running, cannot kill.", file=sys.stderr)
        else:
            print(f"  ⚠ Unexpected response code: {response.status_code}", file=sys.stderr)
    except Exception as e:
        print(f"  ⚠ Remote kill skipped: {e}", file=sys.stderr, flush=True)

def cleanup_hardware(dog=None, skip_pidog_init=False):
    """Safely cleanup all hardware components"""
    success_count = 0
    failure_count = 0
    
    # CRITICAL: Print our own PID for debugging
    print(f"[Cleanup] ⚠️ cleanup_hardware.py running as PID: {os.getpid()}", file=sys.stderr)

    # Kill remote kokoro container via API
    _kill_remote_kokoro_via_api()

    # Reset all Robot-Hat modules using the native system call
    print("\n🧹 Resetting all Robot-Hat modules cleanly...", file=sys.stderr)
    
    try:
        # Create an XMLRPC client to connect to the server
        rpc_client = xmlrpc.client.ServerProxy(f"http://localhost:8001")
        
        # Call the close method on the XMLRPC client
        result = rpc_client.close()
        
        if result.get('status') == 'success':
            print("✅ Hardware reset complete. Pin states cleared.", file=sys.stderr)
            success_count += 1
        else:
            print(f"❌ Hardware reset failed: {result.get('message')}", file=sys.stderr)
            failure_count += 1
    except Exception as e:
        print(f"❌ XMLRPC call failed: {e}", file=sys.stderr)
        failure_count += 1

    # Step 2: Log any errors during cleanup
    if failure_count > 0:
        print(f"[Cleanup] {failure_count} errors during cleanup", file=sys.stderr)
    else:
        print("[Cleanup] All cleanup operations completed successfully", file=sys.stderr)
    
    try:
        # CRITICAL FIX: Kill ALL python3 processes FIRST (before anything else)
        print("\n[Cleanup] === KILLING ALL PYTHON PROCESSES IMMEDIATELY ===", file=sys.stderr)
        
        kill_python_processes()
        
        # Wait for all processes to terminate completely BEFORE listing them
        print("[Cleanup] Waiting for ALL processes to terminate...", file=sys.stderr)
        time.sleep(3)
        
        # CRITICAL FIX: Print running processes AFTER killing main.py (not before)
        print("\n[Cleanup] === DIAGNOSTIC: Running Processes AFTER KILLING MAIN.PY ===", file=sys.stderr)
        
        result = subprocess.run(['ps', '-u', 'pidog'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            lines = result.stdout.split('\n')
            for line in lines:
                if line.strip():
                    print(f"[Cleanup] {line}", file=sys.stderr)
        
        print("[Cleanup] === END DIAGNOSTIC ===\n", file=sys.stderr)

        # Wait for processes to terminate completely
        print("[Cleanup] Waiting for processes to terminate...", file=sys.stderr)
        time.sleep(2)

    except Exception as e:
        print(f"[Cleanup] Critical error during cleanup: {e}", file=sys.stderr)
        failure_count += 1

    # CRITICAL FIX: Always exit immediately - never fall through to more code
    sys.exit(failure_count)
