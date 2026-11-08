"""Anonymised copies of XER exports and of the tables the app lets you download.

Built for sharing: a copy carries no name, code, user or free text of the original, and P6
(and xerscope) compute the same dates, floats and checks on it.

Allowlist, table by table (column meanings: Oracle "XER Import/Export Data Map Guide
(Project)", P6 23):

- ``KEEP``: copied as is. Keys, dates, durations, units, flags and P6 enumerations only.
- ``CODES``: identifiers renamed X<kind><hex>, the hex being an HMAC-SHA256 of the original
  under a key drawn for the session: the same original value gets the same new code in every
  file and every download of the session (task_code, WBS, project, resource, role, OBS codes).
  Without the key the original cannot be found back. Hex digits can spell an original value
  ("XA69C30507" holds the Activity ID "C3050"): such a code is drawn again (HMAC of
  "<kind>:<original>:<n>"), so it then depends on the files read.
- ``LABELS``: names rebuilt from the row's new code ("Activity XA1F09C3B2").
- Project ids: ``proj_id`` and every column naming a project by its id (``sum_base_proj_id``,
  ``orig_proj_id``, ``pred_proj_id``…, ``PROJECT_ID_COLUMN``) get a new 9-digit id drawn as the
  codes are (HMAC under the session key, drawn again when it equals an original id), in the XER
  extract and in the tables: a pointer still names the same project, the database's own id is gone.
- ``MONEY``: costs and prices set to 0 (P6 counts an assignment or an expense, not its cost).
- ``GUIDS``: replaced by new random GUIDs, the same original GUID getting the same new one,
  none holding an original value.

Any other column is emptied and any other table left out; both are reported by name. The
ERMHDR line loses the exporting user, his full name and the database name.

Before a file or a table is handed out, every one of its fields and column names is compared
with every text value of the originals that was not kept, searched for those values inside it
(between a letter or digit and anything else: "calendar 'Night Shift' has no working time")
and for every original code anywhere (``Anonymizer.leaks``): one match and it is refused. The
notes of the rules are the one free text copied out: a value of the originals found inside one
(an error message naming a calendar) is replaced by ``HIDDEN``.
The names of the source files (``PROJ-01.xer``) and their stems (``PROJ-01``) are refused the same
way, but anywhere in a field: they carry the project code and are written into labels
("planned dates of <date> · <file>").
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import re
import secrets
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

import pandas as pd

from .export import csv_bytes, zip_frames
from .xer.parser import RawXer

KEEP = {
    "PROJECT": """acct_id act_pct_link_flag act_this_per_link_flag add_act_remain_flag add_date allow_complete_flag
        allow_neg_act_flag apply_actuals_date base_proj_id base_proj_id1 base_proj_id2 base_type_id batch_sum_flag
        close_period_flag loaded_scope_level new_fin_dates_id sum_refresh_date sumtask_loaded trsrcsum_loaded
        checkout_flag chng_eff_cmp_pct_flag clndr_id
        cost_qty_recalc_flag critical_drtn_hr_cnt critical_path_type def_complete_pct_type def_duration_type
        def_qty_type def_rate_type def_rollup_dates_flag def_task_type export_flag fcst_start_date fintmpl_id
        fy_start_month_num hist_interval hist_level intg_proj_type last_baseline_update_date last_fin_dates_id
        last_level_date last_recalc_date last_schedule_date last_tasksum_date name_sep_char next_data_date
        orig_proj_id plan_end_date plan_start_date priority_num proj_id project_flag rem_target_link_flag
        reset_planned_flag risk_level rsrc_multi_assign_flag rsrc_self_add_flag scd_end_date source_proj_id
        step_complete_flag strgy_priority_num sum_assign_level sum_base_proj_id sum_data_date sum_only_flag
        task_code_base task_code_prefix_flag task_code_step ts_rsrc_mark_act_finish_flag ts_rsrc_vw_inact_actv_flag
        use_project_baseline_flag wbs_max_sum_level""",
    "PROJWBS": """anticip_end_date anticip_start_date dscnt_period_type est_wt ev_compute_type ev_etc_compute_type
        ev_etc_user_value ev_user_pct indep_remain_work_qty obs_id parent_wbs_id phase_id proj_id proj_node_flag
        seq_num status_code sum_data_flag wbs_id""",
    "CALENDAR": """base_clndr_id clndr_data clndr_id clndr_type day_hr_cnt default_flag last_chng_date month_hr_cnt
        proj_id rsrc_private week_hr_cnt year_hr_cnt""",
    "TASK": """act_end_date act_equip_qty act_start_date act_this_per_equip_qty act_this_per_work_qty act_work_qty
        auto_compute_act_flag clndr_id complete_pct_type create_date cstr_date cstr_date2 cstr_type cstr_type2
        driving_path_flag duration_type early_end_date early_start_date est_wt expect_end_date
        external_early_start_date external_late_end_date float_path float_path_order free_float_hr_cnt late_end_date
        late_start_date lock_plan_flag phys_complete_pct priority_type proj_id reend_date rem_late_end_date
        rem_late_start_date remain_drtn_hr_cnt remain_equip_qty remain_work_qty restart_date resume_date rev_fdbk_flag
        review_end_date review_type rsrc_id status_code suspend_date target_drtn_hr_cnt target_end_date
        target_equip_qty target_start_date target_work_qty task_id task_type total_float_hr_cnt update_date wbs_id""",
    "TASKPRED": "aref arls lag_hr_cnt pred_proj_id pred_task_id pred_type proj_id task_id task_pred_id",
    "TASKRSRC": """acct_id act_end_date act_ot_qty act_reg_qty act_start_date act_this_per_qty cost_per_qty_source_type
        cost_qty_link_flag create_date curv_id ot_factor pend_act_ot_qty pend_act_reg_qty pend_complete_pct
        pend_remain_qty prior_ts_act_of_qty prior_ts_act_reg_qty proj_id rate_type reend_date relag_drtn_hr_cnt
        rem_late_end_date rem_late_start_date remain_qty remain_qty_per_hr restart_date role_id rollup_dates_flag
        rsrc_id rsrc_type skill_level target_end_date target_lag_drtn_hr_cnt target_qty target_qty_per_hr
        target_start_date task_id taskrsrc_id ts_pend_act_end_flag""",
    "RSRC": """active_flag auto_compute_act_flag clndr_id cost_qty_type curr_id def_cost_qty_link_flag def_qty_per_hr
        ot_factor ot_flag parent_rsrc_id role_id rsrc_id rsrc_seq_num rsrc_type shift_id timesheet_flag unit_id
        xfer_complete_day_cnt xfer_notstart_day_cnt""",
    "ROLES": "cost_qty_type def_cost_qty_link_flag parent_role_id role_id seq_num",
    "PROJCOST": "acct_id auto_compute_act_flag cost_item_id cost_load_type cost_type_id proj_id target_qty task_id",
    "SCHEDOPTIONS": """LevelPriorityList enable_multiple_longest_path_calc key_activity_for_multiple_longest_paths
        level_all_rsrc_flag level_float_thrs_cnt level_keep_sched_date_flag level_outer_assign_flag
        level_outer_assign_priority level_over_alloc_pct level_within_float_flag limit_multiple_longest_path_calc
        max_multiple_longest_path proj_id sched_calendar_on_relationship_lag sched_float_type
        sched_lag_early_start_flag sched_open_critical_flag sched_outer_depend_type sched_progress_override
        sched_retained_logic sched_setplantoforecast sched_use_expect_end_flag sched_use_project_end_date_for_float
        schedoptions_id use_total_float_multiple_longest_paths""",
    "CURRTYPE": """base_exch_rate curr_id curr_short_name curr_symbol curr_type decimal_digit_cnt decimal_symbol
        digit_group_symbol group_digit_cnt neg_curr_fmt_type pos_curr_fmt_type""",
    "UMEASURE": "seq_num unit_abbrev unit_id unit_name",
    "OBS": "obs_id parent_obs_id seq_num",
    # table_name is a P6 table name ("TASK"), the words block 09 of the diagnostic lists; the field's
    # name and label stay secrets
    "UDFTYPE": "udf_type_id table_name logical_data_type super_flag export_flag",
}
KEEP = {table: frozenset(columns.split()) for table, columns in KEEP.items()}
CODES = {  # (table, column) -> kind of code; the kind's letter follows "X" in the new code
    ("TASK", "task_code"): "A",
    ("PROJWBS", "wbs_short_name"): "W",
    ("PROJECT", "proj_short_name"): "P",
    ("RSRC", "rsrc_short_name"): "R",
    ("ROLES", "role_short_name"): "L",
    ("OBS", "obs_name"): "O",
}
LABELS = {  # (table, column) -> (prefix, column holding the row's code)
    ("TASK", "task_name"): ("Activity", "task_code"),
    ("PROJWBS", "wbs_name"): ("WBS", "wbs_short_name"),
    ("RSRC", "rsrc_name"): ("Resource", "rsrc_short_name"),
    ("ROLES", "role_name"): ("Role", "role_short_name"),
    ("CALENDAR", "clndr_name"): ("Calendar", "clndr_id"),
}
MONEY = {
    "PROJECT": {"def_cost_per_qty"},
    "PROJWBS": {"indep_remain_total_cost", "orig_cost"},
    "TASKRSRC": {"act_ot_cost", "act_reg_cost", "act_this_per_cost", "cost_per_qty", "remain_cost", "target_cost"},
    "PROJCOST": {"act_cost", "cost_per_qty", "remain_cost", "target_cost"},
}
# Amounts xerscope computes from the costs (EV series, baseline cost per activity): 0 in the tables
# it anonymises, as MONEY sets them in the XER. The ratio spi_cost reveals no amount and stays.
MONEY_COLUMNS = frozenset({"bl_cost", "bac_cost", "pv_cost", "ev_cost"})
GUIDS = {"guid"}
# Columns holding a P6 project id (PROJECT.proj_id, sum_base_proj_id, orig_proj_id, source_proj_id,
# base_proj_id1, TASKPRED.pred_proj_id…), and the Debug column that lists them comma-separated.
PROJECT_ID_COLUMN = re.compile(r"(?:\w+_)?proj_id\d*")
PROJECT_ID_LIST_COLUMNS = frozenset({"baselines_to_export"})
NOT_AN_ID = frozenset({"absent"})  # app/diagnostic.ABSENT: the file has no such column
# New project ids: 9 digits, an integer key as P6's own (int32 holds it)
PROJECT_ID_LOW, PROJECT_ID_SPAN = 100_000_000, 900_000_000
# Hex digits of each kind of new code. 8 for activities: ~4e9 values, so ~0.03 % chance of two
# IDs sharing one among 50,000; a clash is refused (CodeClash), never written.
WIDTH = {"A": 8, "W": 6, "P": 6, "R": 6, "L": 6, "O": 6}
DRAWS = 1000  # draws of one code or GUID before giving up (CodeClash): 3-character originals made of hex digits
# What CalendarData is written with (P6 5.0 to 25.12, every reference file): nothing else may pass.
CALENDAR_WORDS = frozenset({"CalendarData", "DaysOfWeek", "Exceptions", "ShowTotal", "VIEW"})
# File stems that are words of xerscope's own tables and labels: as a whole word they say nothing of a
# project, and searching them would refuse every download ("baseline file", "use_project_baseline_flag").
GENERIC_FILE_STEMS = frozenset(
    {"baseline", "baselines", "bl", "export", "exports", "schedule", "project", "projects", "update", "updates",
     "file", "files", "planned", "current", "target", "programme", "program", "planning", "xer", "p6"}
)  # fmt: skip
GENERIC_HEADER = frozenset({"Project", "Project Management", "dbxDatabaseNoName"})
# Words the anonymiser writes itself (label prefixes, header): a file value equal to one (a financial
# period template named "Calendar") is still refused whole, not searched inside "Calendar 638".
OWN_WORDS = frozenset({prefix for prefix, _ in LABELS.values()} | {"Project", "ANON", "file"})
HIDDEN = "[hidden]"  # what replaces a value of the originals found inside a note


PROJECT_ID_IN_NOTE = re.compile(r"(?<!\w)proj_id (\d+)")  # Baseline.source: "(proj_id 370, last update …)"


def is_project_id_column(column: object) -> bool:
    return isinstance(column, str) and PROJECT_ID_COLUMN.fullmatch(column) is not None


def _project_ids_in(raw: RawXer) -> Iterator[str]:
    """Every non-blank value of a project id column, in every table of ``raw``."""
    for frame in raw.tables.values():
        for column in filter(is_project_id_column, frame.columns):
            yield from (value for value in frame[column] if value)


def _is_text(value: str) -> bool:
    """Worth looking for in an output: three characters or more, at least one letter."""
    return len(value) >= 3 and any(character.isalpha() for character in value)


@dataclass
class Report:
    """What was left out, by name only: never a value."""

    dropped_tables: set[str] = field(default_factory=set)
    emptied_columns: set[str] = field(default_factory=set)  # "TABLE.column"


class LeakError(ValueError):
    """An output still holds a text value of the originals."""


class CodeClash(LeakError):
    """Two original values of one kind would get the same new code."""


@dataclass
class Anonymizer:
    """New codes and the text values to keep out, for one set of XER files (one session)."""

    codes: dict[str, dict[str, str]] = field(default_factory=dict)  # kind -> original -> new
    guids: dict[str, str] = field(default_factory=dict)
    wbs_paths: dict[str, str] = field(default_factory=dict)  # original wbs_code -> new
    secrets_: dict[str, str] = field(default_factory=dict)  # text value -> "TABLE.column" it came from
    file_names: set[str] = field(default_factory=set)  # source file names and their stems, found anywhere in a field
    original_codes: set[str] = field(default_factory=set)  # values of the CODES columns, found anywhere in a field
    project_ids: dict[str, str] = field(default_factory=dict)  # original proj_id -> new
    original_project_ids: set[str] = field(default_factory=set)  # never given as a new id
    kept: set[str] = field(default_factory=set)  # values of the kept columns: written as they are
    report: Report = field(default_factory=Report)
    key: bytes = field(default_factory=lambda: secrets.token_bytes(32), repr=False)  # HMAC key of the codes
    taken: dict[str, set[str]] = field(default_factory=dict, repr=False)  # kind -> new codes given

    @classmethod
    def from_raws(cls, raws: Iterable[RawXer], key: bytes | None = None) -> Anonymizer:
        """One pass over the files given. With the session's ``key``, a code is the same whichever
        files were read (an anonymizer of one update and one of the whole series agree), unless
        it is drawn again for holding an original value of the files read."""
        found: dict[str, set[str]] = {kind: set() for kind in WIDTH}
        anonymizer = cls() if key is None else cls(key=key)
        project_nodes: list[tuple[pd.DataFrame, pd.DataFrame]] = []
        for raw in raws:
            anonymizer._collect_secrets(raw)
            anonymizer.original_project_ids.update(_project_ids_in(raw))
            for (table, column), kind in CODES.items():
                frame = raw.table(table)
                if column in frame.columns:
                    found[kind].update(value for value in frame[column] if value)
            project_nodes.append((raw.table("PROJWBS"), raw.table("PROJECT")))
        codes = {value for values in found.values() for value in values}
        anonymizer.original_codes = codes & set(anonymizer.secrets_)
        for kind, values in found.items():
            for value in sorted(values):
                anonymizer.code(kind, value)
        for value in sorted(anonymizer.original_project_ids):
            anonymizer.project_id(value)
        for wbs, _project in project_nodes:
            anonymizer._map_wbs_paths(wbs)
        return anonymizer

    # --- what must not come out ------------------------------------------------------------

    def _collect_secrets(self, raw: RawXer) -> None:
        for position in (3, 4, 5):  # ERMHDR fields: version, date, "Project", login, full name, database
            if len(raw.header) > position and raw.header[position] not in GENERIC_HEADER:
                self.secrets_.setdefault(raw.header[position], "ERMHDR")
        if raw.source:
            name = re.split(r"[/\\]", raw.source)[-1]
            stem = name.rsplit(".", 1)[0]
            # a stem that is a word of xerscope's own output ("Baseline.xml") names no project and would
            # be found in every table: the full name is still searched, the bare word is not
            parts = (name,) if stem.lower() in GENERIC_FILE_STEMS else (name, stem)
            if stem.lower() not in GENERIC_FILE_STEMS:
                self.secrets_.setdefault(stem, "file name")
            self.file_names.update(part for part in parts if _is_text(part))
        kept_values: set[str] = set()
        for table, frame in raw.tables.items():
            keep = KEEP.get(table, frozenset())
            for column in frame.columns:
                values = {value.strip() for value in frame[column] if _is_text(value.strip())}
                if column in keep:
                    kept_values |= values
                else:
                    for value in values:
                        self.secrets_.setdefault(value, f"{table}.{column}")
        # a value also written in a kept column (an enumeration, a unit) is not a secret of the file
        self.kept |= kept_values
        for value in kept_values:
            self.secrets_.pop(value, None)

    def _holds_original(self, new: str) -> bool:
        """Whether ``new`` (a code or GUID drawn here) holds a text value of the originals."""
        return any(
            new[start:end] in self.secrets_ for start in range(len(new)) for end in range(start + 3, len(new) + 1)
        )

    def leaks(self, fields: Iterable[str]) -> dict[str, int]:
        """Original text values found among ``fields``, counted by the column they came from."""
        found: dict[str, int] = {}
        values = list(fields)
        inside: dict[str, str | None] = {}
        longest = max(map(len, self.secrets_), default=0)
        for value in values:
            origin = self.secrets_.get(value.strip())
            if origin is None and value not in self.kept and _is_text(value):
                if value not in inside:
                    secret = next(self._secrets_inside(value, longest), None)
                    inside[value] = self._code_inside(value) or (self.secrets_[secret] if secret else None)
                origin = inside[value]
            if origin is not None:
                found[origin] = found.get(origin, 0) + 1
        if self.file_names:
            # a name is not a word of the output: found whole, whatever surrounds it, in any case
            names = "|".join(re.escape(name) for name in sorted(self.file_names, key=len, reverse=True))
            pattern = re.compile(rf"(?<![A-Za-z0-9])(?:{names})(?![A-Za-z0-9])", re.IGNORECASE)
            hits = sum(1 for value in values if pattern.search(value))
            if hits:
                found["file name"] = max(found.get("file name", 0), hits)
        return found

    def _secrets_inside(self, value: str, longest: int) -> Iterator[str]:
        """Text values of the originals inside ``value`` (not ``value`` itself), each starting and
        ending where a run of letters and digits does: "Night Shift" in "calendar 'Night Shift' has
        no working time", not "Shift" in "Shifts"."""
        bounds = [p for p in range(len(value) + 1) if p in (0, len(value)) or not value[p - 1 : p + 1].isalnum()]
        for i, start in enumerate(bounds):
            for end in bounds[i + 1 :]:
                if end - start > longest:
                    break
                part = value[start:end]
                if end - start >= 3 and part != value and part in self.secrets_ and part not in OWN_WORDS:
                    yield part

    def _code_inside(self, value: str) -> str | None:
        """Where the original code found inside ``value`` came from ("Activity C3050", "XA69C30507")."""
        for start in range(len(value)):
            for end in range(start + 3, len(value) + 1):
                if value[start:end] in self.original_codes:
                    return self.secrets_[value[start:end]]
        return None

    def _refuse_leaks(self, fields: Iterable[str], what: str) -> None:
        found = self.leaks(fields)
        if found:
            where = ", ".join(f"{origin} ({count})" for origin, count in sorted(found.items()))
            raise LeakError(f"{what} not written: it still holds values of {where}")

    # --- codes -----------------------------------------------------------------------------

    def code(self, kind: str, original: str) -> str:
        """The new code: X<kind> and the first hex digits of HMAC-SHA256(key, "<kind>:<original>"),
        or of "<kind>:<original>:<n>" for the first n whose code holds no original value."""
        if not original:
            return ""
        mapping = self.codes.setdefault(kind, {})
        if original not in mapping:
            for draw in range(DRAWS):
                message = f"{kind}:{original}" if draw == 0 else f"{kind}:{original}:{draw}"
                digest = hmac.new(self.key, message.encode(), hashlib.sha256).hexdigest().upper()
                new = f"X{kind}{digest[: WIDTH[kind]]}"
                if not self._holds_original(new):
                    break
            else:
                raise CodeClash(f"no {kind} code holding no original value in {DRAWS} draws")
            taken = self.taken.setdefault(kind, set())
            if new in taken:
                raise CodeClash(f"two {kind} codes would both become {new}: reload the page for a new key")
            taken.add(new)
            mapping[original] = new
        return mapping[original]

    def project_id(self, original: str) -> str:
        """The new proj_id: 9 digits from HMAC-SHA256(key, "proj_id:<original>"), or of
        "proj_id:<original>:<n>" for the first n whose id is no original proj_id of the files read."""
        if not original:
            return ""
        if original not in self.project_ids:
            for draw in range(DRAWS):
                message = f"proj_id:{original}" if draw == 0 else f"proj_id:{original}:{draw}"
                digest = hmac.new(self.key, message.encode(), hashlib.sha256).digest()
                new = str(PROJECT_ID_LOW + int.from_bytes(digest[:8], "big") % PROJECT_ID_SPAN)
                if new not in self.original_project_ids:
                    break
            else:
                raise CodeClash(f"no project id other than the originals in {DRAWS} draws")
            if new in self.project_ids.values():
                raise CodeClash(f"two project ids would both become {new}: reload the page for a new key")
            self.project_ids[original] = new
        return self.project_ids[original]

    def _project_ids(self, value: object) -> object:
        """A table cell of project ids (one, or comma-separated) with the new ids; blanks and
        ``NOT_AN_ID`` kept."""
        if not isinstance(value, str):
            return value if value is None or pd.isna(value) else self.project_id(str(value))
        if value.strip() in NOT_AN_ID:
            return value
        return ",".join(self.project_id(item.strip()) for item in value.split(","))

    def guid(self, original: str) -> str:
        if not original:
            return ""
        if original not in self.guids:
            for _ in range(DRAWS):
                new = base64.b64encode(secrets.token_bytes(16)).decode("ascii").rstrip("=")
                if not self._holds_original(new):
                    break
            else:
                raise CodeClash(f"no GUID holding no original value in {DRAWS} draws")
            self.guids[original] = new
        return self.guids[original]

    def _map_wbs_paths(self, wbs: pd.DataFrame) -> None:
        """Original WBS path (short names joined by ".", project node left out, as xerscope reads it) -> new."""
        if wbs.empty or "wbs_id" not in wbs.columns:
            return
        by_id = wbs.set_index("wbs_id")
        for wbs_id in by_id.index:
            chain, seen, current = [], set(), wbs_id
            while current in by_id.index and current not in seen:
                seen.add(current)
                row = by_id.loc[current]
                if isinstance(row, pd.DataFrame) or row.get("proj_node_flag") == "Y":
                    break
                chain.append(row.get("wbs_short_name", ""))
                current = row.get("parent_wbs_id", "")
            chain.reverse()
            self.wbs_paths[".".join(chain)] = ".".join(self.code("W", short) for short in chain)

    # --- XER -------------------------------------------------------------------------------

    def table(self, name: str, frame: pd.DataFrame) -> pd.DataFrame | None:
        """The anonymised table, or None when the table is left out."""
        if name not in KEEP:
            self.report.dropped_tables.add(name)
            return None
        out = frame.copy()
        new_codes = {}
        for column in frame.columns:
            if (name, column) in CODES:
                kind = CODES[name, column]
                if name == "PROJWBS" and "proj_node_flag" in frame.columns:
                    # the project node's short name is the project code
                    is_node = frame["proj_node_flag"] == "Y"
                    out[column] = [
                        self.code("P" if node else kind, value)
                        for node, value in zip(is_node, frame[column], strict=True)
                    ]
                else:
                    out[column] = [self.code(kind, value) for value in frame[column]]
                new_codes[column] = out[column]
        for column in frame.columns:
            if (name, column) in CODES:
                continue
            if (name, column) in LABELS:
                prefix, source = LABELS[name, column]
                codes = new_codes.get(source, frame[source] if source in frame.columns else None)
                out[column] = [f"{prefix} {code}" if code else "" for code in codes] if codes is not None else ""
            elif column in KEEP[name]:
                out[column] = self._kept(column, frame[column])
            elif column in MONEY.get(name, ()):
                out[column] = ["0" if value.strip() else "" for value in frame[column]]
            elif column in GUIDS:
                out[column] = [self.guid(value) for value in frame[column]]
            else:
                if (frame[column] != "").any():
                    self.report.emptied_columns.add(f"{name}.{column}")
                out[column] = ""
        return out

    def _kept(self, column: str, values: pd.Series) -> pd.Series | list[str]:
        """A kept column as written: the calendar data checked, the project ids renewed."""
        if column == "clndr_data":
            self._check_calendar(values)
        elif is_project_id_column(column):
            return [self.project_id(value) for value in values]
        return values

    @staticmethod
    def _check_calendar(values: pd.Series) -> None:
        words = set()
        for value in values:
            words |= set(re.findall(r"[A-Za-z_]{2,}", value))
        if words - CALENDAR_WORDS:
            raise LeakError(f"CALENDAR.clndr_data holds {len(words - CALENDAR_WORDS)} unknown word(s): not written")

    def xer(self, raw: RawXer) -> bytes:
        """The anonymised file: same tables order, columns and encoding as the original."""
        header = list(raw.header) + [""] * max(0, 8 - len(raw.header))
        header[2:5] = ["Project", "ANON", "ANON"]
        header[5] = "dbxDatabaseNoName"
        lines = ["\t".join(["ERMHDR", *header])]
        fields: list[str] = list(header)
        for name, frame in raw.tables.items():
            out = self.table(name, frame)
            if out is None:
                continue
            lines += [f"%T\t{name}", "\t".join(["%F", *out.columns])]
            fields.extend(out.columns)
            for row in out.itertuples(index=False):
                lines.append("\t".join(["%R", *row]))
                fields.extend(row)
        lines.append("%E")
        self._refuse_leaks(fields, "anonymized XER")
        encoding = "cp1252" if raw.encoding.startswith("cp1252") else "utf-8"
        return ("\r\n".join(lines) + "\r\n").encode(encoding, errors="strict")

    def xer_name(self, raw: RawXer, data_date: pd.Timestamp | None) -> str:
        project = raw.table("PROJECT")
        code = self.code("P", project["proj_short_name"].iloc[0]) if "proj_short_name" in project.columns else "XP"
        return f"{code}_{data_date:%Y-%m-%d}.xer" if data_date is not None else f"{code}.xer"

    # --- tables shown by the app ---------------------------------------------------------------

    CODE_COLUMNS = {"task_code": "task_code", "pred_code": "pred_code", "succ_code": "succ_code"}
    NAME_COLUMNS = {
        "task_name": "task_code",
        "pred_name": "pred_code",
        "succ_name": "succ_code",
        "bl_name": "task_code",
    }
    # columns xerscope writes itself (statuses, P6 enumerations, rule reasons, check names)
    # lists of Activity IDs a rule writes: "B2, C3" (drives, lagged_from) or "B2 (FS), C3 (SS)" (ahead_of)
    CODE_LIST_COLUMNS = frozenset({"drives", "lagged_from", "ahead_of"})
    SAFE_TEXT = frozenset(
        {"type", "status", "constraint", "reason", "check_id", "check", "check_status", "pred_type", "status_now",
         "differences", "previous", "now", "set", "pred_status", "succ_status",
         "id", "group", "result", "count", "target"}
    )  # fmt: skip

    def _notes(self, notes: pd.Series) -> list[str]:
        """The notes of the rules: they name an activity by its Activity ID, a file by its name
        (``Baseline.label``) and a project by its id ("proj_id 370", ``Baseline.source``); all three
        are renamed. A note can also copy an error message (``checks.run_metric``): any other value
        of the originals in it is hidden."""
        names = dict(self.codes.get("A", {}))
        names.update({stem: "file" for stem, origin in self.secrets_.items() if origin == "file name"})
        texts = [
            PROJECT_ID_IN_NOTE.sub(lambda match: f"proj_id {self.project_id(match.group(1))}", note)
            if isinstance(note, str)
            else ""
            for note in notes
        ]
        if names:
            found = "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))
            pattern = re.compile(rf"(?<![\w.-])(?:{found})(?![\w-])")
            texts = [pattern.sub(lambda match: names[match.group(0)], note) for note in texts]
        longest = max(map(len, self.secrets_), default=0)
        return [self._hide(note, longest) for note in texts]

    def _hide(self, note: str, longest: int) -> str:
        """``note`` with every text value of the originals found in it replaced by ``HIDDEN``, longest
        first: an error message copied into a note names what it failed on."""
        if not _is_text(note):
            return note
        if note in self.secrets_ and note not in OWN_WORDS:
            return HIDDEN
        for secret in sorted(set(self._secrets_inside(note, longest)), key=len, reverse=True):
            note = note.replace(secret, HIDDEN)
        return note

    def _code_list(self, text: object) -> str:
        if not isinstance(text, str) or not text:
            return ""
        items = []
        for item in text.split(", "):
            code, bracket, rest = item.partition(" (")
            new = self.codes.get("A", {}).get(code, "")
            items.append(f"{new}{bracket}{rest}" if new else "")
        return ", ".join(items)

    def _renamed(self, column: str, values: pd.Series) -> list | None:
        """The notes or the project ids of ``frame`` renamed; None for any other column."""
        if column == "note":
            return self._notes(values)
        if is_project_id_column(column):
            return [self._project_ids(value) for value in values]
        return None

    def frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        """A table of activities or relationships with new codes and names; other text emptied."""
        out = frame.copy()
        for column in frame.columns:
            values = frame[column]
            if column in self.CODE_COLUMNS:
                out[column] = [
                    self.codes.get("A", {}).get(value, "") if isinstance(value, str) else "" for value in values
                ]
            elif column in self.NAME_COLUMNS:
                continue
            elif (renamed := self._renamed(column, values)) is not None:
                out[column] = renamed
            elif column in ("wbs_code", "pred_wbs_code", "succ_wbs_code"):
                out[column] = [self.wbs_paths.get(value, "") if isinstance(value, str) else "" for value in values]
            elif column in self.CODE_LIST_COLUMNS:
                out[column] = [self._code_list(value) for value in values]
            elif column in self.SAFE_TEXT or not (values.dtype == object or pd.api.types.is_string_dtype(values)):
                continue
            elif values.map(lambda value: isinstance(value, str)).any():
                self.report.emptied_columns.add(f"table.{column}")
                out[column] = ""
        for column in MONEY_COLUMNS & set(out.columns):
            out[column] = [self._zeroed(value) for value in out[column]]
        for column, source in self.NAME_COLUMNS.items():
            if column in frame.columns:
                codes = out[source] if source in out.columns else pd.Series("", index=out.index)
                out[column] = [f"Activity {code}" if code else "" for code in codes]
        self._refuse_frame_leaks(out, "table")
        return out

    def csv(self, frame: pd.DataFrame) -> bytes:
        return csv_bytes(self.frame(frame))

    def zip_xers(self, files: Iterable[tuple[RawXer, pd.Timestamp | None]]) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for raw, data_date in files:
                archive.writestr(self.xer_name(raw, data_date), self.xer(raw))
        return buffer.getvalue()

    # --- diagnostic tables (Debug page) -------------------------------------------------------

    DIAGNOSTIC_CODES = {
        "task_code": "A",
        "pred_code": "A",
        "succ_code": "A",
        "rsrc_short_name": "R",
        "proj_short_name": "P",
    }
    # Cost figures of the "Costs in the file" block: 0 as the anonymised XER holds them (MONEY),
    # "absent" and blanks kept.
    DIAGNOSTIC_MONEY = ("rows_with_cost", "target_cost_total", "cost_per_qty_min", "cost_per_qty_max")

    @staticmethod
    def _zeroed(value: object) -> object:
        return value if isinstance(value, str) or pd.isna(value) else value * 0

    def _renew_project_ids(self, out: pd.DataFrame) -> None:
        """The project id columns of ``out``, and those listing ids (``PROJECT_ID_LIST_COLUMNS``), renewed."""
        for column in out.columns:
            if is_project_id_column(column) or column in PROJECT_ID_LIST_COLUMNS:
                out[column] = [self._project_ids(value) for value in out[column]]

    def _refuse_frame_leaks(self, out: pd.DataFrame, where: str) -> None:
        """``_refuse_leaks`` on the column names and every cell of ``out``."""
        cells = (str(value) for value in out.astype(str).to_numpy().ravel())
        self._refuse_leaks([*map(str, out.columns), *cells], where)

    def zip_frames(self, frames: dict[str, pd.DataFrame]) -> bytes:
        """CSV of each frame, with the codes of ``DIAGNOSTIC_CODES``, the WBS codes and the project ids
        renamed as in the XER extract and the figures of ``DIAGNOSTIC_MONEY`` set to 0.

        No other column changes: the caller selects ids, dates, durations, flags and P6
        enumerations only. Every cell of every table is still checked against the originals'
        text values; one match and nothing is written (``LeakError``).
        """
        outputs = {}
        for name, frame in frames.items():
            out = frame.copy()
            for column, kind in self.DIAGNOSTIC_CODES.items():
                if column in out.columns:
                    mapping = self.codes.get(kind, {})
                    out[column] = [mapping.get(value, "") if isinstance(value, str) else "" for value in out[column]]
            if "wbs_code" in out.columns:
                out["wbs_code"] = [self.wbs_paths.get(v, "") if isinstance(v, str) else "" for v in out["wbs_code"]]
            self._renew_project_ids(out)
            for column in self.DIAGNOSTIC_MONEY:
                if column in out.columns:
                    out[column] = [self._zeroed(value) for value in out[column]]
            self._refuse_frame_leaks(out, f"table {name}")
            outputs[name] = out
        return zip_frames(outputs, "csv")
