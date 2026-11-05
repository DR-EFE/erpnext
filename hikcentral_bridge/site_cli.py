"""Run local demo site operations using the Bench Python environment."""

import argparse
import json
import os
from pathlib import Path

import frappe

from . import demo_site
from .bridge import Config, Ledger

BENCH_DIR = "/home/pipe6/frappe/hikcentral-bench"
SITE = "hikcentral.localhost"


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("command", choices=("seed", "finalize", "verify", "inspect", "reset-attempt"))
	args = parser.parse_args()
	os.chdir(os.path.join(BENCH_DIR, "sites"))
	frappe.init(site=SITE)
	frappe.connect()
	frappe.set_user("Administrator")
	try:
		if args.command == "seed":
			demo_site.seed()
		elif args.command == "finalize":
			demo_site.finalize()
		elif args.command == "inspect":
			demo_site.inspect()
		elif args.command == "reset-attempt":
			demo_site.reset_attempt()
			root = Path(__file__).parent
			config = Config.load(root / "config.example.json")
			ledger = Ledger(config.ledger_path)
			try:
				events = json.loads((root / "fixtures" / "demo_events.json").read_text(encoding="utf-8"))
				ledger.forget([event["source_event_id"] for event in events])
			finally:
				ledger.close()
		else:
			demo_site.verify()
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		raise
	finally:
		frappe.destroy()
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
