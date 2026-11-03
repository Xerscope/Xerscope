"""Anonymised copies of XER exports and of the tables the app lets you download.

Built for sharing: a copy carries no name, code, user or free text of the original, and P6
(and xerscope) compute the same dates, floats and checks on it.

Allowlist, table by table (column meanings: Oracle "XER Import/Export Data Map Guide
(Project)", P6 23):

- ``KEEP``: copied as is. Keys, dates, durations, units, flags and P6 enumerations only.
- ``CODES``: identifiers renamed X<kind><number>, the same original value getting the same
  new code in every file of the set (task_code, WBS, project, resource, role, OBS codes).
- ``LABELS``: names rebuilt from the row's new code ("Activity XA000001").
- ``MONEY``: costs and prices set to 0 (P6 counts an assignment or an expense, not its cost).
- ``GUIDS``: replaced by new random GUIDs, the same original GUID getting the same new one.

Any other column is emptied and any other table left out; both are reported by name. The
ERMHDR line loses the exporting user, his full name and the database name.

Before a file or a table is handed out, every one of its fields is compared with every text
value of the originals that was not kept (``Anonymizer.leaks``): one match and it is refused.
"""

from __future__ import annotations

import base64
import io
import re
import secrets
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field

import pandas as pd

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
GUIDS = {"guid"}
DIGITS = {"A": 6, "W": 4, "P": 3, "R": 4, "L": 3, "O": 3}
# What CalendarData is written with (P6 5.0 to 25.12, every reference file): nothing else may pass.
CALENDAR_WORDS = frozenset({"CalendarData", "DaysOfWeek", "Exceptions", "ShowTotal", "VIEW"})
GENERIC_HEADER = frozenset({"Project", "Project Management", "dbxDatabaseNoName"})


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


@dataclass
class Anonymizer:
    """New codes and the text values to keep out, for one set of XER files (one session)."""

    codes: dict[str, dict[str, str]] = field(default_factory=dict)  # kind -> original -> new
    guids: dict[str, str] = field(default_factory=dict)
    wbs_paths: dict[str, str] = field(default_factory=dict)  # original wbs_code -> new
    secrets_: dict[str, str] = field(default_factory=dict)  # text value -> "TABLE.column" it came from
    report: Report = field(default_factory=Report)

    @classmethod
    def from_raws(cls, raws: Iterable[RawXer]) -> Anonymizer:
        """One pass over the files: codes sorted per kind, so the numbering does not depend on file order."""
        found: dict[str, set[str]] = {kind: set() for kind in DIGITS}
        anonymizer = cls()
        project_nodes: list[tuple[pd.DataFrame, pd.DataFrame]] = []
        for raw in raws:
            anonymizer._collect_secrets(raw)
            for (table, column), kind in CODES.items():
                frame = raw.table(table)
                if column in frame.columns:
                    found[kind].update(value for value in frame[column] if value)
            project_nodes.append((raw.table("PROJWBS"), raw.table("PROJECT")))
        for kind, values in found.items():
            anonymizer.codes[kind] = {
                value: f"X{kind}{n:0{DIGITS[kind]}d}" for n, value in enumerate(sorted(values), 1)
            }
        for wbs, _project in project_nodes:
            anonymizer._map_wbs_paths(wbs)
        anonymizer._check_codes_are_new()
        return anonymizer

    # --- what must not come out ------------------------------------------------------------

    def _collect_secrets(self, raw: RawXer) -> None:
        for position in (3, 4, 5):  # ERMHDR fields: version, date, "Project", login, full name, database
            if len(raw.header) > position and raw.header[position] not in GENERIC_HEADER:
                self.secrets_.setdefault(raw.header[position], "ERMHDR")
        if raw.source:
            stem = raw.source.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            self.secrets_.setdefault(stem, "file name")
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
        for value in kept_values:
            self.secrets_.pop(value, None)

    def _check_codes_are_new(self) -> None:
        for mapping in self.codes.values():
            clash = set(mapping.values()) & set(self.secrets_)
            if clash:
                raise LeakError(f"{len(clash)} new code(s) equal an original value; rename the X prefix")

    def leaks(self, fields: Iterable[str]) -> dict[str, int]:
        """Original text values found among ``fields``, counted by the column they came from."""
        found: dict[str, int] = {}
        for value in fields:
            origin = self.secrets_.get(value.strip())
            if origin is not None:
                found[origin] = found.get(origin, 0) + 1
        return found

    def _refuse_leaks(self, fields: Iterable[str], what: str) -> None:
        found = self.leaks(fields)
        if found:
            where = ", ".join(f"{origin} ({count})" for origin, count in sorted(found.items()))
            raise LeakError(f"{what} not written: it still holds values of {where}")

    # --- codes -----------------------------------------------------------------------------

    def code(self, kind: str, original: str) -> str:
        """The new code; one never seen in the files gets the next number of its kind."""
        if not original:
            return ""
        mapping = self.codes.setdefault(kind, {})
        if original not in mapping:
            mapping[original] = f"X{kind}{len(mapping) + 1:0{DIGITS[kind]}d}"
        return mapping[original]

    def guid(self, original: str) -> str:
        if not original:
            return ""
        if original not in self.guids:
            self.guids[original] = base64.b64encode(secrets.token_bytes(16)).decode("ascii").rstrip("=")
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
                if column == "clndr_data":
                    self._check_calendar(frame[column])
            elif column in MONEY.get(name, ()):
                out[column] = ["0" if value.strip() else "" for value in frame[column]]
            elif column in GUIDS:
                out[column] = [self.guid(value) for value in frame[column]]
            else:
                if (frame[column] != "").any():
                    self.report.emptied_columns.add(f"{name}.{column}")
                out[column] = ""
        return out

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
            for row in out.itertuples(index=False):
                lines.append("\t".join(["%R", *row]))
                fields.extend(row)
        lines.append("%E")
        self._refuse_leaks(fields, "anonymised XER")
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
         "differences", "previous", "now"}
    )  # fmt: skip

    def _code_list(self, text: object) -> str:
        if not isinstance(text, str) or not text:
            return ""
        items = []
        for item in text.split(", "):
            code, bracket, rest = item.partition(" (")
            new = self.codes.get("A", {}).get(code, "")
            items.append(f"{new}{bracket}{rest}" if new else "")
        return ", ".join(items)

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
            elif column == "wbs_code":
                out[column] = [self.wbs_paths.get(value, "") if isinstance(value, str) else "" for value in values]
            elif column in self.CODE_LIST_COLUMNS:
                out[column] = [self._code_list(value) for value in values]
            elif column in self.SAFE_TEXT or not (values.dtype == object or pd.api.types.is_string_dtype(values)):
                continue
            elif values.map(lambda value: isinstance(value, str)).any():
                self.report.emptied_columns.add(f"table.{column}")
                out[column] = ""
        for column, source in self.NAME_COLUMNS.items():
            if column in frame.columns:
                codes = out[source] if source in out.columns else pd.Series("", index=out.index)
                out[column] = [f"Activity {code}" if code else "" for code in codes]
        self._refuse_leaks((str(value) for value in out.astype(str).to_numpy().ravel()), "table")
        return out

    def csv(self, frame: pd.DataFrame) -> bytes:
        return self.frame(frame).to_csv(index=False).encode("utf-8-sig")

    def zip_xers(self, files: Iterable[tuple[RawXer, pd.Timestamp | None]]) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for raw, data_date in files:
                archive.writestr(self.xer_name(raw, data_date), self.xer(raw))
        return buffer.getvalue()

    # --- diagnostic tables (Debug page) -------------------------------------------------------

    DIAGNOSTIC_CODES = {"task_code": "A", "pred_code": "A", "succ_code": "A", "rsrc_short_name": "R"}

    def zip_frames(self, frames: dict[str, pd.DataFrame]) -> bytes:
        """CSV of each frame, with the codes of ``DIAGNOSTIC_CODES`` renamed as in the XER extract.

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
            self._refuse_leaks((str(value) for value in out.astype(str).to_numpy().ravel()), f"table {name}")
            outputs[f"{name}.csv"] = out.to_csv(index=False).encode("utf-8-sig")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for file_name, data in outputs.items():
                archive.writestr(file_name, data)
        return buffer.getvalue()
