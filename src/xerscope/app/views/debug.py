import hashlib
import re
from functools import partial

import pandas as pd
import streamlit as st

from xerscope.analysis import query
from xerscope.analysis.cpm import ScheduleError
from xerscope.analysis.evm import (
    baseline_changes,
    earned_schedule,
    schedule_gap_by_status,
    update_and_baseline_of_code,
    weekly_gains,
    window_weeks,
)
from xerscope.analysis.forensics import engine_gap_wd
from xerscope.app import diagnostic, ui, xml_baselines
from xerscope.app.baseline_export import (
    baseline_export,
    export_contents,
)
from xerscope.app.baselines import (
    baseline_for,
    data_identity,
    snapshot_identity,
)
from xerscope.app.cache import (
    memo,
)
from xerscope.app.code_picker import pick_code_filter
from xerscope.app.downloads import (
    anonymous_exports,
    built_download,
    sources_of,
)
from xerscope.app.loading import (
    lexicon_and_errors,
)
from xerscope.app.session import (
    data_locked,
)
from xerscope.app.state import (
    page_header,
    require_store,
    snapshot_picker,
    standards,
)
from xerscope.export import zip_frames

store = require_store()
top = st.container()  # header above the picker, as on the other pages
snapshot = snapshot_picker(store, "Update", key="debug_snap")
baseline = baseline_for(snapshot)
with top:
    page_header(
        "Debug",
        store,
        snapshot,
        lead="What xerscope read from this file and what it decided, to hold against P6. Read-only. "
        "Columns keep the XER and analysis field names.",
    )

NO_ROW = "No row: nothing in the file read selects a row of this block."


def table(frame: pd.DataFrame, *, key: str, reason: str = NO_ROW, **kwargs) -> None:
    """A block's grid, kept when it is empty because its header is the information, with ``reason`` under it then.

    ``reason`` says why nothing is listed and how the block is read: the file table it comes from, the condition
    that selects its rows.
    """
    ui.table(frame, raw_labels=True, reading="debug", key=key, **kwargs)
    ui.caption_why_empty(frame, reason)


def zip_tag(anonymous: bool, *extra: object) -> tuple:
    """What a zip is built from: files, projects, update, the anonymous switch, then ``extra``."""
    return (*data_identity(), *snapshot_identity(snapshot), anonymous, *extra)


p6_standard = standards()["P6"]
guid_match = memo(
    ("debug_guid_match", *snapshot_identity(snapshot)),
    diagnostic.guid_match_table,
    snapshot,
    baseline_for(snapshot, link=False),
    store.previous(snapshot),
)
try:
    frames = memo(
        ("debug", snapshot.source, str(snapshot.data_date), repr(p6_standard)),
        partial(
            diagnostic.diagnostic_frames,
            updates=[snapshot.source for snapshot in store],
            guid_link=st.session_state.get("guid_link", False),
        ),
        snapshot,
        baseline,
        p6_standard,
    )
except ScheduleError as exc:
    st.error(f"Cannot schedule this file: {ui.md_text(exc)}", icon=":material/block:")
    st.stop()

with st.expander("1 · Scheduling options (SCHEDOPTIONS, PROJECT)", expanded=True, key="debug_options"):
    options = frames["01_options"]
    defaulted = options[options["origin"] == diagnostic.DEFAULTED]
    if not defaulted.empty:
        st.warning(
            "Blank in the file, default applied: " + ", ".join(defaulted["option"]) + ". "
            "Check the Schedule Options dialog in P6 before comparing dates.",
            icon=":material/warning:",
        )
    table(options, key="debug_01_options")
    if baseline is not None and not baseline.is_planned and baseline.snapshot is not snapshot:
        compared = diagnostic.options_comparison(snapshot, baseline.snapshot)
        differing = compared.loc[~compared["same"], "option"]
        if differing.empty:
            st.caption("Against the baseline file: the same value applied for every option.")
        else:
            st.warning(
                "Not the same in this update and in its baseline file: " + ", ".join(differing) + ". "
                "Dates and floats of two files scheduled with different options do not compare.",
                icon=":material/warning:",
            )
        table(compared, key="debug_01_options_vs_baseline")
    st.caption(
        "Projects in the file: sum_base_proj_id is the project's P6 Project Baseline, orig_proj_id the project "
        "a baseline copy was made from."
    )
    table(frames["01b_projects"], key="debug_01b_projects")

# keyed blocks: a label holds a count that changes with the update, and Streamlit keys an
# unkeyed expander on its label, so it would redraw closed
with st.expander(f"2 · Expected finish ({len(frames['02_expected_finish'])} tasks)", key="debug_expected_finish"):
    st.caption(
        "ef_recalc is the expected finish, or the early start when the expected finish falls before it "
        "(remaining_set_to_0). An FF / SF bound later than that wins instead (rem_override_hr blank)."
    )
    table(
        frames["02_expected_finish"],
        key="debug_02_expected_finish",
        reason="No task has an expected finish (TASK.expect_end_date): the table lists the tasks that carry one, "
        "beside the dates P6 stored and the ones recalculated.",
    )
    st.caption(
        "Counts only (no Task ID, no date): the unfinished tasks above by status, type, constraints, "
        "expected finish after the primary constraint date, expected finish off the working time of the "
        "task's calendar, and an FF / SF predecessor. stored_identical: every date and float P6 stored "
        "is the recalculated one; stored_different: at least one is not."
    )
    table(
        frames["02b_expected_finish_forms"],
        key="debug_02b_expected_finish_forms",
        reason="Nothing to count: the table counts the unfinished tasks of the table above, and none is listed there.",
    )

int01, int03 = frames["03_int01_recalculation"], frames["03_int03_assignments"]
with st.expander(
    f"3 · INT-01 / INT-03 differences ({len(int01)} tasks, {len(int03)} assignments)", key="debug_differences"
):
    st.caption("Stored vs recalculated, and the inputs the recalculation read. Facts only.")
    if int01.empty:
        st.caption("INT-01: every stored date and total float is reproduced.")
    else:
        table(int01, max_height=ui.TABLE_SHORT, key="debug_03_int01_recalculation")
    if int03.empty:
        st.caption("INT-03: every stored assignment date is reproduced.")
    else:
        table(int03, max_height=ui.TABLE_SHORT, key="debug_03_int03_assignments")
    gap_wd = engine_gap_wd(snapshot)
    st.caption(
        "Delay analysis reads the recalculated finish. Recalculated finish against the latest finish stored "
        f"in the file: {'not known' if pd.isna(gap_wd) else f'{gap_wd:+.1f} wd'} (0 = reproduced, negative = "
        "recalculated later). Below, the unfinished tasks where the recalculated early dates first differ from "
        "the stored ones (none of their predecessors differs: what differs downstream follows from them): "
        "the steps that lead to them and what each removed, the tasks, then the same tasks counted by form, "
        "with no Task ID and no date."
    )
    table(frames["03a_departure_steps"], key="debug_03a_departure_steps")
    if frames["03b_departures"].empty:
        st.caption("Every stored early date is reproduced.")
    else:
        table(frames["03b_departures"], max_height=ui.TABLE_SHORT, key="debug_03b_departures")
        table(frames["03c_departure_forms"], key="debug_03c_departure_forms")

with st.expander("4 · Check Schedule parameters applied (P6 standard)", key="debug_parameters"):
    st.caption("Targets, x and dialog options of standards/p6.toml, on the tab of the P6 dialog each check sits on.")
    table(frames["04_check_parameters"], key="debug_04_check_parameters")

with st.expander("5 · Baseline and calendars", key="debug_baseline"):
    table(frames["05_baseline"], key="debug_05_baseline")
    st.caption(
        "The baseline each update of the series is measured against, as P6's Maintain Baselines names it: "
        "name (Project ID). kind: in its file, exact (the one it names, from the P6 XML export), probable "
        "(found by its content: a copy of the same generation, or the loaded update it names), chosen in the "
        "window, fallback, planned dates, or none. last_update: P6's Last Update Date of the baseline, when "
        "the file gives one. source: the sentence the pages show."
    )
    table(
        memo(
            ("debug_baseline_used",),
            lambda: xml_baselines.baseline_used_table(store, [baseline_for(update, link=False) for update in store]),
        ),
        key="debug_05_baseline_used",
    )
    st.caption(
        "Every update of the series, by status date: the analysed project (proj_id, add_date 'Date Added') and "
        "the Project Baseline it names (sum_base_proj_id), held by the file or not, and held or not by the "
        "P6 XML baseline file when one is in use (baseline_in_xml_file). use_project_baseline_flag "
        "as stored: unlabelled in the XER data map, read as the Project Details > Settings choice of the "
        "baseline earned value uses (project baseline or each user's primary baseline), unverified. project and "
        "baseline_name: as P6 names them, name (Project ID); baseline_name is blank when neither a loaded file "
        "nor the P6 XML file holds that project: P6 shows it in Project > Assign Baselines of the update's project."
    )
    export = baseline_export()
    xml_held = None if export is None else export[2].baselines
    pointers = diagnostic.baseline_pointers(store, xml_held)
    table(xml_baselines.with_names(pointers, store, xml_held), key="debug_05_baseline_pointers")
    if export is not None:
        st.caption(
            "The baselines of the P6 XML baseline file, in the order of the file: the id an update names "
            "(object_id), the project each was taken from (original_project_id), whether that project names "
            "it as its Project Baseline (project_baseline) and how many updates of the series name it "
            "(updates_naming_it; 0: no update names it)."
        )
        table(
            xml_baselines.xml_baselines_table(export[2], pointers["sum_base_proj_id"]),
            key="debug_05_xml_baselines",
            reason="The P6 XML baseline file holds no baseline: the table has one row per baseline of the file.",
        )
        st.caption(
            "The projects of the P6 XML baseline file, in the order of the file: the id an XER read from one "
            "carries (object_id), its status date (data_date), the date it was added to the database "
            "(date_added), the Project Baseline it names (current_baseline_id) and whether the file holds it, "
            "how many updates of the series were read from it (updates_from_it) and how many have their status "
            "date on the same day (updates_same_status_date)."
        )
        table(
            xml_baselines.xml_projects_table(export[2], store),
            key="debug_05_xml_projects",
            reason="The P6 XML baseline file holds no project: the table has one row per project of the file.",
        )
    st.caption(
        "The baseline found for each update, and what finds it (found_by): in its file; in the "
        "export, under the id it names; a loaded update, when it names the project that update was read from; "
        "or, in the export, the baseline of the version created just before its project when the version "
        "created just after holds a copy of the same baseline (version_before, version_after: by ObjectId, "
        "an order of creation observed in P6 databases, which Oracle does not document). Only the first two "
        "are the baseline P6 measured against. With 'Baseline in each file' the pages measure each update "
        "against the baseline found, the two others announced as probable; with another choice they use the "
        "baseline of the first table of this block. Shown beside it, not applied: the versions of the export "
        "that have the status date of the update, were added to the database once its project was and name a "
        "baseline the export holds (version_same_date) - a copy of the project made at that date carries a copy "
        "of its baseline -, that baseline (its_baseline), and whether it is listed with the status date and the "
        "number of tasks of the one applied (listed_as_applied)."
    )
    table(
        memo(
            ("debug_baseline_resolution",),
            lambda: xml_baselines.resolution_table(store, export_contents(), None if export is None else export[2]),
        ),
        key="debug_05_baseline_resolution",
    )
    st.caption(
        "Tasks of this update that carry the GUID (TASK.guid) of a task of the baseline file or of the "
        "previous update under a new Task ID. P6 links a task to its baseline by Activity ID."
    )
    renumbered_tasks = memo(
        ("debug_renumbered", *snapshot_identity(snapshot)),
        diagnostic.renumbered_table,
        snapshot,
        baseline_for(snapshot, link=False),
        store.previous(snapshot),
    )
    table(
        renumbered_tasks,
        key="debug_05_renumbered",
        reason="No task carries the GUID of a task of the baseline file or of the previous update under a new Task "
        "ID: every task kept its Task ID, or the files hold no GUID, or only blank or repeated ones, to match on.",
    )
    st.caption(
        "How this update's tasks match the baseline file and the previous update, by Activity ID and by GUID: "
        "counts only. renumbered = what 'Link renumbered tasks by GUID' links; gone_guid_absent = tasks gone "
        "whose GUID this update does not carry (deleted, or a copy of the project with new GUIDs)."
    )
    table(
        guid_match,
        key="debug_05_guid_match",
        reason="No baseline file and no previous update to match this update against: the table has one row for "
        "each of the two.",
    )
    table(frames["05_calendars"], key="debug_05_calendars")

with st.expander(f"6 · Load warnings ({len(frames['06_leveling'])} leveled tasks)", key="debug_load_warnings"):
    st.caption(
        "The tasks behind the warnings raised while reading the file. Leveling: open tasks "
        "whose remaining early start (restart_date) differs from the early start. Project finish: "
        "PROJECT.scd_end_date against the tasks that end last."
    )
    for warning in snapshot.warnings:
        st.caption(warning)
    if not frames["06_leveling"].empty:
        table(frames["06_leveling"], max_height=ui.TABLE_SHORT, key="debug_06_leveling")
    table(frames["06_project_finish"], key="debug_06_project_finish")
    table(frames["06_latest_finishes"], key="debug_06_latest_finishes")

with st.expander("7 · Costs in the file (TASKRSRC, PROJCOST)", key="debug_costs"):
    st.caption(
        "Whether the file carries costs: P6 computes its cost-based Schedule Performance Index from them, "
        "xerscope's SPI (labor units) from hours. absent: the column is missing or blank on every row."
    )
    table(
        frames["07_costs"].astype(str), key="debug_07_costs"
    )  # numbers and "absent" in one column: Arrow needs one type

with st.expander("8 · Earned Value settings of the WBS (PROJWBS)", key="debug_ev_settings"):
    st.caption(
        "EV technique (ev_compute_type) and ETC technique (ev_etc_compute_type) of each WBS element. xerscope "
        "computes ETC as the remaining units whatever the technique. ev_etc_user_value is the performance "
        "factor P6 reads when it is entered; a code not identified is shown as stored."
    )
    table(frames["08_etc_techniques"], key="debug_08_etc_techniques")
    table(frames["08_ev_settings"], max_height=ui.TABLE_SHORT, key="debug_08_ev_settings")

with st.expander("9 · XER tables and planned value labor units", key="debug_pv_labor"):
    st.caption(
        "Diagnostic, not used by any KPI. Tables: every %T table of the file with its rows and columns, no cell "
        "value. PV labor units at the status date by task (xerscope) against by baseline assignment (Σ "
        "target_qty x share of the assignment's own dates elapsed; tasks without labor assignment keep "
        "the task value). Resource curves (curv_id) are counted, not modelled. gap_hr = assignment - task."
    )
    table(frames["09_xer_tables"], max_height=ui.TABLE_SHORT, key="debug_09_xer_tables")
    st.caption(
        "Every column of every table of the file, in the file's order, with the rows holding a value in it "
        "(every project of the file): what this export carries, whether xerscope reads it or not."
    )
    table(frames["09_xer_columns"], max_height=ui.TABLE_SHORT, key="debug_09_xer_columns")
    st.caption(
        "TASK columns holding a date or named after a baseline (base_*, bl_*): label in the XER data map v26 "
        "(table TASK), tasks holding a value, earliest and latest date. The data map lists no baseline date "
        "in TASK: such a column is read as stored, its meaning in P6 unverified. Added By and Last Modified By "
        "are counted, never shown."
    )
    table(frames["09_task_dates"], key="debug_09_task_dates")
    if frames["09_udf_fields"].empty:
        st.caption("No user defined field (UDFVALUE) holds a value in the project read.")
    else:
        st.caption(
            "User defined fields holding a value in the project read (UDFTYPE, UDFVALUE): the table of the "
            "objects that carry the field, its data type, its values, how many of them differ, and the tasks "
            "that carry one. A text field of TASK with few different values splits the project as a task code "
            "does. The anonymous download leaves the label out."
        )
        table(frames["09_udf_fields"], key="debug_09_udf_fields")
    if baseline is None or frames["09_pv_labor_check"].empty:
        st.caption("No baseline or no status date: nothing to compare.")
    else:
        table(frames["09_pv_labor_check"], key="debug_09_pv_labor_check")
        table(frames["09_pv_labor_by_status"], key="debug_09_pv_labor_by_status")
        st.caption(
            "Earned Schedule (Lipke): the instant of the plan where PV = EV, on the tasks of the update that have "
            "baseline hours and both EV dates (pv_hr is the update's PV). Plan days from plan_start, the first EV "
            "date: PD to plan_finish, AT to the status date, ES to that instant. Plan time is when at least one "
            "of these tasks' baseline calendars works; a plan day is the project calendar's hours per day. "
            "sv_t_plan_d = ES - AT (negative = behind), spi_t = ES / AT. ev_left_out_hr: earned on tasks without "
            "both EV dates, not in ev_hr. Where the plan asks for no hours, the status date is the ES. "
            "With a task code picked, both tables below hold the tasks of its values only."
        )
        code_filter = pick_code_filter(snapshot, "debug_es")
        part, part_baseline = update_and_baseline_of_code(snapshot, baseline, code_filter)
        part_key = (snapshot.source, str(snapshot.data_date), code_filter)
        schedule = memo(("earned_schedule", *part_key), earned_schedule, part, part_baseline)
        table(pd.DataFrame([schedule.as_row()]), key="debug_09_earned_schedule")
        st.caption(
            "The same tasks by their status in the update: ahead_hr and behind_hr are the positive and the "
            "negative EV - PV of the tasks, summed apart (their sum is ev_hr - pv_hr). planned_finish_passed: "
            "tasks whose EV finish is before the status date. started_on_planned_start: tasks started on the "
            "day of their EV start. P6 stops moving the planned dates of a task once it has started (P6 EPPM "
            "User Guide, Planned Dates): a baseline copied from a project under way keeps the lead or lag of "
            "its started tasks, which these rows size."
        )
        gaps = memo(("schedule_gap_by_status", *part_key), schedule_gap_by_status, part, part_baseline)
        table(
            gaps,
            key="debug_09_schedule_gap_by_status",
            reason="No task of the update has baseline hours and both EV dates: the table counts these tasks by "
            "status.",
        )
        st.caption(
            "The weeks of the four weeks' window of the Earned value page, one by one: hours earned and "
            "planned, plan days gained and elapsed, each week read on the baseline of the update that opens "
            "it. baseline_changed: the update that closes the week names another plan than the one it is "
            "read on. The window's SPI and pace are the ratios of these columns summed. Empty without an "
            "update dated at least 28 days before this one."
        )
        gains = memo(("evm_weekly", code_filter), weekly_gains, store, partial(baseline_for, link=False),
                     st.session_state.get("guid_link", False), code_filter)  # fmt: skip
        table(
            window_weeks(gains, snapshot.data_date, schedule.hours_per_day),
            key="debug_09_window_weeks",
            reason="No update is dated at least 28 days before this one: the four weeks' window holds no week.",
        )
        st.caption(
            "Every update whose baseline is not the previous update's, read on both plans: its time gap in "
            "calendar days on the plan it leaves (gap_old_d) and on the one it takes (gap_new_d), the lag the "
            "change takes out of the cumulative figures (absorbed_d = new - old), the BAC each plan holds, the "
            "tasks the new plan adds or drops, and where each plan comes from. An absorbed lag with the same "
            "BAC: a copy of the project under way, its started tasks' planned dates frozen (P6, Planned Dates). "
            "A BAC that grows: scope added. Empty when every update keeps its predecessor's plan."
        )
        link = st.session_state.get("guid_link", False)
        unlinked = partial(baseline_for, link=False)
        changes = memo(("evm_baseline_changes", code_filter), baseline_changes, store, unlinked, link, code_filter)
        table(
            changes,
            key="debug_09_baseline_changes",
            reason="Every update keeps its predecessor's plan: the table lists the updates whose baseline is not "
            "the previous update's.",
        )
    st.caption(
        "Labor assignments with dates of their own (Original Lag, Planned Start / Finish apart from the "
        "task's), and task dependent assignments on another calendar than their task's."
    )
    table(frames["09_assignment_dates"], key="debug_09_assignment_dates")

NONE = "(none)"
p6_frames: dict = {}
p6_key = None
with st.expander("10 · PV against a P6 export", key="debug_pv_p6"):
    st.caption(
        "Diagnostic, not used by any KPI. Upload the Activities view of P6 saved as CSV (labour units in hours; "
        "XLSX is not read) with Activity ID, Planned Value Labor Units, Earned Value Labor Units and Schedule % "
        "Complete; optional: BL Project Labor Units, Activity Status, BL Project Start / Finish, Planned Start / "
        "Finish. Joined on Activity ID with PV and EV of every baseline task, deleted from the update or not, "
        "and the update's tasks the baseline does not know (PV and EV 0). gap_hr = xerscope - P6, blank "
        "counts as 0. The file stays in this session's memory; the task list is not part of the zip."
    )
    upload = st.file_uploader(
        "P6 Activities export",
        type=diagnostic.P6_EXPORT_SUFFIXES,
        key="debug_p6_export",
        help="The Activities view of P6 saved as CSV (labour units in hours) with Activity ID, Planned Value Labor "
        "Units, Earned Value Labor Units, Schedule % Complete. Use it to hold xerscope's PV and EV against P6's, "
        "task by task; the file stays in this session's memory.",
    )
    if upload is not None and (baseline is None or snapshot.data_date is None):
        st.caption("No baseline or no status date: nothing to compare.")
    elif upload is not None:
        content = upload.getvalue()
        try:
            raw = diagnostic.read_p6_export(upload.name, content)
        except ValueError as exc:
            st.error(ui.md_text(exc), icon=":material/block:")
            raw = None
        if raw is not None:
            columns = diagnostic.p6_export_columns(raw)
            chosen = {}
            for field, column in columns.items():
                if column is None:
                    required = diagnostic.P6_EXPORT_FIELDS[field][1]
                    options = list(raw.columns) if required else [NONE, *raw.columns]
                    picked = st.selectbox(
                        f"Column not found: {field}",
                        options,
                        index=None if required else 0,
                        key=f"debug_p6_{field}",
                        help="The column of your export that carries this field, when its header is not P6's "
                        "default. Pick it once per field; required fields block the comparison until picked.",
                    )
                    if picked is not None and picked != NONE:
                        chosen[field] = picked
            columns = diagnostic.p6_export_columns(raw, chosen)
            tolerance = st.number_input(
                "Gap tolerance (h)",
                min_value=0.0,
                value=diagnostic.PV_P6_TOLERANCE_HR,
                step=0.01,
                format="%.2f",
                key="debug_p6_tolerance",
                help="Difference in hours between xerscope and P6 above which a task is listed as differing "
                "(PV and EV, labour units). Use it to hide rounding gaps; 0 lists every difference.",
            )
            p6_total = st.number_input(
                "PV labor units total shown by P6 (h, optional)",
                value=None,
                step=1.0,
                format="%.2f",
                key="debug_p6_total",
                help="The project PV total P6 shows, to compare with xerscope's sum. "
                "Fill it when the task list of the export is partial.",
            )
            if any(columns[field] is None for field, (_, required) in diagnostic.P6_EXPORT_FIELDS.items() if required):
                st.caption("Choose the missing columns to compare.")
            else:
                digest = hashlib.sha256(content).hexdigest()
                p6_key = (digest, tuple(columns.items()), tolerance, p6_total)
                comparison, notes = memo(
                    ("debug_p6", snapshot.source, str(snapshot.data_date), *p6_key),
                    diagnostic.compare_p6_export,
                    snapshot,
                    baseline,
                    raw,
                    columns,
                    tolerance,
                    p6_total,
                )
                p6_frames = diagnostic.pv_p6_frames(comparison)
                if any(notes.values()):
                    st.warning(
                        f"Set aside: {notes['rows_without_id']} rows without Activity ID, "
                        f"{notes['duplicate_ids']} repeated Activity IDs (first kept), "
                        f"{notes['unreadable_values']} unreadable numbers (counted as 0).",
                        icon=":material/warning:",
                    )
                st.caption(
                    "Totals by group (all = matched + only P6 + only xerscope; the next two cut across them). "
                    "P6 total - export rows: the total typed above less the PV of the export's rows."
                )
                table(comparison.totals, key="debug_10_totals")
                st.caption("PV gap by Schedule % band, xerscope against P6 (absent: no value on that side)")
                table(comparison.cross, key="debug_10_cross")
                st.caption("Tasks in gap, by candidate cause (several can hold for one task)")
                table(comparison.causes, key="debug_10_causes")
                st.caption("Matched tasks by calendar (clndr_id)")
                table(comparison.by_calendar, key="debug_10_by_calendar")
                st.caption("Tasks in gap (PV or EV), largest gap first. On screen only: not in the zip.")
                table(comparison.activities, max_height=ui.TABLE_SHORT, key="debug_10_activities")

with st.expander("11 · Project settings (PROJECT, TASK.complete_pct_type)", key="debug_project_settings"):
    st.caption(
        "Diagnostic, not used by any KPI. Settings of each project of the file as stored; absent: the file has "
        "no such column (sum_base_proj_id and use_project_baseline_flag read blank then). "
        "baseline_names_to_export: number of names only. tasks_*: the project's tasks by % complete type. "
        "Below, what each field is in P6 and where that is written; unverified where no source settles it."
    )
    table(
        frames["11_project_settings"].astype(str), key="debug_11_project_settings"
    )  # flags, dates, counts and "absent": one type for Arrow
    table(diagnostic.project_settings_meaning_table(), key="debug_11_project_settings_meaning")

with st.expander("13 · Calendar detail (CALENDAR.clndr_data, hours per time period)", key="debug_calendars"):
    st.caption(
        "Every calendar of the file as xerscope reads it. Summary: the hours per time period P6 stores "
        "(day_hr_cnt, week_hr_cnt, month_hr_cnt, year_hr_cnt) beside the working time the periods of clndr_data "
        "add up to; hours_per_day_used_for_days divides working hours into days. Week: the working periods of "
        "each weekday (DaysOfWeek, P6 day 1 = Sunday). Exceptions: each dated exception and what it does to the "
        "weekday it replaces. 24:00 is the end of the day."
    )
    calendar_frames = {name: frame for name, frame in frames.items() if name.startswith("13_")}
    table(
        calendar_frames["13_calendar_summary"].astype(str), key="debug_13_calendar_summary"
    )  # numbers, flags and blanks: one type for Arrow
    table(calendar_frames["13_calendar_week"], key="debug_13_calendar_week")
    table(
        calendar_frames["13_calendar_exceptions"],
        max_height=ui.TABLE_SHORT,
        key="debug_13_calendar_exceptions",
        reason="No calendar of the file has an exception (clndr_data Exceptions): every calendar follows the weekly "
        "periods above.",
    )

    built_download(
        "debug_calendars_zip",
        zip_tag(anonymous_exports()),
        "Build calendar detail",
        "Download calendar detail (.zip)",
        f"xerscope_calendars_{ui.stamp(snapshot.data_date)}.zip",
        "application/zip",
        lambda: zip_frames(calendar_frames, "csv"),
        lambda anonymizer: anonymizer.zip_frames(diagnostic.calendar_detail_frames(snapshot, anonymous=True)),
        sources_of(snapshot),
        key="debug_calendars_download",
        build_key="debug_calendars_build",
        icon=":material/calendar_month:",
        help_text="Builds block 13 (each calendar's hours per period, weekday periods, exceptions) as one zip of "
        "CSV files, anonymized when the sidebar switch is on. Use it to check a calendar P6 and xerscope read "
        "differently.",
    )

# not on a deployed instance: the block names the server's folders, the package path and versions
if not data_locked():
    with st.expander("12 · App runtime (where the theme and fonts come from)", key="debug_runtime"):
        st.caption(
            "What Streamlit read at start, to tell an old running copy from a page that did not load the theme. "
            "Config read: no means default theme and fonts, every interface listened on. Package: the copy that "
            "runs; after an update, reload the page with the cache bypassed (Ctrl+Shift+R) if it still looks old."
        )
        table(ui.runtime_table(), key="debug_12_runtime")


def _where(error: str) -> str:
    """ "bad.toml: line 2, column 23": the file and where it fails, never the text an error quotes
    (tomllib names a key or a character; curated/ holds the company's words)."""
    name, _, detail = error.partition(": ")
    where = re.search(r"line \d+, column \d+|byte \d+|(?:group|refuse) #\d+", detail)
    return f"{name}: {where.group(0) if where else 'unreadable'}"


with st.expander("14 · Ask vocabulary (variants generated per source column)", key="debug_ask_variants"):
    # counts only: the groups hold the files' words, written by `xerscope lexicon build` only
    generated = memo(("ask_variants",), query.variants, list(store), baseline=False)
    st.caption(
        "Words of one XER column read as one by the Gantt Ask field (plural, an abbreviation with its dot), "
        "generated in memory from every loaded file; `xerscope lexicon build` writes them as a file."
    )
    variant_counts = pd.DataFrame(list(query.variant_counts(generated).items()), columns=["column", "groups"])
    table(
        variant_counts,
        key="debug_14_ask_variants",
        reason="No word of the loaded files has a variant (a plural, an abbreviation with its dot): the Ask field "
        "reads the words as written.",
    )
    for error in lexicon_and_errors()[1]:  # curated/ files skipped, refusals that cannot apply
        st.warning(ui.md_text(_where(error)))


anonymous = anonymous_exports()
ui.section(
    "Diagnostic",
    "Blocks 1 to 9, 11 and 13 as CSV, and block 10 without its activity list when an export is loaded. With "
    "anonymous exports on, Task IDs, resource codes, WBS codes and project ids are renamed as in the anonymized XER "
    "extract; the tables hold no name or project name. Dates are left as they are.",
)
built_download(
    "debug_zip",
    zip_tag(anonymous, repr(p6_standard), p6_key),
    "Build diagnostic",
    "Download diagnostic (.zip)",
    "xerscope_diagnostic.zip",
    "application/zip",
    lambda: zip_frames({**frames, "05_guid_match": guid_match, **p6_frames}, "csv"),
    lambda anonymizer: anonymizer.zip_frames(
        {
            **diagnostic.diagnostic_frames(
                snapshot,
                baseline,
                p6_standard,
                anonymous=True,
                updates=[snapshot.source for snapshot in store],
                guid_link=st.session_state.get("guid_link", False),
            ),
            "05_guid_match": guid_match,
            **p6_frames,
        },
        diagnostic.own_text(),
    ),
    sources_of(snapshot, baseline=baseline),
    key="debug_download",
    build_key="debug_build",
    icon=":material/folder_zip:",
    help_text="Builds blocks 1 to 9, 11 and 13 as CSV, block 10 without its activity list, as one zip. "
    "Use it to send what xerscope read and decided for this update, without the XER file.",
)
