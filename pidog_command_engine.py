"""
pidog_command_engine.py
Background thread that scans the USER's STT transcription for direct
action commands and fires matching RPC actions in fire-and-forget daemon
threads.

This is the locomotion-capable sibling of pidog_personality_engine.py.
Where the personality engine filters the LLM's response text (what the
robot says back), this engine filters the USER's transcription (what
Carter says to the robot) and matches ALL actions - both stationary
PERSONALITY_ACTIONS and locomotive MOVEMENT_ACTIONS.

Integration (pidog_voice_audio.py, inside _send_audio_to_stt):

    from pidog_command_engine import command_queue
    command_queue.put_nowait(transcription)

That is the only modification to the voice module.

Matching uses word-boundary regex so "walk" triggers on "Walk over here!"
but NOT on "walkway" or "walked".

Shared cooldown: this engine imports the personality engine's module-level
_last_fire dict and uses it for its own cooldown checks. That way a command
the user says ("let's dance") and the LLM's echo of it ("Let's dance!")
cannot double-fire the same action within COOLDOWN_SECONDS. Dict get/set is
GIL-atomic, so no lock is needed.
"""

import queue
import re
import threading
import time
import sys
from itertools import chain

from pidog_actions_dictionary import (
    PERSONALITY_ACTIONS,
    MOVEMENT_ACTIONS,
    COOLDOWN_SECONDS,
    MAX_ACTIONS_PER_MESSAGE,
    ENABLED,
    RETURN_TO_SIT_AFTER_ACTION,
)

from pidog_voice_rpc import _rpc_call_with_timeout

# Shared cooldown state: the SAME dict the personality engine reads/writes.
# Importing the name binds us to the same dict object; both engines mutate
# it in place (never rebind it), so the reference stays valid.
from pidog_personality_engine import _last_fire

# Shared queue: voice module puts the USER's transcription here, engine
# thread reads it.
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
        # Route through the locked helper so we serialize with the audio
        # worker on the shared ServerProxy. Never raises.
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
    """Return True if the action is allowed (not in cooldown).

    Reads the personality engine's shared _last_fire dict so a user command
    and the LLM's echo of it share one cooldown window (no double-fire).
    """
    now = time.monotonic()
    last = _last_fire.get(method_name)
    if last is None:
        return True
    if (now - last) < COOLDOWN_SECONDS:
        return False
    return True


def _scan_text(text, rpc_client):
    """
    Scan the USER's transcription for triggers using word-boundary regex.

    Matches ALL actions: stationary PERSONALITY_ACTIONS plus locomotive
    MOVEMENT_ACTIONS. "walk" matches "Walk over here!" but NOT "walkway".
    """
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
    """
    Launch the command engine thread.
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
