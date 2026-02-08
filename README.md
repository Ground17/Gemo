# Gemo - RC Car Control with Gemini

## Overview
Gemo is an RC car controller that uses Google Gemini, a Raspberry Pi camera, and GPIO motor drivers to decide drive/steer commands from camera frames.

## Requirements
- Raspberry Pi 4/5
- Raspberry Pi Camera
- TB6612FNG (or L298N) motor driver
- DC motors (drive + steering)
- Google Gemini API key

## Features
- Batch mode: capture a frame, ask Gemini for a control command, apply it, repeat.
- Live mode: persistent WebSocket session with native-audio model.
- Safe command defaults: invalid or missing tool calls fall back to `STOP/CENTER`.
- Drive pulse control: forward/reverse are short pulses followed by stop to prevent continuous driving.
- Steering pulse control: short left/right pulses with a minimum interval.
- Logging includes command, reason (optional), and elapsed time since the last log.
- Retry handling for transient 500 errors in batch mode.

## Usage

### Basic run (batch mode)
```bash
python gemo_main.py
```

### Live mode (native-audio)
```bash
python gemo_main.py --mode live
```

### Choose a specific model
```bash
python gemo_main.py --model gemini-3-flash-preview
python gemo_main.py --model gemini-2.5-flash-native-audio-preview-12-2025
```

## Options
- `--mode`: Run mode (`batch`/`live`, default: `batch`)
- `--model`: Gemini model to use
- `--fps`: Frame rate (default: `5.0`)
- `--drive_speed`: Drive speed (default: `0.45`)
- `--drive_pulse`: Drive pulse duration in seconds (default: `0.12`)
- `--steer_pulse`: Steering pulse duration in seconds (default: `0.10`)
- `--steer_power`: Steering power (default: `0.80`)

## Files
- `gemo_main.py`: Main application
- `gemo_gemini.py`: Gemini API integration (batch + live)
- `gemo_gpio.py`: GPIO motor control utilities
- `run.sh`: Run script
