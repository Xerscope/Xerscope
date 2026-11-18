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

An export of several projects with all their baselines runs to gigabytes, so the file is never held
as one tree. ``index_pmxml`` goes through it once and keeps, for each baseline, what lists it and
where its bytes are; ``read_pmxml_baseline`` then reads those bytes alone, with the calendars and the
resources of the file. Both take the bytes of the export or, for one too large to hold, a ``DiskFile``:
the file is then read from the disk piece by piece.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET  # nosec B405 - parses an export the user chose, no entity expansion in 3.x defaults
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import partial
from pathlib import Path
from xml.parsers import expat

import pandas as pd

from .calendar import clndr_data_node
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


@dataclass(frozen=True)
class XmlProject:
    """One ``Project`` of the file: the baseline it names as its Project Baseline, its status date and the
    date it was added to the database (DateAdded), each blank when the file does not give it."""

    object_id: str
    current_baseline_id: str
    data_date: str = ""  # as the XER writes a date: 2026-03-02 08:00
    date_added: str = ""


class DiskFile:
    """A file of the disk read where asked, never whole: ``file[first:end]`` reads those bytes alone.

    Its length is the one it had when it was opened here: a file cut since gives fewer bytes than
    asked, and ``read_pmxml_baseline`` then says the file changed. A file that cannot be read raises
    ``OSError``, as any file does; ``index_pmxml`` and ``read_pmxml_baseline`` report it as a
    ``XerError``."""

    def __init__(self, path: Path) -> None:
        """Note the length of the file; nothing of it is read yet."""
        self.path = path
        self.size = path.stat().st_size

    def __len__(self) -> int:
        """Return the length the file had when it was opened here."""
        return self.size

    def __getitem__(self, span: slice) -> bytes:
        """Read the bytes of ``span`` from the disk."""
        first_byte, end_byte, _ = span.indices(self.size)
        with self.path.open("rb") as file:
            file.seek(first_byte)
            return file.read(max(end_byte - first_byte, 0))


def _cannot_be_read(source: str, error: OSError) -> XerError:
    """The error of a file of the disk that could not be read: its reason, never its path."""
    return XerError(f"{source}: cannot be read ({error.strerror})")


def is_pmxml(data: bytes | DiskFile) -> bool:
    """A P6 XML export: its root element is APIBusinessObjects (the first kilobytes say so)."""
    head = data[:4096].lstrip(b"\xef\xbb\xbf").lstrip()
    return head.startswith(b"<") and b"APIBusinessObjects" in head


def _text(element: ET.Element, namespace: str, field: str) -> str:
    child = element.find(namespace + field)
    return (child.text or "").strip() if child is not None else ""


def _xer_date(value: str) -> str:
    """2023-03-06T08:00:00 -> 2023-03-06 08:00, the XER form; blank stays blank."""
    return value.replace("T", " ")[:16] if value else ""


def _percent(value: str) -> str:
    """P6 XML writes percentages as fractions (MPXJ multiplies by 100); the XER as 0-100."""
    return f"{float(value) * 100:g}" if value else ""


PARSE_CHUNK_BYTES = 1 << 24  # the file goes to the parser 16 MB at a time: what it holds besides the file
LISTED_FIELDS = (
    "ObjectId", "Id", "Name", "DataDate", "DateAdded", "OriginalProjectObjectId", "CurrentBaselineProjectObjectId",
)  # fmt: skip


@dataclass(frozen=True)
class PmxmlIndex:
    """What one pass through a P6 XML export keeps of it. A span is (first byte, byte after the last)
    of an element, with the blanks or comments that follow it."""

    namespace: str  # "{uri}" before each tag as ElementTree writes it, blank without a namespace
    head_end: int  # the bytes before it: the XML declaration and the opening tag of the root element
    tail_start: int  # the bytes from it: the closing tag of the root element
    baselines: list[XmlBaseline]
    baseline_spans: dict[str, tuple[int, int]]  # by baseline ObjectId
    shared_spans: list[tuple[int, int]]  # each Calendar, wherever it is, and each Resource of the file
    projects: list[XmlProject]  # in the order of the file

    @property
    def current_baseline_id(self) -> str:
        """The Project Baseline the file's first project names, blank when none."""
        return self.projects[0].current_baseline_id if self.projects else ""


class _IndexPass:
    """The handlers of the pass ``index_pmxml`` makes. ``depth`` counts the elements open around
    a tag: 0 for the root element, 1 for a project, a baseline, a calendar or a resource of the file,
    2 for a field or an activity of a project.

    The parser gives the byte where a tag starts, not where it ends: a span is closed by the next
    tag that opens or closes after its element."""

    def __init__(self, parser: expat.XMLParserType, source: str) -> None:
        self.parser = parser
        self.source = source
        self.depth = 0
        self.namespace = ""
        self.head_end = -1
        self.tail_start = -1
        self.baselines: list[XmlBaseline] = []
        self.baseline_spans: dict[str, tuple[int, int]] = {}
        self.shared_spans: list[tuple[int, int]] = []
        self.projects: list[XmlProject] = []
        self.calendar_depth = 0  # depth of the calendar being read, 0 outside any
        self.span_starts: dict[int, int] = {}  # by depth: first byte of the element whose span is kept
        self.closing_spans: list[tuple[str, int]] = []  # (what it is, first byte) of spans the next tag ends
        self.project_tag = ""  # Project or BaselineProject while one is read, blank outside
        self.fields: dict[str, str] = {}  # of the project or baseline being read
        self.activities = 0
        self.field = ""  # the listed field being read, blank outside any
        self.field_text: list[str] = []

    def local_name(self, name: str) -> str:
        return name.removeprefix(self.namespace)

    def start_element(self, name: str, attributes: dict) -> None:
        if self.depth == 0:  # the root element: its namespace is the one every tag is read in
            self.namespace = name.split("}")[0] + "}" if "}" in name else ""
        if self.depth < 3 or self.closing_spans or self.local_name(name) == "Calendar":
            self._open(self.local_name(name), self.parser.CurrentByteIndex)
        self.depth += 1

    def end_element(self, name: str) -> None:
        self.depth -= 1
        if self.depth < 3 or self.closing_spans or self.depth == self.calendar_depth:
            self._close(self.local_name(name), self.parser.CurrentByteIndex)

    def _open(self, tag: str, position: int) -> None:
        """A tag opens at ``position``, ``self.depth`` elements around it."""
        self._end_closing_spans(position)
        if self.depth == 0:
            self._check_root(tag)
        elif self.depth == 1 and self.head_end < 0:
            self.head_end = position
        self._keep_span_start(tag, position)
        if self.depth == 1 and tag in ("Project", "BaselineProject"):
            self.project_tag = tag
        elif self.depth == 2 and self.project_tag:
            self._open_project_child(tag)

    def _check_root(self, tag: str) -> None:
        if tag != "APIBusinessObjects":
            raise XerError(f"{self.source}: not a P6 XML export (root element {tag})")

    def _keep_span_start(self, tag: str, position: int) -> None:
        """Note where a calendar that is not inside another, a baseline or a resource of the file starts."""
        if tag == "Calendar" and not self.calendar_depth:
            self.calendar_depth = self.depth
        elif self.depth != 1 or tag not in ("BaselineProject", "Resource"):
            return
        self.span_starts[self.depth] = position

    def _open_project_child(self, tag: str) -> None:
        """A field or an activity of a project or baseline: the first of each listed field is read."""
        if tag == "Activity":
            self.activities += 1
        elif tag in LISTED_FIELDS and tag not in self.fields:
            self.field = tag
            self.parser.CharacterDataHandler = self.field_text.append

    def _close(self, tag: str, position: int) -> None:
        """The tag that closes an element starts at ``position``, ``self.depth`` elements around it."""
        self._end_closing_spans(position)
        if self.depth == 0:
            self.tail_start = position
            if self.head_end < 0:  # a root element without a child
                self.head_end = position
        elif self.depth == 2 and self.field:
            self._close_field()
        elif self.depth == 1 and self.project_tag:
            self._close_project()
        if self.depth == self.calendar_depth:
            self.calendar_depth = 0
        if self.depth in self.span_starts:
            self.closing_spans.append((tag, self.span_starts.pop(self.depth)))

    def _close_field(self) -> None:
        self.parser.CharacterDataHandler = None
        self.fields[self.field] = "".join(self.field_text).strip()
        self.field = ""
        self.field_text.clear()

    def _close_project(self) -> None:
        if self.project_tag == "BaselineProject":
            self.baselines.append(
                XmlBaseline(
                    object_id=self.fields.get("ObjectId", ""),
                    code=self.fields.get("Id", ""),
                    name=self.fields.get("Name", ""),
                    data_date=_xer_date(self.fields.get("DataDate", "")),
                    original_project_id=self.fields.get("OriginalProjectObjectId", ""),
                    activities=self.activities,
                )
            )
        else:
            self.projects.append(
                XmlProject(
                    self.fields.get("ObjectId", ""),
                    self.fields.get("CurrentBaselineProjectObjectId", ""),
                    _xer_date(self.fields.get("DataDate", "")),
                    _xer_date(self.fields.get("DateAdded", "")),
                )
            )
        self.project_tag = ""
        self.fields = {}
        self.activities = 0

    def _end_closing_spans(self, position: int) -> None:
        """The elements closed just before ``position`` end there."""
        for tag, first_byte in self.closing_spans:
            if tag == "BaselineProject":  # two baselines of one id: the first is the one read, as it was listed
                self.baseline_spans.setdefault(self.baselines[-1].object_id, (first_byte, position))
            else:
                self.shared_spans.append((first_byte, position))
        self.closing_spans.clear()


def index_pmxml(data: bytes | DiskFile, source: str) -> PmxmlIndex:
    """The index of a P6 XML export, from one pass that keeps none of its activities."""
    parser = expat.ParserCreate(namespace_separator="}")
    index_pass = _IndexPass(parser, source)
    parser.StartElementHandler = index_pass.start_element
    parser.EndElementHandler = index_pass.end_element
    try:
        for first_byte in range(0, len(data), PARSE_CHUNK_BYTES):
            parser.Parse(data[first_byte : first_byte + PARSE_CHUNK_BYTES], False)
        parser.Parse(b"", True)
    except (expat.ExpatError, LookupError, ValueError) as exc:  # the last two: an encoding Python cannot read
        raise XerError(f"{source}: not a readable P6 XML file ({exc})") from exc
    except OSError as exc:
        raise _cannot_be_read(source, exc) from exc
    return PmxmlIndex(
        namespace="{" + index_pass.namespace if index_pass.namespace else "",
        head_end=index_pass.head_end,
        tail_start=index_pass.tail_start,
        baselines=index_pass.baselines,
        baseline_spans=index_pass.baseline_spans,
        shared_spans=index_pass.shared_spans,
        projects=index_pass.projects,
    )


def list_baselines(data: bytes | DiskFile, source: str) -> tuple[list[XmlBaseline], str]:
    """The baselines of the file and the Project Baseline its project names (blank when none)."""
    index = index_pmxml(data, source)
    return index.baselines, index.current_baseline_id


def _document_of(data: bytes | DiskFile, source: str, index: PmxmlIndex, baseline_span: tuple[int, int]) -> ET.Element:
    """The root element of the file holding one baseline, the calendars and the resources, in the
    order of the file: what the tables of that baseline are read from."""
    first_byte, end_byte = baseline_span
    outside = [span for span in index.shared_spans if not first_byte <= span[0] < end_byte]
    parser = ET.XMLParser()  # nosec B314 - a file the user chose; Python's parser expands no external entity
    try:
        parser.feed(data[: index.head_end])
        for span_start, span_end in sorted([*outside, baseline_span]):
            parser.feed(data[span_start:span_end])
        parser.feed(data[index.tail_start :])
        return parser.close()
    except ET.ParseError as exc:  # the positions of the index are no longer those of the file
        raise XerError(f"{source}: the file changed since it was listed ({exc})") from exc
    except OSError as exc:
        raise _cannot_be_read(source, exc) from exc


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
        periods.append(clndr_data_node(index, attributes=f"s|{start}|f|{end}"))
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
    return "".join(
        clndr_data_node(day_number, children=periods_by_day_number.get(day_number, "")) for day_number in range(1, 8)
    )


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
            periods = _work_periods(exception, namespace)
            nodes.append(clndr_data_node(index, attributes=f"d|{excel_serial}", children=periods))
    return "".join(nodes)


def _calendar_rows(root: ET.Element, namespace: str) -> list[dict]:
    rows = []
    for calendar in root.iter(namespace + "Calendar"):
        days_of_week_node = clndr_data_node("DaysOfWeek", children=_day_nodes(calendar, namespace))
        exceptions_node = clndr_data_node("Exceptions", children=_exception_nodes(calendar, namespace))
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
                "clndr_data": clndr_data_node("CalendarData", children=days_of_week_node + exceptions_node),
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


def read_pmxml_baseline(
    data: bytes | DiskFile, source: str, baseline_id: str | None = None, index: PmxmlIndex | None = None
) -> RawXer:
    """The XER tables of one baseline of a P6 XML export (``choose_baseline`` decides which).

    ``index``: the index of these same bytes when the caller already holds it, so that reading
    several baselines of one file goes through it once; made here otherwise."""
    index = index or index_pmxml(data, source)
    chosen = choose_baseline(index.baselines, index.current_baseline_id, baseline_id, source)
    namespace = index.namespace
    root = _document_of(data, source, index, index.baseline_spans[chosen.object_id])
    project = next(root.iter(namespace + "BaselineProject"))  # the only one of the document
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
