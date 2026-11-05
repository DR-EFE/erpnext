"""Optional negative checks against the running local ERPNext demo site."""

import os
import tempfile
from dataclasses import replace
from pathlib import Path

from hikcentral_bridge.bridge import Bridge, BridgeError, Config, FrappeClient, Ledger


def main():
	config = Config.load(Path(__file__).resolve().parents[1] / "config.example.json")
	with tempfile.TemporaryDirectory() as directory:
		ledger = Ledger(Path(directory) / "negative.sqlite3")
		try:
			base = {
				"employee_no": "HIK-DEMO-CDMX",
				"site_code": "CDMX",
				"occurred_at": "2026-11-02T09:00:00-06:00",
				"device_id": "HIK-NEGATIVE-TEST",
				"direction": "IN",
			}
			cases = [
				(
					"unknown employee",
					{**base, "source_event_id": "negative-employee", "employee_no": "NO-SUCH-EMPLOYEE"},
					FrappeClient(config),
					"failed",
				),
				(
					"invalid direction",
					{**base, "source_event_id": "negative-direction", "direction": "AUTO"},
					FrappeClient(config),
					"invalid",
				),
			]
			for label, event, client, expected in cases:
				try:
					Bridge(config, ledger, client).replay_one(event)
				except BridgeError as exc:
					assert ledger.get(event["source_event_id"])[1] == expected
					print(f"{label}: {expected} ({exc})")
				else:
					raise AssertionError(f"{label} unexpectedly succeeded")

			original_key = os.environ["ERPNEXT_API_KEY"]
			original_secret = os.environ["ERPNEXT_API_SECRET"]
			os.environ["ERPNEXT_API_KEY"] = "invalid-key"
			os.environ["ERPNEXT_API_SECRET"] = "invalid-secret"
			try:
				bad_client = FrappeClient(config)
			finally:
				os.environ["ERPNEXT_API_KEY"] = original_key
				os.environ["ERPNEXT_API_SECRET"] = original_secret
			for label, event, client in [
				("bad credentials", {**base, "source_event_id": "negative-auth"}, bad_client),
				(
					"network outage",
					{**base, "source_event_id": "negative-network"},
					FrappeClient(replace(config, erpnext_url="http://127.0.0.1:8999")),
				),
			]:
				try:
					Bridge(config, ledger, client).replay_one(event)
				except BridgeError as exc:
					assert ledger.get(event["source_event_id"])[1] == "failed"
					print(f"{label}: failed ({exc})")
				else:
					raise AssertionError(f"{label} unexpectedly succeeded")
		finally:
			ledger.close()


if __name__ == "__main__":
	main()
