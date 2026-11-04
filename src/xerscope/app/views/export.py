import pandas as pd
import streamlit as st

from xerscope.app import ui
from xerscope.app.state import anonymizer, download, fetch, held, hold, memo, require_store, show_download
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
download(
    f"Download {table_format.upper()} tables (.zip)",
    f"{store.latest.project_code}_xerscope_{table_format}.zip",
    "application/zip",
    lambda: zip_tables(store, table_format),
    lambda anonymous: memo(("export_anonymised", table_format), zip_tables, store, table_format, anonymous.frame),
    prepare_key="powerbi",
    anon_file_name=f"xerscope_{table_format}.zip",  # the project code would name the project
    type="primary",
)

with st.expander("Preview fact_activity"):
    ui.table(tables["fact_activity"].head(200), max_height=640)


def build_anonymised_extract(store) -> None:
    data_dates = {snapshot.source: snapshot.data_date for snapshot in store}
    items = st.session_state.get("items") or []
    with st.spinner(f"Anonymising {len(items)} file(s)…"):
        extract = fetch(
            st.session_state,
            None,
            lambda anonymous: anonymous.zip_xers(
                (parse_bytes(data, source=name), data_dates.get(name)) for name, data in items
            ),
            prepare=True,
            anonymous=True,
        )
    hold(st.session_state, "anon_extract", None, extract)


ui.section(
    "Anonymised XER extract",
    "Every loaded file with new Activity IDs, WBS, project, resource and calendar names; no user, "
    "free text or cost. Dates, durations, units and logic are unchanged, so P6 and xerscope compute "
    "the same results on it. The new IDs match the anonymised lists of Schedule health.",
)
if st.button("Build anonymised extract", icon=":material/visibility_off:", key="anon_build"):
    build_anonymised_extract(store)
extract = held(st.session_state, "anon_extract", None)
if extract is not None:
    show_download(
        extract,
        "Download anonymised XER (.zip)",
        "xerscope_anonymised_xer.zip",
        "application/zip",
        suffix=False,
        key="anon_download",
    )
    if not extract.refused:
        report = anonymizer().report
        if report.dropped_tables or report.emptied_columns:
            st.caption(
                "Left out: tables "
                + (", ".join(sorted(report.dropped_tables)) or "none")
                + "; columns emptied "
                + (", ".join(sorted(report.emptied_columns)) or "none")
                + "."
            )
