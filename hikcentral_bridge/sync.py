"""Pull raw source events and deliver them through the existing Frappe bridge."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .bridge import Bridge, BridgeError, Config, FrappeClient, Ledger
from .source import EventSource, map_hikcentral_event

ENV_DIR = Path.home() / ".config" / "hikcentral_bridge"


def load_env_file(path: Path):
	"""Read simple KEY=VALUE files without executing shell code."""
	if not path.exists():
		return
	for line in path.read_text(encoding="utf-8").splitlines():
		line = line.strip()
		if not line or line.startswith("#"):
			continue
		if line.startswith("export "):
			line = line[7:].strip()
		key, sep, value = line.partition("=")
		if not sep or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
			raise BridgeError(f"invalid environment line in {path.name}")
		value = value.strip()
		if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
			value = value[1:-1]
		os.environ.setdefault(key, value)


def load_local_env():
	load_env_file(ENV_DIR / "erpnext.env")
	load_env_file(ENV_DIR / "hikcentral.env")


def sync_once(source: EventSource, config: Config, client: Any | None = None) -> list[dict[str, str]]:
	"""Read all source events; the ledger makes repeated polling idempotent."""
	client = client or FrappeClient(config)
	ledger = Ledger(config.ledger_path)
	results: list[dict[str, str]] = []
	try:
		bridge = Bridge(config, ledger, client)
		for raw in source.list_events():
			event_id = raw.get("eventId") if isinstance(raw, dict) else None
			try:
				event = map_hikcentral_event(raw, config)
			except BridgeError as exc:
				if isinstance(raw, dict):
					ledger.record_source_issue(raw, str(exc))
				results.append({"event_id": str(event_id), "status": "invalid", "error": str(exc)})
				continue
			try:
				results.append(bridge.replay_one(event))
			except BridgeError as exc:
				results.append({"event_id": str(event_id), "status": "failed", "error": str(exc)})
	finally:
		ledger.close()
	return results
