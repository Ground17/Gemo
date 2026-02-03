import os, io, time, argparse, asyncio
from dotenv import load_dotenv
load_dotenv()

from picamera2 import Picamera2
from gpiozero import DigitalOutputDevice

from gemo_gpio import TB6612Channel, SteeringPulse
from gemo_gemini import make_client, decide_batch, run_live_loop, Command

# ===== GPIO pins (BCM) =====
# TB6612FNG: PWMA/AIN1/AIN2 for motor A, PWMB/BIN1/BIN2 for motor B, STBY shared
PWMA, AIN1, AIN2 = 18, 23, 24     # drive (A)
PWMB, BIN1, BIN2 = 19, 27, 22     # steer (B)
STBY = 25                         # standby (shared)

DEFAULT_BATCH_MODEL = "gemini-3-flash-preview"
DEFAULT_LIVE_MODEL  = "gemini-2.5-flash-native-audio-preview-12-2025"

def capture_jpeg_bytes(cam: Picamera2) -> bytes:
    buf = io.BytesIO()
    cam.capture_file(buf, format="jpeg")
    return buf.getvalue()

def apply_cmd(cmd: Command, drive_ch: TB6612Channel, steer: SteeringPulse, drive_speed: float):
    if cmd.drive == "FORWARD":
        drive_ch.forward(drive_speed)
    elif cmd.drive == "REVERSE":
        drive_ch.reverse(drive_speed)
    else:
        drive_ch.stop()

    if cmd.steer == "LEFT":
        steer.left()
    elif cmd.steer == "RIGHT":
        steer.right()
    else:
        steer.center()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["batch","live"], default="batch")
    ap.add_argument("--model", default=None)
    ap.add_argument("--fps", type=float, default=5.0)
    ap.add_argument("--drive_speed", type=float, default=0.45)
    ap.add_argument("--steer_pulse", type=float, default=0.10)
    ap.add_argument("--steer_power", type=float, default=0.80)
    args = ap.parse_args()

    if args.mode == "live":
        # live ??? model ??? ???? native-audio? ??
        args.model = DEFAULT_LIVE_MODEL
    else:
        # batch ?? ??? 3-flash
        if args.model is None:
            args.model = DEFAULT_BATCH_MODEL

    # ?? ??
    if not os.getenv("GEMINI_API_KEY") and not (os.getenv("VERTEX_PROJECT") and os.getenv("VERTEX_LOCATION")):
        raise RuntimeError("GEMINI_API_KEY(.env) ?? VERTEX_PROJECT/LOCATION(.env)? ????.")

    # camera
    cam = Picamera2()
    cam.configure(cam.create_still_configuration(main={"size": (640, 360)}))
    cam.start()

    # gpio
    stby = DigitalOutputDevice(STBY, initial_value=True)

    drive_ch = TB6612Channel(
        pwm_pin=PWMA, in1_pin=AIN1, in2_pin=AIN2, stby=stby
    )
    steer_ch = TB6612Channel(
        pwm_pin=PWMB, in1_pin=BIN1, in2_pin=BIN2, stby=stby
)
    steer = SteeringPulse(steer_ch, pulse_s=args.steer_pulse, power=args.steer_power)

    period = 1.0 / max(1.0, args.fps)

    print(f"GEMO start | mode={args.mode} model={args.model}")
    try:
        if args.mode == "batch":
            client = make_client()
            while True:
                t0 = time.time()
                jpeg = capture_jpeg_bytes(cam)
                cmd = decide_batch(client, args.model, jpeg)
                apply_cmd(cmd, drive_ch, steer, args.drive_speed)
                print(f"{cmd.drive}/{cmd.steer}" + (f" | {cmd.reason}" if cmd.reason else ""))
                dt = time.time() - t0
                if dt < period:
                    time.sleep(period - dt)

        else:
            def frame_provider():
                return capture_jpeg_bytes(cam)

            def on_command(cmd: Command):
                apply_cmd(cmd, drive_ch, steer, args.drive_speed)
                print(f"{cmd.drive}/{cmd.steer}" + (f" | {cmd.reason}" if cmd.reason else ""))

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