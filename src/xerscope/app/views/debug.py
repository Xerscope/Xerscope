from functools import partial

import streamlit as st

from xerscope.analysis.cpm import CycleError
from xerscope.anonymize import LeakError
from xerscope.app import diagnostic, ui
from xerscope.app.state import anonymizer, baseline_for, memo, require_store, snapshot_picker, standards

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


try:
    frames = memo(
        ("debug", snapshot.source, str(snapshot.data_date), baseline.label if baseline else None),
        diagnostic.diagnostic_frames,
        snapshot,
        baseline,
        standards()["P6"],
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


def build_diagnostic() -> None:
    anonymous = anonymizer(prepare=True)
    try:
        data = anonymous.zip_frames(frames)
    except LeakError as exc:
        st.session_state["debug_zip"] = (st.session_state.get("signature"), snapshot.source, None, str(exc))
        return
    st.session_state["debug_zip"] = (st.session_state.get("signature"), snapshot.source, data, "")


ui.section(
    "Anonymised diagnostic",
    "Blocks 1 to 6 as CSV, Activity IDs and resource codes renamed as in the anonymised XER extract; "
    "no name, WBS or project name. Dates are left as they are.",
)
if st.button("Build anonymised diagnostic", icon=":material/visibility_off:", key="debug_build"):
    build_diagnostic()
held = st.session_state.get("debug_zip")
if held is not None and held[:2] == (st.session_state.get("signature"), snapshot.source):
    _, _, data, refused = held
    if refused:
        st.error(refused, icon=":material/block:")
    else:
        st.download_button(
            "Download anonymised diagnostic (.zip)",
            data=data,
            file_name="xerscope_diagnostic.zip",
            mime="application/zip",
            icon=":material/download:",
            key="debug_download",
        )
