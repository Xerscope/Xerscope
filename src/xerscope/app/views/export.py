import pandas as pd
import streamlit as st

from xerscope.anonymize import LeakError
from xerscope.app import ui
from xerscope.app.state import ANONYMISED, anonymizer, anonymous_exports, export_anonymizer, memo, require_store
from xerscope.export import export_tables, zip_tables
from xerscope.xer.parser import parse_bytes

store = require_store()
ui.header(
    "Export for Power BI",
    store,
    store.latest,
    lead="Star schema: relate dim_snapshot to every fact table on snapshot_idx, and use task_code "
    "to follow an activity across weeks. Parquet keeps column types; CSV opens anywhere.",
)

tables = memo(("export",), export_tables, store)
ui.table(
    pd.DataFrame(
        [{"table": name, "rows": len(frame), "columns": len(frame.columns)} for name, frame in tables.items()]
    ),
    overrides={
        "table": st.column_config.TextColumn("Table"),
        "rows": st.column_config.NumberColumn("Rows", format="%,d"),
        "columns": st.column_config.NumberColumn("Columns", format="%d"),
    },
)

table_format = st.radio("Format", ["parquet", "csv"], horizontal=True)
label = f"Download {table_format.upper()} tables (.zip)"
if not anonymous_exports():
    st.download_button(
        label,
        data=zip_tables(store, table_format),
        file_name=f"{store.latest.project_code}_xerscope_{table_format}.zip",
        mime="application/zip",
        type="primary",
        icon=":material/download:",
    )
elif (anonymous := export_anonymizer("powerbi")) is not None:
    try:
        data = memo(("export_anonymised", table_format), zip_tables, store, table_format, anonymous.frame)
    except LeakError as exc:
        st.error(str(exc), icon=":material/block:")
    else:
        st.download_button(
            label + ANONYMISED,
            data=data,
            file_name=f"xerscope_{table_format}.zip",  # the project code would name the project
            mime="application/zip",
            type="primary",
            icon=":material/download:",
        )

with st.expander("Preview fact_activity"):
    ui.table(tables["fact_activity"].head(200), max_height=640)


def build_anonymised_extract(store) -> None:
    anonymous = anonymizer(prepare=True)
    data_dates = {snapshot.source: snapshot.data_date for snapshot in store}
    items = st.session_state.get("items") or []
    with st.spinner(f"Anonymising {len(items)} file(s)…"):
        try:
            extract = anonymous.zip_xers((parse_bytes(data, source=name), data_dates.get(name)) for name, data in items)
        except LeakError as exc:
            st.session_state["anon_extract"] = (st.session_state.get("signature"), None, str(exc))
            return
    st.session_state["anon_extract"] = (st.session_state.get("signature"), extract, "")


ui.section(
    "Anonymised XER extract",
    "Every loaded file with new Activity IDs, WBS, project, resource and calendar names; no user, "
    "free text or cost. Dates, durations, units and logic are unchanged, so P6 and xerscope compute "
    "the same results on it. The new IDs match the anonymised lists of Schedule health.",
)
if st.button("Build anonymised extract", icon=":material/visibility_off:", key="anon_build"):
    build_anonymised_extract(store)
held = st.session_state.get("anon_extract")
if held is not None and held[0] == st.session_state.get("signature"):
    _, extract, refused = held
    if refused:
        st.error(refused, icon=":material/block:")
    else:
        st.download_button(
            "Download anonymised XER (.zip)",
            data=extract,
            file_name="xerscope_anonymised_xer.zip",
            mime="application/zip",
            icon=":material/download:",
            key="anon_download",
        )
        report = anonymizer().report
        if report.dropped_tables or report.emptied_columns:
            st.caption(
                "Left out: tables "
                + (", ".join(sorted(report.dropped_tables)) or "none")
                + "; columns emptied "
                + (", ".join(sorted(report.emptied_columns)) or "none")
                + "."
            )
