"""Minimal Elasticsearch REST client used by the bootstrap CLI."""

from __future__ import annotations

import base64
import json
import ssl
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


class ElasticClientError(RuntimeError):
    """Raised when Elasticsearch returns an unexpected response."""


@dataclass(frozen=True)
class ElasticRestClient:
    """Small stdlib-only REST client for Elasticsearch bootstrap tasks."""

    base_url: str
    api_key: str | None = None
    username: str | None = None
    password: str | None = None
    verify_tls: bool = True
    timeout_seconds: float = 30.0

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def put(self, path: str, payload: dict[str, Any]) -> Any:
        return self.request("PUT", path, payload=payload)

    def post(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        return self.request("POST", path, payload=payload)

    def head(self, path: str) -> bool:
        try:
            self.request("HEAD", path, payload=None, decode_json=False)
            return True
        except ElasticClientError as exc:
            if "status=404" in str(exc):
                return False
            raise

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        decode_json: bool = True,
    ) -> Any:
        url = urljoin(self.base_url.rstrip("/") + "/", path.lstrip("/"))
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(url, method=method, data=body, headers=self._headers())
        context = None
        if not self.verify_tls:
            context = ssl._create_unverified_context()
        try:
            with urlopen(request, timeout=self.timeout_seconds, context=context) as response:
                content = response.read().decode("utf-8")
                if not decode_json:
                    return content
                if not content:
                    return {}
                return json.loads(content)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ElasticClientError(
                f"Elasticsearch request failed: status={exc.code} method={method} path={path} body={detail}"
            ) from exc

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.api_key:
            token = self.api_key
            if ":" in self.api_key:
                token = base64.b64encode(self.api_key.encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"ApiKey {token}"
        elif self.username and self.password:
            raw = f"{self.username}:{self.password}".encode("utf-8")
            token = base64.b64encode(raw).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
        return headers
