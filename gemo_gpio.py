import time
from gpiozero import DigitalOutputDevice, PWMOutputDevice

class L298NChannel:
    def __init__(self, en_pwm_pin: int, in1_pin: int, in2_pin: int, pwm_freq: int = 200):
        self.en = PWMOutputDevice(en_pwm_pin, frequency=pwm_freq, initial_value=0.0)
        self.in1 = DigitalOutputDevice(in1_pin, initial_value=False)
        self.in2 = DigitalOutputDevice(in2_pin, initial_value=False)

    def stop(self):
        self.en.value = 0.0
        self.in1.off(); self.in2.off()

    def forward(self, speed: float):
        speed = max(0.0, min(1.0, speed))
        self.in1.on(); self.in2.off()
        self.en.value = speed

    def reverse(self, speed: float):
        speed = max(0.0, min(1.0, speed))
        self.in1.off(); self.in2.on()
        self.en.value = speed


class SteeringPulse:
    """
    2? DC ??(??? ???) ??:
    - CENTER: ?? OFF (?? ??)
    - LEFT/RIGHT: ?? ?? ? OFF
    """
    def __init__(self, ch: L298NChannel, pulse_s: float = 0.10, power: float = 0.80):
        self.ch = ch
        self.pulse_s = pulse_s
        self.power = max(0.0, min(1.0, power))
        self.min_interval = 0.05
        self._last = 0.0

    def center(self):
        self.ch.stop()

    def left(self):
        now = time.time()
        if now - self._last < self.min_interval:
            return
        self._last = now
        self.ch.forward(self.power)
        time.sleep(self.pulse_s)
        self.ch.stop()

    def right(self):
        now = time.time()
        if now - self._last < self.min_interval:
            return
        self._last = now
        self.ch.reverse(self.power)
        time.sleep(self.pulse_s)
        self.ch.stop()
