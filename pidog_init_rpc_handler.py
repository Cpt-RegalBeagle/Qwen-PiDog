"""
PiDog XML-RPC Handler - Provides hardware control API
"""
import sys
import os
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config


class PidogRPCHandler:
    """XML-RPC request handler for PiDog hardware control"""
    
    def __init__(self, dog_instance):
        self.dog = dog_instance
        
        # Initialize software guard gate for ears monitoring
        self.ears_tracking_allowed = True
        
        # Background-polled azimuth angle (0-359) - PEAK-HOLD LATCHING
        self.latched_azimuth = 0
        
        # Initialize hardware ears sensor ONCE during setup
        if hasattr(self.dog, 'ears'):
            from pidog.sound_direction import SoundDirection
            self.dog.ears = SoundDirection()
    
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
            result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            if result.returncode == 0 and os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                if output_file.startswith('/home/pidog/.cache/'):
                    subprocess.run(['rm', '-f', output_file])
                
                return {'status': 'success', 'message': f'Audio recorded successfully ({duration}s)', 'file_size': os.path.getsize(output_file), 'output_file': output_file}
            else:
                error_detail = f"Return code: {result.returncode}, File exists: {os.path.exists(output_file)}, Size: {os.path.getsize(output_file) if os.path.exists(output_file) else 0}"
                return {'status': 'error', 'message': f'Audio capture failed: {error_detail}'}
        except FileNotFoundError as e:
            return {'status': 'error', 'message': f'arecord command not found. Install with: sudo apt install pulseaudio-utils'}
        except PermissionError as e:
            return {'status': 'error', 'message': f'Permission denied for audio recording: {e}'}
        except Exception as e:
            return {'status': 'error', 'message': f'Subprocess exception: {str(e)}'}

    def is_speaking(self) -> bool:
        """Verifies our explicit server-side state lock status against the music thread lifecycle."""
        global _hardware_speaking_lock
        
        if not self.dog:
            return False
            
        try:
            if hasattr(self.dog, 'music') and self.dog.music.sound_thread is not None:
                if self.dog.music.sound_thread.is_alive():
                    return True
        except Exception:
            pass
            
        _hardware_speaking_lock = False
        return _hardware_speaking_lock
    
    def clear_speaking_flag(self):
        """Clear internal speaking flag for state synchronization"""
        if not self.dog:
            return {'status': 'success', 'message': 'No hardware to close'}
        
        try:
            if hasattr(self, '_is_speaking_flag'):
                self._is_speaking_flag = False
            
            return {'status': 'success', 'message': 'Speaking flag cleared'}
        except Exception:
            return {'status': 'error', 'message': 'Failed to clear speaking flag'}
    
    def music_play_file(self, audio_file: str):
        """Plays audio through the music module, engaging an explicit hardware state lock."""
        global _hardware_speaking_lock
        
        if not self.dog:
            raise Exception("Hardware not initialized")
        
        try:
            if hasattr(self.dog, 'music'):
                _hardware_speaking_lock = True
                self.dog.music.sound_play_threading(audio_file, 100)
                return {'status': 'success', 'message': f'Playing audio from {audio_file}'}
            else:
                raise Exception("Music module not available")
        except Exception:
            _hardware_speaking_lock = False
            raise Exception("Music playback error")
    
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
            self.dog.do_action('stretch')
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Stretching'}
        except Exception:
            raise Exception("Stretch error")
    
    def push_up(self):
        """Push-up exercise"""
        if not self.dog:
            raise Exception("Hardware not initialized")
        
        try:
            self.dog.do_action('push_up')
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
            self.dog.do_action('twist_body')
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Twisting body'}
        except Exception:
            raise Exception("Twist body error")
    
    def feet_shake(self):
        """Shake feet"""
        if not self.dog:
            raise Exception("Hardware not initialized")
        
        try:
            self.dog.do_action('feet_shake')
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Shaking feet'}
        except Exception:
            raise Exception("Feet shake error")
    
    def handshake(self):
        """Handshake gesture"""
        if not self.dog:
            raise Exception("Hardware not initialized")
        
        try:
            self.dog.do_action('handshake')
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Handshaking'}
        except Exception:
            raise Exception("Handshake error")
    
    def high_five(self):
        """High five gesture"""
        if not self.dog:
            raise Exception("Hardware not initialized")
        
        try:
            self.dog.do_action('high_five')
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'High fiving'}
        except Exception:
            raise Exception("High five error")
    
    def lick_hand(self):
        """Lick hand action"""
        if not self.dog:
            raise Exception("Hardware not initialized")
        
        try:
            self.dog.do_action('lick_hand')
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Licking hand'}
        except Exception:
            raise Exception("Lick hand error")
    
    def scratch(self):
        """Scratch action"""
        if not self.dog:
            raise Exception("Hardware not initialized")
        
        try:
            self.dog.do_action('scratch')
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Scratching'}
        except Exception:
            raise Exception("Scratch error")
    
    def fluster(self):
        """Flustered expression"""
        if not self.dog:
            raise Exception("Hardware not initialized")
        
        try:
            self.dog.do_action('fluster')
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Flustered'}
        except Exception:
            raise Exception("Fluster error")
    
    def surprise(self):
        """Surprise expression"""
        if not self.dog:
            raise Exception("Hardware not initialized")
        
        try:
            self.dog.do_action('surprise')
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Surprised'}
        except Exception:
            raise Exception("Surprise error")
    
    def think(self):
        """Thinking pose"""
        if not self.dog:
            raise Exception("Hardware not initialized")
        
        try:
            self.dog.do_action('think')
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Thinking'}
        except Exception:
            raise Exception("Think error")
    
    def recall(self):
        """Recall gesture"""
        if not self.dog:
            raise Exception("Hardware not initialized")
        
        try:
            self.dog.do_action('recall')
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Recalling'}
        except Exception:
            raise Exception("Recall error")
    
    def relax_neck(self):
        """Relax neck action"""
        if not self.dog:
            raise Exception("Hardware not initialized")
        
        try:
            self.dog.do_action('relax_neck')
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
            self.dog.do_action('bark_harder')
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Barking harder'}
        except Exception:
            raise Exception("Bark harder error")
    
    def howling(self):
        """Howl"""
        if not self.dog:
            raise Exception("Hardware not initialized")
        
        try:
            self.dog.do_action('howling')
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Howling'}
        except Exception:
            raise Exception("Howling error")
    
    def waiting(self):
        """Standby/waiting pose"""
        if not self.dog:
            raise Exception("Hardware not initialized")
        
        try:
            self.dog.do_action('waiting')
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Waiting'}
        except Exception:
            raise Exception("Waiting error")
    
    def nod(self):
        """Regular nod (not lethargic)"""
        if not self.dog:
            raise Exception("Hardware not initialized")
        
        try:
            self.dog.do_action('nod')
            self.dog.wait_all_done()
            return {'status': 'success', 'message': 'Nodding'}
        except Exception:
            raise Exception("Nod error")

    def get_sound_direction(self) -> int:
        """Reads the native SunFounder ears sensor array to capture the spatial sound angle."""
        if not self.dog or not hasattr(self.dog, 'ears'):
            return -1
        
        try:
            if self.dog.ears.isdetected():
                return int(self.dog.ears.read())
            return -1
        except Exception:
            return -1

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
            
            if hasattr(self.dog, 'head_move'):
                self.dog.head_move([[target_yaw, 0, 0]], speed=80)
                self.dog.wait_all_done()
            
            return {'status': 'success', 'message': f'Head turned to angle {target_yaw}', 'target_yaw': target_yaw}
        except Exception:
            return {'status': 'error', 'message': 'Sound localization error'}

    def pause_ears_monitor(self) -> bool:
        """Disables the tracking calculation without destroying the hardware context handles."""
        if not self.dog:
            return False
        
        try:
            self.ears_tracking_allowed = False
            
            print("  [SERVER LOGIC] Software tracking gate CLOSED.", flush=True)
            
            return True
        except Exception:
            return False

    def resume_ears_monitor(self) -> bool:
        """Enables the tracking calculation on the active, continuously running hardware bus."""
        if not self.dog:
            return False
        
        try:
            # CRITICAL FIX: Clear stale azimuth BEFORE re-enabling tracking
            # This prevents reading cached values from previous conversation cycle
            self.latched_azimuth = -1
            
            print("  [SERVER LOGIC] Ears tracking gate OPENED. Azimuth buffer flushed.", flush=True)
            
            return True
        except Exception:
            return False

    def start_ears_monitor(self):
        """Start background thread to continuously poll ears sensor."""
        import threading
        
        if not hasattr(self, 'latched_azimuth'):
            self.latched_azimuth = -1
        
        def _ears_loop():
            while True:
                try:
                    if self.ears_tracking_allowed and self.dog and hasattr(self.dog, 'ears'):
                        detected = self.dog.ears.isdetected()
                        if detected:
                            val = self.dog.ears.read()
                            if isinstance(val, (int, float)):
                                self.latched_azimuth = int(val)
                except Exception:
                    pass
                
                time.sleep(0.1)
        
        thread = threading.Thread(target=_ears_loop, daemon=True)
        thread.start()

    def get_latched_azimuth(self) -> int:
        """Exposes the internal latched sound vector memory to the network client."""
        return getattr(self, 'latched_azimuth', -1)

    def look_at_last_sound_source(self) -> bool:
        """Transforms our background-polled azimuth angle and clears the latch AFTER head movement."""
        if not self.dog:
            return False
        
        try:
            angle = getattr(self, 'latched_azimuth', -1)
            
            if angle == -1 or angle == 0:
                return False
            
            if angle > 180:
                target_yaw = int((360 - angle) * 0.5)
            else:
                target_yaw = -int(angle * 0.5)
            
            target_yaw = max(-75, min(75, target_yaw))
            
            if hasattr(self.dog, 'head_move'):
                self.dog.head_move([[target_yaw, 0, 0]], speed=75, immediately=True)
                self.dog.wait_all_done()
            
            self.latched_azimuth = -1
            return True
        except Exception:
            return False
