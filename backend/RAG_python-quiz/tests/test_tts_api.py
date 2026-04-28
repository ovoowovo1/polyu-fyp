import base64
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.routers import tts
from tests.support import build_client


class TtsApiTests(unittest.TestCase):
    def setUp(self):
        self.client = build_client(tts.router)

    def test_to_bytes_accepts_bytes(self):
        self.assertEqual(tts._to_bytes(b"abc"), b"abc")

    def test_to_bytes_decodes_base64_string(self):
        encoded = base64.b64encode(b"hello").decode("utf-8")
        self.assertEqual(tts._to_bytes(encoded), b"hello")

    def test_to_bytes_rejects_invalid_type(self):
        with self.assertRaises(ValueError):
            tts._to_bytes(123)

    def test_to_bytes_wraps_base64_decode_errors(self):
        with patch("app.routers.tts.base64.b64decode", side_effect=ValueError("bad base64")):
            with self.assertRaises(ValueError) as ctx:
                tts._to_bytes("bad")

        self.assertIn("non-base64 str", str(ctx.exception))

    def test_rate_from_mime_uses_default_when_missing(self):
        self.assertEqual(tts._rate_from_mime(""), 24000)

    def test_rate_from_mime_extracts_rate(self):
        self.assertEqual(tts._rate_from_mime("audio/L16;codec=pcm;rate=16000"), 16000)

    def test_pcm_to_wav_wraps_pcm_payload(self):
        wav = tts.pcm_to_wav(b"\x00\x01\x02\x03", sample_rate=16000)
        self.assertTrue(wav.startswith(b"RIFF"))
        self.assertIn(b"WAVE", wav[:12])

    def test_find_inline_audio_part_prefers_response_parts(self):
        part = SimpleNamespace(inline_data=SimpleNamespace(mime_type="audio/mpeg"))
        response = SimpleNamespace(parts=[part], candidates=[])
        self.assertIs(tts._find_inline_audio_part(response), part)

    def test_find_inline_audio_part_falls_back_to_candidates(self):
        part = SimpleNamespace(inline_data=SimpleNamespace(mime_type="audio/wav"))
        response = SimpleNamespace(parts=[], candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])
        self.assertIs(tts._find_inline_audio_part(response), part)

    def test_find_inline_audio_part_returns_none_when_candidate_has_no_content_or_audio(self):
        response = SimpleNamespace(
            parts=[],
            candidates=[
                SimpleNamespace(content=None),
                SimpleNamespace(content=SimpleNamespace(parts=[SimpleNamespace(inline_data=SimpleNamespace(mime_type="text/plain"))])),
            ],
        )
        self.assertIsNone(tts._find_inline_audio_part(response))

    def test_make_client_delegates_to_genai_client_factory(self):
        with patch("app.routers.tts.get_llm_client", return_value="client") as get_client:
            client = tts._make_client("api-key")

        self.assertEqual(client, "client")
        get_client.assert_called_once_with("api-key")

    def test_synthesize_once_maps_voice_and_returns_audio_bytes(self):
        response = SimpleNamespace(content=b"audio")
        audio = SimpleNamespace(speech=SimpleNamespace(create=Mock(return_value=response)))
        client = SimpleNamespace(audio=audio)

        with patch("app.routers.tts.get_settings", return_value=SimpleNamespace()), patch(
            "app.routers.tts.get_llm_client",
            return_value=client,
        ):
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

    def test_tts_route_wraps_unexpected_failure(self):
        with patch("app.routers.tts.with_llm_retry_sync", side_effect=RuntimeError("boom")):
            response = self.client.post("/tts", json={"text": "Hello"})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"]["error"], "TTS generation failed.")

    def test_tts_route_passes_through_http_exception(self):
        with patch(
            "app.routers.tts.with_llm_retry_sync",
            side_effect=tts.HTTPException(status_code=429, detail={"error": "rate limited"}),
        ):
            response = self.client.post("/tts", json={"text": "Hello"})

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["detail"]["error"], "rate limited")

