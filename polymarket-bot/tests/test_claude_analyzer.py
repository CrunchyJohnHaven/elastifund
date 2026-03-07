"""Tests for the Claude AI market analyzer."""
import pytest
from unittest.mock import MagicMock, patch

from src.claude_analyzer import ClaudeAnalyzer


class TestClaudeAnalyzer:
    def test_init_no_api_key(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
            analyzer = ClaudeAnalyzer(api_key="")
            assert not analyzer.is_available

    def test_parse_response_buy_yes(self):
        analyzer = ClaudeAnalyzer.__new__(ClaudeAnalyzer)
        analyzer.mispricing_threshold = 0.10

        response = "PROBABILITY: 0.80\nCONFIDENCE: 0.75\nREASONING: Strong evidence for YES"
        result = analyzer._parse_response(response, current_price=0.50)

        assert result["probability"] == 0.80
        assert result["confidence"] == 0.75
        assert result["mispriced"] is True
        assert result["direction"] == "buy_yes"
        assert abs(result["edge"] - 0.30) < 0.001

    def test_parse_response_buy_no(self):
        analyzer = ClaudeAnalyzer.__new__(ClaudeAnalyzer)
        analyzer.mispricing_threshold = 0.10

        response = "PROBABILITY: 0.20\nCONFIDENCE: 0.80\nREASONING: Evidence against"
        result = analyzer._parse_response(response, current_price=0.60)

        assert result["probability"] == 0.20
        assert result["mispriced"] is True
        assert result["direction"] == "buy_no"
        assert result["edge"] < 0

    def test_parse_response_hold(self):
        analyzer = ClaudeAnalyzer.__new__(ClaudeAnalyzer)
        analyzer.mispricing_threshold = 0.10

        response = "PROBABILITY: 0.52\nCONFIDENCE: 0.50\nREASONING: Close to market"
        result = analyzer._parse_response(response, current_price=0.50)

        assert result["mispriced"] is False
        assert result["direction"] == "hold"
        assert abs(result["edge"]) < 0.10

    def test_parse_response_clamps_values(self):
        analyzer = ClaudeAnalyzer.__new__(ClaudeAnalyzer)
        analyzer.mispricing_threshold = 0.10

        response = "PROBABILITY: 1.50\nCONFIDENCE: -0.5\nREASONING: Bad values"
        result = analyzer._parse_response(response, current_price=0.50)

        assert result["probability"] == 1.0
        assert result["confidence"] == 0.0

    def test_parse_response_malformed(self):
        analyzer = ClaudeAnalyzer.__new__(ClaudeAnalyzer)
        analyzer.mispricing_threshold = 0.10

        response = "I think the probability is about 60%"
        result = analyzer._parse_response(response, current_price=0.50)

        # Falls back to current price when parsing fails
        assert result["probability"] == 0.50
        assert result["direction"] == "hold"

    def test_estimate_monthly_cost(self):
        analyzer = ClaudeAnalyzer.__new__(ClaudeAnalyzer)
        cost = analyzer.estimate_monthly_cost(analyses_per_day=50)
        # Should be between $0.50 and $20
        assert 0.50 < cost < 20.0

    def test_build_prompt(self):
        analyzer = ClaudeAnalyzer.__new__(ClaudeAnalyzer)
        prompt = analyzer._build_prompt("Will BTC reach 100K?", 0.65, "Recent rally")
        assert "Will BTC reach 100K?" in prompt
        assert "65.0%" in prompt
        assert "Recent rally" in prompt

    def test_build_prompt_no_context(self):
        analyzer = ClaudeAnalyzer.__new__(ClaudeAnalyzer)
        prompt = analyzer._build_prompt("Test question?", 0.50, "")
        assert "Test question?" in prompt
        assert "Additional context" not in prompt

    @pytest.mark.asyncio
    async def test_analyze_market_no_client(self):
        analyzer = ClaudeAnalyzer.__new__(ClaudeAnalyzer)
        analyzer._client = None
        analyzer.mispricing_threshold = 0.10

        result = await analyzer.analyze_market("Test?", 0.50)
        assert result["direction"] == "hold"
        assert result["mispriced"] is False
        assert "not available" in result["reasoning"]
