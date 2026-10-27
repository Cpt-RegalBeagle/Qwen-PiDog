"""
PiDog XML-RPC Handler - Provides hardware control API
"""
import sys
import os
import time
import threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config

from pidog_rpc_actions import PidogActionMethods


class PidogRPCHandler(PidogActionMethods):
    """XML-RPC request handler for PiDog hardware control"""

    def __init__(self, dog_instance):
        self.dog = dog_instance

        # Tracked TTS playback state (single playback thread)
        self._sound_thread = None
        self._sound_stop_requested = False
        self._current_sound = None

        # dog.ears is pre-initialized in pidog_init.py - do NOT re-create it.

    def read_distance(self):
        """Read ultrasonic distance in cm (-1.0 on no echo)"""
        return round(float(self.dog.read_distance()), 2)

    def touch_read(self):
        """Read dual touch state ('N'|'L'|'R'|'LS'|'RS')"""
        return self.dog.dual_touch.read()

    def head_move(self, yaw=0, roll=0, pitch=0, speed=50):
        """Move head to yaw/roll/pitch degrees relative to neutral"""
        self.dog.head_move([[yaw, roll, pitch]], immediately=True, speed=speed)
        return True

    def wait_head_done(self, timeout=30.0):
        """Wait up to timeout seconds for head motion to complete"""
        t0 = time.monotonic()
        while not self.dog.is_head_done() and time.monotonic() - t0 < timeout:
            time.sleep(0.02)
        return bool(self.dog.is_head_done())

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
            output_file = config.SELF_TEST_AUDIO_PATH

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

    def _tracked_sound_play(self, filename, volume):
        """Mirror of SDK Music.sound_play using the SDK's initialized pygame mixer; waits in 0.05 s slices so a stop request can interrupt."""
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

        if not self.dog:
            raise Exception("Hardware not initialized")

        try:
            if hasattr(self.dog, 'music'):
                # Interrupt live playback before starting new audio
                if self._sound_thread is not None and self._sound_thread.is_alive():
                    self._sound_stop_requested = True
                    if self._current_sound is not None:
                        try:
                            self._current_sound.stop()
                        except Exception:
                            pass
                    self._sound_thread.join(timeout=1.0)

                self._sound_stop_requested = False

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
