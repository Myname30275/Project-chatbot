import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from main import app
from config import settings


class TTSTests(unittest.TestCase):
    def test_stream_and_language(self):
        real_client = httpx.AsyncClient
        requests = []
        def upstream(request):
            requests.append(request)
            return httpx.Response(200, content=b"\x00\x00\xff\x7f")
        def factory(**kwargs):
            return real_client(transport=httpx.MockTransport(upstream))
        with patch.object(settings, "CARTESIA_API_KEY", "test-only"), patch(
            "channels.tts.httpx.AsyncClient", side_effect=factory
        ), TestClient(app) as client:
            for text, lang in [("สวัสดีค่ะ", "th"), ("Hello", "en")]:
                response = client.post("/api/v1/tts/stream", json={"text": text})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, b"\x00\x00\xff\x7f")
                import json
                self.assertEqual(json.loads(requests[-1].content)["language"], lang)
            self.assertNotIn("test-only", client.get("/api/v1/tts/config").text)

    def test_voice_id_overrides_default_and_falls_back_when_absent(self):
        real_client = httpx.AsyncClient
        requests = []
        def upstream(request):
            requests.append(request)
            return httpx.Response(200, content=b"\x00\x00\xff\x7f")
        def factory(**kwargs):
            return real_client(transport=httpx.MockTransport(upstream))
        with patch.object(settings, "CARTESIA_API_KEY", "test-only"), patch.object(
            settings, "CARTESIA_VOICE_ID", "default-voice"
        ), patch("channels.tts.httpx.AsyncClient", side_effect=factory), TestClient(app) as client:
            import json
            client.post("/api/v1/tts/stream", json={"text": "Hi", "voice_id": "picked-voice"})
            self.assertEqual(json.loads(requests[-1].content)["voice"], "picked-voice")
            client.post("/api/v1/tts/stream", json={"text": "Hi"})
            self.assertEqual(json.loads(requests[-1].content)["voice"], "default-voice")

    def test_missing_key_and_invalid_text(self):
        with patch.object(settings, "CARTESIA_API_KEY", ""), TestClient(app) as client:
            self.assertEqual(client.post("/api/v1/tts/stream", json={"text":"Hello"}).status_code, 503)
            self.assertEqual(client.post("/api/v1/tts/stream", json={"text":""}).status_code, 422)

    def test_provider_error_does_not_expose_body(self):
        real_client = httpx.AsyncClient
        def factory(**kwargs):
            return real_client(transport=httpx.MockTransport(
                lambda request: httpx.Response(401, text="private-provider-detail")))
        with patch.object(settings, "CARTESIA_API_KEY", "test-only"), patch(
            "channels.tts.httpx.AsyncClient", side_effect=factory
        ), TestClient(app) as client:
            response = client.post("/api/v1/tts/stream", json={"text":"Hello"})
            self.assertEqual(response.status_code, 502)
            self.assertNotIn("private-provider-detail", response.text)


if __name__ == "__main__":
    unittest.main()
