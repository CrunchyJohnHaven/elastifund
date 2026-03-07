import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bot.constraint_arb_engine import CandidateGenerator
from bot.resolution_normalizer import normalize_market


class TestConstraintPrefilter(unittest.TestCase):
    def _mk_market(
        self,
        *,
        market_id: str,
        event_id: str,
        question: str,
        outcome: str = "Yes",
        outcomes: list[str] | None = None,
        source: str = "Associated Press",
        end_date: str = "2028-11-05T23:59:00Z",
        rules: str | None = None,
    ) -> dict:
        return {
            "market_id": market_id,
            "event_id": event_id,
            "question": question,
            "outcome": outcome,
            "outcomes": outcomes or ["Yes", "No"],
            "category": "politics",
            "resolutionSource": source,
            "endDate": end_date,
            "rules": rules or f"Resolves using {source} at {end_date}.",
        }

    def test_prefilter_promotes_threshold_pair_and_reduces_pair_count(self) -> None:
        generator = CandidateGenerator()
        markets = [
            normalize_market(
                self._mk_market(
                    market_id="cpi-4",
                    event_id="cpi-over-4-june-2026",
                    question="Will CPI be above 4.0 by June 2026?",
                    source="Bureau of Labor Statistics",
                    end_date="2026-06-30T23:59:00Z",
                )
            ),
            normalize_market(
                self._mk_market(
                    market_id="cpi-3",
                    event_id="cpi-over-3-june-2026",
                    question="Will CPI be above 3.0 by June 2026?",
                    source="Bureau of Labor Statistics",
                    end_date="2026-06-30T23:59:00Z",
                )
            ),
            normalize_market(
                self._mk_market(
                    market_id="btc",
                    event_id="btc-over-120k-july-2026",
                    question="Will Bitcoin close above $120k in July 2026?",
                    source="Coinbase",
                    end_date="2026-07-31T23:59:00Z",
                )
            ),
            normalize_market(
                self._mk_market(
                    market_id="madrid",
                    event_id="real-madrid-win-ucl-2026",
                    question="Will Real Madrid win the Champions League in 2026?",
                    source="Associated Press",
                    end_date="2026-05-31T23:59:00Z",
                )
            ),
        ]

        candidates = generator.generate_candidates(markets, max_pairs=20, include_rejected=True)
        naive_pairs = 6
        self.assertLess(generator.last_stats["passed_pairs"], naive_pairs)

        threshold_pair = next(pair for pair in candidates if pair.pair_key == ("cpi-3", "cpi-4"))
        self.assertTrue(threshold_pair.passed)
        self.assertEqual(threshold_pair.sample_bucket, "implication_candidate")
        self.assertEqual(threshold_pair.suggested_label, "B_implies_A")
        self.assertIn("higher_threshold_implies_lower", threshold_pair.reason_codes)

    def test_prefilter_emits_office_and_same_event_buckets(self) -> None:
        generator = CandidateGenerator()
        markets = [
            normalize_market(
                self._mk_market(
                    market_id="trump",
                    event_id="trump-president-2028",
                    question="Will Trump win the 2028 presidential election?",
                    end_date="2028-11-05T23:59:00Z",
                )
            ),
            normalize_market(
                self._mk_market(
                    market_id="gop",
                    event_id="gop-president-2028",
                    question="Will a Republican win the 2028 presidential election?",
                    end_date="2028-11-05T23:59:00Z",
                )
            ),
            normalize_market(
                self._mk_market(
                    market_id="alice",
                    event_id="mayor-race-2028",
                    question="Who will win the 2028 mayor race?",
                    outcome="Alice",
                    outcomes=["Alice", "Bob", "Carol"],
                    end_date="2028-11-05T23:59:00Z",
                )
            ),
            normalize_market(
                self._mk_market(
                    market_id="bob",
                    event_id="mayor-race-2028",
                    question="Who will win the 2028 mayor race?",
                    outcome="Bob",
                    outcomes=["Alice", "Bob", "Carol"],
                    end_date="2028-11-05T23:59:00Z",
                )
            ),
        ]

        candidates = generator.generate_candidates(markets, max_pairs=20, include_rejected=True)
        office_pair = next(pair for pair in candidates if pair.pair_key == ("gop", "trump"))
        self.assertTrue(office_pair.passed)
        self.assertEqual(office_pair.sample_bucket, "office_hierarchy_candidate")
        self.assertIn("shared_office_scope", office_pair.reason_codes)
        self.assertIn("party_candidate_hierarchy", office_pair.reason_codes)

        same_event_pair = next(pair for pair in candidates if pair.pair_key == ("alice", "bob"))
        self.assertTrue(same_event_pair.passed)
        self.assertEqual(same_event_pair.sample_bucket, "same_event_cluster")
        self.assertEqual(same_event_pair.suggested_label, "mutually_exclusive")

    def test_builder_cli_writes_pair_and_triplet_scaffold(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "build_constraint_gold_set.py"

        fixture_rows = [
            self._mk_market(
                market_id="cpi-4",
                event_id="cpi-over-4-june-2026",
                question="Will CPI be above 4.0 by June 2026?",
                source="Bureau of Labor Statistics",
                end_date="2026-06-30T23:59:00Z",
            ),
            self._mk_market(
                market_id="cpi-3",
                event_id="cpi-over-3-june-2026",
                question="Will CPI be above 3.0 by June 2026?",
                source="Bureau of Labor Statistics",
                end_date="2026-06-30T23:59:00Z",
            ),
            self._mk_market(
                market_id="trump",
                event_id="trump-president-2028",
                question="Will Trump win the 2028 presidential election?",
                end_date="2028-11-05T23:59:00Z",
            ),
            self._mk_market(
                market_id="gop",
                event_id="gop-president-2028",
                question="Will a Republican win the 2028 presidential election?",
                end_date="2028-11-05T23:59:00Z",
            ),
            self._mk_market(
                market_id="alice",
                event_id="mayor-race-2028",
                question="Who will win the 2028 mayor race?",
                outcome="Alice",
                outcomes=["Alice", "Bob", "Carol"],
                end_date="2028-11-05T23:59:00Z",
            ),
            self._mk_market(
                market_id="bob",
                event_id="mayor-race-2028",
                question="Who will win the 2028 mayor race?",
                outcome="Bob",
                outcomes=["Alice", "Bob", "Carol"],
                end_date="2028-11-05T23:59:00Z",
            ),
            self._mk_market(
                market_id="carol",
                event_id="mayor-race-2028",
                question="Who will win the 2028 mayor race?",
                outcome="Carol",
                outcomes=["Alice", "Bob", "Carol"],
                end_date="2028-11-05T23:59:00Z",
            ),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "markets.jsonl"
            output_path = Path(tmp) / "constraint_gold_set.jsonl"
            report_path = Path(tmp) / "constraint_gold_set_sampling.md"
            input_path.write_text(
                "\n".join(json.dumps(row, sort_keys=True) for row in fixture_rows) + "\n",
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(script_path),
                    "--input-jsonl",
                    str(input_path),
                    "--pair-count",
                    "4",
                    "--triple-count",
                    "1",
                    "--candidate-cap",
                    "20",
                    "--seed",
                    "7",
                    "--output",
                    str(output_path),
                    "--report",
                    str(report_path),
                ],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn("Wrote 4 pairs and 1 triples", completed.stdout)
            rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(rows), 5)
            self.assertEqual(sum(1 for row in rows if row["sample_type"] == "pair"), 4)
            self.assertEqual(sum(1 for row in rows if row["sample_type"] == "triple"), 1)
            self.assertIn("Candidate reduction vs naive", report_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
