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
from app.logger import get_logger
from app.routers.service_helpers import error_detail
from app.utils.api_key_manager import get_llm_client, with_llm_retry_sync

logger = get_logger(__name__)

router = APIRouter(prefix="", tags=["tts"])


class TTSRequest(BaseModel):
    text: str
    voice_name: Optional[str] = "Zephyr"
    model: Optional[str] = None
    target_mime: Optional[str] = "audio/wav"


def _to_bytes(audio_data) -> bytes:
    if isinstance(audio_data, (bytes, bytearray)):
        return bytes(audio_data)
    if isinstance(audio_data, str):
        try:
            return base64.b64decode(audio_data, validate=False)
        except Exception as error:
            raise ValueError(
                f"Expected bytes or base64 string; got non-base64 str: {error}"
            )
    raise ValueError(f"Unsupported audio data type: {type(audio_data)!r}")


def _rate_from_mime(mime_type: str, default_rate: int = 24000) -> int:
    if not mime_type:
        return default_rate
    match = re.search(r"rate\s*=\s*(\d+)", mime_type, flags=re.IGNORECASE)
    return int(match.group(1)) if match else default_rate


def pcm_to_wav(
    pcm_data: bytes,
    sample_rate: int = 24000,
    channels: int = 1,
    sample_width: int = 2,
) -> bytes:
    byte_rate = sample_rate * channels * sample_width
    block_align = channels * sample_width
    data_size = len(pcm_data)
    riff_chunk_size = 36 + data_size

    buffer = io.BytesIO()
    buffer.write(b"RIFF")
    buffer.write(struct.pack("<I", riff_chunk_size))
    buffer.write(b"WAVE")
    buffer.write(b"fmt ")
    buffer.write(struct.pack("<I", 16))
    buffer.write(struct.pack("<H", 1))
    buffer.write(struct.pack("<H", channels))
    buffer.write(struct.pack("<I", sample_rate))
    buffer.write(struct.pack("<I", byte_rate))
    buffer.write(struct.pack("<H", block_align))
    buffer.write(struct.pack("<H", sample_width * 8))
    buffer.write(b"data")
    buffer.write(struct.pack("<I", data_size))
    buffer.write(pcm_data)

    wav_data = buffer.getvalue()
    logger.debug("[WAV] sample_rate=%s total=%s", sample_rate, len(wav_data))
    return wav_data


def _find_inline_audio_part(resp: types.GenerateContentResponse) -> Optional[types.Part]:
    if hasattr(resp, "parts") and resp.parts:
        for part in resp.parts:
            inline_data = getattr(part, "inline_data", None)
            mime_type = getattr(inline_data, "mime_type", "")
            if inline_data and mime_type.lower().startswith("audio/"):
                return part

    for candidate in getattr(resp, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        if not content:
            continue
        for part in getattr(content, "parts", []) or []:
            inline_data = getattr(part, "inline_data", None)
            mime_type = getattr(inline_data, "mime_type", "")
            if inline_data and mime_type.lower().startswith("audio/"):
                return part
    return None


def _make_client(api_key: str) -> genai.Client:
    return get_llm_client(api_key)


def _synthesize_once(
    api_key: str,
    text: str,
    voice_name: Optional[str],
    model_name: Optional[str],
) -> Tuple[bytes, str]:
    del model_name
    _settings = get_settings()
    _model = "tts-1"

    client = get_llm_client(api_key)
    voice_map = {
        "Zephyr": "alloy",
        "Puck": "echo",
        "Charon": "fable",
        "Kore": "onyx",
        "Fenrir": "nova",
        "Aoede": "shimmer",
    }
    openai_voice = voice_map.get(voice_name or "Zephyr", "alloy")

    response = client.audio.speech.create(
        model=_model,
        voice=openai_voice,
        input=text,
        response_format="mp3",
    )
    audio_bytes = response.content
    mime_type = "audio/mpeg"
    logger.debug("[TTS] mime=%s raw_size=%s", mime_type, len(audio_bytes))
    return audio_bytes, mime_type


@router.post("/tts")
def tts(req: TTSRequest):
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(
            status_code=400,
            detail=error_detail("Text must not be empty."),
        )

    try:
        audio_bytes, mime_type = with_llm_retry_sync(
            "TTS generation",
            _synthesize_once,
            text,
            req.voice_name,
            req.model,
            error_type=HTTPException,
        )
    except HTTPException:
        raise
    except Exception as error:
        logger.error("[TTS] generation failed: %s", error, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=error_detail("TTS generation failed.", details=str(error)),
        ) from error

    logger.debug("[TTS] final_return mime=%s size=%s", mime_type, len(audio_bytes))
    return Response(content=audio_bytes, media_type=mime_type or "audio/mpeg")
