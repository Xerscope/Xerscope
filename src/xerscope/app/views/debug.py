from functools import partial

import streamlit as st

from xerscope.analysis.cpm import CycleError
from xerscope.app import diagnostic, ui
from xerscope.app.state import (
    anonymous_exports,
    baseline_for,
    data_identity,
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
        baseline,
        lead="What xerscope read from this file and what it decided, to hold against P6. Read-only. "
        "Columns keep the XER and analysis field names.",
    )


table = partial(ui.table, raw_labels=True)


p6_standard = standards()["P6"]
try:
    frames = memo(
        ("debug", snapshot.source, str(snapshot.data_date), repr(p6_standard)),
        diagnostic.diagnostic_frames,
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


def zip_tag(anonymous: bool) -> tuple:
    """What the zip is built from, as the frames' memo key: files, projects, baseline, EV basis, update."""
    return (*data_identity(), snapshot.source, str(snapshot.data_date), repr(p6_standard), anonymous)


def build_diagnostic(anonymous: bool) -> None:
    sources = sources_of(snapshot, baseline=baseline)
    fetched = fetch(
        st.session_state,
        lambda: zip_frames(frames, "csv"),
        lambda anonymizer: anonymizer.zip_frames(
            diagnostic.diagnostic_frames(snapshot, baseline, p6_standard, anonymous=True)
        ),
        sources,
        prepare=True,
    )
    hold(st.session_state, "debug_zip", zip_tag(anonymous), fetched)


anonymous = anonymous_exports()
ui.section(
    "Diagnostic",
    "Blocks 1 to 9 as CSV. With anonymous exports on, Task IDs, resource codes and WBS codes are renamed "
    "as in the anonymized XER extract; the tables hold no name or project name. Dates are left as they are.",
)
if st.button("Build diagnostic", icon=":material/folder_zip:", key="debug_build"):
    build_diagnostic(anonymous)
diagnostic_zip = held(st.session_state, "debug_zip", zip_tag(anonymous))
if diagnostic_zip is not None:
    show_download(
        diagnostic_zip, "Download diagnostic (.zip)", "xerscope_diagnostic.zip", "application/zip", key="debug_download"
    )
