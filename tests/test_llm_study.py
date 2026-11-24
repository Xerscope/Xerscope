"""scripts/llm_study.py: the checker, the truths on the demo series, the loopback guard.

No server and no network: the model call is a stub that answers from the case it is given.
The truths are read from xerscope's own tables (the "characterization" values come from the demo
series of ``xerscope sample``), checked beside a value recomputed from the history where one exists.
"""

import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

import llm_study as study  # noqa: E402

GIVEN = '[{"data_date":"2026-10-19","finish":"2026-12-18","slip_wd":-2.0}] A1020'


# --- the checker ----------------------------------------------------------------------------


@pytest.mark.oracle("property")
def test_a_date_or_an_id_does_not_leak_numbers():
    """2026-10-19 is one date and A1020 one ID: neither gives the numbers 2026, -10, -19 or 1020."""
    values = study.extract_values("A1020 finished on 2026-10-19, 3 days after CIV-1010 and 2.5 after P2030.")
    assert values.ids == {"A1020", "CIV-1010", "P2030"}
    assert values.dates == {"2026-10-19"}
    assert values.numbers == (3.0, 2.5)


@pytest.mark.oracle("property")
def test_a_unicode_minus_is_a_minus():
    assert study.extract_values("it moved by −2 working days").numbers == (-2.0,)


@pytest.mark.oracle("property")
def test_invented_values_are_those_outside_what_the_model_was_given():
    reply = "A1020 and B9999 finish on 2026-12-18 or 2026-12-19, moved by 2 and 7 days."
    assert study.invented_values(reply, GIVEN, is_number_checked=True) == ["B9999", "2026-12-19", "7"]


@pytest.mark.oracle("property")
def test_a_number_is_compared_without_its_sign_and_unchecked_in_raw_mode():
    assert study.invented_values("2", GIVEN, is_number_checked=True) == []  # -2.0 is given: a sign slip is not invented
    assert study.invented_values("it is 41 days", GIVEN, is_number_checked=False) == []  # raw: the model computes it
    assert study.invented_values("Z1 is 2026-01-01", GIVEN, is_number_checked=False) == ["Z1", "2026-01-01"]


@pytest.mark.oracle("property")
@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("It finishes on 2026-12-18.", True),
        ("It finishes on 2026-12-17.", False),  # one day off is wrong: a date has no tolerance
        ("Finish: 2026-12-18T16:00", True),  # the date is read inside a datetime
        ("No date given.", False),
    ],
)
def test_a_date_is_correct_only_when_written_exactly(reply, expected):
    assert study.is_correct(reply, "2026-12-18", tolerance=0) is expected


@pytest.mark.oracle("property")
@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("-2", True),
        ("-2.5", True),  # boundary: truth - tolerance, included
        ("-1.5", True),  # boundary: truth + tolerance, included
        ("-2.51", False),
        ("-1.49", False),
        ("2", False),  # the sign is part of the answer
        ("slipped by 3 days", False),
    ],
)
def test_a_number_is_correct_within_the_tolerance_of_its_unit(reply, expected):
    assert study.is_correct(reply, -2.0, tolerance=0.5) is expected


# --- the truths on the demo series ------------------------------------------------------------


@pytest.fixture(scope="module")
def cases(store):
    return study.build_cases(store, study.load_questions(), activity_count=2, max_rows=400)


def case_of(cases, question_id, activity=None):
    return next(c for c in cases if c.question.id == question_id and c.activity == activity)


@pytest.mark.oracle("property")
def test_the_studied_activities_are_open_in_the_latest_update_and_the_tightest_first(store):
    codes = study.studied_activities(store, 3)
    latest = store.history[store.history["snapshot_idx"] == len(store) - 1].set_index("task_code")
    assert not latest.loc[codes, "is_complete"].any()
    assert latest.loc[codes, "total_float_d"].is_monotonic_increasing


@pytest.mark.oracle("characterization")
def test_the_slip_truth_is_the_per_activity_analysis_of_the_demo(store, cases):
    """P2030 progresses slowly on the demo (sample.py): its latest week moves its finish 2 working days later."""
    assert study.studied_activities(store, 1) == ["P2030"]
    assert case_of(cases, "activity_slip_by_progress", 1).truth == -2.0


@pytest.mark.oracle("property")
def test_the_history_truth_is_the_finish_stored_in_the_first_update(store, cases):
    first = store.history[store.history["snapshot_idx"] == 0].set_index("task_code")["finish"]
    for rank, code in enumerate(study.studied_activities(store, 2), start=1):
        assert case_of(cases, "finish_in_first_update", rank).truth == f"{first[code]:%Y-%m-%d}"


@pytest.mark.oracle("property")
def test_the_project_finish_truth_is_the_latest_finish_of_any_activity(store, cases):
    latest = store.history[store.history["snapshot_idx"] == len(store) - 1]
    assert case_of(cases, "project_finish").truth == f"{latest['finish'].max():%Y-%m-%d}"


@pytest.mark.oracle("property")
def test_the_path_truth_counts_the_open_activities_flagged_on_the_longest_path(store, cases):
    latest = store.history[store.history["snapshot_idx"] == len(store) - 1]
    on_path = int((latest["on_longest_path"] & ~latest["is_complete"]).sum())
    assert case_of(cases, "activities_on_longest_path").truth == on_path


@pytest.mark.oracle("property")
def test_a_question_without_an_activity_is_asked_once_and_one_with_it_per_activity(cases):
    ranks = {c.question.id: [] for c in cases}
    for case in cases:
        ranks[case.question.id].append(case.activity)
    assert ranks["activity_slip_by_progress"] == [1, 2]
    assert ranks["project_finish"] == [None]


@pytest.mark.oracle("property")
def test_the_raw_series_is_cut_at_max_rows_and_says_how_many_it_sent(store):
    csv, sent, total = study.raw_series(store, ["data_date", "task_code", "finish"], max_rows=10)
    assert (sent, total) == (10, len(store.history))
    assert csv.splitlines()[0] == "data_date,task_code,finish"
    assert len(csv.splitlines()) == 11 and csv.splitlines()[1].startswith(
        "2026-08-31,"
    )  # ISO days, oldest update first


@pytest.mark.oracle("property")
def test_a_question_with_no_value_on_its_date_is_skipped(store, capsys):
    absent = study.Question(
        "x", "{task_code} {date}", "activity", "slip_wd", "first", 0, "d", ["data_date", "task_code"]
    )
    assert (
        study.build_cases(store, [absent], activity_count=1, max_rows=5) == []
    )  # the series has no row for the first update
    assert "skipped x" in capsys.readouterr().err


# --- a run with a stubbed model ---------------------------------------------------------------


def stub_reply(text, latency_s=1.0, prompt_tokens=100, tokens_per_s=50.0):
    return study.Reply(text, latency_s, prompt_tokens, tokens_per_s)


def truthful(cases):
    """A model that knows every truth: it answers the case whose question text it was asked."""
    by_text = {c.text: c for c in cases}

    def ask(prompt):
        case = by_text[prompt.rsplit("Question: ", 1)[1]]
        return stub_reply(f"The answer is {case.truth}.")

    return ask


@pytest.mark.oracle("property")
def test_a_model_that_reads_every_truth_is_always_correct_and_invents_nothing(cases):
    results = study.run_study(cases, truthful(cases))
    assert len(results) == 2 * len(cases)
    assert all(result.is_correct and not result.invented for result in results)


@pytest.mark.oracle("property")
def test_a_wrong_date_and_an_unknown_id_are_counted_per_mode(cases):
    results = study.run_study(cases, lambda prompt: stub_reply("Z9999 finishes on 1999-01-01 after 12345 days."))
    assert not any(result.is_correct for result in results)
    assert all(
        result.invented == ["Z9999", "1999-01-01"] + (["12345"] if result.mode == "grounded" else [])
        for result in results
    )


@pytest.mark.oracle("property")
def test_the_report_has_a_row_per_mode_and_names_nothing_of_the_series(store, cases):
    results = study.run_study(cases, truthful(cases))
    report = study.render_report("model-q4.gguf", store, results)
    assert "| grounded | 7 | 100% | 0% | 1.0 | 100 | 50.0 |" in report
    assert "| raw | 7 | 100% | 0% | 1.0 | 100 | 50.0 |" in report
    names = set(store.history["task_code"]) | set(store.history["task_name"]) | {store.latest.project_code}
    assert not [name for name in names if name in report]
    assert "raw rows sent" in report and "236 of 236" in report


@pytest.mark.oracle("property")
def test_a_server_without_timings_reports_no_speed(store, cases):
    results = study.run_study(cases, lambda prompt: stub_reply("0", tokens_per_s=None))
    assert "| n/a |" in study.render_report("m", store, results)


@pytest.mark.oracle("property")
def test_main_runs_the_study_on_a_data_folder_and_writes_the_report(sample_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(study, "model_caller", lambda url, max_tokens: lambda prompt: stub_reply("0"))
    monkeypatch.setattr(study, "model_name", lambda url: "stub.gguf")
    out = tmp_path / "report.md"
    assert study.main(["--url", "http://127.0.0.1:8080", "--data", str(sample_dir), "--out", str(out)]) == 0
    assert "stub.gguf" in out.read_text(encoding="utf-8")


# --- the loopback guard -----------------------------------------------------------------------


@pytest.mark.oracle("property")
@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:8080", "http://localhost:8080", "http://[::1]:8080", "https://localhost"]
)
def test_a_loopback_url_is_accepted(url):
    assert study.is_loopback_url(url)


@pytest.mark.oracle("property")
@pytest.mark.parametrize(
    "url",
    [
        "https://10.0.0.1",
        "http://localhost.example.com:8080",  # a longer name that starts with localhost
        "http://127.0.0.1.example.com",
        "http://127.0.0.1@example.com",  # 127.0.0.1 is the userinfo, the host is example.com
        "http://127.0.0.2:8080",  # decision: only the three names; 127.0.0.0/8 is not accepted
        "http://0.0.0.0:8080",
        "ftp://127.0.0.1",
        "file:///etc/passwd",
        "127.0.0.1:8080",  # no scheme
        "",
    ],
)
def test_any_other_url_is_refused(url):
    assert not study.is_loopback_url(url)


@pytest.mark.oracle("property")
def test_main_refuses_an_external_url_before_any_call(monkeypatch, tmp_path, capsys):
    def no_call(*args):
        raise AssertionError("the model must not be called")

    monkeypatch.setattr(study, "model_caller", no_call)
    monkeypatch.setattr(study, "_fetch_json", no_call)
    with pytest.raises(SystemExit) as stopped:
        study.main(["--url", "https://10.0.0.1", "--out", str(tmp_path / "r.md")])
    assert stopped.value.code == 2
    assert "127.0.0.1, ::1, localhost" in capsys.readouterr().err  # the message names the allowed hosts
    assert not (tmp_path / "r.md").exists()


@pytest.mark.oracle("property")
def test_a_redirect_is_not_followed_and_the_environment_proxy_is_not_used():
    handler = study._NoRedirect()
    request = urllib.request.Request("http://127.0.0.1:8080/v1/models")
    assert handler.redirect_request(request, None, 302, "Found", {}, "http://example.com/") is None
    # urllib adds a ProxyHandler from HTTP_PROXY unless one is given; an empty one has no *_open method and is not kept
    assert not [h for h in study._OPENER.handlers if isinstance(h, urllib.request.ProxyHandler)]
