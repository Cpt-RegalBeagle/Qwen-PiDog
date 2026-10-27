"""PiDog XML-RPC action wrapper methods (mixin for PidogRPCHandler)."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import preset_actions functions from the SDK for actions NOT in pidog_actions_dictionary
from pidog.preset_actions import (
    hand_shake as _pa_hand_shake,
    high_five as _pa_high_five,
    lick_hand as _pa_lick_hand,
    push_up as _pa_push_up,
    howling as _pa_howling,
    body_twisting as _pa_body_twisting,
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


class PidogActionMethods:
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
            self.dog.do_action('stand')
            self.dog.wait_all_done()
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
