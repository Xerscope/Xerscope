"""The Gantt Ask field's local agent (src/xerscope/agent, app/agent_panel.py).

The model is replaced by a fixed reply (``chose``): what is checked is what xerscope does with a choice.
The answers are read on a two-update series small enough to compute by hand (``series``); every value
expected below is that hand computation, never a call to the engines the agent runs.
"""

import ast
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from conftest import read_folder
from streamlit.testing.v1 import AppTest
from xerkit import active, hours, snap, todo

from xerscope import agent
from xerscope.agent import client, tools
from xerscope.store import SnapshotStore

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "src" / "xerscope" / "app" / "streamlit_app.py")
WEEK_LATER = "2026-03-09 08:00"


@pytest.fixture(scope="module")
def context():
    """C8 calendar (Mon-Fri, 8 h a day). A (40 h) then B (40 h), FS; D (40 h left, under way) alone.
    Codes: A and D "GC", B "EL". Earlier update: status date Monday 2 March; later: Monday 9 March,
    nothing progressed.

    Later update, by hand: A Mon 9 - Fri 13, B Mon 16 - Fri 20 17:00 (the project finish), D Mon 9 -
    Fri 13. B moved from Fri 13 to Fri 20: -5 working days, all at the progress step, driven by A. The
    longest path is A, B in both updates (2 open, none entered). Total float, as P6 writes it in the
    file and the view reads it: A 0, B 0, D 40 h = 5 days (Fri 13 to Fri 20). A delayed 2 working days:
    B finishes Tue 24, the finish moves 2.0, A's float stays 0.
    """
    # the total float P6 writes in the file (hours), which the view reads: A 0, B 0, D 40 (5 days)
    tasks = [
        todo("A", total_float_hr_cnt="0", **hours(40)),
        todo("B", total_float_hr_cnt="0", **hours(40)),
        active("D", task_name="Coffrage voile", total_float_hr_cnt="40"),
    ]
    codes = [("A", "Discipline", "GC"), ("D", "Discipline", "GC"), ("B", "Discipline", "EL")]
    earlier = snap(tasks, [("A", "B", "FS", 0)], codes=codes)
    later = snap(tasks, [("A", "B", "FS", 0)], codes=codes, data_date=WEEK_LATER)
    store = SnapshotStore([earlier, later])
    return tools.context_for(store, store.latest)


def chose(**reply):
    """A model that always makes this choice; it records the messages it was sent."""

    def chat(messages, schema):
        chat.sent = (messages, schema)
        return reply

    return chat


def ask(context, question, lang="en", **reply):
    return agent.answer(question, context, lang, chose(**reply))


# --- the answers, against the hand computation of ``context`` -------------------------------------


@pytest.mark.oracle("standard")
def test_an_activity_slip_says_the_move_and_the_driver(context):
    said = ask(context, "why did B move", command="activity_slip", field="total_shift_wd", activity_id="B")
    assert said.values["total_shift_wd"] == -5.0 and said.values["driving_predecessors"] == "A"
    assert said.sentence == "Finish moved by (working days, later is negative): -5.0 (since 2026-03-02)"
    assert said.codes == ("B",)


@pytest.mark.oracle("standard")
def test_the_project_move_and_the_longest_path(context):
    said = ask(context, "project finish?", command="project_slip", field="slip_wd")
    assert (said.values["finish"], said.values["slip_wd"], said.values["replanning_wd"]) == ("2026-03-20", -5.0, 0.0)
    said = ask(context, "on the longest path", command="path_changes", field="on_path")
    assert (said.values["on_path"], said.values["entered"], said.values["left_open"]) == (2, 0, 0)


@pytest.mark.oracle("standard")
def test_a_query_counts_lists_and_names_what_the_gantt_draws(context):
    conditions = [{"column": "code: Discipline", "op": "=", "value": "GC"}]
    said = ask(
        context, "which GC activities", command="query", field="list", conditions=conditions, sort_by="activity_id"
    )
    assert said.values["count"] == 2 and said.values["list"] == ["A", "D"] and set(said.codes) == {"A", "D"}
    assert said.sentence == "Activities: A, D (code: Discipline = GC)"
    said = ask(context, "how many per discipline", command="query", field="groups", group_by="code: Discipline")
    assert said.values["groups"] == {"GC": 2, "EL": 1}


@pytest.mark.oracle("standard")
def test_a_simulated_delay_moves_the_finish_and_says_the_float(context):
    said = ask(context, "what if A took 2 more days", "fr", command="simulate_delay", field="finish_move_wd",
               activity_id="A", days=2)  # fmt: skip
    assert (said.values["finish_before"], said.values["finish_after"]) == ("2026-03-20", "2026-03-24")
    assert said.values["finish_move_wd"] == 2.0 and said.values["float_after_d"] == 0.0
    assert (
        said.sentence == "La fin projet bougerait de (j ouvrés): 2.0 (fin 2026-03-20 → 2026-03-24, marge 0.0 → 0.0 j)"
    )


@pytest.mark.parametrize("field", ["none", "count", "total_shift_wd"])
def test_a_value_of_another_command_answers_the_commands_main_value(context, field):
    """Seen with a real model: path_changes asked with "count". Its main value answers, named."""
    said = ask(context, "on the longest path", command="path_changes", field=field)
    assert said.field == "on_path" and said.sentence == "Open activities on the longest path: 2"


def test_an_activity_id_written_as_a_condition_is_the_commands_activity(context):
    """Seen with a real model: simulate_delay with ``activity_id = A`` as a condition."""
    said = ask(context, "what if A took 2 more days", command="simulate_delay", field="finish_move_wd", days=2,
               conditions=[{"column": "activity_id", "op": "=", "value": "A"}])  # fmt: skip
    assert said.choice.argument == "A" and said.values["finish_move_wd"] == 2.0


def test_the_days_of_a_delay_left_out_are_the_one_number_of_the_question(context):
    """Seen with a real model (4 replies of 31): simulate_delay without days. One number in the
    question is the delay; none, or several, leaves the reply refused."""
    reply = {"command": "simulate_delay", "field": "finish_move_wd", "activity_id": "A"}
    assert ask(context, "what if A slips 2 days", **reply).values["finish_move_wd"] == 2.0
    assert "between 1 and" in ask(context, "what if A slips", **reply).refused
    assert "between 1 and" in ask(context, "A slips 2 or 3 days", **reply).refused


def test_a_number_is_read_from_its_text_and_must_be_the_questions(context):
    """Seen with a real model: "fmt(5)" for 5. Read as 5: A and B (float 0) under 5, D (float 5) not.
    A number the question does not hold is refused."""
    condition = {"column": "total_float_d", "op": "<", "value": "fmt(5)"}
    said = ask(context, "less than 5 days of float", command="query", field="count", conditions=[condition])
    assert said.values["count"] == 2 and said.choice.query.conditions[0].value == "5"
    said = ask(context, "little float", command="query", field="count", conditions=[condition])
    assert "not a number of the question" in said.refused


@pytest.mark.parametrize(
    ("op", "value", "kept"), [("=", "true", ["A", "B"]), ("!=", "oui", ["D"]), ("=", "false", ["D"])]
)
def test_a_flag_compared_to_yes_or_no_reads_as_true_or_false(context, op, value, kept):
    """Seen with a real model: "critical = true" on a flag. A and B are critical (float 0), D is not
    (float 5 days)."""
    condition = {"column": "critical", "op": op, "value": value}
    said = ask(context, "critical ones", command="query", field="list", conditions=[condition], sort_by="activity_id")
    assert said.values["list"] == kept


def test_a_fixed_value_is_searched_in_any_language(context):
    """Seen with a real model: "en cours" read as status contains "In progress": D only. The statuses
    are the model's words, not the question's, and are not refused as invented."""
    condition = {"column": "status", "op": "contains", "value": "In progress"}
    said = ask(context, "combien d'activités en cours", "fr", command="query", field="count", conditions=[condition])
    assert said.values["count"] == 1 and said.codes == ("D",)


@pytest.mark.oracle("standard")
def test_a_query_says_its_funnel_from_the_whole_update(context):
    """3 activities; Discipline = GC keeps A and D."""
    said = ask(context, "which GC activities", command="query", field="count",
               conditions=[{"column": "code: Discipline", "op": "=", "value": "GC"}])  # fmt: skip
    assert said.values["start"] == 3 and said.values["steps"] == [("code: Discipline = GC", 2)]


def test_the_reasoning_pass_is_handed_to_the_choice_and_kept(context):
    """With a reasoning pass, the model's notes go with the question to the choice, and the answer keeps
    them for the trace; without one, the question goes alone."""
    chat = chose(command="path_changes", field="on_path")
    said = agent.answer("on the path?", context, "en", chat, reason=lambda messages: "longest path count")
    assert chat.sent[0][1]["content"] == "on the path?\n\nYour notes on it: longest path count"
    assert said.reasoning == "longest path count"
    agent.answer("on the path?", context, "en", chat)
    assert chat.sent[0][1]["content"] == "on the path?"


def test_the_cascade_answers_with_the_fast_model_unless_it_gives_none(context, monkeypatch):
    """The fast model's choice answers when it can; refused (here: "none"), the main model is asked."""
    replies = {"http://llm-fast:8080": {"command": "none", "field": "none"}, None: {"command": "path_changes"}}
    asked = []

    def complete(messages, schema, url=None):
        asked.append(url)
        return replies[url]

    monkeypatch.setattr(client, "complete", complete)
    monkeypatch.setenv("XERSCOPE_LLM_FAST_URL", "http://llm-fast:8080")
    said = agent.answer("on the path?", context)
    assert asked == ["http://llm-fast:8080", None] and said.model == "main" and said.values["on_path"] == 2
    replies["http://llm-fast:8080"] = {"command": "path_changes", "field": "entered"}
    asked.clear()
    said = agent.answer("entered the path?", context)
    assert asked == ["http://llm-fast:8080"] and said.model == "fast" and said.values["entered"] == 0


def test_the_trace_names_each_step_of_the_answer(context):
    from xerscope.app.agent_panel import trace_lines

    said = ask(context, "which GC activities", command="query", field="count",
               conditions=[{"column": "code: Discipline", "op": "=", "value": "GC"}])  # fmt: skip
    assert trace_lines("which GC activities", said) == [
        "- **Question:** which GC activities",
        "- **Choice:** query · count",
        "- **Funnel:** 3 activities → 2 (code: Discipline = GC)",
        "- **Answer:** Activities: 2 (code: Discipline = GC)",
        f"- **Model:** main · {said.seconds:.1f} s",
    ]


# --- what is refused --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        ({"command": "none", "field": "none"}, "cannot answer"),
        ({"command": "invent", "field": "count"}, "no known command"),
        ({"command": "activity_slip", "field": "total_shift_wd", "activity_id": "ZZ999"}, "not an Activity ID"),
        ({"command": "simulate_delay", "field": "finish_move_wd", "activity_id": "A", "days": 0}, "between 1 and"),
        ({"command": "query", "field": "count",
          "conditions": [{"column": "code: Discipline", "op": "=", "value": "CVC"}]},
         "holds no value"),
        ({"command": "query", "field": "count",
          "conditions": [{"column": "activity_name", "op": "contains", "value": "pump"}]},
         "not a word of the question"),
        ({"command": "query", "field": "groups"}, "without a column to group by"),
    ],
)  # fmt: skip
def test_a_choice_outside_the_lists_the_file_or_the_question_gives_no_answer(context, reply, reason):
    said = ask(context, "how many activities are there", **reply)
    assert said.sentence == "" and reason in said.refused and said.codes == ()


def test_the_model_reads_the_files_columns_under_a_flat_closed_schema(context):
    chat = chose(command="none", field="none")
    agent.answer("anything", context, "en", chat)
    messages, schema = chat.sent
    prompt = messages[0]["content"]
    for command in ("query", "activity_slip", "simulate_delay", "none"):
        assert f"- {command} [" in prompt
    for column in ("status", "total_float_d", "code: Discipline", "finish_moved_wd"):
        assert f"- {column} (" in prompt
    assert schema["additionalProperties"] is False and "query" in schema["properties"]["command"]["enum"]
    assert "code: Discipline" in schema["properties"]["conditions"]["items"]["properties"]["column"]["enum"]
    assert "$ref" not in json.dumps(schema)  # a nested reference can be ignored by llama.cpp (issue 21228)
    assert "Coffrage" not in prompt  # no data: the names of the columns, never an activity


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


def test_the_reasoning_pass_asks_thinking_on_without_a_schema(server):
    _, url = server
    message = {"reasoning_content": "GC means the Discipline code", "content": ""}
    _Server.status, _Server.reply = 200, json.dumps({"choices": [{"message": message}]}).encode()
    assert client.think([{"role": "user", "content": "q"}], url) == "GC means the Discipline code"
    sent = _Server.received[0]
    assert "response_format" not in sent and sent["chat_template_kwargs"]["enable_thinking"] is True
    assert sent["chat_template_kwargs"]["reasoning_effort"] == "low" and sent["cache_prompt"] is True


def test_warming_reads_the_instructions_once_and_never_raises(server):
    _, url = server
    _Server.status, _Server.reply = 200, json.dumps({"choices": [{"message": {"content": ""}}]}).encode()
    assert client.warm([{"role": "system", "content": "instructions"}], url) is True
    assert _Server.received[0]["max_tokens"] == 1
    assert client.warm([], "http://127.0.0.1:1") is False  # nothing listens: no answer, no exception


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
    monkeypatch.setattr(client, "warm", lambda messages, url=None: True)  # no connection from a test
    at = read_folder(AppTest.from_file(APP, default_timeout=120).run())
    return at.switch_page("views/gantt.py").run()


def test_the_page_shows_the_agents_answer_when_the_grammar_reads_nothing(sample_dir, monkeypatch):
    monkeypatch.setattr(
        client,
        "complete",
        lambda messages, schema, url=None: {"command": "path_changes", "field": "on_path", "argument": ""},
    )
    at = _gantt(sample_dir, monkeypatch, on=True)
    at.text_input(key="gantt_ask").set_value("how many activities drive the end date right now").run()
    assert not at.exception
    card = " ".join(m.value for m in at.markdown)
    assert "Open activities on the longest path" in card
    assert any("local agent · path_changes · on_path" in c.value for c in at.caption)


def test_a_query_answer_is_what_the_gantt_draws(sample_dir, monkeypatch):
    """The agent's query keeps the activities whose name holds "earthworks": in the demo series, C3020
    (Earthworks) only, so the Gantt draws that task only."""
    conditions = [{"column": "activity_name", "op": "contains", "value": "earthworks"}]
    monkeypatch.setattr(
        client,
        "complete",
        lambda messages, schema, url=None: {"command": "query", "field": "list", "conditions": conditions},
    )
    at = _gantt(sample_dir, monkeypatch, on=True)
    at.text_input(key="gantt_ask").set_value("show me where the earthworks stand, the digging").run()
    assert not at.exception
    drawn = {row["code"] for row in json.loads(at.get("bidi_component")[0].proto.json)["rows"] if row["kind"] == "task"}
    assert drawn == {"C3020"}


def test_the_page_asks_no_model_when_the_agent_is_off_or_the_grammar_reads_all(sample_dir, monkeypatch):
    def fail(messages, schema, url=None):
        raise AssertionError("the model was asked")

    monkeypatch.setattr(client, "complete", fail)
    at = _gantt(sample_dir, monkeypatch, on=False)
    at.text_input(key="gantt_ask").set_value("how many activities drive the end date right now").run()
    assert not at.exception
    at = _gantt(sample_dir, monkeypatch, on=True)
    at.text_input(key="gantt_ask").set_value("critical not started").run()  # the grammar reads every word
    assert not at.exception and not any("local agent" in c.value for c in at.caption)


def test_an_unreachable_model_is_said_and_the_page_still_draws(sample_dir, monkeypatch):
    def down(messages, schema, url=None):
        raise client.ModelError("the local model did not answer (connection refused)")

    monkeypatch.setattr(client, "complete", down)
    at = _gantt(sample_dir, monkeypatch, on=True)
    at.text_input(key="gantt_ask").set_value("how many activities drive the end date right now").run()
    assert not at.exception and any("Local agent unavailable" in w.value for w in at.warning)
