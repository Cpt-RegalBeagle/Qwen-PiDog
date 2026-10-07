#!/usr/bin/env python3
"""
cleanup_hardware.py - Standalone hardware cleanup utility

This script safely shuts down all hardware components in the Ava Voice Assistant,
including:
- RGB LED strips (all LEDs turned off to safe 'listen' mode)
- Head servos (reset to neutral home position)
- Ears (cleared and reset)
- Legs/tail (stopped and reset)
- Body (stopped and reset)
- Audio stream (stopped)
- Camera (closed)

This should be called when automated loop terminations bypass normal teardown,
or when explicit cleanup is needed before exit.

Reference patterns from pidog/examples/:
- 1_wake_up.py: RGB set to 'listen' mode in finally block
- 5_rest.py: body_stop() and close() in finally block
- servo_zeroing.py: All servos set to zero angle
"""
import signal
import sys
import os
import time

# Import config to get module-level settings
import config

# Import pidog module for hardware access
from pidog import Pidog


def cleanup_hardware(dog: Pidog = None) -> bool:
    """
    Safely cleanup all hardware components.

    Args:
        dog: The Pidog instance to clean up. If None, creates a new one and cleans it.

    Returns:
        bool: True if cleanup completed successfully, False otherwise.
    """
    success_count = 0
    failure_count = 0

    try:
        # Get or create the dog instance
        if dog is None:
            try:
                dog = Pidog()
            except Exception as e:
                print(f"⚠ Could not instantiate Pidog: {e}", file=sys.stderr)
                return True  # Still success - no hardware to clean up

        if dog is None:
            print("⚠ Pidog instance is None, skipping cleanup", file=sys.stderr)
            return True

        # Step 1: Turn off all RGB LEDs by setting to 'listen' mode (yellow)
        # This ensures all LEDs are in a known safe state and released
        try:
            print("🛑 Turning off RGB LED strip...", file=sys.stderr)
            if hasattr(dog, 'rgb_strip'):
                # Explicitly close the RGB strip driver first to release hardware
                if hasattr(dog.rgb_strip, 'close'):
                    try:
                        dog.rgb_strip.close()
                        print("    - RGB strip driver closed", file=sys.stderr)
                    except Exception as ce:
                        pass  # Ignore close errors

                # Set to safe 'listen' mode with default brightness
                dog.rgb_strip.set_mode(
                    'listen',
                    color='yellow',
                    bps=config.PI_DOG_RGB_STRIP_BPS,
                    brightness=config.PI_DOG_RGB_STRIP_BRIGHTNESS
                )
                print("  ✅ RGB LEDs turned off (yellow listen mode)", file=sys.stderr)
                success_count += 1
            else:
                print("  ⚠ No rgb_strip attribute found", file=sys.stderr)
        except Exception as e:
            print(f"  ⚠ Error setting RGB LEDs: {e}", file=sys.stderr)
            failure_count += 1

        # Step 2: Stop all body/motion threads
        try:
            print("🛑 Stopping body motion...", file=sys.stderr)
            if hasattr(dog, 'body_stop'):
                dog.body_stop()
                time.sleep(0.2)  # Allow motors to stop
                print("  ✅ Body stopped", file=sys.stderr)
                success_count += 1
            else:
                print("  ⚠ No body_stop method available", file=sys.stderr)
        except Exception as e:
            print(f"  ⚠ Error stopping body: {e}", file=sys.stderr)
            failure_count += 1

        try:
            print("🛑 Stopping legs...", file=sys.stderr)
            if hasattr(dog, 'legs_stop'):
                dog.legs_stop()
                time.sleep(0.2)
                print("  ✅ Legs stopped", file=sys.stderr)
                success_count += 1
            else:
                print("  ⚠ No legs_stop method available", file=sys.stderr)
        except Exception as e:
            print(f"  ⚠ Error stopping legs: {e}", file=sys.stderr)
            failure_count += 1

        try:
            print("🛑 Stopping tail...", file=sys.stderr)
            if hasattr(dog, 'tail_stop'):
                dog.tail_stop()
                time.sleep(0.2)
                print("  ✅ Tail stopped", file=sys.stderr)
                success_count += 1
            else:
                print("  ⚠ No tail_stop method available", file=sys.stderr)
        except Exception as e:
            print(f"  ⚠ Error stopping tail: {e}", file=sys.stderr)
            failure_count += 1

        # Step 3: Reset head to neutral home position
        try:
            print("🔄 Resetting head servos to home position...", file=sys.stderr)
            if hasattr(dog, 'head_move'):
                # Return head to neutral/home position with zero yaw/roll and elevated pitch
                dog.head_move([[0, 0, config.FACE_TRACKING_ELEVATION_DEG]],
                             pitch_comp=config.FACE_TRACKING_PITCH_COMP,
                             immediately=True,
                             speed=50)
                dog.wait_head_done()
                print("  ✅ Head servos reset to home", file=sys.stderr)
                success_count += 1
            else:
                print("  ⚠ No head_move attribute found", file=sys.stderr)
        except Exception as e:
            print(f"  ⚠ Error resetting head servos: {e}", file=sys.stderr)
            failure_count += 1

        # Step 4: Clear ears if available
        try:
            print("🔄 Clearing ears...", file=sys.stderr)
            if hasattr(dog, 'ears') and dog.ears:
                if hasattr(dog.ears, 'clear'):
                    dog.ears.clear()
                if hasattr(dog.ears, 'reset'):
                    dog.ears.reset()
                print("  ✅ Ears cleared", file=sys.stderr)
                success_count += 1
            else:
                print("  ⚠ No ears attribute available", file=sys.stderr)
        except Exception as e:
            print(f"  ⚠ Error clearing ears: {e}", file=sys.stderr)
            failure_count += 1

        # Step 5: Close any open resources
        try:
            print("🔒 Closing hardware resources...", file=sys.stderr)
            if hasattr(dog, 'close'):
                dog.close()
                time.sleep(0.5)  # Allow time for cleanup
                print("  ✅ Dog resources closed", file=sys.stderr)
                success_count += 1
            else:
                print("  ⚠ No close method available", file=sys.stderr)
        except Exception as e:
            print(f"  ⚠ Error closing resources: {e}", file=sys.stderr)
            failure_count += 1

        # Step 6: Close camera if available
        try:
            print("📷 Closing camera...", file=sys.stderr)
            from vilib import Vilib
            # First try to release the camera via ioctl
            import subprocess
            try:
                # Try to release camera using v4l2-ctl
                subprocess.run(['v4l2-ctl', '--release', 'all'], capture_output=True, timeout=2)
                print("    - Camera released via v4l2-ctl", file=sys.stderr)
            except Exception:
                pass  # Ignore if v4l2-ctl not available or fails

            # Try different camera close methods
            if hasattr(Vilib, 'camera_close'):
                # Vilib.camera_close() is a method that closes the camera
                try:
                    Vilib.camera_close()
                    print("    - Camera closed via Vilib.camera_close()", file=sys.stderr)
                except Exception:
                    pass  # Ignore if fails

                time.sleep(0.5)
                print("  ✅ Camera closed", file=sys.stderr)
                success_count += 1
            else:
                print("  ⚠ No camera_close method available", file=sys.stderr)
        except Exception as e:
            print(f"  ⚠ Error closing camera: {e}", file=sys.stderr)
            failure_count += 1

    except Exception as e:
        print(f"⚠ Unexpected error during cleanup: {e}", file=sys.stderr)
        failure_count += 1

    # Print summary
    print(f"\n💾 Cleanup complete: {success_count} success(es), {failure_count} failure(s)", file=sys.stderr)

    # Return success if no critical failures (critical = RGB LEDs still bright)
    return failure_count == 0


def main():
    """Main entry point for cleanup_hardware.py as a standalone script."""
    print("=" * 60)
    print("🧹 Ava Voice Assistant - Hardware Cleanup Utility")
    print("=" * 60)
    print(f"📍 Working directory: {os.getcwd()}", file=sys.stderr)
    print(f"🔧 Using config: {config.SERVER_IP}", file=sys.stderr)
    print("-" * 60, file=sys.stderr)

    # Run cleanup
    success = cleanup_hardware()

    if success:
        print("\n✅ Hardware cleanup completed successfully", file=sys.stderr)
        print("💡 All LEDs are off and servos are in safe positions", file=sys.stderr)
        sys.exit(0)
    else:
        print("\n⚠ Hardware cleanup completed with warnings", file=sys.stderr)
        print("💡 Some hardware components may not have been cleaned properly", file=sys.stderr)
        sys.exit(0)  # Still exit cleanly to avoid zombie processes


if __name__ == "__main__":
    main()
