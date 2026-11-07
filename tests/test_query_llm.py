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
    """A fake llama.cpp server: ``reply`` is the JSON content the model answers, or a callable.
    ``key`` set: a request without that bearer token gets 401, as llama-server's --api-key."""

    def __init__(self, key: str = "", tls: tuple[str, str] | None = None):
        self.reply = {}
        self.requests = []
        self.key = key
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append((self.path, body, self.headers.get("Authorization")))
                if outer.key and self.headers.get("Authorization") != f"Bearer {outer.key}":
                    self.send_response(401)
                    self.end_headers()
                    return
                reply = outer.reply() if callable(outer.reply) else outer.reply
                content = reply if isinstance(reply, str) else json.dumps(reply)
                if body.get("stream"):  # SSE, as llama-server streams: one delta per word
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    for word in content.split(" "):
                        delta = json.dumps({"choices": [{"delta": {"content": word + " "}}]})
                        self.wfile.write(f"data: {delta}\n\n".encode())
                    self.wfile.write(b"data: [DONE]\n\n")
                    return
                answer = json.dumps({"choices": [{"message": {"role": "assistant", "content": content}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(answer)

        self.http = HTTPServer(("127.0.0.1", 0), Handler)
        scheme = "http"
        if tls:
            import ssl

            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(*tls)
            self.http.socket = context.wrap_socket(self.http.socket, server_side=True)
            scheme = "https"
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.url = f"{scheme}://127.0.0.1:{self.http.server_port}"


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
    path, body, _ = server.requests[0]
    assert path == "/v1/chat/completions" and body["response_format"]["type"] == "json_schema"
    assert body["messages"][-1] == {"role": "user", "content": "critical not started civil works"}
    assert json.dumps(VOCAB.to_prompt(), ensure_ascii=False, sort_keys=True) in body["messages"][0]["content"]
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


def test_only_http_urls_and_tls_with_a_key_off_the_loopback():
    with pytest.raises(ValueError):
        query.llm_backend("file:///etc/passwd")
    with pytest.raises(ValueError):  # the deployment's link: TLS, pinned CA and key, or nothing
        query.llm_backend("http://172.28.0.20:8080", key="k")
    with pytest.raises(ValueError):
        query.llm_backend("https://172.28.0.20:8443", key="k")  # no CA
    with pytest.raises(ValueError):
        query.llm_backend("https://172.28.0.20:8443", cafile="ca.pem")  # no key
    assert callable(query.llm_backend("https://172.28.0.20:8443", cafile="ca.pem", key="k"))  # the CA is read later


def test_server_down_falls_back():
    got = query.parse("critical", VOCAB, backend=query.llm_backend("http://127.0.0.1:9"))
    assert got.source == "keywords" and got.categories == ("Critical",)


def test_key_sent_and_a_refused_key_falls_back():
    locked = Server(key="s3cret")
    try:
        locked.reply = {
            "wbs_id": "1",
            "status": [],
            "float": [],
            "code_ids": [],
            "resource_ids": [],
            "milestones": False,
            "loe": False,
            "search": "",
        }
        right = query.parse("civil", VOCAB, backend=query.llm_backend(locked.url, key="s3cret"))
        assert right.source == "model" and locked.requests[-1][2] == "Bearer s3cret"
        wrong = query.parse("critical", VOCAB, backend=query.llm_backend(locked.url, key="nope"))
        assert wrong.source == "keywords" and wrong.categories == ("Critical",)
    finally:
        locked.http.shutdown()


def _self_signed(tmp_path):
    import subprocess

    key, cert = tmp_path / "k.pem", tmp_path / "c.pem"
    subprocess.run(  # noqa: S603
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            key,
            "-out",
            cert,
            "-days",
            "2",
            "-subj",
            "/CN=127.0.0.1",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )
    return str(key), str(cert)


def test_tls_pinned_to_the_models_own_ca(tmp_path):
    pytest.importorskip("ssl")
    import shutil

    if not shutil.which("openssl"):
        pytest.skip("openssl missing")
    key, cert = _self_signed(tmp_path)
    secure = Server(tls=(cert, key))
    try:
        secure.reply = {
            "wbs_id": "1",
            "status": [],
            "float": [],
            "code_ids": [],
            "resource_ids": [],
            "milestones": False,
            "loe": False,
            "search": "",
        }
        pinned = query.parse("civil", VOCAB, backend=query.llm_backend(secure.url, cafile=cert))
        assert pinned.source == "model"
        unpinned = query.parse("civil", VOCAB, backend=query.llm_backend(secure.url))  # system CAs: refused
        assert unpinned.source == "keywords"
    finally:
        secure.http.shutdown()
    with pytest.raises(ValueError):
        query.llm_backend("http://127.0.0.1:1", cafile=cert)  # a CA needs https


def test_the_vocabulary_is_handed_over_once_and_every_request_reuses_the_prefix(server):
    server.reply = {
        "wbs_id": None,
        "status": [],
        "float": [],
        "code_ids": [],
        "resource_ids": [],
        "milestones": False,
        "loe": False,
        "search": "",
    }
    backend = query.llm_backend(server.url)
    assert query.warm(backend, VOCAB) is True and query.warm(None, VOCAB) is False
    query.parse("civil", VOCAB, backend=backend)
    warm_body, ask_body = server.requests[0][1], server.requests[1][1]
    assert warm_body["max_tokens"] == 1 and warm_body["cache_prompt"] is True and ask_body["cache_prompt"] is True
    # the static prefix is byte for byte the same, first in the prompt: what the server's KV cache keys on
    assert warm_body["messages"][0] == ask_body["messages"][0] and ask_body["messages"][1]["content"] == "civil"
    assert "earthworks" not in warm_body["messages"][0]["content"]  # the file's words never leave the app


def test_warm_against_a_server_down_is_false():
    assert query.warm(query.llm_backend("http://127.0.0.1:9"), VOCAB) is False


def test_facts_hold_values_only_and_a_summary_is_kept_only_when_grounded(store, server):
    from xerscope.analysis import wbs as wbs_tree
    from xerscope.viz import categorise

    snapshot = store.latest
    nodes = wbs_tree.tree(snapshot)
    tasks = snapshot.activities.assign(category=categorise(snapshot.activities))
    vocab = query.vocabulary(snapshot, nodes)
    asked = query.parse_keywords("critical not started in civil works", vocab)
    funnel = query.apply(asked, tasks, snapshot, nodes)
    given = query.facts(funnel, snapshot)
    assert given["count"] == len(funnel.rows) and given["steps"][0] == ["WBS CIV · Civil works", 8]
    assert given["rows"][0][0] == funnel.rows.sort_values("total_float_d").iloc[0]["task_code"]
    assert all(len(row) == 3 for row in given["rows"]) and len(given["rows"]) <= query.FACT_ROWS
    text = json.dumps(given)
    assert "Earthworks" not in text and "Foundations" not in text  # Activity IDs, floats and dates: no name
    worst, worst_float, worst_finish = given["rows"][0]
    good = (
        f"{given['count']} critical activities are not started in CIV; "
        f"{worst} ({worst_float:g} wd) finishes {worst_finish}."
    )
    assert query.grounded(good, given)
    assert query.grounded(
        good.replace(worst_finish, "/".join(reversed(worst_finish.split("-")))), given
    )  # a date rewritten
    assert not query.grounded("4 activities are late, the worst by -99 days.", given)  # invented numbers
    assert not query.grounded(f"{worst} drives Z9999.", given)  # an invented Activity ID
    server.reply = good
    backend = query.llm_backend(server.url)
    streamed = "".join(query.summary(backend, "critical not started in civil works", given)).strip()
    assert streamed == good
    body = server.requests[-1][1]
    assert body["stream"] is True and body["max_tokens"] == 60 and body["cache_prompt"] is True
    assert json.dumps(given, sort_keys=True) in body["messages"][1]["content"]
    assert "".join(query.summary(None, "x", given)) == ""  # no model: nothing


def test_a_summary_from_a_server_down_is_empty():
    assert "".join(query.summary(query.llm_backend("http://127.0.0.1:9"), "x", {"count": 1})) == ""
