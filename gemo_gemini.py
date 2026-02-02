import os, base64, asyncio, time
from dataclasses import dataclass
from typing import Literal

from google import genai
from google.genai import types

import asyncio
import websockets

Drive = Literal["FORWARD", "STOP", "REVERSE"]
Steer = Literal["LEFT", "CENTER", "RIGHT"]

@dataclass(frozen=True)
class Command:
    drive: Drive = "STOP"
    steer: Steer = "CENTER"
    reason: str = ""

# ---- tool schema ----
TOOLS_DECL = types.Tool(function_declarations=[{
    "name": "set_rc_controls",
    "description": "Return RC car control commands.",
    "parameters": {
        "type": "object",
        "properties": {
            "drive": {"type": "string", "enum": ["FORWARD","STOP","REVERSE"]},
            "steer": {"type": "string", "enum": ["LEFT","CENTER","RIGHT"]},
            "reason": {"type": "string"},
        },
        "required": ["drive","steer"]
    }
}])

BASE_PROMPT_DEFAULT = (
    "You are an autonomous RC car controller. "
    "Analyze the front camera image and decide the safest drive/steer. "
    "If uncertain, choose STOP and CENTER. "
    "You MUST respond by calling function set_rc_controls."
    "The reason must be a short noun phrase, no punctuation."
)

def make_silence_pcm16(rate: int = 16000, duration_s: float = 0.10) -> bytes:
    """16-bit PCM mono silence, little-endian."""
    samples = int(rate * duration_s)
    return b"\x00\x00" * samples

def make_client():
    """
    - ??: Gemini Developer API (GEMINI_API_KEY)
    - Live/Vertex ? ?: VERTEX_PROJECT + VERTEX_LOCATION ??? vertexai=True? ??
    """
    project = os.getenv("VERTEX_PROJECT")
    location = os.getenv("VERTEX_LOCATION")
    if project and location:
        return genai.Client(vertexai=True, project=project, location=location)
    return genai.Client()

def _sanitize(drive: str, steer: str, reason: str = "") -> Command:
    if drive not in ("FORWARD","STOP","REVERSE"):
        drive = "STOP"
    if steer not in ("LEFT","CENTER","RIGHT"):
        steer = "CENTER"
    return Command(drive=drive, steer=steer, reason=reason or "")
    
# -------------------------
# Batch (generate_content) : gemini-3-flash-preview / gemini-3-pro-preview / robotics-er
# -------------------------
def decide_batch(client: genai.Client, model: str, jpeg: bytes, base_prompt: str = BASE_PROMPT_DEFAULT) -> Command:
    if model == "gemini-3-pro-preview":
        thinking_cfg = types.ThinkingConfig(thinking_budget=128)
    else:
        thinking_cfg = types.ThinkingConfig(thinking_budget=0)

    cfg = types.GenerateContentConfig(
        tools=[TOOLS_DECL],
        temperature=0.2,
        thinking_config=thinking_cfg,
    )

    resp = client.models.generate_content(
        model=model,
        contents=[
            types.Part(text=base_prompt),
            types.Part.from_bytes(data=jpeg, mime_type="image/jpeg"),
        ],
        config=cfg,
    )

    try:
        parts = resp.candidates[0].content.parts
        fc = next((p.function_call for p in parts if getattr(p, "function_call", None)), None)
        if not fc or fc.name != "set_rc_controls":
            return Command()
        args = fc.args or {}
        return _sanitize(args.get("drive","STOP"), args.get("steer","CENTER"), args.get("reason",""))
    except Exception:
        return Command()
        
# -------------------------
# Live (WebSocket session) : gemini-2.5-flash-native-audio-preview-12-2025
# -------------------------
async def _decide_live_once(session, jpeg: bytes, timeout_s: float = 1.5) -> Command:
    # 1) 무음 오디오(PCM16 16kHz) 먼저 전송 (native-audio 모델 안정화)
    silence = make_silence_pcm16(rate=16000, duration_s=0.10)
    await session.send_realtime_input(
        audio=types.Blob(data=silence, mime_type="audio/pcm;rate=16000")
    )

    # 2) 그 다음 비디오(JPEG 프레임) 전송 — send_realtime_input은 한 번에 하나만!
    b64 = base64.b64encode(jpeg).decode("utf-8")
    await session.send_realtime_input(
        video=types.Blob(data=b64, mime_type="image/jpeg")
    )

    async def wait_toolcall() -> Command:
        async for msg in session.receive():
            if msg.tool_call:
                for fc in msg.tool_call.function_calls:
                    if fc.name != "set_rc_controls":
                        continue

                    args = fc.args or {}
                    cmd = _sanitize(
                        args.get("drive", "STOP"),
                        args.get("steer", "CENTER"),
                        args.get("reason", ""),
                    )

                    # Live API: tool response 필수
                    await session.send_tool_response(function_responses=[
                        types.FunctionResponse(id=fc.id, name=fc.name, response={"result": "ok"})
                    ])
                    return cmd
        return Command()

    try:
        return await asyncio.wait_for(wait_toolcall(), timeout=timeout_s)
    except asyncio.TimeoutError:
        return Command()
    
# =========================
# Public Live-loop wrapper
# =========================
async def run_live_loop(
    model: str,
    frame_provider,      # callable -> jpeg bytes
    on_command,          # callable(Command) -> None
    base_prompt: str = BASE_PROMPT_DEFAULT,
    loop_delay_s: float = 0.2,
):
    client = make_client()

    config = {
        "tools": [{"function_declarations": TOOLS_DECL.function_declarations}],
        # native-audio는 AUDIO 모달리티가 안정적
        "response_modalities": ["AUDIO"],
    }

    while True:
        try:
            async with client.aio.live.connect(model=model, config=config) as session:
                await session.send_client_content(
                    turns={"role": "user", "parts": [{"text": base_prompt}]},
                    turn_complete=True,
                )

                while True:
                    jpeg = frame_provider()

                    # ✅ timeout 포함: tool_call이 안 오면 기본값 반환하고 다음 프레임으로 계속
                    cmd = await _decide_live_once(session, jpeg, timeout_s=1.5)
                    on_command(cmd)

                    await asyncio.sleep(loop_delay_s)

        except (websockets.exceptions.ConnectionClosedError,
                websockets.exceptions.ConnectionClosedOK,
                Exception) as e:
            # 연결이 끊기거나 서버가 세션을 닫으면 여기로 옴 → 잠깐 쉬고 자동 재연결
            print(f"[LIVE] reconnecting due to: {type(e).__name__}: {e}")
            await asyncio.sleep(1.0)