"""Run local demo site operations using the Bench Python environment."""

import argparse
import json
import os
from pathlib import Path

import frappe

from . import demo_site
from .bridge import Config, Ledger
from .source import DemoSource

BENCH_DIR = "/home/pipe6/frappe/hikcentral-bench"
SITE = "hikcentral.localhost"


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("command", choices=("seed", "finalize", "verify", "inspect", "reset-attempt"))
	parser.add_argument("--date", default=demo_site.DAY, help="YYYY-MM-DD for finalize/verify")
	args = parser.parse_args()
	os.chdir(os.path.join(BENCH_DIR, "sites"))
	frappe.init(site=SITE)
	frappe.connect()
	frappe.set_user("Administrator")
	try:
		if args.command == "seed":
			demo_site.seed()
		elif args.command == "finalize":
			demo_site.finalize(args.date)
		elif args.command == "inspect":
			demo_site.inspect()
		elif args.command == "reset-attempt":
			demo_site.reset_attempt(args.date)
			root = Path(__file__).parent
			config = Config.load(root / "config.example.json")
			ledger = Ledger(config.ledger_path)
			try:
				events = json.loads((root / "fixtures" / "demo_events.json").read_text(encoding="utf-8"))
				fixture_ids = [event["source_event_id"] for event in events if event["occurred_at"].startswith(args.date)]
				page_ids = DemoSource(config.ledger_path).delete_day(args.date)
				ledger.forget(fixture_ids + page_ids)
			finally:
				ledger.close()
		else:
			demo_site.verify(args.date)
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		raise
	finally:
		frappe.destroy()
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
