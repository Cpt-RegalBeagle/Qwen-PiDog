import xmlrpc.client as xmlrpc_client
import signal
import os
import time
import sys

def _rpc_call_with_timeout(method_name, *args):
    """Make an RPC call with error handling - POSITIONAL ONLY"""
    global rpc_client
    
    if rpc_client is None:
        raise Exception("RPC client not initialized")
    
    try:
        # CRITICAL: Only accept positional arguments - no kwargs allowed
        result = getattr(rpc_client, method_name)(*args)
        return result
    except Exception as e:
        error_msg = str(e).lower()
        # Only catch ACTUAL critical errors - connection failures
        if any(keyword in error_msg for keyword in [
            "connection refused",
            "connection reset",
            "network unreachable",
            "timed out",
            "connection aborted",
            "no route to host"
        ]):
            print(f"  [RPC] CRITICAL: RPC server unreachable! {error_msg}", file=sys.stderr, flush=True)
            raise ConnectionError("RPC server unreachable")
        else:
            # Re-raise all other errors - no silent failures or warnings
            raise


def _setup_rpc_client():
    """Setup XML-RPC client to communicate with pidog_init.py hardware RPC server"""
    global rpc_client
    
    try:
        # CRITICAL FIX: Use proper localhost address for hardware RPC server
        # The daemonized pidog_init.py runs on 127.0.0.1:8001 (NOT 127.0)
        server_url = "http://127.0.0.1:8001"
        rpc_client = xmlrpc_client.ServerProxy(server_url)
        
        return True
        
    except Exception as e:
        print(f"  [RPC] Failed to connect to XML-RPC server: {e}", file=sys.stderr)
        return False


def _rpc_call(method_name, *args):
    """Make an RPC call with error handling - POSITIONAL ONLY"""
    global rpc_client
    
    if rpc_client is None:
        raise Exception("RPC client not initialized")
    
    try:
        # CRITICAL: Only accept positional arguments - no kwargs allowed
        result = getattr(rpc_client, method_name)(*args)
        return result
    except Exception as e:
        print(f"  [RPC] Error calling {method_name}: {e}", file=sys.stderr)
        raise


def _send_sigterm_to_parent():
    """Send SIGTERM to parent process (main.py) on critical errors"""
    try:
        import signal
        
        # Get parent PID (the process that spawned us)
        parent_pid = os.getppid()
        
        if parent_pid > 1:
            print(f"  [VOICE PROFILE] CRITICAL ERROR - Sending SIGTERM to parent PID {parent_pid}", file=sys.stderr)
            os.kill(parent_pid, signal.SIGTERM)
            
            # Wait briefly for main.py to respond before exiting
            time.sleep(0.5)
            
    except Exception as e:
        print(f"  [VOICE PROFILE] Failed to send SIGTERM: {e}", file=sys.stderr)


def _critical_error_exit(message):
    """Exit immediately on critical error - let main.py handle cleanup"""
    print(f"  [VOICE PROFILE] CRITICAL ERROR: {message}", file=sys.stderr, flush=True)
    os._exit(1)
