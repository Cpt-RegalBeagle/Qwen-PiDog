"""Scan AI response text for personality triggers and fire matching RPC actions."""

import queue
import re
import threading
import time
import sys

from pidog_actions_dictionary import (
    PERSONALITY_ACTIONS,
)

from config import (
    COOLDOWN_SECONDS,
    MAX_ACTIONS_PER_MESSAGE,
    ENABLED,
    RETURN_TO_SIT_AFTER_ACTION,
)

from pidog_voice_rpc import _rpc_call_with_timeout

# Shared queue: voice module puts text here, engine thread reads it.
personality_queue = queue.Queue(maxsize=64)

# Internal state
_last_fire = {}
_engine_thread = None
_shutdown = threading.Event()


def _fire_rpc(rpc_client, method_name, args):
    """Fire a single RPC call in a daemon thread. Never raises."""
    def _worker():
        # Skip if proxy missing.
        if not rpc_client:
            return
        # Serialize via locked RPC helper; never raises.
        try:
            _rpc_call_with_timeout(method_name, *args)
        except Exception as e:
            print(f"  [PERSONALITY] RPC fire error on '{method_name}': {e}", file=sys.stderr, flush=True)
            return
        if RETURN_TO_SIT_AFTER_ACTION:
            try:
                _rpc_call_with_timeout('action', 'sit')
            except Exception:
                pass
    t = threading.Thread(target=_worker, daemon=True)
    t.start()


def _check_cooldown(method_name):
    """Return True if the action is allowed (not in cooldown)."""
    now = time.monotonic()
    last = _last_fire.get(method_name)
    if last is None:
        return True
    if (now - last) < COOLDOWN_SECONDS:
        return False
    return True


def _scan_text(text, rpc_client):
    """Match triggers in text using word-boundary regex."""
    if not ENABLED:
        return
    if not text or not isinstance(text, str):
        return
    if not rpc_client:
        return

    lowered = text.lower()
    fired = 0

    for phrase, (method_name, args) in PERSONALITY_ACTIONS.items():
        if fired >= MAX_ACTIONS_PER_MESSAGE:
            break
        pattern = r'\b' + re.escape(phrase.lower()) + r'\b'
        if not re.search(pattern, lowered):
            continue
        if not _check_cooldown(method_name):
            continue
        _last_fire[method_name] = time.monotonic()
        _fire_rpc(rpc_client, method_name, args)
        fired += 1
        print(f"  [PERSONALITY] Fired '{method_name}' (trigger: '{phrase}')", file=sys.stderr, flush=True)


def _engine_loop(rpc_client):
    """Main loop: pull text from queue, scan, fire."""
    print("  [PERSONALITY] Engine thread started.", file=sys.stderr, flush=True)
    while not _shutdown.is_set():
        try:
            text = personality_queue.get(timeout=1.0)
        except queue.Empty:
            continue
        try:
            _scan_text(text, rpc_client)
        except Exception as e:
            print(f"  [PERSONALITY] Scan error (non-fatal): {e}", file=sys.stderr, flush=True)
    print("  [PERSONALITY] Engine thread stopped.", file=sys.stderr, flush=True)


def start_personality_engine(rpc_client):
    """Launch the personality engine thread once RPC client is ready."""
    global _engine_thread
    if _engine_thread is not None and _engine_thread.is_alive():
        return
    _shutdown.clear()
    _engine_thread = threading.Thread(
        target=_engine_loop,
        args=(rpc_client,),
        daemon=True,
        name="pidog-personality",
    )
    _engine_thread.start()
    print("  [PERSONALITY] Engine launched (daemon thread).", file=sys.stderr, flush=True)


def stop_personality_engine():
    """Signal the engine thread to exit. Call during cleanup."""
    _shutdown.set()
    if _engine_thread is not None:
        _engine_thread.join(timeout=3.0)
    print("  [PERSONALITY] Engine stopped.", file=sys.stderr, flush=True)
