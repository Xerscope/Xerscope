"""The Gantt Ask field's local agent (src/xerscope/agent, app/agent_panel.py).

The model is replaced by a fixed choice (``chat``): what is checked is what xerscope does with a choice,
on the demo series. Every value the agent says is compared with the engine that computes it, never with
a figure typed here, and every choice outside the lists is refused.
"""

import ast
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from conftest import read_folder
from streamlit.testing.v1 import AppTest

from xerscope import agent
from xerscope.agent import client, tools
from xerscope.analysis import activity_view as views
from xerscope.analysis.activity_forensics import activity_half_step
from xerscope.analysis.cpm import delay_impact
from xerscope.analysis.forensics import half_step
from xerscope.analysis.longest_path import path_churn

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "src" / "xerscope" / "app" / "streamlit_app.py")


@pytest.fixture(scope="module")
def context(store):
    return tools.context_for(store, store.latest)


def chose(**reply):
    """A model that always makes this choice; it records the messages it was sent."""

    def chat(messages, schema):
        chat.sent = (messages, schema)
        return reply

    return chat


# --- the answers: the engines' values, written by xerscope -----------------------------------


@pytest.mark.oracle("characterization")
def test_an_activity_slip_is_the_half_step_reading_of_that_activity(context):
    chat = chose(command="activity_slip", field="total_shift_wd", activity_id="C3010")
    said = agent.answer("why did C3010 move", context, "en", chat)
    truth = round(activity_half_step(context.previous, context.snapshot, "C3010").total_shift_wd, 2)
    assert not said.refused and said.values["total_shift_wd"] == truth and str(truth) in said.sentence
    assert said.codes == ("C3010",)


@pytest.mark.oracle("characterization")
def test_the_project_move_and_the_longest_path_are_the_engines(context):
    week = half_step(context.previous, context.snapshot)
    said = agent.answer("project finish?", context, "en", chose(command="project_slip", field="slip_wd"))
    assert said.values["slip_wd"] == round(week.slip_wd, 2)
    churn = path_churn(context.store)
    row = churn[churn["data_date"] == context.snapshot.data_date].iloc[0]
    said = agent.answer("how many on the longest path", context, "en", chose(command="path_changes", field="on_path"))
    assert said.values["on_path"] == int(row["on_path"]) and str(int(row["on_path"])) in said.sentence


@pytest.mark.oracle("characterization")
def test_a_query_is_the_views_reading_and_names_the_activities_the_gantt_draws(context):
    conditions = [
        {"column": "critical", "op": "is_true", "value": ""},
        {"column": "status", "op": "=", "value": "Not started"},
    ]
    chat = chose(command="query", field="count", conditions=conditions)
    said = agent.answer("how many critical activities are not started", context, "en", chat)
    truth = views.run(
        context.view,
        views.Query((views.Condition("critical", "is_true"), views.Condition("status", "=", "Not started"))),
    )
    assert said.values["count"] == truth.count and set(said.codes) == set(truth.funnel.rows.index)
    assert said.sentence == f"Activities: {truth.count} (critical · status = Not started)"


@pytest.mark.oracle("characterization")
def test_a_simulated_delay_is_the_engines_delay(context):
    chat = chose(command="simulate_delay", field="finish_move_wd", activity_id="X4020", days=5)
    said = agent.answer("what if X4020 took 5 more days", context, "fr", chat)
    impact = delay_impact(context.snapshot, "X4020", 5)
    assert (
        said.values["finish_move_wd"] == impact.finish_move_wd and said.values["float_after_d"] == impact.float_after_d
    )
    assert said.sentence.startswith("La fin projet bougerait de") and "marge" in said.sentence


def test_the_sentence_is_in_the_questions_language(context):
    said = agent.answer("fin du projet ?", context, "fr", chose(command="project_slip", field="finish"))
    assert said.sentence.startswith("Fin:") and "depuis le" in said.sentence


@pytest.mark.parametrize("field", ["none", "count", "total_shift_wd"])
def test_a_value_of_another_command_answers_the_commands_main_value(context, field):
    """Seen with a real model: path_changes asked with "count". Its main value answers, named."""
    said = agent.answer("on the longest path", context, "en", chose(command="path_changes", field=field))
    assert not said.refused and said.field == "on_path" and said.sentence.startswith("Open activities on")


def test_an_activity_id_written_as_a_condition_is_the_commands_activity(context):
    """Seen with a real model: simulate_delay with ``activity_id = X4020`` as a condition."""
    chat = chose(
        command="simulate_delay", field="finish_move_wd", days=5,
        conditions=[{"column": "activity_id", "op": "=", "value": "X4020"}],
    )  # fmt: skip
    said = agent.answer("what if X4020 took 5 more days", context, "en", chat)
    assert said.choice.argument == "X4020" and not said.refused


def test_the_days_of_a_delay_left_out_are_the_one_number_of_the_question(context):
    """Seen with a real model (4 replies of 31): simulate_delay without days. One number in the
    question is the delay; none, or several, leaves the reply refused."""
    chat = chose(command="simulate_delay", field="finish_move_wd", activity_id="X4020")
    assert agent.answer("what if X4020 slips 5 days", context, "en", chat).choice.days == 5.0
    assert "between 1 and" in agent.answer("what if X4020 slips", context, "en", chat).refused
    assert "between 1 and" in agent.answer("X4020 slips 5 or 10 days", context, "en", chat).refused


def test_a_number_is_read_from_its_text_and_must_be_the_questions(context):
    """Seen with a real model: "fmt(5)" for 5. Read as 5; a number the question does not hold is refused."""
    condition = {"column": "total_float_d", "op": "<", "value": "fmt(5)"}
    said = agent.answer(
        "less than 5 days of float", context, "en", chose(command="query", field="count", conditions=[condition])
    )
    assert not said.refused and said.choice.query.conditions[0].value == "5"
    said = agent.answer("little float", context, "en", chose(command="query", field="count", conditions=[condition]))
    assert "not a number of the question" in said.refused


def test_a_fixed_value_is_searched_in_any_language(context):
    """Seen with a real model: "en cours" read as status contains "In progress": the statuses are the
    model's words, not the question's, and are not refused as invented."""
    condition = {"column": "status", "op": "contains", "value": "In progress"}
    said = agent.answer(
        "combien d'activités en cours", context, "fr", chose(command="query", field="count", conditions=[condition])
    )
    assert (
        not said.refused
        and said.values["count"]
        == views.run(context.view, views.Query((views.Condition("status", "=", "In progress"),))).count
    )


def test_a_command_chosen_with_no_value_answers_its_main_value(context):
    """Seen with a real model: a command right, its value "none": the command's first value is the answer."""
    said = agent.answer("how many critical", context, "en", chose(command="query", field="none", conditions=[]))
    assert not said.refused and said.field == "count"


# --- what is refused --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        ({"command": "none", "field": "none"}, "cannot answer"),
        ({"command": "invent", "field": "count"}, "no known command"),
        ({"command": "activity_slip", "field": "total_shift_wd", "activity_id": "ZZ999"}, "not an Activity ID"),
        ({"command": "simulate_delay", "field": "finish_move_wd", "activity_id": "X4020", "days": 0}, "between 1 and"),
        ({"command": "query", "field": "count", "conditions": [{"column": "status", "op": "=", "value": "Blocked"}]},
         "holds no value"),
        ({"command": "query", "field": "count",
          "conditions": [{"column": "activity_name", "op": "contains", "value": "pump"}]},
         "not a word of the question"),
        ({"command": "query", "field": "groups"}, "without a column to group by"),
    ],
)  # fmt: skip
def test_a_choice_outside_the_lists_the_file_or_the_question_gives_no_answer(context, reply, reason):
    said = agent.answer("how many activities are there", context, "en", chose(**reply))
    assert said.sentence == "" and reason in said.refused and said.codes == ()


def test_the_model_reads_the_files_columns_under_a_flat_closed_schema(context):
    chat = chose(command="none", field="none")
    agent.answer("anything", context, "en", chat)
    messages, schema = chat.sent
    assert all(command in messages[0]["content"] for command in tools.FIELDS)
    assert all(column.name in messages[0]["content"] for column in context.view.columns)
    assert schema["additionalProperties"] is False and schema["properties"]["command"]["enum"] == list(tools.FIELDS)
    columns = schema["properties"]["conditions"]["items"]["properties"]["column"]["enum"]
    assert columns == [column.name for column in context.view.columns]
    assert "$ref" not in json.dumps(schema)  # a nested reference can be ignored by llama.cpp (issue 21228)
    assert context.view.frame.iloc[0]["activity_id"] not in messages[0]["content"]  # no data: names only


# --- the client: the local model only -----------------------------------------------------------


@pytest.mark.parametrize(
    "url", ["http://llm:8080", "http://127.0.0.1:8080", "http://localhost:8080", "http://[::1]:8080"]
)
def test_the_silo_model_or_a_loopback_url_is_allowed(url):
    assert client.is_allowed(url)


@pytest.mark.parametrize(
    "url",
    ["https://api.example.com", "http://llm.example.com:8080", "http://llm@example.com", "http://10.0.0.5:8080",
     "http://127.0.0.2:8080", "ftp://llm", "file:///etc/passwd", "llm:8080", ""],
)  # fmt: skip
def test_any_other_url_is_refused_before_a_connection(url):
    assert not client.is_allowed(url)
    with pytest.raises(client.ModelError, match="must name the local model"):
        client.complete([], {}, url=url or "http://example.com")


class _Server(BaseHTTPRequestHandler):
    reply: bytes = b""
    status: int = 200
    received: list = []

    def do_POST(self):
        self.received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(self.status)
        if self.status == 302:
            self.send_header("Location", "http://example.com/")
        self.end_headers()
        self.wfile.write(self.reply)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    httpd = HTTPServer(("127.0.0.1", 0), _Server)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    _Server.received = []
    yield httpd, f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def test_the_client_asks_for_one_constrained_object_with_thinking_off(server):
    _, url = server
    _Server.status, _Server.reply = (
        200,
        json.dumps({"choices": [{"message": {"content": '{"command": "none"}'}}]}).encode(),
    )
    schema = {"type": "object", "properties": {"command": {"type": "string"}}}
    assert client.complete([{"role": "user", "content": "q"}], schema, url=url) == {"command": "none"}
    sent = _Server.received[0]
    assert sent["response_format"] == {"type": "json_object", "schema": schema}
    assert sent["chat_template_kwargs"] == {"enable_thinking": False} and sent["temperature"] == 0


@pytest.mark.parametrize(
    ("status", "reply"),
    [(200, b"not json"), (200, b'{"choices": [{"message": {"content": "[1]"}}]}'), (302, b""), (500, b"")],
)
def test_a_bad_reply_or_a_redirect_is_an_error_never_followed(server, status, reply):
    _, url = server
    _Server.status, _Server.reply = status, reply
    with pytest.raises(client.ModelError):
        client.complete([], {}, url=url)
    assert len(_Server.received) == 1  # the redirect was not followed


# --- the page --------------------------------------------------------------------------------


def test_the_page_never_loads_the_agent_at_import():
    """The agent's package (and its client) is imported inside the panel's function only: an app with
    XERSCOPE_AGENT off never loads the code that opens a connection."""
    panel = ast.parse((ROOT / "src" / "xerscope" / "app" / "agent_panel.py").read_text(encoding="utf-8"))
    top = [n for n in panel.body if isinstance(n, ast.Import | ast.ImportFrom)]
    assert not any((getattr(n, "module", "") or "").startswith("xerscope.agent") for n in top)


def _gantt(sample_dir, monkeypatch, on):
    monkeypatch.setenv("XERSCOPE_DATA", str(sample_dir))
    monkeypatch.delenv("XERSCOPE_BASELINE", raising=False)
    monkeypatch.setenv("XERSCOPE_AGENT", "on" if on else "off")
    at = read_folder(AppTest.from_file(APP, default_timeout=120).run())
    return at.switch_page("views/gantt.py").run()


def test_the_page_shows_the_agents_answer_when_the_grammar_reads_nothing(sample_dir, monkeypatch):
    monkeypatch.setattr(
        client, "complete", lambda messages, schema: {"command": "path_changes", "field": "on_path", "argument": ""}
    )
    at = _gantt(sample_dir, monkeypatch, on=True)
    at.text_input(key="gantt_ask").set_value("how many activities drive the end date right now").run()
    assert not at.exception
    card = " ".join(m.value for m in at.markdown)
    assert "Open activities on the longest path" in card
    assert any("local agent · path_changes · on_path" in c.value for c in at.caption)


def test_a_query_answer_is_what_the_gantt_draws(sample_dir, monkeypatch):
    """The agent's query keeps the critical activities not started: the Gantt draws those tasks only."""
    conditions = [
        {"column": "critical", "op": "is_true", "value": ""},
        {"column": "status", "op": "=", "value": "Not started"},
    ]
    monkeypatch.setattr(
        client, "complete", lambda messages, schema: {"command": "query", "field": "count", "conditions": conditions}
    )
    at = _gantt(sample_dir, monkeypatch, on=True)
    at.text_input(key="gantt_ask").set_value("which jobs hurt the end date and have not begun").run()
    assert not at.exception
    drawn = {row["code"] for row in json.loads(at.get("bidi_component")[0].proto.json)["rows"] if row["kind"] == "task"}
    view = tools.context_for(*_series(sample_dir)).view
    kept = views.run(
        view, views.Query((views.Condition("critical", "is_true"), views.Condition("status", "=", "Not started")))
    )
    assert drawn == set(kept.funnel.rows.index)


def _series(sample_dir):
    from xerscope.store import SnapshotStore

    store = SnapshotStore.from_folder(sample_dir)
    return store, store.latest


def test_the_page_asks_no_model_when_the_agent_is_off_or_the_grammar_reads_all(sample_dir, monkeypatch):
    def fail(messages, schema):
        raise AssertionError("the model was asked")

    monkeypatch.setattr(client, "complete", fail)
    at = _gantt(sample_dir, monkeypatch, on=False)
    at.text_input(key="gantt_ask").set_value("how many activities drive the end date right now").run()
    assert not at.exception
    at = _gantt(sample_dir, monkeypatch, on=True)
    at.text_input(key="gantt_ask").set_value("critical not started").run()  # the grammar reads every word
    assert not at.exception and not any("local agent" in c.value for c in at.caption)


def test_an_unreachable_model_is_said_and_the_page_still_draws(sample_dir, monkeypatch):
    def down(messages, schema):
        raise client.ModelError("the local model did not answer (connection refused)")

    monkeypatch.setattr(client, "complete", down)
    at = _gantt(sample_dir, monkeypatch, on=True)
    at.text_input(key="gantt_ask").set_value("how many activities drive the end date right now").run()
    assert not at.exception and any("Local agent unavailable" in w.value for w in at.warning)
