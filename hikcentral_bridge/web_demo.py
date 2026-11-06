"""Local-only punch page and periodic synchronization worker."""

from __future__ import annotations

import html
import secrets
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from .bridge import BridgeError, Config, FrappeClient, Ledger
from .source import DemoSource
from .sync import sync_once

PAGE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Marcaje de asistencia · Demo HikCentral</title>
<style>
:root{font-family:system-ui,sans-serif;color:#1d2939;background:#f2f5f8}*{box-sizing:border-box}
body{margin:0;padding:32px 16px}.shell{max-width:900px;margin:auto}h1{font-size:2rem;margin:0 0 8px}
p{line-height:1.5;color:#475467}.note{background:#e6f3ff;border-left:4px solid #2176bd;padding:12px 16px;border-radius:6px}
.card{background:#fff;border:1px solid #d7dfe7;border-radius:12px;padding:22px;margin-top:20px;box-shadow:0 3px 12px #1822300c}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}label{display:block;font-weight:600;font-size:.9rem}
select,input{width:100%;margin-top:7px;padding:12px;border:1px solid #98a2b3;border-radius:8px;background:white;font:inherit}
.actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:20px}button{border:0;border-radius:8px;background:#145ea8;color:white;padding:12px 18px;font:inherit;font-weight:600;cursor:pointer}
button.secondary{background:#344054}table{width:100%;border-collapse:collapse;font-size:.9rem}td,th{text-align:left;padding:10px;border-bottom:1px solid #e4e7ec;word-break:break-word}
.tablewrap{overflow:auto}.error{color:#b42318}.ok{color:#027a48}.muted{color:#667085}@media(max-width:650px){.grid{grid-template-columns:1fr}}
</style></head><body><main class="shell"><h1>Marcaje de asistencia</h1>
<p class="note">Demo local: esta página crea eventos simulados. No registra marcajes dentro de HikCentral.</p>
<p>El sincronizador consulta estos eventos cada 10 segundos y crea los Employee Checkin en ERPNext. Después del cierre del turno, Frappe HR genera Attendance.</p>
<section class="card"><h2>Nuevo marcaje</h2><form method="post" action="/mark">
<input type="hidden" name="csrf" value="__TOKEN__"><div class="grid">
<label>Empleado y sede<select name="employee" required>__EMPLOYEES__</select></label>
<label>Tipo de marcaje<select name="direction"><option value="IN">Entrada</option><option value="OUT">Salida</option></select></label>
<label>Fecha y hora local<input name="local_time" type="datetime-local" value="__NOW__" required></label>
</div><div class="actions"><button type="submit">Guardar marcaje</button></div></form></section>
<section class="card"><h2>Sincronización</h2><p>__MESSAGE__</p>
<form method="post" action="/sync"><input type="hidden" name="csrf" value="__TOKEN__"><button class="secondary" type="submit">Sincronizar ahora</button></form>
<div class="tablewrap"><table><thead><tr><th>Evento</th><th>Empleado</th><th>Hora</th><th>Estado</th><th>Checkin / error</th></tr></thead>
<tbody>__ROWS__</tbody></table></div></section></main></body></html>"""


class DemoApp:
	def __init__(self, config: Config):
		self.config = config
		self.source = DemoSource(config.ledger_path)
		self.client = FrappeClient(config)
		self.token = secrets.token_urlsafe(32)
		self.lock = threading.Lock()
		self.last_error = ""
		self.stop = threading.Event()

	def sync(self):
		with self.lock:
			try:
				result = sync_once(self.source, self.config, self.client)
				self.last_error = ""
				return result
			except BridgeError as exc:
				self.last_error = str(exc)
				return []

	def background_sync(self):
		while not self.stop.wait(10):
			self.sync()

	def render(self, message: str = "") -> bytes:
		ledger = Ledger(self.config.ledger_path)
		try:
			statuses = {row["event_id"]: row for row in ledger.recent_statuses(100)}
		finally:
			ledger.close()
		rows = []
		for event in reversed(self.source.list_events()[-30:]):
			status = statuses.get(event["eventId"], {})
			state = status.get("status", "pendiente")
			detail = status.get("checkin_name") or status.get("error") or ""
			rows.append(
				"<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
					*(html.escape(str(value)) for value in (event["eventId"], event["personCode"], event["checkTime"], state, detail))
				)
			)
		choices = "".join(
			f'<option value="{html.escape(code)}|{html.escape(site)}">{html.escape(code)} · {html.escape(site)}</option>'
			for code, site in self.config.demo_employees
		)
		now = datetime.now(ZoneInfo(self.config.site_timezone)).strftime("%Y-%m-%dT%H:%M")
		page = (
			PAGE.replace("__TOKEN__", html.escape(self.token))
			.replace("__EMPLOYEES__", choices)
			.replace("__NOW__", now)
			.replace("__MESSAGE__", html.escape(message or self.last_error or "Esperando marcajes."))
			.replace("__ROWS__", "".join(rows) or '<tr><td colspan="5" class="muted">Aún no hay marcajes.</td></tr>')
		)
		return page.encode("utf-8")


def serve(config: Config, port: int = 8765):
	app = DemoApp(config)

	class Handler(BaseHTTPRequestHandler):
		def _send(self, code: int, body: bytes, content_type: str = "text/html; charset=utf-8"):
			self.send_response(code)
			self.send_header("Content-Type", content_type)
			self.send_header("Content-Length", str(len(body)))
			self.send_header("Cache-Control", "no-store")
			self.send_header("X-Content-Type-Options", "nosniff")
			self.end_headers()
			self.wfile.write(body)

		def _local_host(self) -> bool:
			return self.headers.get("Host") in {f"localhost:{port}", f"127.0.0.1:{port}"}

		def do_GET(self):
			if not self._local_host():
				self._send(403, b"Host denied", "text/plain")
				return
			if urlsplit(self.path).path != "/":
				self._send(404, b"Not found", "text/plain")
				return
			self._send(200, app.render())

		def do_POST(self):
			if not self._local_host() or urlsplit(self.path).path not in ("/mark", "/sync"):
				self._send(403, b"Denied", "text/plain")
				return
			origin = self.headers.get("Origin")
			if origin and origin not in {f"http://localhost:{port}", f"http://127.0.0.1:{port}"}:
				self._send(403, b"Origin denied", "text/plain")
				return
			if self.headers.get("Content-Type", "").split(";")[0] != "application/x-www-form-urlencoded":
				self._send(415, b"Unsupported content type", "text/plain")
				return
			try:
				length = int(self.headers.get("Content-Length", "0"))
				if length < 1 or length > 4096:
					raise ValueError()
				fields = parse_qs(self.rfile.read(length).decode("utf-8"), max_num_fields=10)
			except (ValueError, UnicodeDecodeError):
				self._send(400, b"Invalid form", "text/plain")
				return
			if not secrets.compare_digest(fields.get("csrf", [""])[0], app.token):
				self._send(403, b"Invalid form token", "text/plain")
				return
			try:
				if self.path == "/mark":
					code, site = fields.get("employee", [""])[0].split("|", 1)
					app.source.create(code, site, fields.get("direction", [""])[0], fields.get("local_time", [""])[0], config)
					message = "Marcaje guardado; se sincronizará automáticamente."
				else:
					results = app.sync()
					message = f"Sincronización terminada: {sum(r['status'] == 'sent' for r in results)} enviados, {sum(r['status'] == 'failed' for r in results)} fallidos."
			except (BridgeError, ValueError) as exc:
				self._send(400, app.render(str(exc)))
				return
			self._send(200, app.render(message))

	server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
	worker = threading.Thread(target=app.background_sync, daemon=True)
	worker.start()
	print(f"Demo local: http://localhost:{port}", flush=True)
	try:
		server.serve_forever()
	finally:
		app.stop.set()
		server.server_close()
