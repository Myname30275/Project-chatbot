import unittest

from chatbot import llm_client, prompt_builder
from shop import pricing


class CatalogTests(unittest.TestCase):
    def test_knowledge_base_meets_project_minimum(self):
        # โจทย์: รายการสินค้า/บริการอย่างน้อย 15 รายการ
        c = pricing.load_catalog()
        items = c["services"] + c["addons"] + c["delivery"] + c["products"]
        self.assertGreaterEqual(len(items), 15)

    def test_ids_are_unique(self):
        c = pricing.load_catalog()
        ids = [i["id"] for s in ("services", "addons", "delivery", "products", "packages") for i in c[s]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_size_priced_services_cover_every_size(self):
        for s in pricing.load_catalog()["services"]:
            if "prices" in s:
                self.assertEqual(set(s["prices"]), set(pricing.SIZES), s["id"])


class QuoteTests(unittest.TestCase):
    def test_sized_service(self):
        q = pricing.quote("bath", "small")
        self.assertEqual((q.min, q.max), (250, 250))

    def test_addon_range_is_carried_into_total(self):
        q = pricing.quote("full_groom", "medium", ("dematting", "spa"))
        self.assertEqual((q.min, q.max), (550 + 150 + 200, 550 + 300 + 200))
        self.assertIn("รวมประมาณ 900 บาท–1,050 บาท", q.text())

    def test_flat_price_service_ignores_size(self):
        self.assertEqual(pricing.quote("nail").min, 100)

    def test_invalid_input_raises_instead_of_guessing(self):
        with self.assertRaises(ValueError):
            pricing.quote("bath")  # ไม่บอกขนาด
        with self.assertRaises(ValueError):
            pricing.quote("hotel_overnight", "small")
        with self.assertRaises(ValueError):
            pricing.quote("bath", "small", ("free_discount",))


class PromptTests(unittest.TestCase):
    def test_system_prompt_has_rules_and_core_info_but_not_prices(self):
        p = prompt_builder.system_prompt()
        shop = pricing.load_catalog()["shop"]
        self.assertNotIn("{{", p)
        for must_have in (shop["name"], shop["assistant_name"], shop["hours"], "ฝากเลี้ยงค้างคืน",
                          "ห้ามให้", prompt_builder.fallback_message()):
            self.assertIn(must_have, p)
        # ราคา/นโยบาย/FAQ ต้องมาจาก RAG ไม่ใช่ฝังใน system prompt
        self.assertNotIn("อาบน้ำ + เป่าขน", p)

    def test_render_rejects_missing_placeholder(self):
        with self.assertRaises(KeyError):
            prompt_builder.render("{{A}} {{B}}", {"A": "x"})

    def test_payload_order_prompt_then_knowledge_then_voice_hint(self):
        payload = llm_client._build_payload(
            [], "ราคาอาบน้ำ", stream=False,
            extra_system=prompt_builder.voice_hint(), knowledge="[1] อาบน้ำ\n- 250 บาท",
        )
        msgs = payload["messages"]
        self.assertEqual(msgs[0], {"role": "system", "content": prompt_builder.system_prompt()})
        self.assertIn("[1] อาบน้ำ", msgs[1]["content"])
        self.assertEqual(msgs[2]["content"], prompt_builder.voice_hint())
        self.assertEqual(msgs[-1], {"role": "user", "content": "ราคาอาบน้ำ"})

    def test_payload_says_so_when_nothing_was_retrieved(self):
        msgs = llm_client._build_payload([], "มีที่จอดรถไหม", stream=False)["messages"]
        self.assertIn("ไม่พบข้อมูล", msgs[1]["content"])


if __name__ == "__main__":
    unittest.main()
