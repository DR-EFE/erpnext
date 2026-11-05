"""Command line replay for the HikCentral demo bridge."""

import argparse
import json
from pathlib import Path

from .bridge import Bridge, BridgeError, Config, FrappeClient, Ledger


def main() -> int:
	parser = argparse.ArgumentParser(description="Replay HikCentral punch records into Frappe HR")
	parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.example.json"))
	parser.add_argument("events", type=Path, help="JSON array of original punch records")
	args = parser.parse_args()
	config = Config.load(args.config)
	client = FrappeClient(config)
	ledger = Ledger(config.ledger_path)
	failed = 0
	try:
		events = json.loads(args.events.read_text(encoding="utf-8"))
		if not isinstance(events, list):
			raise BridgeError("events file must contain a JSON array")
		bridge = Bridge(config, ledger, client)
		for event in events:
			try:
				print(json.dumps(bridge.replay_one(event), ensure_ascii=False))
			except BridgeError as exc:
				failed += 1
				print(
					json.dumps(
						{
							"source_event_id": event.get("source_event_id")
							if isinstance(event, dict)
							else None,
							"status": "failed",
							"error": str(exc),
						},
						ensure_ascii=False,
					)
				)
	finally:
		ledger.close()
	return 1 if failed else 0


if __name__ == "__main__":
	raise SystemExit(main())
