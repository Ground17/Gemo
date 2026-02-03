import time
from typing import Protocol
from gpiozero import DigitalOutputDevice, PWMOutputDevice


class MotorChannel(Protocol):
    def stop(self) -> None: ...
    def forward(self, speed: float) -> None: ...
    def reverse(self, speed: float) -> None: ...

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

# TB6612Channel implementation

class TB6612Channel:
    """TB6612FNG single motor channel using gpiozero.

    Pins (BCM):
      - pwm_pin -> PWMA/PWMB
      - in1_pin -> AIN1/BIN1
      - in2_pin -> AIN2/BIN2
      - stby_pin -> STBY (shared is OK)

    Notes:
      - VCC should be 3.3V from Raspberry Pi
      - VM is motor supply (e.g., 2S 7.4V)
      - GND must be common between Pi and motor supply
    """

    def __init__(
        self,
        pwm_pin: int,
        in1_pin: int,
        in2_pin: int,
        stby_pin: int,
        pwm_freq: int = 1000,
    ):
        self.pwm = PWMOutputDevice(pwm_pin, frequency=pwm_freq, initial_value=0.0)
        self.in1 = DigitalOutputDevice(in1_pin, initial_value=False)
        self.in2 = DigitalOutputDevice(in2_pin, initial_value=False)
        self.stby = DigitalOutputDevice(stby_pin, initial_value=True)

    def _enable(self):
        # Some breakouts require STBY HIGH to run
        self.stby.on()

    def stop(self):
        # Coast/stop
        self.pwm.value = 0.0
        self.in1.off(); self.in2.off()

    def forward(self, speed: float):
        speed = max(0.0, min(1.0, float(speed)))
        self._enable()
        self.in1.on(); self.in2.off()
        self.pwm.value = speed

    def reverse(self, speed: float):
        speed = max(0.0, min(1.0, float(speed)))
        self._enable()
        self.in1.off(); self.in2.on()
        self.pwm.value = speed

    def brake(self):
        # Active brake; PWM=0 with both inputs same
        self._enable()
        self.pwm.value = 0.0
        self.in1.off(); self.in2.off()


class SteeringPulse:
    """
    2? DC ??(??? ???) ??:
    - CENTER: ?? OFF (?? ??)
    - LEFT/RIGHT: ?? ?? ? OFF
    """
    def __init__(self, ch: MotorChannel, pulse_s: float = 0.10, power: float = 0.80):
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
