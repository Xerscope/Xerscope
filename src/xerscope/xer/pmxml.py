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
    except ET.ParseError as exc:
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
    root, ns = _root(data, source)
    baselines = [
        XmlBaseline(
            object_id=_text(b, ns, "ObjectId"),
            code=_text(b, ns, "Id"),
            name=_text(b, ns, "Name"),
            data_date=_xer_date(_text(b, ns, "DataDate")),
            original_project_id=_text(b, ns, "OriginalProjectObjectId"),
            activities=len(b.findall(ns + "Activity")),
        )
        for b in root.findall(ns + "BaselineProject")
    ]
    project = root.find(ns + "Project")
    current = _text(project, ns, "CurrentBaselineProjectObjectId") if project is not None else ""
    return baselines, current


def choose_baseline(baselines: list[XmlBaseline], current: str, wanted: str | None, source: str) -> XmlBaseline:
    """The baseline to read: ``wanted`` (an update's sum_base_proj_id), else the Project Baseline the
    file's project names, else the only one; several and none named is refused, with the list."""
    by_id = {b.object_id: b for b in baselines}
    if not baselines:
        raise XerError(f"{source}: no baseline in this P6 XML export (tick them under Baselines to Export)")
    listed = ", ".join(f"{b.object_id} ({b.code})" for b in baselines)
    if wanted:  # asked for by name: that one or a refusal, never another baseline in its place
        if wanted not in by_id:
            raise XerError(f"{source}: baseline {wanted} is not in this file; it holds {listed}")
        return by_id[wanted]
    if current in by_id:
        return by_id[current]
    if len(baselines) == 1:
        return baselines[0]
    raise XerError(f"{source}: {len(baselines)} baselines and none named as the Project Baseline: {listed}")


def _work_periods(element: ET.Element, ns: str) -> str:
    """WorkTime children as clndr_data periods; the XML's last working minute becomes the XER's end."""
    periods = []
    for index, work in enumerate(element.findall(ns + "WorkTime")):
        start, finish = _text(work, ns, "Start")[:5], _text(work, ns, "Finish")
        if not start or not finish:
            continue
        end = (datetime.strptime(finish[:5], "%H:%M") + timedelta(minutes=1)).strftime("%H:%M")  # 23:59 -> 00:00
        periods.append(f"(0||{index}(s|{start}|f|{end})())")
    return "".join(periods)


def _calendar_rows(root: ET.Element, ns: str) -> list[dict]:
    rows = []
    for calendar in root.iter(ns + "Calendar"):
        week = calendar.find(ns + "StandardWorkWeek")
        days = {}
        for hours in week.findall(ns + "StandardWorkHours") if week is not None else []:
            number = WEEKDAY_NUMBER.get(_text(hours, ns, "DayOfWeek"))
            if number:
                days[number] = _work_periods(hours, ns)
        week_blob = "".join(f"(0||{d}()({days.get(d, '')}))" for d in range(1, 8))
        exceptions = []
        holder = calendar.find(ns + "HolidayOrExceptions")
        for index, exception in enumerate(holder.findall(ns + "HolidayOrException") if holder is not None else []):
            when = _text(exception, ns, "Date")[:10]
            if when:
                serial = (date.fromisoformat(when) - EXCEL_EPOCH).days
                exceptions.append(f"(0||{index}(d|{serial})({_work_periods(exception, ns)}))")
        rows.append(
            {
                "clndr_id": _text(calendar, ns, "ObjectId"),
                "clndr_name": _text(calendar, ns, "Name"),
                "clndr_type": CALENDAR_TYPE.get(_text(calendar, ns, "Type"), ""),
                "base_clndr_id": _text(calendar, ns, "BaseCalendarObjectId"),
                "proj_id": _text(calendar, ns, "ProjectObjectId"),
                "default_flag": "Y" if _text(calendar, ns, "IsDefault") in ("1", "true") else "N",
                "day_hr_cnt": _text(calendar, ns, "HoursPerDay"),
                "week_hr_cnt": _text(calendar, ns, "HoursPerWeek"),
                "month_hr_cnt": _text(calendar, ns, "HoursPerMonth"),
                "year_hr_cnt": _text(calendar, ns, "HoursPerYear"),
                "clndr_data": (
                    f"(0||CalendarData()((0||DaysOfWeek()({week_blob}))(0||Exceptions()({''.join(exceptions)}))))"
                ),
            }
        )
    return rows


def _project_rows(project: ET.Element, ns: str, proj_id: str) -> tuple[list[dict], list[dict]]:
    """PROJECT and PROJWBS: the project node first (its code and name), then each WBS element."""
    node_id = _text(project, ns, "WBSObjectId") or f"node-{proj_id}"
    project_row = {
        "proj_id": proj_id,
        "proj_short_name": _text(project, ns, "Id"),
        "last_recalc_date": _xer_date(_text(project, ns, "DataDate")),
        "plan_start_date": _xer_date(_text(project, ns, "PlannedStartDate")),
        "scd_end_date": _xer_date(_text(project, ns, "ScheduledFinishDate")),
        "clndr_id": _text(project, ns, "ActivityDefaultCalendarObjectId"),
        "orig_proj_id": _text(project, ns, "OriginalProjectObjectId"),
        "sum_base_proj_id": "",
    }
    wbs_rows = [
        {
            "wbs_id": node_id,
            "proj_id": proj_id,
            "parent_wbs_id": "",
            "proj_node_flag": "Y",
            "wbs_short_name": _text(project, ns, "Id"),
            "wbs_name": _text(project, ns, "Name"),
            "seq_num": "0",
        }
    ]
    for wbs in project.findall(ns + "WBS"):
        wbs_rows.append(
            {
                "wbs_id": _text(wbs, ns, "ObjectId"),
                "proj_id": proj_id,
                "parent_wbs_id": _text(wbs, ns, "ParentObjectId") or node_id,
                "proj_node_flag": "N",
                "wbs_short_name": _text(wbs, ns, "Code"),
                "wbs_name": _text(wbs, ns, "Name"),
                "seq_num": _text(wbs, ns, "SequenceNumber") or "0",
            }
        )
    return [project_row], wbs_rows


def _task_row(activity: ET.Element, ns: str, proj_id: str, node_id: str) -> dict:
    t = lambda field: _text(activity, ns, field)  # noqa: E731 - one short reader per field below
    return {
        "task_id": t("ObjectId"),
        "proj_id": proj_id,
        "wbs_id": t("WBSObjectId") or node_id,
        "clndr_id": t("CalendarObjectId"),
        "task_code": t("Id"),
        "task_name": t("Name"),
        "task_type": ACTIVITY_TYPE.get(t("Type"), t("Type")),
        "status_code": ACTIVITY_STATUS.get(t("Status"), t("Status")),
        "complete_pct_type": PERCENT_COMPLETE_TYPE.get(t("PercentCompleteType"), ""),
        "phys_complete_pct": _percent(t("PhysicalPercentComplete")),
        "target_drtn_hr_cnt": t("PlannedDuration"),
        "remain_drtn_hr_cnt": t("RemainingDuration"),
        "target_work_qty": t("PlannedLaborUnits"),
        "act_work_qty": t("ActualLaborUnits"),
        "remain_work_qty": t("RemainingLaborUnits"),
        "target_equip_qty": t("PlannedNonLaborUnits"),
        "act_equip_qty": t("ActualNonLaborUnits"),
        "remain_equip_qty": t("RemainingNonLaborUnits"),
        "target_start_date": _xer_date(t("PlannedStartDate")),
        "target_end_date": _xer_date(t("PlannedFinishDate")),
        "act_start_date": _xer_date(t("ActualStartDate")),
        "act_end_date": _xer_date(t("ActualFinishDate")),
        "early_start_date": _xer_date(t("RemainingEarlyStartDate") or t("StartDate")),
        "early_end_date": _xer_date(t("RemainingEarlyFinishDate") or t("FinishDate")),
        "restart_date": _xer_date(t("RemainingEarlyStartDate")),
        "reend_date": _xer_date(t("RemainingEarlyFinishDate")),
        "late_start_date": _xer_date(t("RemainingLateStartDate")),
        "late_end_date": _xer_date(t("RemainingLateFinishDate")),
        "expect_end_date": _xer_date(t("ExpectedFinishDate")),
        "cstr_type": CONSTRAINT_TYPE.get(t("PrimaryConstraintType"), ""),
        "cstr_date": _xer_date(t("PrimaryConstraintDate")),
        "cstr_type2": CONSTRAINT_TYPE.get(t("SecondaryConstraintType"), ""),
        "cstr_date2": _xer_date(t("SecondaryConstraintDate")),
        "suspend_date": _xer_date(t("SuspendDate")),
        "resume_date": _xer_date(t("ResumeDate")),
        "guid": "",  # the XML writes {8-4-4-4-12}, the XER another encoding: not compared
    }


def read_pmxml_baseline(data: bytes, source: str, baseline_id: str | None = None) -> RawXer:
    """The XER tables of one baseline of a P6 XML export (``choose_baseline`` decides which)."""
    root, ns = _root(data, source)
    baselines, current = list_baselines(data, source)
    chosen = choose_baseline(baselines, current, baseline_id, source)
    project = next(b for b in root.findall(ns + "BaselineProject") if _text(b, ns, "ObjectId") == chosen.object_id)
    proj_id = chosen.object_id
    project_rows, wbs_rows = _project_rows(project, ns, proj_id)
    node_id = wbs_rows[0]["wbs_id"]
    tasks = [_task_row(a, ns, proj_id, node_id) for a in project.findall(ns + "Activity")]
    links = [
        {
            "task_pred_id": _text(r, ns, "ObjectId"),
            "task_id": _text(r, ns, "SuccessorActivityObjectId"),
            "pred_task_id": _text(r, ns, "PredecessorActivityObjectId"),
            "proj_id": _text(r, ns, "SuccessorProjectObjectId") or proj_id,
            "pred_proj_id": _text(r, ns, "PredecessorProjectObjectId") or proj_id,
            "pred_type": RELATIONSHIP_TYPE.get(_text(r, ns, "Type"), _text(r, ns, "Type")),
            "lag_hr_cnt": _text(r, ns, "Lag") or "0",
        }
        for r in project.findall(ns + "Relationship")
    ]
    assignments = []
    for a in project.findall(ns + "ResourceAssignment"):
        t = lambda field, a=a: _text(a, ns, field)  # noqa: E731
        resource_type = t("ResourceType")
        assignments.append(
            {
                "taskrsrc_id": t("ObjectId"),
                "task_id": t("ActivityObjectId"),
                "proj_id": proj_id,
                "rsrc_id": t("ResourceObjectId"),
                "role_id": t("RoleObjectId"),
                "rsrc_type": RESOURCE_TYPE.get(resource_type, "role" if not t("ResourceObjectId") else ""),
                "target_qty": t("PlannedUnits"),
                "target_cost": t("PlannedCost"),
                "act_reg_qty": t("ActualRegularUnits"),
                "act_ot_qty": t("ActualOvertimeUnits"),
                "remain_qty": t("RemainingUnits"),
                "target_qty_per_hr": t("PlannedUnitsPerTime"),
                "remain_qty_per_hr": t("RemainingUnitsPerTime"),
                "target_lag_drtn_hr_cnt": t("PlannedLag"),
                "relag_drtn_hr_cnt": t("RemainingLag"),
                "target_start_date": _xer_date(t("PlannedStartDate")),
                "target_end_date": _xer_date(t("PlannedFinishDate")),
                "act_start_date": _xer_date(t("ActualStartDate")),
                "act_end_date": _xer_date(t("ActualFinishDate")),
                "restart_date": _xer_date(t("RemainingStartDate")),
                "reend_date": _xer_date(t("RemainingFinishDate")),
                "curv_id": t("ResourceCurveObjectId"),
            }
        )
    expenses = [
        {
            "cost_item_id": _text(e, ns, "ObjectId"),
            "task_id": _text(e, ns, "ActivityObjectId"),
            "proj_id": proj_id,
            "target_cost": _text(e, ns, "PlannedCost"),
            "act_cost": _text(e, ns, "ActualCost"),
            "remain_cost": _text(e, ns, "RemainingCost"),
        }
        for e in project.findall(ns + "ActivityExpense")
    ]
    resources = [
        {
            "rsrc_id": _text(r, ns, "ObjectId"),
            "rsrc_short_name": _text(r, ns, "Id"),
            "rsrc_name": _text(r, ns, "Name"),
            "rsrc_type": RESOURCE_TYPE.get(_text(r, ns, "ResourceType"), ""),
            "clndr_id": _text(r, ns, "CalendarObjectId"),
        }
        for r in root.findall(ns + "Resource")
    ]
    tables = {
        "PROJECT": project_rows,
        "PROJWBS": wbs_rows,
        "TASK": tasks,
        "TASKPRED": links,
        "TASKRSRC": assignments,
        "PROJCOST": expenses,
        "CALENDAR": _calendar_rows(root, ns),
        "RSRC": resources,
    }
    frames = {name: pd.DataFrame(rows).astype(str) for name, rows in tables.items() if rows}
    note = f"{source}: baseline {chosen.object_id} ({chosen.code}) read from P6 XML"
    return RawXer(tables=frames, source=source, warnings=[note])
