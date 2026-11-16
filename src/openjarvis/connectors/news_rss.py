"""News/RSS connector — aggregate headlines from RSS and Atom feeds.

Uses stdlib xml.etree.ElementTree for parsing (no extra dependencies).
Config file lists feeds to follow. All HTTP calls are in module-level
functions for easy mocking in tests.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import re
import socket
import ssl
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import urljoin, urlparse

import httpx

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ConnectorRegistry

_DEFAULT_CONFIG_PATH = str(DEFAULT_CONFIG_DIR / "connectors" / "news_rss.json")
_MAX_REDIRECTS = 5
_MAX_FEED_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class _FeedTarget:
    """A validated URL plus the exact public addresses it may connect to."""

    scheme: str
    hostname: str
    port: int
    request_target: str
    host_header: str
    addresses: tuple[str, ...]


def _resolve_host_addresses(hostname: str, port: int) -> tuple[str, ...]:
    """Resolve once, reject every non-global answer, and return pinned IPs."""
    from openjarvis.security.ssrf import is_private_ip

    try:
        results = socket.getaddrinfo(
            hostname,
            port,
            socket.AF_UNSPEC,
            socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError(
            f"RSS feed hostname could not be resolved: {hostname}"
        ) from exc

    addresses: list[str] = []
    for _family, _type, _proto, _canonname, sockaddr in results:
        raw_ip = sockaddr[0].split("%", 1)[0]
        try:
            address = ipaddress.ip_address(raw_ip)
        except ValueError as exc:
            raise ValueError(f"RSS feed resolved to an invalid IP: {raw_ip}") from exc
        # ``is_global`` closes gaps outside the project's original RFC1918
        # list (CGNAT, benchmarking, documentation, and other special ranges).
        if not address.is_global or is_private_ip(str(address)):
            raise ValueError(f"RSS feed resolved to a non-public IP: {address}")
        normalized = str(address)
        if normalized not in addresses:
            addresses.append(normalized)

    if not addresses:
        raise ValueError(f"RSS feed hostname returned no addresses: {hostname}")
    return tuple(addresses)


def _validate_feed_url(url: str) -> _FeedTarget:
    """Reject malformed/private targets and pin the addresses just checked."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Each RSS feed must be an http(s) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("RSS feed URLs must not contain user credentials")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Each RSS feed must include a hostname")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise ValueError("RSS feed URL contains an invalid port") from exc

    from openjarvis.security.ssrf import check_ssrf

    error = check_ssrf(url)
    if error:
        raise ValueError(f"RSS feed URL is not allowed: {error}")

    # IDNA is used consistently for DNS, HTTP Host, TLS SNI, and certificate
    # verification. IP literals are already ASCII and remain unchanged.
    try:
        ipaddress.ip_address(hostname)
        connection_hostname = hostname
    except ValueError:
        try:
            connection_hostname = hostname.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError("RSS feed hostname is not valid IDNA") from exc

    addresses = _resolve_host_addresses(connection_hostname, port)
    default_port = 443 if parsed.scheme == "https" else 80
    displayed_host = (
        f"[{connection_hostname}]"
        if ":" in connection_hostname
        else connection_hostname
    )
    host_header = displayed_host if port == default_port else f"{displayed_host}:{port}"
    request_target = parsed.path or "/"
    if parsed.query:
        request_target = f"{request_target}?{parsed.query}"

    return _FeedTarget(
        scheme=parsed.scheme,
        hostname=connection_hostname,
        port=port,
        request_target=request_target,
        host_header=host_header,
        addresses=addresses,
    )


class _PinnedConnectionMixin:
    """Connect to a verified IP while retaining the URL host for HTTP/TLS."""

    def __init__(self, host: str, port: int, *, pinned_ip: str, **kwargs: Any) -> None:
        self._pinned_ip = pinned_ip
        super().__init__(host, port, **kwargs)
        # HTTPConnection.__init__ deliberately installs socket.create_connection
        # as an instance attribute, so replace that hook after initialization.
        self._create_connection = self._create_pinned_connection

    def _create_pinned_connection(self, address, timeout, source_address):
        # Ignore ``address[0]`` so http.client never performs a second DNS
        # lookup. HTTPSConnection still uses ``self.host`` as TLS SNI and for
        # certificate hostname verification.
        return socket.create_connection(
            (self._pinned_ip, address[1]),
            timeout,
            source_address,
        )


class _PinnedHTTPConnection(_PinnedConnectionMixin, http.client.HTTPConnection):
    pass


class _PinnedHTTPSConnection(_PinnedConnectionMixin, http.client.HTTPSConnection):
    pass


def _request_feed(url: str, target: _FeedTarget) -> httpx.Response:
    """GET *url* using only the already-validated addresses in *target*."""
    request = httpx.Request("GET", url)
    last_error: Exception | None = None

    for address in target.addresses:
        connection_cls = (
            _PinnedHTTPSConnection
            if target.scheme == "https"
            else _PinnedHTTPConnection
        )
        connection = connection_cls(
            target.hostname,
            target.port,
            pinned_ip=address,
            timeout=30.0,
        )
        try:
            connection.request(
                "GET",
                target.request_target,
                headers={
                    "Host": target.host_header,
                    "Accept": (
                        "application/rss+xml, application/atom+xml, "
                        "application/xml, text/xml;q=0.9, */*;q=0.1"
                    ),
                    "User-Agent": "OpenJarvis-RSS/1.0",
                    "Connection": "close",
                },
            )
            raw_response = connection.getresponse()
            body = raw_response.read(_MAX_FEED_BYTES + 1)
            if len(body) > _MAX_FEED_BYTES:
                raise ValueError(f"RSS feed exceeded {_MAX_FEED_BYTES} response bytes")
            return httpx.Response(
                raw_response.status,
                headers=raw_response.getheaders(),
                content=body,
                request=request,
            )
        except (OSError, http.client.HTTPException) as exc:
            last_error = exc
        finally:
            connection.close()

    raise httpx.RequestError(
        f"Unable to fetch RSS feed from its verified addresses: {last_error}",
        request=request,
    ) from last_error


def _fetch_feed(url: str) -> str:
    """Download feed XML while validating every redirect target."""
    current_url = url
    for _ in range(_MAX_REDIRECTS + 1):
        target = _validate_feed_url(current_url)
        resp = _request_feed(current_url, target)
        if resp.status_code not in {301, 302, 303, 307, 308}:
            resp.raise_for_status()
            return resp.text
        location = resp.headers.get("location", "")
        if not location:
            resp.raise_for_status()
            return resp.text
        current_url = urljoin(current_url, location)
    raise ValueError(f"RSS feed exceeded {_MAX_REDIRECTS} redirects")


def _parse_rss_items(xml_text: str, max_items: int = 5) -> List[Dict[str, str]]:
    """Parse RSS or Atom XML and return up to *max_items* entries."""
    root = ET.fromstring(xml_text)
    items: List[Dict[str, str]] = []

    # RSS 2.0: <rss><channel><item>
    for item_el in root.iter("item"):
        if len(items) >= max_items:
            break
        items.append(
            {
                "title": (item_el.findtext("title") or "").strip(),
                "description": (item_el.findtext("description") or "").strip()[:200],
                "link": (item_el.findtext("link") or "").strip(),
                "pubDate": (item_el.findtext("pubDate") or "").strip(),
            }
        )

    # Atom: <feed><entry>
    if not items:
        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "media": "http://search.yahoo.com/mrss/",
        }
        for entry_el in root.iter("{http://www.w3.org/2005/Atom}entry"):
            if len(items) >= max_items:
                break
            link_el = next(
                (link for link in entry_el.findall("atom:link", ns)
                 if link.get("rel", "alternate") == "alternate"),
                None,
            )
            link_href = link_el.get("href", "") if link_el is not None else ""
            title = (entry_el.findtext("atom:title", namespaces=ns) or "").strip()
            summary = (
                entry_el.findtext("atom:summary", namespaces=ns)
                or entry_el.findtext("media:group/media:description", namespaces=ns)
                or entry_el.findtext("atom:content", namespaces=ns)
                or ""
            )
            plain_text = unescape(re.sub(r"<[^<>]+>", " ", summary[:4096]))
            description = " ".join(plain_text.split()) or title
            published = (
                entry_el.findtext("atom:published", namespaces=ns)
                or entry_el.findtext("atom:updated", namespaces=ns)
                or ""
            )
            items.append(
                {
                    "title": title,
                    "description": description[:200],
                    "link": link_href.strip(),
                    "pubDate": published.strip(),
                }
            )

    return items


def _parse_pub_date(date_str: str) -> Optional[datetime]:
    """Best-effort parse of an RSS pubDate or Atom updated timestamp."""
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str)
    except (ValueError, TypeError):
        pass
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


@ConnectorRegistry.register("news_rss")
class NewsRSSConnector(BaseConnector):
    """Aggregate headlines from configured RSS/Atom feeds."""

    connector_id = "news_rss"
    display_name = "News / RSS"
    auth_type = "local"

    def __init__(self, *, config_path: str = _DEFAULT_CONFIG_PATH) -> None:
        self._config_path = Path(config_path)
        self._status = SyncStatus()

    def _load_config(self) -> List[Dict[str, str]]:
        """Load feed list from disk."""
        data = json.loads(self._config_path.read_text(encoding="utf-8"))
        return data.get("feeds", [])

    def configure(self, feeds: List[Dict[str, Any]]) -> None:
        """Validate and persist RSS feed configuration from the connect UI."""
        normalized: List[Dict[str, str]] = []
        for feed in feeds:
            if not isinstance(feed, dict):
                continue
            url = str(feed.get("url", "")).strip()
            _validate_feed_url(url)
            parsed = urlparse(url)
            name = str(feed.get("name", "")).strip() or parsed.netloc
            normalized.append({"name": name, "url": url})
        if not normalized:
            raise ValueError("At least one RSS feed URL is required")
        from openjarvis.security.file_utils import secure_write_json

        secure_write_json(self._config_path, {"feeds": normalized})

    def is_connected(self) -> bool:
        if not self._config_path.exists():
            return False
        try:
            feeds = self._load_config()
            return len(feeds) > 0
        except (json.JSONDecodeError, OSError):
            return False

    def disconnect(self) -> None:
        if self._config_path.exists():
            self._config_path.unlink()

    def sync(
        self, *, since: Optional[datetime] = None, cursor: Optional[str] = None
    ) -> Iterator[Document]:
        """Yield Documents for recent items across all configured feeds."""
        feeds = self._load_config()
        self._status.state = "syncing"
        self._status.error = None
        failures: list[str] = []
        cutoff = since
        if since is not None and since.tzinfo is None:
            cutoff = since.replace(tzinfo=timezone.utc)

        for feed in feeds:
            feed_name = feed.get("name", "Unknown Feed")
            feed_url = feed.get("url", "")
            if not feed_url:
                continue

            try:
                items = _parse_rss_items(_fetch_feed(feed_url))
            except httpx.HTTPStatusError as exc:
                failures.append(f"{feed_name}: HTTP {exc.response.status_code}")
                continue
            except httpx.RequestError as exc:
                reason = (
                    "TLS certificate verification failed"
                    if isinstance(exc.__cause__, ssl.SSLCertVerificationError)
                    else "connection failed"
                )
                failures.append(f"{feed_name}: {reason}")
                continue
            except (ET.ParseError, ValueError) as exc:
                reason = "invalid XML" if isinstance(exc, ET.ParseError) else str(exc)
                failures.append(f"{feed_name}: {reason}")
                continue

            for item in items:
                pub_dt = _parse_pub_date(item["pubDate"])
                if pub_dt is not None and pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)

                # Filter by since if the date is parseable
                if cutoff is not None and pub_dt is not None and pub_dt < cutoff:
                    continue

                title = item["title"] or "Untitled"
                doc_id = f"rss-{feed_name}-{title[:40]}"

                yield Document(
                    doc_id=doc_id,
                    source="news_rss",
                    doc_type="article",
                    content=item["description"],
                    title=title,
                    timestamp=pub_dt or datetime.now(),
                    url=item["link"] or None,
                    metadata={"feed_name": feed_name},
                )

        if failures:
            self._status.state = "error"
            self._status.error = "RSS sync incomplete. " + "; ".join(failures)
        else:
            self._status.state = "idle"
            self._status.last_sync = datetime.now(timezone.utc)

    def sync_status(self) -> SyncStatus:
        return self._status
