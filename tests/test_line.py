"""เทสช่องทาง LINE (ไม่เรียก LINE/LLM จริง — จำลองทั้งหมด)"""

import base64
import hashlib
import hmac
import json
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from channels import line_webhook
from chatbot import assistant
from chatbot.assistant import Reply
from chatbot.conversation_store import InMemoryConversationStore
from config import settings
from vision import documents

SECRET = "test-secret"


def sign(body: bytes) -> str:
    return base64.b64encode(hmac.new(SECRET.encode(), body, hashlib.sha256).digest()).decode()


def event(message: dict, user="U123") -> bytes:
    return json.dumps({"events": [{
        "type": "message", "replyToken": "rt-1", "source": {"type": "user", "userId": user}, "message": message,
    }]}).encode()


class LineWebhookTests(unittest.TestCase):
    def setUp(self):
        from main import app

        self.sent = []      # ข้อความที่ส่งกลับ LINE
        self.asked = []     # (session, ข้อความ, extra_system) ที่ส่งเข้า assistant
        real_client = httpx.AsyncClient

        def line_api(request: httpx.Request):
            if request.url.path.endswith("/message/reply"):
                self.sent.append(json.loads(request.content))
            if request.url.path.endswith("/content"):
                return httpx.Response(200, content=b"\xff\xd8\xffJPEG", headers={"content-type": "image/jpeg"})
            return httpx.Response(200, json={})

        async def fake_respond(session_id, message, **kw):
            self.asked.append((session_id, message, kw.get("extra_system", "")))
            return Reply(text="**ราคา** อาบน้ำ 250 บาทค่ะ")

        self.store = InMemoryConversationStore()
        for target, attr, value in [
            (settings, "LINE_CHANNEL_SECRET", SECRET),
            (settings, "LINE_CHANNEL_ACCESS_TOKEN", "token"),
            (line_webhook.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(line_api))),
            (assistant, "respond", fake_respond),
            (assistant, "store", self.store),
            (line_webhook, "get_store", lambda: self.store),
        ]:
            p = patch.object(target, attr, value)
            p.start()
            self.addCleanup(p.stop)
        self.client = TestClient(app)

    def post(self, body: bytes, signature: str | None = "auto"):
        headers = {"Content-Type": "application/json"}
        if signature:
            headers["X-Line-Signature"] = sign(body) if signature == "auto" else signature
        return self.client.post("/line/webhook", content=body, headers=headers)

    def test_bad_or_missing_signature_is_rejected(self):
        body = event({"type": "text", "text": "สวัสดี"})
        self.assertEqual(self.post(body, signature="forged").status_code, 401)
        self.assertEqual(self.post(body, signature=None).status_code, 401)
        self.assertEqual(self.asked, [])

    def test_text_goes_through_assistant_and_reply_is_plain_text(self):
        r = self.post(event({"type": "text", "text": "อาบน้ำหมาเล็กเท่าไหร่"}))
        self.assertEqual(r.status_code, 200)
        session, message, hint = self.asked[0]
        self.assertEqual((session, message), ("line:U123", "อาบน้ำหมาเล็กเท่าไหร่"))
        self.assertIn("/?book=1", hint)                   # LINE ไม่มีปุ่มจอง → ส่งลิงก์เว็บ
        sent = self.sent[0]
        self.assertEqual(sent["replyToken"], "rt-1")
        self.assertEqual(sent["messages"][0]["text"], "ราคา อาบน้ำ 250 บาทค่ะ")  # ตัด ** ออก

    def test_each_line_user_has_own_session(self):
        self.post(event({"type": "text", "text": "a"}, user="U1"))
        self.post(event({"type": "text", "text": "b"}, user="U2"))
        self.assertEqual([a[0] for a in self.asked], ["line:U1", "line:U2"])

    def test_pet_photo_gets_code_made_reply_and_is_saved(self):
        async def fake_extract(name, mime, data):
            return {"name": name, "kind": "image", "text": "", "meta": {"image_type": "pet", "reply": "น้องไซส์เล็ก อาบน้ำ 250 บาทค่ะ"}}

        with patch.object(documents, "extract", fake_extract):
            self.post(event({"type": "image", "id": "m1"}))
        self.assertIn("250 บาท", self.sent[0]["messages"][0]["text"])
        import asyncio
        history = asyncio.run(self.store.get_history("line:U123"))
        self.assertEqual(history[0]["content"], assistant.IMAGE_MARKER)

    def test_unsupported_message_and_disabled_channel(self):
        self.post(event({"type": "sticker", "id": "s1"}))
        self.assertIn("ข้อความกับรูปภาพ", self.sent[0]["messages"][0]["text"])
        with patch.object(settings, "LINE_CHANNEL_SECRET", None):
            self.assertEqual(self.post(event({"type": "text", "text": "x"})).status_code, 503)

    def test_markdown_cleanup(self):
        self.assertEqual(line_webhook.plain_text("## หัวข้อ\n* ข้อหนึ่ง\n**หนา**"), "หัวข้อ\n- ข้อหนึ่ง\nหนา")


if __name__ == "__main__":
    unittest.main()
