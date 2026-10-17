"""
pidog_personality_engine.py
Background thread that scans AI response text for personality triggers
and fires matching RPC actions in fire-and-forget daemon threads.

Integration (ONE line in pidog_voice_audio.py, inside _stream_and_speak):

    from pidog_personality_engine import personality_queue
    personality_queue.put(full_response)

That is the only modification to the voice module.

Matching is case-insensitive: "Yes" (sentence start) and "yes"
(mid-sentence) both trigger the "yes" entry in PERSONALITY_ACTIONS.
"""

import queue
import threading
import time
import sys

from pidog_actions_dictionary import (
    PERSONALITY_ACTIONS,
    COOLDOWN_SECONDS,
    MAX_ACTIONS_PER_MESSAGE,
    ENABLED,
    RETURN_TO_SIT_AFTER_ACTION,
)

# Shared queue: voice module puts text here, engine thread reads it.
personality_queue = queue.Queue(maxsize=64)

# Internal state
_last_fire = {}
_engine_thread = None
_shutdown = threading.Event()


def _fire_rpc(rpc_client, method_name, args):
    """Fire a single RPC call in a daemon thread. Never raises."""
    def _worker():
        try:
            method = getattr(rpc_client, method_name, None)
        except Exception:
            return
        if method is None:
            return
        try:
            if args:
                method(*args)
            else:
                method()
        except Exception as e:
            print(f"  [PERSONALITY] RPC fire error on '{method_name}': {e}", file=sys.stderr, flush=True)
            return
        # Return to sitting position after personality action completes
        if RETURN_TO_SIT_AFTER_ACTION:
            try:
                rpc_client.action('sit')
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
    """
    Scan text for triggers, fire up to MAX_ACTIONS_PER_MESSAGE actions.

    Matching is case-insensitive substring scan:
      - "Yes, that's right!" matches trigger "yes" (capital Y, sentence start)
      - "I think yes is correct" matches trigger "yes" (lowercase, mid-sentence)
    Both forms are detected because we compare lowered text against lowered phrases.
    """
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
        if phrase.lower() not in lowered:
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
    """
    Launch the personality engine thread.
    Call once after the RPC client is ready.
    """
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
