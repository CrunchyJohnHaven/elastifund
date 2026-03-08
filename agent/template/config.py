from __future__ import annotations

from dataclasses import asdict, dataclass

from shared.python.elastifund_shared.env import env, env_bool, env_int, env_list
from shared.python.elastifund_shared.topology import ELASTIFUND_TOPICS


@dataclass(frozen=True)
class AgentTemplateSettings:
    agent_name: str
    hub_gateway_url: str
    heartbeat_interval_seconds: int
    telemetry_enabled: bool
    subscribed_topics: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "AgentTemplateSettings":
        return cls(
            agent_name=env("ELASTIFUND_AGENT_NAME", "template-agent"),
            hub_gateway_url=env("ELASTIFUND_GATEWAY_URL", "http://gateway:8000"),
            heartbeat_interval_seconds=env_int("ELASTIFUND_AGENT_HEARTBEAT_SECONDS", 60),
            telemetry_enabled=env_bool("ELASTIFUND_AGENT_TELEMETRY_ENABLED", True),
            subscribed_topics=env_list("ELASTIFUND_TOPICS", ELASTIFUND_TOPICS),
        )

    def as_dict(self) -> dict[str, object]:
        return asdict(self)
