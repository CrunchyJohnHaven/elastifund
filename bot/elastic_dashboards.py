"""Import prebuilt Kibana saved objects for Elastifund."""

from __future__ import annotations

import argparse
import base64
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import requests


logger = logging.getLogger("JJ.elastic_dashboards")


@dataclass(slots=True)
class KibanaConfig:
    url: str
    username: str
    password: str
    api_key: str
    dashboards_dir: Path

    @classmethod
    def from_env(cls) -> "KibanaConfig":
        return cls(
            url=os.environ.get("KIBANA_URL", "http://127.0.0.1:5601").rstrip("/"),
            username=os.environ.get("KIBANA_USER", "elastic"),
            password=os.environ.get("KIBANA_PASSWORD", os.environ.get("ES_PASSWORD", "")),
            api_key=os.environ.get("KIBANA_API_KEY", ""),
            dashboards_dir=Path(os.environ.get("KIBANA_DASHBOARDS_DIR", "infra/kibana_dashboards")),
        )


def _headers(config: KibanaConfig) -> dict[str, str]:
    headers = {"kbn-xsrf": "true"}
    if config.api_key:
        token = config.api_key
        if ":" in token:
            token = base64.b64encode(token.encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"ApiKey {token}"
        return headers
    if config.username and config.password:
        raw = f"{config.username}:{config.password}".encode("utf-8")
        headers["Authorization"] = f"Basic {base64.b64encode(raw).decode('ascii')}"
    return headers


def import_dashboards(config: KibanaConfig | None = None) -> dict[str, bool]:
    cfg = config or KibanaConfig.from_env()
    results: dict[str, bool] = {}

    for dashboard_file in sorted(cfg.dashboards_dir.glob("*.ndjson")):
        try:
            with dashboard_file.open("rb") as handle:
                response = requests.post(
                    f"{cfg.url}/api/saved_objects/_import?overwrite=true",
                    headers=_headers(cfg),
                    files={"file": (dashboard_file.name, handle, "application/ndjson")},
                    timeout=30,
                )
            response.raise_for_status()
            results[dashboard_file.name] = True
            logger.info("Imported Kibana dashboard %s", dashboard_file.name)
        except Exception as exc:
            results[dashboard_file.name] = False
            logger.warning("Failed to import %s: %s", dashboard_file.name, exc)

    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import Elastifund Kibana dashboards")
    parser.add_argument("--dashboards-dir", default="infra/kibana_dashboards")
    args = parser.parse_args(argv)

    config = KibanaConfig.from_env()
    config = KibanaConfig(
        url=config.url,
        username=config.username,
        password=config.password,
        api_key=config.api_key,
        dashboards_dir=Path(args.dashboards_dir),
    )
    results = import_dashboards(config)
    return 0 if all(results.values()) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
