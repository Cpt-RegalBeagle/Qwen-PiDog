#!/usr/bin/env python3
"""
Isolated concurrency smoke test for the thread-safe XML-RPC client
(pidog_voice_rpc.py). Validates the _RPC_LOCK fix WITHOUT hardware.

Modes
-----
default  : If the real robot RPC server already owns 127.0.0.1:8001 and
           answers `status`, hammer ONLY the read-only `status` endpoint
           (real-stack mode - no hardware movement, no mic capture).
           Otherwise spin up an in-process single-threaded
           SimpleXMLRPCServer on 127.0.0.1:8001 (mock mode) with
           `status` + `audio_record` endpoints and hammer both - the same
           race topology as production (audio worker audio_record +
           main-loop status health checks + personality fire-threads).
           All locked-mode calls go through the PUBLIC
           pidog_voice_rpc._rpc_call_with_timeout entry point, i.e. the
           exact code path the audio worker, health check and personality
           engine use.
--baseline: Hammer a deliberately UNLOCKED raw shared ServerProxy (the
           pre-fix code) to prove this harness can detect the original
           ResponseNotReady corruption. Informational only (the bug is
           probabilistic, a clean baseline run does not invalidate the
           harness).

Usage
-----
  python3 test_rpc_concurrency_smoke.py             # real if up, else mock
  python3 test_rpc_concurrency_smoke.py --baseline  # demonstrate pre-fix bug

Exit codes: 0 = PASS, 1 = FAIL.
"""
import argparse
import os
import socket
import sys
import threading
import time
import traceback
import xmlrpc.client

HOST, PORT = "127.0.0.1", 8001
URL = "http://%s:%d" % (HOST, PORT)

# Real-stack mode topology (status only - safe, read-only endpoint).
STATUS_THREADS = 8
STATUS_CALLS = 30

# Mock mode adds the audio-record race (mirrors audio worker vs main loop).
AUDIO_THREADS = 4
AUDIO_CALLS = 10

# Errors that indicate shared-connection corruption (the original bug).
CORRUPTION_MARKERS = (
    "responsetnotready",
    "badstatusline",
    "cannotsendrequest",
    "request-sent",
)


def _port_open():
    try:
        with socket.create_connection((HOST, PORT), timeout=1.0):
            return True
    except OSError:
        return False


def _server_answers_status():
    try:
        probe = xmlrpc.client.ServerProxy(URL, timeout=3)
        probe.status()
        return True
    except Exception:
        return False


class MockPidogServer:
    """Single-threaded stand-in for pidog_init.py's XML-RPC server."""

    def __init__(self):
        from xmlrpc.server import SimpleXMLRPCServer
        self.server = SimpleXMLRPCServer((HOST, PORT), logRequests=False)
        self.server.register_function(self.status, "status")
        self.server.register_function(self.audio_record, "audio_record")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def status(self):
        return {"status": "ok", "initialized": True}

    def audio_record(self, duration, output_file):
        # Mimic a ~1s capture without hardware: produce a small file the
        # way the real handler does (file survives for the client to read).
        with open(output_file, "wb") as f:
            f.write(b"RIFF\x00\x00\x00\x00WAVEfmt fake payload")
        return {
            "status": "success",
            "message": "mock recorded %ss" % duration,
            "file_size": os.path.getsize(output_file),
            "output_file": output_file,
        }


def _start_mock():
    mock = MockPidogServer()
    mock.thread.start()
    deadline = time.time() + 5
    while not _port_open():
        if time.time() > deadline:
            raise RuntimeError("mock server did not come up on port %d" % PORT)
        time.sleep(0.05)
    return mock


def _hammer(invoker, label):
    """Run the multi-threaded hammer. invoker(kind, *args) executes one call.

    kind is 'status' or 'audio_record'. Returns (errors, counts, total, elapsed).
    """
    errors = []
    counts = {"status": 0, "audio": 0}
    err_lock = threading.Lock()
    mock_mode = label == "mock"
    total = STATUS_THREADS * STATUS_CALLS + (AUDIO_THREADS * AUDIO_CALLS if mock_mode else 0)

    def record(kind, err):
        with err_lock:
            errors.append((kind, repr(err)))

    def worker_status(i):
        for _ in range(STATUS_CALLS):
            try:
                invoker("status")
                with err_lock:
                    counts["status"] += 1
            except Exception as e:
                record("status", e)

    def worker_audio(i):
        path = "/tmp/pidog_smoke_audio_%d.wav" % i
        for _ in range(AUDIO_CALLS):
            try:
                invoker("audio_record", 1, path)
                with err_lock:
                    counts["audio"] += 1
            except Exception as e:
                record("audio_record", e)

    threads = [threading.Thread(target=worker_status, args=(i,)) for i in range(STATUS_THREADS)]
    if mock_mode:
        threads += [threading.Thread(target=worker_audio, args=(i,)) for i in range(AUDIO_THREADS)]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.time() - t0
    return errors, counts, total, elapsed


def _is_corruption(errors):
    for _, err in errors:
        low = err.lower()
        if any(m in low for m in CORRUPTION_MARKERS):
            return True
    return False


def _report(title, errors, counts, total, elapsed):
    print("=" * 64)
    print(title)
    print("  calls succeeded : %d / %d" % (counts["status"] + counts["audio"], total))
    print("  status calls    : %d / %d" % (counts["status"], STATUS_THREADS * STATUS_CALLS))
    if total > STATUS_THREADS * STATUS_CALLS:
        print("  audio calls     : %d / %d" % (counts["audio"], AUDIO_THREADS * AUDIO_CALLS))
    print("  errors          : %d" % len(errors))
    print("  wall time       : %.2fs" % elapsed)
    if errors:
        print("  first errors:")
        for kind, err in errors[:5]:
            print("    [%s] %s" % (kind, err))
    print("=" * 64)
    return not errors and (counts["status"] + counts["audio"]) >= total


def run_locked_hammer(real_mode):
    """Hammer pidog_voice_rpc's PUBLIC entry points (goes through _RPC_LOCK)."""
    import pidog_voice_rpc as rpc

    if not rpc._setup_rpc_client():
        print("FATAL: cannot connect to RPC server at %s" % URL, file=sys.stderr)
        sys.exit(1)

    label = "real" if real_mode else "mock"
    errors, counts, total, elapsed = _hammer(
        lambda kind, *a: rpc._rpc_call_with_timeout(kind, *a), label)
    passed = _report("LOCKED HAMMER (via pidog_voice_rpc._rpc_call_with_timeout)",
                     errors, counts, total, elapsed)
    if passed:
        print("PASS: %d concurrent calls, zero transport corruption." % (counts["status"] + counts["audio"]))
    else:
        print("FAIL: transport corruption or lost calls - see errors above.")
        if _is_corruption(errors):
            print("      (corruption signatures match the pre-fix ResponseNotReady bug)")
    return passed


def run_baseline():
    """Pre-fix behavior: raw shared ServerProxy, NO lock. Informational."""
    shared = xmlrpc.client.ServerProxy(URL)
    errors, counts, total, elapsed = _hammer(
        lambda kind, *a: getattr(shared, kind)(*a), "mock")
    _report("BASELINE (raw shared proxy, pre-fix behavior - informational)",
            errors, counts, total, elapsed)
    if _is_corruption(errors):
        print("BASELINE reproduced the pre-fix corruption (harness is discriminating).")
    elif errors:
        print("BASELINE saw non-corruption errors only.")
    else:
        print("BASELINE clean - corruption is probabilistic; a clean baseline")
        print("run does NOT invalidate the harness.")


def main():
    parser = argparse.ArgumentParser(description="XML-RPC concurrency smoke test")
    parser.add_argument("--baseline", action="store_true",
                        help="hammer a raw unlocked shared proxy (pre-fix demo)")
    args = parser.parse_args()

    real_mode = _port_open() and _server_answers_status()
    mock = None
    try:
        if real_mode:
            print("[SMOKE] Real RPC server detected on %s - real-stack mode (status only)." % URL)
        else:
            print("[SMOKE] No RPC server on %s - starting in-process mock." % URL)
            mock = _start_mock()
        if args.baseline:
            run_baseline()
        else:
            passed = run_locked_hammer(real_mode)
            sys.exit(0 if passed else 1)
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
    finally:
        if mock is not None:
            mock.server.shutdown()


if __name__ == "__main__":
    main()
