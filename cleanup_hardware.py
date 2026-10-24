#!/usr/bin/env python3
"""
cleanup_hardware.py - Hardware cleanup utility
Kills all python processes and resets hardware components.
Called by main.py for clean shutdown.
"""
import sys
import os
import time
import subprocess
import requests
import xmlrpc.client

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

def cleanup_hardware():
    """Safely cleanup all hardware components"""
    failure_count = 0
    
    # Log own PID
    print(f"[Cleanup] ⚠️ cleanup_hardware.py running as PID: {os.getpid()}", file=sys.stderr)

    # Kill remote kokoro container via API
    _kill_remote_kokoro_via_api()

    # Reset all Robot-Hat modules via XMLRPC call
    print("\n🧹 Resetting all Robot-Hat modules cleanly...", file=sys.stderr)
    
    try:
        # Connect to hardware reset server
        rpc_client = xmlrpc.client.ServerProxy(f"http://localhost:{config.PORT_XMLRPC}")
        
        # Trigger hardware close
        result = rpc_client.close()
        
        if result.get('status') == 'success':
            print("✅ Hardware reset complete. Pin states cleared.", file=sys.stderr)
        else:
            print(f"❌ Hardware reset failed: {result.get('message')}", file=sys.stderr)
            failure_count += 1
    except Exception as e:
        print(f"❌ XMLRPC call failed: {e}", file=sys.stderr)
        failure_count += 1

    # Log cleanup errors
    if failure_count > 0:
        print(f"[Cleanup] {failure_count} errors during cleanup", file=sys.stderr)
    else:
        print("[Cleanup] All cleanup operations completed successfully", file=sys.stderr)
    
    try:
        # Kill all python3 processes
        kill_python_processes()

        # Wait for processes to terminate
        time.sleep(2)

    except Exception as e:
        print(f"[Cleanup] Critical error during cleanup: {e}", file=sys.stderr)
        failure_count += 1

    # Exit immediately with failure count
    sys.exit(failure_count)
