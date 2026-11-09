import pandas as pd
import streamlit as st

from xerscope.analysis import query
from xerscope.analysis.explain import KPI_FORMULAS
from xerscope.analysis.wbs import ROOT, rollup, subtree_ids
from xerscope.app import ui
from xerscope.app.sets import show_steps
from xerscope.app.state import (
    baseline_for,
    compare_picker,
    csv_download,
    file_variants,
    memo,
    page_header,
    require_store,
    session_lexicon,
    snapshot_picker,
    sources_of,
    teach,
)
from xerscope.app.task_panel import show_card, show_history, task_from_row_id
from xerscope.viz import categorise, gantt_data, gantt_rows
from xerscope.viz.gantt import CATEGORY_ORDER
from xerscope.xer.model import STATUS

NODE_KEY = "gantt_node"  # the WBS node the page opens on, kept across reruns
NEXT_NODE_KEY = "gantt_node_next"  # a node to open on the next run (the picker is drawn before the chart)
TASK_KEY = "gantt_task"  # the Activity ID picked in the chart or in the list under it
CHART_KEY = "gantt_chart"
CLICK_KEY = "gantt_clicked"  # the Activity ID of a click in the chart, until the run it causes
PICK_KEY = "gantt_task_pick"  # that list
ASK_KEY = "gantt_ask"  # a sentence turned into filters (analysis/query.py), added to the widgets above
DROPPED_KEY = "gantt_ask_dropped"  # (sentence, [labels taken off with their × button])
FOCUS_KEY = "gantt_focus"  # {"codes": [...], "label": "P6-01 · Logic"} set by Schedule health; None otherwise
GANTT_HEIGHT = 680  # px at most (viz.gantt.fitted_height: less for a short tree); the chart scrolls inside


store = require_store()
top = st.container()

snapshot_column, compare_column = st.columns(2)
with snapshot_column:
    snapshot = snapshot_picker(store, "Update", key="gantt_snap")
with compare_column:
    compare, compare_label = compare_picker(store, snapshot, key="gantt_cmp")
baseline = baseline_for(snapshot)
with top:
    page_header(
        "Gantt & WBS",
        store,
        snapshot,
        lead="Bars are coloured by float; the outline behind each bar is the same task in the "
        "comparison you pick, so slippage shows as the bar leaving its outline.",
    )

nodes = memo(
    ("rollup", snapshot.source),
    rollup,
    snapshot,
    baseline,
    ev_basis=False,  # reads bl_finish only
)
# a focus asked after the WBS picker was drawn (a double click in the chart) applies on the next run
if (wanted := st.session_state.pop(NEXT_NODE_KEY, None)) in set(nodes["wbs_id"]):
    st.session_state[NODE_KEY] = wanted
if st.session_state.get(NODE_KEY) not in set(nodes["wbs_id"]):
    st.session_state[NODE_KEY] = ROOT  # first visit, or a node the picked update does not have
labels = dict(zip(nodes["wbs_id"], nodes["label"], strict=True))


def _clear_ask() -> None:
    st.session_state[ASK_KEY] = ""
    st.session_state[DROPPED_KEY] = ("", [])


def _drop(sentence: str, label: str) -> None:
    """Take one understood filter off (its × button), for this sentence only."""
    held, labels = st.session_state.get(DROPPED_KEY, ("", []))
    st.session_state[DROPPED_KEY] = (sentence, [*(labels if held == sentence else []), label])


# The Ask field: a sentence turned into the page's filters (analysis/query.py: the grammar, the
# lexicon, the file's own labels; no model), the first control of the page. The answer (one
# sentence over the rows, the funnel line) is written into ``answer_box`` once the rows are
# known, below; a × button per filter understood takes it off.
asked = st.text_input(
    "Ask the schedule",
    placeholder='"critical not started in civil works", "jalons en retard", "crew tasks"…',
    key=ASK_KEY,
    icon=":material/search:",
)
answer_box = st.container(key="ask_answer")
taught = st.session_state.get("taught", [])
# the variants of each source column, generated from every loaded file, in memory (never written)
generated = memo(("ask_variants",), query.variants, list(store), baseline=False, ev_basis=False)
lexicon = memo(  # the labels of every loaded file (memo's key names them all), rebuilt when a word is taught
    ("vocabulary", snapshot.source, len(taught)),
    query.vocabulary,
    snapshot,
    nodes,
    session_lexicon(),
    [other for other in store if other is not snapshot],
    query.lexicons(generated, file_variants()),
    baseline=False,
    ev_basis=False,
)
ask = None
if asked:
    ask = memo(  # once per sentence and update, baseline-independent
        ("ask", snapshot.source, asked, len(taught)), query.parse, asked, lexicon, baseline=False, ev_basis=False
    )
if ask is not None:  # the filters taken off this sentence (× buttons), from query.without
    held, dropped = st.session_state.get(DROPPED_KEY, ("", []))
    for label in dropped if held == asked else []:
        ask = query.without(ask, label, lexicon)
if ask is not None and ask.matched:  # what was understood, one button each: "Critical ×" takes it off
    with st.container(horizontal=True, gap="small", key="ask_chips"):
        for label in ask.matched:
            st.button(
                f"{ui.md_text(label)} ×",
                key=f"ask_drop:{label}",
                help="Remove this filter",
                on_click=_drop,
                args=(asked, label),
            )
if ask is not None:
    for word in ask.ignored:  # a word nothing holds: the closest labels, a click teaches it for the session
        offers = query.suggestions(word, lexicon)
        if offers:
            with st.container(horizontal=True, gap="small", vertical_alignment="center", key=f"teach_{word}"):
                st.markdown(f"Did you mean, for **{ui.md_text(word)}**:")
                for _kind, label, _ratio in offers:
                    if st.button(ui.md_text(label), key=f"teach_{word}_{label}", type="tertiary"):
                        teach(word, label)
                        st.rerun()
    if taught:
        st.download_button(
            f"Download the {len(taught)} word(s) taught (.toml, for XERSCOPE_LEXICON)",
            data=query.learned_toml(taught).encode(),
            file_name="lexicon-taught.toml",
            mime="application/toml",
            key="gantt_taught_download",
            type="tertiary",
        )


# "CIV · Civil works › ZA · Zone A": each node and the nodes above it, built once (the list
# formats every node on each rerun)
path_labels = {
    wbs_id: " › ".join(labels[a] for a in reversed(ancestors) if a != ROOT) or labels[ROOT]
    for wbs_id, ancestors in zip(nodes["wbs_id"], nodes["ancestors"], strict=True)
}

current = st.selectbox("WBS", nodes["wbs_id"].tolist(), format_func=path_labels.get, key=NODE_KEY)
node = nodes[nodes["wbs_id"] == current].iloc[0]


def _focus_node(wbs_id: str) -> None:
    st.session_state[NODE_KEY] = wbs_id


# the path to the node, each step a button that moves the focus up ("Project › CIV › ZA");
# nothing at the top node (ancestors list the node itself first)
path = [*(a for a in reversed(node["ancestors"]) if a != current), current]
if len(path) > 1:
    with st.container(horizontal=True, gap="small", vertical_alignment="center", key="gantt_crumbs"):
        for step in path:
            if step == current:
                st.markdown(f"**{ui.md_text(labels[step])}**")
            else:
                st.button(
                    f"{ui.md_text(labels[step])} ›",
                    key=f"crumb_{step}",
                    type="tertiary",
                    on_click=_focus_node,
                    args=(step,),
                )
ui.kpis(
    [
        ("Focus", node["wbs_code"] if current != ROOT else "Whole project", None, node["wbs_name"]),
        (
            "% complete",
            "–" if pd.isna(node["pct_complete"]) else f"{node['pct_complete']:.1f} %",
            None,
            f"Weighted by {node['weight']}",
        ),
        (
            "Forecast finish",
            ui.fmt_date(node["finish"]),
            None if pd.isna(node["finish_variance_wd"]) else f"{node['finish_variance_wd']:+.1f} wd vs BL",
            "Variance to BL: latest finish of the baselined tasks against their latest BL finish"
            + (f"; {node['outside_bl']} task(s) not in the baseline left out" if node["outside_bl"] else ""),
            "inverse",
        ),
        ("Labor hours", f"{node['actual_hr']:,.0f} / {node['budget_hr']:,.0f}", None, "Actual / budgeted"),
        ("Open critical", int(node["critical"])),
    ],
    formulas=KPI_FORMULAS,
)

status_column, float_column, search_column = st.columns(3)
status = status_column.multiselect("Status", list(STATUS.values()), placeholder="All")
categories = float_column.multiselect("Float", CATEGORY_ORDER, placeholder="All")
search = search_column.text_input("Search", placeholder="Task ID or name")
code_type, code_ids, picks = None, set(), []
if not snapshot.code_values.empty:  # the file's P6 activity codes, if it has any
    type_column, value_column = st.columns([1, 2])
    code_type = type_column.selectbox(
        "Task code (P6 activity code)",
        list(dict.fromkeys(snapshot.code_values["code_type"])),
        index=None,
        placeholder="None",
    )
    values = snapshot.code_values[snapshot.code_values["code_type"] == code_type]
    paths = snapshot.code_paths(code_type) if code_type else {}
    description = dict(zip(values["code_id"], values["name"], strict=True))
    by_label = {f"{path} · {description[code_id]}": code_id for code_id, path in paths.items()}
    picks = value_column.multiselect(
        "Code values",
        list(by_label),
        placeholder="Type to search; pick a value, or press Enter to keep every value containing the text"
        if code_type
        else "Pick a task code first",
        accept_new_options=True,
        filter_mode="contains",
        disabled=code_type is None,
        key=f"gantt_code_values:{code_type}",  # another code type starts with nothing picked
    )
    # a suggestion picked = that value exactly (P6 "equals"); text kept = every value whose code
    # contains it, case and accents ignored (P6 "contains")
    short = dict(zip(values["code_id"], values["value"], strict=True))
    for pick in picks:
        if pick in by_label:
            code_ids.add(by_label[pick])
        else:
            code_ids |= {code_id for code_id, value in short.items() if ui.fold(pick) in ui.fold(value)}
options = st.container(horizontal=True, vertical_alignment="bottom", gap="large")
show_links = options.toggle("Logic links", value=False)
hide_loe = options.toggle("Hide LOE", value=True)
timescale = options.segmented_control(
    "Timescale",
    ["Month", "Week"],
    default="Month",
    help="Week shows the 12 weeks around the status date",
    key="gantt_timescale",
)

branch_ids = set(nodes["wbs_id"]) if current == ROOT else subtree_ids(nodes, current)
branch = nodes[nodes["wbs_id"].isin(branch_ids)]
tasks = snapshot.activities
if current != ROOT:
    tasks = tasks[tasks["wbs_id"].isin(branch_ids)]
tasks = tasks.assign(category=categorise(tasks))
if hide_loe and not (ask is not None and ask.loe):  # "LOE" in the sentence overrides the toggle
    tasks = tasks[~tasks["is_loe"]]
unfiltered = len(tasks)
if status:
    tasks = tasks[tasks["status"].isin(status)]
if categories:
    tasks = tasks[tasks["category"].isin(categories)]
if search:
    tasks = tasks[ui.search_mask(tasks, ["task_code", "task_name"], search)]  # accent-insensitive
if code_type and picks:
    tasks = tasks[tasks["task_code"].isin(snapshot.tasks_with_codes(code_type, code_ids))]
ask_funnel = None
if ask is not None:  # the sentence's filters, intersected with the widgets', one funnel step each
    ask_funnel = query.apply(ask, tasks, snapshot, nodes, baseline)  # "late" reads the page's baseline
    tasks = ask_funnel.rows
    with answer_box:  # the banner: the sentence's answer, amber when a word was left out, "Show all"
        # nothing understood but words left out: no row (query.apply); only stop words: no filter
        said = (  # in the question's language
            query.answer(ask, ask_funnel, lexicon, query.language(asked))
            if ask_funnel.steps
            else "No filter: showing all."
        )
        banner = st.container(
            border=True,
            horizontal=True,
            vertical_alignment="center",
            key="ask_banner_warn" if ask.ignored or ask.confidence < query.SURE else "ask_banner",
        )
        with banner:
            st.markdown(ui.md_text(said), width="stretch")
            st.button("Show all", key="ask_clear", type="tertiary", icon=":material/close:", on_click=_clear_ask)
        how = " · unsure reading" if ask.confidence < query.SURE else ""
        st.caption((query.funnel_line(ask_funnel) if ask_funnel.steps else "no filter") + how)
focus = st.session_state.get(FOCUS_KEY)  # the tasks a check listed (Schedule health)
if focus:
    tasks = tasks[tasks["task_code"].isin(focus["codes"])]
    with st.container(horizontal=True, gap="small", vertical_alignment="center"):
        st.markdown(f"Showing the **{len(tasks)}** tasks of **{ui.md_text(focus['label'])}**")
        if st.button("Show all", icon=":material/close:", key="gantt_focus_clear", type="tertiary"):
            st.session_state[FOCUS_KEY] = None
            st.rerun()
filtering = len(tasks) < unfiltered  # every status ticked filters nothing: the outline stays closed


def _clicked() -> None:
    """A click on an activity row: the row id the browser sent, applied by the run it causes."""
    st.session_state[CLICK_KEY] = task_from_row_id(st.session_state[CHART_KEY].get("picked"))


def _pick_from_list() -> None:
    st.session_state[TASK_KEY] = st.session_state[PICK_KEY]


@st.fragment
def chart_and_task() -> None:
    """The chart, the Task list and the picked activity's card, on the rows the widgets above kept.
    Picking an activity (a click in the chart, the list) runs this part alone: the page above and
    the sidebar are not drawn again."""
    rows = gantt_rows(tasks, branch, compare=compare, snapshot=snapshot, keep_empty=not filtering)
    root_row = nodes[nodes["wbs_id"] == ROOT].iloc[0]
    drawn = set(tasks["task_code"])
    # the browser sends a row id only; it counts when it names an activity drawn in this chart
    clicked = st.session_state.pop(CLICK_KEY, None)
    if clicked in drawn:
        st.session_state[TASK_KEY] = clicked
    picked = st.session_state.get(TASK_KEY)
    picked = picked if picked in drawn else None  # an activity the filters or the update leave out
    open_ids = {r["id"] for r in rows if r["kind"] == "wbs"} if filtering else {f"w:{current}"}
    if picked:  # keep the picked activity's branch open so its row shows and is scrolled to
        wbs_id = tasks.loc[tasks["task_code"] == picked, "wbs_id"].iloc[0]
        chain = nodes.loc[nodes["wbs_id"] == wbs_id, "ancestors"]
        open_ids |= {f"w:{a}" for a in (chain.iloc[0] if len(chain) else []) if a in branch_ids}
    chart = ui.GANTT(
        data=gantt_data(
            rows,
            relationships=snapshot.relationships,
            data_date=snapshot.data_date,
            span=(root_row["start"], root_row["finish"]),
            timescale="week" if timescale == "Week" else "month",
            # a filter opens every branch so each match shows; otherwise the chosen node opens
            open_ids=open_ids,
            selected=f"a:{picked}" if picked else f"w:{current}",
            compare_label=compare_label or "",
            links=show_links,
            height=GANTT_HEIGHT,
        ),
        key=CHART_KEY,
        on_picked_change=_clicked,  # a click on an activity row sends "a:<Activity ID>"
        on_focus_change=lambda: None,  # a double click on a WBS row sends "w:<wbs_id>"
    )
    focused = chart.get("focus")
    if isinstance(focused, str) and focused.startswith("w:") and focused[2:] in branch_ids and focused[2:] != current:
        st.session_state[NEXT_NODE_KEY] = focused[2:]
        st.rerun(scope="app")  # the WBS picker is above this part

    codes = tasks["task_code"].tolist()
    names = dict(zip(tasks["task_code"], tasks["task_name"], strict=False))
    st.session_state[PICK_KEY] = picked
    st.selectbox(
        "Task",
        codes,
        format_func=lambda code: f"{code} · {names.get(code, '')}",
        placeholder="Click a task in the chart, or pick one here",
        key=PICK_KEY,
        on_change=_pick_from_list,
    )
    if st.session_state.get(TASK_KEY) and not picked:
        st.caption(f"Task {ui.md_text(st.session_state[TASK_KEY])} is not drawn with the filters above.")
    if picked:
        with st.container(border=True):
            show_card(snapshot, picked)
            ui.section("History across updates")
            show_history(store, picked)


chart_and_task()

if ask_funnel is not None and ask_funnel.steps:
    with st.expander("Population, step by step"):
        show_steps(ask_funnel)
with st.expander("Table view"):
    table_columns = [
        "task_code",
        "task_name",
        "wbs_code",
        "status",
        "category",
        "start",
        "finish",
        "total_float_d",
        "remaining_d",
        "pct_complete",
        "labor_budget_hr",
        "constraint",
    ]
    # a finished task has no float or remaining duration: a dash, not "None"
    shown, overrides = ui.numbers_as_text(tasks[table_columns], ["total_float_d", "remaining_d"])
    ui.table(shown, overrides=overrides)
    csv_download(tasks[table_columns], f"gantt_{ui.stamp(snapshot.data_date)}.csv", sources=sources_of(snapshot))
