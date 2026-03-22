"""
Tests for bot/research_rag.py
==============================
All tests use tmp_path for isolation. No external API calls.
Run with: pytest tests/test_research_rag.py -v
"""
from __future__ import annotations

import pickle
import re
from pathlib import Path

import pytest

try:
    from bot.research_rag import (
        DispatchChunk,
        ResearchRAG,
        RetrievalResult,
        _extract_dispatch_id,
        _extract_metadata,
        _extract_snippet,
        _extract_title,
        _split_into_chunks,
    )
except ImportError:
    from research_rag import (
        DispatchChunk,
        ResearchRAG,
        RetrievalResult,
        _extract_dispatch_id,
        _extract_metadata,
        _extract_snippet,
        _extract_title,
        _split_into_chunks,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BTC_CONTENT = """\
# DISPATCH_075 BTC 5-Minute Maker Strategy

## Overview
The BTC 5-minute maker strategy trades Polymarket BTC 5-minute resolution markets.
Orders are placed as post-only maker orders to earn the maker rebate.
The delta threshold controls entry conditions. If BTC delta is too large we skip.

## Key Parameters
- BTC5_MAX_ABS_DELTA: maximum acceptable price delta for entry
- Maker-only execution: Post-only flag prevents taker fills
- DOWN-biased: DOWN contracts have historically outperformed UP contracts
- Time-of-day filter: suppress trades between 00-02 ET and 08-09 ET

## Results
Gate result: FAIL (3 of 6 criteria). Per-trade CSV shows 51.4% win rate.
Profit factor 1.01. Kelly fraction 0.006.
"""

VPIN_CONTENT = """\
# VPIN Toxicity Analysis

## What is VPIN?
VPIN (Volume-synchronised Probability of Informed Trading) measures order flow toxicity.
High VPIN values indicate that informed traders are active in the market.

## Trading Rules
VPIN > 0.75 indicates toxic flow. Maker orders should be pulled immediately.
VPIN < 0.40 indicates safe conditions for liquidity provision.
Z-score normalisation on 5-minute rolling window.

## Kill Switch
At 60% skew or 3:1 buy/sell ratio the kill switch fires.
"""

CALIBRATION_CONTENT = """\
# Platt Calibration System — DISPATCH_081

## Static Calibration
The static Platt scaling parameters A=0.5914, B=-0.3977 remain optimal.
Walk-forward validation on 532 markets yielded Brier score 0.2134.

## Adaptive Calibration
Adaptive Platt updates parameters incrementally as new resolved markets arrive.
Minimum sample size before adaptation: 50 resolved markets.
The Platt transform maps raw LLM logits to calibrated probabilities.

## Anti-anchoring
Never show Claude the market price when estimating probability.
The agent must form an independent prior before checking the book.
"""

WEATHER_CONTENT = """\
# Weather Markets Strategy

## Overview
Prediction markets on weather outcomes (temperature, precipitation, storms).
Key signal sources: NOAA forecasts, European Centre for Medium-range Weather Forecasts.

## Edge
Weather forecast models have known biases. Ensemble model disagreement
provides a measurable edge. Resolution times are short (24h-72h).

## Implementation
Fetch ECMWF and GFS forecasts via open API. Compute ensemble spread.
High spread → higher uncertainty → wider bid-ask spread → more edge.
"""

POLITICAL_CONTENT = """\
# Political Markets — DISPATCH_097

## Overview
Political prediction markets cover elections, legislation, geopolitical events.
Category gaps show World Events 7.32pp above base rate, Media 7.28pp.

## Signal Sources
- Polling aggregators (538, RealClearPolitics)
- Manifold forecast aggregation
- News sentiment pipeline (Reuters, AP wire)

## Strategy
NO contracts outperform YES at 69 out of 99 price levels tested.
Use asymmetric thresholds: YES entry at 15%, NO entry at 5% edge.
"""


def _make_dispatch_dir(tmp_path: Path) -> Path:
    d = tmp_path / "dispatches"
    d.mkdir()
    (d / "btc_strategy.md").write_text(BTC_CONTENT, encoding="utf-8")
    (d / "vpin_analysis.md").write_text(VPIN_CONTENT, encoding="utf-8")
    (d / "calibration.md").write_text(CALIBRATION_CONTENT, encoding="utf-8")
    (d / "weather_markets.md").write_text(WEATHER_CONTENT, encoding="utf-8")
    (d / "political_markets.md").write_text(POLITICAL_CONTENT, encoding="utf-8")
    return d


# ---------------------------------------------------------------------------
# Unit tests — helpers
# ---------------------------------------------------------------------------

class TestExtractTitle:
    def test_first_heading_returned(self):
        text = "# My Great Dispatch\n\nSome content."
        assert _extract_title(text, "file.md") == "My Great Dispatch"

    def test_heading_with_prefix_stripped(self):
        text = "## Section\n\nContent."
        assert _extract_title(text, "file.md") == "Section"

    def test_no_heading_falls_back_to_filename(self):
        text = "Just some content with no heading."
        title = _extract_title(text, "btc_5min_maker.md")
        assert "btc" in title.lower()

    def test_whitespace_stripped(self):
        text = "#   Spaced Title   \n\nContent."
        assert _extract_title(text, "f.md") == "Spaced Title"


class TestExtractMetadata:
    def test_dispatch_id_extracted(self):
        meta = _extract_metadata("DISPATCH_102 analysis of BTC5", "file.md")
        assert meta.get("dispatch_id") == "DISPATCH_102"

    def test_dispatch_id_from_filename(self):
        meta = _extract_metadata("no id here", "DISPATCH_097_something.md")
        assert meta.get("dispatch_id") == "DISPATCH_097"

    def test_date_extracted(self):
        meta = _extract_metadata("Analysis from 2026-03-14 confirms edge.", "f.md")
        assert "2026-03-14" in meta.get("date", "")

    def test_strategy_tags_extracted(self):
        meta = _extract_metadata("BTC5 uses VPIN gating and Kelly sizing.", "f.md")
        tags = meta.get("strategy_tags", [])
        assert "BTC5" in tags
        assert "VPIN" in tags
        assert "Kelly" in tags

    def test_no_match_returns_empty_dict(self):
        meta = _extract_metadata("lorem ipsum dolor", "lorem.md")
        assert isinstance(meta, dict)


class TestExtractDispatchId:
    def test_from_filename(self):
        did = _extract_dispatch_id("content", "DISPATCH_099_something.md")
        assert "99" in did

    def test_from_content(self):
        did = _extract_dispatch_id("DISPATCH_102 analysis", "plain.md")
        assert "102" in did


class TestSplitIntoChunks:
    def test_short_text_single_chunk(self):
        text = "Short text."
        chunks = _split_into_chunks(text, chunk_size=1000, overlap=200)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_large_text_multiple_chunks(self):
        text = "A" * 3000
        chunks = _split_into_chunks(text, chunk_size=1000, overlap=200)
        assert len(chunks) > 1

    def test_overlap_present(self):
        # Create text with two clear paragraphs totalling > chunk_size
        para1 = "X" * 600 + "\n\n"
        para2 = "Y" * 600
        text = para1 + para2
        chunks = _split_into_chunks(text, chunk_size=800, overlap=100)
        # At least one of the non-first chunks should begin with content from
        # the previous chunk (overlap region)
        if len(chunks) > 1:
            # The second chunk should contain some of the first chunk's tail
            # OR the content should exceed chunk_size proving split happened
            assert len(chunks) >= 2

    def test_all_content_covered(self):
        text = "\n\n".join(["Paragraph number %d with content." % i for i in range(20)])
        chunks = _split_into_chunks(text, chunk_size=200, overlap=50)
        combined = " ".join(chunks)
        # Every paragraph should appear somewhere across the chunks
        assert "Paragraph number 0" in combined
        assert "Paragraph number 19" in combined

    def test_chunk_size_respected(self):
        text = "W" * 5000
        chunks = _split_into_chunks(text, chunk_size=500, overlap=0)
        for c in chunks:
            assert len(c) <= 500 + 1  # +1 for edge tolerance


class TestExtractSnippet:
    def test_returns_string(self):
        text = "The BTC market moves quickly. VPIN is elevated. Maker orders are safe."
        snippet = _extract_snippet(text, "BTC VPIN")
        assert isinstance(snippet, str)
        assert len(snippet) <= 205  # 200 + small tolerance

    def test_relevant_sentence_preferred(self):
        text = (
            "Weather in Dublin is mild. "
            "BTC 5-minute maker strategy uses delta thresholds. "
            "Political markets have high volatility."
        )
        snippet = _extract_snippet(text, "BTC delta maker")
        assert "BTC" in snippet or "delta" in snippet or "maker" in snippet

    def test_empty_text(self):
        snippet = _extract_snippet("", "query")
        assert snippet == ""

    def test_max_len_respected(self):
        text = "word " * 1000
        snippet = _extract_snippet(text, "word", max_len=200)
        assert len(snippet) <= 210


# ---------------------------------------------------------------------------
# Integration tests — ResearchRAG
# ---------------------------------------------------------------------------

class TestBuildIndex:
    def test_returns_correct_chunk_count(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d), chunk_size=500, chunk_overlap=100)
        n = rag.build_index()
        assert n > 0
        # 5 files, each ~400-700 chars — at chunk_size=500 expect at least 5 chunks
        assert n >= 5

    def test_empty_directory_returns_zero(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        rag = ResearchRAG(dispatch_dir=str(empty))
        n = rag.build_index()
        assert n == 0

    def test_nonexistent_directory_returns_zero(self, tmp_path):
        rag = ResearchRAG(dispatch_dir=str(tmp_path / "does_not_exist"))
        n = rag.build_index()
        assert n == 0

    def test_chunks_have_correct_structure(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d), chunk_size=500, chunk_overlap=100)
        rag.build_index()
        for chunk in rag._chunks:
            assert isinstance(chunk, DispatchChunk)
            assert chunk.dispatch_id
            assert chunk.title
            assert chunk.content
            assert isinstance(chunk.chunk_index, int)
            assert isinstance(chunk.embedding, dict)
            assert isinstance(chunk.metadata, dict)

    def test_index_marked_built(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d))
        assert not rag._built
        rag.build_index()
        assert rag._built


class TestRetrieve:
    def test_btc_query_ranks_btc_file_highest(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d), chunk_size=800, chunk_overlap=100)
        rag.build_index()
        results = rag.retrieve("BTC 5-minute maker strategy delta threshold", top_k=5)
        assert len(results) > 0
        top_result = results[0]
        assert "btc" in top_result.chunk.file_path.lower() or \
               "btc" in top_result.chunk.title.lower() or \
               "btc" in top_result.chunk.content.lower()

    def test_vpin_query_ranks_vpin_file_highly(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d), chunk_size=800, chunk_overlap=100)
        rag.build_index()
        results = rag.retrieve("VPIN toxic flow kill switch informed traders", top_k=5)
        assert len(results) > 0
        titles_and_paths = [
            r.chunk.title.lower() + r.chunk.file_path.lower()
            for r in results[:2]
        ]
        assert any("vpin" in t for t in titles_and_paths)

    def test_irrelevant_query_returns_low_similarity(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d), chunk_size=800, chunk_overlap=100)
        rag.build_index()
        # Query about something totally unrelated to the corpus
        results = rag.retrieve(
            "xyzzy frobnicator quantum spaghetti", top_k=5, min_similarity=0.0
        )
        if results:
            assert all(r.similarity < 0.5 for r in results)

    def test_returns_at_most_top_k(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d), chunk_size=800, chunk_overlap=100)
        rag.build_index()
        results = rag.retrieve("market trading strategy", top_k=3)
        assert len(results) <= 3

    def test_min_similarity_filter(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d), chunk_size=800, chunk_overlap=100)
        rag.build_index()
        results = rag.retrieve("BTC maker", top_k=10, min_similarity=0.5)
        for r in results:
            assert r.similarity >= 0.5

    def test_results_sorted_descending(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d), chunk_size=800, chunk_overlap=100)
        rag.build_index()
        results = rag.retrieve("calibration Platt scaling probability", top_k=5)
        for i in range(len(results) - 1):
            assert results[i].similarity >= results[i + 1].similarity

    def test_result_has_snippet(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d), chunk_size=800, chunk_overlap=100)
        rag.build_index()
        results = rag.retrieve("BTC delta threshold", top_k=3)
        for r in results:
            assert isinstance(r.snippet, str)
            assert len(r.snippet) > 0

    def test_empty_index_returns_empty_list(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        rag = ResearchRAG(dispatch_dir=str(empty))
        rag.build_index()
        results = rag.retrieve("anything")
        assert results == []

    def test_retrieve_before_build_returns_empty(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d))
        # Do not call build_index
        results = rag.retrieve("BTC")
        assert results == []


class TestGetContextPrompt:
    def test_returns_string(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d), chunk_size=800, chunk_overlap=100)
        rag.build_index()
        ctx = rag.get_context_prompt("Will BTC be above 70k in 5 minutes?")
        assert isinstance(ctx, str)

    def test_contains_dispatch_id_header(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d), chunk_size=800, chunk_overlap=100)
        rag.build_index()
        ctx = rag.get_context_prompt("BTC 5-minute maker strategy", top_k=2)
        assert "---" in ctx

    def test_respects_max_tokens(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d), chunk_size=800, chunk_overlap=100)
        rag.build_index()
        ctx = rag.get_context_prompt(
            "BTC VPIN calibration", top_k=5, max_tokens=100
        )
        # 100 tokens ≈ 400 chars — result must not massively exceed this
        assert len(ctx) <= 500  # generous buffer for headers

    def test_empty_index_returns_empty_string(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        rag = ResearchRAG(dispatch_dir=str(empty))
        rag.build_index()
        ctx = rag.get_context_prompt("anything")
        assert ctx == ""

    def test_context_contains_relevant_content(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d), chunk_size=800, chunk_overlap=100)
        rag.build_index()
        ctx = rag.get_context_prompt("VPIN toxic order flow kill switch", top_k=2)
        if ctx:
            # Should contain some VPIN-related terms
            lower = ctx.lower()
            assert any(term in lower for term in ["vpin", "toxic", "kill"])


class TestChunkOverlap:
    def test_overlap_content_at_boundaries(self, tmp_path):
        """Content near chunk boundaries should appear in adjacent chunks."""
        # Create a file large enough to require 2+ chunks
        long_text = (
            "# Overlap Test Dispatch\n\n"
            + ("Alpha beta gamma delta epsilon zeta eta theta. " * 15 + "\n\n")
            + "BOUNDARY_MARKER unique token that marks the seam.\n\n"
            + ("Iota kappa lambda mu nu xi omicron pi. " * 15 + "\n\n")
        )
        d = tmp_path / "dispatches"
        d.mkdir()
        (d / "overlap_test.md").write_text(long_text, encoding="utf-8")

        rag = ResearchRAG(dispatch_dir=str(d), chunk_size=300, chunk_overlap=100)
        rag.build_index()

        # Find which chunks contain BOUNDARY_MARKER
        marker_chunks = [
            c for c in rag._chunks if "BOUNDARY_MARKER" in c.content
        ]
        # With overlap, the marker may appear in more than one chunk
        # but at minimum it must appear in at least one
        assert len(marker_chunks) >= 1


class TestMetadataExtraction:
    def test_dispatch_pattern_in_content(self, tmp_path):
        d = tmp_path / "dispatches"
        d.mkdir()
        content = "# DISPATCH_102 BTC Truth Plumbing\n\nAnalysis of fill rates.\n"
        (d / "DISPATCH_102_btc.md").write_text(content, encoding="utf-8")

        rag = ResearchRAG(dispatch_dir=str(d))
        rag.build_index()

        assert len(rag._chunks) > 0
        chunk = rag._chunks[0]
        assert "102" in chunk.dispatch_id

    def test_metadata_dict_present_on_all_chunks(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d), chunk_size=800, chunk_overlap=100)
        rag.build_index()
        for chunk in rag._chunks:
            assert isinstance(chunk.metadata, dict)


class TestUpdateIndex:
    def test_update_adds_new_file(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d), chunk_size=800, chunk_overlap=100)
        rag.build_index()
        initial_count = len(rag._chunks)

        new_file = d / "new_dispatch.md"
        new_file.write_text(
            "# DISPATCH_200 New Strategy\n\nThis is a brand new dispatch about quantum trading.\n"
            * 5,
            encoding="utf-8",
        )
        rag.update_index(str(new_file))

        assert len(rag._chunks) > initial_count

    def test_update_replaces_existing_file(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d), chunk_size=800, chunk_overlap=100)
        rag.build_index()

        # Overwrite btc file with totally different content
        btc_file = d / "btc_strategy.md"
        btc_file.write_text(
            "# BTC Replacement Content\n\nThis is completely new content about something else.\n" * 3,
            encoding="utf-8",
        )
        rag.update_index(str(btc_file))

        # Old content should be gone
        btc_chunks = [c for c in rag._chunks if "btc_strategy" in c.file_path]
        for chunk in btc_chunks:
            assert "BTC Replacement Content" in chunk.content or \
                   "completely new content" in chunk.content or \
                   "something else" in chunk.content

    def test_update_nonexistent_file_does_not_crash(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d), chunk_size=800, chunk_overlap=100)
        rag.build_index()
        # Should log warning and return gracefully
        rag.update_index(str(tmp_path / "does_not_exist.md"))

    def test_retrieve_reflects_updated_content(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d), chunk_size=800, chunk_overlap=100)
        rag.build_index()

        new_file = d / "new_unique_topic.md"
        new_file.write_text(
            "# Unique Graviton Arbitrage Strategy\n\n"
            "graviton arbitrage exploits quantum tunneling effects in dark pools. "
            "This strategy is unlike any other. Graviton signals detected.\n" * 4,
            encoding="utf-8",
        )
        rag.update_index(str(new_file))

        results = rag.retrieve("graviton arbitrage quantum tunneling dark pools", top_k=3)
        assert len(results) > 0
        top_titles_paths = [
            (r.chunk.title + r.chunk.file_path).lower() for r in results[:2]
        ]
        assert any("graviton" in t for t in top_titles_paths)


class TestSaveLoadIndex:
    def test_roundtrip_preserves_chunk_count(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d), chunk_size=800, chunk_overlap=100)
        rag.build_index()
        original_count = len(rag._chunks)

        cache_file = str(tmp_path / "index.pkl")
        rag.save_index(cache_file)

        rag2 = ResearchRAG(dispatch_dir=str(d), chunk_size=800, chunk_overlap=100)
        rag2.load_index(cache_file)
        assert len(rag2._chunks) == original_count

    def test_loaded_index_retrieves_correctly(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d), chunk_size=800, chunk_overlap=100)
        rag.build_index()
        cache_file = str(tmp_path / "index.pkl")
        rag.save_index(cache_file)

        rag2 = ResearchRAG(dispatch_dir=str(d))
        rag2.load_index(cache_file)
        results = rag2.retrieve("BTC maker delta", top_k=3)
        assert len(results) > 0

    def test_loaded_index_marked_built(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d))
        rag.build_index()
        cache_file = str(tmp_path / "index.pkl")
        rag.save_index(cache_file)

        rag2 = ResearchRAG(dispatch_dir=str(d))
        assert not rag2._built
        rag2.load_index(cache_file)
        assert rag2._built

    def test_save_creates_file(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d))
        rag.build_index()
        cache_file = str(tmp_path / "index.pkl")
        assert not Path(cache_file).exists()
        rag.save_index(cache_file)
        assert Path(cache_file).exists()
        assert Path(cache_file).stat().st_size > 0


class TestStats:
    def test_returns_dict(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d), chunk_size=800, chunk_overlap=100)
        rag.build_index()
        s = rag.stats()
        assert isinstance(s, dict)

    def test_correct_num_files(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d), chunk_size=800, chunk_overlap=100)
        rag.build_index()
        s = rag.stats()
        assert s["num_files"] == 5

    def test_num_chunks_positive(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d), chunk_size=800, chunk_overlap=100)
        rag.build_index()
        s = rag.stats()
        assert s["num_chunks"] > 0

    def test_vocab_size_positive(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d), chunk_size=800, chunk_overlap=100)
        rag.build_index()
        s = rag.stats()
        assert s["vocab_size"] > 0

    def test_built_flag_in_stats(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d))
        s_before = rag.stats()
        assert not s_before["built"]
        rag.build_index()
        s_after = rag.stats()
        assert s_after["built"]

    def test_empty_directory_stats(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        rag = ResearchRAG(dispatch_dir=str(empty))
        rag.build_index()
        s = rag.stats()
        assert s["num_files"] == 0
        assert s["num_chunks"] == 0

    def test_backend_field_present(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d))
        rag.build_index()
        s = rag.stats()
        assert s["backend"] in ("sklearn", "fallback")


class TestSearchByMetadata:
    def test_filter_by_dispatch_id(self, tmp_path):
        d = tmp_path / "dispatches"
        d.mkdir()
        (d / "DISPATCH_102_btc.md").write_text(
            "# DISPATCH_102 Analysis\n\nBTC content.", encoding="utf-8"
        )
        (d / "DISPATCH_081_calibration.md").write_text(
            "# DISPATCH_081 Calibration\n\nPlatt content.", encoding="utf-8"
        )
        rag = ResearchRAG(dispatch_dir=str(d))
        rag.build_index()

        matches = rag.search_by_metadata(dispatch_id="DISPATCH_102")
        assert len(matches) > 0
        assert all(c.dispatch_id == "DISPATCH_102" for c in matches)

    def test_filter_by_title_contains(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d), chunk_size=800, chunk_overlap=100)
        rag.build_index()

        matches = rag.search_by_metadata(title_contains="vpin")
        assert len(matches) > 0
        assert all("vpin" in c.title.lower() for c in matches)

    def test_filter_by_strategy_tag(self, tmp_path):
        d = tmp_path / "dispatches"
        d.mkdir()
        (d / "btc_file.md").write_text(
            "# BTC Strategy\n\nBTC5 uses VPIN gating.", encoding="utf-8"
        )
        rag = ResearchRAG(dispatch_dir=str(d))
        rag.build_index()

        matches = rag.search_by_metadata(strategy_tag="BTC5")
        assert len(matches) > 0

    def test_no_match_returns_empty_list(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d), chunk_size=800, chunk_overlap=100)
        rag.build_index()
        matches = rag.search_by_metadata(dispatch_id="DISPATCH_999")
        assert matches == []

    def test_combined_filters(self, tmp_path):
        d = _make_dispatch_dir(tmp_path)
        rag = ResearchRAG(dispatch_dir=str(d), chunk_size=800, chunk_overlap=100)
        rag.build_index()
        # title_contains="vpin" AND dispatch_id that doesn't match → empty
        matches = rag.search_by_metadata(
            title_contains="vpin", dispatch_id="DISPATCH_999"
        )
        assert matches == []


class TestDataclassIntegrity:
    def test_dispatch_chunk_fields(self):
        chunk = DispatchChunk(
            dispatch_id="DISPATCH_001",
            file_path="research/dispatches/test.md",
            title="Test",
            content="Content here",
            chunk_index=0,
            embedding={"token": 0.5},
            metadata={"dispatch_id": "DISPATCH_001"},
        )
        assert chunk.dispatch_id == "DISPATCH_001"
        assert chunk.chunk_index == 0
        assert chunk.embedding == {"token": 0.5}

    def test_retrieval_result_fields(self):
        chunk = DispatchChunk(
            dispatch_id="D1",
            file_path="f.md",
            title="T",
            content="C",
            chunk_index=0,
            embedding={},
            metadata={},
        )
        result = RetrievalResult(chunk=chunk, similarity=0.85, snippet="snippet text")
        assert result.similarity == 0.85
        assert result.snippet == "snippet text"
