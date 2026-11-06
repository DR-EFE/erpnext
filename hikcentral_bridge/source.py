"""Event sources and mapping from HikCentral-shaped records to bridge events."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .bridge import BridgeError, Config


class EventSource(Protocol):
	def list_events(self) -> list[dict[str, Any]]: ...


def map_hikcentral_event(raw: dict[str, Any], config: Config) -> dict[str, str]:
	"""Map one raw access record; never treat a calculated daily report as a punch."""
	if not isinstance(raw, dict):
		raise BridgeError("HikCentral event must be an object")
	event_id = raw.get("eventId")
	if not isinstance(event_id, str) or not event_id.strip():
		raise BridgeError("HikCentral eventId is required")
	device = raw.get("deviceId") or raw.get("readerIndexCode")
	if not isinstance(device, str) or not device.strip():
		raise BridgeError("HikCentral deviceId or readerIndexCode is required")
	site = raw.get("siteCode") or config.device_sites.get(device)
	if site not in config.site_zones:
		raise BridgeError(f"unknown HikCentral siteCode: {site}")
	code = config.person_map.get(str(raw.get("personId", ""))) or raw.get("personCode") or raw.get("employeeNo")
	if not isinstance(code, str) or not code.strip():
		raise BridgeError(f"no attendance_device_id mapping for eventId {event_id}")
	check_time = raw.get("checkTime")
	if not isinstance(check_time, str) or not check_time.strip():
		raise BridgeError("HikCentral checkTime is required")
	try:
		datetime.fromisoformat(check_time.replace("Z", "+00:00"))
	except ValueError as exc:
		raise BridgeError("HikCentral checkTime must be ISO 8601") from exc
	kind = raw.get("checkInAndOutType")
	if kind not in (1, 2, "1", "2"):
		raise BridgeError(f"unsupported checkInAndOutType: {kind}")
	return {
		"source_event_id": event_id,
		"employee_no": code,
		"site_code": site,
		"occurred_at": check_time,
		"device_id": device,
		"direction": "IN" if str(kind) == "1" else "OUT",
	}


class DemoSource:
	"""A persistent local source that imitates raw HikCentral records."""

	def __init__(self, path: Path):
		self.path = path
		path.parent.mkdir(parents=True, exist_ok=True)
		with self._connect() as db:
			db.execute(
				"""CREATE TABLE IF NOT EXISTS source_events (
					event_id TEXT PRIMARY KEY,
					raw_json TEXT NOT NULL,
					created_at TEXT NOT NULL
				)"""
			)

	def _connect(self) -> sqlite3.Connection:
		return sqlite3.connect(self.path, timeout=15)

	def create(self, employee_no: str, site_code: str, direction: str, local_time: str, config: Config):
		if (employee_no, site_code) not in config.demo_employees:
			raise BridgeError("employee and site must match a configured demo employee")
		if direction not in ("IN", "OUT"):
			raise BridgeError("direction must be IN or OUT")
		try:
			parsed = datetime.fromisoformat(local_time)
			if parsed.tzinfo is None:
				parsed = parsed.replace(tzinfo=ZoneInfo(config.site_zones[site_code]))
		except (ValueError, KeyError, ZoneInfoNotFoundError) as exc:
			raise BridgeError("invalid local punch time") from exc
		event = {
			"eventId": f"demo-{uuid.uuid4().hex}",
			"personId": employee_no,
			"personCode": employee_no,
			"siteCode": site_code,
			"checkTime": parsed.isoformat(timespec="seconds"),
			"checkInAndOutType": 1 if direction == "IN" else 2,
			"deviceId": f"HIK-{site_code}-01",
		}
		with self._connect() as db:
			db.execute(
				"INSERT INTO source_events VALUES (?, ?, ?)",
				(event["eventId"], json.dumps(event), datetime.now(timezone.utc).isoformat()),
			)
		return event

	def list_events(self) -> list[dict[str, Any]]:
		with self._connect() as db:
			rows = db.execute("SELECT raw_json FROM source_events ORDER BY created_at, event_id").fetchall()
		return [json.loads(row[0]) for row in rows]

	def event_ids_on_day(self, day: str) -> list[str]:
		return [event["eventId"] for event in self.list_events() if event["checkTime"].startswith(day)]

	def delete_day(self, day: str) -> list[str]:
		ids = self.event_ids_on_day(day)
		with self._connect() as db:
			db.executemany("DELETE FROM source_events WHERE event_id = ?", [(event_id,) for event_id in ids])
		return ids
