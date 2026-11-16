"""Baselines from a P6 XML export (Primavera PM XML, ``APIBusinessObjects``).

P6 Professional does not export a project's baselines in XER; its XML export does ("Baselines to
Export", one tick per baseline). Each baseline is a ``BaselineProject`` element: a complete project
whose ``OriginalProjectObjectId`` names the project it was taken from. The project's own
``CurrentBaselineProjectObjectId`` names its Project Baseline ("the project's baseline to use for
computing summaries", P6 EPPM Web Services reference, Project Fields) - the field the XER writes as
PROJECT.sum_base_proj_id. Object ids are the P6 database's, the same in both formats.

This module turns one baseline into the XER tables ``build_snapshot`` reads (PROJECT, PROJWBS, TASK,
TASKPRED, TASKRSRC, PROJCOST, CALENDAR, RSRC), so a baseline read from XML is analysed exactly as one
read from XER. Conversions, as MPXJ's P6 XML reader makes them: durations and units in hours,
percentages as fractions (x 100), names of types and statuses spelled out ("Task Dependent"). Calendar
work periods end on their last working minute in XML ("11:59") and on the next minute in XER ("12:00").
"""

from __future__ import annotations

import xml.etree.ElementTree as ET  # nosec B405 - parses an export the user chose, no entity expansion in 3.x defaults
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import partial

import pandas as pd

from .parser import RawXer, XerError

EXCEL_EPOCH = date(1899, 12, 30)  # CALENDAR.clndr_data dates are Excel serial numbers

ACTIVITY_STATUS = {"Not Started": "TK_NotStart", "In Progress": "TK_Active", "Completed": "TK_Complete"}
ACTIVITY_TYPE = {
    "Task Dependent": "TT_Task",
    "Resource Dependent": "TT_Rsrc",
    "Level of Effort": "TT_LOE",
    "Start Milestone": "TT_Mile",
    "Finish Milestone": "TT_FinMile",
    "WBS Summary": "TT_WBS",
}
PERCENT_COMPLETE_TYPE = {"Physical": "CP_Phys", "Duration": "CP_Drtn", "Units": "CP_Units"}
CONSTRAINT_TYPE = {
    "Start On": "CS_MSO",
    "Start On or Before": "CS_MSOB",
    "Start On or After": "CS_MSOA",
    "Finish On": "CS_MEO",
    "Finish On or Before": "CS_MEOB",
    "Finish On or After": "CS_MEOA",
    "As Late As Possible": "CS_ALAP",
    "Mandatory Start": "CS_MANDSTART",
    "Mandatory Finish": "CS_MANDFIN",
}
RELATIONSHIP_TYPE = {
    "Finish to Start": "PR_FS",
    "Finish to Finish": "PR_FF",
    "Start to Start": "PR_SS",
    "Start to Finish": "PR_SF",
}
RESOURCE_TYPE = {"Labor": "RT_Labor", "Nonlabor": "RT_Equip", "Material": "RT_Mat"}
CALENDAR_TYPE = {"Global": "CA_Base", "Project": "CA_Project", "Resource": "CA_Rsrc"}
WEEKDAY_NUMBER = {"Sunday": 1, "Monday": 2, "Tuesday": 3, "Wednesday": 4, "Thursday": 5, "Friday": 6, "Saturday": 7}


@dataclass(frozen=True)
class XmlBaseline:
    """One ``BaselineProject`` of the file, as listed to the user before it is read."""

    object_id: str
    code: str
    name: str
    data_date: str
    original_project_id: str
    activities: int


def is_pmxml(data: bytes) -> bool:
    """A P6 XML export: its root element is APIBusinessObjects (the first kilobytes say so)."""
    head = data[:4096].lstrip(b"\xef\xbb\xbf").lstrip()
    return head.startswith(b"<") and b"APIBusinessObjects" in head


def _root(data: bytes, source: str) -> tuple[ET.Element, str]:
    try:
        root = ET.fromstring(data)  # nosec B314 - a file the user chose; Python's parser expands no external entity
    except (ET.ParseError, LookupError, ValueError) as exc:  # the last two: an encoding Python cannot read
        raise XerError(f"{source}: not a readable P6 XML file ({exc})") from exc
    namespace = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
    if root.tag.removeprefix(namespace) != "APIBusinessObjects":
        raise XerError(f"{source}: not a P6 XML export (root element {root.tag.removeprefix(namespace)})")
    return root, namespace


def _text(element: ET.Element, namespace: str, field: str) -> str:
    child = element.find(namespace + field)
    return (child.text or "").strip() if child is not None else ""


def _xer_date(value: str) -> str:
    """2023-03-06T08:00:00 -> 2023-03-06 08:00, the XER form; blank stays blank."""
    return value.replace("T", " ")[:16] if value else ""


def _percent(value: str) -> str:
    """P6 XML writes percentages as fractions (MPXJ multiplies by 100); the XER as 0-100."""
    return f"{float(value) * 100:g}" if value else ""


def list_baselines(data: bytes, source: str) -> tuple[list[XmlBaseline], str]:
    """The baselines of the file and the Project Baseline its project names (blank when none)."""
    root, namespace = _root(data, source)
    baselines = [
        XmlBaseline(
            object_id=_text(baseline, namespace, "ObjectId"),
            code=_text(baseline, namespace, "Id"),
            name=_text(baseline, namespace, "Name"),
            data_date=_xer_date(_text(baseline, namespace, "DataDate")),
            original_project_id=_text(baseline, namespace, "OriginalProjectObjectId"),
            activities=len(baseline.findall(namespace + "Activity")),
        )
        for baseline in root.findall(namespace + "BaselineProject")
    ]
    project = root.find(namespace + "Project")
    current = _text(project, namespace, "CurrentBaselineProjectObjectId") if project is not None else ""
    return baselines, current


def choose_baseline(baselines: list[XmlBaseline], current: str, wanted: str | None, source: str) -> XmlBaseline:
    """The baseline to read: ``wanted`` (an update's sum_base_proj_id), else the Project Baseline the
    file's project names, else the only one; several and none named is refused, with the list."""
    by_id = {baseline.object_id: baseline for baseline in baselines}
    if not baselines:
        raise XerError(f"{source}: no baseline in this P6 XML export (tick them under Baselines to Export)")
    listed = ", ".join(f"{baseline.object_id} ({baseline.code})" for baseline in baselines)
    if wanted:  # asked for by name: that one or a refusal, never another baseline in its place
        if wanted not in by_id:
            raise XerError(f"{source}: baseline {wanted} is not in this file; it holds {listed}")
        return by_id[wanted]
    if current in by_id:
        return by_id[current]
    if len(baselines) == 1:
        return baselines[0]
    raise XerError(f"{source}: {len(baselines)} baselines and none named as the Project Baseline: {listed}")


def _work_periods(element: ET.Element, namespace: str) -> str:
    """WorkTime children as clndr_data periods; the XML's last working minute becomes the XER's end."""
    periods = []
    for index, work_time in enumerate(element.findall(namespace + "WorkTime")):
        start, finish = _text(work_time, namespace, "Start")[:5], _text(work_time, namespace, "Finish")
        if not start or not finish:
            continue
        end = (datetime.strptime(finish[:5], "%H:%M") + timedelta(minutes=1)).strftime("%H:%M")  # 23:59 -> 00:00
        periods.append(f"(0||{index}(s|{start}|f|{end})())")
    return "".join(periods)


def _day_nodes(calendar: ET.Element, namespace: str) -> str:
    """The children of clndr_data's DaysOfWeek node: the seven days of the calendar's standard week,
    1 = Sunday .. 7 = Saturday, each with its working periods."""
    standard_work_week = calendar.find(namespace + "StandardWorkWeek")
    work_hours_of_week = (
        standard_work_week.findall(namespace + "StandardWorkHours") if standard_work_week is not None else []
    )
    periods_by_day_number = {}
    for standard_work_hours in work_hours_of_week:
        day_number = WEEKDAY_NUMBER.get(_text(standard_work_hours, namespace, "DayOfWeek"))
        if day_number:
            periods_by_day_number[day_number] = _work_periods(standard_work_hours, namespace)
    return "".join(f"(0||{day_number}()({periods_by_day_number.get(day_number, '')}))" for day_number in range(1, 8))


def _exception_nodes(calendar: ET.Element, namespace: str) -> str:
    """The children of clndr_data's Exceptions node: each holiday or exception of the calendar, its
    date as an Excel serial number, with its working periods (none on a day off)."""
    holidays_or_exceptions = calendar.find(namespace + "HolidayOrExceptions")
    if holidays_or_exceptions is None:
        return ""
    nodes = []
    for index, exception in enumerate(holidays_or_exceptions.findall(namespace + "HolidayOrException")):
        exception_date = _text(exception, namespace, "Date")[:10]
        if exception_date:
            excel_serial = (date.fromisoformat(exception_date) - EXCEL_EPOCH).days
            nodes.append(f"(0||{index}(d|{excel_serial})({_work_periods(exception, namespace)}))")
    return "".join(nodes)


def _calendar_rows(root: ET.Element, namespace: str) -> list[dict]:
    rows = []
    for calendar in root.iter(namespace + "Calendar"):
        days_of_week_node = f"(0||DaysOfWeek()({_day_nodes(calendar, namespace)}))"
        exceptions_node = f"(0||Exceptions()({_exception_nodes(calendar, namespace)}))"
        rows.append(
            {
                "clndr_id": _text(calendar, namespace, "ObjectId"),
                "clndr_name": _text(calendar, namespace, "Name"),
                "clndr_type": CALENDAR_TYPE.get(_text(calendar, namespace, "Type"), ""),
                "base_clndr_id": _text(calendar, namespace, "BaseCalendarObjectId"),
                "proj_id": _text(calendar, namespace, "ProjectObjectId"),
                "default_flag": "Y" if _text(calendar, namespace, "IsDefault") in ("1", "true") else "N",
                "day_hr_cnt": _text(calendar, namespace, "HoursPerDay"),
                "week_hr_cnt": _text(calendar, namespace, "HoursPerWeek"),
                "month_hr_cnt": _text(calendar, namespace, "HoursPerMonth"),
                "year_hr_cnt": _text(calendar, namespace, "HoursPerYear"),
                "clndr_data": f"(0||CalendarData()({days_of_week_node}{exceptions_node}))",
            }
        )
    return rows


def _project_rows(project: ET.Element, namespace: str, proj_id: str) -> tuple[list[dict], list[dict]]:
    """PROJECT and PROJWBS: the project node first (its code and name), then each WBS element."""
    project_node_id = _text(project, namespace, "WBSObjectId") or f"node-{proj_id}"
    project_row = {
        "proj_id": proj_id,
        "proj_short_name": _text(project, namespace, "Id"),
        "last_recalc_date": _xer_date(_text(project, namespace, "DataDate")),
        "plan_start_date": _xer_date(_text(project, namespace, "PlannedStartDate")),
        "scd_end_date": _xer_date(_text(project, namespace, "ScheduledFinishDate")),
        "clndr_id": _text(project, namespace, "ActivityDefaultCalendarObjectId"),
        "orig_proj_id": _text(project, namespace, "OriginalProjectObjectId"),
        "sum_base_proj_id": "",
    }
    wbs_rows = [
        {
            "wbs_id": project_node_id,
            "proj_id": proj_id,
            "parent_wbs_id": "",
            "proj_node_flag": "Y",
            "wbs_short_name": _text(project, namespace, "Id"),
            "wbs_name": _text(project, namespace, "Name"),
            "seq_num": "0",
        }
    ]
    for wbs in project.findall(namespace + "WBS"):
        wbs_rows.append(
            {
                "wbs_id": _text(wbs, namespace, "ObjectId"),
                "proj_id": proj_id,
                "parent_wbs_id": _text(wbs, namespace, "ParentObjectId") or project_node_id,
                "proj_node_flag": "N",
                "wbs_short_name": _text(wbs, namespace, "Code"),
                "wbs_name": _text(wbs, namespace, "Name"),
                "seq_num": _text(wbs, namespace, "SequenceNumber") or "0",
            }
        )
    return [project_row], wbs_rows


def _task_row(activity: ET.Element, namespace: str, proj_id: str, project_node_id: str) -> dict:
    text_of = partial(_text, activity, namespace)  # text_of("Id"): the text of one field of the activity
    return {
        "task_id": text_of("ObjectId"),
        "proj_id": proj_id,
        "wbs_id": text_of("WBSObjectId") or project_node_id,
        "clndr_id": text_of("CalendarObjectId"),
        "task_code": text_of("Id"),
        "task_name": text_of("Name"),
        "task_type": ACTIVITY_TYPE.get(text_of("Type"), text_of("Type")),
        "status_code": ACTIVITY_STATUS.get(text_of("Status"), text_of("Status")),
        "complete_pct_type": PERCENT_COMPLETE_TYPE.get(text_of("PercentCompleteType"), ""),
        "phys_complete_pct": _percent(text_of("PhysicalPercentComplete")),
        "target_drtn_hr_cnt": text_of("PlannedDuration"),
        "remain_drtn_hr_cnt": text_of("RemainingDuration"),
        "target_work_qty": text_of("PlannedLaborUnits"),
        "act_work_qty": text_of("ActualLaborUnits"),
        "remain_work_qty": text_of("RemainingLaborUnits"),
        "target_equip_qty": text_of("PlannedNonLaborUnits"),
        "act_equip_qty": text_of("ActualNonLaborUnits"),
        "remain_equip_qty": text_of("RemainingNonLaborUnits"),
        "target_start_date": _xer_date(text_of("PlannedStartDate")),
        "target_end_date": _xer_date(text_of("PlannedFinishDate")),
        "act_start_date": _xer_date(text_of("ActualStartDate")),
        "act_end_date": _xer_date(text_of("ActualFinishDate")),
        "early_start_date": _xer_date(text_of("RemainingEarlyStartDate") or text_of("StartDate")),
        "early_end_date": _xer_date(text_of("RemainingEarlyFinishDate") or text_of("FinishDate")),
        "restart_date": _xer_date(text_of("RemainingEarlyStartDate")),
        "reend_date": _xer_date(text_of("RemainingEarlyFinishDate")),
        "late_start_date": _xer_date(text_of("RemainingLateStartDate")),
        "late_end_date": _xer_date(text_of("RemainingLateFinishDate")),
        "expect_end_date": _xer_date(text_of("ExpectedFinishDate")),
        "cstr_type": CONSTRAINT_TYPE.get(text_of("PrimaryConstraintType"), ""),
        "cstr_date": _xer_date(text_of("PrimaryConstraintDate")),
        "cstr_type2": CONSTRAINT_TYPE.get(text_of("SecondaryConstraintType"), ""),
        "cstr_date2": _xer_date(text_of("SecondaryConstraintDate")),
        "suspend_date": _xer_date(text_of("SuspendDate")),
        "resume_date": _xer_date(text_of("ResumeDate")),
        "guid": "",  # the XML writes {8-4-4-4-12}, the XER another encoding: not compared
    }


def _link_rows(project: ET.Element, namespace: str, proj_id: str) -> list[dict]:
    """TASKPRED: a link that names no project is of the baseline's own."""
    rows = []
    for relationship in project.findall(namespace + "Relationship"):
        text_of = partial(_text, relationship, namespace)
        rows.append(
            {
                "task_pred_id": text_of("ObjectId"),
                "task_id": text_of("SuccessorActivityObjectId"),
                "pred_task_id": text_of("PredecessorActivityObjectId"),
                "proj_id": text_of("SuccessorProjectObjectId") or proj_id,
                "pred_proj_id": text_of("PredecessorProjectObjectId") or proj_id,
                "pred_type": RELATIONSHIP_TYPE.get(text_of("Type"), text_of("Type")),
                "lag_hr_cnt": text_of("Lag") or "0",
            }
        )
    return rows


def _assignment_rows(project: ET.Element, namespace: str, proj_id: str) -> list[dict]:
    """TASKRSRC: an assignment without a resource is a role's."""
    rows = []
    for assignment in project.findall(namespace + "ResourceAssignment"):
        text_of = partial(_text, assignment, namespace)
        rows.append(
            {
                "taskrsrc_id": text_of("ObjectId"),
                "task_id": text_of("ActivityObjectId"),
                "proj_id": proj_id,
                "rsrc_id": text_of("ResourceObjectId"),
                "role_id": text_of("RoleObjectId"),
                "rsrc_type": RESOURCE_TYPE.get(
                    text_of("ResourceType"), "role" if not text_of("ResourceObjectId") else ""
                ),
                "target_qty": text_of("PlannedUnits"),
                "target_cost": text_of("PlannedCost"),
                "act_reg_qty": text_of("ActualRegularUnits"),
                "act_ot_qty": text_of("ActualOvertimeUnits"),
                "remain_qty": text_of("RemainingUnits"),
                "target_qty_per_hr": text_of("PlannedUnitsPerTime"),
                "remain_qty_per_hr": text_of("RemainingUnitsPerTime"),
                "target_lag_drtn_hr_cnt": text_of("PlannedLag"),
                "relag_drtn_hr_cnt": text_of("RemainingLag"),
                "target_start_date": _xer_date(text_of("PlannedStartDate")),
                "target_end_date": _xer_date(text_of("PlannedFinishDate")),
                "act_start_date": _xer_date(text_of("ActualStartDate")),
                "act_end_date": _xer_date(text_of("ActualFinishDate")),
                "restart_date": _xer_date(text_of("RemainingStartDate")),
                "reend_date": _xer_date(text_of("RemainingFinishDate")),
                "curv_id": text_of("ResourceCurveObjectId"),
            }
        )
    return rows


def read_pmxml_baseline(data: bytes, source: str, baseline_id: str | None = None) -> RawXer:
    """The XER tables of one baseline of a P6 XML export (``choose_baseline`` decides which)."""
    root, namespace = _root(data, source)
    baselines, current = list_baselines(data, source)
    chosen = choose_baseline(baselines, current, baseline_id, source)
    project = next(
        baseline
        for baseline in root.findall(namespace + "BaselineProject")
        if _text(baseline, namespace, "ObjectId") == chosen.object_id
    )
    proj_id = chosen.object_id
    project_rows, wbs_rows = _project_rows(project, namespace, proj_id)
    project_node_id = wbs_rows[0]["wbs_id"]
    try:  # a percentage or a date P6 would not write: the load contract lets only XerError out
        tasks = [
            _task_row(activity, namespace, proj_id, project_node_id)
            for activity in project.findall(namespace + "Activity")
        ]
        calendars = _calendar_rows(root, namespace)
    except ValueError as exc:
        raise XerError(f"{source}: unreadable value in P6 XML ({exc})") from exc
    links = _link_rows(project, namespace, proj_id)
    # build_snapshot keeps the links whose successor project is the one read; which id P6 writes
    # in SuccessorProjectObjectId inside a BaselineProject is not documented, so a link naming
    # another project is counted, not silently lost.
    other_project = sum(link["proj_id"] != proj_id for link in links)
    notes = [f"{source}: baseline {chosen.object_id} ({chosen.code}) read from P6 XML"]
    if other_project:
        notes.append(
            f"{source}: {other_project} relationship(s) of baseline {chosen.object_id} name another project "
            "as successor project; left out of its logic"
        )
    expenses = [
        {
            "cost_item_id": _text(expense, namespace, "ObjectId"),
            "task_id": _text(expense, namespace, "ActivityObjectId"),
            "proj_id": proj_id,
            "target_cost": _text(expense, namespace, "PlannedCost"),
            "act_cost": _text(expense, namespace, "ActualCost"),
            "remain_cost": _text(expense, namespace, "RemainingCost"),
        }
        for expense in project.findall(namespace + "ActivityExpense")
    ]
    resources = [  # of the file: the baselines share them
        {
            "rsrc_id": _text(resource, namespace, "ObjectId"),
            "rsrc_short_name": _text(resource, namespace, "Id"),
            "rsrc_name": _text(resource, namespace, "Name"),
            "rsrc_type": RESOURCE_TYPE.get(_text(resource, namespace, "ResourceType"), ""),
            "clndr_id": _text(resource, namespace, "CalendarObjectId"),
        }
        for resource in root.findall(namespace + "Resource")
    ]
    tables = {
        "PROJECT": project_rows,
        "PROJWBS": wbs_rows,
        "TASK": tasks,
        "TASKPRED": links,
        "TASKRSRC": _assignment_rows(project, namespace, proj_id),
        "PROJCOST": expenses,
        "CALENDAR": calendars,
        "RSRC": resources,
    }
    frames = {name: pd.DataFrame(rows).astype(str) for name, rows in tables.items() if rows}
    return RawXer(tables=frames, source=source, warnings=notes)
