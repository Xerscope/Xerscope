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
from xerscope.analysis import query
from xerscope.analysis.activity_forensics import activity_half_step
from xerscope.analysis.forensics import half_step
from xerscope.analysis.longest_path import path_churn
from xerscope.analysis.task_filters import branch_tasks
from xerscope.analysis.wbs import tree
from xerscope.viz import categorise

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "src" / "xerscope" / "app" / "streamlit_app.py")


@pytest.fixture(scope="module")
def context(store):
    snapshot = store.latest
    tasks = branch_tasks(snapshot, None, hide_loe=False)
    nodes = tree(snapshot)
    return tools.Context(store, snapshot, tasks.assign(category=categorise(tasks)), nodes, query.vocabulary(snapshot))


def chose(command, field, argument=""):
    """A model that always makes this choice; it records the messages it was sent."""

    def chat(messages, schema):
        chat.sent = (messages, schema)
        return {"command": command, "field": field, "argument": argument}

    return chat


# --- the answers: the engines' values, written by xerscope -----------------------------------


@pytest.mark.oracle("characterization")
def test_an_activity_slip_is_the_half_step_reading_of_that_activity(context):
    said = agent.answer("why did C3010 move", context, "en", chose("activity_slip", "total_shift_wd", "C3010"))
    truth = activity_half_step(context.previous, context.snapshot, "C3010").total_shift_wd
    assert not said.refused and said.values["total_shift_wd"] == round(truth, 2)
    assert said.sentence.startswith("Finish moved by") and f"{round(truth, 2)}" in said.sentence


@pytest.mark.oracle("characterization")
def test_the_project_move_and_the_longest_path_are_the_engines(context):
    week = half_step(context.previous, context.snapshot)
    said = agent.answer("project finish?", context, "en", chose("project_slip", "slip_wd"))
    assert said.values["slip_wd"] == round(week.slip_wd, 2)
    churn = path_churn(context.store)
    row = churn[churn["data_date"] == context.snapshot.data_date].iloc[0]
    said = agent.answer("how many on the longest path", context, "en", chose("path_changes", "on_path"))
    assert said.values["on_path"] == int(row["on_path"]) and str(int(row["on_path"])) in said.sentence


@pytest.mark.oracle("characterization")
def test_a_filter_reads_the_users_own_words_never_the_models(context):
    """The model rewrote the question ("in progress") and lost "civil works": the grammar reads the
    sentence asked, so the count is the page's own reading of it."""
    question = "how many civil works activities are in progress"
    said = agent.answer(question, context, "en", chose("filter", "count", "in progress"))
    ask = query.parse_keywords(question, context.vocab)
    truth = len(query.apply(ask, context.tasks, context.snapshot, context.nodes, None).rows)
    assert said.argument == question and said.values["count"] == truth


@pytest.mark.oracle("characterization")
def test_an_activity_is_found_by_the_words_of_its_name_accents_folded(context):
    said = agent.answer(
        "which activity is the earthworks", context, "en", chose("find_activity", "task_code", "Earthworks")
    )
    assert said.values["task_code"] == "C3020" and "C3020" in said.sentence


def test_a_command_chosen_with_no_value_answers_its_main_value(context):
    """Seen with a real model: "combien de jalons..." came back as filter / none. The command is right
    and names no value: its first one, the count, is the answer."""
    said = agent.answer("how many milestones are not started", context, "en", chose("filter", "none"))
    assert not said.refused and said.field == "count"


def test_the_sentence_is_in_the_questions_language(context):
    said = agent.answer("fin du projet ?", context, "fr", chose("project_slip", "finish"))
    assert said.sentence.startswith("Fin:") and "depuis le" in said.sentence


# --- what is refused --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("choice", "reason"),
    [
        (("none", "none"), "cannot answer"),
        (("simulate", "count"), "no known command"),
        (("path_changes", "count"), "not a value of path_changes"),
        (("activity_slip", "total_shift_wd", "ZZ999"), "not an Activity ID"),
        (("activity_history", "finish", "C3010; drop table"), "not an Activity ID"),
    ],
)
def test_a_choice_outside_the_lists_or_the_file_gives_no_answer(context, choice, reason):
    said = agent.answer("anything", context, "en", chose(*choice))
    assert said.sentence == "" and reason in said.refused


def test_the_model_reads_the_commands_and_a_flat_closed_schema(context):
    chat = chose("none", "none")
    agent.answer("what if C3030 took 5 more days", context, "en", chat)
    messages, schema = chat.sent
    assert all(command in messages[0]["content"] for command in tools.FIELDS)
    assert schema["additionalProperties"] is False and set(schema["required"]) == {"command", "field", "argument"}
    assert schema["properties"]["command"]["enum"] == list(tools.FIELDS)
    assert "$ref" not in json.dumps(schema)  # a nested schema can be ignored by llama.cpp (issue 21228)


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
    assert client.complete([{"role": "user", "content": "q"}], agent.SCHEMA, url=url) == {"command": "none"}
    sent = _Server.received[0]
    assert sent["response_format"] == {"type": "json_object", "schema": agent.SCHEMA}
    assert sent["chat_template_kwargs"] == {"enable_thinking": False} and sent["temperature"] == 0


@pytest.mark.parametrize(
    ("status", "reply"),
    [(200, b"not json"), (200, b'{"choices": [{"message": {"content": "[1]"}}]}'), (302, b""), (500, b"")],
)
def test_a_bad_reply_or_a_redirect_is_an_error_never_followed(server, status, reply):
    _, url = server
    _Server.status, _Server.reply = status, reply
    with pytest.raises(client.ModelError):
        client.complete([], agent.SCHEMA, url=url)
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
