import tempfile
import unittest
from pathlib import Path

from bot.relation_cache import RelationCache


class TestRelationCache(unittest.TestCase):
    def test_cache_persists_and_prompt_version_invalidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "relation_cache.db"
            cache = RelationCache(db_path)
            cache.put(
                pair_key="pair-1",
                prompt_version="v1",
                response={
                    "label": "A_implies_B",
                    "confidence": 0.83,
                    "ambiguous": False,
                    "short_rationale": "A is a stricter event than B.",
                    "needs_human_review": False,
                },
                source="stub-haiku",
                metadata={"latency_ms": 12.3},
            )
            cache.record_event(
                pair_key="pair-1",
                prompt_version="v1",
                model="stub-haiku",
                cache_hit=False,
                input_tokens=120,
                output_tokens=20,
                estimated_cost_usd=0.0012,
                latency_ms=12.3,
            )

            reloaded = RelationCache(db_path)
            cached = reloaded.get("pair-1", "v1")
            self.assertIsNotNone(cached)
            assert cached is not None
            self.assertEqual(cached.response["label"], "A_implies_B")
            self.assertEqual(cached.metadata["latency_ms"], 12.3)
            self.assertIsNone(reloaded.get("pair-1", "v2"))

            reloaded.record_event(
                pair_key="pair-1",
                prompt_version="v1",
                model="stub-haiku",
                cache_hit=True,
            )
            stats = reloaded.stats()
            self.assertEqual(stats.entries, 1)
            self.assertEqual(stats.cache_hits, 1)
            self.assertEqual(stats.cache_misses, 1)
            self.assertEqual(stats.input_tokens, 120)
            self.assertEqual(stats.output_tokens, 20)
            self.assertAlmostEqual(stats.estimated_cost_usd, 0.0012, places=6)


if __name__ == "__main__":
    unittest.main()
