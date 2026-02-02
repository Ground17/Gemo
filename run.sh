#!/bin/bash
set -e

cd /home/pi/gemo
source venv/bin/activate
python rc_autodrive_gemini_gpio.py
