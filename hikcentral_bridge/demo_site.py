"""Idempotent Frappe site setup and verification for the simulated demo.

Run through ``bench --site hikcentral.localhost execute`` with this repository on PYTHONPATH.
"""

from __future__ import annotations

from pathlib import Path
from datetime import date, datetime, timedelta

import frappe

COMPANY = "HikCentral Demo"
HOLIDAYS = "HikCentral Demo 2026"
SHIFT = "HikCentral Demo 09-18"
ROLE = "HikCentral Checkin API"
USER = "hikcentral.demo@localhost.invalid"
DAY = "2026-11-02"
EMPLOYEES = (
	("HIK-DEMO-CDMX", "Ciudad de Mexico"),
	("HIK-DEMO-OAX", "Oaxaca"),
)


def seed():
	"""Prepare exactly the demo master records; do not create attendance early."""
	frappe.set_user("Administrator")
	frappe.db.set_single_value("System Settings", "time_zone", "America/Mexico_City")

	if not frappe.db.exists("Warehouse Type", "Transit"):
		frappe.get_doc({"doctype": "Warehouse Type", "name": "Transit"}).insert(ignore_permissions=True)
	if not frappe.db.exists("Company", COMPANY):
		frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": COMPANY,
				"abbr": "HCD",
				"country": "Mexico",
				"default_currency": "MXN",
				"valuation_method": "FIFO",
			}
		).insert(ignore_permissions=True)
	if not frappe.db.exists("Holiday List", HOLIDAYS):
		frappe.get_doc(
			{
				"doctype": "Holiday List",
				"holiday_list_name": HOLIDAYS,
				"from_date": "2026-01-01",
				"to_date": "2026-12-31",
			}
		).insert(ignore_permissions=True)
	if not frappe.db.exists("Shift Type", SHIFT):
		frappe.get_doc(
			{
				"doctype": "Shift Type",
				"name": SHIFT,
				"start_time": "09:00:00",
				"end_time": "18:00:00",
				"holiday_list": HOLIDAYS,
				"enable_auto_attendance": 1,
				"determine_check_in_and_check_out": "Strictly based on Log Type in Employee Checkin",
				"working_hours_calculation_based_on": "First Check-in and Last Check-out",
				"begin_check_in_before_shift_start_time": 60,
				"allow_check_out_after_shift_end_time": 60,
				"working_hours_threshold_for_half_day": 6,
				"working_hours_threshold_for_absent": 3,
				"process_attendance_after": DAY,
				"absent_buffer_days": 1,
			}
		).insert(ignore_permissions=True)

	if not frappe.db.exists("Gender", "Male"):
		frappe.get_doc({"doctype": "Gender", "gender": "Male"}).insert(ignore_permissions=True)
	for device_id, city in EMPLOYEES:
		employee_name = frappe.db.get_value("Employee", {"attendance_device_id": device_id}, "name")
		if not employee_name:
			employee = frappe.get_doc(
				{
					"doctype": "Employee",
					"first_name": "Demo",
					"last_name": city,
					"gender": "Male",
					"date_of_birth": "1990-01-01",
					"date_of_joining": "2026-01-01",
					"company": COMPANY,
					"status": "Active",
					"attendance_device_id": device_id,
					"holiday_list": HOLIDAYS,
				}
			).insert(ignore_permissions=True)
			employee_name = employee.name
		if not frappe.db.exists(
			"Shift Assignment",
			{
				"employee": employee_name,
				"shift_type": SHIFT,
				"start_date": "2026-01-01",
				"docstatus": 1,
			},
		):
			assignment = frappe.get_doc(
				{
					"doctype": "Shift Assignment",
					"employee": employee_name,
					"shift_type": SHIFT,
					"company": COMPANY,
					"start_date": "2026-01-01",
					"status": "Active",
				}
			).insert(ignore_permissions=True)
			assignment.submit()

	if not frappe.db.exists("Role", ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": ROLE, "desk_access": 1}).insert(
			ignore_permissions=True
		)
	from frappe.permissions import add_permission, update_permission_property

	if not frappe.db.exists("Custom DocPerm", {"parent": "Employee Checkin", "role": ROLE, "permlevel": 0}):
		add_permission("Employee Checkin", ROLE, ptype="create")
	update_permission_property("Employee Checkin", ROLE, 0, "read", 1)
	update_permission_property("Employee Checkin", ROLE, 0, "create", 1)
	if not frappe.db.exists("Custom DocPerm", {"parent": "Employee Checkin", "role": ROLE, "permlevel": 1}):
		add_permission("Employee Checkin", ROLE, permlevel=1, ptype="read")
	update_permission_property("Employee Checkin", ROLE, 1, "read", 1)
	update_permission_property("Employee Checkin", ROLE, 1, "write", 1)
	if not frappe.db.exists("User", USER):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": USER,
				"first_name": "HikCentral",
				"last_name": "Bridge",
				"enabled": 1,
				"user_type": "System User",
				"send_welcome_email": 0,
				"roles": [{"role": ROLE}],
			}
		).insert(ignore_permissions=True)
	else:
		user = frappe.get_doc("User", USER)
		if ROLE not in {row.role for row in user.roles}:
			user.append("roles", {"role": ROLE})
			user.save(ignore_permissions=True)

	secret_file = Path.home() / ".config" / "hikcentral_bridge" / "erpnext.env"
	if not secret_file.exists():
		from frappe.core.doctype.user.user import generate_keys

		keys = generate_keys(USER)
		secret_file.parent.mkdir(parents=True, exist_ok=True)
		secret_file.write_text(
			f"ERPNEXT_API_KEY={keys['api_key']}\nERPNEXT_API_SECRET={keys['api_secret']}\n",
			encoding="utf-8",
		)
		secret_file.chmod(0o600)
	frappe.db.commit()
	print(
		{
			"company": COMPANY,
			"shift": SHIFT,
			"employees": [x[0] for x in EMPLOYEES],
			"credential_file": str(secret_file),
		}
	)


def finalize(day: str = DAY):
	"""Close the selected demo shift window and mark attendance."""
	frappe.set_user("Administrator")
	selected = date.fromisoformat(day)
	shift = frappe.get_doc("Shift Type", SHIFT)
	shift.process_attendance_after = day
	shift.last_sync_of_checkin = datetime.combine(selected + timedelta(days=1), datetime.min.time())
	shift.save(ignore_permissions=True)
	shift.process_auto_attendance()
	frappe.db.commit()
	return verify(day)


def verify(day: str = DAY):
	"""Assert the four source punches created two submitted Present records."""
	checkins = frappe.get_all(
		"Employee Checkin",
		filters={"device_id": ["in", ["HIK-CDMX-01", "HIK-OAX-01"]]},
		fields=["name", "employee", "time", "log_type", "attendance", "offshift"],
	)
	device_ids = {x[0] for x in EMPLOYEES}
	employees = frappe.get_all(
		"Employee", filters={"attendance_device_id": ["in", list(device_ids)]}, fields=["name"]
	)
	checkins = [
		row
		for row in checkins
		if row.employee in {emp.name for emp in employees} and str(row.time).startswith(day)
	]
	assert len(checkins) == 4, f"expected 4 checkins, found {len(checkins)}"
	assert all(row.attendance and not row.offshift for row in checkins), "checkins must link to Attendance"
	attendance = frappe.get_all(
		"Attendance",
		filters={"attendance_date": day, "employee": ["in", [emp.name for emp in employees]]},
		fields=["name", "employee", "status", "docstatus", "shift"],
	)
	assert len(attendance) == 2, f"expected 2 attendance records, found {len(attendance)}"
	assert all(row.status == "Present" and row.docstatus == 1 and row.shift == SHIFT for row in attendance)
	result = {"checkins": [row.name for row in checkins], "attendance": [row.name for row in attendance]}
	print(result)
	return result


def inspect():
	"""Show non-secret demo records while diagnosing a local setup."""
	print(
		{
			"site": frappe.local.site,
			"employees": frappe.get_all(
				"Employee", fields=["name", "attendance_device_id"], limit_page_length=20
			),
			"checkins": frappe.get_all(
				"Employee Checkin",
				fields=[
					"name",
					"employee",
					"time",
					"device_id",
					"log_type",
					"shift",
					"attendance",
					"offshift",
				],
				limit_page_length=20,
			),
			"attendance": frappe.get_all(
				"Attendance", fields=["name", "employee", "attendance_date", "status"], limit_page_length=20
			),
		}
	)


def reset_attempt(day: str = DAY):
	"""Remove this demo's records for one selected day."""
	frappe.set_user("Administrator")
	date.fromisoformat(day)
	employees = frappe.get_all(
		"Employee", filters={"attendance_device_id": ["in", [x[0] for x in EMPLOYEES]]}, pluck="name"
	)
	for attendance_name in frappe.get_all(
		"Attendance", filters={"employee": ["in", employees], "attendance_date": day}, pluck="name"
	):
		doc = frappe.get_doc("Attendance", attendance_name)
		if doc.docstatus == 1:
			doc.cancel()
		frappe.delete_doc("Attendance", attendance_name, force=True, ignore_permissions=True)
	for checkin in frappe.get_all(
		"Employee Checkin",
		filters={"device_id": ["in", ["HIK-CDMX-01", "HIK-OAX-01"]], "employee": ["in", employees]},
		fields=["name", "time"],
	):
		if str(checkin.time).startswith(day):
			frappe.delete_doc("Employee Checkin", checkin.name, force=True, ignore_permissions=True)
	shift = frappe.get_doc("Shift Type", SHIFT)
	shift.last_sync_of_checkin = None
	shift.process_attendance_after = day
	shift.save(ignore_permissions=True)
	frappe.db.commit()
	print(f"Removed demo checkins and attendance for {day}; master records are retained.")
