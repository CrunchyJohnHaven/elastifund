"""Tests for the Claude AI market analyzer."""
import pytest
from unittest.mock import MagicMock, patch

from src.claude_analyzer import ClaudeAnalyzer


def _make_analyzer(**overrides):
    """Create a ClaudeAnalyzer for testing without needing an API key."""
    analyzer = ClaudeAnalyzer.__new__(ClaudeAnalyzer)
    analyzer.mispricing_threshold = 0.10
    analyzer.yes_threshold = 0.15
    analyzer.no_threshold = 0.05
    analyzer.use_calibration = False
    analyzer.account_for_fees = False
    analyzer.min_category_priority = 1
    analyzer._client = None
    analyzer.api_key = ""
    for k, v in overrides.items():
        setattr(analyzer, k, v)
    return analyzer


class TestClaudeAnalyzer:
    def test_init_no_api_key(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
            analyzer = ClaudeAnalyzer(api_key="")
            assert not analyzer.is_available

    def test_parse_response_buy_yes(self):
        analyzer = _make_analyzer()

        response = "PROBABILITY: 0.80\nCONFIDENCE: 0.75\nREASONING: Strong evidence for YES"
        result = analyzer._parse_response(response, current_price=0.50, category="politics")

        assert result["probability"] == 0.80
        assert result["confidence"] == 0.75
        assert result["mispriced"] is True
        assert result["direction"] == "buy_yes"
        assert abs(result["edge"] - 0.30) < 0.001

    def test_parse_response_buy_no(self):
        analyzer = _make_analyzer()

        response = "PROBABILITY: 0.20\nCONFIDENCE: 0.80\nREASONING: Evidence against"
        result = analyzer._parse_response(response, current_price=0.60, category="politics")

        assert result["probability"] == 0.20
        assert result["mispriced"] is True
        assert result["direction"] == "buy_no"
        # Edge is abs(raw_edge) - fee, so positive even for NO trades
        assert result["edge"] > 0

    def test_parse_response_hold(self):
        analyzer = _make_analyzer()

        response = "PROBABILITY: 0.52\nCONFIDENCE: 0.50\nREASONING: Close to market"
        result = analyzer._parse_response(response, current_price=0.50, category="politics")

        assert result["mispriced"] is False
        assert result["direction"] == "hold"
        assert abs(result["edge"]) < 0.10

    def test_parse_response_clamps_values(self):
        analyzer = _make_analyzer()

        response = "PROBABILITY: 1.50\nCONFIDENCE: -0.5\nREASONING: Bad values"
        result = analyzer._parse_response(response, current_price=0.50, category="unknown")

        assert result["probability"] >= 0.99  # Clamped to [0.01, 0.99]
        assert result["confidence"] == 0.0

    def test_parse_response_malformed(self):
        analyzer = _make_analyzer()

        response = "I think the probability is about 60%"
        result = analyzer._parse_response(response, current_price=0.50, category="unknown")

        # Falls back to current price when parsing fails
        assert result["probability"] == 0.50
        assert result["direction"] == "hold"

    def test_estimate_monthly_cost(self):
        analyzer = _make_analyzer()
        cost = analyzer.estimate_monthly_cost(analyses_per_day=50)
        assert 0.50 < cost < 20.0

    def test_build_prompt(self):
        analyzer = _make_analyzer()
        prompt = analyzer._build_prompt("Will BTC reach 100K?", "Recent rally")
        assert "Will BTC reach 100K?" in prompt
        assert "Recent rally" in prompt

    def test_build_prompt_no_context(self):
        analyzer = _make_analyzer()
        prompt = analyzer._build_prompt("Test question?", "")
        assert "Test question?" in prompt

    @pytest.mark.asyncio
    async def test_analyze_market_no_client(self):
        analyzer = _make_analyzer()

        result = await analyzer.analyze_market("Test?", 0.50)
        assert result["direction"] == "hold"
        assert result["mispriced"] is False
        assert "not available" in result["reasoning"]
