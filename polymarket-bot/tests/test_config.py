"""Tests for configuration management."""
import os
import pytest
from unittest.mock import patch


class TestSettings:
    def test_effective_private_key_strips_0x(self):
        env = {
            "POLYMARKET_PRIVATE_KEY": "0xabc123",
            "DATABASE_URL": "sqlite:///test.db",
        }
        with patch.dict(os.environ, env, clear=False):
            from src.core.config import Settings
            settings = Settings()
            assert settings.effective_private_key == "abc123"

    def test_effective_private_key_fallback_to_pk(self):
        env = {
            "POLYMARKET_PRIVATE_KEY": "",
            "POLYMARKET_PK": "def456",
            "DATABASE_URL": "sqlite:///test.db",
        }
        with patch.dict(os.environ, env, clear=False):
            from src.core.config import Settings
            settings = Settings()
            assert settings.effective_private_key == "def456"

    def test_effective_funder_fallback(self):
        env = {
            "POLYMARKET_FUNDER_ADDRESS": "",
            "POLYMARKET_FUNDER": "0xfunder",
            "DATABASE_URL": "sqlite:///test.db",
        }
        with patch.dict(os.environ, env, clear=False):
            from src.core.config import Settings
            settings = Settings()
            assert settings.effective_funder_address == "0xfunder"

    def test_has_api_credentials_true(self):
        env = {
            "POLYMARKET_API_KEY": "key123",
            "POLYMARKET_API_SECRET": "secret123",
            "POLYMARKET_API_PASSPHRASE": "pass123",
            "DATABASE_URL": "sqlite:///test.db",
        }
        with patch.dict(os.environ, env, clear=False):
            from src.core.config import Settings
            settings = Settings()
            assert settings.has_api_credentials is True

    def test_has_api_credentials_false(self):
        env = {
            "POLYMARKET_API_KEY": "",
            "POLYMARKET_API_SECRET": "",
            "POLYMARKET_API_PASSPHRASE": "",
            "DATABASE_URL": "sqlite:///test.db",
        }
        with patch.dict(os.environ, env, clear=False):
            from src.core.config import Settings
            settings = Settings()
            assert settings.has_api_credentials is False

    def test_defaults(self):
        env = {
            "DATABASE_URL": "sqlite:///test.db",
        }
        with patch.dict(os.environ, env, clear=False):
            from src.core.config import Settings
            settings = Settings()
            assert settings.live_trading is False
            assert settings.paper_trading is True
            assert settings.kelly_fraction == 0.5
            assert settings.chain_id == 137
            assert settings.signature_type == 2

    def test_elastic_settings_accept_hub_env_aliases(self):
        env = {
            "DATABASE_URL": "sqlite:///test.db",
            "ELASTIFUND_AGENT_TELEMETRY_ENABLED": "true",
            "ELASTICSEARCH_URL": "http://elasticsearch:9200",
            "ELASTICSEARCH_USERNAME": "elastic",
            "ELASTIC_PASSWORD": "changeme",
            "ELASTIFUND_AGENT_ID": "jj-live-paper",
        }
        with patch.dict(os.environ, env, clear=False):
            from src.core.config import Settings
            settings = Settings()
            assert settings.elastic_telemetry_enabled is True
            assert settings.elasticsearch_url == "http://elasticsearch:9200"
            assert settings.elasticsearch_username == "elastic"
            assert settings.elasticsearch_password == "changeme"
            assert settings.elastic_agent_id == "jj-live-paper"
