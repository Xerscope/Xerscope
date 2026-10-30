import pandas as pd
import streamlit as st

from xerscope.app import ui
from xerscope.app.state import memo, require_store
from xerscope.export import export_tables, zip_tables

store = require_store()
ui.header(
    "Export for Power BI",
    store,
    store.latest,
    lead="Star schema: relate dim_snapshot to every fact table on snapshot_idx, and use task_code "
    "to follow an activity across weeks. Parquet keeps column types; CSV opens anywhere.",
)

tables = memo(("export",), lambda: export_tables(store))
ui.table(
    pd.DataFrame([{"table": k, "rows": len(v), "columns": len(v.columns)} for k, v in tables.items()]),
    overrides={
        "table": st.column_config.TextColumn("Table"),
        "rows": st.column_config.NumberColumn("Rows", format="%,d"),
        "columns": st.column_config.NumberColumn("Columns", format="%d"),
    },
)

fmt = st.radio("Format", ["parquet", "csv"], horizontal=True)
st.download_button(
    f"Download {fmt.upper()} tables (.zip)",
    data=zip_tables(store, fmt),
    file_name=f"{store.latest.project_code}_xerscope_{fmt}.zip",
    mime="application/zip",
    type="primary",
    icon=":material/download:",
)

with st.expander("Preview fact_activity"):
    ui.table(tables["fact_activity"].head(200), max_height=640)
