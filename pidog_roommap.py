#!/usr/bin/env python3
"""
PiDog room mapping (dead-reckoned).

A parked daemon thread watches for config.ROOMMAP_TRIGGER_FILE. On
trigger it removes the trigger, stands the dog up and runs a bounded
multi-cluster scan: 4x 90-deg body frames x a head sweep in
ROOMMAP_YAW_STEP_DEG steps, one ultrasonic sample per step. Position is
dead-reckoned from 90-deg body turns and one trot step per cluster.
The result (samples + 10 cm free/occupied grid) is saved atomically to
ROOMMAP_DIR and mirrored to ROOMMAP_LATEST_FILE.

Stdlib only. All hardware access goes through the injected RPC callable:
    rpc(method_name, *args)
"""
import json
import logging
import math
import os
import threading
import time

import config

log = logging.getLogger("roommap")

last_beat = time.time()

_shutdown = threading.Event()
_thread = None

_GRID_CELL_M = 0.10      # 10 cm grid cells
_GRID_STEP_CM = 10.0     # ray walk step in cm


class _ScanAborted(Exception):
    """Internal: RPC failed mid-scan; abort to parked with best-effort save."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def heartbeat():
    global last_beat
    last_beat = time.time()


def start_roommap(rpc):
    """Start the daemon roommap thread and return it.

    rpc: callable(method_name, *args) — the daemon-side RPC bridge.
    """
    global _thread
    os.makedirs(config.ROOMMAP_DIR, exist_ok=True)
    _thread = threading.Thread(target=_roommap_loop, args=(rpc,),
                               name="pidog-roommap", daemon=True)
    _thread.start()
    return _thread


def stop_roommap(timeout=10):
    """Set the shutdown event and join the thread (bounded by timeout)."""
    _shutdown.set()
    if _thread is not None:
        _thread.join(timeout)


def latest_map():
    """Parsed JSON of config.ROOMMAP_LATEST_FILE, or None on missing/corrupt."""
    try:
        with open(config.ROOMMAP_LATEST_FILE, "r") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def load_map(path):
    """json.load wrapper: dict on success, None on missing/corrupt/non-dict."""
    try:
        with open(path, "r") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# Parked loop
# ---------------------------------------------------------------------------

def _roommap_loop(rpc):
    """PARKED: poll every 0.5 s for the trigger file; on trigger, remove it
    and run a full scan, then back to parked."""
    while not _shutdown.is_set():
        heartbeat()
        if os.path.exists(config.ROOMMAP_TRIGGER_FILE):
            try:
                os.remove(config.ROOMMAP_TRIGGER_FILE)
            except OSError:
                log.exception("could not remove trigger file")
            _run_scan(rpc)
            continue  # back to parked
        _shutdown.wait(0.5)


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

def _run_scan(rpc):
    """Full scan: focus on, stand, sweep, step, save, sit.

    Never raises: any failure is logged, saved best-effort, and the focus
    file is always removed in the finally block.
    """
    state = {
        "x": 0.0,
        "y": 0.0,
        "body_heading": 0.0,
        "samples": [],
        "t_start": time.monotonic(),
        "clusters": 0,
        "saved": False,
    }
    try:
        # 1. Focus file (other modules see we own the head).
        try:
            with open(config.ROOMMAP_FOCUS_FILE, "w") as fh:
                fh.write("1\n")
        except OSError:
            log.exception("could not write focus file")

        # 2. Kill in-flight TTS (best effort).
        _safe_rpc(rpc, "music_stop")

        # 3. Stand up.
        _guarded_rpc(rpc, state, "action", "stand")

        # 4. Multi-cluster sweep + dead-reckoned stepping.
        for cluster in range(1, config.ROOMMAP_MAX_CLUSTERS + 1):
            if time.monotonic() - state["t_start"] > config.ROOMMAP_MAX_DURATION_S:
                log.info("duration cap (%ss) reached; ending scan",
                         config.ROOMMAP_MAX_DURATION_S)
                break

            # Full 360-deg sweep in the current body frame.
            stopped = False
            for heading_idx in range(4):
                base_yaw = heading_idx * 90
                for yaw in range(-90, 91, config.ROOMMAP_YAW_STEP_DEG):
                    if time.monotonic() - state["t_start"] > config.ROOMMAP_MAX_DURATION_S:
                        stopped = True  # duration cap, checked per sample
                        break
                    heartbeat()
                    touch = _guarded_rpc(rpc, state, "touch_read")
                    if touch != "N":
                        _touch_stop(rpc, state, touch)
                        return
                    _guarded_rpc(rpc, state, "head_move", yaw, 0, 0)
                    _guarded_rpc(rpc, state, "wait_head_done", 15.0)
                    d = float(_guarded_rpc(rpc, state, "read_distance"))
                    state["samples"].append({
                        "x": state["x"],
                        "y": state["y"],
                        "abs_yaw": (base_yaw + yaw) % 360,
                        "d": d,  # kept as-is; -1.0 = no echo
                    })
                if stopped:
                    break
            if stopped:
                log.info("duration cap (%ss) reached; ending scan",
                         config.ROOMMAP_MAX_DURATION_S)
                break

            # Move decision: clearest of the 4 body-relative cardinals.
            best_rel, best_clear = _choose_direction(state["samples"],
                                                     state["body_heading"])
            if best_clear < config.ROOMMAP_MIN_CLEAR_CM:
                log.info("fully blocked (best clear %.1f cm); ending scan",
                         best_clear)
                break

            # Turn to best_dir with the fewest 90-deg steps, then one step.
            _turn_to(rpc, state, best_rel)
            _guarded_rpc(rpc, state, "action", "trot")  # blocks to completion
            step_m = config.ROOMMAP_STEP_CM / 100.0
            rad = math.radians(state["body_heading"])
            state["x"] += step_m * math.cos(rad)
            state["y"] += step_m * math.sin(rad)
            state["clusters"] = cluster

            # Re-check touch after the move (same stop path).
            touch = _guarded_rpc(rpc, state, "touch_read")
            if touch != "N":
                _touch_stop(rpc, state, touch)
                return

        # 5-6. Save the map (atomic).
        _save_partial(state)

        # 7. Sit down (best effort).
        _safe_rpc(rpc, "action", "sit")
    except Exception:
        log.exception("roommap scan aborted")
        _save_partial(state)  # best effort; no-op if already saved
        _safe_rpc(rpc, "action", "sit")
    finally:
        # 8. ALWAYS drop the focus file.
        try:
            os.remove(config.ROOMMAP_FOCUS_FILE)
        except OSError:
            pass


def _touch_stop(rpc, state, touch):
    """Touch interrupt: save, sit (focus off happens in _run_scan finally)."""
    log.info("touch interrupt during scan: %r", touch)
    _save_partial(state)
    _safe_rpc(rpc, "action", "sit")


# ---------------------------------------------------------------------------
# RPC wrappers
# ---------------------------------------------------------------------------

def _safe_rpc(rpc, method, *args):
    """Fire-and-forget RPC: log and swallow any exception."""
    try:
        return rpc(method, *args)
    except Exception:
        log.exception("rpc %r failed (ignored)", method)
        return None


def _guarded_rpc(rpc, state, method, *args):
    """Scan-critical RPC: on failure, best-effort save and abort the scan."""
    try:
        return rpc(method, *args)
    except Exception:
        log.exception("rpc %r failed; aborting scan", method)
        _save_partial(state)
        raise _ScanAborted()


# ---------------------------------------------------------------------------
# Move decision
# ---------------------------------------------------------------------------

def _ang_diff(a, b):
    """Signed smallest angle a-b in degrees, range (-180, 180]."""
    d = (a - b) % 360.0
    if d > 180.0:
        d -= 360.0
    return d


def _choose_direction(samples, body_heading):
    """Pick the clearest body-relative cardinal (0/90/180/270 deg).

    Returns (rel_dir, min_clear_cm). d < 0 counts as 0 (blocked);
    d > MAX_RANGE_CM is ignored; a direction with no in-window samples
    counts as fully blocked (unknown = unsafe).
    """
    best_rel, best_clear = 0, -1.0
    for rel in (0, 90, 180, 270):
        target = (body_heading + rel) % 360.0
        clears = []
        for s in samples:
            if abs(_ang_diff(s["abs_yaw"], target)) <= 45.0:
                d = s["d"]
                if d > config.ROOMMAP_MAX_RANGE_CM:
                    continue
                clears.append(0.0 if d < 0 else d)
        min_clear = min(clears) if clears else 0.0
        if min_clear > best_clear:
            best_rel, best_clear = rel, min_clear
    return best_rel, best_clear


def _turn_to(rpc, state, rel):
    """Turn the body to face rel (0/90/180/270) with the fewest 90-deg steps."""
    if rel == 90:
        _turn_left(rpc, state)
    elif rel == 180:
        _turn_left(rpc, state)
        _turn_left(rpc, state)
    elif rel == 270:
        _turn_right(rpc, state)


def _turn_left(rpc, state):
    _guarded_rpc(rpc, state, "action", "turn_left_90")
    state["body_heading"] = (state["body_heading"] + 90.0) % 360.0


def _turn_right(rpc, state):
    _guarded_rpc(rpc, state, "action", "turn_right_90")
    state["body_heading"] = (state["body_heading"] - 90.0) % 360.0


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def _save_partial(state):
    """Best-effort map save; idempotent via state['saved']."""
    if state.get("saved"):
        return
    try:
        _save_map(state)
        state["saved"] = True
    except Exception:
        log.exception("failed to save roommap")


def _save_map(state):
    payload = {
        "metadata": {
            "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "duration_s": round(time.monotonic() - state["t_start"], 1),
            "clusters": state["clusters"],
            "n_samples": len(state["samples"]),
            "step_cm": config.ROOMMAP_STEP_CM,
            "grid_cell_cm": 10,
            "note": "dead-reckoned; headings from 90-deg body turns; position approximate",
        },
        "samples": state["samples"],
        "grid": _build_grid(state["samples"]),
    }
    data = json.dumps(payload, indent=2)
    ts = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    final_path = os.path.join(config.ROOMMAP_DIR, "roommap_{}.json".format(ts))
    tmp_path = os.path.join(config.ROOMMAP_DIR, ".roommap_{}.tmp".format(ts))
    # tmp -> timestamped file -> latest, all via os.replace (atomic).
    with open(tmp_path, "w") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, final_path)
    with open(tmp_path, "w") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, config.ROOMMAP_LATEST_FILE)


# ---------------------------------------------------------------------------
# Grid
# ---------------------------------------------------------------------------

def _build_grid(samples):
    """10 cm occupancy grid: "F" free, "O" obstacle hit.

    For each sample walk its ray from (x, y) in 10 cm steps: cells before
    the hit are "F"; if 0 < d <= MAX_RANGE_CM the hit cell is "O";
    d < 0 (no echo) marks only the first cell — beyond is unknown.
    """
    grid = {}
    max_range_cm = config.ROOMMAP_MAX_RANGE_CM
    for s in samples:
        yaw = math.radians(s["abs_yaw"])
        dx = math.cos(yaw)
        dy = math.sin(yaw)
        x0, y0, d = s["x"], s["y"], s["d"]
        if d < 0:
            _grid_set(grid, x0, y0, dx, dy, 1, "F")
            continue
        if d <= max_range_cm:
            k = 1
            while k * _GRID_STEP_CM < d - 1e-9:
                _grid_set(grid, x0, y0, dx, dy, k, "F")
                k += 1
            _grid_set(grid, x0, y0, dx, dy,
                      max(1, int(math.ceil(d / _GRID_STEP_CM - 1e-9))), "O")
        else:
            # Free up to max range; beyond is unknown.
            k = 1
            while k * _GRID_STEP_CM <= max_range_cm:
                _grid_set(grid, x0, y0, dx, dy, k, "F")
                k += 1
    return grid


def _grid_set(grid, x0, y0, dx, dy, k, value):
    """Mark the ray cell whose far end is at k * 10 cm (cell center keyed)."""
    cx = x0 + (k - 0.5) * _GRID_CELL_M * dx
    cy = y0 + (k - 0.5) * _GRID_CELL_M * dy
    key = "{},{}".format(int(math.floor(cx / _GRID_CELL_M + 1e-9)),
                        int(math.floor(cy / _GRID_CELL_M + 1e-9)))
    grid[key] = value
