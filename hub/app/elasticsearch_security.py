from __future__ import annotations

import base64
import json
import ssl
from dataclasses import dataclass
from typing import Any
from urllib import error, request


@dataclass(frozen=True)
class ElasticsearchSecurityClient:
    base_url: str
    username: str
    password: str
    verify_certs: bool = False
    timeout_seconds: float = 5.0

    def ping(self) -> tuple[bool, dict[str, Any]]:
        try:
            payload = self._request("GET", "/")
        except RuntimeError as exc:
            return False, {"error": str(exc)}

        version = payload.get("version", {}).get("number")
        cluster_name = payload.get("cluster_name")
        return True, {"cluster_name": cluster_name, "version": version}

    def create_api_key(
        self,
        *,
        name: str,
        role_descriptors: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"name": name}
        if role_descriptors:
            body["role_descriptors"] = role_descriptors
        if metadata:
            body["metadata"] = metadata
        return self._request("POST", "/_security/api_key", body)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = None
        headers = {
            "Authorization": f"Basic {self._basic_auth_header()}",
        }
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        url = f"{self.base_url.rstrip('/')}{path}"
        req = request.Request(url=url, method=method, data=body, headers=headers)
        context = None
        if url.startswith("https://") and not self.verify_certs:
            context = ssl._create_unverified_context()

        try:
            with request.urlopen(req, timeout=self.timeout_seconds, context=context) as response:
                content = response.read().decode("utf-8")
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Elasticsearch returned {exc.code}: {details}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Unable to reach Elasticsearch at {self.base_url}: {exc.reason}") from exc

        if not content:
            return {}
        return json.loads(content)

    def _basic_auth_header(self) -> str:
        token = f"{self.username}:{self.password}".encode("utf-8")
        return base64.b64encode(token).decode("ascii")
