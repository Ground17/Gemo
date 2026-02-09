import os, asyncio, time, base64
from dataclasses import dataclass
from typing import Literal

from google import genai
from google.genai import types, errors as genai_errors

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
    "You MUST respond by calling function set_rc_controls. "
    "The reason must be a short noun phrase, no punctuation."
)

def make_silence_pcm16(rate: int = 16000, duration_s: float = 0.10) -> bytes:
    """16-bit PCM mono silence, little-endian."""
    samples = int(rate * duration_s)
    return b"\x00\x00" * samples

def make_client():
    """
    - Dev API: GEMINI_API_KEY
    - Vertex: VERTEX_PROJECT + VERTEX_LOCATION
    """
    project = os.getenv("VERTEX_PROJECT")
    location = os.getenv("VERTEX_LOCATION")
    if project and location:
        return genai.Client(vertexai=True, project=project, location=location)
    return genai.Client(http_options={"api_version": "v1beta"})

def _sanitize(drive: str, steer: str, reason: str = "") -> Command:
    if drive not in ("FORWARD","STOP","REVERSE"):
        drive = "STOP"
    if steer not in ("LEFT","CENTER","RIGHT"):
        steer = "CENTER"
    return Command(drive=drive, steer=steer, reason=reason or "")
    
# -------------------------
# Batch (generate_content) : gemini-3-flash-preview / gemini-3-pro-preview / robotics-er
# -------------------------
def decide_batch(
    client: genai.Client,
    model: str,
    jpeg: bytes,
    base_prompt: str = BASE_PROMPT_DEFAULT,
    max_retries: int = 2,
    retry_delay_s: float = 0.4,
) -> Command:
    if model == "gemini-3-pro-preview":
        thinking_cfg = types.ThinkingConfig(thinking_budget=128)
    else:
        thinking_cfg = types.ThinkingConfig(thinking_budget=0)

    cfg = types.GenerateContentConfig(
        tools=[TOOLS_DECL],
        temperature=0.2,
        thinking_config=thinking_cfg,
    )

    resp = None
    for attempt in range(max_retries + 1):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=[
                    types.Part(text=base_prompt),
                    types.Part.from_bytes(data=jpeg, mime_type="image/jpeg"),
                ],
                config=cfg,
            )
            break
        except (genai_errors.ServerError, genai_errors.APIError, Exception) as e:
            if attempt >= max_retries:
                print(f"[BATCH] generate_content failed: {type(e).__name__}: {e}")
                return Command()
            time.sleep(retry_delay_s * (2 ** attempt))

    try:
        if resp is None:
            return Command()
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
async def _decide_live_once(
    session,
    jpeg: bytes,
    timeout_s: float = 2.5,
    send_audio: bool = True,
) -> Command:
    # 1) Optionally send silence (PCM16 16kHz). Only needed for AUDIO modality.
    if send_audio:
        silence = make_silence_pcm16(rate=16000, duration_s=0.10)
        await session.send_realtime_input(audio={"data": silence, "mime_type": "audio/pcm"})

    # 2) Then send video (JPEG frame) — send_realtime_input accepts one at a time.
    b64 = base64.b64encode(jpeg).decode("utf-8")
    await session.send_realtime_input(video={"data": b64, "mime_type": "image/jpeg"})

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

                    # Live API: tool response is required.
                    await session.send_tool_response(function_responses=[
                        types.FunctionResponse(id=fc.id, name=fc.name, response={"result": "ok"})
                    ])
                    return cmd
        return Command(reason="no_tool_call")

    try:
        return await asyncio.wait_for(wait_toolcall(), timeout=timeout_s)
    except asyncio.TimeoutError:
        return Command(reason="timeout")
    
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

    response_modalities = ["TEXT"]
    config = types.LiveConnectConfig(
        response_modalities=response_modalities,
        tools=[{"function_declarations": TOOLS_DECL.function_declarations}],
    )
    send_audio = "AUDIO" in response_modalities

    while True:
        try:
            async with client.aio.live.connect(model=model, config=config) as session:
                await session.send_client_content(
                    turns=types.Content(parts=[types.Part(text=base_prompt)]),
                    turn_complete=True,
                )

                while True:
                    jpeg = frame_provider()

                    # Timeout: if no tool_call arrives, return defaults and continue.
                    cmd = await _decide_live_once(session, jpeg, send_audio=send_audio)
                    on_command(cmd)

                    await asyncio.sleep(loop_delay_s)

        except (websockets.exceptions.ConnectionClosedError,
                websockets.exceptions.ConnectionClosedOK,
                Exception) as e:
            # If the connection drops or the server closes the session, pause and reconnect.
            print(f"[LIVE] reconnecting due to: {type(e).__name__}: {e}")
            await asyncio.sleep(1.0)
