import hashlib
from functools import partial

import streamlit as st

from xerscope.analysis.cpm import CycleError
from xerscope.app import diagnostic, ui
from xerscope.app.state import (
    anonymous_exports,
    baseline_for,
    data_identity,
    data_locked,
    fetch,
    held,
    hold,
    memo,
    page_header,
    require_store,
    show_download,
    snapshot_picker,
    sources_of,
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


table = partial(ui.table, raw_labels=True)


p6_standard = standards()["P6"]
try:
    frames = memo(
        ("debug", snapshot.source, str(snapshot.data_date), repr(p6_standard)),
        partial(
            diagnostic.diagnostic_frames,
            updates=[s.source for s in store],
            guid_link=st.session_state.get("guid_link", False),
        ),
        snapshot,
        baseline,
        p6_standard,
    )
except CycleError as exc:
    st.error(f"Cannot schedule this file: {exc}", icon=":material/block:")
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
    table(options)
    st.caption(
        "Projects in the file: sum_base_proj_id is the project's P6 Project Baseline, orig_proj_id the project "
        "a baseline copy was made from."
    )
    table(frames["01b_projects"])

# keyed blocks: a label holds a count that changes with the update, and Streamlit keys an
# unkeyed expander on its label, so it would redraw closed
with st.expander(f"2 · Expected finish ({len(frames['02_expected_finish'])} tasks)", key="debug_expected_finish"):
    st.caption(
        "ef_recalc is the expected finish, or the early start when the expected finish falls before it "
        "(remaining_set_to_0). An FF / SF bound later than that wins instead (rem_override_hr blank)."
    )
    table(frames["02_expected_finish"])

int01, int03 = frames["03_int01_recalculation"], frames["03_int03_assignments"]
with st.expander(
    f"3 · INT-01 / INT-03 differences ({len(int01)} tasks, {len(int03)} assignments)", key="debug_differences"
):
    st.caption("Stored vs recalculated, and the inputs the recalculation read. Facts only.")
    if int01.empty:
        st.caption("INT-01: every stored date and total float is reproduced.")
    else:
        table(int01, max_height=480)
    if int03.empty:
        st.caption("INT-03: every stored assignment date is reproduced.")
    else:
        table(int03, max_height=480)

with st.expander("4 · Check Schedule parameters applied (P6 standard)", key="debug_parameters"):
    st.caption("Targets and x of standards/p6.toml, on the tab of the P6 dialog each check sits on.")
    table(frames["04_check_parameters"])

with st.expander("5 · Baseline and calendars", key="debug_baseline"):
    table(frames["05_baseline"])
    st.caption(
        "Every update of the series, by data date: the analysed project (proj_id, add_date 'Date Added') and "
        "the Project Baseline it names (sum_base_proj_id), held by the file or not. use_project_baseline_flag "
        "as stored: unlabelled in the XER data map, read as the Project Details > Settings choice of the "
        "baseline earned value uses (project baseline or each user's primary baseline), unverified."
    )
    table(diagnostic.baseline_pointers(store))
    st.caption(
        "Tasks of this update that carry the GUID (TASK.guid) of a task of the baseline file or of the "
        "previous update under a new Activity ID. P6 links a task to its baseline by Activity ID."
    )
    table(diagnostic.renumbered_table(snapshot, baseline_for(snapshot, link=False), store.previous(snapshot)))
    table(frames["05_calendars"])

with st.expander(f"6 · Load warnings ({len(frames['06_leveling'])} leveled tasks)", key="debug_load_warnings"):
    st.caption(
        "The tasks behind the warnings raised while reading the file. Leveling: open tasks "
        "whose remaining early start (restart_date) differs from the early start. Project finish: "
        "PROJECT.scd_end_date against the tasks that end last."
    )
    for warning in snapshot.warnings:
        st.caption(warning)
    if not frames["06_leveling"].empty:
        table(frames["06_leveling"], max_height=480)
    table(frames["06_project_finish"])
    table(frames["06_latest_finishes"])

with st.expander("7 · Costs in the file (TASKRSRC, PROJCOST)", key="debug_costs"):
    st.caption(
        "Whether the file carries costs: P6 computes its cost-based Schedule Performance Index from them, "
        "xerscope's SPI (labor units) from hours. absent: the column is missing or blank on every row."
    )
    table(frames["07_costs"].astype(str))  # numbers and "absent" in one column: Arrow needs one type

with st.expander("8 · Earned Value settings of the WBS (PROJWBS)", key="debug_ev_settings"):
    st.caption(
        "EV technique (ev_compute_type) and ETC technique (ev_etc_compute_type) of each WBS element. xerscope "
        "computes ETC as the remaining units whatever the technique. ev_etc_user_value is the performance "
        "factor P6 reads when it is entered; a code not identified is shown as stored."
    )
    table(frames["08_etc_techniques"])
    table(frames["08_ev_settings"], max_height=480)

with st.expander("9 · XER tables and planned value labor units", key="debug_pv_labor"):
    st.caption(
        "Diagnostic, not used by any KPI. Tables: every %T table of the file with its rows and columns, no cell "
        "value. PV labor units at the status date by task (xerscope) against by baseline assignment (Σ "
        "target_qty x share of the assignment's own dates elapsed; tasks without labor assignment keep "
        "the task value). Resource curves (curv_id) are counted, not modelled. gap_hr = assignment - task."
    )
    table(frames["09_xer_tables"], max_height=480)
    if frames["09_pv_labor_check"].empty:
        st.caption("No baseline or no status date: nothing to compare.")
    else:
        table(frames["09_pv_labor_check"])
        table(frames["09_pv_labor_by_status"])
    st.caption(
        "Labor assignments with dates of their own (Original Lag, Planned Start / Finish apart from the "
        "task's), and task dependent assignments on another calendar than their task's."
    )
    table(frames["09_assignment_dates"])

NONE = "(none)"
p6_frames: dict = {}
p6_key = None
with st.expander("10 · PV against a P6 export", key="debug_pv_p6"):
    st.caption(
        "Diagnostic, not used by any KPI. Upload the Activities view of P6 saved as CSV (labour units in hours; "
        "XLSX is not read) with Activity ID, Planned Value Labor Units, Earned Value Labor Units and Schedule % "
        "Complete; optional: BL Project Labor Units, Activity Status, BL Project Start / Finish, Planned Start / "
        "Finish. Joined on Activity ID with PV and EV of every baseline activity, deleted from the update or not, "
        "and the update activities the baseline does not know (PV and EV 0). gap_hr = xerscope - P6, blank "
        "counts as 0. The file stays in this session's memory; the activity list is not part of the zip."
    )
    upload = st.file_uploader("P6 Activities export", type=diagnostic.P6_EXPORT_SUFFIXES, key="debug_p6_export")
    if upload is not None and (baseline is None or snapshot.data_date is None):
        st.caption("No baseline or no data date: nothing to compare.")
    elif upload is not None:
        content = upload.getvalue()
        try:
            raw = diagnostic.read_p6_export(upload.name, content)
        except ValueError as exc:
            st.error(str(exc), icon=":material/block:")
            raw = None
        if raw is not None:
            columns = diagnostic.p6_export_columns(raw)
            chosen = {}
            for field, column in columns.items():
                if column is None:
                    required = diagnostic.P6_EXPORT_FIELDS[field][1]
                    options = list(raw.columns) if required else [NONE, *raw.columns]
                    picked = st.selectbox(
                        f"Column not found: {field}", options, index=None if required else 0, key=f"debug_p6_{field}"
                    )
                    if picked is not None and picked != NONE:
                        chosen[field] = picked
            columns = diagnostic.p6_export_columns(raw, chosen)
            tolerance = st.number_input(
                "Gap tolerance (h)", min_value=0.0, value=diagnostic.PV_P6_TOLERANCE_HR, step=0.01, format="%.2f",
                key="debug_p6_tolerance",
            )  # fmt: skip
            p6_total = st.number_input(
                "PV labor units total shown by P6 (h, optional)", value=None, step=1.0, format="%.2f",
                key="debug_p6_total",
            )  # fmt: skip
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
                table(comparison.totals)
                st.caption("PV gap by Schedule % band, xerscope against P6 (absent: no value on that side)")
                table(comparison.cross)
                st.caption("Activities in gap, by candidate cause (several can hold for one activity)")
                table(comparison.causes)
                st.caption("Matched activities by calendar (clndr_id)")
                table(comparison.by_calendar)
                st.caption("Activities in gap (PV or EV), largest gap first. On screen only: not in the zip.")
                table(comparison.activities, max_height=480)

with st.expander("11 · Project settings (PROJECT, TASK.complete_pct_type)", key="debug_project_settings"):
    st.caption(
        "Diagnostic, not used by any KPI. Settings of each project of the file as stored; absent: the file has "
        "no such column (sum_base_proj_id and use_project_baseline_flag read blank then). "
        "baseline_names_to_export: number of names only. tasks_*: the project's tasks by % complete type. "
        "Below, what each field is in P6 and where that is written; unverified where no source settles it."
    )
    table(frames["11_project_settings"].astype(str))  # flags, dates, counts and "absent": one type for Arrow
    table(diagnostic.project_settings_meaning_table())

with st.expander("13 · Calendar detail (CALENDAR.clndr_data, hours per time period)", key="debug_calendars"):
    st.caption(
        "Every calendar of the file as xerscope reads it. Summary: the hours per time period P6 stores "
        "(day_hr_cnt, week_hr_cnt, month_hr_cnt, year_hr_cnt) beside the working time the periods of clndr_data "
        "add up to; hours_per_day_used_for_days divides working hours into days. Week: the working periods of "
        "each weekday (DaysOfWeek, P6 day 1 = Sunday). Exceptions: each dated exception and what it does to the "
        "weekday it replaces. 24:00 is the end of the day."
    )
    calendar_frames = {name: frame for name, frame in frames.items() if name.startswith("13_")}
    table(calendar_frames["13_calendar_summary"].astype(str))  # numbers, flags and blanks: one type for Arrow
    table(calendar_frames["13_calendar_week"])
    table(calendar_frames["13_calendar_exceptions"], max_height=480)

    def calendar_zip_tag(anonymous: bool) -> tuple:
        """What the calendar zip is built from: files, projects, update and the anonymous switch."""
        return (*data_identity(), snapshot.source, str(snapshot.data_date), anonymous)

    if st.button("Build calendar detail", icon=":material/calendar_month:", key="debug_calendars_build"):
        hold(
            st.session_state,
            "debug_calendars_zip",
            calendar_zip_tag(anonymous_exports()),
            fetch(
                st.session_state,
                lambda: zip_frames(calendar_frames, "csv"),
                lambda anonymizer: anonymizer.zip_frames(diagnostic.calendar_detail_frames(snapshot, anonymous=True)),
                sources_of(snapshot),
                prepare=True,
            ),
        )
    calendar_zip = held(st.session_state, "debug_calendars_zip", calendar_zip_tag(anonymous_exports()))
    if calendar_zip is not None:
        show_download(
            calendar_zip,
            "Download calendar detail (.zip)",
            f"xerscope_calendars_{ui.stamp(snapshot.data_date)}.zip",
            "application/zip",
            key="debug_calendars_download",
        )

# not on a deployed instance: the block names the server's folders, the package path and versions
if not data_locked():
    with st.expander("12 · App runtime (where the theme and fonts come from)", key="debug_runtime"):
        st.caption(
            "What Streamlit read at start, to tell an old running copy from a page that did not load the theme. "
            "Config read: no means default theme and fonts, every interface listened on. Package: the copy that "
            "runs; after an update, reload the page with the cache bypassed (Ctrl+Shift+R) if it still looks old."
        )
        table(ui.runtime_table())


def zip_tag(anonymous: bool) -> tuple:
    """What the zip is built from: files, projects, baseline, EV basis, update, P6 export of block 10."""
    return (*data_identity(), snapshot.source, str(snapshot.data_date), repr(p6_standard), anonymous, p6_key)


def build_diagnostic(anonymous: bool) -> None:
    sources = sources_of(snapshot, baseline=baseline)
    fetched = fetch(
        st.session_state,
        lambda: zip_frames({**frames, **p6_frames}, "csv"),
        lambda anonymizer: anonymizer.zip_frames(
            {
                **diagnostic.diagnostic_frames(
                    snapshot,
                    baseline,
                    p6_standard,
                    anonymous=True,
                    updates=[s.source for s in store],
                    guid_link=st.session_state.get("guid_link", False),
                ),
                **p6_frames,
            }
        ),
        sources,
        prepare=True,
    )
    hold(st.session_state, "debug_zip", zip_tag(anonymous), fetched)


anonymous = anonymous_exports()
ui.section(
    "Diagnostic",
    "Blocks 1 to 9, 11 and 13 as CSV, and block 10 without its activity list when an export is loaded. With "
    "anonymous exports on, Task IDs, resource codes and WBS codes are renamed as in the anonymized XER "
    "extract; the tables hold no name or project name. Dates are left as they are.",
)
if st.button("Build diagnostic", icon=":material/folder_zip:", key="debug_build"):
    build_diagnostic(anonymous)
diagnostic_zip = held(st.session_state, "debug_zip", zip_tag(anonymous))
if diagnostic_zip is not None:
    show_download(
        diagnostic_zip, "Download diagnostic (.zip)", "xerscope_diagnostic.zip", "application/zip", key="debug_download"
    )
