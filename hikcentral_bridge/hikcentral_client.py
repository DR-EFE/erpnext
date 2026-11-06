"""Signed OpenAPI transport; raw-event request schema awaits the matching 2.6.3 guide."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import ssl
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from typing import Any

from .bridge import BridgeError

VERSION_PATH = "/artemis/api/common/v1/version"


def signed_headers(path: str, key: str, secret: str, *, nonce: str | None = None, timestamp: str | None = None):
	if not path.startswith("/artemis/api/") or "?" in path or "#" in path:
		raise BridgeError("OpenAPI path must be an absolute Artemis API path")
	nonce = nonce or str(uuid.uuid4())
	timestamp = timestamp or str(time.time_ns() // 1_000_000)
	accept = "*/*"
	content_type = "application/json"
	string_to_sign = (
		f"POST\n{accept}\n{content_type}\n"
		f"x-ca-key:{key}\nx-ca-nonce:{nonce}\nx-ca-timestamp:{timestamp}\n{path}"
	)
	signature = base64.b64encode(
		hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).digest()
	).decode("ascii")
	return {
		"Accept": accept,
		"Content-Type": content_type,
		"X-Ca-Key": key,
		"X-Ca-Nonce": nonce,
		"X-Ca-Timestamp": timestamp,
		"X-Ca-Signature-Headers": "x-ca-key,x-ca-nonce,x-ca-timestamp",
		"X-Ca-Signature": signature,
	}


class HikCentralClient:
	def __init__(self, base_url: str | None = None):
		self.base_url = (base_url or os.environ.get("HIKCENTRAL_BASE_URL", "")).rstrip("/")
		self.key = os.environ.get("HIKCENTRAL_USER_KEY", "")
		self.secret = os.environ.get("HIKCENTRAL_APP_SECRET", "")
		if not self.base_url.startswith("https://") or not self.key or not self.secret:
			raise BridgeError("set HTTPS HIKCENTRAL_BASE_URL, HIKCENTRAL_USER_KEY and HIKCENTRAL_APP_SECRET")
		if os.environ.get("HIKCENTRAL_VERIFY_TLS", "true").lower() != "true":
			raise BridgeError("TLS verification must stay enabled; set HIKCENTRAL_CA_BUNDLE for local CA")
		ca_bundle = os.environ.get("HIKCENTRAL_CA_BUNDLE")
		self.context = ssl.create_default_context(cafile=ca_bundle if ca_bundle else None)

	def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
		request = urllib.request.Request(
			self.base_url + path,
			data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
			headers=signed_headers(path, self.key, self.secret),
			method="POST",
		)
		try:
			with urllib.request.urlopen(request, timeout=15, context=self.context) as response:
				body = json.load(response)
		except urllib.error.HTTPError as exc:
			raise BridgeError(f"HikCentral HTTP {exc.code}") from exc
		except (urllib.error.URLError, TimeoutError, ssl.SSLError) as exc:
			raise BridgeError(f"HikCentral connection/TLS failed: {exc}") from exc
		except (ValueError, UnicodeDecodeError) as exc:
			raise BridgeError("HikCentral returned invalid JSON") from exc
		if not isinstance(body, dict) or str(body.get("code")) != "0":
			raise BridgeError(f"HikCentral API error: {body.get('code') if isinstance(body, dict) else 'invalid body'}")
		return body

	def probe_version(self) -> dict[str, Any]:
		return self.post_json(VERSION_PATH, {})


class HikCentralSource:
	"""Real source with version-specific request/response adapters supplied after guide validation."""

	def __init__(
		self,
		client: HikCentralClient,
		path: str,
		request_page: Callable[[int], dict[str, Any]],
		parse_page: Callable[[dict[str, Any]], tuple[list[dict[str, Any]], bool]],
		max_pages: int = 1000,
	):
		self.client = client
		self.path = path
		self.request_page = request_page
		self.parse_page = parse_page
		self.max_pages = max_pages

	def list_events(self) -> list[dict[str, Any]]:
		all_events: list[dict[str, Any]] = []
		for page in range(1, self.max_pages + 1):
			items, has_more = self.parse_page(self.client.post_json(self.path, self.request_page(page)))
			if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
				raise BridgeError("HikCentral event page is not a list of objects")
			all_events.extend(items)
			if not has_more:
				return all_events
		raise BridgeError("HikCentral pagination exceeded the configured page limit")
