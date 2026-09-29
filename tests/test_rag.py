"""เทส RAG แบบไม่ต้องใช้ API key — embedding ถูกจำลอง (mock) ทั้งหมด"""

import asyncio
import json
import unittest
from unittest.mock import patch

from config import settings
from rag import embedder, retriever
from rag.chunker import build_chunks, chunks_hash
from shop import pricing


def run(coro):
    return asyncio.run(coro)


class ChunkerTests(unittest.TestCase):
    def test_every_catalog_item_is_retrievable(self):
        text = "\n".join(c.text for c in build_chunks())
        c = pricing.load_catalog()
        for section in ("services", "addons", "delivery", "packages", "products"):
            for item in c[section]:
                self.assertIn(item["name"], text, item["id"])

    def test_all_prices_of_a_service_stay_in_one_chunk(self):
        bath = next(c for c in build_chunks() if c.id == "service:bath")
        for price in ("250 บาท", "350 บาท", "500 บาท", "300 บาท"):
            self.assertIn(price, bath.text)

    def test_every_faq_and_policy_section_is_a_chunk(self):
        ids = {c.id for c in build_chunks()}
        self.assertTrue({f"faq:{i}" for i in range(1, 11)} <= ids)
        self.assertIn("policy:1", ids)

    def test_committed_index_matches_current_shop_data(self):
        # ถ้าเทสนี้ล้ม แปลว่าแก้ shop/ แล้วลืมรัน `python -m rag.build_index`
        index = json.loads(retriever.INDEX_PATH.read_text(encoding="utf-8"))
        self.assertEqual(index["hash"], chunks_hash(build_chunks()))
        self.assertEqual(len(index["vectors"]), len(build_chunks()))


class LexicalSearchTests(unittest.TestCase):
    def setUp(self):
        self.r = retriever.Retriever(build_chunks(), None)

    def top_ids(self, q, k=4):
        return [h.chunk.id for h in run(self.r.search(q, k))]

    def test_finds_specific_service(self):
        self.assertEqual(self.top_ids("มีบีบต่อมกลิ่นไหม")[0], "service:anal_gland")
        self.assertIn("service:nail", self.top_ids("ตัดเล็บอย่างเดียวได้ไหม"))

    def test_finds_policy_faq(self):
        self.assertIn("faq:9", self.top_ids("ยกเลิกนัดกะทันหันเสียเงินไหม"))

    def test_follow_up_question_uses_previous_turn(self):
        history = [{"role": "user", "content": "มีบริการรับ-ส่งถึงบ้านไหม"},
                   {"role": "assistant", "content": "มีค่ะ"}]
        q = retriever.build_query(history, "แล้วไกลกี่กิโลได้")
        self.assertIn("delivery", [h.chunk.id for h in run(self.r.search(q))])


class HybridAndFallbackTests(unittest.TestCase):
    def setUp(self):
        self.chunks = build_chunks()
        # vector ปลอม: chunk ที่ i ชี้ไปมิติที่ i — คำถามจะ "ตรงความหมาย" กับ products เท่านั้น
        n = len(self.chunks)
        self.vectors = [[1.0 if j == i else 0.0 for j in range(n)] for i in range(n)]
        self.target = next(i for i, c in enumerate(self.chunks) if c.id == "products")

    def test_semantic_score_can_rank_a_chunk_without_word_overlap(self):
        qvec = [1.0 if j == self.target else 0.0 for j in range(len(self.chunks))]

        async def fake_embed(texts):
            return [qvec]

        r = retriever.Retriever(self.chunks, self.vectors)
        with patch.object(embedder, "embed", fake_embed):
            hits = run(r.search("ของฝากกลับบ้าน"))
        self.assertEqual(hits[0].chunk.id, "products")

    def test_embedding_failure_falls_back_to_lexical(self):
        async def broken_embed(texts):
            raise embedder.EmbeddingError("down")

        r = retriever.Retriever(self.chunks, self.vectors)
        with patch.object(embedder, "embed", broken_embed):
            hits = run(r.search("มีบีบต่อมกลิ่นไหม"))
        self.assertEqual(hits[0].chunk.id, "service:anal_gland")

    def test_stale_or_mismatched_index_is_not_used(self):
        with patch.object(settings, "VISION_BASE_URL", "http://x"), \
             patch.object(settings, "VISION_API_KEY", "k"):
            self.assertIsNotNone(retriever._load_vectors(self.chunks))
            changed = self.chunks[:-1]  # จำลองว่าข้อมูลร้านเปลี่ยน
            self.assertIsNone(retriever._load_vectors(changed))
            with patch.object(settings, "EMBED_DIMENSIONS", 3072):
                self.assertIsNone(retriever._load_vectors(self.chunks))

    def test_no_embedding_config_means_lexical_only(self):
        with patch.object(settings, "VISION_BASE_URL", None), \
             patch.object(settings, "EMBED_BASE_URL", None):
            self.assertIsNone(retriever._load_vectors(self.chunks))


if __name__ == "__main__":
    unittest.main()
