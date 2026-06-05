import base64
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.routers import tts
from tests.support import build_client


def inline_audio_part(mime_type):
    return SimpleNamespace(inline_data=SimpleNamespace(mime_type=mime_type))


def tts_response(*, parts=None, candidates=None):
    return SimpleNamespace(parts=parts or [], candidates=candidates or [])


def candidate(parts=None, content=True):
    return SimpleNamespace(content=SimpleNamespace(parts=parts or []) if content else None)


class TtsApiTests(unittest.TestCase):
    def setUp(self):
        self.client = build_client(tts.router)

    def test_to_bytes_accepts_bytes_and_decodes_base64_string(self):
        cases = (
            (b"abc", b"abc"),
            (base64.b64encode(b"hello").decode("utf-8"), b"hello"),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(tts._to_bytes(value), expected)

    def test_to_bytes_rejects_invalid_type(self):
        with self.assertRaises(ValueError):
            tts._to_bytes(123)

    def test_to_bytes_wraps_base64_decode_errors(self):
        with patch("app.routers.tts.base64.b64decode", side_effect=ValueError("bad base64")):
            with self.assertRaises(ValueError) as ctx:
                tts._to_bytes("bad")

        self.assertIn("non-base64 str", str(ctx.exception))

    def test_rate_from_mime_uses_default_and_extracts_rate(self):
        cases = (("", 24000), ("audio/L16;codec=pcm;rate=16000", 16000))
        for mime_type, expected in cases:
            with self.subTest(mime_type=mime_type):
                self.assertEqual(tts._rate_from_mime(mime_type), expected)

    def test_pcm_to_wav_wraps_pcm_payload(self):
        wav = tts.pcm_to_wav(b"\x00\x01\x02\x03", sample_rate=16000)
        self.assertTrue(wav.startswith(b"RIFF"))
        self.assertIn(b"WAVE", wav[:12])

    def test_find_inline_audio_part_prefers_response_parts(self):
        part = inline_audio_part("audio/mpeg")
        self.assertIs(tts._find_inline_audio_part(tts_response(parts=[part])), part)

    def test_find_inline_audio_part_falls_back_to_candidates(self):
        part = inline_audio_part("audio/wav")
        self.assertIs(tts._find_inline_audio_part(tts_response(candidates=[candidate([part])])), part)

    def test_find_inline_audio_part_returns_none_when_candidate_has_no_content_or_audio(self):
        text_part = inline_audio_part("text/plain")
        self.assertIsNone(tts._find_inline_audio_part(tts_response(candidates=[candidate(content=False), candidate([text_part])])))

    def test_synthesize_once_maps_voice_and_returns_audio_bytes(self):
        response = SimpleNamespace(content=b"audio")
        audio = SimpleNamespace(speech=SimpleNamespace(create=Mock(return_value=response)))
        client = SimpleNamespace(audio=audio)

        with patch("app.routers.tts.get_llm_client", return_value=client):
            data, mime_type = tts._synthesize_once("api-key", "hello", "Kore", None)

        self.assertEqual(data, b"audio")
        self.assertEqual(mime_type, "audio/mpeg")
        self.assertEqual(client.audio.speech.create.call_args.kwargs["voice"], "onyx")

    def test_tts_route_rejects_empty_text(self):
        response = self.client.post("/tts", json={"text": "  "})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["error"], "Text must not be empty.")

    def test_tts_route_returns_audio_bytes(self):
        with patch("app.routers.tts.with_llm_retry_sync", return_value=(b"audio", "audio/mpeg")):
            response = self.client.post("/tts", json={"text": "Hello"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"audio")
        self.assertEqual(response.headers["content-type"], "audio/mpeg")

    def test_tts_route_maps_generation_failures(self):
        cases = (
            (RuntimeError("boom"), 500, "TTS generation failed."),
            (tts.HTTPException(status_code=429, detail={"error": "rate limited"}), 429, "rate limited"),
        )
        for side_effect, status, error in cases:
            with self.subTest(status=status), patch("app.routers.tts.with_llm_retry_sync", side_effect=side_effect):
                response = self.client.post("/tts", json={"text": "Hello"})
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json()["detail"]["error"], error)

