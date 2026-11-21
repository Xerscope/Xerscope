import pandas as pd
import streamlit as st

from xerscope.app import ui
from xerscope.app.state import (
    anonymizer,
    baseline_files_tag,
    baseline_items,
    built_download,
    download,
    memo,
    page_header,
    require_store,
    source_raws,
)
from xerscope.export import Fmt, export_tables, zip_tables
from xerscope.xer.parser import parse_bytes

store = require_store()
page_header(
    "Export for Power BI",
    store,
    store.latest,
    lead="Star schema: relate dim_snapshot to every fact table on snapshot_idx, and use task_code "
    "to follow a task across weeks. Parquet keeps column types; CSV opens anywhere.",
)

tables = memo(("export",), export_tables, store, baseline=False)
ui.table(
    pd.DataFrame(
        [{"table": name, "rows": len(frame), "columns": len(frame.columns)} for name, frame in tables.items()]
    ),
    overrides={
        "table": st.column_config.TextColumn("Table"),
        "rows": st.column_config.NumberColumn("Rows", format="%,d"),
        **ui.count_columns(columns="Columns"),
    },
    key="export_tables",
    reading="export_tables",
)

table_formats: list[Fmt] = ["parquet", "csv"]
table_format = st.radio("Format", table_formats, horizontal=True)
download(
    f"Download {table_format.upper()} tables (.zip)",
    f"{store.latest.project_code}_xerscope_{table_format}.zip",
    "application/zip",
    lambda: zip_tables(store, table_format),
    lambda anonymous: memo(
        ("export_anonymised", table_format), zip_tables, store, table_format, anonymous.frame, baseline=False
    ),
    prepare_key="powerbi",
    anon_file_name=f"xerscope_{table_format}.zip",  # the project code would name the project
    type="primary",
)

with st.expander("Preview fact_activity"):
    ui.table(
        tables["fact_activity"].head(200), max_height=640, key="export_fact_activity", reading="export_fact_activity"
    )


def _data_date(raw) -> pd.Timestamp | None:
    """A file's status date from its PROJECT row (a baseline's, which the series does not hold)."""
    project = raw.table("PROJECT")
    if "last_recalc_date" not in project.columns or project.empty:
        return None
    value = pd.to_datetime(project["last_recalc_date"].iloc[0], errors="coerce")
    return None if pd.isna(value) else value


ui.section(
    "Anonymized XER extract",
    "Every loaded file, and the separate baseline file (each baseline of a P6 XML export, as an XER), with "
    "new Task IDs, WBS, project, resource and calendar names; no user, "
    "free text or cost. Dates, durations, units and logic are unchanged, so P6 and xerscope compute "
    "the same results on it. The new IDs match the anonymized lists of Schedule health.",
)
data_dates = {snapshot.source: snapshot.data_date for snapshot in store}
items = st.session_state.get("items") or []
baselines = baseline_items(st.session_state)  # the separate baseline file, each baseline of an XML
# built for the loaded files and the baseline file of that time: another baseline file asks for a new one
extract = built_download(
    "anon_extract",
    baseline_files_tag(st.session_state),
    "Build anonymized extract",
    "Download anonymized XER (.zip)",
    "xerscope_anonymised_xer.zip",
    "application/zip",
    None,
    lambda anonymous: anonymous.zip_xers(
        [
            *((parse_bytes(data, source=name), data_dates.get(name)) for name, data in items),
            *((raw, _data_date(raw)) for name, data in baselines for raw in source_raws(name, data)),
        ]
    ),
    None,
    key="anon_download",
    build_key="anon_build",
    icon=":material/visibility_off:",
    spinner=f"Anonymizing {len(items) + len(baselines)} file(s)…",
    anonymous=True,
    suffix=False,
)
if extract is not None and not extract.refused:
    built = anonymizer()
    report = built.report if built is not None else None
    if report is not None and (report.dropped_tables or report.emptied_columns):
        st.caption(
            "Left out: tables "
            + (", ".join(sorted(report.dropped_tables)) or "none")
            + "; columns emptied "
            + (", ".join(sorted(report.emptied_columns)) or "none")
            + "."
        )
