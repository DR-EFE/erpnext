"""Replay original punch events into Frappe HR Employee Checkin."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CHECKIN_METHOD = (
	"/api/method/hrms.hr.doctype.employee_checkin.employee_checkin.add_log_based_on_employee_field"
)


class BridgeError(Exception):
	"""An event could not be validated or delivered."""


def event_fingerprint(event: dict[str, Any]) -> str:
	return hashlib.sha256(
		json.dumps(event, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
	).hexdigest()


@dataclass(frozen=True)
class Config:
	erpnext_url: str
	site_timezone: str
	site_zones: dict[str, str]
	ledger_path: Path

	@classmethod
	def load(cls, path: Path) -> Config:
		data = json.loads(path.read_text(encoding="utf-8"))
		return cls(
			erpnext_url=data["erpnext_url"].rstrip("/"),
			site_timezone=data["site_timezone"],
			site_zones=data["site_zones"],
			ledger_path=Path(data["ledger_path"]).expanduser(),
		)


def normalize_event(event: dict[str, Any], config: Config) -> tuple[dict[str, str], str]:
	"""Return Frappe payload and a stable fingerprint of the source record."""
	for field in ("source_event_id", "employee_no", "site_code", "occurred_at", "device_id"):
		if not isinstance(event.get(field), str) or not event[field].strip():
			raise BridgeError(f"{field} must be a non-empty string")
	if event["site_code"] not in config.site_zones:
		raise BridgeError(f"unknown site_code: {event['site_code']}")
	try:
		source_zone = ZoneInfo(config.site_zones[event["site_code"]])
		site_zone = ZoneInfo(config.site_timezone)
		occurred = datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00"))
	except (ValueError, ZoneInfoNotFoundError) as exc:
		raise BridgeError(f"invalid occurred_at or timezone: {exc}") from exc
	if occurred.tzinfo is None:
		occurred = occurred.replace(tzinfo=source_zone)
	local_time = occurred.astimezone(site_zone)
	if local_time.utcoffset() is None:
		raise BridgeError("timestamp has no valid UTC offset")
	direction = event.get("direction")
	if direction not in (None, "IN", "OUT"):
		raise BridgeError("direction must be IN, OUT, or null")
	payload = {
		"employee_field_value": event["employee_no"],
		"timestamp": local_time.strftime("%Y-%m-%d %H:%M:%S.%f"),
		"device_id": event["device_id"],
	}
	if direction:
		payload["log_type"] = direction
	return payload, event_fingerprint(event)


class Ledger:
	def __init__(self, path: Path):
		path.parent.mkdir(parents=True, exist_ok=True)
		self.db = sqlite3.connect(path)
		self.db.execute(
			"""CREATE TABLE IF NOT EXISTS events (
				source_event_id TEXT PRIMARY KEY,
				fingerprint TEXT NOT NULL,
				employee_no TEXT NOT NULL,
				site_code TEXT NOT NULL,
				occurred_at TEXT NOT NULL,
				status TEXT NOT NULL,
				checkin_name TEXT,
				error TEXT,
				updated_at TEXT NOT NULL
			)"""
		)
		self.db.commit()

	def get(self, event_id: str) -> tuple[str, str, str | None] | None:
		return self.db.execute(
			"SELECT fingerprint, status, checkin_name FROM events WHERE source_event_id = ?", (event_id,)
		).fetchone()

	def record(
		self, event: dict[str, Any], fingerprint: str, status: str, name: str | None, error: str | None
	):
		self.db.execute(
			"""INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
			ON CONFLICT(source_event_id) DO UPDATE SET
				status=excluded.status, checkin_name=excluded.checkin_name,
				error=excluded.error, updated_at=excluded.updated_at""",
			(
				event["source_event_id"],
				fingerprint,
				event["employee_no"],
				event["site_code"],
				event["occurred_at"],
				status,
				name,
				error,
				datetime.now(timezone.utc).isoformat(),
			),
		)
		self.db.commit()

	def close(self):
		self.db.close()

	def forget(self, event_ids: list[str]):
		self.db.executemany(
			"DELETE FROM events WHERE source_event_id = ?", [(event_id,) for event_id in event_ids]
		)
		self.db.commit()


class FrappeClient:
	def __init__(self, config: Config):
		key = os.environ.get("ERPNEXT_API_KEY")
		secret = os.environ.get("ERPNEXT_API_SECRET")
		if not key or not secret:
			raise BridgeError("set ERPNEXT_API_KEY and ERPNEXT_API_SECRET in the environment")
		self.url = config.erpnext_url + CHECKIN_METHOD
		self.authorization = f"token {key}:{secret}"

	def create_checkin(self, payload: dict[str, str]) -> str:
		request = urllib.request.Request(
			self.url,
			data=json.dumps(payload).encode("utf-8"),
			headers={"Authorization": self.authorization, "Content-Type": "application/json"},
			method="POST",
		)
		try:
			with urllib.request.urlopen(request, timeout=15) as response:
				body = json.load(response)
		except urllib.error.HTTPError as exc:
			raise BridgeError(f"ERPNext HTTP {exc.code}") from exc
		except (urllib.error.URLError, TimeoutError) as exc:
			raise BridgeError(
				f"ERPNext connection failed: {exc.reason if hasattr(exc, 'reason') else exc}"
			) from exc
		except (ValueError, UnicodeDecodeError) as exc:
			raise BridgeError("ERPNext returned invalid JSON") from exc
		name = body.get("message", {}).get("name") if isinstance(body, dict) else None
		if not isinstance(name, str) or not name:
			raise BridgeError("ERPNext response has no Employee Checkin name")
		return name


class Bridge:
	def __init__(self, config: Config, ledger: Ledger, client: Any):
		self.config = config
		self.ledger = ledger
		self.client = client

	def replay_one(self, event: dict[str, Any]) -> dict[str, str]:
		if not isinstance(event, dict):
			raise BridgeError("each source event must be an object")
		event_id = event.get("source_event_id")
		fingerprint = event_fingerprint(event)
		previous = self.ledger.get(event_id) if isinstance(event_id, str) else None
		if previous:
			if previous[0] != fingerprint:
				raise BridgeError(f"source_event_id {event_id} changed its content")
			if previous[1] == "sent":
				return {"source_event_id": event_id, "status": "skipped", "checkin_name": previous[2] or ""}
		try:
			payload, _ = normalize_event(event, self.config)
		except BridgeError as exc:
			if all(
				isinstance(event.get(key), str) and event[key]
				for key in ("source_event_id", "employee_no", "site_code", "occurred_at")
			):
				self.ledger.record(event, fingerprint, "invalid", None, str(exc))
			raise
		try:
			name = self.client.create_checkin(payload)
		except BridgeError as exc:
			self.ledger.record(event, fingerprint, "failed", None, str(exc))
			raise
		self.ledger.record(event, fingerprint, "sent", name, None)
		return {"source_event_id": event_id, "status": "sent", "checkin_name": name}
