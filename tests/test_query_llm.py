"""analysis/query.py, the model backend: a llama.cpp server answers JSON; anything else falls back."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from xerscope.analysis import query
from xerscope.analysis.query import Filter, Vocabulary

VOCAB = Vocabulary(
    wbs={"1": "CIV · Civil works", "2": "ENG · Ingénierie"},
    codes={"c1": ("Zone", "B2", "north"), "c3": ("Phase", "P1", "")},
    resources={"r1": ("CREW", "Site crew")},
    words=frozenset({"earthworks"}),
)


class Server:
    """A fake llama.cpp server: ``reply`` is the JSON content the model answers, or a callable."""

    def __init__(self):
        self.reply = {}
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append((self.path, body))
                reply = outer.reply() if callable(outer.reply) else outer.reply
                content = reply if isinstance(reply, str) else json.dumps(reply)
                answer = json.dumps({"choices": [{"message": {"role": "assistant", "content": content}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(answer)

        self.http = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.http.server_port}"


@pytest.fixture
def server():
    s = Server()
    yield s
    s.http.shutdown()


def test_answer_becomes_a_filter_and_the_request_holds_labels_only(server):
    server.reply = {
        "wbs_id": "1",
        "status": ["Not started"],
        "float": ["Critical"],
        "code_ids": ["c1"],
        "resource_ids": ["r1"],
        "milestones": False,
        "loe": False,
        "search": "earthworks",
    }
    got = query.parse("critical not started civil works", VOCAB, backend=query.llm_backend(server.url))
    assert got == Filter(
        wbs_id="1",
        status=("Not started",),
        categories=("Critical",),
        code_type="Zone",
        code_ids=frozenset({"c1"}),
        resources=frozenset({"r1"}),
        search="earthworks",
        matched=(
            "WBS: CIV · Civil works",
            "Status: Not started",
            "Float: Critical",
            "Zone: B2",
            "Resource: CREW",
            "Search: earthworks",
        ),
        source="model",
    )
    path, body = server.requests[0]
    assert path == "/v1/chat/completions" and body["response_format"]["type"] == "json_schema"
    assert body["messages"][-1] == {"role": "user", "content": "critical not started civil works"}
    assert json.dumps(VOCAB.to_prompt(), ensure_ascii=False) in body["messages"][0]["content"]
    assert "earthworks" not in body["messages"][0]["content"]  # the file's words never leave the app


def test_invented_ids_and_mixed_code_types_are_dropped():
    answer = {
        "wbs_id": "9",
        "status": ["Done", "Complete"],
        "float": [],
        "code_ids": ["c1", "c3", "zz"],
        "resource_ids": ["nobody"],
        "milestones": True,
        "loe": "yes",
        "search": 3,
    }
    got = query.from_answer(answer, VOCAB)
    assert got.wbs_id is None and got.status == ("Complete",) and got.resources == frozenset()
    assert got.code_type == "Zone" and got.code_ids == frozenset({"c1"})  # first kept id, sorted, sets the type
    assert got.milestones and got.loe and got.search == "" and got.source == "model"


@pytest.mark.parametrize("reply", ["not json", "[1, 2]", lambda: time.sleep(2) or {}])
def test_bad_or_slow_answers_fall_back_on_the_grammar(server, reply):
    server.reply = reply
    got = query.parse("critical", VOCAB, backend=query.llm_backend(server.url, timeout=0.5))
    assert got.categories == ("Critical",) and got.source == "keywords"


def test_only_http_urls():
    with pytest.raises(ValueError):
        query.llm_backend("file:///etc/passwd")


def test_server_down_falls_back():
    got = query.parse("critical", VOCAB, backend=query.llm_backend("http://127.0.0.1:9"))
    assert got.source == "keywords" and got.categories == ("Critical",)
