from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache

from shared.python.elastifund_shared.env import env, env_bool, env_int, env_list, mask_secret
from shared.python.elastifund_shared.topology import ELASTIFUND_INDICES, ELASTIFUND_TOPICS


@dataclass(frozen=True)
class HubSettings:
    app_name: str
    environment: str
    host: str
    port: int
    elasticsearch_url: str
    elasticsearch_username: str
    elasticsearch_password: str
    elasticsearch_verify_certs: bool
    redis_url: str
    kafka_bootstrap_servers: tuple[str, ...]
    kafka_client_id: str
    agent_registration_index: str
    default_indices: tuple[str, ...]
    default_topics: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "HubSettings":
        return cls(
            app_name=env("HUB_APP_NAME", "Elastifund Hub Gateway"),
            environment=env("HUB_ENV", "local"),
            host=env("HUB_GATEWAY_HOST", "0.0.0.0"),
            port=env_int("HUB_GATEWAY_PORT", 8000),
            elasticsearch_url=env("ELASTICSEARCH_URL", "http://elasticsearch:9200"),
            elasticsearch_username=env("ELASTICSEARCH_USERNAME", "elastic"),
            elasticsearch_password=env("ELASTIC_PASSWORD", "changeme"),
            elasticsearch_verify_certs=env_bool("ELASTICSEARCH_VERIFY_CERTS", False),
            redis_url=env("REDIS_URL", "redis://redis:6379/0"),
            kafka_bootstrap_servers=env_list("KAFKA_BOOTSTRAP_SERVERS", ("kafka:9092",)),
            kafka_client_id=env("KAFKA_CLIENT_ID", "elastifund-hub"),
            agent_registration_index=env("ELASTIFUND_AGENT_INDEX", "elastifund-agents"),
            default_indices=env_list("ELASTIFUND_INDICES", ELASTIFUND_INDICES),
            default_topics=env_list("ELASTIFUND_TOPICS", ELASTIFUND_TOPICS),
        )

    def public_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["elasticsearch_password"] = mask_secret(self.elasticsearch_password)
        return data


@lru_cache(maxsize=1)
def get_settings() -> HubSettings:
    return HubSettings.from_env()
