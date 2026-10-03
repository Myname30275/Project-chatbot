"""เทสปุ่มทางลัดใต้คำตอบ + คำตอบสำเร็จรูปเมื่อลูกค้าส่งเบอร์/เลขจองให้เช็คคิว (chatbot/actions.py)"""

import asyncio
import unittest
from unittest.mock import patch

from chatbot import actions, assistant, llm_client
from chatbot.conversation_store import InMemoryConversationStore
from guardrails import input_rules, judge
from rag import retriever


def run(coro):
    return asyncio.run(coro)


class SuggestTests(unittest.TestCase):
    def test_buttons_follow_what_the_customer_asked(self):
        for message, expected in [
            ("เช็คคิวให้หน่อย", ["check"]),
            ("ร้านยืนยันคิวยังคะ", ["check"]),
            ("ได้เงินคืนหรือยัง", ["check"]),
            ("อยากยกเลิกคิว", ["cancel"]),
            ("จองไว้แล้วแต่ไปไม่ได้ ยกเลิกยังไง", ["check", "cancel"]),
            ("อยากจองคิววันเสาร์", ["book"]),
            ("ราคาอาบน้ำหมาเล็กเท่าไหร่", []),
        ]:
            with self.subTest(message=message):
                self.assertEqual(actions.suggest(message), expected)

    def test_buttons_also_follow_what_the_bot_pointed_to(self):
        self.assertEqual(actions.suggest("ขอบคุณค่ะ", 'กดปุ่ม "เช็คคิว" ได้เลยค่ะ'), ["check"])
        self.assertEqual(actions.suggest("โอเค", 'กดปุ่ม "จองคิว" ในแชทได้เลยค่ะ'), ["book"])

    def test_lookup_request_detects_phone_or_booking_code(self):
        for message in ["0800600370", "080-060-0370 ค่ะ", "เบอร์ 0812345678 เช็คคิวให้หน่อย",
                        "HH-1004-01", "ยกเลิกคิว hh-1004-01"]:
            with self.subTest(message=message):
                self.assertTrue(actions.lookup_request(message))
        for message in ["ร้านเปิดกี่โมง", "โทร 0812345678 ได้ไหม ร้านเปิดกี่โมง", "หนัก 12 กิโล"]:
            with self.subTest(message=message):
                self.assertFalse(actions.lookup_request(message))

    def test_line_reply_has_link_instead_of_button(self):
        self.assertIn("/check", actions.lookup_reply("line"))
        self.assertIn("ปุ่ม", actions.lookup_reply("web"))
        self.assertNotIn("0800600370", actions.lookup_reply("web"))


class AssistantActionTests(unittest.TestCase):
    def setUp(self):
        self.reply = "กดปุ่ม \"เช็คคิว\" แล้วกรอกเบอร์โทรที่ใช้จองได้เลยค่ะ"
        self.llm_calls = 0

        async def fake_stream(history, message, blocks=None, **kw):
            self.llm_calls += 1
            yield {"type": "delta", "content": self.reply}
            yield {"type": "done"}

        async def privacy(message):  # ด่าน 2 เคยตีความเบอร์โทรว่าเป็นการขอข้อมูลลูกค้าคนอื่น
            return judge.Verdict("PRIVACY")

        self.store = InMemoryConversationStore()
        for target, attr, value in [
            (llm_client, "chat_stream", fake_stream),
            (judge, "classify", privacy),
            (retriever, "retrieve", lambda history, message: asyncio.sleep(0, [])),
            (assistant, "store", self.store),
            (input_rules, "rate_limiter", input_rules.RateLimiter()),
        ]:
            p = patch.object(target, attr, value)
            p.start()
            self.addCleanup(p.stop)

    def events(self, message, **kw):
        async def collect():
            return [e async for e in assistant.respond_stream("s", message, **kw)]
        return run(collect())

    def test_phone_number_gets_check_button_not_privacy_refusal(self):
        events = self.events("0800600370")
        self.assertFalse(any("blocked" in e for e in events))
        text = "".join(e.get("delta", "") for e in events)
        self.assertIn("เช็คคิว", text)
        self.assertIn({"actions": ["check"]}, events)
        self.assertEqual(self.llm_calls, 0)
        self.assertEqual(run(self.store.get_history("s")), [])  # ไม่เก็บเบอร์ลงประวัติแชท

    def test_line_gets_link(self):
        reply = run(assistant.respond("s", "HH-1004-01", channel="line"))
        self.assertIn("/check", reply.text)

    def test_normal_answer_ends_with_suggested_buttons(self):
        with patch.object(judge, "classify", lambda m: asyncio.sleep(0, judge.Verdict("SAFE"))):
            events = self.events("ร้านยืนยันคิวให้หรือยังคะ")
        self.assertEqual(self.llm_calls, 1)
        self.assertIn({"actions": ["check"]}, events)
        self.assertEqual(events[-1], {"done": True})


if __name__ == "__main__":
    unittest.main()
