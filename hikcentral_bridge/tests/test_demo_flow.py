import base64
import hashlib
import hmac
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from hikcentral_bridge.bridge import BridgeError, Config
from hikcentral_bridge.hikcentral_client import HikCentralClient, HikCentralSource, signed_headers
from hikcentral_bridge.source import DemoSource, map_hikcentral_event
from hikcentral_bridge.sync import sync_once


class FakeFrappe:
	def __init__(self):
		self.calls = []
		self.failure = None

	def create_checkin(self, payload):
		self.calls.append(payload)
		if self.failure:
			raise BridgeError(self.failure)
		return f"CHK-{len(self.calls)}"


class DemoFlowTests(unittest.TestCase):
	def setUp(self):
		self.temp = tempfile.TemporaryDirectory()
		self.config = Config(
			"http://localhost:8000",
			"America/Mexico_City",
			{"CDMX": "America/Mexico_City", "OAX": "America/Mexico_City"},
			Path(self.temp.name) / "events.sqlite3",
		)
		self.source = DemoSource(self.config.ledger_path)

	def tearDown(self):
		self.temp.cleanup()

	def test_page_source_to_checkin_and_repeat_poll(self):
		for code, site in self.config.demo_employees:
			self.source.create(code, site, "IN", "2026-11-05T09:00", self.config)
			self.source.create(code, site, "OUT", "2026-11-05T18:00", self.config)
		client = FakeFrappe()
		first = sync_once(self.source, self.config, client)
		second = sync_once(self.source, self.config, client)
		self.assertEqual([row["status"] for row in first], ["sent"] * 4)
		self.assertEqual([row["status"] for row in second], ["skipped"] * 4)
		self.assertEqual(len(client.calls), 4)
		self.assertEqual({call["employee_field_value"] for call in client.calls}, {"HIK-DEMO-CDMX", "HIK-DEMO-OAX"})
		self.assertEqual({call["log_type"] for call in client.calls}, {"IN", "OUT"})

	def test_failed_delivery_retries_and_unsupported_type_is_recorded(self):
		self.source.create("HIK-DEMO-CDMX", "CDMX", "IN", "2026-11-05T09:00", self.config)
		client = FakeFrappe()
		client.failure = "ERPNext HTTP 500"
		self.assertEqual(sync_once(self.source, self.config, client)[0]["status"], "failed")
		client.failure = None
		self.assertEqual(sync_once(self.source, self.config, client)[0]["status"], "sent")
		raw = self.source.list_events()[0]
		with self.assertRaisesRegex(BridgeError, "unsupported checkInAndOutType"):
			map_hikcentral_event({**raw, "checkInAndOutType": 3}, self.config)

	def test_person_id_mapping_and_validation(self):
		raw = self.source.create("HIK-DEMO-CDMX", "CDMX", "IN", "2026-11-05T09:00", self.config)
		config = Config(
			self.config.erpnext_url,
			self.config.site_timezone,
			self.config.site_zones,
			self.config.ledger_path,
			person_map={"HCP-123": "HIK-DEMO-CDMX"},
			device_sites={"reader-123": "CDMX"},
		)
		mapped = map_hikcentral_event({**raw, "personCode": "other", "personId": "HCP-123", "siteCode": "", "deviceId": "reader-123"}, config)
		self.assertEqual(mapped["employee_no"], "HIK-DEMO-CDMX")
		self.assertEqual(mapped["site_code"], "CDMX")
		with self.assertRaisesRegex(BridgeError, "mapping"):
			map_hikcentral_event({**raw, "personCode": "", "personId": "missing"}, config)

	def test_form_rejects_unknown_employee_and_direction(self):
		with self.assertRaisesRegex(BridgeError, "employee and site"):
			self.source.create("unknown", "CDMX", "IN", "2026-11-05T09:00", self.config)
		with self.assertRaisesRegex(BridgeError, "direction"):
			self.source.create("HIK-DEMO-CDMX", "CDMX", "BREAK", "2026-11-05T09:00", self.config)

	def test_reset_source_deletes_only_selected_day(self):
		first = self.source.create("HIK-DEMO-CDMX", "CDMX", "IN", "2026-11-05T09:00", self.config)
		second = self.source.create("HIK-DEMO-CDMX", "CDMX", "IN", "2026-11-06T09:00", self.config)
		self.assertEqual(self.source.delete_day("2026-11-05"), [first["eventId"]])
		self.assertEqual([event["eventId"] for event in self.source.list_events()], [second["eventId"]])


class HikCentralTransportTests(unittest.TestCase):
	def test_signature_uses_nonce_timestamp_and_path(self):
		path = "/artemis/api/common/v1/version"
		headers = signed_headers(path, "key", "secret", nonce="nonce-1", timestamp="123")
		message = f"POST\n*/*\napplication/json\nx-ca-key:key\nx-ca-nonce:nonce-1\nx-ca-timestamp:123\n{path}"
		expected = base64.b64encode(hmac.new(b"secret", message.encode(), hashlib.sha256).digest()).decode()
		self.assertEqual(headers["X-Ca-Signature"], expected)
		self.assertEqual(headers["X-Ca-Signature-Headers"], "x-ca-key,x-ca-nonce,x-ca-timestamp")

	def test_tls_validation_cannot_be_disabled(self):
		with patch.dict("os.environ", {
			"HIKCENTRAL_BASE_URL": "https://127.0.0.1",
			"HIKCENTRAL_USER_KEY": "key",
			"HIKCENTRAL_APP_SECRET": "secret",
			"HIKCENTRAL_VERIFY_TLS": "false",
		}):
			with self.assertRaisesRegex(BridgeError, "TLS verification"):
				HikCentralClient()

	def test_hikcentral_auth_failure_is_reported_without_secrets(self):
		with patch.dict("os.environ", {
			"HIKCENTRAL_BASE_URL": "https://127.0.0.1",
			"HIKCENTRAL_USER_KEY": "key",
			"HIKCENTRAL_APP_SECRET": "secret",
			"HIKCENTRAL_VERIFY_TLS": "true",
		}):
			client = HikCentralClient()
			with patch("urllib.request.urlopen", side_effect=HTTPError(client.base_url, 401, "Unauthorized", {}, None)):
				with self.assertRaisesRegex(BridgeError, "HikCentral HTTP 401") as caught:
					client.probe_version()
				self.assertNotIn("secret", str(caught.exception))

	def test_real_source_paginates_with_version_specific_adapters(self):
		class FakeHik:
			def post_json(self, path, body):
				return {"code": "0", "data": {"items": [{"eventId": str(body["pageNo"])}], "more": body["pageNo"] == 1}}

		source = HikCentralSource(
			FakeHik(), "/artemis/api/acs/v1/door/events",
			lambda page: {"pageNo": page},
			lambda response: (response["data"]["items"], response["data"]["more"]),
		)
		self.assertEqual([event["eventId"] for event in source.list_events()], ["1", "2"])


if __name__ == "__main__":
	unittest.main()
