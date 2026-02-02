# Gemo - Gemini을 이용한 RC카 제어

## 개요
Gemo는 Google Gemini AI와 라즈베리파이 카메라, GPIO를 활용하여 RC카를 자동으로 제어하는 프로젝트입니다.

## 필요한 것
- 라즈베리파이 4/5
- 라즈베리파이 카메라
- L298N 모터 드라이버
- DC 모터 (구동, 조향용)
- Google Gemini API 키

## 사용법

### 기본 실행 (배치 모드)
```bash
python gemo_main.py
```

### 라이브 모드 (실시간 오디오)
```bash
python gemo_main.py --mode live
```

### 특정 모델 사용
```bash
python gemo_main.py --model gemini-3-flash-preview
python gemo_main.py --model gemini-2.5-flash-native-audio-preview-12-2025
```

## 옵션
- `--mode`: 실행 모드 (batch/live, 기본값: batch)
- `--model`: 사용할 Gemini 모델
- `--fps`: 프레임 속도 (기본값: 5.0)
- `--drive_speed`: 구동 속도 (기본값: 0.45)
- `--steer_pulse`: 조향 펄스 (기본값: 0.10)
- `--steer_power`: 조향 전력 (기본값: 0.80)

## 구성
- `gemo_main.py`: 메인 애플리케이션
- `gemo_gemini.py`: Gemini API 통합
- `gemo_gpio.py`: GPIO 제어
- `run.sh`: 실행 스크립트