import os, io, time, argparse, asyncio
from dotenv import load_dotenv
load_dotenv()

from picamera2 import Picamera2
from gpiozero import DigitalOutputDevice

from gemo_gpio import TB6612Channel, SteeringPulse, DrivePulse
from gemo_gemini import make_client, decide_batch, run_live_loop, Command

# ===== GPIO pins (BCM) =====
# TB6612FNG: PWMA/AIN1/AIN2 for motor A, PWMB/BIN1/BIN2 for motor B, STBY shared
PWMA, AIN1, AIN2 = 18, 23, 24     # drive (A)
PWMB, BIN1, BIN2 = 19, 27, 22     # steer (B)
STBY = 25                         # standby (shared)

DEFAULT_BATCH_MODEL = "gemini-3-flash-preview"
DEFAULT_LIVE_MODEL  = "gemini-2.5-flash-native-audio-preview-09-2025"

def capture_jpeg_bytes(cam: Picamera2) -> bytes:
    buf = io.BytesIO()
    cam.capture_file(buf, format="jpeg")
    return buf.getvalue()

def apply_cmd(cmd: Command, drive_ch: TB6612Channel, steer: SteeringPulse, drive_speed: float):
    steer_action = None
    if cmd.steer == "LEFT":
        steer_action = steer.left
    elif cmd.steer == "RIGHT":
        steer_action = steer.right

    if steer_action and cmd.drive in ("FORWARD", "REVERSE"):
        # When moving, pulse steering before and after the drive pulse.
        steer_action()

    if cmd.drive == "FORWARD":
        drive_ch.forward(drive_speed)
    elif cmd.drive == "REVERSE":
        drive_ch.reverse(drive_speed)
    else:
        drive_ch.stop()

    if steer_action:
        steer_action()
    else:
        steer.center()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["batch","live"], default="batch")
    ap.add_argument("--model", default=None)
    ap.add_argument("--fps", type=float, default=5.0)
    ap.add_argument("--drive_speed", type=float, default=0.45)
    ap.add_argument("--drive_pulse", type=float, default=1.20)
    ap.add_argument("--steer_pulse", type=float, default=0.10)
    ap.add_argument("--steer_power", type=float, default=0.80)
    args = ap.parse_args()

    if args.mode == "live":
        # Live mode uses the native-audio preview model by default.
        if args.model and args.model != DEFAULT_LIVE_MODEL:
            print(f"[LIVE] overriding model {args.model} -> {DEFAULT_LIVE_MODEL}")
        args.model = DEFAULT_LIVE_MODEL
        # Live video input is expected at ~1 FPS.
        if args.fps > 1.0:
            args.fps = 1.0
    else:
        # Batch mode defaults to 3-flash preview unless overridden.
        if args.model is None:
            args.model = DEFAULT_BATCH_MODEL

    # API key / Vertex config check
    if not os.getenv("GEMINI_API_KEY") and not (os.getenv("VERTEX_PROJECT") and os.getenv("VERTEX_LOCATION")):
        raise RuntimeError("GEMINI_API_KEY(.env) ?? VERTEX_PROJECT/LOCATION(.env)? ????.")

    # Camera
    cam = Picamera2()
    cam.configure(cam.create_still_configuration(main={"size": (640, 360)}))
    cam.start()

    # GPIO
    stby = DigitalOutputDevice(STBY, initial_value=True)

    drive_raw = TB6612Channel(
        pwm_pin=PWMA, in1_pin=AIN1, in2_pin=AIN2, stby=stby
    )
    drive_ch = DrivePulse(drive_raw, pulse_s=args.drive_pulse)
    steer_ch = TB6612Channel(
        pwm_pin=PWMB, in1_pin=BIN1, in2_pin=BIN2, stby=stby
)
    steer = SteeringPulse(steer_ch, pulse_s=args.steer_pulse, power=args.steer_power)

    period = 1.0 / max(1.0, args.fps)

    def format_cmd_log(cmd: Command, dt_s: float) -> str:
        base = f"{cmd.drive}/{cmd.steer}"
        if cmd.reason:
            base += f" | {cmd.reason}"
        base += f" | +{dt_s:.3f}s"
        return base

    print(f"GEMO start | mode={args.mode} model={args.model}")
    try:
        if args.mode == "batch":
            client = make_client()
            last_print = time.monotonic()
            while True:
                t0 = time.time()
                jpeg = capture_jpeg_bytes(cam)
                cmd = decide_batch(client, args.model, jpeg)
                apply_cmd(cmd, drive_ch, steer, args.drive_speed)
                now = time.monotonic()
                print(format_cmd_log(cmd, now - last_print))
                last_print = now
                dt = time.time() - t0
                if dt < period:
                    time.sleep(period - dt)

        else:
            def frame_provider():
                return capture_jpeg_bytes(cam)

            last_print = time.monotonic()
            def on_command(cmd: Command):
                nonlocal last_print
                apply_cmd(cmd, drive_ch, steer, args.drive_speed)
                now = time.monotonic()
                print(format_cmd_log(cmd, now - last_print))
                last_print = now

            asyncio.run(run_live_loop(
                model=args.model,
                frame_provider=frame_provider,
                on_command=on_command,
                loop_delay_s=period,
            ))

    finally:
        # Ensure motors are stopped and steering centered
        drive_ch.stop()
        steer.center()
        steer_ch.stop()
        cam.stop()

if __name__ == "__main__":
    main()
