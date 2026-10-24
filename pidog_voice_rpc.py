import xmlrpc.client as xmlrpc_client
import http.client
import os
import time
import sys
import threading
import config

rpc_client = None
# Serializes ALL access to the single shared ServerProxy (ServerProxy is NOT
# thread-safe: it reuses one internal http.client.HTTPConnection).
_RPC_LOCK = threading.Lock()

# Transient socket errors that poison a ServerProxy's shared HTTP connection.
# On these we re-establish the proxy once and retry the same call.
_TRANSIENT_ERRORS = (
    http.client.ResponseNotReady,
    http.client.BadStatusLine,
    http.client.CannotSendRequest,
    ConnectionResetError,
)


class _TimeoutTransport(xmlrpc_client.Transport):
    """Transport with a hard 20s socket timeout (H1); a stuck handler must not block the caller forever.
    On timeout the call raises TimeoutError, which _classify() maps to ConnectionError (fail-fast, no retry).
    `socket_timeout` overrides the 20s default for a DEDICATED proxy; None keeps the class default."""

    SOCKET_TIMEOUT = 20

    def __init__(self, socket_timeout=None):
        super().__init__()
        if socket_timeout is not None:
            self.SOCKET_TIMEOUT = socket_timeout

    def make_connection(self, host):
        if isinstance(host, tuple):
            return http.client.HTTPConnection(host[0], host[1], timeout=self.SOCKET_TIMEOUT)
        return http.client.HTTPConnection(host, timeout=self.SOCKET_TIMEOUT)


def _build_proxy(socket_timeout=None):
    """Build a fresh ServerProxy WITHOUT touching the shared rpc_client global (DEDICATED-proxy support).
    `socket_timeout` overrides the 20s class default; None keeps it. Shared client only (re)assigned by _create_proxy() under _RPC_LOCK."""
    server_url = f"http://127.0.0.1:{config.PORT_XMLRPC}"
    return xmlrpc_client.ServerProxy(server_url, transport=_TimeoutTransport(socket_timeout))


def _create_proxy():
    """Create a fresh ServerProxy and assign it to the rpc_client global (caller must hold _RPC_LOCK; assigned only on success)."""
    global rpc_client

    new_client = _build_proxy()
    rpc_client = new_client
    return new_client


def _setup_rpc_client():
    """Setup XML-RPC client to pidog_init.py hardware RPC server (idempotent, thread-safe)."""
    try:
        with _RPC_LOCK:
            if rpc_client is not None:
                # Already configured - idempotent, keep existing client.
                return True
            _create_proxy()
        return True
    except Exception as e:
        print(f"  [RPC] Failed to connect to XML-RPC server: {e}", file=sys.stderr, flush=True)
        return False


def _invoke_locked(method_name, args):
    """Run a single RPC under _RPC_LOCK with transient-socket recovery.
    Transient socket errors: re-establish the proxy and retry the SAME call exactly once under lock.
    Socket timeout = fail-fast, no retry (a fresh proxy cannot unstick a busy handler).
    `args` is a tuple of positional arguments only; never swallows errors."""
    global rpc_client

    if rpc_client is None:
        raise Exception("RPC client not initialized")

    def _do_call():
        # CRITICAL: Only accept positional arguments - no kwargs allowed
        return getattr(rpc_client, method_name)(*args)

    def _classify(exc):
        # Fail-fast on socket timeouts (H1 _TimeoutTransport): the
        # single-threaded server handler is stuck; a fresh client proxy
        # cannot unstick it, so no retry - classify as critical now.
        if isinstance(exc, TimeoutError):
            print("  [RPC] CRITICAL: RPC server unresponsive (socket timeout)", file=sys.stderr, flush=True)
            raise ConnectionError("RPC server unreachable") from exc
        error_msg = str(exc).lower()
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
            raise ConnectionError("RPC server unreachable") from exc
        # Re-raise all other errors - no silent failures or warnings
        raise

    with _RPC_LOCK:
        try:
            return _do_call()
        except Exception as e:
            if isinstance(e, _TRANSIENT_ERRORS):
                # Poisoned connection: re-establish once (lock already held)
                # and retry the SAME call exactly once.
                _create_proxy()
                try:
                    result = _do_call()
                    print("  [RPC] Transient socket error, re-established connection and retried once", file=sys.stderr, flush=True)
                    return result
                except Exception as retry_exc:
                    # Retry also failed - classify/propagate as usual.
                    _classify(retry_exc)
            else:
                _classify(e)


def _rpc_call_with_timeout(method_name, *args):
    """Make an RPC call with error handling - POSITIONAL ONLY"""
    return _invoke_locked(method_name, args)


def _rpc_call(method_name, *args):
    """Make an RPC call with error handling - POSITIONAL ONLY"""
    return _invoke_locked(method_name, args)


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
