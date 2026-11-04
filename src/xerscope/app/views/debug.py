from functools import partial

import streamlit as st

from xerscope.analysis.cpm import CycleError
from xerscope.app import diagnostic, ui
from xerscope.app.state import (
    anonymous_exports,
    baseline_for,
    fetch,
    held,
    hold,
    memo,
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
    ui.header(
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

# keyed blocks: a label holds a count that changes with the update, and Streamlit keys an
# unkeyed expander on its label, so it would redraw closed
with st.expander(f"2 · Expected finish ({len(frames['02_expected_finish'])} activities)", key="debug_expected_finish"):
    st.caption(
        "ef_recalc is the expected finish, or the early start when the expected finish falls before it "
        "(remaining_set_to_0). An FF / SF bound later than that wins instead (rem_override_hr blank)."
    )
    table(frames["02_expected_finish"])

int01, int03 = frames["03_int01_recalculation"], frames["03_int03_assignments"]
with st.expander(
    f"3 · INT-01 / INT-03 differences ({len(int01)} activities, {len(int03)} assignments)", key="debug_differences"
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
    table(frames["05_calendars"])

with st.expander(f"6 · Load warnings ({len(frames['06_leveling'])} leveled activities)", key="debug_load_warnings"):
    st.caption(
        "The activities behind the warnings raised while reading the file. Leveling: open activities "
        "whose remaining early start (restart_date) differs from the early start. Project finish: "
        "PROJECT.scd_end_date against the activities that end last."
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
        "xerscope's SPI (labour units) from hours. absent: the column is missing or blank on every row."
    )
    table(frames["07_costs"])


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
    hold(st.session_state, "debug_zip", (snapshot.source, anonymous), fetched)


anonymous = anonymous_exports()
ui.section(
    "Diagnostic",
    "Blocks 1 to 7 as CSV. With anonymous exports on, Activity IDs and resource codes are renamed as in "
    "the anonymised XER extract; the tables hold no name, WBS or project name. Dates are left as they are.",
)
if st.button("Build diagnostic", icon=":material/folder_zip:", key="debug_build"):
    build_diagnostic(anonymous)
diagnostic_zip = held(st.session_state, "debug_zip", (snapshot.source, anonymous))
if diagnostic_zip is not None:
    show_download(
        diagnostic_zip, "Download diagnostic (.zip)", "xerscope_diagnostic.zip", "application/zip", key="debug_download"
    )
