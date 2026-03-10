"""Public-web discovery helpers for deterministic revenue audits."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Mapping, Protocol
from urllib.parse import urljoin, urlparse

import httpx

from nontrading.config import DEFAULT_PERSONAL_EMAIL_DOMAINS

from .models import FetchedPage, ProspectProfile, PublicContactChannel

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
PHONE_RE = re.compile(r"(?:\+?1[-.\s]*)?(?:\(?\d{3}\)?[-.\s]*)\d{3}[-.\s]*\d{4}")
CTA_HINTS = ("book", "schedule", "quote", "estimate", "call", "contact", "start", "request", "audit")
LINK_PRIORITY_HINTS = ("contact", "services", "service", "about", "locations", "location")


@dataclass(frozen=True)
class FetchPolicy:
    timeout_seconds: float = 8.0
    max_pages: int = 3
    max_body_bytes: int = 250_000
    user_agent: str = "ElastifundRevenueAudit/1.0 (+https://elastifund.io)"


@dataclass(frozen=True)
class FetchResponse:
    url: str
    body: str
    status_code: int = 200
    content_type: str = "text/html; charset=utf-8"
    final_url: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "url", str(self.url).strip())
        object.__setattr__(self, "body", str(self.body))
        object.__setattr__(self, "status_code", int(self.status_code))
        object.__setattr__(self, "content_type", str(self.content_type or "text/html").strip().lower())
        object.__setattr__(self, "final_url", str(self.final_url or self.url).strip())


class PageFetcher(Protocol):
    def fetch(self, url: str) -> FetchResponse:
        """Fetch one public page."""


class HTTPPageFetcher:
    """Bounded read-only fetcher for public website discovery."""

    def __init__(self, policy: FetchPolicy | None = None):
        self.policy = policy or FetchPolicy()

    def fetch(self, url: str) -> FetchResponse:
        with httpx.Client(
            follow_redirects=True,
            headers={"User-Agent": self.policy.user_agent},
            timeout=self.policy.timeout_seconds,
        ) as client:
            response = client.get(url)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "text/html")
            body = response.text[: self.policy.max_body_bytes]
            return FetchResponse(
                url=url,
                body=body,
                status_code=response.status_code,
                content_type=content_type,
                final_url=str(response.url),
            )


class StaticPageFetcher:
    """Deterministic fixture fetcher for tests and offline examples."""

    def __init__(self, pages: Mapping[str, str | FetchResponse]):
        self.pages = {
            self._normalize_key(url): value if isinstance(value, FetchResponse) else FetchResponse(url=url, body=value)
            for url, value in pages.items()
        }

    @staticmethod
    def _normalize_key(url: str) -> str:
        parsed = urlparse(str(url).strip())
        path = parsed.path or "/"
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"

    def fetch(self, url: str) -> FetchResponse:
        key = self._normalize_key(url)
        try:
            return self.pages[key]
        except KeyError as exc:
            raise KeyError(f"No static revenue-audit fixture registered for {url}") from exc


@dataclass
class _PageParser(HTMLParser):
    base_url: str
    title_parts: list[str] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)
    h1: list[str] = field(default_factory=list)
    meta_description: str = ""
    canonical_url: str = ""
    internal_links: list[str] = field(default_factory=list)
    external_links: list[str] = field(default_factory=list)
    cta_texts: list[str] = field(default_factory=list)
    schema_types: list[str] = field(default_factory=list)
    contact_channels: list[PublicContactChannel] = field(default_factory=list)
    forms_detected: bool = False
    script_count: int = 0
    image_count: int = 0
    current_anchor_href: str | None = None
    current_anchor_parts: list[str] = field(default_factory=list)
    current_button_parts: list[str] = field(default_factory=list)
    current_h1_parts: list[str] = field(default_factory=list)
    current_script_parts: list[str] = field(default_factory=list)
    capture_title: bool = False
    capture_button: bool = False
    capture_h1: bool = False
    capture_json_ld: bool = False
    in_ignored_tag: bool = False

    def __post_init__(self) -> None:
        super().__init__(convert_charrefs=True)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {str(key).lower(): str(value or "") for key, value in attrs}
        tag_name = tag.lower()
        if tag_name == "title":
            self.capture_title = True
        elif tag_name == "meta":
            if attr_map.get("name", "").lower() == "description":
                self.meta_description = attr_map.get("content", "").strip()
        elif tag_name == "link":
            rel = attr_map.get("rel", "").lower()
            if "canonical" in rel and attr_map.get("href"):
                self.canonical_url = urljoin(self.base_url, attr_map["href"])
        elif tag_name == "a":
            self.current_anchor_href = attr_map.get("href") or ""
            self.current_anchor_parts = []
        elif tag_name == "button":
            self.capture_button = True
            self.current_button_parts = []
        elif tag_name == "h1":
            self.capture_h1 = True
            self.current_h1_parts = []
        elif tag_name == "form":
            self.forms_detected = True
        elif tag_name == "img":
            self.image_count += 1
        elif tag_name == "script":
            self.script_count += 1
            if "ld+json" in attr_map.get("type", "").lower():
                self.capture_json_ld = True
                self.current_script_parts = []
        elif tag_name in {"style", "noscript"}:
            self.in_ignored_tag = True

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if tag_name == "title":
            self.capture_title = False
        elif tag_name == "a":
            self._finalize_anchor()
        elif tag_name == "button":
            self.capture_button = False
            text = " ".join(" ".join(self.current_button_parts).split())
            if text:
                self.cta_texts.append(text)
            self.current_button_parts = []
        elif tag_name == "h1":
            self.capture_h1 = False
            text = " ".join(" ".join(self.current_h1_parts).split())
            if text:
                self.h1.append(text)
            self.current_h1_parts = []
        elif tag_name == "script":
            if self.capture_json_ld:
                self._parse_schema_payload("".join(self.current_script_parts))
            self.capture_json_ld = False
            self.current_script_parts = []
        elif tag_name in {"style", "noscript"}:
            self.in_ignored_tag = False

    def handle_data(self, data: str) -> None:
        text = str(data or "")
        if not text.strip():
            return
        if self.capture_title:
            self.title_parts.append(text)
        if self.capture_h1:
            self.current_h1_parts.append(text)
        if self.current_anchor_href is not None:
            self.current_anchor_parts.append(text)
        if self.capture_button:
            self.current_button_parts.append(text)
        if self.capture_json_ld:
            self.current_script_parts.append(text)
        if not self.in_ignored_tag:
            self.text_parts.append(text)

    def _finalize_anchor(self) -> None:
        href = str(self.current_anchor_href or "").strip()
        text = " ".join(" ".join(self.current_anchor_parts).split())
        self.current_anchor_href = None
        self.current_anchor_parts = []
        if not href:
            return
        normalized_href = href.lower()
        if normalized_href.startswith("mailto:"):
            email = href.split(":", 1)[1].strip()
            if email:
                self.contact_channels.append(
                    PublicContactChannel(
                        kind="email",
                        value=email,
                        source_url=self.base_url,
                        label=text,
                        is_business=self._is_business_email(email),
                    )
                )
            return
        if normalized_href.startswith("tel:"):
            phone = href.split(":", 1)[1].strip()
            if phone:
                self.contact_channels.append(
                    PublicContactChannel(
                        kind="phone",
                        value=phone,
                        source_url=self.base_url,
                        label=text,
                    )
                )
            return
        absolute = urljoin(self.base_url, href)
        if self._is_same_domain(absolute):
            self.internal_links.append(absolute)
            anchor_text = text.lower()
            if any(hint in absolute.lower() for hint in ("contact", "quote", "estimate")) or "contact" in anchor_text:
                self.contact_channels.append(
                    PublicContactChannel(
                        kind="contact_page",
                        value=absolute,
                        source_url=self.base_url,
                        label=text,
                    )
                )
            if text and any(hint in anchor_text for hint in CTA_HINTS):
                self.cta_texts.append(text)
            return
        self.external_links.append(absolute)

    def _parse_schema_payload(self, payload: str) -> None:
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return
        for schema_type in self._extract_schema_types(parsed):
            text = str(schema_type).strip()
            if text:
                self.schema_types.append(text)

    def _extract_schema_types(self, payload: object) -> list[str]:
        if isinstance(payload, dict):
            items: list[str] = []
            if "@type" in payload:
                raw_type = payload["@type"]
                if isinstance(raw_type, list):
                    items.extend(str(item) for item in raw_type)
                else:
                    items.append(str(raw_type))
            for value in payload.values():
                items.extend(self._extract_schema_types(value))
            return items
        if isinstance(payload, list):
            items: list[str] = []
            for item in payload:
                items.extend(self._extract_schema_types(item))
            return items
        return []

    def _is_same_domain(self, url: str) -> bool:
        return urlparse(url).netloc.lower() == urlparse(self.base_url).netloc.lower()

    @staticmethod
    def _is_business_email(email: str) -> bool:
        domain = email.partition("@")[2].strip().lower()
        return bool(domain) and domain not in set(DEFAULT_PERSONAL_EMAIL_DOMAINS)

    def build_page(self, response: FetchResponse) -> FetchedPage:
        visible_text = " ".join(" ".join(self.text_parts).split())
        channels = list(self.contact_channels)
        for email in EMAIL_RE.findall(visible_text):
            channels.append(
                PublicContactChannel(
                    kind="email",
                    value=email,
                    source_url=response.final_url or response.url,
                    is_business=self._is_business_email(email),
                )
            )
        for phone in PHONE_RE.findall(visible_text):
            channels.append(
                PublicContactChannel(
                    kind="phone",
                    value=phone,
                    source_url=response.final_url or response.url,
                )
            )
        if self.forms_detected:
            channels.append(
                PublicContactChannel(
                    kind="contact_form",
                    value=response.final_url or response.url,
                    source_url=response.final_url or response.url,
                    label="public_form",
                )
            )
        content_hash = hashlib.sha256(response.body.encode("utf-8")).hexdigest()
        return FetchedPage(
            url=response.url,
            final_url=response.final_url or response.url,
            status_code=response.status_code,
            content_type=response.content_type,
            title=" ".join(" ".join(self.title_parts).split()),
            meta_description=self.meta_description,
            canonical_url=self.canonical_url,
            h1=tuple(self.h1),
            text=visible_text,
            internal_links=tuple(self.internal_links),
            external_links=tuple(self.external_links),
            cta_texts=tuple(self.cta_texts),
            schema_types=tuple(self.schema_types),
            contact_channels=tuple(channels),
            forms_detected=self.forms_detected,
            script_count=self.script_count,
            image_count=self.image_count,
            html_bytes=len(response.body.encode("utf-8")),
            metadata={"content_sha256": content_hash},
        )


class RevenueAuditDiscovery:
    """Deterministic public-web discovery worker for website-audit prospects."""

    def __init__(self, fetcher: PageFetcher | None = None, policy: FetchPolicy | None = None):
        self.policy = policy or FetchPolicy()
        self.fetcher = fetcher or HTTPPageFetcher(self.policy)

    def discover(
        self,
        seed_url: str,
        *,
        company_name: str = "",
        country_code: str = "US",
        discovery_source: str = "manual_seed",
    ) -> ProspectProfile:
        homepage = self._fetch_page(seed_url)
        candidates = self._select_candidate_links(homepage)
        pages = [homepage]
        notes: list[str] = []
        for candidate in candidates[: max(self.policy.max_pages - 1, 0)]:
            try:
                pages.append(self._fetch_page(candidate))
            except Exception as exc:  # pragma: no cover - defensive only
                notes.append(f"fetch_failed:{candidate}:{exc.__class__.__name__}")
        channels: list[PublicContactChannel] = []
        contact_urls: list[str] = []
        for page in pages:
            channels.extend(page.contact_channels)
            for channel in page.contact_channels:
                if channel.kind in {"contact_page", "contact_form"}:
                    contact_urls.append(channel.value)
                elif channel.kind in {"email", "phone"}:
                    contact_urls.append(channel.source_url)
        label = company_name.strip() or _derive_company_name(homepage) or _domain_label(homepage.final_url)
        return ProspectProfile(
            seed_url=seed_url,
            website_url=homepage.final_url or homepage.url,
            domain=urlparse(homepage.final_url or homepage.url).netloc,
            company_name=label,
            country_code=country_code,
            discovery_source=discovery_source,
            pages=tuple(pages),
            contact_channels=tuple(channels),
            public_contact_urls=tuple(contact_urls),
            discovery_notes=tuple(notes),
            metadata={
                "max_pages": self.policy.max_pages,
                "fetched_pages": len(pages),
            },
        )

    def _fetch_page(self, url: str) -> FetchedPage:
        response = self.fetcher.fetch(url)
        parser = _PageParser(base_url=response.final_url or response.url)
        parser.feed(response.body)
        parser.close()
        return parser.build_page(response)

    def _select_candidate_links(self, page: FetchedPage) -> list[str]:
        root_domain = urlparse(page.final_url).netloc.lower()
        ranked: list[tuple[int, int, str]] = []
        for index, link in enumerate(page.internal_links):
            parsed = urlparse(link)
            if parsed.netloc.lower() != root_domain:
                continue
            if (parsed.path or "/") == "/":
                continue
            score = self._link_priority(link)
            ranked.append((score, index, link))
        ranked.sort()
        return [link for _, _, link in ranked]

    @staticmethod
    def _link_priority(url: str) -> int:
        lower = url.lower()
        for index, hint in enumerate(LINK_PRIORITY_HINTS):
            if hint in lower:
                return index
        return len(LINK_PRIORITY_HINTS) + lower.count("/")


def discover_prospect(
    seed_url: str,
    *,
    fetcher: PageFetcher | None = None,
    policy: FetchPolicy | None = None,
    company_name: str = "",
    country_code: str = "US",
    discovery_source: str = "manual_seed",
) -> ProspectProfile:
    return RevenueAuditDiscovery(fetcher=fetcher, policy=policy).discover(
        seed_url,
        company_name=company_name,
        country_code=country_code,
        discovery_source=discovery_source,
    )


def _derive_company_name(page: FetchedPage) -> str:
    for candidate in (page.title, page.h1[0] if page.h1 else ""):
        text = str(candidate).strip()
        if not text:
            continue
        for separator in ("|", "-", ":", "•"):
            if separator in text:
                left = text.split(separator, 1)[0].strip()
                if left:
                    return left
        return text
    return ""


def _domain_label(url: str) -> str:
    domain = urlparse(url).netloc.lower()
    label = domain.split(".", 1)[0].replace("-", " ").replace("_", " ").strip()
    return " ".join(part.capitalize() for part in label.split()) or domain
