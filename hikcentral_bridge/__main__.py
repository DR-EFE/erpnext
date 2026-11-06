"""Command line replay for the HikCentral demo bridge."""

import argparse
import json
import sys
from pathlib import Path

from .bridge import Bridge, BridgeError, Config, FrappeClient, Ledger
from .hikcentral_client import HikCentralClient
from .source import DemoSource
from .sync import load_local_env, sync_once
from .web_demo import serve


def replay_main(argv: list[str]) -> int:
	parser = argparse.ArgumentParser(description="Replay HikCentral punch records into Frappe HR")
	parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.example.json"))
	parser.add_argument("events", type=Path, help="JSON array of original punch records")
	args = parser.parse_args(argv)
	load_local_env()
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


def main() -> int:
	argv = sys.argv[1:]
	if not argv or argv[0] not in ("serve", "sync", "probe"):
		return replay_main(argv)
	parser = argparse.ArgumentParser(description="Run the local punch page or synchronization")
	parser.add_argument("command", choices=("serve", "sync", "probe"))
	parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.example.json"))
	parser.add_argument("--port", type=int, default=8765)
	args = parser.parse_args(argv)
	load_local_env()
	if args.command == "probe":
		response = HikCentralClient().probe_version()
		print(json.dumps({"code": response["code"], "data": response.get("data")}, ensure_ascii=False))
		return 0
	config = Config.load(args.config)
	if args.command == "serve":
		serve(config, args.port)
		return 0
	results = sync_once(DemoSource(config.ledger_path), config)
	for result in results:
		print(json.dumps(result, ensure_ascii=False))
	return 1 if any(result["status"] in ("failed", "invalid") for result in results) else 0


if __name__ == "__main__":
	raise SystemExit(main())
