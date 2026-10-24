"""Background thread scanning the USER's STT transcription for direct action commands; fires matching RPC actions in fire-and-forget daemon threads. Shares pidog_personality_engine's _last_fire cooldown dict."""

import queue
import re
import threading
import time
import sys
from itertools import chain

from pidog_actions_dictionary import (
    PERSONALITY_ACTIONS,
    MOVEMENT_ACTIONS,
)

from config import (
    COOLDOWN_SECONDS,
    MAX_ACTIONS_PER_MESSAGE,
    ENABLED,
    RETURN_TO_SIT_AFTER_ACTION,
)

from pidog_voice_rpc import _rpc_call_with_timeout

# Shared cooldown state: same _last_fire dict as pidog_personality_engine (mutated in place, never rebound).
from pidog_personality_engine import _last_fire

# Shared queue: voice module puts the USER's transcription here; engine thread reads it.
command_queue = queue.Queue(maxsize=64)

# Internal state
_engine_thread = None
_shutdown = threading.Event()


def _fire_rpc(rpc_client, method_name, args):
    """Fire a single RPC call in a daemon thread. Never raises."""
    def _worker():
        # Truthiness guard only - keep the early-out for a missing proxy.
        if not rpc_client:
            return
        # Route through the locked helper to serialize on the shared ServerProxy. Never raises.
        try:
            _rpc_call_with_timeout(method_name, *args)
        except Exception as e:
            print(f"  [COMMAND] RPC fire error on '{method_name}': {e}", file=sys.stderr, flush=True)
            return
        if RETURN_TO_SIT_AFTER_ACTION:
            try:
                _rpc_call_with_timeout('action', 'sit')
            except Exception:
                pass
    t = threading.Thread(target=_worker, daemon=True)
    t.start()


def _check_cooldown(method_name):
    """Return True if the action is allowed (not in cooldown); shares the personality engine's _last_fire dict (no double-fire)."""
    now = time.monotonic()
    last = _last_fire.get(method_name)
    if last is None:
        return True
    if (now - last) < COOLDOWN_SECONDS:
        return False
    return True


def _scan_text(text, rpc_client):
    """Scan the USER's transcription for triggers (word-boundary regex); matches all actions: PERSONALITY_ACTIONS plus MOVEMENT_ACTIONS."""
    if not ENABLED:
        return
    if not text or not isinstance(text, str):
        return
    if not rpc_client:
        return

    lowered = text.lower()
    fired = 0

    for phrase, (method_name, args) in chain(PERSONALITY_ACTIONS.items(), MOVEMENT_ACTIONS.items()):
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
        print(f"  [COMMAND] Fired '{method_name}' (trigger: '{phrase}')", file=sys.stderr, flush=True)


def _engine_loop(rpc_client):
    """Main loop: pull text from queue, scan, fire."""
    print("  [COMMAND] Engine thread started.", file=sys.stderr, flush=True)
    while not _shutdown.is_set():
        try:
            text = command_queue.get(timeout=1.0)
        except queue.Empty:
            continue
        try:
            _scan_text(text, rpc_client)
        except Exception as e:
            print(f"  [COMMAND] Scan error (non-fatal): {e}", file=sys.stderr, flush=True)
    print("  [COMMAND] Engine thread stopped.", file=sys.stderr, flush=True)


def start_command_engine(rpc_client):
    """Launch the command engine thread; call once after the RPC client is ready."""
    global _engine_thread
    if _engine_thread is not None and _engine_thread.is_alive():
        return
    _shutdown.clear()
    _engine_thread = threading.Thread(
        target=_engine_loop,
        args=(rpc_client,),
        daemon=True,
        name="pidog-command",
    )
    _engine_thread.start()
    print("  [COMMAND] Engine launched (daemon thread).", file=sys.stderr, flush=True)


def stop_command_engine():
    """Signal the engine thread to exit. Call during cleanup."""
    _shutdown.set()
    if _engine_thread is not None:
        _engine_thread.join(timeout=3.0)
    print("  [COMMAND] Engine stopped.", file=sys.stderr, flush=True)
