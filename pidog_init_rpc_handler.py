"""
PiDog XML-RPC Handler - Provides hardware control API
"""
import sys
import os
import time
import threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config

# Import preset_actions functions from the SDK for actions NOT in ActionDict
from pidog.preset_actions import (
    hand_shake as _pa_hand_shake,
    high_five as _pa_high_five,
    lick_hand as _pa_lick_hand,
    push_up as _pa_push_up,
    howling as _pa_howling,
    body_twisting as _pa_body_twisting,
    scratch as _pa_scratch,
    feet_shake as _pa_feet_shake,
    relax_neck as _pa_relax_neck,
    nod as _pa_nod,
    think as _pa_think,
    recall as _pa_recall,
    fluster as _pa_fluster,
    surprise as _pa_surprise,
    stretch as _pa_stretch,
    bark_action as _pa_bark_action,
    waiting as _pa_waiting,
)

# Module-level shared speaking lock (defined here so the `global` statements in
# is_speaking() / music_play_file() / clear_speaking_flag() always resolve).
_hardware_speaking_lock = False


class PidogRPCHandler:
    """XML-RPC request handler for PiDog hardware control"""

    def __init__(self, dog_instance):
        self.dog = dog_instance

        # Initialize software guard gate for ears monitoring
        self.ears_tracking_allowed = True

        # Background-polled azimuth angle (0-359) - PEAK-HOLD LATCHING
        # -1 is the universal "no sound" sentinel across all code paths
        self.latched_azimuth = -1

        # Shutdown flag for ears background thread
        self._ears_shutdown = False

        # Guard against spawning duplicate ears threads
        self._ears_thread = None

        # SPI bus mutex - serializes ALL access to TR16F064B registers
        # Prevents 'GPIO busy' when background thread and RPC handler contend
        self._ears_spi_lock = threading.Lock()

        # Option C: tracked TTS playback state (single playback thread)
        self._sound_thread = None
        self._sound_stop_requested = False
        self._current_sound = None

        # Ears sensor is already initialized by pidog_init.py hardware setup.
        # Do NOT re-create it - that would orphan the original GPIO/SPI handles
        # and cause 'GPIO busy' on every subsequent read.

    def init(self):
        """Initialize hardware - verifies initialization was successful"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        return {'status': 'initialized', 'message': 'Hardware ready'}

    def action(self, name):
        """Smart catch-all router that enforces our safe, non-blocking custom methods over legacy SDK strings."""

        if not self.dog:
            return {'status': 'error', 'message': 'Hardware uninitialized'}

        try:
            target_method_name = str(name).strip().lower()

            if hasattr(self, target_method_name) and callable(getattr(self, target_method_name)):
                method = getattr(self, target_method_name)
                return method()

            if hasattr(self.dog, 'do_action'):
                self.dog.do_action(target_method_name)
                self.dog.wait_all_done()
                return {'status': 'success', 'message': f'Legacy action {target_method_name} triggered asynchronously'}

            return {'status': 'error', 'message': f'Action {target_method_name} not supported by hardware'}
        except Exception:
            return {'status': 'error', 'message': f'Router exception on {name}'}

    def head_move(self, target: list):
        """Move head to specified position - uses DEFAULT servo speed"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            self.dog.head_move(target)
            self.dog.wait_all_done()
            return {'status': 'success', 'message': f'Head moved to {target}'}
        except Exception:
            raise Exception("Head move error")

    def body_stop(self):
        """Stop all body/motion threads"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            self.dog.body_stop()
            return {'status': 'success', 'message': 'Body stopped'}
        except Exception:
            raise Exception("Body stop error")

    def head_stop(self):
        """Stop all head motion threads"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            self.dog.head_stop()
            return {'status': 'success', 'message': 'Head stopped'}
        except Exception:
            raise Exception("Head stop error")

    def legs_stop(self):
        """Stop all leg motion threads"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            self.dog.legs_stop()
            return {'status': 'success', 'message': 'Legs stopped'}
        except Exception:
            raise Exception("Legs stop error")

    def tail_stop(self):
        """Stop all tail motion threads"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            self.dog.tail_stop()
            return {'status': 'success', 'message': 'Tail stopped'}
        except Exception:
            raise Exception("Tail stop error")

    def wag_tail(self):
        """Wag tail - uses legacy SDK fallback"""
        if not self.dog:
            return {'status': 'error', 'message': 'Hardware not initialized'}

        try:
            self.dog.do_action('wag_tail')
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Wagging tail'}
        except Exception:
            return {'status': 'error', 'message': 'Wag tail error'}

    def status(self):
        """Get hardware status - minimal implementation"""
        if not self.dog:
            return {'status': 'not_initialized', 'message': 'Hardware not initialized yet'}

        try:
            return {
                'status': 'ok',
                'initialized': True
            }
        except Exception:
            return {'status': 'error', 'message': 'Status check failed', 'initialized': False}

    def rgb_strip_set_mode(self, mode: str, color: str = 'green'):
        """Set RGB strip mode - accepts mode, color as positional arguments (SDK only supports 2 args)"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            valid_modes = ['breath', 'boom', 'bark']

            if mode == 'listen':
                mode = 'breath'
            elif mode == 'close':
                mode = 'breath'
                color = 'black'

            valid_colors = ['red', 'green', 'blue', 'yellow', 'cyan', 'magenta',
                           'white', 'black', 'pink', 'orange', 'purple']

            if color not in valid_colors:
                color = 'black'

            if hasattr(self.dog, 'rgb_strip'):
                self.dog.rgb_strip.set_mode(mode, color)

            return {'status': 'success', 'mode': mode}
        except Exception:
            raise Exception("RGB strip error")

    def camera_capture(self):
        """Capture a photo via Vilib - WITH TIMEOUT AND ERROR HANDLING"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            from vilib import Vilib

            start_time = time.time()
            timeout = 10

            while time.time() - start_time < timeout:
                try:
                    Vilib.camera_start()
                    time.sleep(1)
                    break
                except Exception as e:
                    if time.time() - start_time >= timeout:
                        raise Exception(f"Camera start timeout after {timeout}s: {e}")
                    time.sleep(0.5)

            target_path = os.path.expanduser('~/test_photo.jpg')
            if os.path.exists(target_path):
                try:
                    os.remove(target_path)
                except Exception:
                    pass

            start_time = time.time()
            photo_timeout = 15

            while time.time() - start_time < photo_timeout:
                try:
                    Vilib.take_photo('test_photo', os.path.expanduser('~'))
                    break
                except Exception as e:
                    if time.time() - start_time >= photo_timeout:
                        raise Exception(f"Photo capture timeout after {photo_timeout}s: {e}")
                    time.sleep(0.5)

            time.sleep(1)

            try:
                Vilib.camera_close()
            except Exception:
                pass

            if os.path.exists(target_path):
                os.remove(target_path)
                return {'status': 'success', 'message': 'Photo captured successfully'}
            else:
                return {'status': 'error', 'message': 'Photo capture failed - file not found'}
        except Exception as e:
            return {'status': 'error', 'message': f'Camera capture skipped: {str(e)}'}

    def imu_get_data(self):
        """Get IMU calibrated data"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            acc, gyro = self.dog.imu.get_calibrated_data()

            return {
                'status': 'success',
                'acceleration': acc,
                'gyroscope': gyro
            }
        except Exception:
            raise Exception("IMU read error")

    def audio_record(self, duration=1, output_file=None):
        """Record audio to file for STT - accepts duration and optional output filename as positional arguments"""
        import subprocess

        if output_file is None:
            output_file = '/home/pidog/.cache/audio_capture.wav'

        cache_dir = os.path.dirname(output_file)
        if not os.path.exists(cache_dir):
            try:
                os.makedirs(cache_dir, mode=0o755, exist_ok=True)
            except Exception as e:
                return {'status': 'error', 'message': f'Failed to create cache directory: {e}'}

        if os.path.exists(output_file):
            try:
                os.remove(output_file)
            except Exception:
                pass

        cmd = ['arecord', '-D', 'default', '-d', str(duration), '-f', 'S16_LE', '-r', '16000', '-c', '1', output_file]

        try:
            result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=duration + 10)

            if result.returncode == 0 and os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                return {'status': 'success', 'message': f'Audio recorded successfully ({duration}s)', 'file_size': os.path.getsize(output_file), 'output_file': output_file}
            else:
                error_detail = f"Return code: {result.returncode}, File exists: {os.path.exists(output_file)}, Size: {os.path.getsize(output_file) if os.path.exists(output_file) else 0}"
                return {'status': 'error', 'message': f'Audio capture failed: {error_detail}'}
        except subprocess.TimeoutExpired:
            return {'status': 'error', 'message': f'arecord timed out after {duration + 10}s (audio device may be wedged)'}
        except FileNotFoundError as e:
            return {'status': 'error', 'message': f'arecord command not found. Install with: sudo apt install pulseaudio-utils'}
        except PermissionError as e:
            return {'status': 'error', 'message': f'Permission denied for audio recording: {e}'}
        except Exception as e:
            return {'status': 'error', 'message': f'Subprocess exception: {str(e)}'}

    def is_speaking(self) -> bool:
        """Delegates to tracked playback-thread state (Option C)."""
        return self.is_music_playing()

    def clear_speaking_flag(self):
        """Clear internal speaking flag for state synchronization"""
        global _hardware_speaking_lock

        if not self.dog:
            return {'status': 'success', 'message': 'No hardware to close'}

        try:
            _hardware_speaking_lock = False

            return {'status': 'success', 'message': 'Speaking flag cleared'}
        except Exception:
            return {'status': 'error', 'message': 'Failed to clear speaking flag'}

    def _tracked_sound_play(self, filename, volume):
        """Mirror of SDK Music.sound_play (music.py L170-185) using the SDK's own
        initialized pygame mixer. Waits get_length() in 0.05 s slices so a stop
        request can interrupt the wait."""
        sound = self.dog.music.pygame.mixer.Sound(filename)
        sound.set_volume(round(volume/100.0, 2))

        if self._sound_stop_requested:
            # Stop was requested during decode - never start audio
            return

        # Store AFTER successful decode so hard stop can interrupt playback
        self._current_sound = sound
        try:
            sound.play()
            remaining = sound.get_length()
            while remaining > 0 and not self._sound_stop_requested:
                step = min(0.05, remaining)
                time.sleep(step)
                remaining -= step
        finally:
            self._current_sound = None

    def music_play_file(self, audio_file: str):
        """Plays audio in a handler-owned, stop-interruptible thread (single-playback invariant)."""
        global _hardware_speaking_lock

        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            if hasattr(self.dog, 'music'):
                # STOP-STALE-FIRST: interrupt any live playback before starting new audio
                if self._sound_thread is not None and self._sound_thread.is_alive():
                    self._sound_stop_requested = True
                    if self._current_sound is not None:
                        try:
                            self._current_sound.stop()
                        except Exception:
                            pass
                    self._sound_thread.join(timeout=1.0)

                self._sound_stop_requested = False

                # Compat only - tracked thread state is now the source of truth
                _hardware_speaking_lock = True
                volume = 100
                self._sound_thread = threading.Thread(
                    target=self._tracked_sound_play,
                    args=(audio_file, volume),
                    name="Tracked Sound Play Thread",
                    daemon=True)
                self._sound_thread.start()
                return {'status': 'success', 'message': f'Playing: {audio_file}'}
            else:
                raise Exception("Music module not available")
        except Exception:
            _hardware_speaking_lock = False
            raise Exception("Music playback error")

    def is_music_playing(self) -> bool:
        """True while a tracked playback thread is alive and not stopped.
        Pure thread-alive check - no pygame, no I/O (cheap to poll ~2/s)."""
        return self._sound_thread is not None and self._sound_thread.is_alive() and not self._sound_stop_requested

    def music_stop(self):
        """Request stop, hard-stop the decoded Sound, and join the playback thread."""
        self._sound_stop_requested = True
        if self._current_sound is not None:
            try:
                self._current_sound.stop()
            except Exception:
                pass
        if self._sound_thread is not None:
            self._sound_thread.join(timeout=1.0)
        return {'status': 'success', 'message': 'stop requested'}

    def close(self):
        """Safely closes the PiDog instance and releases hardware channels across any thread context."""
        if not self.dog:
            return {'status': 'success', 'message': 'No hardware to close'}

        try:
            self.body_stop()
            self.legs_stop()
            self.tail_stop()

            if hasattr(self.dog, 'rgb_strip'):
                self.dog.rgb_strip.set_mode('breath', 'black')

            self.dog.close()

            return {'status': 'success', 'message': 'PiDog hardware handles terminated successfully'}
        except Exception:
            return {'status': 'error', 'message': 'Hardware teardown execution exception'}

    def shake_head(self):
        """Snappy, realistic side-to-side head shake matching official SunFounder constraints"""

        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            if hasattr(self.dog, 'head_stop'):
                self.dog.head_stop()

            quick_shake = [[35, 0, 0], [-35, 0, 0], [0, 0, 0]]

            self.dog.head_move(
                quick_shake,
                roll_comp=0,
                pitch_comp=0,
                immediately=True,
                speed=95
            )

            if hasattr(self.dog, 'wait_head_done'):
                self.dog.wait_head_done()

            return {'status': 'success', 'message': 'Quick head shake completed'}
        except Exception:
            return {'status': 'error', 'message': 'Hardware execution exception'}

    def nod_lethargy(self):
        """Snappy, realistic nodding while drowsy with explicit keyword arguments"""

        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            if hasattr(self.dog, 'head_stop'):
                self.dog.head_stop()

            quick_nod = [[0, 30, -30], [0, -30, 30], [0, 0, 0]]

            self.dog.head_move(
                quick_nod,
                roll_comp=0,
                pitch_comp=0,
                immediately=True,
                speed=95
            )

            if hasattr(self.dog, 'wait_head_done'):
                self.dog.wait_head_done()

            return {'status': 'success', 'message': 'Quick nodding completed'}
        except Exception:
            return {'status': 'error', 'message': 'Hardware execution exception'}

    def tilting_head_left(self):
        """Snappy, realistic tilt head to the left with explicit keyword arguments"""

        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            if hasattr(self.dog, 'head_stop'):
                self.dog.head_stop()

            quick_tilt = [[0, -25, 15]]

            self.dog.head_move(
                quick_tilt,
                roll_comp=0,
                pitch_comp=0,
                immediately=True,
                speed=95
            )

            if hasattr(self.dog, 'wait_head_done'):
                self.dog.wait_head_done()

            return {'status': 'success', 'message': 'Quick tilt left completed'}
        except Exception:
            return {'status': 'error', 'message': 'Hardware execution exception'}

    def tilting_head_right(self):
        """Snappy, realistic tilt head to the right with explicit keyword arguments"""

        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            if hasattr(self.dog, 'head_stop'):
                self.dog.head_stop()

            quick_tilt = [[0, 25, 20]]

            self.dog.head_move(
                quick_tilt,
                roll_comp=0,
                pitch_comp=0,
                immediately=True,
                speed=95
            )

            if hasattr(self.dog, 'wait_head_done'):
                self.dog.wait_head_done()

            return {'status': 'success', 'message': 'Quick tilt right completed'}
        except Exception:
            return {'status': 'error', 'message': 'Hardware execution exception'}

    def tilting_head(self):
        """Snappy, realistic alternating head tilt left and right with explicit keyword arguments"""

        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            if hasattr(self.dog, 'head_stop'):
                self.dog.head_stop()

            quick_tilt = [[0, -22, 20], [0, 22, 20]]

            self.dog.head_move(
                quick_tilt,
                roll_comp=0,
                pitch_comp=0,
                immediately=True,
                speed=95
            )

            if hasattr(self.dog, 'wait_head_done'):
                self.dog.wait_head_done()

            return {'status': 'success', 'message': 'Quick alternating tilt completed'}
        except Exception:
            return {'status': 'error', 'message': 'Hardware execution exception'}

    def head_bark(self):
        """Snappy, realistic head position for barking with explicit keyword arguments"""

        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            if hasattr(self.dog, 'head_stop'):
                self.dog.head_stop()

            quick_bark = [[0, 0, -40], [0, 0, -10]]

            self.dog.head_move(
                quick_bark,
                roll_comp=0,
                pitch_comp=0,
                immediately=True,
                speed=95
            )

            if hasattr(self.dog, 'wait_head_done'):
                self.dog.wait_head_done()

            return {'status': 'success', 'message': 'Quick bark position completed'}
        except Exception:
            return {'status': 'error', 'message': 'Hardware execution exception'}

    def head_up_down(self):
        """Snappy, realistic vertical head movement with explicit keyword arguments"""

        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            if hasattr(self.dog, 'head_stop'):
                self.dog.head_stop()

            quick_vertical = [[0, 0, 20], [0, 0, -10]]

            self.dog.head_move(
                quick_vertical,
                roll_comp=0,
                pitch_comp=0,
                immediately=True,
                speed=95
            )

            if hasattr(self.dog, 'wait_head_done'):
                self.dog.wait_head_done()

            return {'status': 'success', 'message': 'Quick vertical movement completed'}
        except Exception:
            return {'status': 'error', 'message': 'Hardware execution exception'}

    def stretch(self):
        """Full body stretch"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            _pa_stretch(self.dog)
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Stretching'}
        except Exception:
            raise Exception("Stretch error")

    def push_up(self):
        """Push-up exercise"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            _pa_push_up(self.dog)
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Doing push-ups'}
        except Exception:
            raise Exception("Push up error")

    def doze_off(self):
        """Sleep/dozing action"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            self.dog.do_action('doze_off')
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Dozing off'}
        except Exception:
            raise Exception("Doze off error")

    def twist_body(self):
        """Body twisting motion"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            _pa_body_twisting(self.dog)
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Twisting body'}
        except Exception:
            raise Exception("Twist body error")

    def feet_shake(self):
        """Shake feet"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            _pa_feet_shake(self.dog)
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Shaking feet'}
        except Exception:
            raise Exception("Feet shake error")

    def handshake(self):
        """Handshake gesture"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            _pa_hand_shake(self.dog)
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Handshaking'}
        except Exception:
            raise Exception("Handshake error")

    def high_five(self):
        """High five gesture"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            _pa_high_five(self.dog)
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'High fiving'}
        except Exception:
            raise Exception("High five error")

    def lick_hand(self):
        """Lick hand action"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            _pa_lick_hand(self.dog)
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Licking hand'}
        except Exception:
            raise Exception("Lick hand error")

    def scratch(self):
        """Scratch action"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            _pa_scratch(self.dog)
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Scratching'}
        except Exception:
            raise Exception("Scratch error")

    def fluster(self):
        """Flustered expression"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            _pa_fluster(self.dog, pitch_comp=0)
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Flustered'}
        except Exception:
            raise Exception("Fluster error")

    def surprise(self):
        """Surprise expression"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            _pa_surprise(self.dog, pitch_comp=0)
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Surprised'}
        except Exception:
            raise Exception("Surprise error")

    def think(self):
        """Thinking pose"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            _pa_think(self.dog, pitch_comp=0)
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Thinking'}
        except Exception:
            raise Exception("Think error")

    def recall(self):
        """Recall gesture"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            _pa_recall(self.dog, pitch_comp=0)
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Recalling'}
        except Exception:
            raise Exception("Recall error")

    def relax_neck(self):
        """Relax neck action"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            _pa_relax_neck(self.dog, pitch_comp=0)
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Relaxing neck'}
        except Exception:
            raise Exception("Relax neck error")

    def lie_with_hands_out(self):
        """Lie down with hands extended forward"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            self.dog.do_action('lie_with_hands_out')
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Lying with hands out'}
        except Exception:
            raise Exception("Lie with hands out error")

    def trot(self):
        """Trot (small run)"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            self.dog.do_action('trot')
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Trotting'}
        except Exception:
            raise Exception("Trot error")

    def half_sit(self):
        """Half sit position"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            self.dog.do_action('half_sit')
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Half sitting'}
        except Exception:
            raise Exception("Half sit error")

    def bark_harder(self):
        """Bark with more intensity"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            _pa_bark_action(self.dog, [0, 0, 0], 'single_bark_1')
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Barking harder'}
        except Exception:
            raise Exception("Bark harder error")

    def howling(self):
        """Howl"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            _pa_howling(self.dog)
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Howling'}
        except Exception:
            raise Exception("Howling error")

    def waiting(self):
        """Standby/waiting pose"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            _pa_waiting(self.dog, pitch_comp=0)
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Waiting'}
        except Exception:
            raise Exception("Waiting error")

    def nod(self):
        """Regular nod (not lethargic)"""
        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            _pa_nod(self.dog, pitch_comp=0)
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Nodding'}
        except Exception:
            raise Exception("Nod error")

    def look_at_angle(self, angle: int):
        """Sweeps head servos smoothly toward the sound angle without blocking."""
        if not self.dog:
            return {'status': 'error', 'message': 'Hardware not initialized'}

        try:
            target_yaw = 0

            if angle != -1:
                if angle <= 180:
                    target_yaw = -int(angle * 0.5)
                else:
                    target_yaw = int((360 - angle) * 0.5)

            target_yaw = max(-75, min(75, target_yaw))

            if hasattr(self.dog, 'head_move'):
                self.dog.head_move([[target_yaw, 0, 0]], speed=80)
                self.dog.wait_all_done()

            return {'status': 'success', 'message': f'Head turned to angle {target_yaw}', 'target_yaw': target_yaw}
        except Exception:
            return {'status': 'error', 'message': 'Sound localization error'}

    def read_sound_direction(self) -> int:
        """Legacy one-shot read gated by isdetected() interrupt pin. Returns angle 0-355 or -1."""
        if not self.dog:
            return -1

        try:
            if not hasattr(self.dog, 'ears'):
                return -1

            with self._ears_spi_lock:
                if not self.dog.ears.isdetected():
                    return -1
                val = self.dog.ears.read()

            if isinstance(val, (int, float)) and val >= 0:
                self.latched_azimuth = int(val)
                return int(val)

            return -1
        except Exception:
            return -1

    def _single_ears_read(self, poll_idx):
        """Perform a single SPI read with up to 3 retry attempts on GPIO busy."""
        for attempt in range(3):
            try:
                with self._ears_spi_lock:
                    val = self.dog.ears.read()
            except Exception as e:
                print(f"  [EARS] Poll {poll_idx + 1}/3 attempt {attempt + 1} exception: {e}", file=sys.stderr, flush=True)
                time.sleep(0.5)
                continue
            print(f"  [EARS] Poll {poll_idx + 1}/3 raw: {repr(val)} (type={type(val).__name__})", file=sys.stderr, flush=True)
            if isinstance(val, (int, float)) and val >= 0:
                return int(val)
            print(f"  [EARS] Poll {poll_idx + 1}/3 rejected: not valid non-negative number", file=sys.stderr, flush=True)
            return None
        return None

    def _poll_ears_triple(self):
        """Perform 3 SPI reads of the TR16F064B direction register with inter-poll settling.
        Uses _ears_spi_lock to prevent contention with background ears thread.
        Returns list of valid angles (may be fewer than 3 if a poll fails)."""
        results = []
        time.sleep(0.1)
        for poll_idx in range(3):
            if poll_idx > 0:
                time.sleep(0.05)
            val = self._single_ears_read(poll_idx)
            if val is not None:
                results.append(val)
        return results

    def read_sound_direction_direct(self) -> int:
        """Direct Poll Bypass - skips isdetected() interrupt gate entirely.
        The TR16F064B continuously updates its Phase-Difference orientation registers over SPI
        regardless of interrupt pin state. Performs 3 rapid polls with settling delays and
        returns the median to stabilize against lower-amplitude human voice noise.
        Accepts 2/3 valid reads as a fallback.
        Stops background ears thread to guarantee exclusive GPIO access."""
        if not self.dog:
            return -1
        if not hasattr(self.dog, 'ears'):
            return -1
        try:
            self._ears_shutdown = True
            if self._ears_thread is not None and self._ears_thread.is_alive():
                self._ears_thread.join(timeout=1.0)
            self._ears_thread = None
            time.sleep(0.5)
            readings = self._poll_ears_triple()
            if len(readings) < 2:
                print(f"  [EARS] Direct poll FAILED: only {len(readings)}/3 valid reads", file=sys.stderr, flush=True)
                return -1
            if len(readings) == 3:
                readings_sorted = sorted(readings)
                avg_angle = readings_sorted[1]
            else:
                avg_angle = sum(readings) // len(readings)
            self.latched_azimuth = avg_angle
            print(f"  [EARS] Direct poll SUCCESS: readings={readings}, median={avg_angle}", file=sys.stderr, flush=True)
            return avg_angle
        except Exception as e:
            print(f"  [EARS] Direct poll unexpected error: {e}", file=sys.stderr, flush=True)
            return -1
        finally:
            self.start_ears_monitor()

    def pause_ears_monitor(self) -> bool:
        """Disables tracking and fully stops the background thread to release SPI/GPIO bus."""
        if not self.dog:
            return False

        try:
            self.ears_tracking_allowed = False
            self._ears_shutdown = True
            if self._ears_thread is not None and self._ears_thread.is_alive():
                self._ears_thread.join(timeout=1.0)
            self._ears_thread = None

            print("  [SERVER LOGIC] Software tracking gate CLOSED. Thread stopped.", file=sys.stderr, flush=True)

            return True
        except Exception:
            return False

    def resume_ears_monitor(self) -> bool:
        """Enables the tracking calculation on the active, continuously running hardware bus."""
        if not self.dog:
            return False

        try:
            self.latched_azimuth = -1
            self.ears_tracking_allowed = True

            print("  [SERVER LOGIC] Ears tracking gate OPENED. Azimuth buffer flushed.", file=sys.stderr, flush=True)

            return True
        except Exception:
            return False

    def start_ears_monitor(self):
        """Start background thread to continuously poll ears sensor. Safe to call multiple times."""

        if self._ears_thread is not None and self._ears_thread.is_alive():
            return

        self.latched_azimuth = -1
        self._ears_shutdown = False

        def _ears_loop():
            while not self._ears_shutdown:
                try:
                    if self.ears_tracking_allowed and self.dog and hasattr(self.dog, 'ears'):
                        with self._ears_spi_lock:
                            detected = self.dog.ears.isdetected()
                            if detected:
                                val = self.dog.ears.read()
                                if isinstance(val, (int, float)):
                                    self.latched_azimuth = int(val)
                except Exception:
                    pass

                time.sleep(0.1)

        self._ears_thread = threading.Thread(target=_ears_loop, daemon=True)
        self._ears_thread.start()

    def stop_ears_monitor(self):
        """Signal the ears background thread to stop."""
        self._ears_shutdown = True

    def get_latched_azimuth(self) -> int:
        """Exposes the internal latched sound vector memory to the network client."""
        return getattr(self, 'latched_azimuth', -1)
