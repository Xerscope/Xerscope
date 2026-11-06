"""Build tiny P6 XML exports (APIBusinessObjects) in tests, as xerkit builds XER files: a project, its
baselines (BaselineProject) and a calendar, every value written out so it can be checked by hand."""

from __future__ import annotations

from xml.sax.saxutils import escape

NAMESPACE = "http://xmlns.oracle.com/Primavera/P6/V23.12/API/BusinessObjects"
# Monday to Friday 08:00-12:00 / 13:00-17:00 as P6 XML writes it (last working minute: 11:59, 16:59),
# with Friday 2026-04-03 a holiday and Saturday 2026-03-07 worked 08:00-12:00: xerkit's C8 plus that Saturday.
WORKDAY = [("08:00:00", "11:59:00"), ("13:00:00", "16:59:00")]
EXCEPTIONS = [("2026-04-03", []), ("2026-03-07", [("08:00:00", "11:59:00")])]


def _fields(values: dict) -> str:
    return "".join(f"<{key}>{escape(str(value))}</{key}>" for key, value in values.items())


def _work(periods) -> str:
    return "".join(f"<WorkTime><Start>{s}</Start><Finish>{f}</Finish></WorkTime>" for s, f in periods)


def calendar(object_id: str = "8", name: str = "Mon-Fri 8h", hours_per_day: int = 8) -> str:
    days = "".join(
        f"<StandardWorkHours><DayOfWeek>{day}</DayOfWeek>{_work(WORKDAY if day not in ('Saturday', 'Sunday') else [])}"
        "</StandardWorkHours>"
        for day in ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")
    )
    exceptions = "".join(
        f"<HolidayOrException><Date>{day}T00:00:00</Date>{_work(periods)}</HolidayOrException>"
        for day, periods in EXCEPTIONS
    )
    return (
        "<Calendar>"
        + _fields({"ObjectId": object_id, "Name": name, "Type": "Global", "HoursPerDay": hours_per_day,
                   "HoursPerWeek": hours_per_day * 5, "HoursPerMonth": 172, "HoursPerYear": 2000})
        + f"<StandardWorkWeek>{days}</StandardWorkWeek><HolidayOrExceptions>{exceptions}</HolidayOrExceptions>"
        + "</Calendar>"
    )  # fmt: skip


def activity(code: str, object_id: str, start: str, finish: str, hours: float, **extra) -> str:
    """An activity of a baseline: planned dates ("2026-03-02T08:00:00"), planned hours as labour units."""
    values = {
        "ObjectId": object_id,
        "Id": code,
        "Name": code,
        "CalendarObjectId": "8",
        "Status": "Not Started",
        "Type": "Task Dependent",
        "PercentCompleteType": "Duration",
        "PhysicalPercentComplete": 0,
        "PlannedDuration": hours,
        "RemainingDuration": hours,
        "PlannedLaborUnits": hours,
        "PlannedStartDate": start,
        "PlannedFinishDate": finish,
        "StartDate": start,
        "FinishDate": finish,
        **extra,
    }
    return f"<Activity>{_fields(values)}</Activity>"


def baseline(object_id: str, code: str, activities: list[str], data_date: str = "2026-02-23T08:00:00") -> str:
    values = {"ObjectId": object_id, "Id": code, "Name": f"{code} name", "OriginalProjectObjectId": "1",
              "DataDate": data_date, "PlannedStartDate": data_date, "ActivityDefaultCalendarObjectId": "8"}  # fmt: skip
    return f"<BaselineProject>{_fields(values)}{''.join(activities)}</BaselineProject>"


def pmxml_bytes(baselines: list[str], current_baseline: str = "", project_activities: list[str] = ()) -> bytes:
    """A P6 XML export: the project (proj_id 1, its Project Baseline ``current_baseline``) and ``baselines``."""
    project = _fields({"ObjectId": "1", "Id": "UPD", "Name": "Update", "DataDate": "2026-03-02T08:00:00",
                       "CurrentBaselineProjectObjectId": current_baseline})  # fmt: skip
    body = calendar() + f"<Project>{project}{''.join(project_activities)}</Project>" + "".join(baselines)
    head = f'<?xml version="1.0" encoding="UTF-8"?><APIBusinessObjects xmlns="{NAMESPACE}">'
    return f"{head}{body}</APIBusinessObjects>".encode()
