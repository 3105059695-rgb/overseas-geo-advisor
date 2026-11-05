"""Offline vector correctness tests; real model smoke is explicitly opt-in.

GEO_VECTOR_MODEL_DIR=<existing model directory> python -m unittest discover -s tests -p test_geo_vectors.py
No test installs dependencies or downloads weights.
"""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import geo_vectors as gv

HAS_NUMPY = importlib.util.find_spec("numpy") is not None


class FixtureEncoder:
    metadata = {"model_id": "explicit-unit-test-vectors", "dimensions": 3}
    truncated_count = 0
    dependencies = {}

    def encode(self, texts, *, query=False):
        import numpy as np
        if query:
            return np.asarray([[1., 0., 0.] for _ in texts], dtype=np.float32)
        return np.asarray([[1., 0., 0.] if "robots" in text else [0., 1., 0.] for text in texts], dtype=np.float32)


def write_records(path, records):
    path.write_text("\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n", encoding="utf-8")


def record(name, text, **kwargs):
    return {"document_id": name, "source_version": "source-sha256-immutable", "work_id": name,
            "chunk_id": name + "-chunk", "line_start": 11, "line_end": 21, "text": text,
            "title": "来源原文", "content_role": "body", "section_path": ["研究条件"],
            "metadata": {"original_url": "https://example.org/" + name, "review_status": "unreviewed",
                         "allowed_uses": ["reading_lead"]}, **kwargs}


@unittest.skipUnless(HAS_NUMPY, "optional numpy is absent")
class VectorIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "chunks.jsonl"
        self.index = self.root / "index"
        self.encoder = FixtureEncoder()
        write_records(self.source, [record("irrelevant", "南瓜炒熟"), record("relevant", "robots.txt blocks crawlers")])
        self.manifest = gv.build_index(self.index, chunks_jsonl=self.source, encoder=self.encoder)

    def test_rank_and_provenance_are_preserved_offline(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")):
            hits = gv.VectorRetriever(self.index, encoder=self.encoder).search("why cannot robots access", limit=1)
        self.assertEqual(len(hits), 1)
        hit = hits[0]
        self.assertEqual(hit["document_id"], "relevant")
        self.assertAlmostEqual(hit["score"], 1.0)
        self.assertEqual((hit["line_start"], hit["line_end"]), (11, 21))
        self.assertEqual(hit["source_version"], "source-sha256-immutable")
        self.assertEqual(hit["metadata"]["review_status"], "unreviewed")
        self.assertEqual(hit["original_url"], "https://example.org/relevant")
        self.assertEqual(hit["index_model"], self.encoder.metadata)
        self.assertNotIn("text", hit)

    def test_blank_query_and_bounds(self):
        retriever = gv.VectorRetriever(self.index, encoder=self.encoder)
        self.assertEqual(retriever.search(" "), [])
        self.assertEqual(retriever.search("query", 0), [])
        with self.assertRaises(ValueError):
            retriever.search("x" * 16001)

    def test_rebuild_reuses_verified_identical_index(self):
        with patch.object(self.encoder, "encode", side_effect=AssertionError("must reuse")):
            manifest = gv.build_index(self.index, chunks_jsonl=self.source, encoder=self.encoder)
        self.assertTrue(manifest["reused"])
        self.assertEqual(manifest["fingerprint"], self.manifest["fingerprint"])

    def test_index_rejects_model_mismatch(self):
        other = FixtureEncoder()
        other.metadata = {"model_id": "another-model", "dimensions": 3}
        with self.assertRaisesRegex(ValueError, "different encoder"):
            gv.VectorRetriever(self.index, encoder=other)

    def test_index_rejects_tampered_provenance(self):
        (self.index / self.manifest["records_file"]).write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "integrity"):
            gv.VectorRetriever(self.index, encoder=self.encoder)

    def test_index_rejects_path_escape(self):
        manifest = dict(self.manifest, vectors_file="../outside.npy")
        (self.index / "index.json").write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "escapes"):
            gv.VectorRetriever(self.index, encoder=self.encoder)

    def test_source_range_validation(self):
        write_records(self.source, [record("bad", "some text", line_start=22, line_end=21)])
        with self.assertRaisesRegex(ValueError, "line range"):
            gv.build_index(self.root / "bad-index", chunks_jsonl=self.source, encoder=self.encoder)

    def test_heading_only_candidates_are_not_evidence(self):
        write_records(self.source, [record("heading", "robots", metadata={"block_kind": "heading"}),
                                    record("body", "robots body")])
        gv.build_index(self.root / "headings", chunks_jsonl=self.source, encoder=self.encoder)
        hits = gv.VectorRetriever(self.root / "headings", encoder=self.encoder).search("query")
        self.assertEqual([hit["document_id"] for hit in hits], ["body"])

    def test_jsonl_unicode_separators_do_not_split_source_records(self):
        text = "正文\u2028还有同一条JSON记录\u0085robots"
        write_records(self.source, [record("unicode", text)])
        self.assertEqual(gv._records(self.source, None)[0]["text"], text)

    def test_multiple_windows_return_best_window_once_per_chunk(self):
        encoder = FixtureEncoder()
        encoder.split_text = lambda text: [{"text": "pumpkin", "char_start": 0, "char_end": 4},
                                           {"text": "robots", "char_start": 3, "char_end": len(text)}]
        manifest = gv.build_index(self.root / "windows", chunks_jsonl=self.source, encoder=encoder)
        self.assertEqual(manifest["count"], 4)
        self.assertEqual(manifest["source_chunk_count"], 2)
        hits = gv.VectorRetriever(self.root / "windows", encoder=encoder).search("query", 10)
        self.assertEqual(len(hits), 2)
        self.assertTrue(all(hit["vector_window"]["index"] == 1 for hit in hits))


@unittest.skipUnless(os.environ.get("GEO_VECTOR_MODEL_DIR"), "real encoder requires existing GEO_VECTOR_MODEL_DIR")
class RealEmbeddingSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.encoder = gv.LocalEncoder(Path(os.environ["GEO_VECTOR_MODEL_DIR"]))

    def test_chinese_paraphrase_beats_unrelated_passages_without_network(self):
        import numpy as np
        with patch("urllib.request.urlopen", side_effect=AssertionError("offline inference only")):
            passages = self.encoder.encode([
                "服务器通过robots.txt拒绝搜索机器人的访问，可能导致网页无法被抓取和展示。",
                "内容中引用权威研究、统计数据和专家观点，能够增强信息可信度。",
                "烹饪南瓜时先去皮切丝，然后下锅加盐炒熟。",
            ])
            query = self.encoder.encode(["为什么自动检索程序进不了我的网站？"], query=True)
        scores = (query @ passages.T)[0]
        self.assertEqual(int(scores.argmax()), 0)
        self.assertGreater(float(scores[0] - scores[2]), 0.03)
        self.assertTrue(np.allclose(np.linalg.norm(passages, axis=1), 1, atol=1e-5))

    def test_long_unicode_passage_windows_cover_tail_and_overlap(self):
        text = "研究发现网站的引用依赖搜索引擎的抓取与索引。" * 100 + "尾部不可遗失。"
        windows = self.encoder.split_text(text)
        self.assertGreater(len(windows), 1)
        self.assertEqual(windows[0]["char_start"], 0)
        self.assertEqual(windows[-1]["char_end"], len(text))
        self.assertTrue(windows[-1]["text"].endswith("尾部不可遗失。"))
        for previous, current in zip(windows, windows[1:]):
            self.assertLess(current["char_start"], previous["char_end"])
            self.assertEqual(current["text"], text[current["char_start"]:current["char_end"]])


if __name__ == "__main__":
    unittest.main()
