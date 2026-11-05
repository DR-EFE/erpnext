import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from hikcentral_bridge.bridge import Bridge, BridgeError, Config, FrappeClient, Ledger, normalize_event


class FakeClient:
	def __init__(self, failure=None):
		self.calls = []
		self.failure = failure

	def create_checkin(self, payload):
		self.calls.append(payload)
		if self.failure:
			raise BridgeError(self.failure)
		return f"CHK-{len(self.calls)}"


class BridgeTests(unittest.TestCase):
	def setUp(self):
		self.temp = tempfile.TemporaryDirectory()
		self.config = Config(
			erpnext_url="http://localhost:8000",
			site_timezone="America/Mexico_City",
			site_zones={"CDMX": "America/Mexico_City", "OAX": "America/Mexico_City"},
			ledger_path=Path(self.temp.name) / "events.sqlite3",
		)
		self.ledger = Ledger(self.config.ledger_path)
		self.event = {
			"source_event_id": "event-1",
			"employee_no": "HIK-DEMO-CDMX",
			"site_code": "CDMX",
			"occurred_at": "2026-11-02T15:00:00Z",
			"device_id": "door-1",
			"direction": "IN",
		}

	def tearDown(self):
		self.ledger.close()
		self.temp.cleanup()

	def test_converts_utc_to_site_time_and_uses_documented_fields(self):
		payload, _ = normalize_event(self.event, self.config)
		self.assertEqual(
			payload,
			{
				"employee_field_value": "HIK-DEMO-CDMX",
				"timestamp": "2026-11-02 09:00:00.000000",
				"device_id": "door-1",
				"log_type": "IN",
			},
		)

	def test_replay_skips_sent_source_event(self):
		client = FakeClient()
		bridge = Bridge(self.config, self.ledger, client)
		self.assertEqual(bridge.replay_one(self.event)["status"], "sent")
		self.assertEqual(bridge.replay_one(self.event)["status"], "skipped")
		self.assertEqual(len(client.calls), 1)
		self.assertEqual(self.ledger.get("event-1")[2], "CHK-1")

	def test_failed_delivery_is_saved_and_can_retry(self):
		client = FakeClient("ERPNext HTTP 404")
		bridge = Bridge(self.config, self.ledger, client)
		with self.assertRaisesRegex(BridgeError, "HTTP 404"):
			bridge.replay_one(self.event)
		self.assertEqual(self.ledger.get("event-1")[1], "failed")
		client.failure = None
		self.assertEqual(bridge.replay_one(self.event)["status"], "sent")

	def test_rejects_changed_source_event_id(self):
		bridge = Bridge(self.config, self.ledger, FakeClient())
		bridge.replay_one(self.event)
		changed = {**self.event, "occurred_at": "2026-11-02T16:00:00Z"}
		with self.assertRaisesRegex(BridgeError, "changed its content"):
			bridge.replay_one(changed)

	def test_invalid_direction_is_recorded(self):
		bridge = Bridge(self.config, self.ledger, FakeClient())
		with self.assertRaisesRegex(BridgeError, "direction"):
			bridge.replay_one({**self.event, "direction": "AUTO"})
		self.assertEqual(self.ledger.get("event-1")[1], "invalid")

	def test_unknown_employee_response_is_saved(self):
		client = FakeClient("ERPNext HTTP 417: No Employee found")
		with self.assertRaisesRegex(BridgeError, "No Employee"):
			Bridge(self.config, self.ledger, client).replay_one(self.event)
		self.assertEqual(self.ledger.get("event-1")[1], "failed")

	def test_http_client_authenticates_and_requires_checkin_name(self):
		with patch.dict("os.environ", {"ERPNEXT_API_KEY": "demo-key", "ERPNEXT_API_SECRET": "demo-secret"}):
			client = FrappeClient(self.config)
			with patch(
				"urllib.request.urlopen", return_value=io.BytesIO(b'{"message":{"name":"CHK-001"}}')
			) as call:
				self.assertEqual(client.create_checkin({"employee_field_value": "HIK-DEMO-CDMX"}), "CHK-001")
				request = call.call_args.args[0]
				self.assertEqual(request.get_header("Authorization"), "token demo-key:demo-secret")
				self.assertEqual(request.get_method(), "POST")
			with patch("urllib.request.urlopen", return_value=io.BytesIO(b'{"message":{}}')):
				with self.assertRaisesRegex(BridgeError, "no Employee Checkin name"):
					client.create_checkin({})

	def test_http_client_reports_auth_and_network_failures(self):
		with patch.dict("os.environ", {"ERPNEXT_API_KEY": "bad", "ERPNEXT_API_SECRET": "bad"}):
			client = FrappeClient(self.config)
			with patch(
				"urllib.request.urlopen", side_effect=HTTPError(client.url, 403, "Forbidden", {}, None)
			):
				with self.assertRaisesRegex(BridgeError, "HTTP 403"):
					client.create_checkin({})
			with patch("urllib.request.urlopen", side_effect=URLError("connection refused")):
				with self.assertRaisesRegex(BridgeError, "connection failed"):
					client.create_checkin({})

	def test_fixture_has_four_distinct_events(self):
		fixture = Path(__file__).resolve().parents[1] / "fixtures" / "demo_events.json"
		events = json.loads(fixture.read_text(encoding="utf-8"))
		self.assertEqual(len(events), 4)
		self.assertEqual(len({e["source_event_id"] for e in events}), 4)
		for event in events:
			normalize_event(event, self.config)


if __name__ == "__main__":
	unittest.main()
