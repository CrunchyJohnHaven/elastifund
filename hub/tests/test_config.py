from hub.app.config import HubSettings


def test_hub_settings_from_env(monkeypatch):
    monkeypatch.setenv("HUB_APP_NAME", "Test Hub")
    monkeypatch.setenv("HUB_ENV", "test")
    monkeypatch.setenv("HUB_GATEWAY_PORT", "8100")
    monkeypatch.setenv("ELASTIC_PASSWORD", "supersecret")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092,kafka:9093")
    monkeypatch.setenv("ELASTIFUND_INDICES", "a,b")

    settings = HubSettings.from_env()

    assert settings.app_name == "Test Hub"
    assert settings.environment == "test"
    assert settings.port == 8100
    assert settings.elasticsearch_password == "supersecret"
    assert settings.kafka_bootstrap_servers == ("kafka:9092", "kafka:9093")
    assert settings.default_indices == ("a", "b")


def test_public_dict_masks_password(monkeypatch):
    monkeypatch.setenv("ELASTIC_PASSWORD", "supersecret")

    settings = HubSettings.from_env()
    public_data = settings.public_dict()

    assert public_data["elasticsearch_password"] != "supersecret"
    assert public_data["elasticsearch_password"].endswith("cret")
