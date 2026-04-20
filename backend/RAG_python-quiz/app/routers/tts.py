# To run this code you need to install the following dependencies:
# pip install google-genai

import base64
import io
import re
import struct
from typing import Optional, Tuple

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from google import genai
from google.genai import types

from app.config import get_settings
from app.utils.api_key_manager import with_gemini_retry_sync, get_genai_client
from app.logger import get_logger

logger = get_logger(__name__)

# -----------------------------------------------------------------------------
# Router (no new FastAPI app here)
# -----------------------------------------------------------------------------
router = APIRouter(prefix="", tags=["tts"])

# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------
class TTSRequest(BaseModel):
    text: str
    voice_name: Optional[str] = "Zephyr" 
    model: Optional[str] = None     
    target_mime: Optional[str] = "audio/wav"


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _to_bytes(audio_data) -> bytes:
    """
    Gemini Python SDK usually returns bytes (NOT base64 string) in inline_data.data.
    Only base64-decode if it's a str. This prevents corrupting the payload.
    """
    if isinstance(audio_data, (bytes, bytearray)):
        return bytes(audio_data)
    if isinstance(audio_data, str):
        # Some transports (REST/JS) return base64 strings. Decode those.
        try:
            return base64.b64decode(audio_data, validate=False)
        except Exception as e:
            raise ValueError(f"Expected bytes or base64 string; got non-base64 str: {e}")
    raise ValueError(f"Unsupported audio data type: {type(audio_data)!r}")


def _rate_from_mime(mime_type: str, default_rate: int = 24000) -> int:
    """
    Parse sample rate from mime strings like:
    'audio/L16;rate=24000' or 'audio/L16;codec=pcm;rate=24000'
    """
    if not mime_type:
        return default_rate
    m = re.search(r"rate\s*=\s*(\d+)", mime_type, flags=re.IGNORECASE)
    return int(m.group(1)) if m else default_rate


def pcm_to_wav(pcm_data: bytes, sample_rate: int = 24000, channels: int = 1, sample_width: int = 2) -> bytes:
    """
    Wrap raw 16-bit PCM (little-endian) into a WAV container.
    This mirrors the structure you already had (RIFF/WAVE fmt/data).
    """
    # WAV header sizes
    byte_rate = sample_rate * channels * sample_width
    block_align = channels * sample_width
    data_size = len(pcm_data)
    riff_chunk_size = 36 + data_size

    buf = io.BytesIO()

    # RIFF header
    buf.write(b'RIFF')
    buf.write(struct.pack('<I', riff_chunk_size))
    buf.write(b'WAVE')

    # fmt  subchunk
    buf.write(b'fmt ')
    buf.write(struct.pack('<I', 16))                    # Subchunk1Size for PCM
    buf.write(struct.pack('<H', 1))                     # AudioFormat = 1 (PCM)
    buf.write(struct.pack('<H', channels))              # NumChannels
    buf.write(struct.pack('<I', sample_rate))           # SampleRate
    buf.write(struct.pack('<I', byte_rate))             # ByteRate
    buf.write(struct.pack('<H', block_align))           # BlockAlign
    buf.write(struct.pack('<H', sample_width * 8))      # BitsPerSample

    # data subchunk
    buf.write(b'data')
    buf.write(struct.pack('<I', data_size))
    buf.write(pcm_data)

    wav_data = buf.getvalue()

    # Debug logs (kept concise)
    logger.debug(f"[WAV] header first 44 bytes: {wav_data[:44].hex()}")
    logger.debug(f"[WAV] sample_rate={sample_rate}, channels={channels}, bits={sample_width*8}, total={len(wav_data)}")
    return wav_data


def _find_inline_audio_part(resp: types.GenerateContentResponse) -> Optional[types.Part]:
    """
    Locate the first inline audio part.
    """
    # Primary path with new SDK
    if hasattr(resp, "parts") and resp.parts:
        for p in resp.parts:
            if getattr(p, "inline_data", None) and getattr(p.inline_data, "mime_type", ""):
                if p.inline_data.mime_type.lower().startswith("audio/"):
                    return p

    # Fallback: scan candidates if present
    for cand in getattr(resp, "candidates", []) or []:
        content = getattr(cand, "content", None)
        if not content:
            continue
        for p in getattr(content, "parts", []) or []:
            if getattr(p, "inline_data", None) and getattr(p.inline_data, "mime_type", ""):
                if p.inline_data.mime_type.lower().startswith("audio/"):
                    return p
    return None


def _make_client(api_key: str) -> genai.Client:
    return get_genai_client(api_key)


def _synthesize_once(api_key: str, text: str, voice_name: Optional[str], model_name: Optional[str]) -> Tuple[bytes, str]:
    """
    Single attempt to synthesize audio with OpenAI. Returns (audio_bytes, mime_type).
    """
    settings = get_settings()
    # OpenAI TTS models: tts-1 or tts-1-hd
    model = "tts-1" 

    client = get_genai_client(api_key)

    # OpenAI TTS API
    # Voice options: alloy, echo, fable, onyx, nova, shimmer
    # Map Gemini voices to OpenAI voices if needed, or use a default
    openai_voice = "alloy"
    if voice_name:
        voice_map = {
            "Zephyr": "alloy", # Example mapping
            "Puck": "echo",
            "Charon": "fable",
            "Kore": "onyx",
            "Fenrir": "nova",
            "Aoede": "shimmer"
        }
        openai_voice = voice_map.get(voice_name, "alloy")

    response = client.audio.speech.create(
        model=model,
        voice=openai_voice,
        input=text,
        response_format="mp3" # OpenAI returns mp3 by default, or opus, aac, flac. wav is not directly supported but mp3 is fine for browsers.
    )

    # OpenAI returns binary content directly
    audio_bytes = response.content
    mime_type = "audio/mpeg" # mp3

    logger.debug(f"[TTS] mime={mime_type}, raw_size={len(audio_bytes)} bytes")
    return audio_bytes, mime_type


# -----------------------------------------------------------------------------
# Route
# -----------------------------------------------------------------------------
@router.post("/tts")
def tts(req: TTSRequest):
    """
    Generate speech using Gemini and return audio/wav for browser playback.
    - No new FastAPI() app is created; this is just the router endpoint.
    - Uses unified retry mechanism with automatic key rotation.
    """
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text must not be empty.")

    # 使用統一的重試機制
    audio_bytes, mime_type = with_gemini_retry_sync(
        "語音合成",
        _synthesize_once,
        text,
        req.voice_name,
        req.model,
        error_type=HTTPException
    )

    # OpenAI returns MP3, no need to wrap in WAV container if we return audio/mpeg
    # But if the frontend expects WAV, we might need to convert or just return MP3 and hope frontend handles it.
    # Most browsers handle audio/mpeg fine.
    # Let's return the bytes directly with the correct mime type.
    
    logger.debug(f"[TTS] final_return mime={mime_type}, size={len(audio_bytes)}")
    return Response(content=audio_bytes, media_type=mime_type or "audio/mpeg")
